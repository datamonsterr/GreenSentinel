"""Run the real deployment helper against an offline Railway CLI boundary."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts/railway_deploy_code.sh"
DEPLOYMENT = "deployment-under-test"

RAILWAY_STUB = """#!/usr/bin/env python3
import json, os, pathlib, sys, time
args = sys.argv[1:]
api_token = bool(os.environ.get('RAILWAY_API_TOKEN'))
project_token = bool(os.environ.get('RAILWAY_TOKEN'))
with open(os.environ['FAKE_CALLS'], 'a') as log:
    log.write(json.dumps({'args': args, 'api_token': api_token,
                          'project_token': project_token}) + '\\n')
if not (api_token or project_token):
    print('Not signed in.', file=sys.stderr)
    sys.exit(1)
scenario = json.loads(pathlib.Path(os.environ['FAKE_SCENARIO']).read_text())
# GQLClient::new_authorized selects project-access-token before account bearer.
if project_token and args[args.index('--environment') + 1] != scenario['project_environment']:
    print('Project token does not authorize this environment.', file=sys.stderr)
    sys.exit(1)
if args[0] == 'up':
    response = scenario['submission']
elif args[:2] == ['deployment', 'list']:
    counter = pathlib.Path(os.environ['FAKE_POLLS'])
    count = int(counter.read_text()) if counter.exists() else 0
    counter.write_text(str(count + 1))
    response = scenario['polls'][min(count, len(scenario['polls']) - 1)]
else:
    raise AssertionError(args)
if response.get('hang'):
    time.sleep(60)
sys.stdout.write(response.get('output', ''))
sys.exit(response.get('exit_code', 0))
"""


def status_response(status: object = "SUCCESS", deployment: str = DEPLOYMENT) -> dict:
    return {"output": json.dumps([{"id": deployment, "status": status}])}


def run_deploy(
    tmp_path: Path,
    *,
    polls: list[dict] | None = None,
    submission: dict | None = None,
    api_token: bool = True,
    project_token: bool = False,
    project_environment: str = "environment-test",
    attempts: int = 3,
) -> tuple[subprocess.CompletedProcess[str], list[dict]]:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    railway = fake_bin / "railway"
    railway.write_text(RAILWAY_STUB, encoding="utf-8")
    railway.chmod(0o755)
    (fake_bin / "python3").symlink_to(sys.executable)
    # Keep real timeout process-group termination, but shorten production waits.
    timeout = fake_bin / "timeout"
    timeout.write_text(
        '#!/bin/bash\nwhile [[ "$1" == --* ]]; do shift; done\nshift\nexec "$REAL_TIMEOUT" --signal=TERM 0.5s "$@"\n',
        encoding="utf-8",
    )
    timeout.chmod(0o755)
    scenario = tmp_path / "scenario.json"
    scenario.write_text(
        json.dumps(
            {
                "submission": submission
                if submission is not None
                else {
                    "output": json.dumps({"deploymentId": DEPLOYMENT}) + "\n",
                },
                "polls": polls if polls is not None else [status_response()],
                "project_environment": project_environment,
            }
        ),
        encoding="utf-8",
    )
    calls = tmp_path / "calls.jsonl"
    real_timeout = shutil.which("timeout")
    assert real_timeout, "GNU timeout is required by the deployment helper"
    # Do not inherit developer credentials or a cached Railway login.
    env = {
        "PATH": f"{fake_bin}{os.pathsep}{os.defpath}",
        "HOME": str(tmp_path),
        "TMPDIR": str(scratch),
        "REAL_TIMEOUT": real_timeout,
        "FAKE_SCENARIO": str(scenario),
        "FAKE_CALLS": str(calls),
        "FAKE_POLLS": str(tmp_path / "polls"),
        "RAILWAY_DEPLOY_ATTEMPTS": str(attempts),
        "RAILWAY_DEPLOY_SLEEP": "0",
    }
    if api_token:
        env["RAILWAY_API_TOKEN"] = "fake-account-token"
    if project_token:
        env["RAILWAY_TOKEN"] = "fake-project-token"
    result = subprocess.run(
        [
            real_timeout,
            "4s",
            "bash",
            str(SCRIPT),
            "--service",
            "service-test",
            "--project",
            "project-test",
            "--environment",
            "environment-test",
            "--message",
            "contract deploy",
        ],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=6,
    )
    recorded = [json.loads(line) for line in calls.read_text().splitlines()]
    assert list(scratch.iterdir()) == [], "helper leaked temporary files"
    return result, recorded


@pytest.mark.parametrize("api_token,project_token", [(True, False), (True, True), (False, True)])
def test_uses_one_supported_credential_for_upload_and_polling(tmp_path, api_token, project_token):
    result, calls = run_deploy(
        tmp_path,
        api_token=api_token,
        project_token=project_token,
        project_environment="other-environment" if api_token else "environment-test",
    )
    assert result.returncode == 0, result.stderr
    assert f"Deployment {DEPLOYMENT} reached SUCCESS." in result.stdout
    assert calls[0]["args"] == [
        "up",
        "--service",
        "service-test",
        "--project",
        "project-test",
        "--environment",
        "environment-test",
        "--detach",
        "--json",
        "-m",
        "contract deploy",
    ]
    assert calls[1]["args"] == [
        "deployment",
        "list",
        "--service",
        "service-test",
        "--project",
        "project-test",
        "--environment",
        "environment-test",
        "--json",
    ]
    assert len(calls) == 2
    assert all(call["api_token"] == api_token for call in calls)
    assert all(call["project_token"] == (project_token and not api_token) for call in calls)


def test_waits_for_uploaded_deployment_in_ndjson_output(tmp_path):
    result, calls = run_deploy(
        tmp_path,
        submission={
            "output": 'Uploading...\n{"event":"progress"}\n'
            + json.dumps({"result": {"deploymentId": DEPLOYMENT}})
            + "\n"
        },
        polls=[status_response("SUCCESS", "previous-deployment"), status_response("BUILDING"), status_response()],
    )
    assert result.returncode == 0, result.stderr
    assert len(calls) == 4


@pytest.mark.parametrize("status", ["FAILED", "CRASHED", "REMOVED", "SKIPPED"])
def test_stops_immediately_on_terminal_failure(tmp_path, status):
    result, calls = run_deploy(tmp_path, polls=[status_response(status), status_response()])
    assert result.returncode == 1
    assert f"ended in {status}" in result.stderr
    assert len(calls) == 2


@pytest.mark.parametrize("output", ["", "not-json", "{", "[]", "null"])
def test_recovers_from_malformed_or_missing_poll_output(tmp_path, output):
    result, calls = run_deploy(tmp_path, polls=[{"output": output}, status_response()])
    assert result.returncode == 0, result.stderr
    assert "Traceback" not in result.stderr
    assert len(calls) == 3


def test_retries_poll_command_failure(tmp_path):
    result, calls = run_deploy(tmp_path, polls=[{"exit_code": 1}, status_response()])
    assert result.returncode == 0, result.stderr
    assert len(calls) == 3


@pytest.mark.parametrize(
    "response",
    [
        {"output": "not-json"},
        {"exit_code": 1},
        {"output": "[]"},
        {"output": json.dumps([{"id": DEPLOYMENT}])},
        status_response("BUILDING"),
        status_response(None),
        status_response("UNKNOWN"),
        status_response("SUCCESS", "previous-deployment"),
    ],
)
def test_fails_after_poll_budget_without_target_success(tmp_path, response):
    result, calls = run_deploy(tmp_path, polls=[response], attempts=2)
    assert result.returncode == 1
    assert "did not reach SUCCESS within 2 attempts" in result.stderr
    assert len(calls) == 3


@pytest.mark.parametrize(
    "submission",
    [
        {"exit_code": 1},
        {"output": "not-json"},
        {"output": "{}"},
        {"hang": True},
    ],
)
def test_never_polls_an_unconfirmed_upload(tmp_path, submission):
    result, calls = run_deploy(tmp_path, submission=submission)
    assert result.returncode == 1
    assert len(calls) == 1
    assert "submission failed" in result.stderr or "no deployment ID" in result.stderr


def test_hung_poll_command_cannot_bypass_attempt_budget(tmp_path):
    result, calls = run_deploy(tmp_path, polls=[{"hang": True}], attempts=2)
    assert result.returncode == 1, result.stderr
    assert "did not reach SUCCESS within 2 attempts" in result.stderr
    assert len(calls) == 3

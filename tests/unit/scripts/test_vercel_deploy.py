"""Exercise deployment submission and completion at the command boundary."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
URL = "https://p063-contract.vercel.app"

VERCEL_STUB = """#!/usr/bin/env python3
import json, os, pathlib, sys
with open(os.environ['CALLS'], 'a') as log:
    log.write(json.dumps(['vercel', *sys.argv[1:]]) + '\\n')
counter = pathlib.Path(os.environ['ATTEMPTS'])
attempt = int(counter.read_text()) + 1 if counter.exists() else 1
counter.write_text(str(attempt))
mode = os.environ['SUBMISSION']
if mode == 'auth':
    print('Error: User not found.', file=sys.stderr)
    sys.exit(1)
if mode == 'network' or (mode == 'recover' and attempt == 1):
    print('Error: fetch failed', file=sys.stderr)
    sys.exit(1)
print('invalid-url' if mode == 'invalid' else 'https://p063-contract.vercel.app')
"""

PYTHON_STUB = """#!/usr/bin/env python3
import json, os, sys
with open(os.environ['CALLS'], 'a') as log:
    log.write(json.dumps(['python3', *sys.argv[1:]]) + '\\n')
if sys.argv[2] == 'check' and os.environ['PREFLIGHT'] == 'fail':
    print('Project scope mismatch.', file=sys.stderr)
    sys.exit(1)
if sys.argv[2] == 'wait' and os.environ['COMPLETION'] == 'fail':
    print('Deployment ended in ERROR.', file=sys.stderr)
    sys.exit(1)
print('dpl_contract')
"""


def run_deploy(tmp_path, submission="success", completion="ready", args=(), preflight="ready", api_url=None):
    for name, source in {
        "vercel": VERCEL_STUB,
        "python3": PYTHON_STUB,
        "sleep": "#!/bin/sh\nexit 0\n",
    }.items():
        executable = tmp_path / name
        executable.write_text(source.replace("#!/usr/bin/env python3", f"#!{sys.executable}"))
        executable.chmod(0o755)
    calls = tmp_path / "calls.jsonl"
    test_env = {
        **os.environ,
        "PATH": f"{tmp_path}{os.pathsep}{os.environ['PATH']}",
        "VERCEL_TOKEN": "fake-contract-token",
        "VERCEL_ORG_ID": "team_contract",
        "VERCEL_PROJECT_ID": "prj_contract",
        "SUBMISSION": submission,
        "COMPLETION": completion,
        "PREFLIGHT": preflight,
        "CALLS": str(calls),
        "ATTEMPTS": str(tmp_path / "attempts"),
    }
    if api_url:
        test_env["API_BASE_URL"] = api_url
        test_env["NEXT_PUBLIC_API_URL"] = api_url
    result = subprocess.run(
        ["bash", str(ROOT / "scripts/vercel_deploy.sh"), *args],
        cwd=ROOT,
        env=test_env,
        capture_output=True,
        text=True,
        timeout=10,
    )
    recorded = [json.loads(line) for line in calls.read_text().splitlines()]
    return result, recorded


@pytest.mark.parametrize("args", [(), ("--prod",)])
def test_deploy_waits_through_project_api_without_cli_user_lookup(tmp_path, args):
    result, calls = run_deploy(tmp_path, args=args)
    assert result.returncode == 0, result.stderr
    assert result.stdout == URL + "\n"
    assert Path(calls[0][1]).name == "vercel_project.py"
    assert calls[0][2:] == ["check"]
    assert calls[1] == [
        "vercel",
        "deploy",
        "--prebuilt",
        "--no-wait",
        "--archive=tgz",
        *args,
    ]
    assert Path(calls[2][1]).name == "vercel_project.py"
    assert calls[2][2:] == ["wait", URL]
    assert len(calls) == 3
    assert "fake-contract-token" not in json.dumps(calls)


def test_configured_preview_api_urls_are_forwarded_as_runtime_env(tmp_path):
    result, calls = run_deploy(tmp_path, api_url="https://api.preview.example")
    assert result.returncode == 0, result.stderr
    assert calls[1] == [
        "vercel",
        "deploy",
        "--prebuilt",
        "--no-wait",
        "--archive=tgz",
        "--env",
        "API_BASE_URL=https://api.preview.example",
        "--env",
        "NEXT_PUBLIC_API_URL=https://api.preview.example",
    ]


def test_transient_submission_error_retries_then_checks_exact_deployment(tmp_path):
    result, calls = run_deploy(tmp_path, submission="recover")
    assert result.returncode == 0, result.stderr
    assert result.stdout == URL + "\n"
    assert [call[0] for call in calls] == ["python3", "vercel", "vercel", "python3"]


@pytest.mark.parametrize("submission,attempts", [("network", 3), ("auth", 1)])
def test_submission_failure_never_runs_followup_or_reports_success(tmp_path, submission, attempts):
    result, calls = run_deploy(tmp_path, submission=submission)
    assert result.returncode != 0
    assert result.stdout == ""
    assert len(calls) == attempts + 1
    assert calls[0][2:] == ["check"]
    assert all(call[0] == "vercel" for call in calls[1:])
    expected = "fetch failed" if submission == "network" else "User not found."
    assert expected in result.stderr


def test_nonready_deployment_fails_without_emitting_url(tmp_path):
    result, calls = run_deploy(tmp_path, completion="fail")
    assert result.returncode != 0
    assert result.stdout == ""
    assert "Deployment ended in ERROR." in result.stderr
    assert len(calls) == 3


def test_invalid_submission_url_fails_before_followup(tmp_path):
    result, calls = run_deploy(tmp_path, submission="invalid")
    assert result.returncode != 0
    assert result.stdout == ""
    assert len(calls) == 2


def test_project_scope_failure_stops_before_submission(tmp_path):
    result, calls = run_deploy(tmp_path, preflight="fail")
    assert result.returncode != 0
    assert result.stdout == ""
    assert len(calls) == 1
    assert calls[0][2:] == ["check"]
    assert "Project scope mismatch." in result.stderr

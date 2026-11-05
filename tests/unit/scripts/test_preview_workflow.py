"""Execute the preview rollout at its CLI boundary without deploying resources."""

import os
import subprocess

import pytest
import yaml

from tests.support.repo import REPO_ROOT

ROOT = REPO_ROOT

RAILWAY_STUB = """#!/usr/bin/env python3
import json, os, sys
args = sys.argv[1:]
if os.environ.get("RAILWAY_API_TOKEN") and os.environ.get("RAILWAY_TOKEN"):
    print("project token was not isolated", file=sys.stderr)
    sys.exit(1)
if os.environ.get("HOME") == os.environ.get("SHARED_RUNNER_HOME"):
    print("shared Railway config home was not isolated", file=sys.stderr)
    sys.exit(1)
for flag, expected in [("--project", "project-contract"),
                       ("--service", "service-contract"),
                       ("--environment", "pr-108")]:
    if flag not in args or args[args.index(flag) + 1] != expected:
        print("missing scope: " + flag + " " + expected, file=sys.stderr)
        sys.exit(1)
if args[0] == "up":
    mode = os.environ["FAKE_UPLOAD"]
    if mode == "fail":
        print(json.dumps({"error": "upload failed"}))
        sys.exit(1)
    if mode == "skip" or "--detach" not in args:
        print(json.dumps({"status": "success"}))
    else:
        print(json.dumps({"deploymentId": "submitted-deployment", "logsUrl": "https://railway.test/logs"}))
elif args[:2] == ["deployment", "list"]:
    print(json.dumps([
        {"id": "concurrent-deployment", "status": "SUCCESS"},
        {"id": "submitted-deployment", "status": os.environ["FAKE_STATUS"]}
    ]))
elif args[:2] == ["variable", "list"]:
    origin = "https://preview-contract.vercel.app" if os.environ.get("VARIABLE_READY") == "true" else "https://old-preview.vercel.app"
    print(json.dumps({"CLERK_AUTHORIZED_PARTIES": "https://green-sentinel-dev.vercel.app," + origin}))
"""


@pytest.mark.parametrize(
    ("upload", "status", "healthy", "expected_exit"),
    [
        ("success", "SUCCESS", "true", 0),
        ("success", "FAILED", "true", 1),
        ("success", "BUILDING", "true", 1),
        ("skip", "SUCCESS", "true", 1),
        ("fail", "SUCCESS", "true", 1),
        ("success", "SUCCESS", "false", 1),
    ],
)
def test_preview_requires_scoped_submission_completion_and_health(tmp_path, upload, status, healthy, expected_exit):
    script = (ROOT / "scripts/authorize_preview.sh").read_text()

    stubs = {
        "railway": RAILWAY_STUB,
        "npm": "#!/bin/sh\nexit 0\n",
        "sleep": "#!/bin/sh\nexit 0\n",
        "curl": '#!/bin/sh\n[ "$HEALTH_READY" = true ]\n',
    }
    for name, contents in stubs.items():
        executable = tmp_path / name
        executable.write_text(contents)
        executable.chmod(0o755)
    environment = {
        **os.environ,
        "PATH": f"{tmp_path}{os.pathsep}{os.environ['PATH']}",
        "RAILWAY_PROJECT_ID": "project-contract",
        "RAILWAY_SERVICE_ID": "service-contract",
        "RAILWAY_API_TOKEN": "fake-account-token",
        "RAILWAY_TOKEN": "fake-project-token",
        "SHARED_RUNNER_HOME": os.environ.get("HOME", ""),
        "TARGET_ENV": "pr-108",
        "AUTH_ENV": "pr-108",
        "REUSE_DEPLOYMENT": "false",
        "PREVIEW_URL": "https://preview-contract.vercel.app",
        "BACKEND_URL": "https://backend-contract.example",
        "FAKE_UPLOAD": upload,
        "FAKE_STATUS": status,
        "HEALTH_READY": healthy,
        "VARIABLE_READY": "true",
    }
    result = subprocess.run(
        ["bash", "-e"],
        input=script,
        text=True,
        capture_output=True,
        cwd=ROOT,
        env=environment,
        timeout=30,
    )
    assert result.returncode == expected_exit, result.stdout + result.stderr
    assert ("healthy after authorization rollout" in result.stdout) == (expected_exit == 0)


def test_preview_refuses_deploy_when_exact_origin_has_not_propagated(tmp_path):
    script = (ROOT / "scripts/authorize_preview.sh").read_text()
    for name, contents in {
        "railway": RAILWAY_STUB,
        "sleep": "#!/bin/sh\nexit 0\n",
        "curl": "#!/bin/sh\nexit 0\n",
    }.items():
        executable = tmp_path / name
        executable.write_text(contents)
        executable.chmod(0o755)
    environment = {
        **os.environ,
        "PATH": f"{tmp_path}{os.pathsep}{os.environ['PATH']}",
        "RAILWAY_PROJECT_ID": "project-contract",
        "RAILWAY_SERVICE_ID": "service-contract",
        "RAILWAY_API_TOKEN": "fake-account-token",
        "RAILWAY_TOKEN": "fake-project-token",
        "TARGET_ENV": "pr-108",
        "AUTH_ENV": "pr-108",
        "PREVIEW_URL": "https://preview-contract.vercel.app",
        "BACKEND_URL": "https://backend-contract.example",
        "FAKE_UPLOAD": "success",
        "FAKE_STATUS": "SUCCESS",
        "VARIABLE_READY": "false",
    }
    result = subprocess.run(
        ["bash", "-e"], input=script, text=True, capture_output=True, cwd=ROOT, env=environment, timeout=30
    )
    assert result.returncode == 1
    assert "did not expose the exact preview origin" in result.stderr
    assert "deploymentId" not in result.stdout


@pytest.mark.parametrize(
    ("preview_url", "comment_exit"),
    [("https://backend-contract.example", 0), ("https://backend-contract.example", 1), ("", 0)],
)
def test_preview_comment_consumes_verified_output_without_railway_access(tmp_path, preview_url, comment_exit):
    workflow = yaml.safe_load((ROOT / ".github/workflows/deploy-railway.yml").read_text())
    step = next(
        step
        for step in workflow["jobs"]["deploy-pr-preview"]["steps"]
        if step.get("name") == "Comment Preview Link on Pull Request"
    )
    values = {
        "${{ github.event.pull_request.number }}": "117",
        "${{ github.event.pull_request.head.sha }}": "fixture-head",
        "${{ secrets.GITHUB_TOKEN }}": "github-test-secret",
        "${{ steps.railway-preview.outputs.railway_url }}": preview_url,
    }

    def render(text):
        for expression, value in values.items():
            text = text.replace(expression, value)
        return text

    calls = tmp_path / "unexpected_calls"
    comments = tmp_path / "gh_calls"
    summary = tmp_path / "summary"
    body = tmp_path / "railway_comment.txt"
    stubs = {
        "python3": '#!/bin/sh\nprintf "python3\\n" >> "$UNEXPECTED_CALLS"\nexit 97\n',
        "railway": '#!/bin/sh\nprintf "railway\\n" >> "$UNEXPECTED_CALLS"\nexit 98\n',
        "gh": '#!/bin/sh\nprintf "%s\\n" "$*" >> "$GH_CALLS"\nexit "$COMMENT_EXIT"\n',
    }
    for name, contents in stubs.items():
        stub = tmp_path / name
        stub.write_text(contents)
        stub.chmod(0o755)
    environment = {
        **os.environ,
        **{name: render(value) for name, value in step.get("env", {}).items()},
        "PATH": f"{tmp_path}{os.pathsep}{os.environ['PATH']}",
        "GITHUB_STEP_SUMMARY": str(summary),
        "UNEXPECTED_CALLS": str(calls),
        "GH_CALLS": str(comments),
        "COMMENT_EXIT": str(comment_exit),
    }
    script = render(step["run"]).replace("/tmp/railway_comment.txt", str(body))
    result = subprocess.run(
        ["bash", "-e", "-o", "pipefail"],
        input=script,
        text=True,
        capture_output=True,
        env=environment,
        cwd=ROOT,
        timeout=10,
    )
    assert not calls.exists(), "Comment step must consume the provisioned output without querying Railway"
    if preview_url:
        assert result.returncode == 0, result.stdout + result.stderr
        assert "Railway Backend Preview Deployed" in summary.read_text()
        assert "`pr-117`" in summary.read_text()
        assert f"Backend API URL:** {preview_url}" in summary.read_text()
        assert f"Health Endpoint:** {preview_url}/health" in summary.read_text()
        assert body.read_text() == summary.read_text()
        assert comments.read_text() == f"pr comment 117 --body-file {body}\n"
    else:
        assert result.returncode != 0
        assert not summary.exists()
        assert not body.exists()
        assert not comments.exists()

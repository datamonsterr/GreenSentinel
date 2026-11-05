import json
import subprocess

import pytest


def _responses(status="FAILED", logs=None, log_code=0):

    calls = []

    def run(args, **kwargs):
        calls.append(args)
        if len(calls) == 1:
            return subprocess.CompletedProcess(args, 0, '{"deploymentId":"dep-1"}', "")
        if len(calls) == 2:
            return subprocess.CompletedProcess(args, 0, json.dumps([{"id": "dep-1", "status": status}]), "")
        return subprocess.CompletedProcess(args, log_code, logs or "", "log fetch failed")

    return calls, run


def test_failed_deployment_includes_bounded_sanitized_logs(monkeypatch):
    from scripts import railway_pr

    monkeypatch.setenv("DATABASE_PASSWORD", "super-secret")
    calls, run = _responses(logs="build failed DATABASE_PASSWORD=super-secret https://u:p@example.test/x")
    monkeypatch.setattr(railway_pr.subprocess, "run", run)

    with pytest.raises(RuntimeError) as exc:
        railway_pr.deploy_service("svc", "project", "pr-279", 279)

    message = str(exc.value)
    assert "ended in FAILED" in message
    assert "build failed" in message
    assert "super-secret" not in message
    assert "u:p@" not in message
    assert calls[2][0:4] == ["railway", "logs", "dep-1", "--build"]
    assert "--build" in calls[2] and "--lines" in calls[2] and "100" in calls[2]
    assert calls[3][:4] == ["railway", "logs", "dep-1", "--deployment"]


def test_failed_log_fetch_preserves_original_failure(monkeypatch):
    from scripts import railway_pr

    calls, run = _responses(logs="", log_code=1)
    monkeypatch.setattr(railway_pr.subprocess, "run", run)

    with pytest.raises(RuntimeError, match=r"Railway deployment dep-1 ended in FAILED"):
        railway_pr.deploy_service("svc", "project", "pr-279", 279)


def test_diagnostic_timeouts_keep_original_failure(monkeypatch):
    from scripts import railway_pr

    calls, underlying = _responses()

    def run(args, **kwargs):
        if args[1] == "logs":
            assert kwargs["timeout"] == 30
            raise subprocess.TimeoutExpired(args, 30)
        return underlying(args, **kwargs)

    monkeypatch.setattr(railway_pr.subprocess, "run", run)
    with pytest.raises(RuntimeError, match="ended in FAILED") as exc:
        railway_pr.deploy_service("svc", "project", "pr-279", 279)
    assert "TimeoutExpired" in str(exc.value)


def test_diagnostic_logs_redact_database_credentials(monkeypatch):
    from scripts import railway_pr

    database_url = "postgresql://user:database-canary@database.test/db"
    monkeypatch.setenv("DEV_DATABASE_URL", database_url)
    detail = railway_pr._sanitize_deployment_logs(database_url + " postgresql://u:other-canary@db.test/db")
    assert "database-canary" not in detail
    assert "other-canary" not in detail

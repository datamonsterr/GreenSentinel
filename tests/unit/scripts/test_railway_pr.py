import subprocess

import pytest


def test_preview_failure_diagnostics_uses_latest_deployment_and_redacts(monkeypatch):
    from scripts import railway_pr

    monkeypatch.setenv("DATABASE_URL", "postgresql://user:secret@db.example/app")
    calls = []

    def run(args, **kwargs):
        calls.append((args, kwargs))
        return subprocess.CompletedProcess(args, 0, "DATABASE_URL=postgresql://user:secret@db.example/app", "")

    monkeypatch.setattr(railway_pr.subprocess, "run", run)
    result = railway_pr.preview_failure_diagnostics("svc", "project", "pr-340")

    assert "secret" not in result
    assert calls[0][0] == [
        "railway",
        "logs",
        "--deployment",
        "--lines",
        "100",
        "--service",
        "svc",
        "--project",
        "project",
        "--environment",
        "pr-340",
    ]
    assert calls[0][1]["timeout"] == 30


def test_preview_failure_diagnostics_preserves_health_failure_on_timeout(monkeypatch):
    from scripts import railway_pr

    def run(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], kwargs["timeout"])

    monkeypatch.setattr(railway_pr.subprocess, "run", run)

    assert railway_pr.preview_failure_diagnostics("svc", "project", "pr-340") == (
        "(unable to retrieve preview logs: TimeoutExpired)"
    )


class _SentinelStopError(Exception):
    pass


def test_setup_pr_adopts_environment_when_appearing_on_second_poll(monkeypatch, capsys):
    from scripts import railway_pr

    env_responses = [
        [],
        [],
        [{"id": "env-adopted-99", "name": "pr-99"}],
    ]

    def mock_get_environments(project_id):
        return env_responses.pop(0)

    def mock_create_pr_environment(project_id, pr_number, source_env_id):
        raise RuntimeError("Railway API returned 1 GraphQL error(s): UNKNOWN: Problem processing request")

    def mock_stop(*args, **kwargs):
        raise _SentinelStopError()

    sleep_calls = []

    monkeypatch.setattr(railway_pr, "get_environments", mock_get_environments)
    monkeypatch.setattr(railway_pr, "create_pr_environment", mock_create_pr_environment)
    monkeypatch.setattr(railway_pr, "get_service_domain", mock_stop)

    with pytest.raises(_SentinelStopError):
        railway_pr.setup_pr(
            99,
            "proj-1",
            "svc-1",
            "dev-1",
            sleep=sleep_calls.append,
        )

    assert sleep_calls == [10, 10]
    assert len(env_responses) == 0
    captured = capsys.readouterr()
    assert "[WARN] Failed to create environment:" in captured.err
    assert "[+] Adopted environment created despite API error: env-adopted-99" in captured.out


def test_setup_pr_raises_original_error_when_environment_never_appears(monkeypatch, capsys):
    from scripts import railway_pr

    original_err = "Railway API returned 1 GraphQL error(s): UNKNOWN: Problem processing request"

    def mock_get_environments(project_id):
        return []

    def mock_create_pr_environment(project_id, pr_number, source_env_id):
        raise RuntimeError(original_err)

    def mock_stop(*args, **kwargs):
        raise _SentinelStopError()

    sleep_calls = []

    monkeypatch.setattr(railway_pr, "get_environments", mock_get_environments)
    monkeypatch.setattr(railway_pr, "create_pr_environment", mock_create_pr_environment)
    monkeypatch.setattr(railway_pr, "get_service_domain", mock_stop)

    with pytest.raises(RuntimeError, match="UNKNOWN: Problem processing request") as exc_info:
        railway_pr.setup_pr(
            99,
            "proj-1",
            "svc-1",
            "dev-1",
            sleep=sleep_calls.append,
        )

    assert str(exc_info.value) == original_err
    assert sleep_calls == [10] * 6
    captured = capsys.readouterr()
    assert "[WARN] Failed to create environment:" in captured.err
    assert "Adopted environment" not in captured.out


def test_setup_pr_adopts_immediately_when_error_indicates_already_exists(monkeypatch, capsys):
    from scripts import railway_pr

    env_responses = [
        [],
        [{"id": "env-exists-99", "name": "pr-99"}],
    ]

    def mock_get_environments(project_id):
        return env_responses.pop(0)

    def mock_create_pr_environment(project_id, pr_number, source_env_id):
        raise RuntimeError("Railway API returned 1 GraphQL error(s): An environment with that name already exists")

    def mock_stop(*args, **kwargs):
        raise _SentinelStopError()

    sleep_calls = []

    monkeypatch.setattr(railway_pr, "get_environments", mock_get_environments)
    monkeypatch.setattr(railway_pr, "create_pr_environment", mock_create_pr_environment)
    monkeypatch.setattr(railway_pr, "get_service_domain", mock_stop)

    with pytest.raises(_SentinelStopError):
        railway_pr.setup_pr(
            99,
            "proj-1",
            "svc-1",
            "dev-1",
            sleep=sleep_calls.append,
        )

    assert sleep_calls == []
    assert len(env_responses) == 0
    captured = capsys.readouterr()
    assert "[WARN] Failed to create environment:" in captured.err
    assert "[+] Adopted environment created despite API error: env-exists-99" in captured.out

import json
import subprocess

import pytest

from scripts import railway_pr


def test_run_railway_api_reports_sanitized_graphql_error(monkeypatch):
    canary = "graphql-canary-token"
    payload = {
        "errors": [
            {
                "message": f"denied token={canary} https://railway.app/graphql?access_token={canary}",
                "extensions": {"code": "FORBIDDEN", "secret": canary},
            }
        ],
        "data": {"request": canary},
    }
    monkeypatch.setenv("RAILWAY_API_TOKEN", canary)
    monkeypatch.setattr(
        railway_pr.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 1, json.dumps(payload), "railway api failed"),
    )

    with pytest.raises(RuntimeError, match=r"FORBIDDEN") as exc_info:
        railway_pr.run_railway_api("mutation", {"token": canary, "id": "request-canary"})

    detail = str(exc_info.value)
    assert canary not in detail
    assert "request-canary" not in detail
    assert "data" not in detail
    assert "headers" not in detail


def test_run_railway_api_uses_generic_message_without_stdout(monkeypatch):
    monkeypatch.setattr(
        railway_pr.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 1, "", "generic secret failure"),
    )

    with pytest.raises(RuntimeError, match="Railway API request failed"):
        railway_pr.run_railway_api("mutation")


def test_run_railway_api_non_json_stdout_redacted_with_http_429(monkeypatch):
    canary = "canary-secret-token"
    monkeypatch.setenv("RAILWAY_API_TOKEN", canary)
    sleep_calls = []
    output = f"Railway API returned HTTP 429: Too Many Requests; token={canary} https://api.railway.app?secret={canary}"
    monkeypatch.setattr(
        railway_pr.subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args[0], 1, output, ""),
    )

    with pytest.raises(RuntimeError) as exc_info:
        railway_pr.run_railway_api("query { me }", {"key": canary}, sleep=sleep_calls.append)

    err = str(exc_info.value)
    assert "Railway API returned a non-JSON error response:" in err
    assert "HTTP 429" in err
    assert canary not in err
    assert "[REDACTED]" in err


def test_run_railway_api_retries_transient_rate_limit_then_succeeds(monkeypatch, capsys):
    calls = []

    def fake_run(cmd, *args, **kwargs):
        calls.append(cmd)
        if len(calls) == 1:
            return subprocess.CompletedProcess(cmd, 1, "Rate limited ... You are being ratelimited.", "")
        return subprocess.CompletedProcess(cmd, 0, json.dumps({"data": {"status": "ok"}}), "")

    sleep_calls = []
    monkeypatch.setattr(railway_pr.subprocess, "run", fake_run)

    result = railway_pr.run_railway_api("query { test }", sleep=sleep_calls.append)

    assert result == {"data": {"status": "ok"}}
    assert len(calls) == 2
    assert sleep_calls == [15]
    captured = capsys.readouterr()
    assert "[!] Railway API transient error (attempt 1/4):" in captured.err
    assert "retrying in 15s" in captured.err


def test_run_railway_api_no_retry_on_json_graphql_error(monkeypatch):
    payload = {"errors": [{"message": "Rate limited in GraphQL", "extensions": {"code": "FORBIDDEN"}}]}
    calls = []

    def fake_run(cmd, *args, **kwargs):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 1, json.dumps(payload), "")

    sleep_calls = []
    monkeypatch.setattr(railway_pr.subprocess, "run", fake_run)

    with pytest.raises(RuntimeError, match=r"FORBIDDEN"):
        railway_pr.run_railway_api("query { test }", sleep=sleep_calls.append)

    assert len(calls) == 1
    assert len(sleep_calls) == 0


def test_run_railway_api_gives_up_after_4_attempts(monkeypatch, capsys):
    calls = []

    def fake_run(cmd, *args, **kwargs):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 1, "Railway API returned HTTP 502 Bad Gateway", "")

    sleep_calls = []
    monkeypatch.setattr(railway_pr.subprocess, "run", fake_run)

    with pytest.raises(RuntimeError, match="non-JSON error response"):
        railway_pr.run_railway_api("query { test }", sleep=sleep_calls.append)

    assert len(calls) == 4
    assert sleep_calls == [15, 30, 60]
    captured = capsys.readouterr()
    assert "(attempt 1/4)" in captured.err
    assert "(attempt 2/4)" in captured.err
    assert "(attempt 3/4)" in captured.err
    assert "(attempt 4/4)" not in captured.err


def test_run_railway_api_parses_try_again_in_seconds(monkeypatch, capsys):
    calls = []

    def fake_run(cmd, *args, **kwargs):
        calls.append(cmd)
        if len(calls) == 1:
            return subprocess.CompletedProcess(
                cmd,
                1,
                "Rate limited ... You are being ratelimited. Try again in about 30 seconds.",
                "",
            )
        return subprocess.CompletedProcess(cmd, 0, json.dumps({"data": {"id": 123}}), "")

    sleep_calls = []
    monkeypatch.setattr(railway_pr.subprocess, "run", fake_run)

    result = railway_pr.run_railway_api("query { test }", sleep=sleep_calls.append)

    assert result == {"data": {"id": 123}}
    assert len(calls) == 2
    assert sleep_calls == [30]
    captured = capsys.readouterr()
    assert "retrying in 30s" in captured.err


def test_run_railway_api_parses_try_again_in_minutes_and_caps(monkeypatch):
    calls = []

    def fake_run(cmd, *args, **kwargs):
        calls.append(cmd)
        if len(calls) == 1:
            return subprocess.CompletedProcess(
                cmd,
                1,
                "Rate limited. Try again in about 3 minutes.",
                "",
            )
        return subprocess.CompletedProcess(cmd, 0, json.dumps({"data": {"ok": True}}), "")

    sleep_calls = []
    monkeypatch.setattr(railway_pr.subprocess, "run", fake_run)

    result = railway_pr.run_railway_api("query { test }", sleep=sleep_calls.append)
    assert result == {"data": {"ok": True}}
    assert sleep_calls == [120]


def test_run_railway_api_environment_create_mutation_safety(monkeypatch):
    query = """
    mutation createEnv($input: EnvironmentCreateInput!) {
      environmentCreate(input: $input) {
        id
      }
    }
    """
    calls_500 = []
    monkeypatch.setattr(
        railway_pr.subprocess,
        "run",
        lambda cmd, *args, **kwargs: (
            calls_500.append(cmd)
            or subprocess.CompletedProcess(cmd, 1, "Railway API returned HTTP 500 Internal Server Error", "")
        ),
    )
    sleep_calls = []
    with pytest.raises(RuntimeError):
        railway_pr.run_railway_api(query, sleep=sleep_calls.append)
    assert len(calls_500) == 1
    assert len(sleep_calls) == 0

    calls_429 = []

    def fake_run_429(cmd, *args, **kwargs):
        calls_429.append(cmd)
        if len(calls_429) == 1:
            return subprocess.CompletedProcess(cmd, 1, "Railway API returned HTTP 429: Too Many Requests", "")
        return subprocess.CompletedProcess(cmd, 0, json.dumps({"data": {"id": "env-1"}}), "")

    monkeypatch.setattr(railway_pr.subprocess, "run", fake_run_429)
    result = railway_pr.run_railway_api(query, sleep=sleep_calls.append)
    assert result == {"data": {"id": "env-1"}}
    assert len(calls_429) == 2
    assert sleep_calls == [15]

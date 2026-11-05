"""Exercise the staging workflow without network, database, or Redis access."""

import io
import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path
from urllib.error import HTTPError, URLError

import pytest
import yaml

from scripts import staging_smoke

ROOT = Path(__file__).resolve().parents[2]


def test_staging_smoke_step_checks_remote_contract_and_exits(tmp_path):
    """A healthy remote API must finish without entering the local simulator."""
    workflow = yaml.safe_load((ROOT / ".github/workflows/deploy-railway.yml").read_text())
    step = next(step for step in workflow["jobs"]["deploy-staging"]["steps"] if "Smoke Test" in step.get("name", ""))
    calls = tmp_path / "requests.txt"
    launcher = tmp_path / "python3"
    launcher.write_text(
        f"#!{sys.executable}\n"
        + textwrap.dedent(
            """\
            import io
            import os
            import runpy
            import sys
            from urllib.error import HTTPError
            import urllib.request

            if sys.argv[1] != "scripts/staging_smoke.py":
                sys.exit("Staging smoke entered the local trip simulator instead of probing the API")

            def urlopen(request, *, timeout):
                url = request.full_url
                assert request.get_method() == "GET"
                assert not request.has_header("Authorization")
                assert not request.has_header("Cookie")
                assert 0 < timeout <= 20
                with open(os.environ["SMOKE_CALLS"], "a") as calls:
                    calls.write(url + "\\n")
                if url == "https://staging.example/health":
                    response = io.BytesIO(b'{"status":"ok","database":"connected","env":"staging"}')
                    response.status = 200
                    return response
                assert url == "https://staging.example/api/v1/account/settings"
                raise HTTPError(url, 401, "Unauthorized", {}, io.BytesIO(b'{"detail":"Clerk session required"}'))

            urllib.request.urlopen = urlopen
            sys.argv = sys.argv[1:]
            runpy.run_path(sys.argv[0], run_name="__main__")
            """
        )
    )
    launcher.chmod(0o755)
    # Let the old shell reach its simulator call without touching a real API.
    curl = tmp_path / "curl"
    curl.write_text('#!/bin/sh\ncase "$*" in *account/settings*) printf 401;; esac\n')
    curl.chmod(0o755)

    result = subprocess.run(
        ["bash", "-e", "-o", "pipefail", "-c", step["run"]],
        cwd=ROOT,
        env={
            **os.environ,
            "PATH": f"{tmp_path}:{os.environ['PATH']}",
            "STAGING_API_URL": "https://staging.example/",
            "SMOKE_CALLS": str(calls),
        },
        capture_output=True,
        text=True,
        timeout=5,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert calls.read_text().splitlines() == [
        "https://staging.example/health",
        "https://staging.example/api/v1/account/settings",
    ]


HEALTH = (200, b'{"status":"ok","database":"connected","env":"staging"}')
ACCOUNT = (401, b'{"detail":"Clerk session required"}')


def mock_api(monkeypatch, *, health=HEALTH, account=ACCOUNT):
    """Replace only HTTP and sleep; keep contract parsing and CLI behavior real."""
    calls = []
    sleeps = []

    def urlopen(request, *, timeout):
        calls.append((request, timeout))
        result = health if request.full_url.endswith("/health") else account
        if isinstance(result, Exception):
            raise result
        status, body = result
        if status >= 400:
            raise HTTPError(request.full_url, status, "Error", {}, io.BytesIO(body))
        response = io.BytesIO(body)
        response.status = status
        return response

    monkeypatch.setattr(staging_smoke, "urlopen", urlopen)
    monkeypatch.setattr(staging_smoke.time, "sleep", sleeps.append)
    return calls, sleeps


def test_smoke_uses_only_two_unauthenticated_gets_with_request_timeouts(monkeypatch):
    calls, sleeps = mock_api(monkeypatch)

    staging_smoke.run_smoke("https://staging.example/")

    assert [request.full_url for request, _ in calls] == [
        "https://staging.example/health",
        "https://staging.example/api/v1/account/settings",
    ]
    for request, timeout in calls:
        assert request.get_method() == "GET"
        assert request.data is None
        assert request.header_items() == [("Accept", "application/json")]
        assert timeout == 10
    assert sleeps == []


@pytest.mark.parametrize(
    "health",
    [
        (503, HEALTH[1]),
        (200, b"<html>not JSON</html>"),
        (200, b"[]"),
        (200, b"null"),
        (200, b"{}"),
        *[
            (200, json.dumps(payload).encode())
            for payload in (
                {"status": "degraded", "database": "connected", "env": "staging"},
                {"status": "ok", "database": "disconnected", "env": "staging"},
                {"status": "ok", "env": "staging"},
                {"status": "ok", "database": "connected"},
                {"status": "ok", "database": "connected", "env": "test"},
                {"status": "ok", "database": "connected", "env": "dev"},
                {"status": "ok", "database": "connected", "env": "production"},
            )
        ],
        URLError("connection refused"),
        TimeoutError("request timed out"),
    ],
)
def test_unready_health_fails_after_bounded_retries_without_checking_account(monkeypatch, health):
    calls, sleeps = mock_api(monkeypatch, health=health)

    with pytest.raises(staging_smoke.StagingSmokeError, match="health contract failed after 12 attempts"):
        staging_smoke.run_smoke("https://staging.example")

    assert len(calls) == 12
    assert all(request.full_url == "https://staging.example/health" for request, _ in calls)
    assert sleeps == [5] * 11


def test_health_can_recover_before_the_retry_limit(monkeypatch):
    calls, sleeps = mock_api(monkeypatch)
    transport = staging_smoke.urlopen
    attempts = 0

    def warming_up(request, *, timeout):
        nonlocal attempts
        attempts += 1
        if attempts <= 2:
            raise URLError("starting")
        return transport(request, timeout=timeout)

    monkeypatch.setattr(staging_smoke, "urlopen", warming_up)

    staging_smoke.run_smoke("https://staging.example")

    assert attempts == 4
    assert len(calls) == 2
    assert sleeps == [5, 5]


@pytest.mark.parametrize(
    "account",
    [
        (200, b'{"detail":"Clerk session required"}'),
        (200, b'{"id":"fixture-user"}'),
        (403, b'{"detail":"Forbidden"}'),
        (404, b'{"detail":"Not Found"}'),
        (500, b'{"detail":"Internal Server Error"}'),
        (401, b'{"detail":"unrelated unauthorized response"}'),
        (401, b"{}"),
        (401, b"[]"),
        (401, b"<html>Unauthorized</html>"),
        URLError("connection refused"),
        TimeoutError("request timed out"),
    ],
)
def test_account_contract_rejects_stale_routes_fixture_auth_and_wrong_401s(monkeypatch, account):
    calls, sleeps = mock_api(monkeypatch, account=account)

    with pytest.raises(staging_smoke.StagingSmokeError):
        staging_smoke.run_smoke("https://staging.example")

    assert len(calls) == 2
    assert sleeps == []


def test_cli_fails_nonzero_on_a_broken_contract(monkeypatch, capsys):
    mock_api(monkeypatch, account=(404, b'{"detail":"Not Found"}'))
    monkeypatch.setattr(sys, "argv", ["staging_smoke.py", "--api-url", "https://staging.example"])

    assert staging_smoke.main() == 1
    output = capsys.readouterr()
    assert "Staging smoke failed:" in output.err
    assert "HTTP 404" in output.err
    assert "passed" not in output.out


def test_cli_reports_contract_scope_without_a_trip_lifecycle_claim(monkeypatch, capsys):
    mock_api(monkeypatch)
    monkeypatch.setattr(sys, "argv", ["staging_smoke.py", "--api-url", "https://staging.example"])

    assert staging_smoke.main() == 0
    assert "synthetic trip lifecycle not exercised" in capsys.readouterr().out


@pytest.mark.parametrize("url", ["", "staging.example", "file:///tmp/health"])
def test_invalid_target_fails_before_any_request(monkeypatch, url):
    calls, sleeps = mock_api(monkeypatch)

    with pytest.raises(staging_smoke.StagingSmokeError, match="absolute HTTP"):
        staging_smoke.run_smoke(url)

    assert calls == []
    assert sleeps == []

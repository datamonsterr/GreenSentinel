"""Project-scoped Vercel deployment checks at the CLI and HTTP boundaries."""

import io
import json
from email.message import Message
from urllib.error import HTTPError, URLError
from urllib.request import HTTPSHandler, ProxyHandler
from urllib.request import build_opener as stdlib_build_opener
from urllib.response import addinfourl

import pytest

from scripts import vercel_project

SETTINGS = {"VERCEL_TOKEN": "test-secret", "VERCEL_ORG_ID": "team_example", "VERCEL_PROJECT_ID": "prj_example"}
READY = {"id": "dpl_example", "projectId": "prj_example", "readyState": "READY", "url": "preview.vercel.app"}


class APIResponse(io.BytesIO):
    status = 200


class VercelAPI:
    def __init__(self, *payloads):
        self.payloads = iter(payloads)
        self.requests = []

    def open(self, request, *, timeout):
        self.requests.append((request, timeout))
        response = next(self.payloads)
        if isinstance(response, Exception):
            raise response
        return APIResponse(response if isinstance(response, bytes) else json.dumps(response).encode())


class Clock:
    def __init__(self):
        self.elapsed = 0.0

    def monotonic(self):
        return self.elapsed

    def sleep(self, duration):
        self.elapsed += duration


@pytest.fixture(autouse=True)
def project_directory(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)


def test_wait_requires_token_without_contacting_vercel(monkeypatch, tmp_path, capsys):
    monkeypatch.chdir(tmp_path)
    assert vercel_project.main(["wait", "https://preview.vercel.app"], environ={}) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "VERCEL_TOKEN" in captured.err


def test_wait_verifies_ready_deployment_with_team_scoped_request(monkeypatch, tmp_path, capsys):
    monkeypatch.chdir(tmp_path)
    api = VercelAPI(READY)
    assert vercel_project.main(["wait", "https://preview.vercel.app"], environ=SETTINGS, opener=api) == 0
    request, timeout = api.requests[0]
    assert request.full_url == "https://api.vercel.com/v13/deployments/preview.vercel.app?teamId=team_example"
    assert request.get_method() == "GET"
    assert request.get_header("Authorization") == "Bearer test-secret"
    assert timeout <= 30
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize(
    ("project", "code"),
    [
        ({"id": "prj_example", "accountId": "team_example"}, 0),
        ({"id": "prj_other", "accountId": "team_example"}, 1),
        ({"id": "prj_example", "accountId": "team_other"}, 1),
        ({"id": "prj_example"}, 0),
    ],
)
def test_check_verifies_requested_project_and_owner(project, code, capsys):
    api = VercelAPI(project)
    assert vercel_project.main(["check"], environ=SETTINGS, opener=api) == code
    request, _ = api.requests[0]
    assert request.full_url == "https://api.vercel.com/v9/projects/prj_example?teamId=team_example"
    assert request.get_method() == "GET"
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize(
    "link",
    [
        {"orgId": "team_other", "projectId": "prj_example"},
        {"orgId": "team_example", "projectId": "prj_other"},
        {"orgId": "team_example"},
        ["not a project"],
        "invalid JSON",
    ],
)
def test_check_rejects_mismatched_or_invalid_local_project_before_api(tmp_path, link, capsys):
    folder = tmp_path / ".vercel"
    folder.mkdir()
    (folder / "project.json").write_text(link if isinstance(link, str) else json.dumps(link))
    api = VercelAPI({"id": "prj_example", "accountId": "team_example"})
    assert vercel_project.main(["check"], environ=SETTINGS, opener=api) == 1
    assert api.requests == []
    assert "project.json" in capsys.readouterr().err


def test_wait_polls_submitted_deployment_until_ready(capsys):
    api = VercelAPI({**READY, "readyState": "BUILDING"}, READY)
    clock = Clock()
    assert (
        vercel_project.main(
            ["wait", "https://preview.vercel.app"],
            environ=SETTINGS,
            opener=api,
            clock=clock.monotonic,
            sleep=clock.sleep,
        )
        == 0
    )
    assert clock.elapsed == 5
    assert [request.full_url for request, _ in api.requests] == [
        "https://api.vercel.com/v13/deployments/preview.vercel.app?teamId=team_example",
        "https://api.vercel.com/v13/deployments/preview.vercel.app?teamId=team_example",
    ]
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize(
    "payload",
    [
        {**READY, "projectId": "prj_other"},
        {key: value for key, value in READY.items() if key != "projectId"},
        {**READY, "project": {"id": "prj_other"}},
        {**READY, "readyState": "ERROR"},
        {**READY, "readyState": "CANCELED"},
        {**READY, "readyState": "BLOCKED"},
        {**READY, "readyState": "UNKNOWN"},
        {**READY, "readyState": {"test-secret": "READY"}},
        {**READY, "id": "../../other"},
        {**READY, "id": None},
        {**READY, "url": "other.vercel.app"},
    ],
)
def test_wait_rejects_failed_or_unverified_deployment(payload, capsys):
    api = VercelAPI(payload, READY)
    clock = Clock()
    assert (
        vercel_project.main(
            ["wait", "https://preview.vercel.app"],
            environ=SETTINGS,
            opener=api,
            clock=clock.monotonic,
            sleep=clock.sleep,
        )
        == 1
    )
    assert len(api.requests) == 1
    assert capsys.readouterr().out == ""


def test_wait_accepts_documented_nested_project_identity():
    payload = {key: value for key, value in READY.items() if key != "projectId"}
    api = VercelAPI({**payload, "project": {"id": "prj_example"}})
    assert vercel_project.main(["wait", "https://preview.vercel.app"], environ=SETTINGS, opener=api) == 0


def test_wait_timeout_bounds_polling_and_network_timeouts(capsys):
    api = VercelAPI(*[{**READY, "readyState": "BUILDING"}] * 120)
    clock = Clock()
    assert (
        vercel_project.main(
            ["wait", "https://preview.vercel.app"],
            environ=SETTINGS,
            opener=api,
            clock=clock.monotonic,
            sleep=clock.sleep,
        )
        == 1
    )
    assert clock.elapsed == 600
    assert len(api.requests) == 120
    assert api.requests[-1][1] == 5
    assert "Timed out" in capsys.readouterr().err


@pytest.mark.parametrize("returned_alias", ["green-sentinel-dev.vercel.app", "other.vercel.app", None])
def test_alias_uses_verified_deployment_id_and_confirms_alias(returned_alias, capsys):
    api = VercelAPI(READY, {"alias": returned_alias, "uid": "alias_example"})
    assert vercel_project.main(
        ["alias", "https://preview.vercel.app", "green-sentinel-dev.vercel.app"], environ=SETTINGS, opener=api
    ) == (0 if returned_alias == "green-sentinel-dev.vercel.app" else 1)
    request, _ = api.requests[1]
    assert request.full_url == "https://api.vercel.com/v2/deployments/dpl_example/aliases?teamId=team_example"
    assert request.get_method() == "POST"
    assert json.loads(request.data) == {"alias": "green-sentinel-dev.vercel.app"}
    assert request.get_header("Content-type") == "application/json"
    assert capsys.readouterr().out == ""


def test_alias_never_mutates_unverified_project(capsys):
    api = VercelAPI({**READY, "projectId": "prj_other"})
    assert (
        vercel_project.main(
            ["alias", "https://preview.vercel.app", "green-sentinel-dev.vercel.app"], environ=SETTINGS, opener=api
        )
        == 1
    )
    assert [request.get_method() for request, _ in api.requests] == ["GET"]
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize(
    "deployment",
    [
        "https://evil.example",
        "https://preview.vercel.app.evil.example",
        "https://user:password@preview.vercel.app",
        "http://preview.vercel.app",
        "https://preview.vercel.app:443",
        "https://preview.vercel.app/path",
        "https://preview.vercel.app?teamId=other",
        "https://preview.vercel.app#other",
        "https://preview.vercel.app\n",
        "https://preview\\.vercel.app",
        "https://[preview.vercel.app",
    ],
)
def test_wait_rejects_unsafe_deployment_references_before_api(deployment):
    api = VercelAPI(READY)
    assert vercel_project.main(["wait", deployment], environ=SETTINGS, opener=api) == 1
    assert api.requests == []


def test_wait_accepts_bare_deployment_hostname():
    api = VercelAPI(READY)
    assert vercel_project.main(["wait", "preview.vercel.app"], environ=SETTINGS, opener=api) == 0
    assert (
        api.requests[0][0].full_url == "https://api.vercel.com/v13/deployments/preview.vercel.app?teamId=team_example"
    )


@pytest.mark.parametrize(
    "domain",
    ["https://example.com", "example.com/path", "example.com?other", "x@a.com", "-bad.com", "a..com", "127.0.0.1"],
)
def test_alias_rejects_unsafe_domains_before_api(domain):
    api = VercelAPI(READY, {"alias": domain})
    assert vercel_project.main(["alias", "https://preview.vercel.app", "--", domain], environ=SETTINGS, opener=api) == 1
    assert api.requests == []


@pytest.mark.parametrize(
    ("name", "value"),
    [("VERCEL_TOKEN", "token\nsecret"), ("VERCEL_ORG_ID", "team/example"), ("VERCEL_PROJECT_ID", "prj?other")],
)
def test_check_rejects_invalid_credentials_without_leaking_values(name, value, capsys):
    api = VercelAPI({"id": "prj_example"})
    assert vercel_project.main(["check"], environ={**SETTINGS, name: value}, opener=api) == 1
    captured = capsys.readouterr()
    assert value not in captured.out + captured.err
    assert api.requests == []


@pytest.mark.parametrize("timeout", ["0", "-1", "nan", "inf"])
def test_wait_rejects_unbounded_or_invalid_timeout_before_api(timeout):
    api = VercelAPI(READY)
    assert vercel_project.main(["wait", "preview.vercel.app", "--timeout", timeout], environ=SETTINGS, opener=api) == 1
    assert api.requests == []


def http_failure(status):
    return HTTPError("https://api.vercel.com/redacted", status, "test-secret", {}, io.BytesIO(b"test-secret"))


@pytest.mark.parametrize("status", [401, 403, 404, 422])
def test_wait_fails_on_permanent_http_errors_without_leaking_body(status, capsys):
    api = VercelAPI(http_failure(status), READY)
    assert vercel_project.main(["wait", "preview.vercel.app"], environ=SETTINGS, opener=api) == 1
    captured = capsys.readouterr()
    assert str(status) in captured.err
    assert "test-secret" not in captured.out + captured.err
    assert len(api.requests) == 1


@pytest.mark.parametrize(
    "failure",
    [
        http_failure(429),
        http_failure(500),
        http_failure(502),
        http_failure(503),
        URLError("test-secret"),
        TimeoutError("test-secret"),
    ],
)
def test_wait_retries_transient_get_failures_within_deadline(failure, capsys):
    api = VercelAPI(failure, READY)
    clock = Clock()
    assert (
        vercel_project.main(
            ["wait", "preview.vercel.app"], environ=SETTINGS, opener=api, clock=clock.monotonic, sleep=clock.sleep
        )
        == 0
    )
    assert clock.elapsed == 5
    assert len(api.requests) == 2
    captured = capsys.readouterr()
    assert "test-secret" not in captured.out + captured.err


@pytest.mark.parametrize("failure", [http_failure(500), URLError("test-secret")])
def test_alias_never_blindly_retries_failed_mutation(failure, capsys):
    api = VercelAPI(READY, failure, {"alias": "green-sentinel-dev.vercel.app"})
    assert (
        vercel_project.main(
            ["alias", "preview.vercel.app", "green-sentinel-dev.vercel.app"], environ=SETTINGS, opener=api
        )
        == 1
    )
    assert [request.get_method() for request, _ in api.requests] == ["GET", "POST"]
    captured = capsys.readouterr()
    assert "test-secret" not in captured.out + captured.err


@pytest.mark.parametrize(
    "response",
    [b"not JSON test-secret", b"\xff", b"x" * (1024 * 1024 + 1), [], None],
    ids=["invalid-json", "invalid-encoding", "oversize", "array", "null"],
)
def test_check_rejects_malformed_response_without_leaking_body(response, capsys):
    api = VercelAPI(response)
    assert vercel_project.main(["check"], environ=SETTINGS, opener=api) == 1
    captured = capsys.readouterr()
    assert "test-secret" not in captured.out + captured.err
    assert captured.out == ""


@pytest.mark.parametrize(
    ("aliases", "code"),
    [
        ({"aliases": [{"alias": "green-sentinel-dev.vercel.app", "uid": "alias_example"}]}, 0),
        ({"aliases": [{"alias": "other.vercel.app"}]}, 1),
        ({"aliases": []}, 1),
        ({"aliases": "green-sentinel-dev.vercel.app"}, 1),
    ],
)
def test_alias_conflict_succeeds_only_when_exact_deployment_owns_alias(aliases, code, capsys):
    api = VercelAPI(READY, http_failure(409), aliases)
    assert (
        vercel_project.main(
            ["alias", "preview.vercel.app", "green-sentinel-dev.vercel.app"], environ=SETTINGS, opener=api
        )
        == code
    )
    assert [request.get_method() for request, _ in api.requests] == ["GET", "POST", "GET"]
    assert (
        api.requests[-1][0].full_url == "https://api.vercel.com/v2/deployments/dpl_example/aliases?teamId=team_example"
    )
    captured = capsys.readouterr()
    assert "test-secret" not in captured.out + captured.err


def test_api_redirect_cannot_forward_token_to_another_host(monkeypatch, capsys):
    requests = []

    class HTTPSStub(HTTPSHandler):
        def https_open(self, request):
            requests.append(request)
            headers = Message()
            if request.host == "api.vercel.com":
                headers["Location"] = "https://foreign.example/leak"
                response = addinfourl(io.BytesIO(b"test-secret"), headers, request.full_url, 302)
            else:
                response = addinfourl(io.BytesIO(json.dumps(READY).encode()), headers, request.full_url, 200)
            response.msg = "test-secret"
            return response

    monkeypatch.setattr(
        vercel_project, "build_opener", lambda *handlers: stdlib_build_opener(ProxyHandler({}), HTTPSStub(), *handlers)
    )
    assert vercel_project.main(["wait", "preview.vercel.app"], environ=SETTINGS) == 1
    assert [request.host for request in requests] == ["api.vercel.com"]
    captured = capsys.readouterr()
    assert "302" in captured.err
    assert "test-secret" not in captured.out + captured.err


def test_wait_does_not_accept_ready_response_after_deadline(capsys):
    clock = Clock()

    class SlowVercelAPI(VercelAPI):
        def open(self, request, *, timeout):
            clock.elapsed += 6
            return super().open(request, timeout=timeout)

    api = SlowVercelAPI(READY)
    assert (
        vercel_project.main(
            ["wait", "preview.vercel.app", "--timeout", "5"],
            environ=SETTINGS,
            opener=api,
            clock=clock.monotonic,
            sleep=clock.sleep,
        )
        == 1
    )
    assert api.requests[0][1] == 5
    assert "Timed out" in capsys.readouterr().err

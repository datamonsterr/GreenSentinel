"""Deployment routing and protection policy at the GitHub CLI boundary."""

import io
import json
import os
import subprocess
import sys
from email.message import Message
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import HTTPSHandler, ProxyHandler
from urllib.request import build_opener as stdlib_build_opener
from urllib.response import addinfourl

import pytest

from scripts import deployment_policy

ROOT = Path(__file__).resolve().parents[3]


class GitHubResponse(io.BytesIO):
    status = 200

    def __init__(self, payload, link=""):
        super().__init__(payload if isinstance(payload, bytes) else json.dumps(payload).encode())
        self.headers = {"Link": link}


class GitHubAPI:
    def __init__(self, *pages):
        self.pages = iter(pages)
        self.requests = []

    def open(self, request, *, timeout):
        self.requests.append((request, timeout))
        page = next(self.pages)
        if isinstance(page, Exception):
            raise page
        payload, link = page
        return GitHubResponse(payload, link)


def missing_gh(*args, **kwargs):
    raise FileNotFoundError("gh unavailable")


@pytest.fixture
def github_rest(monkeypatch):
    monkeypatch.setenv("GITHUB_REPOSITORY", "org/repo")
    monkeypatch.setenv("GH_TOKEN", "test-secret")
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.setattr(deployment_policy.subprocess, "run", missing_gh)


def test_missing_gh_classifies_backend_from_authenticated_second_page(monkeypatch, github_rest):
    api = GitHubAPI(
        (
            [{"filename": "docs/README.md"}],
            '<https://api.github.com/repos/org/repo/pulls/115/files?per_page=100&page=2>; rel="next"',
        ),
        ([{"filename": "src/api/routes.py"}], ""),
    )
    monkeypatch.setattr(deployment_policy, "build_opener", lambda *handlers: api, raising=False)
    assert deployment_policy.classify(115) == {"backend": True, "frontend": True}
    assert [request.full_url for request, _ in api.requests] == [
        "https://api.github.com/repos/org/repo/pulls/115/files?per_page=100",
        "https://api.github.com/repos/org/repo/pulls/115/files?per_page=100&page=2",
    ]
    assert all(request.get_header("Authorization") == "Bearer test-secret" for request, _ in api.requests)


def test_missing_gh_follows_canonical_link_on_original_trusted_repository(monkeypatch, github_rest):
    api = GitHubAPI(
        (
            [{"filename": "docs/README.md"}],
            '<https://api.github.com/repositories/1364255456/pulls/115/files?per_page=100&page=2>; rel="next"',
        ),
        ([{"filename": "src/api/routes.py"}], ""),
    )
    monkeypatch.setattr(deployment_policy, "build_opener", lambda *handlers: api)
    assert deployment_policy.classify(115) == {"backend": True, "frontend": True}
    assert api.requests[-1][0].full_url == "https://api.github.com/repos/org/repo/pulls/115/files?per_page=100&page=2"


@pytest.mark.parametrize(
    "query",
    [
        "per_page=100&page=0",
        "per_page=100&page=secret",
        "per_page=100&page=2&page=3",
        "per_page=99&page=2",
        "per_page=100&page=2&other=secret",
    ],
)
def test_canonical_pagination_rejects_invalid_page_query_before_http(monkeypatch, github_rest, query):
    api = GitHubAPI(
        (
            [{"filename": "docs/README.md"}],
            f'<https://api.github.com/repositories/1364255456/pulls/115/files?{query}>; rel="next"',
        ),
        ([{"filename": "src/api/routes.py"}], ""),
    )
    monkeypatch.setattr(deployment_policy, "build_opener", lambda *handlers: api)
    with pytest.raises(RuntimeError, match="pagination"):
        deployment_policy.classify(115)
    assert len(api.requests) == 1


def test_missing_gh_requires_token_before_http(monkeypatch, github_rest):
    monkeypatch.delenv("GH_TOKEN")
    api = GitHubAPI()
    monkeypatch.setattr(deployment_policy, "build_opener", lambda *handlers: api)
    with pytest.raises(RuntimeError, match="GH_TOKEN or GITHUB_TOKEN"):
        deployment_policy.classify(115)
    assert api.requests == []


def test_missing_gh_rejects_invalid_token_before_http(monkeypatch, github_rest):
    monkeypatch.setenv("GH_TOKEN", "token\nsecret")
    api = GitHubAPI(([], ""))
    monkeypatch.setattr(deployment_policy, "build_opener", lambda *handlers: api)
    with pytest.raises(RuntimeError, match="token") as error:
        deployment_policy.classify(115)
    assert "token\nsecret" not in str(error.value)
    assert api.requests == []


def test_present_gh_failure_does_not_fallback_to_rest(monkeypatch, github_rest):
    def failed_gh(*args, **kwargs):
        raise subprocess.CalledProcessError(1, args[0], stderr="authentication failed")

    monkeypatch.setattr(deployment_policy.subprocess, "run", failed_gh)
    api = GitHubAPI()
    monkeypatch.setattr(deployment_policy, "build_opener", lambda *handlers: api)
    with pytest.raises(subprocess.CalledProcessError):
        deployment_policy.classify(115)
    assert api.requests == []


def test_missing_gh_environment_check_uses_plain_rest_object(monkeypatch, github_rest):
    monkeypatch.delenv("GH_TOKEN")
    monkeypatch.setenv("GITHUB_TOKEN", "github-test-secret")
    api = GitHubAPI(({"protection_rules": [{"type": "required_reviewers", "reviewers": [{"id": 1}]}]}, ""))
    monkeypatch.setattr(deployment_policy, "build_opener", lambda *handlers: api)
    deployment_policy.check_environment("staging")
    assert api.requests[0][0].full_url == "https://api.github.com/repos/org/repo/environments/staging"
    assert api.requests[0][0].get_header("Authorization") == "Bearer github-test-secret"


@pytest.mark.parametrize(
    "url",
    [
        "https://foreign.example/repos/org/repo/pulls/115/files?page=2",
        "http://api.github.com/repos/org/repo/pulls/115/files?page=2",
        "https://api.github.com/repos/other/repo/pulls/115/files?page=2",
        "https://user@api.github.com/repos/org/repo/pulls/115/files?page=2",
        "https://api.github.com:443/repos/org/repo/pulls/115/files?page=2",
        "https://api.github.com/repos/org/repo/pulls/115/files?page=2#fragment",
        "https://api.github.com/repos/org/repo/pulls/116/files?page=2",
        "https://api.github.com/repos/org/repo/pulls/115/files?per_page=100",
    ],
)
def test_pagination_rejects_unsafe_or_repeated_url_before_sending_token(monkeypatch, github_rest, url):
    api = GitHubAPI(([{"filename": "docs/README.md"}], f'<{url}>; rel="next"'), ([], ""))
    monkeypatch.setattr(deployment_policy, "build_opener", lambda *handlers: api)
    with pytest.raises(RuntimeError, match="pagination"):
        deployment_policy.classify(115)
    assert len(api.requests) == 1


@pytest.mark.parametrize("repository", ["org/../repo", "../repo", "org/repo?other"])
def test_rest_requires_explicit_safe_repository(monkeypatch, github_rest, repository):
    monkeypatch.setenv("GITHUB_REPOSITORY", repository)
    api = GitHubAPI(([], ""))
    monkeypatch.setattr(deployment_policy, "build_opener", lambda *handlers: api)
    with pytest.raises(RuntimeError, match="GITHUB_REPOSITORY"):
        deployment_policy.classify(115)
    assert api.requests == []


@pytest.mark.parametrize(
    "failure",
    [
        HTTPError("https://api.github.com/redacted", 401, "test-secret", {}, io.BytesIO(b"test-secret")),
        HTTPError("https://api.github.com/redacted", 403, "test-secret", {}, io.BytesIO(b"test-secret")),
        URLError("test-secret"),
    ],
)
def test_rest_failure_rejects_without_logging_token_or_body(monkeypatch, github_rest, failure, capsys):
    api = GitHubAPI(failure)
    monkeypatch.setattr(deployment_policy, "build_opener", lambda *handlers: api)
    with pytest.raises(RuntimeError, match="GitHub API") as error:
        deployment_policy.classify(115)
    captured = capsys.readouterr()
    assert "test-secret" not in str(error.value) + captured.out + captured.err
    assert len(api.requests) == 1


def test_rest_invalid_json_rejects_without_logging_body(monkeypatch, github_rest, capsys):
    api = GitHubAPI((b"invalid JSON test-secret", ""))
    monkeypatch.setattr(deployment_policy, "build_opener", lambda *handlers: api)
    with pytest.raises(RuntimeError, match="GitHub API") as error:
        deployment_policy.classify(115)
    captured = capsys.readouterr()
    assert "test-secret" not in str(error.value) + captured.out + captured.err


def test_rest_redirect_cannot_forward_token_to_another_host(monkeypatch, github_rest):
    requests = []

    class HTTPSStub(HTTPSHandler):
        def https_open(self, request):
            requests.append(request)
            headers = Message()
            if request.host == "api.github.com":
                headers["Location"] = "https://foreign.example/leak"
                response = addinfourl(io.BytesIO(b"test-secret"), headers, request.full_url, 302)
            else:
                payload = [{"filename": "src/api/routes.py"}]
                response = addinfourl(io.BytesIO(json.dumps(payload).encode()), headers, request.full_url, 200)
            response.msg = "test-secret"
            return response

    monkeypatch.setattr(
        deployment_policy,
        "build_opener",
        lambda *handlers: stdlib_build_opener(ProxyHandler({}), HTTPSStub(), *handlers),
    )
    with pytest.raises(RuntimeError, match="302"):
        deployment_policy.classify(115)
    assert [request.host for request in requests] == ["api.github.com"]


def run_policy(tmp_path, action, payload, *args):
    stub = tmp_path / "gh"
    stub.write_text(
        "#!/usr/bin/env python3\nimport json, os, sys\n"
        "if 'pulls/' in ' '.join(sys.argv):\n"
        " assert '--paginate' in sys.argv and '--slurp' in sys.argv\n"
        "print(os.environ['GH_PAYLOAD'])\n"
    )
    stub.chmod(0o755)
    output = tmp_path / "output"
    result = subprocess.run(
        [sys.executable, "scripts/deployment_policy.py", action, *args],
        cwd=ROOT,
        env={
            **os.environ,
            "PATH": f"{tmp_path}:{os.environ['PATH']}",
            "GH_PAYLOAD": json.dumps(payload),
            "GITHUB_OUTPUT": str(output),
            "GITHUB_REPOSITORY": "org/repo",
        },
        capture_output=True,
        text=True,
    )
    return result, output.read_text() if output.exists() else ""


@pytest.mark.parametrize(
    ("paths", "backend", "frontend"),
    [
        (["src/webapp/app/page.tsx"], False, True),
        (["src/api/routes.py"], True, True),
        (["src/webapp/app/page.tsx", "src/services/cases.py"], True, True),
        (["migrations/001.sql"], True, True),
        (["docs/README.md"], False, False),
    ],
)
def test_changed_files_route_frontend_and_backend(tmp_path, paths, backend, frontend):
    result, output = run_policy(tmp_path, "classify", [[{"filename": p} for p in paths]], "--pr", "109")
    assert result.returncode == 0, result.stderr
    assert f"backend={str(backend).lower()}\n" in output
    assert f"frontend={str(frontend).lower()}\n" in output


def test_classifier_reads_pages_and_renamed_backend(tmp_path):
    payload = [
        [{"filename": f"docs/{i}.md"} for i in range(100)],
        [{"filename": "docs/moved.md", "previous_filename": "src/service.py"}],
    ]
    result, output = run_policy(tmp_path, "classify", payload, "--pr", "109")
    assert result.returncode == 0, result.stderr
    assert "backend=true" in output


@pytest.mark.parametrize(
    ("environment", "payload", "passes"),
    [
        ("staging", {"protection_rules": []}, False),
        ("staging", {"protection_rules": [{"type": "required_reviewers", "reviewers": [{"id": 1}]}]}, True),
        ("production", {"protection_rules": [{"type": "required_reviewers", "reviewers": [{"id": 1}]}]}, False),
    ],
)
def test_protection_guard_requires_live_reviewers(tmp_path, environment, payload, passes):
    result, _ = run_policy(tmp_path, "check-environment", payload, "--environment", environment)
    assert (result.returncode == 0) == passes, result.stderr


def test_vercel_failed_upload_cannot_become_successful_alias(tmp_path):
    stub = tmp_path / "vercel"
    submitted = tmp_path / "submitted"
    stub.write_text(f"#!/bin/sh\ntouch '{submitted}'\necho 'https://upload-only.vercel.app'\nexit 1\n")
    stub.chmod(0o755)
    helper = tmp_path / "python3"
    helper.write_text('#!/bin/sh\ntest "$2" = check\n')
    helper.chmod(0o755)
    result = subprocess.run(
        ["bash", "scripts/vercel_deploy.sh"],
        cwd=ROOT,
        env={**os.environ, "PATH": f"{tmp_path}:{os.environ['PATH']}", "VERCEL_TOKEN": "test"},
        text=True,
        capture_output=True,
    )
    assert result.returncode != 0
    assert result.stdout == ""
    assert submitted.exists()


@pytest.mark.parametrize("ready", [True, False])
def test_vercel_requires_project_api_ready_after_upload(tmp_path, ready):
    stub = tmp_path / "vercel"
    stub.write_text("#!/bin/sh\ncase \"$1\" in\ndeploy) echo 'https://preview.vercel.app';;\n*) exit 4;;\nesac\n")
    stub.chmod(0o755)
    helper = tmp_path / "python3"
    helper.write_text(
        '#!/bin/sh\ncase "$2" in\ncheck) exit 0;;\n'
        "wait) test \"$3\" = 'https://preview.vercel.app' || exit 4; "
        + ("exit 0" if ready else "exit 1")
        + ";;\n*) exit 4;;\nesac\n"
    )
    helper.chmod(0o755)
    result = subprocess.run(
        ["bash", "scripts/vercel_deploy.sh"],
        cwd=ROOT,
        env={**os.environ, "PATH": f"{tmp_path}:{os.environ['PATH']}", "VERCEL_TOKEN": "test"},
        text=True,
        capture_output=True,
    )
    assert (result.returncode == 0) == ready
    assert result.stdout == ("https://preview.vercel.app\n" if ready else "")


def test_railway_upload_failure_is_fatal(monkeypatch):
    from scripts import railway_pr

    monkeypatch.setattr(
        railway_pr.subprocess, "run", lambda *a, **k: subprocess.CompletedProcess(a, 1, "", "upload failed")
    )
    with pytest.raises(RuntimeError, match="upload"):
        railway_pr.deploy_service("svc", "project", "pr-109", 109)


def test_cleanup_refuses_non_ephemeral_environment(monkeypatch):
    from scripts import railway_pr

    monkeypatch.setattr(
        railway_pr, "get_environments", lambda *_: [{"name": "pr-109", "id": "permanent", "isEphemeral": False}]
    )
    with pytest.raises(RuntimeError, match="ephemeral"):
        railway_pr.cleanup_pr(109, "project")


@pytest.mark.parametrize("status", ["SUCCESS", "FAILED", "SKIPPED"])
def test_railway_waits_for_submitted_deployment_only(monkeypatch, status):
    from scripts import railway_pr

    responses = iter(
        [
            subprocess.CompletedProcess([], 0, '{"deploymentId":"mine"}', ""),
            subprocess.CompletedProcess(
                [], 0, json.dumps([{"id": "newer", "status": "SUCCESS"}, {"id": "mine", "status": status}]), ""
            ),
        ]
    )
    monkeypatch.setattr(railway_pr.subprocess, "run", lambda *a, **k: next(responses))
    if status == "SUCCESS":
        railway_pr.deploy_service("svc", "project", "pr-109", 109)
        with pytest.raises(StopIteration):
            next(responses)
    else:
        with pytest.raises(RuntimeError, match=status):
            railway_pr.deploy_service("svc", "project", "pr-109", 109)


def test_stale_head_cannot_resolve_old_preview(monkeypatch, capsys):
    from scripts import railway_pr

    monkeypatch.setattr(
        railway_pr.subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess([], 0, '{"GREENSENTINEL_PREVIEW_HEAD_SHA":"old"}', ""),
    )
    with pytest.raises(RuntimeError, match="head"):
        railway_pr.get_url(109, "project", "service", True, "new")
    assert capsys.readouterr().out == ""


def test_dev_authorization_preserves_existing_exact_origins(monkeypatch):
    from scripts import auth_config

    old = "https://custom-dev.example,https://other-preview.vercel.app"
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **k: subprocess.CompletedProcess([], 0, json.dumps({"CLERK_AUTHORIZED_PARTIES": old}), ""),
    )
    result = auth_config.merged_railway_origins("dev", "project", "service", "dev", "", ("https://new.vercel.app",))
    assert set(old.split(",")).issubset(result.split(","))
    assert "https://new.vercel.app" in result.split(",")
    assert "https://green-sentinel-dev.vercel.app" in result.split(",")

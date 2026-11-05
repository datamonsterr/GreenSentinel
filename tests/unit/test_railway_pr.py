"""Tests for Railway PR Preview Environment Manager script."""

import json
from io import BytesIO
from unittest.mock import MagicMock, patch

import pytest

from scripts.railway_pr import (
    DEFAULT_DEV_URL,
    cleanup_pr,
    create_pr_environment,
    create_service_domain,
    delete_environment_by_id,
    deploy_service,
    get_environments,
    get_railway_workflow_runs,
    get_service_domain,
    get_url,
    set_service_variable,
    setup_pr,
    wait_for_provisioning,
)


def test_get_environments():
    fake_response = {
        "data": {
            "project": {
                "environments": {
                    "edges": [
                        {"node": {"id": "env-1", "name": "production", "isEphemeral": False}},
                        {"node": {"id": "env-2", "name": "dev", "isEphemeral": False}},
                        {"node": {"id": "env-3", "name": "pr-42", "isEphemeral": True}},
                    ]
                }
            }
        }
    }
    with patch("scripts.railway_pr.run_railway_api", return_value=fake_response):
        envs = get_environments("test-project-id")
        assert len(envs) == 3
        assert envs[0]["name"] == "production"
        assert envs[2]["name"] == "pr-42"
        assert envs[2]["isEphemeral"] is True


def test_create_pr_environment():
    fake_response = {
        "data": {
            "environmentCreate": {
                "id": "env-new-99",
                "name": "pr-99",
            }
        }
    }
    with patch("scripts.railway_pr.run_railway_api", return_value=fake_response) as mock_api:
        res = create_pr_environment("test-proj", 99, "dev-env-id")
        assert res["id"] == "env-new-99"
        assert res["name"] == "pr-99"
        mock_api.assert_called_once()
        args, kwargs = mock_api.call_args
        assert "EnvironmentCreateInput!" in args[0]
        assert args[1]["input"]["name"] == "pr-99"
        assert args[1]["input"]["ephemeral"] is True


def test_delete_environment_by_id():
    fake_response = {"data": {"environmentDelete": True}}
    with patch("scripts.railway_pr.run_railway_api", return_value=fake_response) as mock_api:
        success = delete_environment_by_id("env-to-delete")
        assert success is True
        mock_api.assert_called_once()
        args, kwargs = mock_api.call_args
        assert args[1]["id"] == "env-to-delete"


def test_get_service_domain():
    fake_cli_out = json.dumps({"domains": [{"domain": "p063-preview-pr-10.up.railway.app"}]})
    mock_run = MagicMock()
    mock_run.returncode = 0
    mock_run.stdout = fake_cli_out
    with patch("subprocess.run", return_value=mock_run):
        domain = get_service_domain("service-1", "pr-10")
        assert domain == "p063-preview-pr-10.up.railway.app"


def test_create_service_domain():
    fake_response = {
        "data": {
            "serviceDomainCreate": {
                "id": "dom-1",
                "domain": "p063-backend-pr-77.up.railway.app",
            }
        }
    }
    with patch("scripts.railway_pr.run_railway_api", return_value=fake_response):
        domain = create_service_domain("service-1", "env-77")
        assert domain == "p063-backend-pr-77.up.railway.app"


def test_get_url_fallback(capsys):
    with patch("scripts.railway_pr.get_service_domain", return_value=None):
        get_url(123, "proj-1", "svc-1")
        captured = capsys.readouterr()
        assert captured.out.strip() == DEFAULT_DEV_URL


def test_get_url_required_preview_fails_without_provisioned_domain():
    with (
        patch("scripts.railway_pr.get_service_domain", return_value=None),
        pytest.raises(RuntimeError, match="not provisioned"),
    ):
        get_url(123, "proj-1", "svc-1", require_preview=True)


def test_get_url_existing(capsys):
    with patch("scripts.railway_pr.get_service_domain", return_value="custom-pr-42.up.railway.app"):
        get_url(42, "proj-1", "svc-1")
        captured = capsys.readouterr()
        assert captured.out.strip() == "https://custom-pr-42.up.railway.app"


def test_cleanup_pr_existing():
    envs = [{"id": "env-55", "name": "pr-55", "isEphemeral": True}]
    with (
        patch("scripts.railway_pr.get_environments", return_value=envs),
        patch("scripts.railway_pr.delete_environment_by_id", return_value=True) as mock_delete,
    ):
        cleanup_pr(55, "proj-1")
        mock_delete.assert_called_once_with("env-55")


def test_cleanup_pr_refuses_non_ephemeral():
    envs = [{"id": "env-55", "name": "pr-55", "isEphemeral": False}]
    with (
        patch("scripts.railway_pr.get_environments", return_value=envs),
        patch("scripts.railway_pr.delete_environment_by_id") as mock_delete,
        pytest.raises(RuntimeError, match="refusing to delete a non-ephemeral environment"),
    ):
        cleanup_pr(55, "proj-1")
        mock_delete.assert_not_called()


def test_cleanup_pr_non_existing(capsys):
    with (
        patch("scripts.railway_pr.get_environments", return_value=[]),
        patch("scripts.railway_pr.delete_environment_by_id") as mock_delete,
    ):
        cleanup_pr(99, "proj-1")
        mock_delete.assert_not_called()
        captured = capsys.readouterr()
        assert "does not exist or was already deleted" in captured.out


def test_set_service_variable():
    mock_run = MagicMock()
    mock_run.returncode = 0
    with patch("subprocess.run", return_value=mock_run) as mock_sp:
        success = set_service_variable("svc-1", "proj-1", "pr-12", "DATABASE_URL", "postgresql://dev")
        assert success is True
        mock_sp.assert_called_once()
        args = mock_sp.call_args[0][0]
        assert "DATABASE_URL=postgresql://dev" in args
        assert "--environment" in args
        assert "pr-12" in args


def test_setup_pr_binds_preview_database_to_postgres_service_reference(monkeypatch):
    monkeypatch.setenv("DEV_DATABASE_URL", "postgresql://shared-dev")
    with (
        patch("scripts.railway_pr.get_environments", return_value=[{"id": "env-12", "name": "pr-12"}]),
        patch("scripts.railway_pr.get_service_domain", return_value="preview.example.com"),
        patch("scripts.railway_pr.set_service_variable", return_value=True) as set_variable,
        patch("scripts.railway_pr.deploy_service"),
        patch("scripts.railway_pr.prepare_preview_schema") as prepare_schema,
    ):
        setup_pr(12, "project", "service", "dev", head_sha="abc123")

    calls = {call.args[3]: call.args[4] for call in set_variable.call_args_list}
    assert calls["DATABASE_URL"] == "${{Postgres.DATABASE_URL}}"
    assert calls["DATABASE_URL"] != "postgresql://shared-dev"
    prepare_schema.assert_called_once_with("service", "project", "pr-12", 12, "abc123")


def test_setup_pr_aborts_before_deploy_when_preview_database_binding_fails():
    with (
        patch("scripts.railway_pr.get_environments", return_value=[{"id": "env-12", "name": "pr-12"}]),
        patch("scripts.railway_pr.get_service_domain", return_value="preview.example.com"),
        patch("scripts.railway_pr.set_service_variable", return_value=False) as set_variable,
        patch("scripts.railway_pr.deploy_service") as deploy,
        pytest.raises(RuntimeError, match="preview DATABASE_URL"),
    ):
        setup_pr(12, "project", "service", "dev")

    set_variable.assert_called_once_with("service", "project", "pr-12", "DATABASE_URL", "${{Postgres.DATABASE_URL}}")
    deploy.assert_not_called()


def test_wait_for_provisioning_ignores_unrelated_runs_then_succeeds():
    responses = [
        [
            {
                "id": 1,
                "head_sha": "other",
                "pull_requests": [{"number": 12}],
                "status": "completed",
                "conclusion": "success",
            }
        ],
        [
            {
                "id": 2,
                "head_sha": "sha",
                "pull_requests": [{"number": 99}],
                "status": "completed",
                "conclusion": "success",
            }
        ],
        [{"id": 3, "head_sha": "sha", "pull_requests": [{"number": 12}], "status": "queued"}],
        [{"id": 3, "head_sha": "sha", "pull_requests": [{"number": 12}], "status": "in_progress"}],
        [
            {
                "id": 3,
                "head_sha": "sha",
                "pull_requests": [{"number": 12}],
                "status": "completed",
                "conclusion": "success",
            }
        ],
    ]
    now = [0]

    def clock():
        return now[0]

    def sleep(seconds):
        now[0] += seconds

    wait_for_provisioning(
        12, "sha", timeout_seconds=20, poll_seconds=1, get_runs=lambda *_: responses.pop(0), sleep=sleep, clock=clock
    )


@pytest.mark.parametrize("conclusion", ["failure", "cancelled"])
def test_wait_for_provisioning_fails_completed_failure(conclusion):
    runs = [
        {"id": 4, "head_sha": "sha", "pull_requests": [{"number": 12}], "status": "completed", "conclusion": conclusion}
    ]
    with pytest.raises(RuntimeError, match=f"ended in {conclusion}"):
        wait_for_provisioning(12, "sha", get_runs=lambda *_: runs, timeout_seconds=1, poll_seconds=1)


def test_wait_for_provisioning_times_out_without_exact_run():
    now = [0]

    with pytest.raises(RuntimeError, match="timed out"):
        wait_for_provisioning(
            12,
            "sha",
            timeout_seconds=2,
            poll_seconds=1,
            get_runs=lambda *_: [],
            sleep=lambda seconds: now.__setitem__(0, now[0] + seconds),
            clock=lambda: now[0],
        )


def test_workflow_metadata_uses_authenticated_rest_when_cli_is_unavailable(monkeypatch):
    monkeypatch.setenv("GH_TOKEN", "workflow-contract-token")
    runs = [{"id": 5, "head_sha": "commit-contract", "pull_requests": [{"number": 108}]}]
    response = BytesIO(json.dumps({"workflow_runs": runs}).encode())
    with (
        patch("scripts.railway_pr.subprocess.run", side_effect=FileNotFoundError),
        patch("scripts.railway_pr.urllib.request.urlopen", return_value=response) as opener,
    ):
        assert get_railway_workflow_runs(108, "commit-contract") == runs
    request = opener.call_args.args[0]
    assert request.full_url == (
        "https://api.github.com/repos/AI20K-Build-Phase-Cohort-4/P-063/actions/workflows/"
        "deploy-railway.yml/runs?event=pull_request&head_sha=commit-contract&per_page=20"
    )
    assert request.get_header("Authorization") == "Bearer workflow-contract-token"


def test_workflow_metadata_requires_credentials_when_cli_is_unavailable(monkeypatch):
    monkeypatch.delenv("GH_TOKEN", raising=False)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    with (
        patch("scripts.railway_pr.subprocess.run", side_effect=FileNotFoundError),
        pytest.raises(RuntimeError, match="GH_TOKEN"),
    ):
        get_railway_workflow_runs(108, "commit-contract")


def _up_result(deployment_id="dep-1"):
    mock_run = MagicMock()
    mock_run.returncode = 0
    mock_run.stdout = json.dumps({"deploymentId": deployment_id})
    return mock_run


def _list_result(status="SUCCESS"):
    mock_run = MagicMock()
    mock_run.returncode = 0
    mock_run.stdout = json.dumps([{"id": "dep-1", "status": status}])
    return mock_run


def test_deploy_service_retries_transient_list_failure():
    import subprocess

    calls = {"n": 0}

    def fake_run(cmd, **kwargs):
        calls["n"] += 1
        if "up" in cmd:
            return _up_result()
        if calls["n"] == 2:
            raise subprocess.CalledProcessError(1, cmd, stderr="transient")
        return _list_result("SUCCESS")

    with (
        patch("scripts.railway_pr.subprocess.run", side_effect=fake_run),
        patch("scripts.railway_pr.time.sleep") as mock_sleep,
    ):
        deploy_service("svc-1", "proj-1", "pr-12", 12)
        mock_sleep.assert_called_once_with(5)


def test_deploy_service_raises_after_repeated_list_failures():
    import subprocess

    def fake_run(cmd, **kwargs):
        if "up" in cmd:
            return _up_result()
        raise subprocess.CalledProcessError(1, cmd, stderr="down")

    with (
        patch("scripts.railway_pr.subprocess.run", side_effect=fake_run),
        patch("scripts.railway_pr.time.sleep"),
        pytest.raises(RuntimeError, match="deployment list failed"),
    ):
        deploy_service("svc-1", "proj-1", "pr-12", 12)

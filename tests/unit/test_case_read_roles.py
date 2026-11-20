"""Workflow roles (ADR-031) get read-only case access; writes stay analyst-only."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from src.api.auth import Principal, require_principal
from src.api.routes import get_case_service
from src.main import app
from src.services.case_workflow import awaiting_status

ROLES = ["reviewer", "ops_director", "marketplace_director"]
READ = [
    "/cases",
    "/cases/c1",
    "/cases/c1/forensic-brief",
    "/cases/c1/policy",
    "/cases/c1/agent-context",
    "/cases/c1/workflow-draft",
    "/cases/c1/dispute-dossier",
    "/cases/history",
]
WRITE = [
    ("POST", "/cases/c1/claim", {"analyst_id": "p1"}),
    ("POST", "/cases/c1/release", {"analyst_id": "p1"}),
    ("POST", "/cases/c1/actions", {"action_type": "REQUEST_EVIDENCE", "analyst_id": "p1"}),
    ("POST", "/cases/c1/adjudicate", {"outcome": "AGREE", "analyst_id": "p1", "rationale": "long enough rationale", "expected_case_version": 1}),
    ("POST", "/cases/c1/preliminary-assessment", {"analyst_id": "p1", "judgment": "Chưa đủ cơ sở"}),
    ("PUT", "/cases/c1/workflow-draft", {"text": "x"}),
    ("POST", "/cases/c1/delegate-inquiry", {"instruction": "x"}),
    ("POST", "/cases/c1/match-precedent", {"case_id": "c1"}),
    ("POST", "/cases/c1/apply-precedent", {}),
    ("DELETE", "/cases/c1/agent-context", None),
]


@pytest.fixture
def client_for():
    svc = MagicMock()
    svc.list_cases = AsyncMock(return_value={"items": [], "total": 0, "limit": 50, "offset": 0})
    svc.list_case_history = AsyncMock(return_value={"items": [], "total": 0, "limit": 50, "offset": 0})

    def make(role):
        p = Principal(id="p1", organization_id="org1", roles=frozenset({role}))
        app.dependency_overrides[require_principal] = lambda: p
        app.dependency_overrides[get_case_service] = lambda: svc
        return TestClient(app, raise_server_exceptions=False), svc

    yield make
    app.dependency_overrides.clear()


@pytest.mark.parametrize("role", ROLES)
@pytest.mark.parametrize("path", READ)
def test_workflow_roles_not_forbidden_on_reads(client_for, role, path):
    c, _ = client_for(role)
    r = c.get(path)
    assert "Insufficient role" not in r.text, (path, r.text)


@pytest.mark.parametrize("role", ROLES)
@pytest.mark.parametrize(("method", "path", "body"), WRITE)
def test_workflow_roles_forbidden_on_writes(client_for, role, method, path, body):
    c, _ = client_for(role)
    r = c.request(method, path, json=body)
    assert r.status_code == 403 and "Insufficient role" in r.text


@pytest.mark.parametrize(
    ("role", "status"),
    [("reviewer", "report_issued"), ("ops_director", "need_ops_dir_approved"), ("marketplace_director", "need_mkp_dir_approved")],
)
def test_awaiting_me_filters_to_role_status_and_ignores_leases(client_for, role, status):
    c, svc = client_for(role)
    assert c.get("/cases?awaiting=me").status_code == 200
    kw = svc.list_cases.call_args.kwargs
    assert kw["status"] == status and kw["availability"] == "all"
    assert awaiting_status({role}) == status


def test_workflow_role_all_view_is_unfiltered(client_for):
    c, svc = client_for("reviewer")
    assert c.get("/cases").status_code == 200
    assert svc.list_cases.call_args.kwargs["status"] is None


def test_awaiting_me_rejected_for_analyst(client_for):
    c, _ = client_for("analyst")
    assert c.get("/cases?awaiting=me").status_code == 400


def test_awaiting_status_none_for_admin_and_analyst():
    assert awaiting_status({"admin", "reviewer"}) is None
    assert awaiting_status({"analyst"}) is None


@pytest.mark.parametrize(
    ("role", "status", "action"),
    [("reviewer", "report_issued", "confirm-report"), ("ops_director", "need_ops_dir_approved", "approve-ops"), ("marketplace_director", "need_mkp_dir_approved", "approve-marketplace")],
)
def test_workflow_get_returns_role_actions(client_for, monkeypatch, role, status, action):
    from src.services import case_workflow

    c, svc = client_for(role)
    svc._resolve_case_id.return_value = "c1"
    monkeypatch.setattr("src.api.routes.require_case_scope", lambda *a, **k: None)
    monkeypatch.setattr(case_workflow, "load_stepper", lambda *a, **k: {"status": status, "steps": []})
    r = c.get("/cases/c1/workflow")
    assert r.status_code == 200 and r.json()["actions"] == [action]

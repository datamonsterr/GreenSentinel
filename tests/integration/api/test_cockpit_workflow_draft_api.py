"""Offline ASGI boundary for tenant-scoped workflow draft persistence."""

from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from src.api.auth import Principal, require_principal
from src.api.routes import router
from src.models.schemas import WorkflowDraftRequest
from src.services.case_service import CaseService, get_case_service

CASE_ID = "99999999-1111-4111-8111-111111111111"


@pytest.fixture
def service(monkeypatch):
    monkeypatch.setattr(CaseService, "_load_seed_data", lambda self: None)
    svc = CaseService()
    monkeypatch.setattr(svc, "_get_db_connection", lambda: None)
    svc._cases = {CASE_ID: {"id": CASE_ID, "organization_id": "org-a", "status": "ready"}}
    return svc


def application(service, role="analyst", org="org-a"):
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")

    async def get_service():
        return service

    async def principal():
        return Principal("analyst-1", org, frozenset({role}))

    app.dependency_overrides[get_case_service] = get_service
    app.dependency_overrides[require_principal] = principal
    return app


@pytest.mark.asyncio
async def test_api_save_read_and_stale_write(service):
    async with AsyncClient(transport=ASGITransport(app=application(service)), base_url="http://test") as client:
        saved = await client.put(
            f"/api/v1/cases/{CASE_ID}/workflow-draft", json={"text": "Verify measured speed", "expected_version": 0}
        )
        assert saved.status_code == 200
        assert saved.json()["updated_by"] == "analyst-1"
        assert saved.json()["version"] == 1
        read = await client.get(f"/api/v1/cases/{CASE_ID}/workflow-draft")
        assert read.json() == saved.json()
        stale = await client.put(
            f"/api/v1/cases/{CASE_ID}/workflow-draft", json={"text": "Stale edit", "expected_version": 0}
        )
        assert stale.status_code == 409


@pytest.mark.asyncio
@pytest.mark.parametrize("role,org,expected", [("driver", "org-a", 403), ("analyst", "org-b", 404)])
async def test_api_rejects_driver_and_other_tenant(service, role, org, expected):
    async with AsyncClient(
        transport=ASGITransport(app=application(service, role, org)), base_url="http://test"
    ) as client:
        for method in ("get", "put"):
            response = await client.request(
                method,
                f"/api/v1/cases/{CASE_ID}/workflow-draft",
                **({"json": {"text": "Unauthorized"}} if method == "put" else {}),
            )
            assert response.status_code == expected
    assert "workflow_draft" not in service._cases[CASE_ID]


@pytest.mark.asyncio
async def test_api_rejects_oversized_text_and_negative_version(service):
    async with AsyncClient(transport=ASGITransport(app=application(service)), base_url="http://test") as client:
        for payload in ({"text": "x" * 20001}, {"text": "notes", "expected_version": -1}):
            assert (await client.put(f"/api/v1/cases/{CASE_ID}/workflow-draft", json=payload)).status_code == 422


@pytest.mark.asyncio
async def test_database_save_binds_tenant_and_commits_notes_with_event(service, monkeypatch):
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    cur.fetchone.return_value = {
        "id": CASE_ID,
        "status": "ready",
        "workflow_draft": {},
        "workflow_trace": {"timeline": []},
    }
    monkeypatch.setattr(service, "_get_db_connection", lambda: conn)
    result = await service.save_workflow_draft(
        CASE_ID,
        WorkflowDraftRequest(text="Measured evidence", expected_version=0),
        analyst_id="analyst-1",
        organization_id="org-a",
    )
    assert result.version == 1
    select, update = cur.execute.call_args_list
    assert "FOR UPDATE" in select.args[0]
    assert select.args[1] == (CASE_ID, "org-a")
    assert "organization_id = %s" in update.args[0]
    assert update.args[1][-2:] == (CASE_ID, "org-a")
    assert "workflow_draft_saved" in update.args[1][1]
    conn.commit.assert_called_once()
    conn.rollback.assert_not_called()
    conn.close.assert_called_once()


@pytest.mark.asyncio
async def test_database_event_write_failure_rolls_back_and_surfaces_503(service, monkeypatch):
    conn = MagicMock()
    cur = conn.cursor.return_value.__enter__.return_value
    cur.fetchone.return_value = {"id": CASE_ID, "status": "ready"}
    cur.execute.side_effect = [None, RuntimeError("write failed")]
    monkeypatch.setattr(service, "_get_db_connection", lambda: conn)
    async with AsyncClient(transport=ASGITransport(app=application(service)), base_url="http://test") as client:
        result = await client.put(f"/api/v1/cases/{CASE_ID}/workflow-draft", json={"text": "notes"})
    assert result.status_code == 503
    conn.rollback.assert_called_once()
    conn.commit.assert_not_called()

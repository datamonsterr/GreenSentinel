"""Active queue membership and retained history through the HTTP boundary."""

from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from src.api.auth import Principal, require_principal
from src.api.routes import router
from src.config import Settings
from src.services.case_service import CaseService, get_case_service


@pytest.fixture
def queue_app(monkeypatch):
    service = CaseService(Settings(app_env="test", database_url=""))
    monkeypatch.setattr(service, "_get_db_connection", lambda: None)
    monkeypatch.setattr(service, "get_redis_client", lambda: None)
    monkeypatch.setattr(service, "get_principal_role", lambda *args: "analyst")
    service._cases.clear()
    service._case_aliases.clear()
    now = datetime.now(UTC)
    states = [
        "resolved",
        "dismissed",
        "suspended",
        "auto_dismissed",
        "ready",
        "evidence_requested",
        "escalated",
        "pending_analyst_review",
    ]
    for index, state in enumerate(states):
        case_id = f"queue-{state}"
        service._cases[case_id] = {
            "id": case_id,
            "status": state,
            "organization_id": "org-owned",
            "priority_tier": 1,
            "priority_score": 100 - index,
            "created_at": now,
            "updated_at": now,
            "version": 1,
        }
        service._active_leases[case_id] = {"analyst_id": "analyst-owned", "expires_at": now + timedelta(minutes=5)}
    service._cases["foreign-case"] = dict(
        service._cases["queue-resolved"], id="foreign-case", organization_id="org-foreign"
    )
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[get_case_service] = lambda: service
    app.dependency_overrides[require_principal] = lambda: Principal(
        id="analyst-owned", organization_id="org-owned", roles=frozenset({"analyst"})
    )
    return app


@pytest.mark.asyncio
@pytest.mark.parametrize("availability", ["available", "mine"])
async def test_active_queue_filters_before_count_and_pagination(queue_app, availability):
    async with AsyncClient(transport=ASGITransport(app=queue_app), base_url="http://test") as client:
        response = await client.get("/api/v1/cases", params={"availability": availability, "limit": 2, "offset": 1})
    assert response.status_code == 200
    assert response.json()["total"] == 4
    assert [item["status"] for item in response.json()["items"]] == ["evidence_requested", "escalated"]


@pytest.mark.asyncio
@pytest.mark.parametrize("params,expected_total", [({"availability": "all"}, 8), ({"status": "resolved"}, 1)])
async def test_explicit_history_keeps_terminal_records_and_organization_scope(queue_app, params, expected_total):
    async with AsyncClient(transport=ASGITransport(app=queue_app), base_url="http://test") as client:
        response = await client.get("/api/v1/cases", params=params)
    assert response.status_code == 200
    assert response.json()["total"] == expected_total
    assert "queue-resolved" in [item["id"] for item in response.json()["items"]]
    assert "foreign-case" not in [item["id"] for item in response.json()["items"]]


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["AGREE", "DISAGREE"])
async def test_final_decision_removes_case_and_stale_retry_cannot_duplicate(queue_app, outcome):
    case_id = "queue-ready"
    async with AsyncClient(transport=ASGITransport(app=queue_app), base_url="http://test") as client:
        payload = {
            "analyst_id": "analyst-owned",
            "outcome": outcome,
            "rationale": "Reviewed evidence and confirmed the decision",
            "expected_case_version": 1,
        }
        failed = await client.post(f"/api/v1/cases/{case_id}/adjudicate", json={**payload, "expected_case_version": 99})
        assert failed.status_code == 409
        assert (await client.get("/api/v1/cases")).json()["total"] == 4
        committed = await client.post(f"/api/v1/cases/{case_id}/adjudicate", json=payload)
        assert committed.status_code == 200, committed.text
        retry = await client.post(f"/api/v1/cases/{case_id}/adjudicate", json=payload)
        assert retry.status_code == 409
        for availability in ("available", "mine"):
            queue = (await client.get("/api/v1/cases", params={"availability": availability})).json()
            assert queue["total"] == 3
            assert case_id not in [item["id"] for item in queue["items"]]
        history = (await client.get("/api/v1/cases", params={"status": "resolved"})).json()
        assert case_id in [item["id"] for item in history["items"]]


@pytest.mark.asyncio
async def test_evidence_request_preserves_active_queue_and_escalation_stays_unsupported(queue_app):
    async with AsyncClient(transport=ASGITransport(app=queue_app), base_url="http://test") as client:
        payload = {"analyst_id": "analyst-owned", "action_type": "REQUEST_EVIDENCE", "notes": "Need pickup evidence"}
        response = await client.post("/api/v1/cases/queue-ready/actions", json=payload)
        assert response.status_code == 200
        assert response.json()["new_case_status"] == "evidence_requested"
        for availability in ("available", "mine"):
            queue = (await client.get("/api/v1/cases", params={"availability": availability})).json()
            assert queue["total"] == 4
            assert (
                next(item for item in queue["items"] if item["id"] == "queue-ready")["status"] == "evidence_requested"
            )
        rejected = await client.post("/api/v1/cases/queue-ready/actions", json={**payload, "action_type": "ESCALATE"})
        assert rejected.status_code == 422

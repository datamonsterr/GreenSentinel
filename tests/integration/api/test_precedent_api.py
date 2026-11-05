"""Integration tests for Precedent Workflow Mining & Jev Similarity API Endpoints."""

import pytest
from httpx import ASGITransport, AsyncClient

from src.main import app
from src.services.jev_precedent_service import get_jev_precedent_service

ANALYST_HEADERS = {"X-Principal-ID": "anl-test-001", "X-Role": "analyst"}
DRIVER_HEADERS = {"X-Principal-ID": "drv-test-001", "X-Role": "driver"}


@pytest.fixture(autouse=True)
def offline_precedent_service(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep legacy seed-contract tests independent from a running local database."""
    from types import SimpleNamespace

    from src.config import get_settings
    from src.services.case_service import get_case_service

    service = get_jev_precedent_service()
    monkeypatch.setattr(service, "_get_db_connection", lambda: None)
    # S4-TENANT #294 P1c: case-scoped routes pre-check scope through
    # CaseService. Pin it to the same offline posture so these fixture-contract
    # tests exercise the service fallback instead of the live PG rows.
    settings = get_settings()
    offline_cases = SimpleNamespace(
        settings=settings,
        _cases={},
        _resolve_case_id=lambda case_id: case_id,
        _get_db_connection=lambda: None,
    )
    app.dependency_overrides[get_case_service] = lambda: offline_cases
    yield
    app.dependency_overrides.pop(get_case_service, None)


@pytest.mark.asyncio
async def test_list_precedents_api():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.get("/api/v1/precedents", headers=ANALYST_HEADERS)
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) >= 5
        assert any(p["violation_code"] == "ERR-02" for p in data)


@pytest.mark.asyncio
async def test_get_precedent_by_id_api():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.get(
            "/api/v1/precedents/018f2f4e-9100-7000-8000-000000000001",
            headers=ANALYST_HEADERS,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == "018f2f4e-9100-7000-8000-000000000001"
        assert data["violation_code"] == "ERR-02"
        assert "workflow_trace" in data
        assert len(data["workflow_trace"]["agent_tools_called"]) >= 1


@pytest.mark.asyncio
async def test_match_case_precedent_api():
    payload = {
        "case_id": "case-match-api-01",
        "claim_type": "traffic_gridlock",
        "driver_statement": "Kẹt xe Kim Mã giờ cao điểm chiều tối",
        "violation_code": "ERR-02",
        "telemetry_summary": {"corroborated": True, "ratio": 2.7, "observed_speed": 2.1},
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.post(
            "/api/v1/cases/case-match-api-01/match-precedent",
            headers=ANALYST_HEADERS,
            json=payload,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["case_id"] == "case-match-api-01"
        assert data["has_match"] is True
        assert data["top_match"] is not None
        assert data["top_match"]["similarity_score"] >= 0.80
        assert len(data["top_match"]["matching_factors"]) >= 1


@pytest.mark.asyncio
async def test_apply_precedent_api():
    payload = {"precedent_id": "018f2f4e-9100-7000-8000-000000000001"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.post(
            "/api/v1/cases/case-match-api-01/apply-precedent",
            headers=ANALYST_HEADERS,
            json=payload,
        )
        assert resp.status_code == 409
        assert "Database is required" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_get_workflow_trace_api():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.get(
            "/api/v1/cases/case-match-api-01/workflow-trace",
            headers=ANALYST_HEADERS,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "agent_tools_called" in data
        assert "related_policies" in data


@pytest.mark.asyncio
async def test_precedent_api_rbac_rejects_driver():
    """Driver role should be forbidden from accessing precedent mining endpoints."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.get("/api/v1/precedents", headers=DRIVER_HEADERS)
        assert resp.status_code == 403

        resp2 = await ac.post(
            "/api/v1/cases/case-001/match-precedent",
            headers=DRIVER_HEADERS,
            json={"case_id": "case-001"},
        )
        assert resp2.status_code == 403

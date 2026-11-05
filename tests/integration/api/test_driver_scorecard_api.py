"""API contracts for the live driver scorecard (issue #100).

Routes:
- GET /api/v1/drivers/{driver_id}/scorecard
- GET /api/v1/cases/{case_id}/driver-scorecard (case -> driver alias)

NOTE (repo convention): the canonical suite lives at
tests/integration/api/ (not tests/test_api/ named in the issue DoD,
which does not exist).
"""

from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from src.api.routes import router
from src.config import Settings, get_settings
from src.services.case_service import CaseService, get_case_service

TEST_ORG = "018f2f4e-0000-7000-8000-000000000001"
OTHER_ORG = "018f2f4e-0000-7000-8000-000000000002"
ANALYST_HEADERS = {"X-Role": "analyst"}


@pytest.fixture(autouse=True)
def force_memory_backend(monkeypatch):
    """Force the in-memory fallback so tests are deterministic with or without a live DB."""
    monkeypatch.setattr(CaseService, "_get_db_connection", lambda self: None)
    yield


def _seed(driver_id="drv-api-1", org=TEST_ORG, n_trips=4, n_cases=2, penalized=1, case_org=None):
    cs = get_case_service()
    created = datetime.now(UTC) - timedelta(days=500)
    cs._drivers[driver_id] = {"id": driver_id, "created_at": created.isoformat(), "organization_id": org}
    for i in range(n_trips):
        asgn = f"asgn-{driver_id}-{i}"
        cs._assignments[asgn] = {"id": asgn, "driver_id": driver_id, "trip_id": f"trip-{driver_id}-{i}"}
        cs._trips[f"trip-{driver_id}-{i}"] = {"id": f"trip-{driver_id}-{i}"}
    for i in range(n_cases):
        case_id = f"case-{driver_id}-{i}"
        cs._cases[case_id] = {
            "id": case_id,
            "assignment_id": f"asgn-{driver_id}-{i}",
            "organization_id": case_org or org,
            "suspected_category": "ERR-02",
            "created_at": datetime.now(UTC).isoformat(),
        }
    for i in range(penalized):
        cs._adjudications.append({"case_id": f"case-{driver_id}-{i}", "outcome": "suspend", "organization_id": org})
    return cs


@pytest.mark.asyncio
async def test_driver_scorecard_route_200_and_schema(client: AsyncClient):
    _seed()
    res = await client.get("/api/v1/drivers/drv-api-1/scorecard", headers=ANALYST_HEADERS)
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["driver_id"] == "drv-api-1"
    assert data["violation_ratio_90d"] == round(2 / 4 * 100, 1)
    assert data["fined_ratio"] == 50.0
    assert data["benchmark_violation_ratio"] == 5.0
    assert data["repeat_offense_risk_score"] == min(99, max(10, 2 * 15 + 1 * 25))
    assert data["tenure_months"] >= 12
    assert isinstance(data["past_incidents"], list) and len(data["past_incidents"]) == 2
    first = data["past_incidents"][0]
    for key in ("trip_id", "occurred_at", "violation_type", "investigation_finding", "action_taken", "status"):
        assert key in first


@pytest.mark.asyncio
async def test_case_alias_route_matches_driver_route(client: AsyncClient):
    _seed()
    direct = await client.get("/api/v1/drivers/drv-api-1/scorecard", headers=ANALYST_HEADERS)
    alias = await client.get("/api/v1/cases/case-drv-api-1-0/driver-scorecard", headers=ANALYST_HEADERS)
    assert alias.status_code == 200, alias.text
    assert alias.json() == direct.json()


@pytest.mark.asyncio
async def test_scorecard_empty_history(client: AsyncClient):
    _seed(driver_id="drv-bare", n_trips=0, n_cases=0, penalized=0)
    res = await client.get("/api/v1/drivers/drv-bare/scorecard", headers=ANALYST_HEADERS)
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["violation_ratio_90d"] == 0.0
    assert data["past_incidents"] == []


@pytest.mark.asyncio
async def test_scorecard_unknown_driver_and_case_404(client: AsyncClient):
    res = await client.get("/api/v1/drivers/drv-ghost/scorecard", headers=ANALYST_HEADERS)
    assert res.status_code == 404
    res = await client.get("/api/v1/cases/case-ghost/driver-scorecard", headers=ANALYST_HEADERS)
    assert res.status_code == 404


@pytest.mark.asyncio
async def test_case_alias_cross_org_is_403(client: AsyncClient):
    _seed(driver_id="drv-xorg", case_org=OTHER_ORG)
    res = await client.get("/api/v1/cases/case-drv-xorg-0/driver-scorecard", headers=ANALYST_HEADERS)
    assert res.status_code == 403


@pytest.mark.asyncio
async def test_driver_route_org_mismatch_is_403(client: AsyncClient):
    _seed(driver_id="drv-foreign", org=OTHER_ORG)
    res = await client.get("/api/v1/drivers/drv-foreign/scorecard", headers=ANALYST_HEADERS)
    assert res.status_code == 403


@pytest.mark.asyncio
async def test_driver_role_is_forbidden(client: AsyncClient):
    _seed()
    res = await client.get("/api/v1/drivers/drv-api-1/scorecard", headers={"X-Role": "driver"})
    assert res.status_code == 403


@pytest.mark.asyncio
async def test_scorecard_db_unavailable_is_503(client: AsyncClient, monkeypatch):
    _seed()
    cs = get_case_service()
    monkeypatch.setattr(cs, "settings", Settings(app_env="production", database_url=""))
    res = await client.get("/api/v1/drivers/drv-api-1/scorecard", headers=ANALYST_HEADERS)
    assert res.status_code == 503


@pytest.mark.asyncio
async def test_scorecard_requires_auth_on_hosted_stack():
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    app.dependency_overrides[get_settings] = lambda: Settings(app_env="production", clerk_secret_key="test")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        res = await ac.get("/api/v1/drivers/drv-api-1/scorecard")
    assert res.status_code == 401

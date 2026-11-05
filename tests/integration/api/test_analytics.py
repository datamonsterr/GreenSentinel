"""Test suite for System and Operational Analytics Metrics.

Issue #152: show complete current system metrics and verify with test runs.
"""

from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from src.api.auth import Principal, require_principal
from src.api.routes import router
from src.config import Settings, get_settings
from src.services.case_service import CaseService, get_case_service


@pytest.fixture
def analytics_app() -> tuple[FastAPI, CaseService]:
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    settings = Settings(
        supabase_url="https://test.supabase.co",
        supabase_service_role_key="test-key",
        environment="test",
        allow_test_fallback=True,
    )
    app.dependency_overrides[get_settings] = lambda: settings
    service = CaseService(settings)
    service._cases.clear()
    service._leases.clear()
    service._adjudications.clear()
    app.dependency_overrides[get_case_service] = lambda: service
    return app, service


@pytest.mark.asyncio
async def test_analytics_metrics_aggregate_dataset_exceeding_100_rows(
    analytics_app: tuple[FastAPI, CaseService],
) -> None:
    """Verify metrics aggregate over complete organization dataset (>100 rows), independent of page limits."""
    app, service = analytics_app
    org_id = "018f2f4e-0000-7000-8000-000000000001"
    now = datetime.now(UTC)

    # Seed 120 total cases (> 100 rows)
    # 40 P0 new cases (ERR-01)
    for i in range(40):
        c_id = f"case-p0-{i}"
        service._cases[c_id] = {
            "id": c_id,
            "organization_id": org_id,
            "status": "new",
            "priority_tier": 0,
            "suspected_category": "ERR-01",
            "created_at": now - timedelta(hours=5),
            "version": 1,
        }

    # 40 P1 in_review cases (ERR-02), 15 with active foreign review leases
    for i in range(40):
        c_id = f"case-p1-{i}"
        service._cases[c_id] = {
            "id": c_id,
            "organization_id": org_id,
            "status": "in_review",
            "priority_tier": 1,
            "suspected_category": "ERR-02",
            "created_at": now - timedelta(hours=4),
            "version": 1,
        }
        if i < 15:
            service._leases[c_id] = {
                "analyst_id": f"analyst-other-{i}",
                "acquired_at": now - timedelta(minutes=2),
                "expires_at": now + timedelta(minutes=5),
            }

    # 20 pending driver confirmation cases (ERR-03)
    for i in range(20):
        c_id = f"case-drv-{i}"
        service._cases[c_id] = {
            "id": c_id,
            "organization_id": org_id,
            "status": "awaiting_driver_confirmation",
            "priority_tier": 2,
            "suspected_category": "ERR-03",
            "created_at": now - timedelta(hours=3),
            "version": 1,
        }

    # 10 driver confirmed resolution cases
    for i in range(10):
        c_id = f"case-resolved-drv-{i}"
        service._cases[c_id] = {
            "id": c_id,
            "organization_id": org_id,
            "status": "driver_confirmed_resolution",
            "priority_tier": 2,
            "suspected_category": "ERR-04",
            "created_at": now - timedelta(hours=2),
            "version": 1,
        }

    # 10 auto-dismissed cases
    for i in range(10):
        c_id = f"case-autodismiss-{i}"
        service._cases[c_id] = {
            "id": c_id,
            "organization_id": org_id,
            "status": "auto_dismissed",
            "priority_tier": 2,
            "suspected_category": "ERR-05",
            "created_at": now - timedelta(hours=1),
            "version": 1,
        }

    # Seed 25 adjudications with durations for MTTR
    for i in range(25):
        service._adjudications.append(
            {
                "id": f"adj-{i}",
                "case_id": f"case-p0-{i}",
                "organization_id": org_id,
                "outcome": "AGREE" if i % 2 == 0 else "DISAGREE",
                "approved_at": now - timedelta(minutes=10),
                "created_at": now - timedelta(minutes=10),
            }
        )

    principal = Principal(
        id="analyst-lead",
        roles={"senior_analyst", "analyst"},
        organization_id=org_id,
    )
    app.dependency_overrides[require_principal] = lambda: principal

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/v1/analytics/metrics")
        assert resp.status_code == 200, resp.text
        data = resp.json()

        # Check Queue metrics
        queue = data["queue"]
        assert queue["total_cases"] == 120, "Total count must aggregate full dataset, exceeding 100 rows"
        assert queue["active_backlog"] == 80, "40 new + 40 in_review"
        assert queue["claimed_cases"] == 15, "15 cases have active foreign review leases"
        assert queue["available_unclaimed"] == 65, "80 backlog - 15 claimed = 65 available"
        assert queue["pending_driver_confirmation"] == 20
        assert queue["priority_distribution"]["P0"] == 40
        assert queue["priority_distribution"]["P1"] == 40
        assert queue["priority_distribution"]["P2"] == 40

        # Check Dispositions & Outcomes
        dispositions = data["dispositions"]
        assert dispositions["driver_confirmed_resolutions"] == 10
        assert dispositions["auto_dismissed_count"] == 10
        assert dispositions["analyst_adjudications_total"] == 25
        assert dispositions["analyst_decisions_breakdown"]["AGREE"] == 13
        assert dispositions["analyst_decisions_breakdown"]["DISAGREE"] == 12

        # Check Category distribution
        categories = data["categories"]
        assert categories["ERR-01"] == 40
        assert categories["ERR-02"] == 40
        assert categories["ERR-03"] == 20
        assert categories["ERR-04"] == 10
        assert categories["ERR-05"] == 10

        # Check Performance
        perf = data["performance"]
        assert perf["average_mttr_seconds"] is not None
        assert perf["average_mttr_seconds"] > 0
        assert perf["hitl_enforcement_ratio_pct"] == 100.0
        assert perf["reviewer_concordance_pct"] is None, "Unmeasured concordance must be None, not fabricated"


@pytest.mark.asyncio
async def test_analytics_metrics_tenant_isolation(
    analytics_app: tuple[FastAPI, CaseService],
) -> None:
    """Ensure organization B cases and metrics never contaminate organization A."""
    app, service = analytics_app
    org_a = "018f2f4e-0000-7000-8000-000000000001"
    org_b = "018f2f4e-0000-7000-8000-000000000002"
    now = datetime.now(UTC)

    # 10 cases in Org A
    for i in range(10):
        service._cases[f"case-a-{i}"] = {
            "id": f"case-a-{i}",
            "organization_id": org_a,
            "status": "new",
            "priority_tier": 1,
            "created_at": now,
        }

    # 50 cases in Org B
    for i in range(50):
        service._cases[f"case-b-{i}"] = {
            "id": f"case-b-{i}",
            "organization_id": org_b,
            "status": "new",
            "priority_tier": 0,
            "created_at": now,
        }

    principal_a = Principal(
        id="analyst-a",
        roles={"analyst"},
        organization_id=org_a,
    )
    app.dependency_overrides[require_principal] = lambda: principal_a

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/v1/analytics/metrics")
        assert resp.status_code == 200
        data = resp.json()
        assert data["queue"]["total_cases"] == 10, "Org A must only see its own 10 cases"


@pytest.mark.asyncio
async def test_analytics_metrics_window_boundary(
    analytics_app: tuple[FastAPI, CaseService],
) -> None:
    """Ensure window_days excludes records created outside the time window."""
    app, service = analytics_app
    org_id = "018f2f4e-0000-7000-8000-000000000001"
    now = datetime.now(UTC)

    # Case within 7 days
    service._cases["case-recent"] = {
        "id": "case-recent",
        "organization_id": org_id,
        "status": "new",
        "priority_tier": 0,
        "created_at": now - timedelta(days=2),
    }

    # Case outside 7 days but within 30 days
    service._cases["case-older"] = {
        "id": "case-older",
        "organization_id": org_id,
        "status": "new",
        "priority_tier": 1,
        "created_at": now - timedelta(days=15),
    }

    principal = Principal(id="analyst-1", roles={"analyst"}, organization_id=org_id)
    app.dependency_overrides[require_principal] = lambda: principal

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # 7-day window
        resp_7 = await client.get("/api/v1/analytics/metrics?window_days=7")
        assert resp_7.status_code == 200
        assert resp_7.json()["queue"]["total_cases"] == 1

        # 30-day window
        resp_30 = await client.get("/api/v1/analytics/metrics?window_days=30")
        assert resp_30.status_code == 200
        assert resp_30.json()["queue"]["total_cases"] == 2


@pytest.mark.asyncio
async def test_analytics_metrics_rbac_permissions(
    analytics_app: tuple[FastAPI, CaseService],
) -> None:
    """Only analyst, senior_analyst, admin roles can access analytics metrics."""
    app, _ = analytics_app
    org_id = "018f2f4e-0000-7000-8000-000000000001"

    # Driver role denied
    driver_principal = Principal(
        id="drv-01",
        roles={"driver"},
        organization_id=org_id,
        driver_id="drv-01",
    )
    app.dependency_overrides[require_principal] = lambda: driver_principal

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/v1/analytics/metrics")
        assert resp.status_code == 403

    # Analyst role allowed
    analyst_principal = Principal(
        id="analyst-01",
        roles={"analyst"},
        organization_id=org_id,
    )
    app.dependency_overrides[require_principal] = lambda: analyst_principal

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/v1/analytics/metrics")
        assert resp.status_code == 200


@pytest.mark.asyncio
async def test_analytics_metrics_empty_missingness_handling(
    analytics_app: tuple[FastAPI, CaseService],
) -> None:
    """Empty datasets return structured zero counts and None for unmeasured metrics."""
    app, _ = analytics_app
    org_id = "018f2f4e-0000-7000-8000-000000000001"

    principal = Principal(id="analyst-1", roles={"analyst"}, organization_id=org_id)
    app.dependency_overrides[require_principal] = lambda: principal

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/v1/analytics/metrics")
        assert resp.status_code == 200
        data = resp.json()

        assert data["queue"]["total_cases"] == 0
        assert data["queue"]["active_backlog"] == 0
        assert data["performance"]["average_mttr_seconds"] is None
        assert data["performance"]["hitl_enforcement_ratio_pct"] is None
        assert data["performance"]["reviewer_concordance_pct"] is None
        assert data["health"]["database_healthy"] is False

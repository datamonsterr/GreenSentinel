"""Test suite for Analyst Profile, Decision Metrics, and Immutable Audit Ledger.

Issue #151: show analyst profile, decision metrics and immutable activity.
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
def audit_app() -> tuple[FastAPI, CaseService]:
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
    app.dependency_overrides[get_case_service] = lambda: service
    return app, service


@pytest.mark.asyncio
async def test_get_analyst_audit_profile_metrics_and_governance(
    audit_app: tuple[FastAPI, CaseService],
) -> None:
    app, service = audit_app
    analyst_id = "analyst-001"
    org_id = "018f2f4e-0000-7000-8000-000000000001"

    # Seed an analyst principal
    service._principals[analyst_id] = {
        "id": analyst_id,
        "display_name": "Nguyễn Hoàng Nam",
        "roles": ["fraud_analyst", "analyst"],
        "organization_id": org_id,
    }

    # Seed past cases with adjudications
    now = datetime.now(UTC)
    case_id_1 = "case-audit-01"
    service._cases[case_id_1] = {
        "id": case_id_1,
        "organization_id": org_id,
        "status": "resolved",
        "driver_id": "drv-01",
        "driver_name": "Nguyễn Văn Tuấn",
        "vehicle_plate": "30A-123.45",
        "priority_tier": 1,
        "priority_score": 85,
        "suspected_category": "ERR-02",
        "created_at": now - timedelta(hours=2),
        "updated_at": now - timedelta(hours=1),
        "assigned_analyst_id": analyst_id,
        "version": 2,
    }
    service._adjudications.append(
        {
            "id": "adj-01",
            "case_id": case_id_1,
            "analyst_id": analyst_id,
            "outcome": "AGREE",
            "rationale": "Stationary duration confirmed above threshold",
            "approved_at": now - timedelta(hours=1),
            "created_at": now - timedelta(hours=1),
            "organization_id": org_id,
        }
    )

    principal = Principal(
        id=analyst_id,
        roles={"fraud_analyst", "analyst"},
        organization_id=org_id,
    )
    app.dependency_overrides[require_principal] = lambda: principal

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/v1/analyst/audit")
        assert resp.status_code == 200, resp.text
        data = resp.json()

        assert data["analyst_id"] == analyst_id
        assert data["display_name"] == "Nguyễn Hoàng Nam"
        assert "fraud_analyst" in data["roles"]

        # Metrics check
        metrics = data["metrics"]
        assert metrics["today_decisions_count"] == 1
        assert metrics["thirty_day_decisions_count"] == 1
        assert metrics["average_mttr_seconds"] is not None
        assert metrics["average_mttr_seconds"] > 0

        # Governance limits check
        gov = data["governance_limits"]
        assert gov["dismiss_authority"] == "Unrestricted"
        assert gov["warning_authority"] == "Authorized"
        assert gov["direct_fine_limit_vnd"] > 0

        # Ledger check
        ledger = data["ledger"]
        assert len(ledger) == 1
        assert ledger[0]["case_id"] == case_id_1
        assert ledger[0]["verdict"] == "AGREE"
        assert "Nguyễn Văn Tuấn" in ledger[0]["subject_entity"]


@pytest.mark.asyncio
async def test_get_analyst_audit_ledger_search_and_filter(
    audit_app: tuple[FastAPI, CaseService],
) -> None:
    app, service = audit_app
    analyst_id = "analyst-002"
    org_id = "018f2f4e-0000-7000-8000-000000000001"
    now = datetime.now(UTC)

    service._principals[analyst_id] = {
        "id": analyst_id,
        "display_name": "Lê Văn Hùng",
        "roles": ["senior_analyst", "analyst"],
        "organization_id": org_id,
    }

    # Seed 2 cases: one approved, one dismissed
    service._cases["c-1"] = {
        "id": "c-1",
        "organization_id": org_id,
        "status": "resolved",
        "driver_name": "Trần Đức Bình",
        "vehicle_plate": "29E-888.88",
        "suspected_category": "ERR-02",
        "assigned_analyst_id": analyst_id,
        "created_at": now - timedelta(hours=3),
        "version": 1,
    }
    service._adjudications.append(
        {
            "id": "adj-1",
            "case_id": "c-1",
            "analyst_id": analyst_id,
            "outcome": "AGREE",
            "rationale": "Intentional delay verified",
            "approved_at": now - timedelta(hours=2),
            "organization_id": org_id,
        }
    )

    service._cases["c-2"] = {
        "id": "c-2",
        "organization_id": org_id,
        "status": "dismissed",
        "driver_name": "Phạm Văn Cường",
        "vehicle_plate": "51A-999.99",
        "suspected_category": "ERR-05",
        "assigned_analyst_id": analyst_id,
        "created_at": now - timedelta(hours=2),
        "version": 1,
    }
    service._adjudications.append(
        {
            "id": "adj-2",
            "case_id": "c-2",
            "analyst_id": analyst_id,
            "outcome": "DISAGREE",
            "rationale": "Traffic jam corroborated by TomTom peers",
            "approved_at": now - timedelta(hours=1),
            "organization_id": org_id,
        }
    )

    principal = Principal(
        id=analyst_id,
        roles={"senior_analyst", "analyst"},
        organization_id=org_id,
    )
    app.dependency_overrides[require_principal] = lambda: principal

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Search by driver plate
        resp = await client.get("/api/v1/analyst/audit?search=29E-888")
        assert resp.status_code == 200
        items = resp.json()["ledger"]
        assert len(items) == 1
        assert items[0]["case_id"] == "c-1"

        # Filter by verdict DISAGREE
        resp2 = await client.get("/api/v1/analyst/audit?verdict=DISAGREE")
        assert resp2.status_code == 200
        items2 = resp2.json()["ledger"]
        assert len(items2) == 1
        assert items2[0]["case_id"] == "c-2"


@pytest.mark.asyncio
async def test_get_analyst_audit_active_lease_banner(
    audit_app: tuple[FastAPI, CaseService],
) -> None:
    app, service = audit_app
    analyst_id = "analyst-003"
    org_id = "018f2f4e-0000-7000-8000-000000000001"
    now = datetime.now(UTC)

    service._principals[analyst_id] = {
        "id": analyst_id,
        "display_name": "Trần Thị Mai",
        "roles": ["fraud_analyst"],
        "organization_id": org_id,
    }

    # Case currently claimed by analyst
    active_case_id = "case-active-lock"
    service._cases[active_case_id] = {
        "id": active_case_id,
        "organization_id": org_id,
        "status": "in_review",
        "driver_name": "Bùi Văn Nam",
        "vehicle_plate": "30F-555.55",
        "priority_tier": 0,
        "assigned_analyst_id": analyst_id,
        "created_at": now - timedelta(minutes=10),
        "version": 1,
    }
    service._leases[active_case_id] = {
        "analyst_id": analyst_id,
        "acquired_at": now - timedelta(minutes=2),
        "expires_at": now + timedelta(minutes=3),
    }

    principal = Principal(
        id=analyst_id,
        roles={"fraud_analyst"},
        organization_id=org_id,
    )
    app.dependency_overrides[require_principal] = lambda: principal

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/v1/analyst/audit")
        assert resp.status_code == 200
        data = resp.json()

        active_lease = data["active_lease"]
        assert active_lease is not None
        assert active_lease["case_id"] == active_case_id
        assert active_lease["severity"] == "P0"
        assert active_lease["remaining_seconds"] > 0
        assert "Bùi Văn Nam" in active_lease["driver_name"]


@pytest.mark.asyncio
async def test_get_analyst_audit_rbac_authorization(
    audit_app: tuple[FastAPI, CaseService],
) -> None:
    app, _ = audit_app
    org_id = "018f2f4e-0000-7000-8000-000000000001"

    # Driver role only should be forbidden
    driver_principal = Principal(
        id="drv-user-01",
        roles={"driver"},
        organization_id=org_id,
        driver_id="drv-01",
    )
    app.dependency_overrides[require_principal] = lambda: driver_principal

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/v1/analyst/audit")
        assert resp.status_code == 403


@pytest.mark.asyncio
async def test_get_analyst_audit_tenant_isolation(
    audit_app: tuple[FastAPI, CaseService],
) -> None:
    app, service = audit_app
    org_a = "018f2f4e-0000-7000-8000-000000000001"
    org_b = "018f2f4e-0000-7000-8000-000000000002"
    now = datetime.now(UTC)

    # Analyst in Org A
    analyst_a = "analyst-org-a"
    service._principals[analyst_a] = {
        "id": analyst_a,
        "display_name": "Org A Analyst",
        "roles": ["analyst"],
        "organization_id": org_a,
    }

    # Case & Adjudication in Org B (should never leak to Org A)
    service._cases["case-b"] = {
        "id": "case-b",
        "organization_id": org_b,
        "status": "resolved",
        "assigned_analyst_id": "other-analyst",
        "created_at": now,
        "version": 1,
    }
    service._adjudications.append(
        {
            "id": "adj-b",
            "case_id": "case-b",
            "analyst_id": "other-analyst",
            "outcome": "AGREE",
            "rationale": "Secret case in Org B",
            "approved_at": now,
            "organization_id": org_b,
        }
    )

    principal_a = Principal(
        id=analyst_a,
        roles={"analyst"},
        organization_id=org_a,
    )
    app.dependency_overrides[require_principal] = lambda: principal_a

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/v1/analyst/audit")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["ledger"]) == 0
        assert data["metrics"]["today_decisions_count"] == 0

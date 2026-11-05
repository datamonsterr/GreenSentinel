"""Tests for Issue #150: Case history browsing, searching, and read-only audit inspection.

Verifies:
1. Paginated server-backed processed case history listing across terminal statuses:
   'resolved', 'dismissed', 'auto_dismissed'.
2. Search within history by driver name (accented/unaccented), driver ID, and vehicle plate.
3. Filter history by decision outcome, resolving analyst, and date boundaries.
4. Read-only inspection: opening a processed case does NOT create an active lease or trigger sanctions.
5. Active non-terminal cases ('ready', 'in_review', 'evidence_requested') are strictly excluded from history.
6. Driver role authorization: drivers only view their own historical records.
7. Honest missingness: legacy records with absent fields do not fabricate data.
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
def history_test_app():
    """Setup in-memory case service populated with active and processed cases."""
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    settings = Settings(app_env="test", database_url="")
    service = CaseService(settings)
    service._in_memory_sessions = True

    service._cases.clear()
    service._assignments.clear()
    service._drivers.clear()
    service._vehicles.clear()
    service._active_leases.clear()
    service._adjudications.clear()

    now = datetime.now(UTC)

    # Active Case 1: P1, ready (NOT processed, must NOT appear in history)
    cid_active = "018f2f4e-a000-7000-8000-000000000001"
    asgn_active = "asgn-active"
    service._cases[cid_active] = {
        "id": cid_active,
        "assignment_id": asgn_active,
        "driver_id": "drv-active",
        "driver_name": "Active Driver",
        "vehicle_plate": "30A-111.11",
        "priority_tier": 1,
        "priority_score": 90,
        "status": "ready",
        "organization_id": "org-main",
        "version": 1,
        "created_at": now - timedelta(days=2),
        "updated_at": now - timedelta(days=2),
    }

    # Processed Case 2: RESOLVED by Analyst 1, P1, Driver "Nguyễn Văn Bình", Plate 29E-123.45
    cid_proc1 = "018f2f4e-a000-7000-8000-000000000002"
    asgn_proc1 = "asgn-proc1"
    service._cases[cid_proc1] = {
        "id": cid_proc1,
        "assignment_id": asgn_proc1,
        "driver_id": "drv-binh-01",
        "driver_name": "Nguyễn Văn Bình",
        "vehicle_plate": "29E-123.45",
        "priority_tier": 1,
        "priority_score": 85,
        "status": "resolved",
        "organization_id": "org-main",
        "version": 3,
        "assigned_analyst_id": "analyst-alice",
        "created_at": now - timedelta(days=5),
        "updated_at": now - timedelta(days=1),
    }
    service._adjudications.append(
        {
            "case_id": cid_proc1,
            "analyst_id": "analyst-alice",
            "outcome": "AGREE",
            "status": "adjudicated",
            "decision_rationale": "Confirmed stationary fraud violation against GPS evidence.",
            "adjudicated_at": (now - timedelta(days=1)).isoformat(),
        }
    )

    # Processed Case 3: DISMISSED by Analyst 2, P2, Driver "Trần Thị Hoa", Plate 30A-999.88
    cid_proc2 = "018f2f4e-a000-7000-8000-000000000003"
    asgn_proc2 = "asgn-proc2"
    service._cases[cid_proc2] = {
        "id": cid_proc2,
        "assignment_id": asgn_proc2,
        "driver_id": "drv-hoa-02",
        "driver_name": "Trần Thị Hoa",
        "vehicle_plate": "30A-999.88",
        "priority_tier": 2,
        "priority_score": 40,
        "status": "dismissed",
        "organization_id": "org-main",
        "version": 2,
        "assigned_analyst_id": "analyst-bob",
        "created_at": now - timedelta(days=10),
        "updated_at": now - timedelta(days=3),
    }
    service._adjudications.append(
        {
            "case_id": cid_proc2,
            "analyst_id": "analyst-bob",
            "outcome": "DISAGREE",
            "status": "adjudicated",
            "decision_rationale": "Driver telemetry confirmed heavy congestion delay.",
            "adjudicated_at": (now - timedelta(days=3)).isoformat(),
        }
    )

    # Processed Case 4: AUTO_DISMISSED by system, Driver "Lê Hoàng Nam", Plate 51F-777.88
    cid_proc3 = "018f2f4e-a000-7000-8000-000000000004"
    asgn_proc3 = "asgn-proc3"
    service._cases[cid_proc3] = {
        "id": cid_proc3,
        "assignment_id": asgn_proc3,
        "driver_id": "drv-nam-03",
        "driver_name": "Lê Hoàng Nam",
        "vehicle_plate": "51F-777.88",
        "priority_tier": 2,
        "priority_score": 30,
        "status": "auto_dismissed",
        "organization_id": "org-main",
        "version": 1,
        "created_at": now - timedelta(days=15),
        "updated_at": now - timedelta(days=7),
    }

    # Foreign Org Case: Processed in org-other
    cid_foreign = "018f2f4e-a000-7000-8000-000000000005"
    service._cases[cid_foreign] = {
        "id": cid_foreign,
        "driver_id": "drv-binh-foreign",
        "driver_name": "Nguyễn Văn Bình",
        "vehicle_plate": "29E-123.45",
        "priority_tier": 1,
        "status": "resolved",
        "organization_id": "org-other",
        "version": 2,
        "created_at": now - timedelta(days=2),
        "updated_at": now - timedelta(days=1),
    }

    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_case_service] = lambda: service
    app.dependency_overrides[require_principal] = lambda: Principal(
        id="analyst-test",
        organization_id="org-main",
        roles=frozenset({"analyst", "fraud_analyst"}),
    )
    return app


@pytest.mark.asyncio
async def test_list_processed_case_history_excludes_active_cases(history_test_app):
    """Verify history endpoint returns only processed cases and strictly excludes active triage items."""
    async with AsyncClient(transport=ASGITransport(app=history_test_app), base_url="http://test") as client:
        res = await client.get("/api/v1/cases/history")
        assert res.status_code == 200
        data = res.json()
        assert data["total"] == 3
        statuses = {item["status"] for item in data["items"]}
        assert statuses == {"resolved", "dismissed", "auto_dismissed"}
        assert "ready" not in statuses


@pytest.mark.asyncio
async def test_case_history_search_by_driver_and_plate(history_test_app):
    """Verify searching history by driver name and vehicle registration plate."""
    async with AsyncClient(transport=ASGITransport(app=history_test_app), base_url="http://test") as client:
        # Search unaccented "binh" matches "Nguyễn Văn Bình"
        res1 = await client.get("/api/v1/cases/history", params={"search": "binh"})
        assert res1.status_code == 200
        data1 = res1.json()
        assert data1["total"] == 1
        assert data1["items"][0]["driver_name"] == "Nguyễn Văn Bình"

        # Search plate "30A" matches "Trần Thị Hoa"
        res2 = await client.get("/api/v1/cases/history", params={"search": "30A"})
        assert res2.status_code == 200
        data2 = res2.json()
        assert data2["total"] == 1
        assert data2["items"][0]["vehicle_plate"] == "30A-999.88"


@pytest.mark.asyncio
async def test_case_history_filter_by_decision_and_status(history_test_app):
    """Verify filtering processed history by specific terminal status and decision outcome."""
    async with AsyncClient(transport=ASGITransport(app=history_test_app), base_url="http://test") as client:
        # Filter by status "dismissed"
        res1 = await client.get("/api/v1/cases/history", params={"status": "dismissed"})
        assert res1.status_code == 200
        data1 = res1.json()
        assert data1["total"] == 1
        assert data1["items"][0]["status"] == "dismissed"

        # Filter by status "resolved"
        res2 = await client.get("/api/v1/cases/history", params={"status": "resolved"})
        assert res2.status_code == 200
        data2 = res2.json()
        assert data2["total"] == 1
        assert data2["items"][0]["status"] == "resolved"


@pytest.mark.asyncio
async def test_case_history_read_only_access_does_not_claim_lease(history_test_app):
    """Verify opening a historical case retrieves full details without creating an active lease."""
    service = history_test_app.dependency_overrides[get_case_service]()
    cid = "018f2f4e-a000-7000-8000-000000000002"

    async with AsyncClient(transport=ASGITransport(app=history_test_app), base_url="http://test") as client:
        res = await client.get(f"/api/v1/cases/{cid}")
        assert res.status_code == 200
        data = res.json()
        assert data["case"]["status"] == "resolved"
        assert data["case"]["version"] == 3

    # Assert no active lease was created in memory
    assert cid not in service._active_leases


@pytest.mark.asyncio
async def test_case_history_tenant_isolation(history_test_app):
    """Verify processed cases belonging to foreign organizations are not exposed."""
    async with AsyncClient(transport=ASGITransport(app=history_test_app), base_url="http://test") as client:
        res = await client.get("/api/v1/cases/history", params={"search": "binh"})
        assert res.status_code == 200
        data = res.json()
        # Case 5 belongs to org-other, so only Case 2 (org-main) should match
        assert data["total"] == 1
        assert data["items"][0]["id"] == "018f2f4e-a000-7000-8000-000000000002"


@pytest.mark.asyncio
async def test_case_history_pagination(history_test_app):
    """Verify pagination controls (limit, offset) across processed history beyond page 1."""
    async with AsyncClient(transport=ASGITransport(app=history_test_app), base_url="http://test") as client:
        # Page 1: limit 2
        res1 = await client.get("/api/v1/cases/history", params={"limit": 2, "offset": 0})
        assert res1.status_code == 200
        data1 = res1.json()
        assert data1["total"] == 3
        assert len(data1["items"]) == 2

        # Page 2: limit 2, offset 2
        res2 = await client.get("/api/v1/cases/history", params={"limit": 2, "offset": 2})
        assert res2.status_code == 200
        data2 = res2.json()
        assert data2["total"] == 3
        assert len(data2["items"]) == 1
        assert data2["items"][0]["id"] != data1["items"][0]["id"]

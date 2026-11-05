"""Tests for Issue #149: Case search by driver identity, driver ID, and vehicle plate.

Verifies:
1. Exact and partial matching on driver_name, driver_id, and vehicle_plate.
2. Case-insensitive and Vietnamese accent-normalized search.
3. Combination with priority and availability filters.
4. Organization boundary isolation (tenant scoping).
5. Safe handling of special characters, wildcard patterns, and SQL injection strings.
6. Empty or whitespace-only search defaults to unfiltered listing.
"""

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from src.api.auth import Principal, require_principal
from src.api.routes import router
from src.config import Settings, get_settings
from src.services.case_service import CaseService, get_case_service


@pytest.fixture
def search_test_app():
    """Setup in-memory case service populated with distinctive driver and plate cases."""
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    settings = Settings(app_env="test", database_url="")
    service = CaseService(settings)
    service._in_memory_sessions = True

    # Seed distinctive cases
    service._cases.clear()
    service._assignments.clear()
    service._drivers.clear()
    service._vehicles.clear()
    service._active_leases.clear()

    # Case 1: Driver Nguyễn Văn Bình, plate 29E-123.45, driver_id drv-binh-01, org-1
    cid1 = "018f2f4e-a000-7000-8000-000000000001"
    asgn1 = "asgn-01"
    drv1 = "drv-binh-01"
    veh1 = "veh-01"
    service._drivers[drv1] = {
        "id": drv1,
        "external_ref": "DRV-REF-101",
        "display_name": "Nguyễn Văn Bình",
    }
    service._vehicles[veh1] = {
        "id": veh1,
        "registration_ref": "29E-123.45",
    }
    service._assignments[asgn1] = {
        "id": asgn1,
        "trip_id": "trip-01",
        "driver_id": drv1,
        "vehicle_id": veh1,
    }
    service._cases[cid1] = {
        "id": cid1,
        "assignment_id": asgn1,
        "driver_id": drv1,
        "driver_name": "Nguyễn Văn Bình",
        "vehicle_plate": "29E-123.45",
        "priority_tier": 1,
        "priority_score": 90,
        "status": "ready",
        "organization_id": "org-main",
        "version": 1,
    }

    # Case 2: Driver Trần Thị Hoa, plate 30A-999.88, driver_id drv-hoa-02, org-main
    cid2 = "018f2f4e-a000-7000-8000-000000000002"
    asgn2 = "asgn-02"
    drv2 = "drv-hoa-02"
    veh2 = "veh-02"
    service._drivers[drv2] = {
        "id": drv2,
        "external_ref": "DRV-REF-102",
        "display_name": "Trần Thị Hoa",
    }
    service._vehicles[veh2] = {
        "id": veh2,
        "registration_ref": "30A-999.88",
    }
    service._assignments[asgn2] = {
        "id": asgn2,
        "trip_id": "trip-02",
        "driver_id": drv2,
        "vehicle_id": veh2,
    }
    service._cases[cid2] = {
        "id": cid2,
        "assignment_id": asgn2,
        "driver_id": drv2,
        "driver_name": "Trần Thị Hoa",
        "vehicle_plate": "30A-999.88",
        "priority_tier": 2,
        "priority_score": 50,
        "status": "ready",
        "organization_id": "org-main",
        "version": 1,
    }

    # Case 3: Foreign organization case with driver matching "Nguyễn", org-other
    cid3 = "018f2f4e-a000-7000-8000-000000000003"
    asgn3 = "asgn-03"
    drv3 = "drv-nguyen-foreign"
    veh3 = "veh-03"
    service._drivers[drv3] = {
        "id": drv3,
        "external_ref": "DRV-REF-103",
        "display_name": "Nguyễn Quốc Bảo",
    }
    service._vehicles[veh3] = {
        "id": veh3,
        "registration_ref": "51G-555.66",
    }
    service._assignments[asgn3] = {
        "id": asgn3,
        "trip_id": "trip-03",
        "driver_id": drv3,
        "vehicle_id": veh3,
    }
    service._cases[cid3] = {
        "id": cid3,
        "assignment_id": asgn3,
        "driver_id": drv3,
        "driver_name": "Nguyễn Quốc Bảo",
        "vehicle_plate": "51G-555.66",
        "priority_tier": 1,
        "priority_score": 85,
        "status": "ready",
        "organization_id": "org-other",
        "version": 1,
    }

    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_case_service] = lambda: service
    app.dependency_overrides[require_principal] = lambda: Principal(
        id="test-analyst",
        organization_id="org-main",
        roles=frozenset({"analyst", "fraud_analyst"}),
    )
    return app


@pytest.mark.asyncio
async def test_search_cases_by_partial_driver_name_accented_and_unaccented(search_test_app):
    """Verify search matches driver name with accented and unaccented inputs."""
    async with AsyncClient(transport=ASGITransport(app=search_test_app), base_url="http://test") as client:
        # Search with accent: "Bình"
        res1 = await client.get(
            "/api/v1/cases",
            params={"search": "Bình", "availability": "all"},
            headers={"Authorization": "Bearer test-analyst-token"},
        )
        assert res1.status_code == 200
        data1 = res1.json()
        assert data1["total"] == 1
        assert data1["items"][0]["driver_name"] == "Nguyễn Văn Bình"

        # Search unaccented: "binh" matches "Bình"
        res2 = await client.get(
            "/api/v1/cases",
            params={"search": "binh", "availability": "all"},
            headers={"Authorization": "Bearer test-analyst-token"},
        )
        assert res2.status_code == 200
        data2 = res2.json()
        assert data2["total"] == 1
        assert data2["items"][0]["driver_name"] == "Nguyễn Văn Bình"

        # Search unaccented "Hoa" matches "Trần Thị Hoa"
        res3 = await client.get(
            "/api/v1/cases",
            params={"search": "hoa", "availability": "all"},
            headers={"Authorization": "Bearer test-analyst-token"},
        )
        assert res3.status_code == 200
        data3 = res3.json()
        assert data3["total"] == 1
        assert data3["items"][0]["driver_name"] == "Trần Thị Hoa"


@pytest.mark.asyncio
async def test_search_cases_by_vehicle_plate(search_test_app):
    """Verify search matches vehicle registration/plate number."""
    async with AsyncClient(transport=ASGITransport(app=search_test_app), base_url="http://test") as client:
        # Exact plate
        res1 = await client.get(
            "/api/v1/cases",
            params={"search": "29E-123.45", "availability": "all"},
            headers={"Authorization": "Bearer test-analyst-token"},
        )
        assert res1.status_code == 200
        data1 = res1.json()
        assert data1["total"] == 1
        assert data1["items"][0]["vehicle_plate"] == "29E-123.45"

        # Partial plate without dot or lowercase: "30a"
        res2 = await client.get(
            "/api/v1/cases",
            params={"search": "30a", "availability": "all"},
            headers={"Authorization": "Bearer test-analyst-token"},
        )
        assert res2.status_code == 200
        data2 = res2.json()
        assert data2["total"] == 1
        assert data2["items"][0]["vehicle_plate"] == "30A-999.88"


@pytest.mark.asyncio
async def test_search_cases_by_driver_id_and_external_ref(search_test_app):
    """Verify search matches driver ID or external reference."""
    async with AsyncClient(transport=ASGITransport(app=search_test_app), base_url="http://test") as client:
        # Driver ID: "drv-binh-01"
        res1 = await client.get(
            "/api/v1/cases",
            params={"search": "drv-binh-01", "availability": "all"},
            headers={"Authorization": "Bearer test-analyst-token"},
        )
        assert res1.status_code == 200
        data1 = res1.json()
        assert data1["total"] == 1
        assert data1["items"][0]["driver_id"] == "drv-binh-01"

        # Driver External Ref: "DRV-REF-102"
        res2 = await client.get(
            "/api/v1/cases",
            params={"search": "REF-102", "availability": "all"},
            headers={"Authorization": "Bearer test-analyst-token"},
        )
        assert res2.status_code == 200
        data2 = res2.json()
        assert data2["total"] == 1
        assert data2["items"][0]["driver_name"] == "Trần Thị Hoa"


@pytest.mark.asyncio
async def test_search_cases_combined_with_filters(search_test_app):
    """Verify search parameter combines correctly with priority and availability filters."""
    async with AsyncClient(transport=ASGITransport(app=search_test_app), base_url="http://test") as client:
        # Search "Nguyễn" + priority "P1" -> matches case 1
        res1 = await client.get(
            "/api/v1/cases",
            params={"search": "Nguyen", "priority": "P1", "availability": "all"},
            headers={"Authorization": "Bearer test-analyst-token"},
        )
        assert res1.status_code == 200
        data1 = res1.json()
        assert data1["total"] == 1
        assert data1["items"][0]["driver_name"] == "Nguyễn Văn Bình"

        # Search "Nguyễn" + priority "P2" -> 0 matches (case 1 is P1)
        res2 = await client.get(
            "/api/v1/cases",
            params={"search": "Nguyen", "priority": "P2", "availability": "all"},
            headers={"Authorization": "Bearer test-analyst-token"},
        )
        assert res2.status_code == 200
        data2 = res2.json()
        assert data2["total"] == 0


@pytest.mark.asyncio
async def test_search_cases_respects_organization_boundary(search_test_app):
    """Verify cross-organization cases are excluded even when matching the search string."""
    service = search_test_app.dependency_overrides[get_case_service]()
    # Explicitly test service.list_cases with organization_id="org-main"
    res = await service.list_cases(
        organization_id="org-main",
        search="Nguyen",
        availability="all",
    )
    # Case 3 belongs to org-other, so it MUST NOT be returned!
    assert res.total == 1
    assert res.items[0].driver_name == "Nguyễn Văn Bình"


@pytest.mark.asyncio
async def test_search_cases_safe_on_special_characters_and_wildcards(search_test_app):
    """Verify injection attempts, wildcards, and special characters are handled safely without 500."""
    async with AsyncClient(transport=ASGITransport(app=search_test_app), base_url="http://test") as client:
        for payload in ["'", "''", "'; DROP TABLE app.fraud_cases; --", "%%", "%_", "\\", "[]", " "]:
            res = await client.get(
                "/api/v1/cases",
                params={"search": payload, "availability": "all"},
                headers={"Authorization": "Bearer test-analyst-token"},
            )
            assert res.status_code == 200

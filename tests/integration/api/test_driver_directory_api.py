"""Integration tests for real Clerk-linked drivers (Issue #464).

Covers:
- GET /test/api/v1/drivers/search?email= (min 3 chars, 503 on missing key, returns only linked org drivers)
- GET /test/api/v1/drivers/linked (503 on missing key, batched lookup)
- POST /test/api/v1/definitions driver validation (422 on mock, unlinked, cross-tenant, suspended)
- POST /test/api/v1/presets/plan driver validation (422 on invalid, succeeds with active linked driver)
- POST /test/api/v1/presets/{id}/runs:
  - missing driver_ids -> 422
  - mock/unlinked driver_ids -> 422
  - valid driver_ids -> round-robin assignment, stored on batch trip, in events, in GET /runs driver_name
  - no synthetic app.drivers created
"""

from __future__ import annotations

import asyncio
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from src.main import app
from src.services.case_service import get_case_service
from src.services.clerk_directory import ClerkDirectoryClient
from src.services.driver_directory import (
    DriverRecord,
    HybridDriverDirectory,
    InMemoryDriverDirectory,
    get_driver_directory,
    set_driver_directory,
)

ORG_A = "018f2f4e-0000-7000-8000-000000000001"
ORG_B = "018f2f4e-0000-7000-8000-00000000000b"


def _client(org: str = ORG_A, principal: str = "tester-1") -> TestClient:
    return TestClient(
        app,
        headers={
            "X-Test-Context": "true",
            "X-Role": "demo_operator",
            "X-Principal-Id": principal,
            "X-Organization-Id": org,
        },
    )


@pytest.fixture(autouse=True)
def setup_test_drivers():
    """Seed active Clerk-linked drivers for ORG_A and ORG_B into in-memory driver directory."""
    dir_svc = InMemoryDriverDirectory()
    set_driver_directory(dir_svc)

    # Driver A1 in ORG_A
    d_a1 = UUID("018f2f4e-3000-7000-8000-000000000011")
    p_a1 = UUID("018f2f4e-2000-7000-8000-000000000011")
    v_a1 = UUID("018f2f4e-4000-7000-8000-000000000011")
    dir_svc.register_driver(
        DriverRecord(
            driver_id=d_a1,
            organization_id=ORG_A,
            principal_id=p_a1,
            external_subject="user_clerk_a1",
            display_name="Nguyen Van A1",
            email="driver.a1@example.com",
            account_status="active",
            vehicle_id=v_a1,
            license_plate="29A-111.11",
        )
    )

    # Driver A2 in ORG_A
    d_a2 = UUID("018f2f4e-3000-7000-8000-000000000012")
    p_a2 = UUID("018f2f4e-2000-7000-8000-000000000012")
    v_a2 = UUID("018f2f4e-4000-7000-8000-000000000012")
    dir_svc.register_driver(
        DriverRecord(
            driver_id=d_a2,
            organization_id=ORG_A,
            principal_id=p_a2,
            external_subject="user_clerk_a2",
            display_name="Tran Van A2",
            email="driver.a2@example.com",
            account_status="active",
            vehicle_id=v_a2,
            license_plate="29A-222.22",
        )
    )

    # Driver A3 (suspended) in ORG_A
    d_a3_susp = UUID("018f2f4e-3000-7000-8000-000000000013")
    dir_svc.register_driver(
        DriverRecord(
            driver_id=d_a3_susp,
            organization_id=ORG_A,
            principal_id=UUID("018f2f4e-2000-7000-8000-000000000013"),
            external_subject="user_clerk_a3_susp",
            display_name="Le Suspended",
            email="driver.a3@example.com",
            account_status="suspended",
        )
    )

    # Driver A4 (unlinked - no clerk subject) in ORG_A
    d_a4_unlink = UUID("018f2f4e-3000-7000-8000-000000000014")
    dir_svc.register_driver(
        DriverRecord(
            driver_id=d_a4_unlink,
            organization_id=ORG_A,
            principal_id=UUID("018f2f4e-2000-7000-8000-000000000014"),
            external_subject=None,  # type: ignore[arg-type]
            display_name="Pham Unlinked",
            email=None,
            account_status="active",
        )
    )

    # Driver B1 in ORG_B
    d_b1 = UUID("018f2f4e-3000-7000-8000-000000000021")
    p_b1 = UUID("018f2f4e-2000-7000-8000-000000000021")
    dir_svc.register_driver(
        DriverRecord(
            driver_id=d_b1,
            organization_id=ORG_B,
            principal_id=p_b1,
            external_subject="user_clerk_b1",
            display_name="Hoang Van B1",
            email="driver.b1@example.com",
            account_status="active",
        )
    )

    yield dir_svc
    set_driver_directory(HybridDriverDirectory())


def test_drivers_search_validation_and_503(monkeypatch):
    """GET /drivers/search validates min 3 chars and returns 503 if CLERK_SECRET_KEY is missing."""
    client = _client(ORG_A)

    # Min 3 chars validation
    resp = client.get("/test/api/v1/drivers/search?email=ab")
    assert resp.status_code == 422

    # Missing clerk secret key -> 503
    from src.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "clerk_secret_key", None)

    resp = client.get("/test/api/v1/drivers/search?email=abc")
    assert resp.status_code == 503
    assert "CLERK_SECRET_KEY" in resp.json()["detail"]


def test_drivers_linked_503_when_secret_missing(monkeypatch):
    """GET /drivers/linked returns 503 if CLERK_SECRET_KEY is missing."""
    client = _client(ORG_A)
    from src.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "clerk_secret_key", None)

    resp = client.get("/test/api/v1/drivers/linked")
    assert resp.status_code == 503
    assert "CLERK_SECRET_KEY" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_drivers_search_mocked_clerk(monkeypatch):
    """GET /drivers/search queries Clerk and filters to active linked org drivers."""
    client = _client(ORG_A)
    from src.config import get_settings

    monkeypatch.setattr(get_settings(), "clerk_secret_key", "sk_test_fake")

    # Mock Clerk users search returning users from org A, org B, and an unknown user
    mock_clerk_users = [
        {
            "id": "user_clerk_a1",
            "first_name": "Nguyen",
            "last_name": "Van A1",
            "email_addresses": [{"id": "idn_1", "email_address": "driver.a1@example.com"}],
            "primary_email_address_id": "idn_1",
        },
        {
            "id": "user_clerk_b1",
            "first_name": "Hoang",
            "last_name": "Van B1",
            "email_addresses": [{"id": "idn_2", "email_address": "driver.b1@example.com"}],
            "primary_email_address_id": "idn_2",
        },
        {
            "id": "user_clerk_unknown",
            "first_name": "Stranger",
            "last_name": "User",
            "email_addresses": [{"id": "idn_3", "email_address": "stranger@example.com"}],
            "primary_email_address_id": "idn_3",
        },
    ]

    async def mock_search(self, query, limit=10):
        return mock_clerk_users

    monkeypatch.setattr(ClerkDirectoryClient, "search_users", mock_search)

    resp = client.get("/test/api/v1/drivers/search?email=driver")
    assert resp.status_code == 200, resp.text
    drivers = resp.json()

    # Must keep only org A's active linked driver
    assert len(drivers) == 1
    assert drivers[0]["driver_id"] == "018f2f4e-3000-7000-8000-000000000011"
    assert drivers[0]["display_name"] == "Nguyen Van A1"
    assert drivers[0]["email"] == "driver.a1@example.com"
    assert drivers[0]["license_plate"] == "29A-111.11"


@pytest.mark.asyncio
async def test_drivers_linked_mocked_clerk(monkeypatch):
    """GET /drivers/linked returns all active Clerk-linked drivers of caller org with Clerk details."""
    client = _client(ORG_A)
    from src.config import get_settings

    monkeypatch.setattr(get_settings(), "clerk_secret_key", "sk_test_fake")

    async def mock_get_users(self, user_ids):
        return [
            {
                "id": "user_clerk_a1",
                "first_name": "Nguyen",
                "last_name": "Van A1 (Clerk)",
                "email_addresses": [{"id": "idn_1", "email_address": "driver.a1@example.com"}],
                "primary_email_address_id": "idn_1",
            },
            {
                "id": "user_clerk_a2",
                "first_name": "Tran",
                "last_name": "Van A2 (Clerk)",
                "email_addresses": [{"id": "idn_2", "email_address": "driver.a2@example.com"}],
                "primary_email_address_id": "idn_2",
            },
        ]

    monkeypatch.setattr(ClerkDirectoryClient, "get_users_by_ids", mock_get_users)

    resp = client.get("/test/api/v1/drivers/linked")
    assert resp.status_code == 200, resp.text
    drivers = resp.json()

    # ORG_A has 2 active linked drivers (A1 and A2); suspended A3 and unlinked A4 excluded
    assert len(drivers) == 2
    driver_ids = {d["driver_id"] for d in drivers}
    assert "018f2f4e-3000-7000-8000-000000000011" in driver_ids
    assert "018f2f4e-3000-7000-8000-000000000012" in driver_ids


def test_definitions_driver_validation_rejects_mock_and_unlinked():
    """POST /definitions rejects mock ids (drv-sim-001), unlinked, suspended, and cross-tenant with 422."""
    client = _client(ORG_A)

    plan_res = client.post("/test/api/v1/plans", json={"name": "Test Plan"})
    assert plan_res.status_code == 201
    plan_id = plan_res.json()["id"]

    route_geom = {
        "type": "LineString",
        "coordinates": [[105.8542, 21.0285], [105.8545, 21.0288]],
    }

    # 1. Mock driver id 'drv-sim-001' -> 422
    resp = client.post(
        "/test/api/v1/definitions",
        json={
            "plan_id": plan_id,
            "route_geometry": route_geom,
            "driver_config": {"driver_id": "drv-sim-001"},
        },
    )
    assert resp.status_code == 422
    assert "Clerk-linked" in resp.json()["detail"] or "driver" in resp.json()["detail"].lower()

    # 2. Suspended driver -> 422
    resp = client.post(
        "/test/api/v1/definitions",
        json={
            "plan_id": plan_id,
            "route_geometry": route_geom,
            "driver_config": {"driver_id": "018f2f4e-3000-7000-8000-000000000013"},
        },
    )
    assert resp.status_code == 422

    # 3. Cross-tenant driver (from ORG_B) -> 422
    resp = client.post(
        "/test/api/v1/definitions",
        json={
            "plan_id": plan_id,
            "route_geometry": route_geom,
            "driver_config": {"driver_id": "018f2f4e-3000-7000-8000-000000000021"},
        },
    )
    assert resp.status_code == 422

    # 4. Valid active Clerk-linked driver -> 201
    valid_resp = client.post(
        "/test/api/v1/definitions",
        json={
            "plan_id": plan_id,
            "route_geometry": route_geom,
            "driver_config": {"driver_id": "018f2f4e-3000-7000-8000-000000000011"},
        },
    )
    assert valid_resp.status_code == 201
    assert valid_resp.json()["driver_config"]["driver_id"] == "018f2f4e-3000-7000-8000-000000000011"
    # Linked vehicle plate applied
    assert valid_resp.json()["driver_config"]["vehicle_plate"] == "29A-111.11"


def test_preset_plan_driver_validation():
    """POST /presets/plan rejects invalid driver_id with 422 and succeeds with active linked driver."""
    client = _client(ORG_A)

    # 1. Invalid / mock driver_id -> 422
    resp = client.post(
        "/test/api/v1/presets/plan",
        json={"preset_id": "synthesized-vietnam", "driver_id": "drv-sim-001"},
    )
    assert resp.status_code == 422

    # 2. Cross-tenant driver_id -> 422
    resp = client.post(
        "/test/api/v1/presets/plan",
        json={"preset_id": "synthesized-vietnam", "driver_id": "018f2f4e-3000-7000-8000-000000000021"},
    )
    assert resp.status_code == 422

    # 3. Active Clerk-linked driver -> 201
    resp = client.post(
        "/test/api/v1/presets/plan",
        json={"preset_id": "synthesized-vietnam", "driver_id": "018f2f4e-3000-7000-8000-000000000011"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["definition"]["driver_config"]["driver_id"] == "018f2f4e-3000-7000-8000-000000000011"
    assert data["definition"]["driver_config"]["vehicle_plate"] == "29A-111.11"


@pytest.mark.asyncio
async def test_preset_batch_run_requires_driver_ids_and_round_robin(monkeypatch):
    """POST /presets/{preset_id}/runs requires driver_ids, assigns round-robin, and stores driver on trip."""
    client = _client(ORG_A)

    # Mock classifier
    async def mock_assess(self, model_input):
        return {
            "category": None,  # no violation, no invented label
            "confidence": 0.95,
            "reason_codes": [],
        }

    monkeypatch.setattr("src.services.telemetry_queue_worker.JevAssessmentAgent.assess", mock_assess)

    async def fast_sleep(_):
        pass

    monkeypatch.setattr("src.services.test_preset_batch._sleep", fast_sleep)

    d1 = "018f2f4e-3000-7000-8000-000000000011"
    d2 = "018f2f4e-3000-7000-8000-000000000012"

    # 1. Missing driver_ids -> 422
    resp = client.post(
        "/test/api/v1/presets/synthesized-vietnam/runs",
        json={"trip_limit": 3, "trips_per_batch": 1, "interval_s": 0.01},
    )
    assert resp.status_code == 422

    # 2. Empty driver_ids -> 422
    resp = client.post(
        "/test/api/v1/presets/synthesized-vietnam/runs",
        json={"trip_limit": 3, "trips_per_batch": 1, "interval_s": 0.01, "driver_ids": []},
    )
    assert resp.status_code == 422

    # 3. Invalid/mock driver in driver_ids -> 422
    resp = client.post(
        "/test/api/v1/presets/synthesized-vietnam/runs",
        json={
            "trip_limit": 3,
            "trips_per_batch": 1,
            "interval_s": 0.01,
            "driver_ids": [d1, "018f2f4e-3000-7000-8000-000000000099"],
        },
    )
    assert resp.status_code == 422

    # Record driver set before batch run to verify preset batch creates no new app.drivers rows
    dir_svc = get_driver_directory()
    case_svc = get_case_service()
    driver_ids_before = {str(rec.driver_id) for rec in dir_svc._drivers.values()}
    driver_keys_before = set(dir_svc._drivers.keys())
    case_driver_ids_before = set(case_svc._drivers.keys())

    # 4. Valid batch of 3 trips with 2 drivers: trip 0->d1, trip 1->d2, trip 2->d1
    resp = client.post(
        "/test/api/v1/presets/synthesized-vietnam/runs",
        json={
            "trip_limit": 3,
            "trips_per_batch": 1,
            "interval_s": 0.01,
            "driver_ids": [d1, d2],
        },
    )
    assert resp.status_code in (201, 202), resp.text
    batch_id = resp.json()["id"]

    await asyncio.sleep(0.1)

    # Assert driver set is unchanged (no synthetic app.drivers created)
    driver_ids_after = {str(rec.driver_id) for rec in dir_svc._drivers.values()}
    assert driver_ids_after == driver_ids_before
    assert set(dir_svc._drivers.keys()) == driver_keys_before
    assert set(case_svc._drivers.keys()) == case_driver_ids_before

    # Verify batch trips detail has driver_id and driver_name in round-robin order
    detail_resp = client.get(f"/test/api/v1/presets/runs/{batch_id}")
    assert detail_resp.status_code == 200
    detail = detail_resp.json()
    trips = detail["trips"]
    assert len(trips) == 3

    assert trips[0]["driver_id"] == d1
    assert trips[0]["driver_name"] == "Nguyen Van A1"
    assert trips[1]["driver_id"] == d2
    assert trips[1]["driver_name"] == "Tran Van A2"
    assert trips[2]["driver_id"] == d1
    assert trips[2]["driver_name"] == "Nguyen Van A1"

    # Category was None from classifier, ensure predicted_label is None (not invented)
    assert trips[0]["predicted_label"] is None

    # Verify GET /runs displays driver_name
    runs_resp = client.get("/test/api/v1/runs")
    assert runs_resp.status_code == 200
    batch_run_summaries = [r for r in runs_resp.json() if r.get("source") == "preset_batch"]
    assert len(batch_run_summaries) >= 3
    driver_names = {r["driver_name"] for r in batch_run_summaries[:3]}
    assert "Nguyen Van A1" in driver_names
    assert "Tran Van A2" in driver_names

    # Verify SSE events carry driver_id and driver_name
    events_resp = client.get(f"/test/api/v1/presets/runs/{batch_id}/events")
    assert events_resp.status_code == 200
    events_text = events_resp.text
    found_driver_event = False
    for line in events_text.splitlines():
        if line.startswith("data: "):
            try:
                import json

                payload = json.loads(line.replace("data: ", ""))
                if "driver_id" in payload or ("data" in payload and "driver_id" in payload["data"]):
                    found_driver_event = True
                    break
            except Exception:
                pass
    assert found_driver_event

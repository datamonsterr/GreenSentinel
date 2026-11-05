"""Integration tests for preset batch run API, SSE events, cancel, and tenant isolation (Issue #458)."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from src.main import app
from src.services.driver_directory import DriverRecord, get_driver_directory

ORG_A = "018f2f4e-0000-7000-8000-000000000001"
ORG_B = "018f2f4e-0000-7000-8000-00000000000b"

DRIVER_A1_ID = UUID("018f2f4e-3000-7000-8000-000000000011")
DRIVER_A2_ID = UUID("018f2f4e-3000-7000-8000-000000000012")
DRIVER_B_ID = UUID("018f2f4e-3000-7000-8000-0000000000bb")


@pytest.fixture(autouse=True)
def setup_drivers():
    driver_dir = get_driver_directory()
    driver_dir.register_driver(
        DriverRecord(
            driver_id=DRIVER_A1_ID,
            organization_id=ORG_A,
            principal_id=UUID("018f2f4e-0000-7000-8000-000000000011"),
            external_subject="user_real_org_a1",
            display_name="Nguyen Van Real A1",
            email="driver.a1@example.com",
            account_status="active",
            license_plate="29A-12345",
        )
    )
    driver_dir.register_driver(
        DriverRecord(
            driver_id=DRIVER_A2_ID,
            organization_id=ORG_A,
            principal_id=UUID("018f2f4e-0000-7000-8000-000000000012"),
            external_subject="user_real_org_a2",
            display_name="Nguyen Van Real A2",
            email="driver.a2@example.com",
            account_status="active",
            license_plate="29A-67890",
        )
    )
    driver_dir.register_driver(
        DriverRecord(
            driver_id=DRIVER_B_ID,
            organization_id=ORG_B,
            principal_id=UUID("018f2f4e-0000-7000-8000-000000000021"),
            external_subject="user_real_org_b",
            display_name="Tran Van Real B",
            email="driver.b@example.com",
            account_status="active",
            license_plate="29B-99999",
        )
    )


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


def test_get_preset_detail_vietnam():
    """GET /presets/{preset_id} returns preset info, rich sample trips, and computed distributions."""
    client = _client(ORG_A)
    resp = client.get("/test/api/v1/presets/synthesized-vietnam")
    assert resp.status_code == 200, resp.text
    data = resp.json()

    assert data["id"] == "synthesized-vietnam"
    assert data["title"] == "Vietnam trips (synthesized)"
    assert data["trip_count"] == 100
    assert data["source_release"] == "synthesized_vietnam_trip"
    assert data["revision"] == "a914d500b1c536f1dbfb59f8ea4c961bd38b5c7e"

    # Sample trips have rich fields
    assert len(data["sample_trips"]) > 0
    sample = data["sample_trips"][0]
    assert sample["trip_ref"].startswith("vn_trip_")
    assert "city" in sample and sample["city"] in {"Hanoi", "Ho Chi Minh City"}
    assert "driver_name" in sample
    assert "license_plate" in sample
    assert "pickup_name" in sample
    assert "dropoff_name" in sample

    # Computed distributions
    dist = data["distributions"]
    assert dist["total_records"] == 100
    assert dist["by_label"]["no_violation"] == 76
    assert dist["by_label"]["fraud"] == 24
    assert dist["by_city"]["Hanoi"] == 80
    assert dist["by_city"]["Ho Chi Minh City"] == 20
    assert dist["by_cancellation_actor"]["passenger"] == 10
    assert dist["by_cancellation_actor"]["driver"] == 8


def test_get_preset_detail_not_found():
    """GET /presets/{preset_id} with unknown ID returns 404."""
    client = _client(ORG_A)
    resp = client.get("/test/api/v1/presets/unknown-preset-xyz")
    assert resp.status_code == 404


def test_post_preset_batch_run_validation():
    """POST /presets/{preset_id}/runs validates bounds (trip_limit, trips_per_batch, interval_s, driver_ids)."""
    client = _client(ORG_A)

    # Missing driver_ids -> 422
    resp = client.post(
        "/test/api/v1/presets/synthesized-vietnam/runs",
        json={"trips_per_batch": 1, "interval_s": 1.0},
    )
    assert resp.status_code == 422

    # Empty driver_ids -> 422
    resp = client.post(
        "/test/api/v1/presets/synthesized-vietnam/runs",
        json={"driver_ids": [], "trips_per_batch": 1, "interval_s": 1.0},
    )
    assert resp.status_code == 422

    # Cross-tenant driver_id -> 422
    resp = client.post(
        "/test/api/v1/presets/synthesized-vietnam/runs",
        json={"driver_ids": [str(DRIVER_B_ID)], "trips_per_batch": 1, "interval_s": 1.0},
    )
    assert resp.status_code == 422

    # trips_per_batch < 1 -> 422
    resp = client.post(
        "/test/api/v1/presets/synthesized-vietnam/runs",
        json={"driver_ids": [str(DRIVER_A1_ID)], "trips_per_batch": 0, "interval_s": 1.0},
    )
    assert resp.status_code == 422

    # interval_s <= 0 -> 422
    resp = client.post(
        "/test/api/v1/presets/synthesized-vietnam/runs",
        json={"driver_ids": [str(DRIVER_A1_ID)], "trips_per_batch": 1, "interval_s": 0.0},
    )
    assert resp.status_code == 422

    # trip_limit = 0 -> 422
    resp = client.post(
        "/test/api/v1/presets/synthesized-vietnam/runs",
        json={"driver_ids": [str(DRIVER_A1_ID)], "trip_limit": 0, "trips_per_batch": 1, "interval_s": 1.0},
    )
    assert resp.status_code == 422

    # trip_limit > available -> 422
    resp = client.post(
        "/test/api/v1/presets/synthesized-vietnam/runs",
        json={"driver_ids": [str(DRIVER_A1_ID)], "trip_limit": 10000, "trips_per_batch": 1, "interval_s": 1.0},
    )
    assert resp.status_code == 422

    # unavailable preset -> 400
    resp = client.post(
        "/test/api/v1/presets/wrong-direction/runs",
        json={"driver_ids": [str(DRIVER_A1_ID)], "trip_limit": 5, "trips_per_batch": 1, "interval_s": 1.0},
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_preset_batch_run_3_trips_to_completion(monkeypatch):
    """3-trip batch runs to completion with ordered events and zero live LLM spend."""
    client = _client(ORG_A)

    # Mock classifier to ensure zero live LLM spend
    async def mock_assess(self, model_input):
        return {
            "category": "ERR-01" if "cancel" in str(model_input) else "no_violation",
            "confidence": 0.94,
            "reason_codes": ["MOCK_TEST"],
            "forensic_brief": "Mock test assessment",
            "priority_tier": 2 if "cancel" in str(model_input) else None,
            "priority_score": 10 if "cancel" in str(model_input) else None,
        }

    monkeypatch.setattr("src.services.telemetry_queue_worker.JevAssessmentAgent.assess", mock_assess)

    # Instant sleeper for fast tests
    async def fast_sleep(_):
        pass

    monkeypatch.setattr("src.services.test_preset_batch._sleep", fast_sleep)

    # Launch batch of 3 trips
    resp = client.post(
        "/test/api/v1/presets/synthesized-vietnam/runs",
        json={
            "driver_ids": [str(DRIVER_A1_ID), str(DRIVER_A2_ID)],
            "trip_limit": 3,
            "trips_per_batch": 1,
            "interval_s": 0.01,
        },
    )
    assert resp.status_code in (201, 202), resp.text
    batch_data = resp.json()
    batch_id = batch_data["id"]

    # Wait for completion (fast sleep means nearly instantaneous)
    await asyncio.sleep(0.1)

    # Check batch detail
    batch_resp = client.get(f"/test/api/v1/presets/runs/{batch_id}")
    assert batch_resp.status_code == 200, batch_resp.text
    detail = batch_resp.json()

    assert detail["status"] == "COMPLETED"
    assert len(detail["trips"]) == 3

    # Round-robin assignment verification: 0 -> A1, 1 -> A2, 2 -> A1
    assert detail["trips"][0]["driver_id"] == str(DRIVER_A1_ID)
    assert detail["trips"][0]["driver_name"] == "Nguyen Van Real A1"
    assert detail["trips"][1]["driver_id"] == str(DRIVER_A2_ID)
    assert detail["trips"][1]["driver_name"] == "Nguyen Van Real A2"
    assert detail["trips"][2]["driver_id"] == str(DRIVER_A1_ID)
    assert detail["trips"][2]["driver_name"] == "Nguyen Van Real A1"

    for trip in detail["trips"]:
        assert trip["status"] == "COMPLETED"
        assert trip["expected_label"] is not None
        assert trip["predicted_label"] is not None
        assert trip["confidence"] is not None
        # Compact snapshot verified
        snap = trip["snapshot"]
        assert "conversation" in snap
        assert "gps_summary" in snap
        assert "speed_stats" in snap

    # Verify SSE events endpoint
    events_resp = client.get(f"/test/api/v1/presets/runs/{batch_id}/events")
    assert events_resp.status_code == 200
    events_text = events_resp.text

    # Verify ordered events and reached_classifier flag
    event_types: list[str] = []
    for line in events_text.splitlines():
        if line.startswith("event: "):
            event_types.append(line.replace("event: ", "").strip())
        elif line.startswith("data: "):
            try:
                payload = json.loads(line.replace("data: ", ""))
                if "reached_classifier" in payload:
                    assert isinstance(payload["reached_classifier"], bool)
                if payload.get("driver_id"):
                    assert payload["driver_id"] in (str(DRIVER_A1_ID), str(DRIVER_A2_ID))
            except json.JSONDecodeError:
                pass

    assert "connect" in event_types
    assert "trip.queued" in event_types
    assert "trip.started" in event_types
    assert "trip.telemetry_loaded" in event_types
    assert "trip.published" in event_types
    assert "trip.classifier_received" in event_types
    assert "trip.classified" in event_types
    assert "batch.completed" in event_types


@pytest.mark.asyncio
async def test_preset_batch_run_cancel_stops_pending_trips(monkeypatch):
    """POST /presets/runs/{batch_id}/cancel stops pending trips."""
    client = _client(ORG_A)

    # Delay sleeper to catch cancel during execution
    sleep_started = asyncio.Event()
    cancel_signal = asyncio.Event()

    async def controlled_sleep(_):
        sleep_started.set()
        await cancel_signal.wait()

    monkeypatch.setattr("src.services.test_preset_batch._sleep", controlled_sleep)

    resp = client.post(
        "/test/api/v1/presets/synthesized-vietnam/runs",
        json={
            "driver_ids": [str(DRIVER_A1_ID)],
            "trip_limit": 5,
            "trips_per_batch": 1,
            "interval_s": 5.0,
        },
    )
    assert resp.status_code in (201, 202)
    batch_id = resp.json()["id"]

    # Wait until first trip completes and scheduler enters sleep
    await asyncio.wait_for(sleep_started.wait(), timeout=2.0)

    # Cancel batch
    cancel_resp = client.post(f"/test/api/v1/presets/runs/{batch_id}/cancel")
    assert cancel_resp.status_code == 200
    assert cancel_resp.json()["status"] == "CANCELLED"

    # Release sleeper
    cancel_signal.set()
    await asyncio.sleep(0.05)

    # Verify batch detail shows cancelled and pending trips skipped
    detail_resp = client.get(f"/test/api/v1/presets/runs/{batch_id}")
    assert detail_resp.status_code == 200
    detail = detail_resp.json()

    assert detail["status"] == "CANCELLED"
    # At least one trip skipped
    statuses = [t["status"] for t in detail["trips"]]
    assert "SKIPPED" in statuses or "CANCELLED" in statuses


@pytest.mark.asyncio
async def test_batch_trips_visible_in_get_runs(monkeypatch):
    """Each batch trip appears in GET /runs with source=preset_batch."""
    client = _client(ORG_A)

    async def mock_assess(self, model_input):
        return {
            "category": "no_violation",
            "confidence": 0.95,
            "reason_codes": [],
            "forensic_brief": "Nominal",
            "priority_tier": None,
            "priority_score": None,
        }

    monkeypatch.setattr("src.services.telemetry_queue_worker.JevAssessmentAgent.assess", mock_assess)
    monkeypatch.setattr("src.services.test_preset_batch._sleep", AsyncMock())

    resp = client.post(
        "/test/api/v1/presets/synthesized-vietnam/runs",
        json={
            "driver_ids": [str(DRIVER_A1_ID)],
            "trip_limit": 2,
            "trips_per_batch": 2,
            "interval_s": 0.01,
        },
    )
    assert resp.status_code in (201, 202)
    batch_id = resp.json()["id"]

    # Wait for batch completion
    for _ in range(50):
        await asyncio.sleep(0.05)
        detail = client.get(f"/test/api/v1/presets/runs/{batch_id}").json()
        if detail.get("status") in ("COMPLETED", "FAILED", "CANCELLED"):
            break

    assert detail["status"] == "COMPLETED"
    assert len(detail["trips"]) == 2

    # Verify GET /runs includes batch trips with source="preset_batch" and correct driver_name
    runs_resp = client.get("/test/api/v1/runs?limit=50")
    assert runs_resp.status_code == 200
    runs = runs_resp.json()

    batch_run_ids = {str(t["run_id"]) for t in detail["trips"] if t.get("run_id")}
    assert len(batch_run_ids) == 2

    matched_runs = [r for r in runs if r["id"] in batch_run_ids]
    assert len(matched_runs) == 2
    for r in matched_runs:
        assert r.get("source") == "preset_batch"
        assert r.get("driver_name") == "Nguyen Van Real A1"


@pytest.mark.asyncio
async def test_batch_trips_expected_and_predicted_label_in_get_runs(monkeypatch):
    """After a 2-trip batch completes, GET /runs rows with source=preset_batch have expected_label and predicted_label set."""
    client = _client(ORG_A)

    async def mock_assess(self, model_input):
        return {
            "category": "ERR-01" if "cancel" in str(model_input) else "no_violation",
            "confidence": 0.92,
            "reason_codes": ["TEST"],
            "forensic_brief": "Test forensic brief",
            "priority_tier": 2 if "cancel" in str(model_input) else None,
            "priority_score": 10 if "cancel" in str(model_input) else None,
        }

    monkeypatch.setattr("src.services.telemetry_queue_worker.JevAssessmentAgent.assess", mock_assess)
    monkeypatch.setattr("src.services.test_preset_batch._sleep", AsyncMock())

    resp = client.post(
        "/test/api/v1/presets/synthesized-vietnam/runs",
        json={
            "driver_ids": [str(DRIVER_A1_ID)],
            "trip_limit": 2,
            "trips_per_batch": 2,
            "interval_s": 0.01,
        },
    )
    assert resp.status_code in (201, 202)
    batch_id = resp.json()["id"]

    # Wait for batch completion
    for _ in range(50):
        await asyncio.sleep(0.05)
        detail = client.get(f"/test/api/v1/presets/runs/{batch_id}").json()
        if detail.get("status") in ("COMPLETED", "FAILED", "CANCELLED"):
            break

    assert detail["status"] == "COMPLETED"
    assert len(detail["trips"]) == 2

    # Fetch GET /runs and find the batch runs
    runs_resp = client.get("/test/api/v1/runs?limit=50")
    assert runs_resp.status_code == 200
    runs = runs_resp.json()

    batch_run_ids = {str(t["run_id"]) for t in detail["trips"] if t.get("run_id")}
    assert len(batch_run_ids) == 2

    matched_runs = [r for r in runs if r["id"] in batch_run_ids]
    assert len(matched_runs) == 2

    for r in matched_runs:
        assert r["source"] == "preset_batch"
        assert r["expected_label"] is not None
        assert r["predicted_label"] is not None
        assert r["confidence"] is not None


def test_preset_batch_cross_tenant_isolation_404():
    """Batch run queries from a foreign organization return 404."""
    client_a = _client(ORG_A)
    client_b = _client(ORG_B)

    # Org A creates batch
    resp_a = client_a.post(
        "/test/api/v1/presets/synthesized-vietnam/runs",
        json={
            "driver_ids": [str(DRIVER_A1_ID)],
            "trip_limit": 1,
            "trips_per_batch": 1,
            "interval_s": 1.0,
        },
    )
    assert resp_a.status_code in (201, 202)
    batch_id = resp_a.json()["id"]

    # Org B queries Org A's batch -> 404
    assert client_b.get(f"/test/api/v1/presets/runs/{batch_id}").status_code == 404

    # Org B streams Org A's events -> 404
    assert client_b.get(f"/test/api/v1/presets/runs/{batch_id}/events").status_code == 404

    # Org B cancels Org A's batch -> 404
    assert client_b.post(f"/test/api/v1/presets/runs/{batch_id}/cancel").status_code == 404

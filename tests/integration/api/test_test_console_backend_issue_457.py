"""Integration tests for issue #457: run enrichment, trace pipeline, and expected_label."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from src.main import app
from src.models.test_simulation import TestTelemetrySample
from src.services import test_simulation_publish
from src.services.driver_directory import DriverRecord, get_driver_directory
from src.services.test_simulation_runner import get_simulation_runner

ORG_A = "018f2f4e-0000-7000-8000-00000000000a"
ORG_B = "018f2f4e-0000-7000-8000-00000000000b"
TEST_DRIVER_ID = "018f2f4e-3000-7000-8000-000000000011"
RICH_DRIVER_ID = "018f2f4e-3000-7000-8000-000000000012"


@pytest.fixture(autouse=True)
def setup_drivers():
    driver_dir = get_driver_directory()
    driver_dir.register_driver(
        DriverRecord(
            driver_id=UUID(TEST_DRIVER_ID),
            organization_id=ORG_A,
            principal_id=UUID("018f2f4e-2000-7000-8000-000000000011"),
            external_subject="user_real_org_a",
            display_name="Nguyen Viet",
            email="driver.a@example.com",
            account_status="active",
            license_plate="29A-888.88",
        )
    )
    driver_dir.register_driver(
        DriverRecord(
            driver_id=UUID(RICH_DRIVER_ID),
            organization_id=ORG_A,
            principal_id=UUID("018f2f4e-2000-7000-8000-000000000012"),
            external_subject="user_real_org_a2",
            display_name="Nguyen Rich",
            email="rich.a@example.com",
            account_status="active",
            license_plate="30A-999.99",
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


def _create_full_run(
    client: TestClient,
    *,
    expected_label: str | None = None,
    with_addresses: bool = True,
    vehicle_plate: str = "29A-888.88",
    driver_id: str = TEST_DRIVER_ID,
) -> dict:

    plan = client.post("/test/api/v1/plans", json={"name": "Integration Plan 457"}).json()
    def_payload = {
        "plan_id": plan["id"],
        "route_geometry": {
            "type": "LineString",
            "coordinates": [[105.8524, 21.0285], [105.8342, 21.0450]],
        },
        "driver_config": {
            "speed_mps": 12.0,
            "update_cadence_s": 1.0,
            "driver_id": driver_id,
            "vehicle_plate": vehicle_plate,
        },
        "fault_configs": [],
        "messages": [],
    }
    if with_addresses:
        def_payload.update(
            {
                "initial_snapshot": {
                    "location": {"latitude": 21.0285, "longitude": 105.8524},
                    "address": "123 Origin St",
                },
                "pickup_snapshot": {
                    "location": {"latitude": 21.0350, "longitude": 105.8400},
                    "address": "456 Pickup Ave",
                },
                "destination_snapshot": {
                    "location": {"latitude": 21.0450, "longitude": 105.8342},
                    "address": "789 Dropoff Blvd",
                },
            }
        )

    definition = client.post("/test/api/v1/definitions", json=def_payload).json()
    run_payload: dict[str, object] = {
        "definition_revision_id": definition["id"],
        "speed_factor": 1.0,
    }
    if expected_label is not None:
        run_payload["expected_label"] = expected_label

    res = client.post("/test/api/v1/runs", json=run_payload)
    assert res.status_code == 202, res.text
    return res.json()


def test_expected_label_round_trip():
    client = _client()
    for valid_label in ["no_violation", "ERR-01", "ERR-02", "ERR-03", "ERR-04", "ERR-05", "insufficient_evidence"]:
        run = _create_full_run(client, expected_label=valid_label)
        assert run.get("expected_label") == valid_label

        # GET /runs/{id}
        fetched = client.get(f"/test/api/v1/runs/{run['id']}").json()
        assert fetched.get("expected_label") == valid_label

        # GET /runs
        history = client.get("/test/api/v1/runs").json()
        match = next(r for r in history if r["id"] == run["id"])
        assert match.get("expected_label") == valid_label


def test_expected_label_validation_rejects_unknown():
    client = _client()
    plan = client.post("/test/api/v1/plans", json={"name": "Invalid Label Plan"}).json()
    definition = client.post(
        "/test/api/v1/definitions",
        json={
            "plan_id": plan["id"],
            "driver_config": {"driver_id": TEST_DRIVER_ID},
            "route_geometry": {"type": "LineString", "coordinates": [[105.85, 21.02], [105.84, 21.03]]},
        },
    ).json()

    res = client.post(
        "/test/api/v1/runs",
        json={"definition_revision_id": definition["id"], "expected_label": "UNKNOWN_CODE"},
    )
    assert res.status_code == 422


def test_runs_history_enrichment_from_published_run(monkeypatch):
    client = _client()
    runner = get_simulation_runner()
    run_data = _create_full_run(
        client,
        expected_label="ERR-03",
        with_addresses=True,
        vehicle_plate="30A-999.99",
        driver_id=RICH_DRIVER_ID,
    )
    run_id = UUID(run_data["id"])

    # Simulate recorded samples so publish succeeds
    now = datetime.now(UTC)
    sample = TestTelemetrySample(
        run_id=run_id,
        step_index=0,
        latitude=21.0350,
        longitude=105.8400,
        speed_mps=10.0,
        heading_deg=45.0,
        emitted_at=now,
    )
    runner.repository.save_sample(sample)
    runner.repository.update_run_status(run_id, "COMPLETED")

    # Mock process_telemetry_event to simulate classifier processing
    async def mock_process(event, service, *, organization_id):
        return {
            "status": "processed",
            "trip_id": event["trip_id"],
            "case_id": "case-mock-457",
            "category": "ERR-03",
            "confidence": 0.94,
            "priority_label": "P1",
            "priority_tier": 1,
            "assessment": {
                "category": "ERR-03",
                "confidence": 0.94,
                "reason_codes": ["ROUTE_DIVERGENCE"],
                "forensic_brief": "Intentional route divergence detected",
            },
        }

    monkeypatch.setattr(test_simulation_publish, "process_telemetry_event", mock_process)

    # Publish run
    client.post(
        f"/test/api/v1/runs/{run_id}/publish-production",
        json={
            "driver_id": RICH_DRIVER_ID,
            "passenger_id": "pass-001",
            "vehicle_id": "veh-001",
            "policy_version_id": "pol-001",
        },
    )

    # Fetch history
    history = client.get("/test/api/v1/runs").json()
    match = next(r for r in history if r["id"] == str(run_id))

    assert match["source"] == "manual"
    assert match["expected_label"] == "ERR-03"
    assert match["predicted_label"] == "ERR-03"
    assert match["error_type"] == "ERR-03"
    assert match["confidence"] == 0.94
    assert match["case_id"] == "case-mock-457"
    assert match["license_plate"] == "30A-999.99"
    assert match["origin_address"] == "123 Origin St"
    assert match["pickup_address"] == "456 Pickup Ave"
    assert match["destination_address"] == "789 Dropoff Blvd"


def test_runs_history_unenriched_fields_stay_null():
    client = _client()
    run_data = _create_full_run(client, with_addresses=False)
    run_id = run_data["id"]

    history = client.get("/test/api/v1/runs").json()
    match = next(r for r in history if r["id"] == run_id)

    assert match["expected_label"] is None
    assert match["predicted_label"] is None
    assert match["error_type"] is None
    assert match["confidence"] is None
    assert match["case_id"] is None
    assert match["origin_address"] is None
    assert match["pickup_address"] is None
    assert match["destination_address"] is None


def test_runs_trace_order_and_evidence_only_stages(monkeypatch):
    client = _client()
    runner = get_simulation_runner()
    run_data = _create_full_run(client, expected_label="ERR-01")
    run_id = UUID(run_data["id"])

    # 1. Initially (QUEUED): only "created" stage is done
    res = client.get(f"/test/api/v1/runs/{run_id}/trace")
    assert res.status_code == 200
    trace = res.json()
    assert isinstance(trace, list)

    stage_names = [s["stage"] for s in trace]
    expected_order = [
        "created",
        "driving_to_pickup",
        "picked_up",
        "driving_to_destination",
        "completed",
        "published",
        "classifier_received",
        "classified",
        "case_created",
    ]
    assert stage_names == expected_order

    # Only created has state done
    assert trace[0]["stage"] == "created"
    assert trace[0]["state"] == "done"
    assert trace[0]["occurred_at"] is not None
    for s in trace[1:]:
        assert s["state"] != "done"

    # 2. Add samples and complete
    now = datetime.now(UTC)
    s1 = TestTelemetrySample(
        run_id=run_id,
        step_index=0,
        latitude=21.0285,
        longitude=105.8524,
        speed_mps=10.0,
        heading_deg=0.0,
        emitted_at=now,
    )
    s2 = TestTelemetrySample(
        run_id=run_id,
        step_index=1,
        latitude=21.0350,
        longitude=105.8400,
        speed_mps=10.0,
        heading_deg=0.0,
        emitted_at=now,
    )
    s3 = TestTelemetrySample(
        run_id=run_id,
        step_index=2,
        latitude=21.0450,
        longitude=105.8342,
        speed_mps=10.0,
        heading_deg=0.0,
        emitted_at=now,
    )
    runner.repository.save_sample(s1)
    runner.repository.save_sample(s2)
    runner.repository.save_sample(s3)
    runner.repository.update_run_status(run_id, "COMPLETED")

    # Mock publish
    async def mock_process(event, service, *, organization_id):
        return {
            "status": "processed",
            "trip_id": event["trip_id"],
            "case_id": "case-trace-457",
            "category": "ERR-01",
            "confidence": 0.95,
            "assessment": {"category": "ERR-01", "confidence": 0.95},
        }

    monkeypatch.setattr(test_simulation_publish, "process_telemetry_event", mock_process)

    client.post(
        f"/test/api/v1/runs/{run_id}/publish-production",
        json={
            "driver_id": TEST_DRIVER_ID,
            "passenger_id": "pass-001",
            "vehicle_id": "veh-001",
            "policy_version_id": "pol-001",
        },
    )

    # 3. After completion and publication, all 9 stages are done
    res2 = client.get(f"/test/api/v1/runs/{run_id}/trace")
    assert res2.status_code == 200
    trace2 = res2.json()

    assert all(s["state"] == "done" for s in trace2)

    # Check detail content
    classified_stage = next(s for s in trace2 if s["stage"] == "classified")
    assert classified_stage["detail"]["label"] == "ERR-01"
    assert classified_stage["detail"]["confidence"] == 0.95

    case_stage = next(s for s in trace2 if s["stage"] == "case_created")
    assert case_stage["detail"]["case_id"] == "case-trace-457"


def test_runs_trace_cancellation_actor_and_reason():
    client = _client()
    run_data = _create_full_run(client)
    run_id = run_data["id"]

    cancel_res = client.post(
        f"/test/api/v1/runs/{run_id}/controls",
        json={"command": "CANCEL", "payload": {"actor": "passenger", "reason": "Driver arrived at wrong location"}},
    )
    assert cancel_res.status_code == 200

    trace = client.get(f"/test/api/v1/runs/{run_id}/trace").json()
    cancel_stage = next(s for s in trace if s["stage"] == "cancelled")
    assert cancel_stage["state"] == "done"
    assert cancel_stage["detail"]["actor"] == "passenger"
    assert cancel_stage["detail"]["reason"] == "Driver arrived at wrong location"


def test_cross_tenant_isolation_returns_404():
    client_a = _client(org=ORG_A)
    client_b = _client(org=ORG_B)

    run = _create_full_run(client_a, expected_label="ERR-04")
    run_id = run["id"]

    # Tenant B cannot access run directly -> 404
    assert client_b.get(f"/test/api/v1/runs/{run_id}").status_code == 404

    # Tenant B cannot access trace -> 404
    assert client_b.get(f"/test/api/v1/runs/{run_id}/trace").status_code == 404

    # Tenant B history does not contain Tenant A's run
    b_history = client_b.get("/test/api/v1/runs").json()
    assert not any(r["id"] == run_id for r in b_history)

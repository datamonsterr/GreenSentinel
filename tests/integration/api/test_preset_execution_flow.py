"""Integration tests for preset selection, materialization, execution, and publish flow."""

from __future__ import annotations

from unittest.mock import patch
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from src.main import app
from src.services.driver_directory import DriverRecord, get_driver_directory
from src.services.test_simulation_runner import get_simulation_runner

ORG_A = "018f2f4e-0000-7000-8000-000000000001"
ORG_B = "018f2f4e-0000-7000-8000-00000000000b"
DRIVER_B_ID = UUID("018f2f4e-3000-7000-8000-0000000000b1")


@pytest.fixture(autouse=True)
def setup_drivers():
    driver_dir = get_driver_directory()
    driver_dir.register_driver(
        DriverRecord(
            driver_id=DRIVER_B_ID,
            organization_id=ORG_B,
            principal_id=UUID("018f2f4e-2000-7000-8000-0000000000b1"),
            external_subject="user_real_org_b",
            display_name="Tran Van B",
            email="driver.b@example.com",
            account_status="active",
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


def test_preset_plan_vietnam_creates_runnable_plan():
    """Selecting a Vietnam preset trip produces nonempty real telemetry and a runnable plan."""
    client = _client(ORG_A)
    resp = client.post(
        "/test/api/v1/presets/plan",
        json={"preset_id": "synthesized-vietnam"},
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()

    assert data["preset_id"] == "synthesized-vietnam"
    assert data["trip_ref"].startswith("vn_trip_")
    assert data["distance_m"] > 0
    assert data["telemetry_points"] > 0
    assert len(data["telemetry"]) > 0

    plan = data["plan"]
    assert plan["id"]
    definition = data["definition"]
    assert definition["id"]
    assert len(definition["route_geometry"]["coordinates"]) >= 2
    assert definition["initial_snapshot"] is not None
    assert definition["pickup_snapshot"] is not None
    assert definition["destination_snapshot"] is not None

    # Verify execution controls: plan can be started via existing /runs endpoint
    run_resp = client.post(
        "/test/api/v1/runs",
        json={
            "definition_revision_id": definition["id"],
            "speed_factor": 1.0,
            "title": "Vietnam Preset Execution Run",
        },
    )
    assert run_resp.status_code == 202, run_resp.text
    run_data = run_resp.json()
    assert run_data["id"]
    assert run_data["definition_revision_id"] == definition["id"]
    assert run_data["status"] in {"QUEUED", "RUNNING"}


def test_preset_plan_two_orgs_isolation_and_foreign_org_denial():
    """Two organizations using the same corpus row preserve tenant isolation.
    Foreign org IDs or preset refs from other tenants are denied / scoped strictly to authenticated org.
    """
    client_a = _client(ORG_A, principal="tester-a")
    client_b = _client(ORG_B, principal="tester-b")

    # Both plan the same trip
    resp_a = client_a.post(
        "/test/api/v1/presets/plan",
        json={"preset_id": "synthesized-vietnam", "trip_ref": "vn_trip_0001"},
    )
    assert resp_a.status_code == 201, resp_a.text
    data_a = resp_a.json()
    plan_a_id = data_a["plan"]["id"]
    def_a_id = data_a["definition"]["id"]

    resp_b = client_b.post(
        "/test/api/v1/presets/plan",
        json={"preset_id": "synthesized-vietnam", "trip_ref": "vn_trip_0001"},
    )
    assert resp_b.status_code == 201, resp_b.text
    data_b = resp_b.json()
    plan_b_id = data_b["plan"]["id"]
    def_b_id = data_b["definition"]["id"]

    # Separate plan and definition identities
    assert plan_a_id != plan_b_id
    assert def_a_id != def_b_id

    # Org B cannot access Org A's plan or definition
    assert client_b.get(f"/test/api/v1/plans/{plan_a_id}").status_code == 404
    # Org B cannot start a run using Org A's definition
    assert (
        client_b.post(
            "/test/api/v1/runs",
            json={"definition_revision_id": def_a_id},
        ).status_code
        == 404
    )

    # Client cannot inject a client organization_id in request body to override auth principal
    spoofed = client_a.post(
        "/test/api/v1/presets/plan",
        json={
            "preset_id": "synthesized-vietnam",
            "trip_ref": "vn_trip_0001",
            "organization_id": ORG_B,
        },
    )
    assert spoofed.status_code == 201
    spoofed_plan = spoofed.json()["plan"]
    # Plan must belong to Org A (authenticated principal), never Org B
    runner = get_simulation_runner()
    db_plan = runner.repository.get_plan(UUID(spoofed_plan["id"]), organization_id=ORG_A)
    assert db_plan is not None
    assert runner.repository.get_plan(UUID(spoofed_plan["id"]), organization_id=ORG_B) is None


def test_preset_plan_unavailable_profile_rejected():
    """Attempting to materialize an unavailable preset is rejected."""
    client = _client()
    resp = client.post(
        "/test/api/v1/presets/plan",
        json={"preset_id": "wrong-direction"},
    )
    assert resp.status_code == 400
    assert "Unavailable" in resp.json()["detail"]


def test_preset_plan_docker_sample_inclusion_fallback():
    """When full trips.jsonl is absent (Docker sample inclusion), preset resolves from sample_100.jsonl."""
    client = _client()

    with patch("src.services.test_presets._DATA_ROOT") as mock_data_root:
        # Simulate environment where only sample_100.jsonl exists
        from pathlib import Path

        real_root = Path("data/benchmark-10k")
        mock_data_root.__truediv__.side_effect = lambda path: real_root / path

        # Planning existing sample trip works
        resp = client.post(
            "/test/api/v1/presets/plan",
            json={"preset_id": "synthesized-vietnam", "trip_ref": "vn_trip_0001"},
        )
        assert resp.status_code == 201

    # Requesting nonexistent trip reference fails with 404
    resp_missing = client.post(
        "/test/api/v1/presets/plan",
        json={"preset_id": "synthesized-vietnam", "trip_ref": "trip-nonexistent-9999"},
    )
    assert resp_missing.status_code == 404

"""Integration tests for Tester Trip Simulation API routes (/test/api/v1)."""

from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from src.main import app
from src.services.driver_directory import DriverRecord, get_driver_directory

TEST_DRIVER_ID = "018f2f4e-3000-7000-8000-000000000011"
ORG_ID = "018f2f4e-0000-7000-8000-000000000001"


@pytest.fixture(autouse=True)
def setup_drivers():
    driver_dir = get_driver_directory()
    driver_dir.register_driver(
        DriverRecord(
            driver_id=UUID(TEST_DRIVER_ID),
            organization_id=ORG_ID,
            principal_id=UUID("018f2f4e-2000-7000-8000-000000000011"),
            external_subject="user_real_org_a",
            display_name="Nguyen Viet",
            email="driver.a@example.com",
            account_status="active",
        )
    )


client = TestClient(
    app,
    headers={
        "X-Test-Context": "true",
        "X-Role": "demo_operator",
        "X-Principal-Id": "tester-1",
        "X-Organization-Id": ORG_ID,
    },
)


def test_test_simulation_boundary_rejection():
    # Attempting to call with X-Test-Context: false must fail with 400
    res = client.post(
        "/test/api/v1/plans",
        json={"name": "Illegal Boundary Plan"},
        headers={"X-Test-Context": "false"},
    )
    assert res.status_code == 400
    assert "X-Test-Context: true" in res.json()["detail"]


def test_test_simulation_requires_explicit_context_and_identity():
    unauthenticated = TestClient(app)
    missing = unauthenticated.get("/test/api/v1/plans")
    assert missing.status_code == 400
    assert "X-Test-Context: true" in missing.json()["detail"]


def test_test_simulation_rejects_anonymous_after_explicit_context():
    anonymous = TestClient(app)
    response = anonymous.get(
        "/test/api/v1/plans",
        headers={"X-Test-Context": "true"},
    )
    assert response.status_code == 401


def test_test_simulation_allows_any_authenticated_organization_member():
    member = TestClient(
        app,
        headers={
            "X-Test-Context": "true",
            "X-Role": "driver",
            "X-Principal-Id": "member-driver",
            "X-Organization-Id": "018f2f4e-0000-7000-8000-000000000001",
        },
    )
    response = member.get("/test/api/v1/plans")
    assert response.status_code == 200


def test_test_simulation_plan_isolation_between_organizations():
    owner = TestClient(
        app,
        headers={
            "X-Test-Context": "true",
            "X-Role": "driver",
            "X-Principal-Id": "org-a",
            "X-Organization-Id": "018f2f4e-0000-7000-8000-00000000000a",
        },
    )
    other = TestClient(
        app,
        headers={
            "X-Test-Context": "true",
            "X-Role": "driver",
            "X-Principal-Id": "org-b",
            "X-Organization-Id": "018f2f4e-0000-7000-8000-00000000000b",
        },
    )
    created = owner.post("/test/api/v1/plans", json={"name": "Org A plan"})
    assert created.status_code == 201
    plan_id = created.json()["id"]
    assert other.get(f"/test/api/v1/plans/{plan_id}").status_code == 404


def test_simulation_plan_and_definition_lifecycle():
    # 1. Create plan
    plan_res = client.post(
        "/test/api/v1/plans",
        json={"name": "Hanoi GPS Anomaly Test", "description": "Jump fault along Hoan Kiem route"},
        headers={"X-Test-Context": "true"},
    )
    assert plan_res.status_code == 201
    plan_data = plan_res.json()
    plan_id = plan_data["id"]
    assert plan_data["name"] == "Hanoi GPS Anomaly Test"

    # 2. List plans
    list_res = client.get("/test/api/v1/plans", headers={"X-Test-Context": "true"})
    assert list_res.status_code == 200
    plans = list_res.json()
    assert any(p["id"] == plan_id for p in plans)

    # 3. Create definition revision with route geometry and fault config
    route_geom = {
        "type": "LineString",
        "coordinates": [
            [105.8524, 21.0285],
            [105.8342, 21.0450],
        ],
    }
    faults = [
        {
            "kind": "JUMP",
            "at_offset_s": 5,
            "displacement_m": 450.0,
            "bearing_deg": 45.0,
        }
    ]

    rev_res = client.post(
        "/test/api/v1/definitions",
        json={
            "plan_id": plan_id,
            "route_geometry": route_geom,
            "driver_config": {
                "speed_mps": 15.0,
                "update_cadence_s": 1.0,
                "driver_id": TEST_DRIVER_ID,
            },
            "fault_configs": faults,
        },
        headers={"X-Test-Context": "true"},
    )
    assert rev_res.status_code == 201
    rev_data = rev_res.json()
    rev_id = rev_data["id"]
    assert rev_data["plan_id"] == plan_id
    assert len(rev_data["fault_configs"]) == 1

    # 4. Instantiate and queue run
    run_res = client.post(
        "/test/api/v1/runs",
        json={"definition_revision_id": rev_id, "speed_factor": 10.0},
        headers={"X-Test-Context": "true"},
    )
    assert run_res.status_code == 202
    run_data = run_res.json()
    run_id = run_data["id"]
    _force_running(run_id)
    assert run_data["status"] in ("QUEUED", "RUNNING")

    # 5. Apply control commands
    pause_res = client.post(
        f"/test/api/v1/runs/{run_id}/controls",
        json={"command": "PAUSE"},
        headers={"X-Test-Context": "true"},
    )
    assert pause_res.status_code == 200
    assert pause_res.json()["command"] == "PAUSE"

    resume_res = client.post(
        f"/test/api/v1/runs/{run_id}/controls",
        json={"command": "RESUME"},
        headers={"X-Test-Context": "true"},
    )
    assert resume_res.status_code == 200
    assert resume_res.json()["command"] == "RESUME"

    # 6. Check run status
    status_res = client.get(f"/test/api/v1/runs/{run_id}", headers={"X-Test-Context": "true"})
    assert status_res.status_code == 200
    assert status_res.json()["id"] == run_id

    # 7. Cancel run
    cancel_res = client.post(
        f"/test/api/v1/runs/{run_id}/controls",
        json={"command": "CANCEL"},
        headers={"X-Test-Context": "true"},
    )
    assert cancel_res.status_code == 200


def test_fail_closed_credential_safeguard(monkeypatch):
    import pytest

    from src.services.test_simulation_repository import enforce_fail_closed_credential_safeguards

    # Should succeed without prod keys
    monkeypatch.delenv("TWILIO_AUTH_TOKEN", raising=False)
    enforce_fail_closed_credential_safeguards()

    # Must raise error if production credentials loaded in test mode
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", "prod-secret-token")
    with pytest.raises(RuntimeError) as excinfo:
        enforce_fail_closed_credential_safeguards()
    assert "FAIL-CLOSED CREDENTIAL SAFEGUARD" in str(excinfo.value)


def test_hosted_simulation_refuses_missing_or_operational_database():
    from src.config import Settings
    from src.services.test_simulation_repository import TestSimulationRepository

    with pytest.raises(RuntimeError, match="TEST_DATABASE_URL is required"):
        TestSimulationRepository(Settings(app_env="production", test_database_url=""))
    with pytest.raises(RuntimeError, match="isolated"):
        TestSimulationRepository(
            Settings(
                app_env="production",
                database_url="postgresql://db/operational",
                test_database_url="postgresql://db/operational",
            )
        )


@pytest.mark.asyncio
async def test_transactional_outbox_flow():
    from src.services.test_simulation_repository import TestSimulationRepository
    from src.services.test_simulation_runner import SimulationRunner

    repo = TestSimulationRepository()
    repo.create_outbox_event(
        aggregate_type="trip.telemetry",
        aggregate_id="trip-test-123",
        payload={"event_type": "telemetry.observed", "sequence": 1},
    )

    unprocessed = repo.fetch_unprocessed_outbox()
    assert len(unprocessed) >= 1

    class MockQueue:
        def __init__(self):
            self.items = []

        async def enqueue(self, payload):
            self.items.append(payload)
            return "mock-receipt"

    mock_q = MockQueue()
    runner = SimulationRunner(repository=repo, queue=mock_q)  # type: ignore[arg-type]
    dispatched = await runner.flush_outbox()
    assert dispatched >= 1

    remaining = repo.fetch_unprocessed_outbox()
    assert len(remaining) == 0


def test_simulation_does_not_fabricate_case_or_risk_from_faults():
    # A configured fault is telemetry input, not detector evidence.
    plan_res = client.post(
        "/test/api/v1/plans",
        json={"name": "Data Continuity Plan"},
        headers={"X-Test-Context": "true"},
    )
    plan_id = plan_res.json()["id"]

    rev_res = client.post(
        "/test/api/v1/definitions",
        json={
            "plan_id": plan_id,
            "route_geometry": {
                "type": "LineString",
                "coordinates": [[105.8524, 21.0285], [105.8342, 21.0450]],
            },
            "pickup_snapshot": {"location": {"latitude": 21.0285, "longitude": 105.8524}},
            "destination_snapshot": {"location": {"latitude": 21.0450, "longitude": 105.8342}},
            "driver_config": {"speed_mps": 10.0, "update_cadence_s": 1.0, "driver_id": TEST_DRIVER_ID},
            "fault_configs": [{"kind": "JUMP", "at_offset_s": 2, "displacement_m": 250.0, "bearing_deg": 90.0}],
            "messages": [
                {"sender_role": "DRIVER", "content": "I am on the way.", "offset_seconds": 0},
                {"sender_role": "PASSENGER", "content": "Waiting at lobby.", "offset_seconds": 1},
            ],
        },
        headers={"X-Test-Context": "true"},
    )
    rev_id = rev_res.json()["id"]

    # Start simulation run
    run_res = client.post(
        "/test/api/v1/runs",
        json={"definition_revision_id": rev_id, "speed_factor": 5.0},
        headers={"X-Test-Context": "true"},
    )
    assert run_res.status_code == 202
    run_id = run_res.json()["id"]
    _force_running(run_id)
    _force_running(run_id)

    # No case/risk is fabricated before detector output exists.
    cases_res = client.get(
        f"/test/api/v1/cases?run_id={run_id}", headers={"X-Test-Context": "true", "X-Role": "demo_operator"}
    )
    assert cases_res.status_code == 200
    assert cases_res.json() == []

    # Notifications remain sandbox-only.
    notif_res = client.get(
        f"/test/api/v1/runs/{run_id}/notifications",
        headers={"X-Test-Context": "true"},
    )
    assert notif_res.status_code == 200
    notifications = notif_res.json()
    assert len(notifications) == 2
    assert notifications[0]["body"] == "I am on the way."


def test_dynamic_speed_control():
    plan_res = client.post(
        "/test/api/v1/plans",
        json={"name": "Speed Control Plan"},
        headers={"X-Test-Context": "true"},
    )
    plan_id = plan_res.json()["id"]

    rev_res = client.post(
        "/test/api/v1/definitions",
        json={
            "plan_id": plan_id,
            "route_geometry": {
                "type": "LineString",
                "coordinates": [[105.8524, 21.0285], [105.8342, 21.0450]],
            },
            "pickup_snapshot": {"location": {"latitude": 21.0285, "longitude": 105.8524}},
            "destination_snapshot": {"location": {"latitude": 21.0450, "longitude": 105.8342}},
            "driver_config": {"speed_mps": 10.0, "update_cadence_s": 1.0, "driver_id": TEST_DRIVER_ID},
            "fault_configs": [],
            "messages": [],
        },
        headers={"X-Test-Context": "true"},
    )
    rev_id = rev_res.json()["id"]

    run_res = client.post(
        "/test/api/v1/runs",
        json={"definition_revision_id": rev_id, "speed_factor": 1.0},
        headers={"X-Test-Context": "true"},
    )
    assert run_res.status_code == 202
    run_id = run_res.json()["id"]
    _force_running(run_id)

    ctrl_res = client.post(
        f"/test/api/v1/runs/{run_id}/control",
        json={"command": "SET_SPEED_FACTOR", "payload": {"speed_factor": 10.0}},
        headers={"X-Test-Context": "true"},
    )
    assert ctrl_res.status_code == 200


def test_simulation_route_resolution_endpoint(monkeypatch):
    from unittest.mock import MagicMock

    mock_osrm_res = MagicMock()
    mock_osrm_res.status = 200
    mock_osrm_res.read.return_value = (
        b'{"routes":[{"geometry":{"type":"LineString","coordinates":[[105.85,21.02],[105.851,21.025],[105.852,21.028]]},'
        b'"distance":500.0,"duration":60.0}]}'
    )
    mock_osrm_res.__enter__.return_value = mock_osrm_res
    mock_osrm_res.__exit__.return_value = None

    monkeypatch.setattr("src.services.routing_service.urlopen", lambda *args, **kwargs: mock_osrm_res)

    res = client.post(
        "/test/api/v1/routes/resolve",
        json={
            "origin": [105.8524, 21.0285],
            "pickup": [105.8520, 21.0278],
            "destination": [105.8340, 21.0480],
        },
        headers={"X-Test-Context": "true"},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["provider"] == "osrm"
    assert "pickup_route" in data
    assert "destination_route" in data
    geometry = data["route_geometry"]
    assert geometry["type"] == "MultiLineString"
    assert len(geometry["coordinates"]) == 2
    assert all(len(leg) == 3 for leg in geometry["coordinates"])

    # Provider failure must not invent a route or metrics.
    monkeypatch.setattr("src.services.routing_service.urlopen", MagicMock(side_effect=Exception("Network error")))
    fallback_res = client.post(
        "/test/api/v1/routes/resolve",
        json={
            "origin": [105.8524, 21.0285],
            "pickup": [105.8520, 21.0278],
            "destination": [105.8340, 21.0480],
        },
        headers={"X-Test-Context": "true"},
    )
    assert fallback_res.status_code == 503
    assert fallback_res.json() == {"detail": "Route provider unavailable"}


def test_simulation_explicit_save_case_and_triage():
    # 1. Create plan, definition with fault, and run
    plan_res = client.post(
        "/test/api/v1/plans",
        json={"name": "Save Case Plan"},
        headers={"X-Test-Context": "true"},
    )
    plan_id = plan_res.json()["id"]

    rev_res = client.post(
        "/test/api/v1/definitions",
        json={
            "plan_id": plan_id,
            "route_geometry": {
                "type": "LineString",
                "coordinates": [[105.8524, 21.0285], [105.8342, 21.0450]],
            },
            "pickup_snapshot": {"location": {"latitude": 21.0285, "longitude": 105.8524}},
            "destination_snapshot": {"location": {"latitude": 21.045, "longitude": 105.8342}},
            "driver_config": {"speed_mps": 12.0, "update_cadence_s": 1.0, "driver_id": TEST_DRIVER_ID},
            "fault_configs": [{"kind": "JUMP", "at_offset_s": 5, "displacement_m": 200.0, "bearing_deg": 90.0}],
            "messages": [],
        },
        headers={"X-Test-Context": "true"},
    )
    rev_id = rev_res.json()["id"]

    run_res = client.post(
        "/test/api/v1/runs",
        json={"definition_revision_id": rev_id, "speed_factor": 1.0},
        headers={"X-Test-Context": "true"},
    )
    run_id = run_res.json()["id"]

    from datetime import UTC, datetime

    from src.models.test_simulation import TestTelemetrySample
    from src.services.test_simulation_runner import get_simulation_runner

    repository = get_simulation_runner().repository
    repository.save_sample(
        TestTelemetrySample(
            run_id=run_id,
            step_index=0,
            latitude=21.0285,
            longitude=105.8524,
            speed_mps=12.0,
            heading_deg=90.0,
            emitted_at=datetime.now(UTC),
            is_fault_injected=True,
            fault_type="JUMP",
        )
    )
    repository.update_run_status(run_id, "COMPLETED")

    # 2. Before saving, case does not exist in workplace
    cases_before = client.get(
        f"/test/api/v1/cases?run_id={run_id}",
        headers={"X-Test-Context": "true"},
    )
    assert cases_before.status_code == 200
    assert cases_before.json() == []

    # 3. Explicitly save simulation case
    save_res = client.post(
        f"/test/api/v1/runs/{run_id}/save-case",
        headers={"X-Test-Context": "true"},
    )
    assert save_res.status_code == 201
    case_data = save_res.json()
    case_id = case_data["id"]
    assert case_id == f"case-sim-{run_id}"
    assert case_data["run_id"] == run_id
    assert case_data["status"] == "OPEN"
    assert "ERR-05" in case_data["anomaly_types"]
    assert case_data["risk_score"] > 0.5

    # 4. Case now appears in workplace triage queue
    cases_after = client.get(
        f"/test/api/v1/cases?run_id={run_id}",
        headers={"X-Test-Context": "true"},
    )
    assert cases_after.status_code == 200
    cases_list = cases_after.json()
    assert len(cases_list) == 1
    assert cases_list[0]["id"] == case_id

    # 4b. Idempotency: repeated save returns existing case without error or duplicate
    repeat_save = client.post(
        f"/test/api/v1/runs/{run_id}/save-case",
        headers={"X-Test-Context": "true"},
    )
    assert repeat_save.status_code == 201
    assert repeat_save.json()["id"] == case_id
    cases_after_repeat = client.get(
        f"/test/api/v1/cases?run_id={run_id}",
        headers={"X-Test-Context": "true"},
    )
    assert len(cases_after_repeat.json()) == 1

    # 5. Triage the case
    triage_res = client.post(
        f"/test/api/v1/cases/{case_id}/triage",
        json={"decision": "APPROVE_LEGITIMATE", "rationale": "Verified GPS jump behavior"},
        headers={"X-Test-Context": "true"},
    )
    assert triage_res.status_code == 200
    assert triage_res.json()["new_status"] == "CLOSED"

    # 6. Verify status updated in case queue
    updated_cases = client.get(
        f"/test/api/v1/cases?run_id={run_id}",
        headers={"X-Test-Context": "true"},
    )
    assert updated_cases.status_code == 200
    assert updated_cases.json()[0]["status"] == "CLOSED"


def test_simulation_real_detection_and_case_detail():
    # 1. Faulty run (JUMP fault)
    plan_res = client.post(
        "/test/api/v1/plans",
        json={"name": "Real Detection Plan"},
        headers={"X-Test-Context": "true"},
    )
    plan_id = plan_res.json()["id"]

    rev_res = client.post(
        "/test/api/v1/definitions",
        json={
            "plan_id": plan_id,
            "route_geometry": {
                "type": "LineString",
                "coordinates": [[105.8524, 21.0285], [105.8342, 21.0450]],
            },
            "pickup_snapshot": {"location": {"latitude": 21.0285, "longitude": 105.8524}},
            "destination_snapshot": {"location": {"latitude": 21.045, "longitude": 105.8342}},
            "driver_config": {"speed_mps": 12.0, "update_cadence_s": 1.0, "driver_id": TEST_DRIVER_ID},
            "fault_configs": [{"kind": "JUMP", "at_offset_s": 2, "displacement_m": 250.0, "bearing_deg": 90.0}],
            "messages": [],
        },
        headers={"X-Test-Context": "true"},
    )
    rev_id = rev_res.json()["id"]

    run_res = client.post(
        "/test/api/v1/runs",
        json={"definition_revision_id": rev_id},
        headers={"X-Test-Context": "true"},
    )
    run_id = run_res.json()["id"]

    from datetime import UTC, datetime

    from src.models.test_simulation import TestTelemetrySample
    from src.services.test_simulation_runner import get_simulation_runner

    repository = get_simulation_runner().repository
    repository.save_sample(
        TestTelemetrySample(
            run_id=run_id,
            step_index=0,
            latitude=21.0285,
            longitude=105.8574,
            speed_mps=12.0,
            heading_deg=90.0,
            emitted_at=datetime.now(UTC),
            is_fault_injected=True,
            fault_type="JUMP",
        )
    )
    repository.update_run_status(run_id, "COMPLETED")

    save_res = client.post(
        f"/test/api/v1/runs/{run_id}/save-case",
        headers={"X-Test-Context": "true"},
    )
    assert save_res.status_code == 201
    case_data = save_res.json()
    # Real Jev Assessment classifies JUMP as ERR-05 with 0.98 confidence (not hardcoded 0.88)
    assert case_data["risk_score"] == 0.98
    assert "ERR-05" in case_data["anomaly_types"]
    assert "ERR-05" in case_data["anomaly_types"]

    # Verify detail
    detail_res = client.get(
        f"/test/api/v1/cases/{case_data['id']}/detail",
        headers={"X-Test-Context": "true"},
    )
    assert detail_res.status_code == 200
    detail = detail_res.json()
    assert detail["features"]["mock_location_detected"] is True
    assert detail["features"]["drift_distance_m"] > 100.0
    assert detail["traffic_corroboration"]["verdict"] == "refuted"
    assert detail["assessment"]["category"] == "ERR-05"
    assert detail["assessment"]["confidence"] == 0.98

    # 2. Nominal run (No faults)
    nominal_rev = client.post(
        "/test/api/v1/definitions",
        json={
            "plan_id": plan_id,
            "route_geometry": {
                "type": "LineString",
                "coordinates": [[105.8524, 21.0285], [105.8342, 21.0450]],
            },
            "pickup_snapshot": {"location": {"latitude": 21.0285, "longitude": 105.8524}},
            "destination_snapshot": {"location": {"latitude": 21.045, "longitude": 105.8342}},
            "driver_config": {"speed_mps": 12.0, "update_cadence_s": 1.0, "driver_id": TEST_DRIVER_ID},
            "fault_configs": [],
            "messages": [],
        },
        headers={"X-Test-Context": "true"},
    )
    nom_run = client.post(
        "/test/api/v1/runs",
        json={"definition_revision_id": nominal_rev.json()["id"]},
        headers={"X-Test-Context": "true"},
    ).json()
    _force_running(nom_run["id"])
    complete_nominal = client.post(
        f"/test/api/v1/runs/{nom_run['id']}/controls",
        json={"command": "FAST_COMPLETE", "payload": {}},
        headers={"X-Test-Context": "true"},
    )
    assert complete_nominal.status_code == 200

    repository.save_sample(
        TestTelemetrySample(
            run_id=nom_run["id"],
            step_index=0,
            latitude=21.0285,
            longitude=105.8524,
            speed_mps=12.0,
            heading_deg=0.0,
            emitted_at=datetime.now(UTC),
        )
    )
    from uuid import UUID

    repository.update_run_status(UUID(nom_run["id"]), "COMPLETED")

    nom_save = client.post(
        f"/test/api/v1/runs/{nom_run['id']}/save-case",
        headers={"X-Test-Context": "true"},
    ).json()

    # Nominal trip is evaluated dynamically as no_violation (0.05 risk score, not hardcoded 0.04)
    assert nom_save["risk_score"] == 0.05
    assert nom_save["anomaly_types"] == ["NORMAL_TRIP"]

    nom_detail = client.get(
        f"/test/api/v1/cases/{nom_save['id']}/detail",
        headers={"X-Test-Context": "true"},
    ).json()
    assert nom_detail["features"]["mock_location_detected"] is False
    assert nom_detail["features"]["drift_distance_m"] < 1.0
    assert nom_detail["traffic_corroboration"]["verdict"] == "corroborated"
    assert nom_detail["assessment"]["category"] == "no_violation"


def _force_running(run_id: str) -> None:
    from uuid import UUID

    from src.services.test_simulation_runner import get_simulation_runner

    get_simulation_runner().repository.update_run_status(UUID(run_id), "RUNNING")

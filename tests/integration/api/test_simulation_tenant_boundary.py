"""Public simulation API ownership, including durable PostgreSQL restarts."""

import os
from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from src.api import test_routes
from src.api.auth import Principal
from src.config import Settings
from src.services.driver_directory import (
    DriverRecord,
    HybridDriverDirectory,
    InMemoryDriverDirectory,
    set_driver_directory,
)
from src.services.test_simulation_repository import TestSimulationRepository
from src.services.test_simulation_runner import SimulationRunner

BASE = "/test/api/v1"
ORG_A, ORG_B, ACTOR = (str(uuid4()) for _ in range(3))
DRIVER_A_ID = UUID("018f2f4e-3000-7000-8000-0000000000a1")
DRIVER_B_ID = UUID("018f2f4e-3000-7000-8000-0000000000b1")


@pytest.fixture(autouse=True)
def setup_test_drivers():
    """Seed active Clerk-linked drivers for ORG_A and ORG_B into in-memory driver directory."""
    dir_svc = InMemoryDriverDirectory()
    set_driver_directory(dir_svc)

    for org, drv_id, sub, name in [
        (ORG_A, DRIVER_A_ID, "user_clerk_a", "Driver A"),
        (ORG_B, DRIVER_B_ID, "user_clerk_b", "Driver B"),
    ]:
        dir_svc.register_driver(
            DriverRecord(
                driver_id=drv_id,
                organization_id=org,
                principal_id=UUID("018f2f4e-2000-7000-8000-000000000001"),
                external_subject=sub,
                display_name=name,
                email=f"{sub}@example.com",
                account_status="active",
                license_plate="29A-123.45",
            )
        )

    yield dir_svc
    set_driver_directory(HybridDriverDirectory())


@pytest.fixture(params=["memory", "postgres"])
def boundary(request, monkeypatch):
    database = os.getenv("TEST_SIMULATION_DATABASE_URL", "") if request.param == "postgres" else ""
    if request.param == "postgres" and not database:
        pytest.skip("Set TEST_SIMULATION_DATABASE_URL to a migrated disposable PostgreSQL database")
    settings = Settings(app_env="test", test_database_url=database, database_url="")
    repo = TestSimulationRepository(settings)
    runner = SimulationRunner(repository=repo, settings=settings)
    runner.start_run = AsyncMock()
    runner.apply_control = AsyncMock()
    monkeypatch.setattr(test_routes, "get_simulation_runner", lambda: runner)

    async def identity(request: Request, *args):
        return Principal(ACTOR, request.headers.get("Test-Org", ""), frozenset())

    monkeypatch.setattr(test_routes, "require_principal", identity)
    api = FastAPI()
    api.include_router(test_routes.router, prefix="/test/api/v1")
    with TestClient(api) as client:
        yield client, runner, settings
    repo.close()


def headers(org=ORG_A):
    return {"X-Test-Context": "true", "Test-Org": org, "X-Organization-Id": org}


def create_run(client, org=ORG_A, key=None):
    plan = client.post(f"{BASE}/plans", headers=headers(org), json={"name": "Tenant boundary"})
    assert plan.status_code == 201, plan.text
    driver_id = DRIVER_A_ID if org == ORG_A else DRIVER_B_ID
    definition = client.post(
        f"{BASE}/definitions",
        headers=headers(org),
        json={
            "plan_id": plan.json()["id"],
            "route_geometry": {"type": "LineString", "coordinates": [[105.0, 21.0], [105.001, 21.001]]},
            "driver_config": {"driver_id": str(driver_id)},
            "initial_snapshot": {"location": {"latitude": 21.0, "longitude": 105.0}},
            "pickup_snapshot": {"location": {"latitude": 21.0, "longitude": 105.0}},
            "destination_snapshot": {"location": {"latitude": 21.001, "longitude": 105.001}},
        },
    )
    assert definition.status_code == 201, definition.text
    payload = {"definition_revision_id": definition.json()["id"], "idempotency_key": key}
    response = client.post(f"{BASE}/runs", headers=headers(org), json=payload)
    assert response.status_code == 202, response.text
    return plan.json()["id"], definition.json()["id"], response.json()["id"], payload


def test_requires_active_organization(boundary):
    client, _, _ = boundary
    assert client.get(f"{BASE}/plans", headers=headers("")).status_code == 403


@pytest.mark.parametrize("state", ["QUEUED", "RUNNING", "PAUSED"])
def test_in_progress_case_save_does_not_assess_recorded_or_future_points(boundary, monkeypatch, state):
    from src.models.test_simulation import TestTelemetrySample

    client, runner, _ = boundary
    _, _, run_id, _ = create_run(client)
    runner.repository.save_sample(
        TestTelemetrySample(
            run_id=UUID(run_id),
            step_index=0,
            latitude=21,
            longitude=105,
            speed_mps=5,
            heading_deg=45,
            emitted_at=datetime.now(UTC),
        )
    )
    runner.repository.update_run_status(UUID(run_id), state)
    assessor = AsyncMock(return_value={"category": "no_violation", "confidence": 0.8})
    monkeypatch.setattr(test_routes.JevAssessmentAgent, "assess", assessor)
    response = client.post(f"{BASE}/runs/{run_id}/save-case", headers=headers())
    assert response.status_code == 409, response.text
    assessor.assert_not_awaited()


def test_terminal_case_save_requires_recorded_telemetry(boundary, monkeypatch):
    client, runner, _ = boundary
    _, _, run_id, _ = create_run(client)
    runner.repository.update_run_status(UUID(run_id), "COMPLETED")
    assessor = AsyncMock()
    monkeypatch.setattr(test_routes.JevAssessmentAgent, "assess", assessor)
    response = client.post(f"{BASE}/runs/{run_id}/save-case", headers=headers())
    assert response.status_code == 409, response.text
    assert response.json()["detail"] == "Simulation has no recorded telemetry"
    assessor.assert_not_awaited()


def test_terminal_case_save_assesses_only_recorded_samples(boundary, monkeypatch):
    from src.models.test_simulation import TestTelemetrySample

    client, runner, _ = boundary
    _, _, run_id, _ = create_run(client)
    runner.repository.save_sample(
        TestTelemetrySample(
            run_id=UUID(run_id),
            step_index=0,
            latitude=21,
            longitude=105,
            speed_mps=5,
            heading_deg=45,
            emitted_at=datetime.now(UTC),
        )
    )
    runner.repository.update_run_status(UUID(run_id), "COMPLETED")
    assessor = AsyncMock(return_value={"category": "no_violation", "confidence": 0.8})
    monkeypatch.setattr(test_routes.JevAssessmentAgent, "assess", assessor)
    response = client.post(f"{BASE}/runs/{run_id}/save-case", headers=headers())
    assert response.status_code == 201, response.text
    points = assessor.call_args.args[0]["points"]
    assert len(points) == 1
    assert points[0]["latitude"] == 21
    assert points[0]["longitude"] == 105


def test_definition_and_run_routes_hide_foreign_resources_before_effects(boundary):
    client, runner, _ = boundary
    plan, definition, run, payload = create_run(client)
    runner.start_run.reset_mock()
    for path in [
        f"plans/{plan}",
        f"definitions/{definition}",
        f"runs/{run}",
        f"runs/{run}/samples",
        f"runs/{run}/notifications",
        f"runs/{run}/stream",
    ]:
        assert client.get(f"{BASE}/{path}", headers=headers(ORG_B)).status_code == 404, path
    assert client.post(f"{BASE}/runs", headers=headers(ORG_B), json=payload).status_code == 404
    for path, body in [
        (f"runs/{run}/control", {"command": "CANCEL"}),
        (f"runs/{run}/save-case", {}),
        (f"runs/{run}/publish-production", {}),
    ]:
        assert client.post(f"{BASE}/{path}", headers=headers(ORG_B), json=body).status_code == 404, path
    runner.start_run.assert_not_called()
    runner.apply_control.assert_not_called()


def test_cases_are_scoped_and_durable(boundary):
    client, runner, settings = boundary
    _, _, run, _ = create_run(client)
    case_id = str(uuid4())
    runner.repository.create_case(
        {
            "id": case_id,
            "run_id": run,
            "trip_id": str(uuid4()),
            "risk_score": 0.7,
            "anomaly_types": [],
            "status": "OPEN",
            "created_at": datetime.now(UTC),
        }
    )
    if settings.test_database_url:
        runner.repository.close()
        runner.repository = TestSimulationRepository(settings)
    assert any(row["id"] == case_id for row in client.get(f"{BASE}/cases", headers=headers()).json())
    assert client.get(f"{BASE}/cases", headers=headers(ORG_B)).json() == []
    assert client.get(f"{BASE}/cases/{case_id}", headers=headers(ORG_B)).status_code == 404
    assert (
        client.post(
            f"{BASE}/cases/{case_id}/triage",
            headers=headers(ORG_B),
            json={"decision": "INVESTIGATE", "rationale": "cross tenant"},
        ).status_code
        == 404
    )
    assert runner.repository.get_case(case_id)["status"] == "OPEN"
    accepted = client.post(
        f"{BASE}/cases/{case_id}/triage", headers=headers(), json={"decision": "INVESTIGATE", "rationale": "review"}
    )
    assert accepted.status_code == 200
    if settings.test_database_url:
        runner.repository.close()
        runner.repository = TestSimulationRepository(settings)
    assert runner.repository.get_case(case_id)["status"] == "UNDER_REVIEW"


def test_idempotency_is_organization_scoped_across_restart(boundary):
    client, runner, settings = boundary
    key = str(uuid4())
    _, _, run_a, payload = create_run(client, key=key)
    _, _, run_b, _ = create_run(client, org=ORG_B, key=key)
    assert run_a != run_b
    if settings.test_database_url:
        runner.repository.close()
        runner.repository = TestSimulationRepository(settings)
    repeated = client.post(f"{BASE}/runs", headers=headers(), json=payload)
    assert repeated.status_code == 202, repeated.text
    assert repeated.json()["id"] == run_a
    assert client.get(f"{BASE}/runs/{run_a}", headers=headers(ORG_B)).status_code == 404


def test_missing_run_cannot_publish_payload_fallback(boundary):
    client, _, _ = boundary
    response = client.post(
        f"{BASE}/runs/{uuid4()}/publish-production",
        headers=headers(),
        json={"points": [{"latitude": 21, "longitude": 105}]},
    )
    assert response.status_code == 404


def test_invalid_case_filter_is_validation_error(boundary):
    client, _, _ = boundary
    assert client.get(f"{BASE}/cases?run_id=garbage", headers=headers()).status_code == 422


def test_idempotency_conflict_rejected(boundary):
    client, _, _ = boundary
    key = str(uuid4())
    create_run(client, key=key)
    _, _, _, other_payload = create_run(client)
    other_payload["idempotency_key"] = key
    response = client.post(f"{BASE}/runs", headers=headers(), json=other_payload)
    assert response.status_code == 409


def test_publish_rejects_forged_organization(boundary):
    client, _, _ = boundary
    _, _, run, _ = create_run(client)
    response = client.post(f"{BASE}/runs/{run}/publish-production", headers=headers(), json={"organization_id": ORG_B})
    assert response.status_code == 409


def test_case_assessment_cannot_be_overridden_by_client_labels(boundary, monkeypatch):
    client, _, _ = boundary
    monkeypatch.setattr(
        test_routes.JevAssessmentAgent,
        "assess",
        AsyncMock(return_value={"category": "no_violation", "confidence": 0.95}),
    )
    _, _, run, _ = create_run(client)
    response = client.post(
        f"{BASE}/runs/{run}/save-case", headers=headers(), json={"risk_score": 1.0, "anomaly_types": ["ERR-01"]}
    )
    assert response.status_code == 422


@pytest.mark.parametrize("outcome", ["nominal", "case", "error", "unpersisted"])
def test_publish_uses_verified_org_and_actual_persistence_result(boundary, monkeypatch, outcome):
    from src.models.test_simulation import TestTelemetrySample
    from src.services import test_simulation_publish

    client, runner, _ = boundary
    _, _, run, _ = create_run(client)
    runner.repository.update_run_status(UUID(run), "COMPLETED")
    for step in range(2):
        runner.repository.save_sample(
            TestTelemetrySample(
                run_id=UUID(run),
                step_index=step,
                latitude=21 + step / 1000,
                longitude=105 + step / 1000,
                speed_mps=5,
                heading_deg=45,
                emitted_at=datetime.now(UTC),
            )
        )
    case_id = str(uuid4()) if outcome == "case" else None
    processor = AsyncMock(
        return_value={
            "status": "queued" if outcome == "unpersisted" else "processed",
            "trip_id": str(uuid4()),
            "case_id": case_id,
        }
    )
    if outcome == "error":
        processor.side_effect = RuntimeError("database unavailable")
    monkeypatch.setattr(test_simulation_publish, "process_telemetry_event", processor)
    response = client.post(
        f"{BASE}/runs/{run}/publish-production",
        headers=headers(),
        json={
            "driver_id": str(uuid4()),
            "passenger_id": str(uuid4()),
            "vehicle_id": str(uuid4()),
            "policy_version_id": str(uuid4()),
            "points": [{"latitude": 0, "longitude": 0, "risk_score": 1}],
        },
    )
    assert response.status_code == (503 if outcome in {"error", "unpersisted"} else 201), response.text
    event = processor.call_args.args[0]
    assert processor.call_args.kwargs["organization_id"] == ORG_A
    assert event["organization_id"] == ORG_A
    assert event["points"][0]["latitude"] == 21
    assert "force_create_case" not in event
    assert "case_id" not in event
    if response.status_code == 201:
        assert response.json()["case_id"] == case_id


def test_fixture_auth_still_requires_explicit_organization(monkeypatch):
    from src.config import get_settings

    api = FastAPI()
    api.include_router(test_routes.router, prefix=BASE)
    api.dependency_overrides[get_settings] = lambda: Settings(app_env="test", test_auth_enabled=True)
    with TestClient(api) as client:
        response = client.get(f"{BASE}/plans", headers={"X-Test-Context": "true", "X-Principal-Id": ACTOR})
    assert response.status_code == 403

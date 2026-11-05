"""Publish path must carry recorded cancellation evidence to the pipeline.

A cancelled simulation is not a completed one: the canonical telemetry event
must expose the participant actor and reason so downstream agents and cases can
read them, and a normal run must never be mislabelled as cancelled.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from src.models.test_simulation import (
    DriverSimConfig,
    GeoJsonLineString,
    LatLon,
    PassengerSimConfig,
    PublishProductionPayload,
    TestDefinitionRevisionCreate,
    TestPlanCreate,
    TestRunCreate,
    TestStopSnapshot,
    TestTelemetrySample,
)
from src.services import test_simulation_publish
from src.services.test_simulation_repository import TestSimulationRepository

ORG = "018f2f4e-0000-7000-8000-000000000001"


def _repository_with_run(*, cancelled: bool) -> tuple[TestSimulationRepository, object]:
    repo = TestSimulationRepository()
    plan = repo.create_plan(TestPlanCreate(name="Publish evidence"), ORG)
    definition = repo.create_definition_revision(
        TestDefinitionRevisionCreate(
            plan_id=plan.id,
            route_geometry=GeoJsonLineString(coordinates=[[105.8524, 21.0285], [105.8342, 21.0450]]),
            driver_config=DriverSimConfig(speed_mps=12.0, driver_id="drv-pub-001"),
            passenger_config=PassengerSimConfig(passenger_id="pass-pub-001"),
            fault_configs=[],
            messages=[],
            initial_snapshot=TestStopSnapshot(location=LatLon(latitude=21.0, longitude=105.0), address="Origin"),
            pickup_snapshot=TestStopSnapshot(location=LatLon(latitude=21.0285, longitude=105.8524), address="Pickup"),
            destination_snapshot=TestStopSnapshot(
                location=LatLon(latitude=21.045, longitude=105.8342), address="Dropoff"
            ),
        ),
        ORG,
    )
    run = repo.create_run(TestRunCreate(definition_revision_id=definition.id), total_steps=5, organization_id=ORG)
    repo.save_sample(
        TestTelemetrySample(
            run_id=run.id,
            step_index=0,
            latitude=21.0285,
            longitude=105.8524,
            speed_mps=12.0,
            heading_deg=0.0,
            emitted_at=datetime.now(UTC),
        )
    )
    if cancelled:
        repo.update_run_status(
            run.id,
            "CANCELLED",
            cancellation_actor="passenger",
            cancellation_reason="Customer changed plan",
        )
    else:
        repo.update_run_status(run.id, "COMPLETED")
    return repo, run.id


def _payload() -> PublishProductionPayload:
    return PublishProductionPayload(
        driver_id="drv-pub-001",
        passenger_id="pass-pub-001",
        vehicle_id="veh-pub-001",
        policy_version_id="pol-pub-001",
    )


@pytest.mark.asyncio
async def test_cancelled_run_publishes_cancellation_evidence(monkeypatch):
    captured: dict[str, object] = {}

    async def fake_process(event, service, *, organization_id):
        captured.update(event)
        return {"status": "processed", "trip_id": event["trip_id"], "case_id": None}

    monkeypatch.setattr(test_simulation_publish, "process_telemetry_event", fake_process)

    repo, run_id = _repository_with_run(cancelled=True)
    result = await test_simulation_publish.publish_simulation(repo, run_id, _payload(), ORG, service=None)  # type: ignore[arg-type]

    assert captured["lifecycle_state"] == "cancelled"
    assert captured["cancellation_actor"] == "passenger"
    assert captured["cancellation_reason"] == "Customer changed plan"
    assert result.status == "published"


@pytest.mark.asyncio
async def test_normal_run_publishes_completed_without_cancellation(monkeypatch):
    captured: dict[str, object] = {}

    async def fake_process(event, service, *, organization_id):
        captured.update(event)
        return {"status": "processed", "trip_id": event["trip_id"], "case_id": None}

    monkeypatch.setattr(test_simulation_publish, "process_telemetry_event", fake_process)

    repo, run_id = _repository_with_run(cancelled=False)
    await test_simulation_publish.publish_simulation(repo, run_id, _payload(), ORG, service=None)  # type: ignore[arg-type]

    assert captured["lifecycle_state"] == "completed"
    assert "cancellation_actor" not in captured
    assert "cancellation_reason" not in captured


@pytest.mark.asyncio
async def test_retry_reuses_ingestion_identity(monkeypatch):
    events: list[dict[str, object]] = []

    async def fake_process(event, service, *, organization_id):
        events.append(event)
        return {"status": "processed", "trip_id": event["trip_id"], "case_id": None}

    monkeypatch.setattr(test_simulation_publish, "process_telemetry_event", fake_process)
    repo, run_id = _repository_with_run(cancelled=False)
    await test_simulation_publish.publish_simulation(repo, run_id, _payload(), ORG, service=None)  # type: ignore[arg-type]
    await test_simulation_publish.publish_simulation(repo, run_id, _payload(), ORG, service=None)  # type: ignore[arg-type]

    assert len(events) == 1


@pytest.mark.asyncio
async def test_retry_uses_persisted_publish_receipt_without_reprocessing(monkeypatch):
    processor = AsyncMock(return_value={"status": "processed", "trip_id": "trip-1", "case_id": "case-1"})
    monkeypatch.setattr(test_simulation_publish, "process_telemetry_event", processor)
    repo, run_id = _repository_with_run(cancelled=False)
    first = await test_simulation_publish.publish_simulation(repo, run_id, _payload(), ORG, service=None)  # type: ignore[arg-type]
    second = await test_simulation_publish.publish_simulation(repo, run_id, _payload(), ORG, service=None)  # type: ignore[arg-type]

    assert first == second
    processor.assert_awaited_once()


@pytest.mark.asyncio
async def test_oversized_run_is_rejected_without_truncating_evidence(monkeypatch):
    repo, run_id = _repository_with_run(cancelled=False)
    for index in range(1, 2001):
        repo.save_sample(
            TestTelemetrySample(
                run_id=run_id,
                step_index=index,
                latitude=21.0285,
                longitude=105.8524,
                speed_mps=12.0,
                heading_deg=0.0,
                emitted_at=datetime.now(UTC),
            )
        )

    processor = AsyncMock()
    monkeypatch.setattr(test_simulation_publish, "process_telemetry_event", processor)
    with pytest.raises(Exception) as error:
        await test_simulation_publish.publish_simulation(repo, run_id, _payload(), ORG, service=None)  # type: ignore[arg-type]
    assert getattr(error.value, "status_code", None) == 413
    processor.assert_not_awaited()


@pytest.mark.asyncio
async def test_concurrent_publish_processes_one_owned_run_once(monkeypatch):
    calls = []

    async def process(event, service, *, organization_id):
        calls.append(event)
        await asyncio.sleep(0.02)
        return {"status": "processed", "trip_id": event["trip_id"], "case_id": None, "category": "no_violation"}

    monkeypatch.setattr(test_simulation_publish, "process_telemetry_event", process)
    repo, run_id = _repository_with_run(cancelled=False)
    first, second = await asyncio.gather(
        *[test_simulation_publish.publish_simulation(repo, run_id, _payload(), ORG, service=None) for _ in range(2)]
    )
    assert first == second
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_publish_simulation_propagates_address_labels(monkeypatch):
    captured: dict[str, object] = {}

    async def fake_process(event, service, *, organization_id):
        captured.update(event)
        return {"status": "processed", "trip_id": event["trip_id"], "case_id": None}

    monkeypatch.setattr(test_simulation_publish, "process_telemetry_event", fake_process)

    repo, run_id = _repository_with_run(cancelled=False)
    payload = PublishProductionPayload(
        driver_id="drv-pub-001",
        passenger_id="pass-pub-001",
        vehicle_id="veh-pub-001",
        policy_version_id="pol-pub-001",
        pickup_address="Vincom Center Bà Triệu",
        dropoff_address="Hồ Tây",
    )
    await test_simulation_publish.publish_simulation(repo, run_id, payload, ORG, service=None)  # type: ignore[arg-type]

    assert captured.get("pickup_address") == "Vincom Center Bà Triệu"
    assert captured.get("dropoff_address") == "Hồ Tây"

"""Disposable PostgreSQL receipts survive restart and serialize API processes."""

import asyncio
import os
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from src.config import Settings
from src.models.test_simulation import (
    GeoJsonLineString,
    LatLon,
    PublishProductionPayload,
)
from src.models.test_simulation import (
    TestDefinitionRevisionCreate as Definition,
)
from src.models.test_simulation import (
    TestPlanCreate as Plan,
)
from src.models.test_simulation import (
    TestRunCreate as Run,
)
from src.models.test_simulation import (
    TestStopSnapshot as Stop,
)
from src.models.test_simulation import (
    TestTelemetrySample as Sample,
)
from src.services import test_simulation_publish as publishing
from src.services.test_simulation_repository import TestSimulationRepository as Repository


@pytest.fixture
def owned_run():
    url = os.getenv("TEST_SIMULATION_DATABASE_URL")
    if not url:
        pytest.skip("TEST_SIMULATION_DATABASE_URL must name a migrated disposable PostgreSQL database")
    settings = Settings(app_env="test", test_database_url=url, database_url="")
    repo = Repository(settings)
    org = str(uuid4())
    plan = repo.create_plan(Plan(name="Receipt restart"), org)
    stop = Stop(location=LatLon(latitude=21.0, longitude=105.0), address="Recorded pickup")
    definition = repo.create_definition_revision(
        Definition(
            plan_id=plan.id,
            route_geometry=GeoJsonLineString(coordinates=[[105.0, 21.0], [105.1, 21.1]]),
            initial_snapshot=stop,
            pickup_snapshot=stop,
            destination_snapshot=stop,
        ),
        org,
    )
    run = repo.create_run(Run(definition_revision_id=definition.id), total_steps=1, organization_id=org)
    repo.save_sample(
        Sample(
            run_id=run.id,
            step_index=0,
            latitude=21.0,
            longitude=105.0,
            speed_mps=12,
            heading_deg=0,
            emitted_at=datetime.now(UTC),
        )
    )
    repo.update_run_status(run.id, "COMPLETED")
    yield settings, repo, run.id, org
    repo.close()


@pytest.mark.asyncio
async def test_receipt_survives_repository_restart_and_hides_foreign_scope(owned_run, monkeypatch):
    settings, repo, run_id, org = owned_run
    calls = []

    async def process(event, service, *, organization_id):
        calls.append(event)
        return {"status": "processed", "trip_id": event["trip_id"], "case_id": None, "category": "no_violation"}

    monkeypatch.setattr(publishing, "process_telemetry_event", process)
    payload = PublishProductionPayload(driver_id="d", passenger_id="p", vehicle_id="v", policy_version_id="policy")
    first = await publishing.publish_simulation(repo, run_id, payload, org, None)
    repo.close()
    restarted = Repository(settings)
    try:
        second = await publishing.publish_simulation(restarted, run_id, payload, org, None)
        assert second == first
        assert len(calls) == 1
        assert restarted.get_publish_submission(run_id, str(uuid4())) is None
        receipt = restarted.get_publish_submission(run_id, org, include_processing=True)
        assert receipt["result"]["category"] == "no_violation"
    finally:
        restarted.close()


@pytest.mark.asyncio
async def test_independent_repositories_process_concurrent_submission_once(owned_run, monkeypatch):
    settings, repo, run_id, org = owned_run
    calls = []

    async def process(event, service, *, organization_id):
        calls.append(event)
        await asyncio.sleep(0.05)
        return {"status": "processed", "trip_id": event["trip_id"], "case_id": None, "category": "no_violation"}

    monkeypatch.setattr(publishing, "process_telemetry_event", process)
    other = Repository(settings)
    payload = PublishProductionPayload(driver_id="d", passenger_id="p", vehicle_id="v", policy_version_id="policy")
    try:
        first, second = await asyncio.gather(
            publishing.publish_simulation(repo, run_id, payload, org, None),
            publishing.publish_simulation(other, run_id, payload, org, None),
        )
        assert first == second
        assert len(calls) == 1
    finally:
        other.close()

from copy import deepcopy
from pathlib import Path

import pytest
from fastapi import HTTPException

from scripts.road_trip_generator import RoadTripFixture, RoadTripManifest, validate_road_trip
from src.config import Settings
from src.models.schemas import TelemetryEventEnvelope
from src.services.case_service import CaseService


def road_trip():
    fixture = RoadTripFixture.load(Path("tests/fixtures/road_telemetry"))
    return RoadTripManifest.build(fixture).to_dict()


def test_normal_trip_matches_road_endpoints_and_public_ingest_contract():
    trip = road_trip()
    pickup, destination = trip["route_snapshots"]
    assert trip["trip"]["origin"]["coordinates"] == pickup["route_geojson"]["coordinates"][0]
    assert trip["trip"]["pickup"]["coordinates"] == pickup["route_geojson"]["coordinates"][-1]
    assert trip["trip"]["dropoff"]["coordinates"] == destination["route_geojson"]["coordinates"][-1]
    events = [TelemetryEventEnvelope.model_validate(e) for e in trip["ingest_events"]]
    assert [e.sequence for e in events] == list(range(1, len(events) + 1))
    assert trip["fraud_case"]["resolved_at"] is None


@pytest.mark.parametrize("mutation", ["speed", "endpoint", "missing_position", "unknown_leg"])
def test_validator_rejects_invalid_motion_or_geometry(mutation):
    trip = road_trip()
    if mutation == "speed":
        trip["ingest_events"][2]["payload"]["speed_mps"] = 45.0
    elif mutation == "endpoint":
        trip["trip"]["pickup"]["coordinates"] = [106.0, 22.0]
    elif mutation == "missing_position":
        trip["ingest_events"][2]["payload"]["position"] = None
    else:
        trip["ingest_events"][2]["leg"] = "unknown"
    assert validate_road_trip(trip)["passed"] is False


async def test_public_ingestion_accepts_both_legs_and_rejects_changed_replay(monkeypatch):
    service = CaseService(Settings(database_url=""))
    monkeypatch.setattr(service, "_get_db_connection", lambda: None)
    events = [TelemetryEventEnvelope.model_validate(e) for e in road_trip()["ingest_events"]]
    for event in events:
        assert (await service.ingest_telemetry(event)).duplicate is False
    assert (await service.ingest_telemetry(events[-1])).duplicate is True
    changed = deepcopy(events[-1])
    changed.payload.speed_mps = 45.0
    with pytest.raises(HTTPException) as error:
        await service.ingest_telemetry(changed)
    assert error.value.status_code == 409

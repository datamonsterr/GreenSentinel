from __future__ import annotations

import json
import math
from datetime import datetime

import pytest

from scripts.road_scenarios import SCENARIOS, build_scenario
from scripts.road_trip_generator import RoadTripFixture, validate_road_trip
from tests.support.repo import REPO_ROOT

FIXTURE_DIR = REPO_ROOT / "tests/fixtures/road_telemetry"


@pytest.fixture
def fixture() -> RoadTripFixture:
    return RoadTripFixture.load(FIXTURE_DIR)


def _events(manifest: dict) -> list[dict]:
    return manifest["ingest_events"]


def test_all_scenarios_return_canonical_manifest_shape(fixture: RoadTripFixture) -> None:
    for scenario in SCENARIOS:
        result = build_scenario(fixture, scenario)
        assert [
            key
            for key in ("trip", "trip_assignment", "fraud_case", "route_snapshots", "ingest_events", "manifest")
            if key in result
        ] == ["trip", "trip_assignment", "fraud_case", "route_snapshots", "ingest_events", "manifest"]
        assert result["fraud_case"]["status"] == "ready"
        assert result["fraud_case"]["resolved_at"] is None
        assert "adjudication" not in result["fraud_case"]
        assert "sanction" not in result["fraud_case"]
        assert result["manifest"]["evaluation"]["scenario"] == scenario
        assert all("scenario" not in e["payload"] and "intent" not in e["payload"] for e in _events(result))


@pytest.mark.parametrize("scenario", ["stalled", "reverse_travel", "technical_dropout"])
def test_cancelled_pickup_has_no_fabricated_destination_lifecycle(fixture: RoadTripFixture, scenario: str) -> None:
    result = build_scenario(fixture, scenario)
    assert result["trip_assignment"]["arrived_at"] is None
    assert result["trip_assignment"]["started_at"] is None
    assert result["trip_assignment"]["ended_at"] is None
    assert result["trip_assignment"]["accepted_at"] <= result["ingest_events"][0]["occurred_at"]


def test_normal_progress_has_strictly_ordered_events_and_derived_speed(fixture: RoadTripFixture) -> None:
    result = build_scenario(fixture, "normal_progress")
    events = _events(result)
    assert len(events) > 10
    assert [e["sequence"] for e in events] == list(range(len(events)))
    timestamps = [e["occurred_at"] for e in events]
    assert timestamps == sorted(timestamps)
    for previous, current in zip(events, events[1:]):
        p0, p1 = previous["payload"]["position"], current["payload"]["position"]
        dt = (
            datetime.fromisoformat(current["occurred_at"].replace("Z", "+00:00"))
            - datetime.fromisoformat(previous["occurred_at"].replace("Z", "+00:00"))
        ).total_seconds()
        assert dt > 0
        assert abs(current["payload"]["speed_mps"] - _distance(p0, p1) / dt) <= 0.05


def test_stalled_has_at_least_three_minutes_stationary_at_origin(fixture: RoadTripFixture) -> None:
    result = build_scenario(fixture, "stalled")
    events = [e for e in _events(result) if e["leg"] == "pickup"]
    origin = result["trip"]["origin"]["coordinates"]
    # Stationary receiver drift (sigma 2 m) stays inside the 15 m SSD anchor radius.
    stationary = [
        e for e in events if _distance(e["payload"]["position"], {"longitude": origin[0], "latitude": origin[1]}) < 15
    ]
    assert stationary[0]["payload"]["speed_mps"] == 0
    elapsed = (
        datetime.fromisoformat(stationary[-1]["occurred_at"].replace("Z", "+00:00"))
        - datetime.fromisoformat(stationary[0]["occurred_at"].replace("Z", "+00:00"))
    ).total_seconds()
    # Planned 230 s at 10 s cadence; measured chain keeps >= 220 s (no jitter, no gaps).
    assert elapsed >= 220


def test_traffic_gridlock_is_slow_and_provenance_is_synthetic(fixture: RoadTripFixture) -> None:
    result = build_scenario(fixture, "traffic_gridlock")
    observations = result["traffic_observations"][0]
    assert observations["is_simulated"] is True
    assert observations["source"] == "synthetic"
    assert observations["assignment_id"] == result["trip_assignment"]["id"]
    assert observations["avg_speed_mps"] > 0
    assert observations["observed_at"] < observations["valid_until"]
    assert "live" not in json.dumps(observations).lower()
    normal = build_scenario(fixture, "normal_progress")
    assert result["trip_assignment"]["ended_at"] > normal["trip_assignment"]["ended_at"]


def test_dropout_omits_over_thirty_seconds_and_records_separate_crash_incidents(fixture: RoadTripFixture) -> None:
    result = build_scenario(fixture, "technical_dropout")
    events = _events(result)
    gaps = [
        (
            datetime.fromisoformat(b["occurred_at"].replace("Z", "+00:00"))
            - datetime.fromisoformat(a["occurred_at"].replace("Z", "+00:00"))
        ).total_seconds()
        for a, b in zip(events, events[1:])
    ]
    assert max(gaps) > 30
    incidents = result["platform_incidents"]
    assert len(incidents) >= 2
    assert all(i["incident_type"] == "app_crash" and i["state"] == "observed" for i in incidents)
    assert all(i["started_at"] < i["ended_at"] and i["source"] == "synthetic" for i in incidents)


@pytest.mark.parametrize("scenario", ["stalled", "technical_dropout"])
def test_incomplete_scenarios_cancel_without_destination_or_invented_arrival(
    fixture: RoadTripFixture, scenario: str
) -> None:
    result = build_scenario(fixture, scenario)
    assert all(event["leg"] == "pickup" for event in result["ingest_events"])
    assert result["trip"]["status"] == "cancelled"
    assert result["trip"]["completed_at"] is None
    assert result["trip"]["cancelled_at"] == result["ingest_events"][-1]["occurred_at"]
    assert result["trip_assignment"]["state"] == "cancelled"
    assert result["trip_assignment"]["ended_at"] is None
    assert result["trip_assignment"]["cancelled_at"] == result["ingest_events"][-1]["occurred_at"]
    assert result["fraud_case"]["status"] == "ready"


def test_operational_arrays_are_top_level_and_times_match_last_event(fixture: RoadTripFixture) -> None:
    for scenario in ("normal_progress", "traffic_gridlock"):
        result = build_scenario(fixture, scenario)
        assert result["trip"]["completed_at"] == result["ingest_events"][-1]["occurred_at"]
        assert result["trip_assignment"]["ended_at"] == result["ingest_events"][-1]["occurred_at"]
    assert "traffic_observations" not in build_scenario(fixture, "normal_progress")["manifest"]["evaluation"]
    assert "platform_incidents" not in build_scenario(fixture, "technical_dropout")["manifest"]["evaluation"]


def test_reverse_uses_captured_directed_away_route_without_reversing_polyline(fixture: RoadTripFixture) -> None:
    result = build_scenario(fixture, "reverse_travel")
    actual = result["manifest"]["actual_routes"]["actual_route"]
    assert actual["geometry"]["type"] == "LineString"
    assert actual["geometry"]["coordinates"][0] == result["trip"]["origin"]["coordinates"]
    assert actual["provenance"]["provider"] == "osrm"
    assert actual["provenance"]["captured_at_utc"]
    assert actual["provenance"]["url_checksum"]
    assert len(result["route_snapshots"]) == 2
    pickup_events = [e for e in result["ingest_events"] if e["leg"] == "pickup"]
    assert all(
        pickup_events[i]["payload"]["position"] != pickup_events[i + 1]["payload"]["position"]
        for i in range(len(pickup_events) - 1)
    )
    assert [e["occurred_at"] for e in result["ingest_events"]] == sorted(
        e["occurred_at"] for e in result["ingest_events"]
    )
    assert result["trip"]["cancelled_at"] == result["ingest_events"][-1]["occurred_at"]
    assert all(event["leg"] == "pickup" for event in result["ingest_events"])
    assert result["trip"]["status"] == "cancelled"


@pytest.mark.parametrize("scenario", ["stalled", "technical_dropout"])
def test_transformed_boundary_observations_match_derived_speed(fixture: RoadTripFixture, scenario: str) -> None:
    result = build_scenario(fixture, scenario)
    failures = validate_road_trip(result)["failures"]
    assert not any("speed disagrees" in failure for failure in failures)


def test_unknown_scenario_fails_explicitly(fixture: RoadTripFixture) -> None:
    with pytest.raises(ValueError, match="Unsupported scenario"):
        build_scenario(fixture, "invented")


def _distance(a: dict, b: dict) -> float:
    earth_r = 6_371_000.0
    p1, p2 = math.radians(a["latitude"]), math.radians(b["latitude"])
    dp = p2 - p1
    dl = math.radians(b["longitude"] - a["longitude"])
    x = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return earth_r * 2 * math.atan2(math.sqrt(x), math.sqrt(1 - x))

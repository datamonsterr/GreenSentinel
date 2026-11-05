"""Deterministic T3/T4 road telemetry scenarios built on the T1 contract."""

from __future__ import annotations

import hashlib
import json
import math
import random
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from scripts.road_trip_generator import (
    BASE_TIME,
    RoadTripFixture,
    RoadTripManifest,
    _haversine_m,
    _stable_uuid,
    _utc_z,
    sample_route_points,
)

SCENARIOS = ("normal_progress", "stalled", "reverse_travel", "traffic_gridlock", "technical_dropout")
_AWAY_FILE = Path(__file__).parents[1] / "tests" / "fixtures" / "road_telemetry" / "osrm_route_actual_away.json"
_AWAY_PROVENANCE = Path(__file__).parents[1] / "tests" / "fixtures" / "road_telemetry" / "PROVENANCE_actual_away.json"


def build_scenario(fixture: RoadTripFixture, scenario: str, seed: int = 42) -> dict[str, Any]:
    if scenario not in SCENARIOS:
        raise ValueError(f"Unsupported scenario: {scenario}")
    result = RoadTripManifest.build(fixture, seed=seed).to_dict()
    result = {
        key: result[key]
        for key in ("trip", "trip_assignment", "fraud_case", "route_snapshots", "ingest_events", "manifest")
    }
    for index, event in enumerate(result["ingest_events"]):
        event["sequence"] = index
        event["producer_sequence"] = index
    result["manifest"]["evaluation"] = {"scenario": scenario, "intent": scenario}
    if scenario == "stalled":
        _stall(result, seed)
    elif scenario == "traffic_gridlock":
        _scale_time(result, 1.8)
        events = result["ingest_events"]
        result["traffic_observations"] = [
            {
                "assignment_id": result["trip_assignment"]["id"],
                "source": "synthetic",
                "is_simulated": True,
                "provenance": "deterministic scenario transform; synthetic source only",
                "avg_speed_mps": round(sum(e["payload"]["speed_mps"] for e in events) / len(events), 3),
                "observed_at": events[0]["occurred_at"],
                "valid_until": events[-1]["occurred_at"],
                "congestion_level": "heavy",
            }
        ]
    elif scenario == "technical_dropout":
        _dropout(result)
    elif scenario == "reverse_travel":
        _reverse(result, seed)
    return result


def _recompute_speeds(events: list[dict[str, Any]]) -> None:
    for index, event in enumerate(events):
        if index == 0:
            event["payload"]["speed_mps"] = 0.0
            continue
        previous = events[index - 1]
        dt = (
            datetime.fromisoformat(event["occurred_at"].replace("Z", "+00:00"))
            - datetime.fromisoformat(previous["occurred_at"].replace("Z", "+00:00"))
        ).total_seconds()
        a, b = previous["payload"]["position"], event["payload"]["position"]
        event["payload"]["speed_mps"] = round(
            _haversine_m(a["longitude"], a["latitude"], b["longitude"], b["latitude"]) / dt, 3
        )


def _scale_time(result: dict[str, Any], factor: float) -> None:
    result["manifest"]["cadence"]["cadence_s"] *= factor
    result["manifest"]["cadence"]["max_interval_s"] *= factor
    events = result["ingest_events"]
    for event in events:
        old = datetime.fromisoformat(event["occurred_at"].replace("Z", "+00:00"))
        seconds = (old - BASE_TIME).total_seconds() * factor
        event["occurred_at"] = _utc_z(BASE_TIME + timedelta(seconds=seconds))
        event["received_at"] = _utc_z(BASE_TIME + timedelta(seconds=seconds, milliseconds=200))
    _recompute_speeds(events)
    for key in ("accepted_at", "arrived_at", "started_at", "ended_at"):
        old = datetime.fromisoformat(result["trip_assignment"][key].replace("Z", "+00:00"))
        result["trip_assignment"][key] = _utc_z(
            BASE_TIME + timedelta(seconds=(old - BASE_TIME).total_seconds() * factor)
        )
    result["trip"]["completed_at"] = result["trip_assignment"]["ended_at"]


def _stall(result: dict[str, Any], seed: int) -> None:
    events = [event for event in result["ingest_events"] if event["leg"] == "pickup"]
    origin = result["trip"]["origin"]["coordinates"]
    first = events[0]
    stall_shift_s = 240
    for event in events:
        old = datetime.fromisoformat(event["occurred_at"].replace("Z", "+00:00"))
        event["occurred_at"] = _utc_z(old + timedelta(seconds=stall_shift_s))
        received = datetime.fromisoformat(event["received_at"].replace("Z", "+00:00"))
        event["received_at"] = _utc_z(received + timedelta(seconds=stall_shift_s))
    rng = random.Random(f"road-stall:{seed}")
    lat_scale = 111_320.0
    lon_scale = 111_320.0 * math.cos(math.radians(origin[1]))
    extra = []
    for index in range(1, 25):
        event = json.loads(json.dumps(first))
        event["event_id"] = _stable_uuid(f"greensentinel:road-t3:seed{seed}", f"stall:{index}")
        event["sequence"] = index
        event["producer_sequence"] = index
        event["occurred_at"] = _utc_z(BASE_TIME + timedelta(seconds=(index - 1) * 10))
        event["received_at"] = _utc_z(BASE_TIME + timedelta(seconds=(index - 1) * 10, milliseconds=200))
        dx_m, dy_m = rng.gauss(0.0, 2.0), rng.gauss(0.0, 2.0)
        event["payload"]["position"] = {
            "longitude": origin[0] + dx_m / lon_scale,
            "latitude": origin[1] + dy_m / lat_scale,
            "accuracy_m": round(rng.uniform(6.0, 15.0), 1),
        }
        event["payload"]["speed_mps"] = 0.0
        extra.append(event)
    result["ingest_events"] = extra + events
    for index, event in enumerate(result["ingest_events"]):
        event["sequence"] = index
        event["producer_sequence"] = index
    result["manifest"]["evaluation"]["stall_duration_s"] = 230
    _recompute_speeds(result["ingest_events"])
    _cancel_incomplete(result)


def _dropout(result: dict[str, Any]) -> None:
    events = [event for event in result["ingest_events"] if event["leg"] == "pickup"]
    keep = [event for index, event in enumerate(events) if not 5 <= index <= 9]
    for index, event in enumerate(keep):
        event["sequence"] = index
        event["producer_sequence"] = index
    result["ingest_events"] = keep
    result["manifest"]["cadence"]["intentional_gaps"] = [
        {
            "after_sequence": keep[4]["sequence"],
            "before_sequence": keep[5]["sequence"],
            "interval_s": (
                datetime.fromisoformat(keep[5]["occurred_at"].replace("Z", "+00:00"))
                - datetime.fromisoformat(keep[4]["occurred_at"].replace("Z", "+00:00"))
            ).total_seconds(),
            "source": "synthetic-app-dropout",
        }
    ]
    _recompute_speeds(result["ingest_events"])
    result["platform_incidents"] = [
        {
            "incident_type": "app_crash",
            "state": "observed",
            "started_at": events[5]["occurred_at"],
            "ended_at": events[6]["occurred_at"],
            "source_event_id": events[5]["event_id"],
            "details": "synthetic app lifecycle crash",
            "source": "synthetic",
        },
        {
            "incident_type": "app_crash",
            "state": "observed",
            "started_at": events[9]["occurred_at"],
            "ended_at": events[10]["occurred_at"],
            "source_event_id": events[9]["event_id"],
            "details": "synthetic app lifecycle restart",
            "source": "synthetic",
        },
    ]
    _cancel_incomplete(result)


def _cancel_incomplete(result: dict[str, Any]) -> None:
    last_at = result["ingest_events"][-1]["occurred_at"]
    result["trip"].update({"status": "cancelled", "completed_at": None, "cancelled_at": last_at})
    result["trip_assignment"].update(
        {
            "state": "cancelled",
            "accepted_at": result["trip_assignment"]["offered_at"],
            "arrived_at": None,
            "started_at": None,
            "ended_at": None,
            "cancelled_at": last_at,
        }
    )


def _reverse(result: dict[str, Any], seed: int) -> None:
    if not _AWAY_FILE.exists() or not _AWAY_PROVENANCE.exists():
        raise FileNotFoundError("Captured away-route fixture or provenance is missing")
    with _AWAY_FILE.open(encoding="utf-8") as stream:
        route = json.load(stream)["routes"][0]
    with _AWAY_PROVENANCE.open(encoding="utf-8") as stream:
        provenance = json.load(stream)
    actual = {
        "geometry": route["geometry"],
        "distance_m": route["distance"],
        "duration_s": route["duration"],
        "provenance": {**provenance, "url_checksum": hashlib.sha256(provenance["query_url"].encode()).hexdigest()},
    }
    result["manifest"]["actual_routes"] = {"actual_route": actual}
    result["manifest"]["evaluation"]["validation_route"] = "manifest.actual_routes.actual_route"
    coords = route["geometry"]["coordinates"]
    result["ingest_events"] = [e for e in result["ingest_events"] if e["leg"] == "pickup"]
    points = sample_route_points(coords, len(result["ingest_events"]), seed, 0, route["duration"])
    pickup_events = result["ingest_events"]
    for event, point in zip(pickup_events, points):
        event["payload"]["position"] = {
            "longitude": point["longitude"],
            "latitude": point["latitude"],
            "accuracy_m": 8.0,
        }
    _recompute_speeds(result["ingest_events"])
    for index, event in enumerate(result["ingest_events"]):
        event["sequence"] = index
        event["producer_sequence"] = index
    _cancel_incomplete(result)

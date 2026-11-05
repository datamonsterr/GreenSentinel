"""Adapt the shared road scenarios to the existing relational seed and API contracts."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from scripts.road_trip_generator import BASE_TIME, RoadTripFixture, RoadTripManifest, validate_road_trip
from src.models.schemas import TelemetryEventEnvelope

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests/fixtures/road_telemetry"
DATASET_VERSION = "road-v1"


def stable_id(name: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"greensentinel:{DATASET_VERSION}:{name}"))


def timestamp(value: str, offset: timedelta) -> str:
    return (datetime.fromisoformat(value.replace("Z", "+00:00")) + offset).isoformat().replace("+00:00", "Z")


def wkt(geometry: dict[str, Any]) -> str:
    coords = geometry["coordinates"]
    if geometry["type"] == "Point":
        return f"POINT({coords[0]} {coords[1]})"
    return "LINESTRING(" + ",".join(f"{lon} {lat}" for lon, lat in coords) + ")"


def hash_payload(payload: Any) -> str:
    return "\\x" + hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def apply_road_dataset(data: dict[str, Any]) -> dict[str, Any]:
    """Keep seed identities and historical records; replace synthetic motion with routed samples."""
    from scripts.road_scenarios import build_scenario

    fixture = RoadTripFixture.load(FIXTURES)
    assignments = {a["id"]: a for a in data["trip_assignments"]}
    trips = {t["id"]: t for t in data["trips"]}
    labels = {label["assignment_id"]: label for label in data["simulation_labels"]}
    runs: dict[str, dict[str, Any]] = {}
    road_cases = []
    events: list[dict[str, Any]] = []
    telemetry: list[dict[str, Any]] = []
    routes: list[dict[str, Any]] = []
    traffic: list[dict[str, Any]] = []
    incidents: list[dict[str, Any]] = []
    case_ordinals = {case_id: index for index, case_id in enumerate(sorted(case["id"] for case in data["fraud_cases"]))}
    for case in data["fraud_cases"]:
        i = case_ordinals[case["id"]]
        assignment = assignments[case["assignment_id"]]
        trip = trips[assignment["trip_id"]]
        legacy = labels[assignment["id"]]
        old_run = next(r for r in data["simulation_runs"] if r["id"] == legacy["simulation_run_id"])
        scenario = {
            "intentional_dic": "stalled" if i % 2 == 0 else "reverse_travel",
            "traffic_gridlock": "traffic_gridlock",
            "technical_dropout": "technical_dropout",
        }.get(old_run["scenario"], "normal_progress")
        canonical = build_scenario(fixture, scenario, seed=42 + i)
        offset = datetime.fromisoformat(trip["requested_at"]) - BASE_TIME
        run_id = old_run["id"]
        runs.setdefault(
            old_run["scenario"],
            {
                "id": run_id,
                "organization_id": data["organization"]["id"],
                "scenario": old_run["scenario"],
                "seed": 42,
                "generator_version": DATASET_VERSION,
                "status": "completed",
                "simulated_clock_origin": BASE_TIME.isoformat(),
                "started_at": BASE_TIME.isoformat(),
                "finished_at": (BASE_TIME + timedelta(days=2)).isoformat(),
                "requested_by": data["analysts"][0]["id"],
                "created_at": BASE_TIME.isoformat(),
            },
        )
        canonical["trip"].update({"id": trip["id"], "passenger_id": trip["passenger_id"]})
        canonical["trip_assignment"].update(
            {
                "id": assignment["id"],
                "trip_id": trip["id"],
                "driver_id": assignment["driver_id"],
                "vehicle_id": assignment["vehicle_id"],
            }
        )
        canonical["fraud_case"].update({"id": case["id"], "assignment_id": assignment["id"]})
        for row in (canonical["trip"], canonical["trip_assignment"], canonical["fraud_case"]):
            for key, value in list(row.items()):
                if key.endswith("_at") and value:
                    row[key] = timestamp(value, offset)
        for row in canonical["ingest_events"]:
            row.update(
                {
                    "event_id": stable_id(f"{assignment['id']}:event:{row['sequence']}"),
                    "trip_id": trip["id"],
                    "assignment_id": assignment["id"],
                    "driver_id": assignment["driver_id"],
                    "simulation_run_id": run_id,
                    "source": "road-simulator",
                    "correlation_id": stable_id(assignment["id"]),
                }
            )
            row["occurred_at"] = timestamp(row["occurred_at"], offset)
            row["received_at"] = timestamp(row["received_at"], offset)
            if old_run["scenario"] == "fake_gps":
                row["payload"].update({"gps_state": "mock_reported", "mock_location_reported": True})
            row["payload"] = TelemetryEventEnvelope.model_validate(row).payload.model_dump(mode="json")
            row["payload_hash"] = hash_payload(row["payload"])
            row["producer_sequence"] = row["sequence"]
            events.append(row)
            pos = row["payload"]["position"]
            telemetry.append(
                {
                    "event_id": row["event_id"],
                    "assignment_id": assignment["id"],
                    "occurred_at": row["occurred_at"],
                    "position": wkt({"type": "Point", "coordinates": [pos["longitude"], pos["latitude"]]})
                    if pos
                    else None,
                    "accuracy_m": pos["accuracy_m"] if pos else None,
                    **{
                        k: row["payload"][k]
                        for k in (
                            "speed_mps",
                            "bearing_deg",
                            "app_state",
                            "network_state",
                            "gps_state",
                            "mock_location_reported",
                        )
                    },
                }
            )
        for snapshot in canonical["route_snapshots"]:
            snapshot.update(
                {"id": stable_id(f"{assignment['id']}:route:{snapshot['leg']}"), "assignment_id": assignment["id"]}
            )
            snapshot["calculated_at"] = timestamp(snapshot["calculated_at"], offset)
            snapshot["provenance"].update(
                {
                    "dataset_version": DATASET_VERSION,
                    "origin": "osrm",
                    "status": "ok",
                    "is_shortest_path": False,
                    "generator_seed": canonical["manifest"]["seed"],
                }
            )
            routes.append({**snapshot, "route": wkt(snapshot["route_geojson"])})
        for name, target in (("traffic_observations", traffic), ("platform_incidents", incidents)):
            for j, source_row in enumerate(canonical.get(name, [])):
                row = dict(source_row)
                row.update({"id": stable_id(f"{assignment['id']}:{name}:{j}"), "assignment_id": assignment["id"]})
                for key in ("observed_at", "valid_until", "started_at", "ended_at"):
                    if row.get(key):
                        row[key] = timestamp(row[key], offset)
                if name == "traffic_observations":
                    row.update({"is_simulated": True, "source": "synthetic-road-simulator"})
                    row["average_speed_mps"] = row.pop("avg_speed_mps", row.get("average_speed_mps"))
                    if row["congestion_level"] == "gridlock":
                        row["congestion_level"] = "heavy"
                    provenance = row.get("provenance")
                    row["provenance"] = {
                        **(provenance if isinstance(provenance, dict) else {"method": provenance}),
                        "dataset_version": DATASET_VERSION,
                        "is_simulated": True,
                    }
                else:
                    row["source_event_id"] = None
                    row["details"] = {
                        "method": row.get("details"),
                        "source": "synthetic",
                        "dataset_version": DATASET_VERSION,
                    }
                target.append(row)
        for key in ("requested_at", "created_at", "completed_at", "cancelled_at", "status"):
            if key in canonical["trip"]:
                trip[key] = canonical["trip"][key]
        trip.update(
            {
                "pickup": wkt(canonical["trip"]["pickup"]),
                "dropoff": wkt(canonical["trip"]["dropoff"]),
                "pickup_address": "Keangnam Hanoi (synthetic trip)",
                "dropoff_address": "Noi Bai (synthetic trip)",
                "district": "Cau Giay",
            }
        )
        assignment.update(
            {
                k: v
                for k, v in canonical["trip_assignment"].items()
                if k not in {"id", "trip_id", "driver_id", "vehicle_id"}
            }
        )
        legacy["simulation_run_id"] = run_id
        canonical["manifest"]["evaluation"] = {
            "scenario": scenario,
            "expected_category": legacy["expected_category"],
            "expected_guardrail": legacy["expected_guardrail"],
        }
        road_cases.append(canonical)
    data.update(
        {
            "manifest": {
                "dataset_version": DATASET_VERSION,
                "seed_version": DATASET_VERSION,
                "seed": 42,
                "seed_derivation": "base seed 42 plus zero-based ordinal of the sorted fraud-case UUIDs",
                "generator_version": DATASET_VERSION,
                "clock_origin": BASE_TIME.isoformat(),
                "units": road_cases[0]["manifest"]["units"],
                "route_checksums": road_cases[0]["manifest"]["route_checksums"],
                "source": "synthetic",
            },
            "road_cases": road_cases,
            "ingest_events": events,
            "telemetry_points": telemetry,
            "route_snapshots": routes,
            "traffic_observations": traffic,
            "platform_incidents": incidents,
            "simulation_runs": list(runs.values()),
        }
    )
    for snapshot in data["evidence_snapshots"]:
        snapshot["dossier"].pop("scenario", None)
        snapshot["dossier_hash"] = hash_payload(snapshot["dossier"])
    return data


def validate_dataset(data: dict[str, Any]) -> dict[str, Any]:
    failures = {}
    for case in data["road_cases"]:
        result = validate_road_trip(case)
        if not result["passed"]:
            failures[case["fraud_case"]["id"]] = result["failures"]
    covered = {c["trip_assignment"]["id"] for c in data["road_cases"]}
    expected_pairs = {(case["id"], case["assignment_id"]) for case in data["fraud_cases"]}
    actual_pairs = {(case["fraud_case"]["id"], case["trip_assignment"]["id"]) for case in data["road_cases"]}
    if actual_pairs != expected_pairs or len(data["road_cases"]) != len(expected_pairs):
        failures["coverage"] = ["road cases must cover active fraud cases exactly once"]
    for case in data["fraud_cases"]:
        if case["assignment_id"] not in covered:
            failures[case["id"]] = ["missing road fixture"]
    assignments = {row["id"]: row for row in data["trip_assignments"]}
    case_ids = {row["assignment_id"]: row["id"] for row in data["fraud_cases"]}
    flat_events = {row["event_id"]: row for row in data["ingest_events"]}
    for event in data["ingest_events"]:
        assignment = assignments.get(event["assignment_id"])
        if not assignment or event["trip_id"] != assignment["trip_id"] or event["driver_id"] != assignment["driver_id"]:
            key = case_ids.get(event["assignment_id"], event["assignment_id"])
            failures.setdefault(key, []).append("flat ingest event relationships do not match assignment")
    for point in data["telemetry_points"]:
        event = flat_events.get(point["event_id"])
        if not event or any(point[field] != event[field] for field in ("assignment_id", "occurred_at")):
            key = case_ids.get(point["assignment_id"], point["assignment_id"])
            failures.setdefault(key, []).append("flat telemetry does not match source event")
    route_counts: dict[str, list[str]] = {}
    for route in data["route_snapshots"]:
        assignment_id = route["assignment_id"]
        route_counts.setdefault(assignment_id, []).append(route["leg"])
        if assignment_id not in assignments:
            failures.setdefault(assignment_id, []).append("flat route references unknown assignment")
    for assignment_id, case_id in case_ids.items():
        if sorted(route_counts.get(assignment_id, [])) != ["destination", "pickup"]:
            failures.setdefault(case_id, []).append("flat routes must have exactly one pickup and destination leg")
    for observation in data["traffic_observations"]:
        key = case_ids.get(observation["assignment_id"], observation["assignment_id"])
        if observation["assignment_id"] not in assignments:
            failures.setdefault(key, []).append("traffic references unknown assignment")
        try:
            start = datetime.fromisoformat(observation["observed_at"].replace("Z", "+00:00"))
            end = datetime.fromisoformat(observation["valid_until"].replace("Z", "+00:00"))
            valid = start.tzinfo is not None and end.tzinfo is not None and start <= end
        except (ValueError, TypeError, AttributeError):
            valid = False
        if not valid:
            failures.setdefault(key, []).append("traffic has an invalid validity interval")
        if not observation.get("is_simulated") or observation.get("source") != "synthetic-road-simulator":
            failures.setdefault(key, []).append("traffic must remain explicitly synthetic")
    return {
        "passed": not failures,
        "cases": len(data["road_cases"]),
        "failures": failures,
        "dataset_version": DATASET_VERSION,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "data/synthetic/seed_data.json")
    parser.add_argument("--validate", action="store_true")
    parser.add_argument("--shared-fixture", type=Path)
    args = parser.parse_args()
    from scripts.generate_synthetic_data import generate_synthetic_dataset

    data = generate_synthetic_dataset()
    if args.validate:
        result = validate_dataset(data)
        print(json.dumps(result, indent=2))
        if not result["passed"]:
            raise SystemExit(1)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(data, ensure_ascii=False))
    if args.shared_fixture:
        # The normal fixture is shared across API/GIS tests, independently of the larger seed.
        args.shared_fixture.write_text(
            json.dumps(RoadTripManifest.build(RoadTripFixture.load(FIXTURES)).to_dict(), separators=(",", ":"))
        )


if __name__ == "__main__":
    main()

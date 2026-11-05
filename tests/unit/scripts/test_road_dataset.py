import json
from collections import Counter

from scripts.generate_synthetic_data import generate_synthetic_dataset
from scripts.road_dataset import apply_road_dataset, validate_dataset
from src.models.schemas import TelemetryEventEnvelope


def test_every_demo_assignment_has_source_backed_geometry_and_valid_motion():
    data = generate_synthetic_dataset()
    assert data == generate_synthetic_dataset()
    assert data["manifest"]["dataset_version"] == "road-v1"
    assert len(data["fraud_cases"]) == 100
    assert set(Counter(r["assignment_id"] for r in data["route_snapshots"]).values()) == {2}
    assert all(r["provider"] == "osrm" for r in data["route_snapshots"])
    assert {c["manifest"]["evaluation"]["scenario"] for c in data["road_cases"]} >= {
        "normal_progress",
        "stalled",
        "reverse_travel",
        "traffic_gridlock",
        "technical_dropout",
    }
    assert validate_dataset(data)["passed"]
    for event in data["ingest_events"]:
        TelemetryEventEnvelope.model_validate(event)
        assert not {"scenario", "intent", "expected_category"}.intersection(event["payload"])


def test_seed_has_available_err01_case_with_route_and_timestamped_gps():
    data = generate_synthetic_dataset()
    assignments = {row["id"]: row for row in data["trip_assignments"]}
    routes_by_assignment = {row["assignment_id"] for row in data["route_snapshots"] if row.get("route")}
    telemetry_by_assignment = {
        row["assignment_id"] for row in data["telemetry_points"] if row.get("occurred_at") and row.get("position")
    }

    candidates = [
        case
        for case in data["fraud_cases"]
        if case["suspected_category"] == "ERR-01"
        and case["status"] not in {"resolved", "dismissed", "suspended", "auto_dismissed"}
        and case["assignment_id"] in assignments
        and case["assignment_id"] in routes_by_assignment
        and case["assignment_id"] in telemetry_by_assignment
    ]

    assert candidates, "preview seed must contain a claimable ERR-01 case with route/GPS evidence"


def test_validation_fails_with_case_attribution_for_corrupted_seed():
    data = generate_synthetic_dataset()
    data["road_cases"][0]["ingest_events"][2]["payload"]["speed_mps"] = 49.0
    result = validate_dataset(data)
    assert not result["passed"]
    assert data["road_cases"][0]["fraud_case"]["id"] in json.dumps(result["failures"])


def test_validation_rejects_foreign_flat_telemetry_and_route_links():
    data = generate_synthetic_dataset()
    data["telemetry_points"][0]["assignment_id"] = data["trip_assignments"][1]["id"]
    data["route_snapshots"][0]["assignment_id"] = "foreign-assignment"
    result = validate_dataset(data)
    assert not result["passed"]
    assert "telemetry" in json.dumps(result["failures"])
    assert "route" in json.dumps(result["failures"])


def test_validation_rejects_duplicate_coverage_and_invalid_traffic():
    data = generate_synthetic_dataset()
    data["road_cases"].append(data["road_cases"][0])
    traffic = data["traffic_observations"][0]
    traffic.update(assignment_id="foreign-assignment", valid_until="invalid")
    result = validate_dataset(data)
    assert not result["passed"]
    assert "coverage" in json.dumps(result["failures"])
    assert "traffic" in json.dumps(result["failures"])


def test_case_motion_and_seed_are_stable_when_input_cases_are_reordered():
    data = generate_synthetic_dataset()
    first = {case["fraud_case"]["id"]: case for case in data["road_cases"]}
    data["fraud_cases"].reverse()
    second = apply_road_dataset(data)
    assert {case["fraud_case"]["id"]: case for case in second["road_cases"]} == first
    assert "seed_derivation" in second["manifest"]
    for case in second["road_cases"]:
        assert all(
            route["provenance"]["generator_seed"] == case["manifest"]["seed"] for route in case["route_snapshots"]
        )

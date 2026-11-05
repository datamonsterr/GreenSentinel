"""Unit tests for the synthesized_vietnam_trip generator."""

import json
import tempfile
from pathlib import Path

import pytest

from scripts.benchmark.synthesize_vietnam import (
    DEFAULT_SEED,
    generate_vietnam_dataset,
    point_to_polyline_min_distance_m,
)


@pytest.fixture(scope="module")
def generated_dataset():
    with tempfile.TemporaryDirectory() as tmpdir:
        out_dir = Path(tmpdir) / "synthesized_vietnam_trip"
        dest, sha, manifest = generate_vietnam_dataset(out_dir, seed=DEFAULT_SEED)
        yield dest, sha, manifest


def test_generator_file_structure(generated_dataset):
    dest, sha, manifest = generated_dataset
    assert (dest / "trips.jsonl").exists()
    assert (dest / "labels.csv").exists()
    assert (dest / "manifest.json").exists()
    assert (dest / "checksums.json").exists()
    assert (dest / "sample_100.jsonl").exists()
    assert (dest / "sample_100.parquet").exists()


def test_generator_counts_and_severities(generated_dataset):
    dest, sha, manifest = generated_dataset
    assert manifest["total_trips"] == 1000

    # Exact class counts
    assert manifest["class_counts"]["no_violation"] == 700
    assert manifest["class_counts"]["ERR-05"] == 30
    assert manifest["class_counts"]["ERR-02"] == 70
    assert manifest["class_counts"]["ERR-03"] == 65
    assert manifest["class_counts"]["ERR-01"] == 75
    assert manifest["class_counts"]["ERR-04"] == 60
    assert (
        "insufficient_evidence" not in manifest["class_counts"]
        or manifest["class_counts"].get("insufficient_evidence") == 0
    )

    # Severity counts: 30 P0, 135 P1, 135 P2 (270 P1/P2 = 90% and 30 P0 = 10% of 300 violations)
    assert manifest["severity_counts"]["P0"] == 30
    assert manifest["severity_counts"]["P1"] == 135
    assert manifest["severity_counts"]["P2"] == 135
    assert manifest["severity_counts"]["no_violation"] == 700


def test_generator_driver_split_disjoint(generated_dataset):
    dest, sha, manifest = generated_dataset
    assert manifest["splits"]["train"] == 800
    assert manifest["splits"]["test"] == 200
    assert manifest["drivers"]["leakage"] == 0


def test_generator_telemetry_validity_and_geography(generated_dataset):
    dest, sha, manifest = generated_dataset
    trips_path = dest / "trips.jsonl"
    with trips_path.open("r", encoding="utf-8") as f:
        for _idx, line in enumerate(f):
            t = json.loads(line)
            # Geography bounds (Vietnam)
            assert 8.0 <= t["pickup"]["lat"] <= 24.0
            assert 102.0 <= t["pickup"]["lon"] <= 110.0
            assert 8.0 <= t["dropoff"]["lat"] <= 24.0
            assert 102.0 <= t["dropoff"]["lon"] <= 110.0

            # Finite and nonzero distance
            assert t["route"]["distance_m"] > 0
            assert len(t["telemetry"]) > 0
            for pt in t["telemetry"]:
                assert pt["latitude"] is not None
                assert pt["longitude"] is not None

            # Organization portability (no hardcoded tenant leakage)
            assert t["driver_profile"].get("organization_id") is None


def test_generator_road_geometry_residuals(generated_dataset):
    """Verify normal telemetry is strictly constrained to cached road geometry (cross-track <= 15m),
    while intentional anomalies (route deviation, fake GPS) depart intentionally.
    """
    dest, _, _ = generated_dataset
    trips_path = dest / "trips.jsonl"
    with trips_path.open("r", encoding="utf-8") as f:
        for line in f:
            t = json.loads(line)
            road_coords = t["planned_route"]["geometry"]["coordinates"]
            label = t["label"]
            residuals = [
                point_to_polyline_min_distance_m(pt["longitude"], pt["latitude"], road_coords) for pt in t["telemetry"]
            ]
            max_res = max(residuals) if residuals else 0.0

            if label == "no_violation":
                # Strict adherence to cached road segment
                assert max_res <= 15.0, (
                    f"Normal trip {t['trip_ref']} departed from road: max cross-track {max_res}m > 15m"
                )
            elif label == "ERR-03":
                # Intentional route deviation must depart from the road
                assert max_res >= 50.0, (
                    f"Route deviation trip {t['trip_ref']} failed to depart road: max cross-track {max_res}m < 50m"
                )
                assert t["generation_audit"]["departure_mode"] == "intentional_detour"
            elif label == "ERR-05":
                # Intentional GPS teleportation / spoofing
                assert max_res >= 100.0, (
                    f"Fake GPS trip {t['trip_ref']} failed to depart road: max cross-track {max_res}m < 100m"
                )
                assert t["generation_audit"]["departure_mode"] == "gps_teleportation_spoof"


def test_generator_determinism():
    """Verify two runs with the same seed yield identical trips_sha256."""
    with tempfile.TemporaryDirectory() as tmpdir:
        out1 = Path(tmpdir) / "run1"
        out2 = Path(tmpdir) / "run2"
        _, sha1, _ = generate_vietnam_dataset(out1, seed=42)
        _, sha2, _ = generate_vietnam_dataset(out2, seed=42)
        assert sha1 == sha2, "Rerun determinism failed: different SHA-256 for identical seed"

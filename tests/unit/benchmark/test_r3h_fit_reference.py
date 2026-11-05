"""Unit tests for exp(R3H) reference distribution fitting (Issue #551 / #494)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.benchmark.experiments.r3h.fit_reference import (
    compute_measurement_quantiles,
    fit_reference_distributions,
)


@pytest.fixture
def sample_train_trips() -> list[dict]:
    """Small synthetic in-memory corpus with train and validation splits."""
    trips = []
    # 10 train no_violation trips with varying progress ratios and detour ratios
    for i in range(10):
        trips.append(
            {
                "trip_id": f"train_nv_{i}",
                "split": "train",
                "label": "no_violation",
                "pickup": [105.8500, 21.0200],
                "dropoff": [105.8600, 21.0300],
                "planned_route": {"distance_m": 1000.0, "is_estimated": False},
                "telemetry": [
                    {
                        "occurred_at": 1000,
                        "longitude": 105.8500,
                        "latitude": 21.0200 + 0.001 * (10 - i),
                        "speed_mps": 5.0,
                    },
                    {"occurred_at": 1060, "longitude": 105.8500, "latitude": 21.0200, "speed_mps": 0.0},
                ],
            }
        )
    # 5 train ERR-03 trips with detours / low progress
    for i in range(5):
        trips.append(
            {
                "trip_id": f"train_err03_{i}",
                "split": "train",
                "label": "ERR-03",
                "pickup": [105.8500, 21.0200],
                "dropoff": [105.8600, 21.0300],
                "planned_route": {"distance_m": 1000.0, "is_estimated": False},
                "telemetry": [
                    {"occurred_at": 1000, "longitude": 105.8500, "latitude": 21.0100, "speed_mps": 5.0},
                    {"occurred_at": 1060, "longitude": 105.8700, "latitude": 21.0100, "speed_mps": 5.0},
                ],
            }
        )
    # 3 validation trips (must be ignored by fit_reference_distributions)
    for i in range(3):
        trips.append(
            {
                "trip_id": f"val_nv_{i}",
                "split": "validation",
                "label": "no_violation",
                "pickup": [105.8500, 21.0200],
                "dropoff": [105.8600, 21.0300],
                "telemetry": [
                    {"occurred_at": 1000, "longitude": 105.8500, "latitude": 21.0200, "speed_mps": 0.0},
                ],
            }
        )
    return trips


def test_compute_measurement_quantiles() -> None:
    """Ensure quantiles match p01, p05, p10, p25, p50, p75, p90, p95, p99."""
    values = list(range(1, 101))  # 1 to 100
    q = compute_measurement_quantiles(values)
    expected_keys = ["p01", "p05", "p10", "p25", "p50", "p75", "p90", "p95", "p99"]
    for k in expected_keys:
        assert k in q, f"Missing quantile key {k}"

    assert q["p50"] == pytest.approx(50.5, abs=1.0)
    assert q["p10"] < q["p25"] < q["p50"] < q["p75"] < q["p90"]


def test_fit_reference_distributions_train_only(tmp_path: Path, sample_train_trips: list[dict]) -> None:
    """Verify that fit_reference_distributions processes only train split and filters no_violation for quantiles."""
    input_file = tmp_path / "trips.jsonl"
    with open(input_file, "w", encoding="utf-8") as f:
        for t in sample_train_trips:
            f.write(json.dumps(t) + "\n")

    out_file = tmp_path / "jev_reference_quantiles.json"
    result = fit_reference_distributions(
        in_path=input_file,
        out_path=out_file,
    )

    assert out_file.exists()
    assert result["split"] == "train"
    assert result["n"] == 10  # 10 train no_violation trips
    assert "fitted_at" in result
    assert "corpus_trips_sha256" in result

    quantiles = result["quantiles"]
    assert "pickup_progress_ratio" in quantiles
    assert "route_detour_ratio" in quantiles
    assert "directional_approach_vector_index" in quantiles
    assert "min_distance_to_pickup" in quantiles

    class_medians = result["class_medians"]
    assert "no_violation" in class_medians["pickup_progress_ratio"]
    assert "ERR-03" in class_medians["pickup_progress_ratio"]

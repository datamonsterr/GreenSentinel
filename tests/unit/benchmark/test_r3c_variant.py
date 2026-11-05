"""Unit tests for R3C clean GBM variant (Issue #546 / Epic #494)."""

from __future__ import annotations

from pathlib import Path

import pytest

from scripts.benchmark.experiments import variants
from scripts.benchmark.experiments.r3c.train import GBM_CLASSES, train_r3c_gbm
from scripts.benchmark.experiments.variants import get_variant, list_variants


@pytest.fixture(scope="module")
def mock_trained_model(tmp_path_factory) -> Path:
    tmp_dir = tmp_path_factory.mktemp("r3c_test_model")
    model_path = tmp_dir / "model.pkl"

    bundles = []
    classes = ["no_violation", "ERR-01", "ERR-02", "ERR-03", "ERR-04", "ERR-05"]
    for i in range(60):
        cls = classes[i % len(classes)]
        bundles.append(
            {
                "trip_ref": f"train_{i:04d}",
                "driver_id": f"drv_{i % 10:03d}",
                "split": "train",
                "label": cls,
                "pickup": {"latitude": 10.770, "longitude": 106.690},
                "dropoff": {"latitude": 10.780, "longitude": 106.700},
                "planned_route": {"distance_m": 1500.0, "duration_s": 250.0},
                "telemetry": [
                    {
                        "latitude": 10.770,
                        "longitude": 106.690,
                        "speed_mps": 6.0,
                        "occurred_at": "2026-10-01T00:00:00Z",
                    },
                    {
                        "latitude": 10.772,
                        "longitude": 106.692,
                        "speed_mps": 6.5,
                        "occurred_at": "2026-10-01T00:00:30Z",
                    },
                ],
            }
        )
    train_r3c_gbm(bundles, output_path=model_path, n_estimators=5, random_state=42)
    return model_path


def test_variant_registered():
    variants.discover_variants()
    all_vars = list_variants()
    assert "r3c_clean_gbm" in all_vars


def test_variant_short_circuit_on_outage(monkeypatch, mock_trained_model: Path):
    monkeypatch.setenv("R3C_MODEL_PATH", str(mock_trained_model))
    # Import variant module
    from scripts.benchmark.experiments.variants import r3c_clean_gbm

    r3c_clean_gbm.reset_model_cache()

    outage_bundle = {
        "trip_ref": "outage-test",
        "platform_incident": {"kind": "NETWORK_OUTAGE"},
        "telemetry": [],
    }

    fn = get_variant("r3c_clean_gbm")
    res = fn(outage_bundle, live=False)

    assert res["predicted_category"] == "insufficient_evidence"
    assert res["probabilities"]["insufficient_evidence"] > 0.9
    assert res["model_used"] == "guardrail_short_circuit"


def test_variant_predicts_on_normal_trip(monkeypatch, mock_trained_model: Path):
    monkeypatch.setenv("R3C_MODEL_PATH", str(mock_trained_model))
    from scripts.benchmark.experiments.variants import r3c_clean_gbm

    r3c_clean_gbm.reset_model_cache()

    normal_bundle = {
        "trip_ref": "normal-test",
        "pickup": {"latitude": 10.770, "longitude": 106.690},
        "dropoff": {"latitude": 10.780, "longitude": 106.700},
        "planned_route": {"distance_m": 1500.0, "duration_s": 250.0},
        "telemetry": [
            {
                "latitude": 10.770,
                "longitude": 106.690,
                "speed_mps": 7.0,
                "occurred_at": "2026-10-01T00:00:00Z",
            },
            {
                "latitude": 10.772,
                "longitude": 106.692,
                "speed_mps": 7.5,
                "occurred_at": "2026-10-01T00:00:30Z",
            },
        ],
    }

    fn = get_variant("r3c_clean_gbm")
    res = fn(normal_bundle, live=False)

    assert res["predicted_category"] in GBM_CLASSES
    assert len(res["probabilities"]) == 7  # 7 benchmark classes
    assert "insufficient_evidence" in res["probabilities"]
    assert res["probabilities"]["insufficient_evidence"] == 0.0
    assert 0.0 <= res["confidence"] <= 1.0
    assert res["input_tokens"] == 0

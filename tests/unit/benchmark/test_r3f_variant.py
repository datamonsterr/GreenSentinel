"""Unit tests for R3F variant runner and probability export for stacking."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("torch")

from scripts.benchmark.experiments.r3f.dataset import (
    DEFAULT_CLASSES,
    MODEL_CLASSES,
    NUM_CHANNELS,
    NUM_STATIC_FEATURES,
)
from scripts.benchmark.experiments.r3f.model import R3FTrajectoryClassifier, save_r3f_model
from scripts.benchmark.experiments.variants.r3f_seq import (
    predict_r3f_probabilities,
    r3f_seq_variant,
)


@pytest.fixture
def mock_trained_model_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    model = R3FTrajectoryClassifier(
        in_channels=NUM_CHANNELS,
        static_dim=NUM_STATIC_FEATURES,
        num_classes=len(MODEL_CLASSES),
    )
    ckpt = tmp_path / "model.pt"
    save_r3f_model(model, ckpt, metadata={"classes": MODEL_CLASSES})
    monkeypatch.setenv("R3F_MODEL_PATH", str(ckpt))
    return ckpt


@pytest.fixture
def sample_bundle() -> dict[str, Any]:
    return {
        "trip_ref": "trip-r3f-eval-01",
        "driver_id": "drv-002",
        "label": "no_violation",
        "telemetry": [
            {
                "latitude": 21.000 + i * 0.0002,
                "longitude": 105.800 + i * 0.0002,
                "accuracy_m": 5.0,
                "speed_mps": 8.0,
                "mock_location_reported": False,
                "occurred_at": f"2026-10-01T08:00:{i:02d}Z",
            }
            for i in range(50)
        ],
        "pickup": {"lat": 21.000, "lon": 105.800},
        "dropoff": {"lat": 21.010, "lon": 105.810},
        "trip": {"fare_amount_vnd": 35000},
    }


def test_r3f_variant_normal_prediction(mock_trained_model_file: Path, sample_bundle: dict[str, Any]):
    res = r3f_seq_variant(sample_bundle, live=False)
    assert "predicted_category" in res
    assert res["predicted_category"] in DEFAULT_CLASSES
    assert 0.0 <= res["confidence"] <= 1.0

    probs = res.get("probabilities")
    assert isinstance(probs, dict)
    assert set(probs.keys()) == set(DEFAULT_CLASSES)
    assert pytest.approx(sum(probs.values()), abs=1e-4) == 1.0

    assert res["priority_tier"] in (1, 2, 3)
    assert res["model_used"] == "r3f_trajectory_sequence"


def test_r3f_variant_guardrail_short_circuit(mock_trained_model_file: Path, sample_bundle: dict[str, Any]):
    # Trip with platform outage should trigger guardrail short-circuit
    short_circuit_bundle = dict(sample_bundle)
    short_circuit_bundle["platform_incident"] = {
        "kind": "platform_outage",
        "severity": "CRITICAL",
        "impact": "telemetry_lost",
    }
    short_circuit_bundle["telemetry"] = []

    res = r3f_seq_variant(short_circuit_bundle, live=False)
    assert res["predicted_category"] == "insufficient_evidence"
    assert res["model_used"] == "guardrail_short_circuit"
    assert res["guardrail_blocked"] is True


def test_predict_r3f_probabilities_export(mock_trained_model_file: Path, sample_bundle: dict[str, Any]):
    probs = predict_r3f_probabilities(sample_bundle)
    assert isinstance(probs, dict)
    assert len(probs) == len(DEFAULT_CLASSES)
    for c in DEFAULT_CLASSES:
        assert c in probs
        assert isinstance(probs[c], float)
    assert pytest.approx(sum(probs.values()), abs=1e-4) == 1.0

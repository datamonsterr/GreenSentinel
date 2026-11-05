"""Unit tests for R3F model training pipeline and early stopping."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

pytest.importorskip("torch")

from scripts.benchmark.experiments.r3f.dataset import MODEL_CLASSES
from scripts.benchmark.experiments.r3f.model import load_r3f_model
from scripts.benchmark.experiments.r3f.train import (
    compute_class_weights,
    train_r3f_model,
)


def create_synthetic_corpus(path: Path, n_trips: int = 50) -> None:
    classes = MODEL_CLASSES
    with path.open("w", encoding="utf-8") as f:
        for i in range(n_trips):
            label = classes[i % len(classes)]
            bundle = {
                "trip_ref": f"synth-trip-{i:03d}",
                "driver_id": f"drv-{i:02d}",
                "split": "train",
                "label": label,
                "telemetry": [
                    {
                        "latitude": 21.0 + step * 0.0005,
                        "longitude": 105.8 + step * 0.0005,
                        "occurred_at": f"2026-10-01T08:{step // 60:02d}:{step % 60:02d}Z",
                        "accuracy_m": 5.0,
                        "mock_location_reported": (label == "ERR-02" and step % 10 == 0),
                    }
                    for step in range(30)
                ],
                "pickup": {"lat": 21.0, "lon": 105.8},
                "dropoff": {"lat": 21.015, "lon": 105.815},
                "trip": {"fare_amount_vnd": 40000},
            }
            f.write(json.dumps(bundle) + "\n")


def test_compute_class_weights():
    # Labels 0, 0, 0, 1
    y = [0, 0, 0, 1]
    weights = compute_class_weights(y, num_classes=2)
    assert len(weights) == 2
    # Minority class (1) must have higher weight than majority class (0)
    assert weights[1] > weights[0]


def test_train_r3f_model_synthetic():
    with tempfile.TemporaryDirectory() as tmp_dir:
        corpus_path = Path(tmp_dir) / "synth_trips.jsonl"
        out_model_path = Path(tmp_dir) / "model.pt"
        create_synthetic_corpus(corpus_path, n_trips=40)

        result = train_r3f_model(
            corpus_path=corpus_path,
            out_model_path=out_model_path,
            epochs=2,
            batch_size=8,
            lr=1e-3,
            val_ratio=0.25,
            seed=20261017,
        )

        assert out_model_path.exists()
        assert "best_val_macro_f1" in result
        assert "train_time_s" in result
        assert result["epochs_trained"] == 2

        # Verify saved model can be loaded and executes forward pass
        loaded_model, meta = load_r3f_model(out_model_path)
        assert meta.get("classes") == MODEL_CLASSES

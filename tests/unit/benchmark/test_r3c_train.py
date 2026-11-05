"""Unit tests for R3C LightGBM training pipeline (Issue #546 / Epic #494)."""

from __future__ import annotations

import pickle
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from scripts.benchmark.experiments.r3c.train import (
    GBM_CLASSES,
    build_train_dataset,
    train_r3c_gbm,
)


@pytest.fixture
def mock_training_bundles() -> list[dict[str, Any]]:
    bundles = []
    # Create synthetic bundles for each of the 6 GBM classes + 1 insufficient_evidence (which short-circuits)
    classes = ["no_violation", "ERR-01", "ERR-02", "ERR-03", "ERR-04", "ERR-05"]
    for i in range(120):
        cls = classes[i % len(classes)]
        bundles.append(
            {
                "trip_ref": f"train_{i:04d}",
                "driver_id": f"drv_{i % 20:03d}",
                "split": "train",
                "label": cls,
                "pickup": {"latitude": 10.770, "longitude": 106.690},
                "dropoff": {"latitude": 10.780, "longitude": 106.700},
                "planned_route": {"distance_m": 1500.0, "duration_s": 250.0},
                "telemetry": [
                    {
                        "latitude": 10.770 + (i % 5) * 0.001,
                        "longitude": 106.690 + (i % 5) * 0.001,
                        "speed_mps": 6.0 + (i % 3),
                        "occurred_at": "2026-10-01T00:00:00Z",
                    },
                    {
                        "latitude": 10.772 + (i % 5) * 0.001,
                        "longitude": 106.692 + (i % 5) * 0.001,
                        "speed_mps": 6.5 + (i % 3),
                        "occurred_at": "2026-10-01T00:00:30Z",
                    },
                ],
            }
        )
    # Add an insufficient_evidence bundle with network outage (should be skipped in GBM training)
    bundles.append(
        {
            "trip_ref": "outage_01",
            "driver_id": "drv_999",
            "split": "train",
            "label": "insufficient_evidence",
            "platform_incident": {"kind": "NETWORK_OUTAGE"},
            "telemetry": [],
        }
    )
    return bundles


def test_build_train_dataset(mock_training_bundles):
    x_mat, y, weights = build_train_dataset(mock_training_bundles)
    assert len(x_mat) == 120  # Outage trip skipped
    assert len(y) == 120
    assert len(weights) == 120
    # Labels should only contain the 6 GBM classes
    assert set(np.unique(y)).issubset(set(GBM_CLASSES))
    assert "insufficient_evidence" not in np.unique(y)


def test_train_r3c_gbm(mock_training_bundles, tmp_path: Path):
    model_path = tmp_path / "model.pkl"
    artifact = train_r3c_gbm(
        mock_training_bundles,
        output_path=model_path,
        n_estimators=10,
        random_state=42,
    )
    assert model_path.exists()
    assert "model" in artifact
    assert "classes" in artifact
    assert artifact["classes"] == GBM_CLASSES

    # Verify reload
    with open(model_path, "rb") as f:
        reloaded = pickle.load(f)
    assert reloaded["classes"] == GBM_CLASSES

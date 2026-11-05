"""Unit tests for R3D Stacked variant (Issue #554 / Epic #494)."""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import numpy as np

from scripts.benchmark.experiments import variants
from scripts.benchmark.experiments.r3c.train import BENCHMARK_7_CLASSES, GBM_CLASSES
from scripts.benchmark.experiments.variants import get_variant, list_variants


def _make_sample_bundle(trip_ref: str = "trip_001", is_outage: bool = False) -> dict[str, Any]:
    if is_outage:
        return {
            "trip_ref": trip_ref,
            "driver_id": "drv_001",
            "label": "insufficient_evidence",
            "telemetry": [],
            "planned_route": {"pickup": [10.7769, 106.7009], "dropoff": [10.7800, 106.7050]},
            "platform_incident": {"type": "network_outage"},
        }

    return {
        "trip_ref": trip_ref,
        "driver_id": "drv_001",
        "label": "no_violation",
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
        "platform_incident": None,
    }


def test_variant_registered():
    """Verify r3d_stacked is registered in the experiment variants registry."""
    variants.discover_variants()
    all_vars = list_variants()
    assert "r3d_stacked" in all_vars
    fn = get_variant("r3d_stacked")
    assert callable(fn)


def test_variant_short_circuit_on_guardrail():
    """Verify platform outages or missing telemetry short-circuit to insufficient_evidence."""
    variants.discover_variants()
    fn = get_variant("r3d_stacked")
    bundle = _make_sample_bundle(is_outage=True)
    res = fn(bundle, live=False)

    assert res["predicted_category"] == "insufficient_evidence"
    assert res["confidence"] == 1.0
    assert res["probabilities"]["insufficient_evidence"] == 1.0
    for c in GBM_CLASSES:
        assert res["probabilities"][c] == 0.0
    assert res["input_tokens"] == 0
    assert res["model_used"] == "guardrail_short_circuit"


def test_variant_prediction_with_stacker():
    """Verify normal assessment predicts 7 classes with valid sum, confidence and priority tier."""
    variants.discover_variants()
    fn = get_variant("r3d_stacked")
    from scripts.benchmark.experiments.variants import r3d_stacked

    bundle = _make_sample_bundle(is_outage=False)

    # Mock base model predictions
    mock_r3c_probs = {c: 0.1 for c in GBM_CLASSES}
    mock_r3c_probs["no_violation"] = 0.5

    mock_r3f_probs = {c: 0.1 for c in GBM_CLASSES}
    mock_r3f_probs["no_violation"] = 0.5

    with (
        patch.object(
            r3d_stacked,
            "predict_r3c_probabilities_for_bundle",
            return_value=mock_r3c_probs,
        ),
        patch.object(
            r3d_stacked,
            "predict_r3f_probabilities_for_bundle",
            return_value=mock_r3f_probs,
        ),
    ):
        res = fn(bundle, live=False)

        assert res["predicted_category"] in GBM_CLASSES
        assert 0.0 <= res["confidence"] <= 1.0
        assert "probabilities" in res
        probs = res["probabilities"]
        assert len(probs) == len(BENCHMARK_7_CLASSES)
        assert probs["insufficient_evidence"] == 0.0
        np.testing.assert_allclose(sum(probs.values()), 1.0, atol=1e-5)
        assert res["input_tokens"] == 0
        assert res["priority_tier"] in (1, 2, 3)

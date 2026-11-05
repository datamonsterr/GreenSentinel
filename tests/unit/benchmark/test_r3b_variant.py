"""Unit tests for R3B evidence context experiment variant (Issue #547 / #494)."""

from __future__ import annotations

from typing import Any

import pytest

from scripts.benchmark.experiments import variants


@pytest.fixture
def sample_r3b_bundle() -> dict[str, Any]:
    return {
        "trip_ref": "trip-r3b-test-01",
        "driver_id": "drv-r3b-001",
        "telemetry": [
            {
                "latitude": 10.770,
                "longitude": 106.690,
                "speed_mps": 5.0,
                "occurred_at": "2026-10-01T00:00:00Z",
            },
            {
                "latitude": 10.772,
                "longitude": 106.692,
                "speed_mps": 6.0,
                "occurred_at": "2026-10-01T00:01:00Z",
            },
        ],
        "pickup": [106.695, 10.775],
        "dropoff": [106.700, 10.780],
        "trip": {"fare_amount_vnd": 50000, "status": "completed"},
        "assignment": {},
    }


def test_r3b_variant_is_registered() -> None:
    """r3b_evidence_context variant must be discoverable in variants registry."""
    variants.discover_variants()
    all_variants = variants.list_variants()
    assert "r3b_evidence_context" in all_variants, f"r3b_evidence_context not registered; available: {all_variants}"


def test_r3b_variant_offline_execution(sample_r3b_bundle: dict[str, Any]) -> None:
    """r3b_evidence_context variant should execute offline using fallback or mock without crashing."""
    variants.discover_variants()
    fn = variants.get_variant("r3b_evidence_context")
    res = fn(sample_r3b_bundle, live=False)

    assert "predicted_category" in res
    assert "confidence" in res
    assert "input_tokens" in res
    assert "latency_ms" in res
    assert res["predicted_category"] in {
        "ERR-01",
        "ERR-02",
        "ERR-03",
        "ERR-04",
        "ERR-05",
        "no_violation",
        "insufficient_evidence",
    }

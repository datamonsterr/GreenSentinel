"""Unit tests for R3C clean feature extractor (Issue #546 / Epic #494)."""

from __future__ import annotations

import math
from typing import Any

import pytest

from scripts.benchmark.experiments.r3c.features import (
    CANDIDATE_FEATURE_NAMES,
    FEATURE_NAMES,
    extract_features,
    haversine_distance_m,
)


@pytest.fixture
def clean_sample_bundle() -> dict[str, Any]:
    return {
        "trip_ref": "trip-r3c-test-01",
        "driver_id": "drv-001",
        "pickup": {"latitude": 10.775, "longitude": 106.695},
        "dropoff": {"latitude": 10.785, "longitude": 106.705},
        "planned_route": {"distance_m": 2000.0, "duration_s": 300.0},
        "telemetry": [
            {
                "latitude": 10.770,
                "longitude": 106.690,
                "speed_mps": 8.0,
                "occurred_at": "2026-10-01T00:00:00Z",
                "mock_location_reported": False,
            },
            {
                "latitude": 10.772,
                "longitude": 106.692,
                "speed_mps": 8.5,
                "occurred_at": "2026-10-01T00:00:30Z",
                "mock_location_reported": False,
            },
            {
                "latitude": 10.774,
                "longitude": 106.694,
                "speed_mps": 8.2,
                "occurred_at": "2026-10-01T00:01:00Z",
                "mock_location_reported": False,
            },
        ],
        "driver_analytics": {"window_7d": {"trips": 15, "cancellations": 0}},
        "driver_profile": {"rating": 4.9, "total_trips": 100},
        # Synthetic / leaky fields that MUST NOT leak into feature vector:
        "platform_incident": {"kind": "TELEMETRY_ANOMALY"},
        "driver_objection": {"text": "Tài xế khiếu nại"},
        "simulation_audit": {"severity": "critical"},
    }


def test_haversine_distance_m():
    # Distance between ~10.770, 106.690 and ~10.772, 106.692 is ~305m
    d = haversine_distance_m(10.770, 106.690, 10.772, 106.692)
    assert 250.0 < d < 350.0
    # Zero distance
    assert haversine_distance_m(10.0, 106.0, 10.0, 106.0) == 0.0


def test_feature_extraction_structure(clean_sample_bundle: dict[str, Any]):
    feat_dict, feat_vec = extract_features(clean_sample_bundle)
    assert len(feat_vec) == len(FEATURE_NAMES)
    assert len(feat_dict) == len(FEATURE_NAMES)
    assert sorted(feat_dict.keys()) == sorted(FEATURE_NAMES)

    for k, v in feat_dict.items():
        assert isinstance(v, (int, float)), f"Feature {k} is not numeric"
        assert not math.isnan(v), f"Feature {k} is NaN"
        assert not math.isinf(v), f"Feature {k} is Inf"


def test_leaky_fields_excluded():
    leaky_keywords = [
        "platform_incident",
        "platform_outage",
        "incident",
        "objection",
        "risk_band",
        "davi_score",
        "distance_to_pickup_m",
        "cancellation_reason",
        "cancellation_actor",
        "scenario",
    ]
    for feat in FEATURE_NAMES:
        for kw in leaky_keywords:
            assert kw not in feat.lower(), f"Feature '{feat}' contains forbidden leaky keyword '{kw}'"


def test_candidate_features_superset():
    assert set(FEATURE_NAMES).issubset(set(CANDIDATE_FEATURE_NAMES))


def test_empty_telemetry_resilience():
    empty_bundle = {"trip_ref": "empty", "telemetry": []}
    feat_dict, feat_vec = extract_features(empty_bundle)
    assert len(feat_vec) == len(FEATURE_NAMES)
    for k, v in feat_dict.items():
        assert not math.isnan(v), f"Feature {k} is NaN on empty telemetry"
        assert not math.isinf(v), f"Feature {k} is Inf on empty telemetry"


def test_single_point_telemetry():
    bundle = {
        "telemetry": [
            {
                "latitude": 10.770,
                "longitude": 106.690,
                "speed_mps": 0.0,
                "occurred_at": "2026-10-01T00:00:00Z",
            }
        ]
    }
    feat_dict, feat_vec = extract_features(bundle)
    assert len(feat_vec) == len(FEATURE_NAMES)
    assert feat_dict["point_count"] == 1.0

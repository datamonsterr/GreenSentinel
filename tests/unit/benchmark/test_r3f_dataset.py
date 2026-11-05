"""Unit tests for R3F dataset resampling, feature extraction, and domain randomisation."""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pytest

from scripts.benchmark.experiments.r3f.dataset import (
    NUM_CHANNELS,
    NUM_STATIC_FEATURES,
    NUM_STEPS,
    apply_domain_randomisation,
    extract_r3f_features,
    haversine_m,
    resample_telemetry,
)


@pytest.fixture
def sample_bundle() -> dict[str, Any]:
    return {
        "trip_ref": "trip-r3f-test-01",
        "driver_id": "drv-001",
        "label": "ERR-02",
        "telemetry": [
            {
                "latitude": 21.000 + i * 0.0005,
                "longitude": 105.800 + i * 0.0005,
                "accuracy_m": 8.0,
                "speed_mps": 5.0,
                "mock_location_reported": (i % 20 == 0),
                "occurred_at": f"2026-10-01T08:00:{i:02d}Z" if i < 60 else f"2026-10-01T08:01:{i - 60:02d}Z",
            }
            for i in range(80)
        ],
        "pickup": {"lat": 21.000, "lon": 105.800},
        "dropoff": {"lat": 21.040, "lon": 105.840},
        "trip": {"fare_amount_vnd": 65000},
        "driver_profile": {"rating": 4.9},
    }


def test_haversine_distance():
    # Hanoi Royal City to Ga Ha Noi ~ 4.5km
    d = haversine_m(21.0035, 105.8165, 21.0231, 105.8424)
    assert 3000 < d < 6000


def test_resample_telemetry_shape(sample_bundle: dict[str, Any]):
    pts = sample_bundle["telemetry"]
    resampled = resample_telemetry(pts, num_steps=NUM_STEPS)
    assert len(resampled) == NUM_STEPS
    assert all("lat" in p and "lon" in p and "t" in p for p in resampled)
    # Check monotonicity of time
    for i in range(1, len(resampled)):
        assert resampled[i]["t"] >= resampled[i - 1]["t"]


def test_resample_telemetry_edge_cases():
    # Empty points
    res_empty = resample_telemetry([], num_steps=NUM_STEPS)
    assert len(res_empty) == NUM_STEPS
    assert all(p["lat"] == 0.0 for p in res_empty)

    # Single point
    pt = [{"latitude": 21.0, "longitude": 105.0, "accuracy_m": 5.0, "occurred_at": "2026-10-01T00:00:00Z"}]
    res_single = resample_telemetry(pt, num_steps=NUM_STEPS)
    assert len(res_single) == NUM_STEPS
    assert math.isclose(res_single[0]["lat"], 21.0)
    assert math.isclose(res_single[-1]["lat"], 21.0)


def test_extract_r3f_features_shapes_and_channels(sample_bundle: dict[str, Any]):
    seq, static = extract_r3f_features(sample_bundle, augment=False)
    assert isinstance(seq, np.ndarray)
    assert isinstance(static, np.ndarray)

    assert seq.shape == (NUM_CHANNELS, NUM_STEPS)
    assert static.shape == (NUM_STATIC_FEATURES,)

    # Verify no NaN or Inf
    assert not np.isnan(seq).any()
    assert not np.isinf(seq).any()
    assert not np.isnan(static).any()
    assert not np.isinf(static).any()


def test_no_label_leakage_in_features(sample_bundle: dict[str, Any]):
    # Mutate bundle with sensitive fields
    polluted_bundle = dict(sample_bundle)
    polluted_bundle["platform_incident"] = {"kind": "platform_outage", "severity": "HIGH"}
    polluted_bundle["driver_objection"] = "Driver stated route detour due to police block"
    polluted_bundle["cancellation_actor"] = "driver"
    polluted_bundle["cancellation_reason"] = "passenger_no_show"
    polluted_bundle["davi_score"] = 0.99
    polluted_bundle["distance_to_pickup_m"] = 500.0

    seq1, static1 = extract_r3f_features(sample_bundle, augment=False)
    seq2, static2 = extract_r3f_features(polluted_bundle, augment=False)

    # Features must be identical despite label proxies
    np.testing.assert_allclose(seq1, seq2, atol=1e-5)
    np.testing.assert_allclose(static1, static2, atol=1e-5)


def test_domain_randomisation_augmentations(sample_bundle: dict[str, Any]):
    seq_clean, _ = extract_r3f_features(sample_bundle, augment=False)

    # With augmentation, outputs should be perturbed but valid and finite
    seq_aug, static_aug = extract_r3f_features(sample_bundle, augment=True)
    assert seq_aug.shape == (NUM_CHANNELS, NUM_STEPS)
    assert static_aug.shape == (NUM_STATIC_FEATURES,)
    assert not np.isnan(seq_aug).any()
    assert not np.isinf(seq_aug).any()

    # The augmented sequence should differ from the clean sequence
    assert not np.allclose(seq_clean, seq_aug, atol=1e-3)


def test_apply_domain_randomisation_components(sample_bundle: dict[str, Any]):
    pts = [
        {"lat": 21.0 + i * 0.001, "lon": 105.8 + i * 0.001, "t": float(i), "accuracy_m": 5.0, "mock": False}
        for i in range(128)
    ]
    pickup = (21.0, 105.8)
    dropoff = (21.128, 105.928)

    aug_pts, aug_pickup, aug_dropoff = apply_domain_randomisation(
        pts,
        pickup=pickup,
        dropoff=dropoff,
        enable_noise=True,
        enable_rotation=True,
        enable_dropout=True,
        enable_timewarp=True,
    )

    assert 10 <= len(aug_pts) <= 150
    assert all(not math.isnan(p["lat"]) and not math.isnan(p["lon"]) for p in aug_pts)
    assert aug_pickup is not None
    assert aug_dropoff is not None

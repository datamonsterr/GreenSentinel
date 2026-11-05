from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from src.services.fraud_classifier.features_sequence import (
    MODEL_CLASSES,
    NUM_CHANNELS,
    NUM_STATIC_FEATURES,
    NUM_STEPS,
    extract_r3f_features,
)
from src.services.fraud_classifier.features_tabular import (
    CANDIDATE_FEATURE_NAMES,
    FEATURE_NAMES,
    extract_features,
)
from src.services.fraud_classifier.guardrail import (
    evaluate_bundle_guardrail,
    normalise_bundle,
    scrub_bundle,
)
from src.services.jev_state_builder import map_telemetry_event_to_jev_input

FIXTURE_PATH = Path("tests/fixtures/benchmark/classifier_fixtures.json")


@pytest.fixture
def fixtures() -> dict:
    with FIXTURE_PATH.open() as f:
        return json.load(f)


def test_tabular_feature_names_constants():
    assert len(FEATURE_NAMES) == 37
    assert len(CANDIDATE_FEATURE_NAMES) == 48
    assert set(FEATURE_NAMES).issubset(set(CANDIDATE_FEATURE_NAMES))


def test_sequence_feature_constants():
    assert NUM_CHANNELS == 7
    assert NUM_STEPS == 128
    assert NUM_STATIC_FEATURES == 6
    assert len(MODEL_CLASSES) == 6


def test_extract_tabular_features(fixtures):
    trip = fixtures["normal_trip"]
    feat_dict, feat_vec = extract_features(trip)
    assert len(feat_dict) == 37
    assert len(feat_vec) == 37
    assert all(np.isfinite(v) for v in feat_vec)
    assert feat_dict["point_count"] > 0
    assert feat_dict["trip_duration_s"] > 0


def test_extract_sequence_features(fixtures):
    trip = fixtures["normal_trip"]
    seq_data, static_data = extract_r3f_features(trip, augment=False)
    assert seq_data.shape == (NUM_CHANNELS, NUM_STEPS)
    assert static_data.shape == (NUM_STATIC_FEATURES,)
    assert seq_data.dtype == np.float32
    assert static_data.dtype == np.float32
    assert np.all(np.isfinite(seq_data))
    assert np.all(np.isfinite(static_data))


def test_scrub_bundle(fixtures):
    trip = dict(fixtures["normal_trip"])
    trip["label"] = "ERR-02"
    trip["scenario"] = "stall_scenario"
    trip["expected_category"] = "ERR-02"
    trip["simulation_id"] = "sim-123"
    trip["anomaly_score"] = 0.99
    trip["profile_provenance"] = "synthetic"

    scrubbed = scrub_bundle(trip)
    assert "label" not in scrubbed
    assert "scenario" not in scrubbed
    assert "expected_category" not in scrubbed
    assert "simulation_id" not in scrubbed
    assert "anomaly_score" not in scrubbed
    assert "profile_provenance" not in scrubbed
    assert "telemetry" in scrubbed
    assert "pickup" in scrubbed


def test_normalise_bundle_formats(fixtures):
    trip = fixtures["normal_trip"]
    # 1. Raw bundle
    norm1 = normalise_bundle(trip)
    assert "telemetry" in norm1
    assert len(norm1["telemetry"]) > 0

    # 2. Mapped jev input
    jev_inp = map_telemetry_event_to_jev_input(trip)
    norm2 = normalise_bundle(jev_inp)
    assert "telemetry" in norm2
    assert len(norm2["telemetry"]) > 0

    # Both produce extractable features
    _, vec1 = extract_features(norm1)
    _, vec2 = extract_features(norm2)
    assert len(vec1) == 37
    assert len(vec2) == 37


def test_guardrail_short_circuit(fixtures):
    normal_trip = fixtures["normal_trip"]
    gr_normal = evaluate_bundle_guardrail(normal_trip)
    assert not gr_normal["should_short_circuit"]
    assert not gr_normal["blocked"]

    gr_trip = fixtures["guardrail_trip"]
    gr_blocked = evaluate_bundle_guardrail(gr_trip)
    assert gr_blocked["should_short_circuit"]
    assert gr_blocked["blocked"]
    assert gr_blocked["reason"] == "APP_CRASH"

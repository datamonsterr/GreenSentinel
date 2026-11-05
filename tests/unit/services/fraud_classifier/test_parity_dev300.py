from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.services.fraud_classifier.model import (
    ClassifierUnavailableError,
    get_fraud_classifier,
    reset_fraud_classifier,
)

DEV300_PATH = Path("/home/dat/releases_v2_1/dev300.jsonl")
PRED300_PATH = Path("/home/dat/research_v2/FINAL/r3d_dev300_blind/predictions.jsonl")


def test_dev300_parity():
    if not DEV300_PATH.exists() or not PRED300_PATH.exists():
        pytest.skip("dev300 dataset or reference predictions not present (offline/CI mode)")

    reset_fraud_classifier()
    try:
        classifier = get_fraud_classifier()
    except ClassifierUnavailableError:
        pytest.skip("Classifier artifacts not yet available")

    class_matches = 0
    max_prob_diff = 0.0
    total = 0

    with DEV300_PATH.open() as f_trips, PRED300_PATH.open() as f_preds:
        for idx, (trip_line, pred_line) in enumerate(zip(f_trips, f_preds, strict=False)):
            trip = json.loads(trip_line)
            expected = json.loads(pred_line)
            total += 1

            result = classifier.predict(trip)

            if result.category == expected["predicted_category"]:
                class_matches += 1
            else:
                pytest.fail(
                    f"Trip {idx} ({trip.get('trip_ref')}) class mismatch: "
                    f"got {result.category}, expected {expected['predicted_category']}"
                )

            for c, exp_p in expected["probabilities"].items():
                p = result.probabilities.get(c, 0.0)
                diff = abs(p - exp_p)
                if diff > max_prob_diff:
                    max_prob_diff = diff

    assert total == 300, f"Expected 300 trips in dev300, got {total}"
    assert class_matches == 300, f"Expected 300/300 class matches, got {class_matches}"
    assert max_prob_diff <= 1e-4, f"Max probability diff {max_prob_diff} exceeds 1e-4 threshold"

"""Unit tests for R3D Stacker meta-learner and feature interfaces (Issue #554 / Epic #494)."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

import numpy as np

from scripts.benchmark.experiments.r3c.train import GBM_CLASSES
from scripts.benchmark.experiments.r3d.stack import (
    baseline_averaging,
    baseline_geometric,
    build_stacker_features,
    evaluate_meta_learner_candidates,
    fit_meta_learner,
    predict_stacker_probabilities,
)


def _make_sample_oof_data(n_samples: int = 50, seed: int = 42) -> dict[str, list[Any]]:
    rng = np.random.RandomState(seed)
    data: dict[str, list[Any]] = {
        "trip_ref": [f"trip_{i:03d}" for i in range(n_samples)],
        "driver_id": [f"drv_{i // 5:02d}" for i in range(n_samples)],
        "label": [GBM_CLASSES[i % len(GBM_CLASSES)] for i in range(n_samples)],
        "fold": [i % 5 for i in range(n_samples)],
    }
    for c in GBM_CLASSES:
        data[f"r3c_p_{c}"] = []
        data[f"r3f_p_{c}"] = []

    for i in range(n_samples):
        r3c_p = rng.dirichlet(np.ones(len(GBM_CLASSES)))
        r3f_p = rng.dirichlet(np.ones(len(GBM_CLASSES)))
        for idx, cls_name in enumerate(GBM_CLASSES):
            data[f"r3c_p_{cls_name}"].append(float(r3c_p[idx]))
            data[f"r3f_p_{cls_name}"].append(float(r3f_p[idx]))

    return data


def test_build_stacker_features_without_llm():
    """Verify feature matrix without LLM columns: R3C probs, R3F probs, abs diffs, and entropies."""
    data = _make_sample_oof_data(n_samples=10)
    x_feat, feat_names = build_stacker_features(data)

    assert isinstance(x_feat, np.ndarray)
    assert x_feat.shape[0] == 10
    # 6 (r3c) + 6 (r3f) + 6 (abs diff) + 1 (r3c entropy) + 1 (r3f entropy) = 20 features
    assert x_feat.shape[1] == 20
    assert len(feat_names) == 20

    assert "r3c_entropy" in feat_names
    assert "r3f_entropy" in feat_names
    for c in GBM_CLASSES:
        assert f"r3c_p_{c}" in feat_names
        assert f"r3f_p_{c}" in feat_names
        assert f"diff_p_{c}" in feat_names


def test_build_stacker_features_with_optional_llm():
    """Verify feature interface accepts optional llm_p_<class> columns without breaking when absent."""
    data = _make_sample_oof_data(n_samples=5)
    # Add synthetic LLM probability columns
    for c in GBM_CLASSES:
        data[f"llm_p_{c}"] = [1.0 / len(GBM_CLASSES)] * 5

    x_with_llm, feat_names_with_llm = build_stacker_features(data)
    # Base 20 features + LLM features
    assert x_with_llm.shape[1] > 20
    for c in GBM_CLASSES:
        assert f"llm_p_{c}" in feat_names_with_llm


def test_baseline_averaging_and_geometric():
    """Verify simple probability averaging and normalized geometric mean baselines."""
    data = _make_sample_oof_data(n_samples=10)
    avg_preds = baseline_averaging(data)
    geom_preds = baseline_geometric(data)

    assert avg_preds.shape == (10, len(GBM_CLASSES))
    assert geom_preds.shape == (10, len(GBM_CLASSES))

    np.testing.assert_allclose(avg_preds.sum(axis=1), 1.0, atol=1e-5)
    np.testing.assert_allclose(geom_preds.sum(axis=1), 1.0, atol=1e-5)


def test_fit_and_predict_meta_learner():
    """Verify training and artifact inference for logistic regression and lightgbm meta-learners."""
    data = _make_sample_oof_data(n_samples=60)
    cv_results = evaluate_meta_learner_candidates(data)

    assert "logistic_regression" in cv_results
    assert "lightgbm" in cv_results
    assert "best_model" in cv_results
    assert cv_results["best_model"] in ("logistic_regression", "lightgbm")

    with tempfile.TemporaryDirectory() as tmpdir:
        artifact_path = Path(tmpdir) / "stacker.pkl"
        artifact = fit_meta_learner(data, model_type=cv_results["best_model"], output_path=artifact_path)
        assert artifact_path.exists()
        assert artifact["model_type"] == cv_results["best_model"]

        # Inference on a single trip dictionary of base probabilities
        r3c_probs = {c: 1.0 / len(GBM_CLASSES) for c in GBM_CLASSES}
        r3f_probs = {c: 1.0 / len(GBM_CLASSES) for c in GBM_CLASSES}
        p_pred = predict_stacker_probabilities(r3c_probs, r3f_probs, artifact)

        assert isinstance(p_pred, dict)
        assert len(p_pred) == len(GBM_CLASSES)
        np.testing.assert_allclose(sum(p_pred.values()), 1.0, atol=1e-5)

"""Training pipeline for Experiment R3C Clean LightGBM Baseline (Issue #546 / Epic #494).

Trains multiclass LightGBM on the train split (28k drivers split) using clean, leak-audited
kinematic features with balanced class weights and early stopping on a train-internal fold.
Saves model artifact to $R3C_MODEL_PATH (default /home/dat/research_v2/R3C/model.pkl).
Insufficient_evidence is excluded from GBM training because it is resolved exclusively
via guardrail short-circuiting outside the GBM.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import pickle
import sys
from pathlib import Path
from typing import Any

import lightgbm as lgb
import numpy as np
from sklearn.model_selection import train_test_split
from sklearn.utils.class_weight import compute_sample_weight

REPO_ROOT = Path(__file__).resolve().parents[4]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.benchmark import run_10k  # noqa: E402
from scripts.benchmark.driver_ledger import driver_split  # noqa: E402
from src.services.fraud_classifier.features_tabular import (  # noqa: E402
    FEATURE_NAMES,
    extract_features,
)

logger = logging.getLogger(__name__)

DEFAULT_MODEL_PATH = Path("/home/dat/research_v2/R3C/model.pkl")

# The 6 violation/non-violation classes handled by GBM.
# insufficient_evidence is handled purely by guardrail short-circuit outside GBM.
GBM_CLASSES: list[str] = [
    "no_violation",
    "ERR-01",
    "ERR-02",
    "ERR-03",
    "ERR-04",
    "ERR-05",
]

BENCHMARK_7_CLASSES: list[str] = [
    "no_violation",
    "ERR-01",
    "ERR-02",
    "ERR-03",
    "ERR-04",
    "ERR-05",
    "insufficient_evidence",
]


def resolve_model_path(custom_path: Path | str | None = None) -> Path:
    """Resolve destination model path honoring R3C_MODEL_PATH env var."""
    if custom_path:
        return Path(custom_path)
    env_path = os.environ.get("R3C_MODEL_PATH")
    if env_path:
        return Path(env_path)
    return DEFAULT_MODEL_PATH


def build_train_dataset(
    bundles: list[dict[str, Any]],
) -> tuple[np.ndarray, list[str], np.ndarray]:
    """Filter and build feature matrix X, string labels y, and sample weights.

    Excludes trips that short-circuit guardrails (such as platform network outages)
    and any trip labeled insufficient_evidence.
    """
    features_rows: list[list[float]] = []
    y_labels: list[str] = []

    for b in bundles:
        label = str(b.get("label") or "no_violation")
        if label == "insufficient_evidence":
            continue

        # Check guardrail short-circuit
        _, points, _ = run_10k.bundle_to_input(b)
        incident = b.get("platform_incident")
        incidents = [incident] if isinstance(incident, dict) else []
        guardrail = run_10k.evaluate_telemetry_window(points, incidents)
        if run_10k.should_short_circuit(guardrail):
            continue

        if label not in GBM_CLASSES:
            continue

        _, feat_vec = extract_features(b)
        features_rows.append(feat_vec)
        y_labels.append(label)

    if not features_rows:
        x_matrix = np.empty((0, len(FEATURE_NAMES)), dtype=float)
        weights = np.empty((0,), dtype=float)
        return x_matrix, y_labels, weights

    x_matrix = np.array(features_rows, dtype=float)
    x_matrix = np.nan_to_num(x_matrix, nan=-999.0, posinf=-999.0, neginf=-999.0)
    weights = compute_sample_weight("balanced", y_labels)

    return x_matrix, y_labels, weights


def fit_gbm_classifier(
    features_rows: list[list[float]] | np.ndarray,
    y_labels: list[str],
    output_path: Path | str | None = None,
    n_estimators: int = 250,
    learning_rate: float = 0.05,
    random_state: int = 42,
) -> dict[str, Any]:
    """Fit LightGBM on pre-extracted feature rows and labels."""
    out_path = resolve_model_path(output_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if isinstance(features_rows, np.ndarray):
        x_matrix = features_rows
    else:
        x_matrix = np.array(features_rows, dtype=float)
    x_matrix = np.nan_to_num(x_matrix, nan=-999.0, posinf=-999.0, neginf=-999.0)

    class_to_idx = {c: i for i, c in enumerate(GBM_CLASSES)}
    y_indices = np.array([class_to_idx[lbl] for lbl in y_labels], dtype=int)

    # Train-internal split for early stopping
    if len(x_matrix) >= 20 and len(np.unique(y_indices)) > 1:
        x_tr, x_val, y_tr, y_val = train_test_split(
            x_matrix,
            y_indices,
            test_size=0.15,
            stratify=y_indices,
            random_state=random_state,
        )
    else:
        x_tr, y_tr = x_matrix, y_indices
        x_val, y_val = x_matrix, y_indices

    clf = lgb.LGBMClassifier(
        objective="multiclass",
        num_class=len(GBM_CLASSES),
        class_weight="balanced",
        n_estimators=n_estimators,
        learning_rate=learning_rate,
        num_leaves=31,
        max_depth=6,
        subsample=0.85,
        colsample_bytree=0.85,
        random_state=random_state,
        n_jobs=-1,
        verbose=-1,
    )

    callbacks = [lgb.early_stopping(stopping_rounds=25, verbose=False)]
    clf.fit(
        x_tr,
        y_tr,
        eval_set=[(x_val, y_val)],
        callbacks=callbacks,
    )

    artifact = {
        "model": clf,
        "classes": GBM_CLASSES,
        "all_classes": BENCHMARK_7_CLASSES,
        "feature_names": FEATURE_NAMES,
        "class_to_idx": class_to_idx,
        "train_samples": len(x_matrix),
        "best_iteration": getattr(clf, "best_iteration_", n_estimators),
    }

    with out_path.open("wb") as f:
        pickle.dump(artifact, f)

    logger.info("Saved trained R3C model artifact to %s", out_path)
    return artifact


def train_r3c_gbm(
    train_bundles: list[dict[str, Any]],
    output_path: Path | str | None = None,
    n_estimators: int = 250,
    learning_rate: float = 0.05,
    random_state: int = 42,
) -> dict[str, Any]:
    """Train LightGBM multiclass classifier from trip bundles."""
    x_matrix, y, _ = build_train_dataset(train_bundles)
    return fit_gbm_classifier(
        x_matrix,
        y,
        output_path=output_path,
        n_estimators=n_estimators,
        learning_rate=learning_rate,
        random_state=random_state,
    )


def run_training(
    corpus_path: Path,
    output_path: Path | None = None,
    sample_cap: int | None = None,
) -> dict[str, Any]:
    """Load train split from corpus file and execute training."""
    logger.info("Streaming train split from %s", corpus_path)
    features_rows: list[list[float]] = []
    y_labels: list[str] = []

    with corpus_path.open("r", encoding="utf-8") as f:
        for idx, line in enumerate(f):
            if not line.strip():
                continue
            b = json.loads(line)
            split = b.get("split")
            if not split:
                drv_id = str(b.get("driver_id") or b.get("trip_ref") or "unknown")
                split = driver_split(drv_id)

            if split != "train":
                continue

            label = str(b.get("label") or "no_violation")
            if label == "insufficient_evidence" or label not in GBM_CLASSES:
                continue

            _, points, _ = run_10k.bundle_to_input(b)
            incident = b.get("platform_incident")
            incidents = [incident] if isinstance(incident, dict) else []
            guardrail = run_10k.evaluate_telemetry_window(points, incidents)
            if run_10k.should_short_circuit(guardrail):
                continue

            _, feat_vec = extract_features(b)
            features_rows.append(feat_vec)
            y_labels.append(label)

            if sample_cap and len(features_rows) >= sample_cap:
                break

    logger.info("Extracted %d train feature rows for 6-class GBM. Fitting...", len(features_rows))
    return fit_gbm_classifier(features_rows, y_labels, output_path=output_path)


def main():
    parser = argparse.ArgumentParser(description="Train R3C clean LightGBM baseline")
    parser.add_argument("--corpus", type=Path, default=Path("/home/dat/releases_v2_1/trips.jsonl"))
    parser.add_argument("--out-model", type=Path, default=None)
    parser.add_argument("--sample-cap", type=int, default=None)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    run_training(args.corpus, output_path=args.out_model, sample_cap=args.sample_cap)


if __name__ == "__main__":
    main()

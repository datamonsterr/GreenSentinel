"""Training, calibration, and fusion tuning for Experiment E4 (Issue #513 / Epic #494).

Builds feature matrix from TRAIN split without label proxies.
Fits HistGradientBoostingClassifier, calibrates on TRAIN holdout (isotonic),
tunes log-linear fusion weight and abstention threshold, and saves artifact
to /home/dat/research_v2/E4/model.pkl.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import logging
import pickle
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
from sklearn.calibration import CalibratedClassifierCV
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.inspection import permutation_importance
from sklearn.metrics import f1_score
from sklearn.model_selection import PredefinedSplit, train_test_split

REPO_ROOT = Path(__file__).resolve().parents[4]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.benchmark import run_10k  # noqa: E402
from scripts.benchmark.driver_ledger import driver_split  # noqa: E402
from scripts.benchmark.experiments.e4.features import FEATURE_NAMES, extract_features  # noqa: E402
from scripts.benchmark.experiments.e4.fusion import (  # noqa: E402
    DEFAULT_CLASSES,
    blend_log_linear,
    predict_with_abstention,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

CLASSES = DEFAULT_CLASSES
CLASS_TO_IDX = {c: i for i, c in enumerate(CLASSES)}


def _extract_single_trip(line: str) -> tuple[list[float], str, str] | None:
    """Parse one line from trips.jsonl, extract features and label if in train split."""
    if not line.strip():
        return None
    bundle = json.loads(line)
    split = bundle.get("split")
    if not split:
        drv_id = str(bundle.get("driver_id") or bundle.get("trip_ref") or "unknown")
        split = driver_split(drv_id)
    if split != "train":
        return None

    label = str(bundle.get("label") or "no_violation")
    trip_ref = str(bundle.get("trip_ref") or "")
    _, feat_vec = extract_features(bundle)
    return feat_vec, label, trip_ref


def build_train_dataset(
    corpus_path: Path,
    max_workers: int = 8,
    limit: int | None = None,
) -> tuple[np.ndarray, np.ndarray, list[str]]:
    """Build feature matrix X, labels y, and trip_refs from TRAIN split."""
    logger.info("Reading TRAIN split from %s...", corpus_path)
    lines: list[str] = []
    with corpus_path.open("r", encoding="utf-8") as f:
        for line in f:
            lines.append(line)
            if limit and len(lines) >= limit * 2:
                # heuristic buffer
                pass

    logger.info("Found %d total lines. Extracting features with %d workers...", len(lines), max_workers)
    X_list: list[list[float]] = []  # noqa: N806
    y_list: list[int] = []
    refs: list[str] = []

    with concurrent.futures.ProcessPoolExecutor(max_workers=max_workers) as executor:
        # Chunk lines for throughput
        results = executor.map(_extract_single_trip, lines, chunksize=100)
        for res in results:
            if res is None:
                continue
            feat_vec, label, ref = res
            if label not in CLASS_TO_IDX:
                continue
            X_list.append(feat_vec)
            y_list.append(CLASS_TO_IDX[label])
            refs.append(ref)
            if limit and len(X_list) >= limit:
                break

    X = np.array(X_list, dtype=np.float32)  # noqa: N806
    y = np.array(y_list, dtype=np.int64)
    logger.info("Extracted TRAIN dataset: X shape %s, y shape %s", X.shape, y.shape)
    return X, y, refs


def compute_heuristic_probabilities(
    corpus_path: Path,
    holdout_refs: set[str],
) -> dict[str, dict[str, float]]:
    """Run offline heuristic assessment on holdout trips to get baseline Jev probs for fusion tuning."""
    logger.info("Computing offline heuristic probabilities for %d holdout trips...", len(holdout_refs))
    service = run_10k.build_offline_service()
    probs_by_ref: dict[str, dict[str, float]] = {}

    with corpus_path.open("r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            bundle = json.loads(line)
            ref = str(bundle.get("trip_ref") or "")
            if ref not in holdout_refs:
                continue

            cleaned_bundle = run_10k.blank_cancellation_enums(bundle)
            jev_inp, points, _ = run_10k.bundle_to_input(cleaned_bundle)
            jev_inp.state_variant = "features_numeric"

            incident = cleaned_bundle.get("platform_incident")
            incidents = [incident] if isinstance(incident, dict) else []
            guardrail = run_10k.evaluate_telemetry_window(points, incidents)

            if run_10k.should_short_circuit(guardrail):
                a = run_10k.build_guardrail_assessment(guardrail)
                cat = str(a.get("category") or "insufficient_evidence")
                conf = float(a.get("confidence") or 0.0)
                probs = dict(a.get("probabilities") or {cat: conf})
            else:
                res = service._calibrated_heuristic(jev_inp, [])
                probs = dict(res.probabilities or {res.category: res.confidence})

            # Normalize across all classes
            full_probs = {c: float(probs.get(c, 0.001)) for c in CLASSES}
            s = sum(full_probs.values())
            probs_by_ref[ref] = {c: v / s for c, v in full_probs.items()}

    return probs_by_ref


def tune_fusion_parameters(
    gbm_probs: np.ndarray,
    llm_probs_list: list[dict[str, float]],
    y_true: np.ndarray,
) -> tuple[float, float, float, float, float]:
    """Grid search weight_gbm and abstain_threshold on holdout split to maximize macro-F1.

    Returns:
        (best_weight, best_thresh, gbm_f1, llm_f1, fused_f1)
    """
    y_true_labels = [CLASSES[idx] for idx in y_true]

    # 1. GBM-only performance
    gbm_preds = [CLASSES[np.argmax(p)] for p in gbm_probs]
    gbm_macro_f1 = float(f1_score(y_true_labels, gbm_preds, average="macro", zero_division=0))

    # 2. LLM-only performance
    llm_preds = [max(p.items(), key=lambda kv: kv[1])[0] for p in llm_probs_list]
    llm_macro_f1 = float(f1_score(y_true_labels, llm_preds, average="macro", zero_division=0))

    logger.info("Holdout baseline: GBM-only macro-F1 = %.4f, LLM-only macro-F1 = %.4f", gbm_macro_f1, llm_macro_f1)

    # Convert gbm_probs to list of dicts
    gbm_probs_dicts = [{CLASSES[j]: float(row[j]) for j in range(len(CLASSES))} for row in gbm_probs]

    weights = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9]
    thresholds = [0.20, 0.25, 0.30, 0.35, 0.40, 0.45, 0.50]

    best_f1 = -1.0
    best_w = 0.5
    best_t = 0.35

    for w in weights:
        for t in thresholds:
            fused_preds = []
            for p_g, p_l in zip(gbm_probs_dicts, llm_probs_list, strict=False):
                blended = blend_log_linear(p_g, p_l, weight_gbm=w, classes=CLASSES)
                pred_c, _ = predict_with_abstention(blended, threshold=t)
                fused_preds.append(pred_c)

            score = float(f1_score(y_true_labels, fused_preds, average="macro", zero_division=0))
            if score > best_f1:
                best_f1 = score
                best_w = w
                best_t = t

    logger.info(
        "Tuned Fusion: best_weight=%.2f, best_threshold=%.2f -> Holdout Fused macro-F1=%.4f (gain over GBM: %+.4f, LLM: %+.4f)",
        best_w,
        best_t,
        best_f1,
        best_f1 - gbm_macro_f1,
        best_f1 - llm_macro_f1,
    )
    return best_w, best_t, gbm_macro_f1, llm_macro_f1, best_f1


def train_e4_hybrid_model(
    corpus_path: Path,
    out_model_path: Path,
    holdout_ratio: float = 0.20,
    seed: int = 20261017,
    max_workers: int = 8,
    limit: int | None = None,
) -> dict[str, Any]:
    """Train HistGradientBoostingClassifier, calibrate on holdout, tune fusion, and save artifact."""
    out_model_path.parent.mkdir(parents=True, exist_ok=True)

    # 1. Build dataset from TRAIN split
    X, y, refs = build_train_dataset(corpus_path, max_workers=max_workers, limit=limit)  # noqa: N806
    n_samples = len(X)
    if n_samples == 0:
        raise ValueError("No train samples extracted!")

    # 2. Stratified train/holdout split
    indices = np.arange(n_samples)
    idx_train, idx_holdout = train_test_split(
        indices,
        test_size=holdout_ratio,
        stratify=y,
        random_state=seed,
    )
    # Guard against sklearn bug when an entire column is NaN
    all_nan = np.isnan(X).all(axis=0)
    if np.any(all_nan):
        X[:, all_nan] = 0.0

    X_fit, y_fit = X[idx_train], y[idx_train]  # noqa: N806
    X_holdout, y_holdout = X[idx_holdout], y[idx_holdout]  # noqa: N806
    holdout_refs_set = {refs[i] for i in idx_holdout}

    # 3. Fit base HistGradientBoostingClassifier with balanced class weights
    logger.info("Fitting HistGradientBoostingClassifier...")
    t0 = time.perf_counter()
    min_leaf = min(20, max(2, len(X_fit) // 10))
    base_clf = HistGradientBoostingClassifier(
        max_iter=150,
        learning_rate=0.10,
        max_leaf_nodes=31,
        min_samples_leaf=min_leaf,
        class_weight="balanced",
        random_state=seed,
    )
    base_clf.fit(X_fit, y_fit)
    logger.info("Fitted base model in %.2fs", time.perf_counter() - t0)

    # 4. Calibrate on holdout part of TRAIN
    logger.info("Calibrating on TRAIN holdout using PredefinedSplit + Isotonic calibration...")
    # Setup PredefinedSplit: -1 for fit fold, 0 for calibration fold
    X_full = np.vstack([X_fit, X_holdout])  # noqa: N806
    y_full = np.concatenate([y_fit, y_holdout])
    test_fold = np.array([-1] * len(X_fit) + [0] * len(X_holdout))
    ps = PredefinedSplit(test_fold)

    calibrated_clf = CalibratedClassifierCV(
        estimator=base_clf,
        cv=ps,
        method="isotonic",
    )
    calibrated_clf.fit(X_full, y_full)
    logger.info("Calibration complete.")

    # 5. Predict calibrated probabilities on holdout
    gbm_holdout_probs = calibrated_clf.predict_proba(X_holdout)

    # 6. Compute holdout heuristic probabilities for fusion tuning
    llm_probs_dict = compute_heuristic_probabilities(corpus_path, holdout_refs_set)
    aligned_llm_probs = [llm_probs_dict.get(refs[idx], {c: 1.0 / len(CLASSES) for c in CLASSES}) for idx in idx_holdout]

    # 7. Tune fusion parameters on holdout
    best_w, best_thresh, gbm_f1, llm_f1, fused_f1 = tune_fusion_parameters(
        gbm_holdout_probs,
        aligned_llm_probs,
        y_holdout,
    )

    # 8. Compute feature importances on holdout
    logger.info("Computing permutation feature importances on holdout...")
    eval_n = min(1000, len(X_holdout))
    perm_res = permutation_importance(
        base_clf,
        X_holdout[:eval_n],
        y_holdout[:eval_n],
        n_repeats=3,
        random_state=seed,
        n_jobs=max_workers,
    )
    importances: list[tuple[str, float]] = []
    for idx, name in enumerate(FEATURE_NAMES):
        importances.append((name, float(perm_res.importances_mean[idx])))
    importances.sort(key=lambda kv: kv[1], reverse=True)

    logger.info("Top 10 Features by Permutation Importance:")
    for rank, (feat, imp) in enumerate(importances[:10], 1):
        logger.info("  %2d. %-35s : %.5f", rank, feat, imp)

    # 9. Save model artifact
    artifact: dict[str, Any] = {
        "model": calibrated_clf,
        "base_model": base_clf,
        "feature_names": FEATURE_NAMES,
        "classes": CLASSES,
        "weight_gbm": best_w,
        "abstain_threshold": best_thresh,
        "feature_importances": importances,
        "metrics_holdout": {
            "gbm_only_macro_f1": round(gbm_f1, 4),
            "llm_only_macro_f1": round(llm_f1, 4),
            "fused_macro_f1": round(fused_f1, 4),
        },
    }

    with out_model_path.open("wb") as f:
        pickle.dump(artifact, f)
    logger.info("Saved model artifact to %s (size: %.2f KB)", out_model_path, out_model_path.stat().st_size / 1024.0)

    return artifact


def main():
    parser = argparse.ArgumentParser(description="Train E4 Hybrid Classifier")
    parser.add_argument("--corpus", type=Path, default=Path("/home/dat/releases_v2/trips.jsonl"), help="Corpus path")
    parser.add_argument(
        "--out-model", type=Path, default=Path("/home/dat/research_v2/E4/model.pkl"), help="Output path"
    )
    parser.add_argument("--holdout-ratio", type=float, default=0.20, help="Train holdout ratio")
    parser.add_argument("--seed", type=int, default=20261017, help="Random seed")
    parser.add_argument("--workers", type=int, default=8, help="Parallel worker count")
    parser.add_argument("--limit", type=int, default=None, help="Optional limit for testing")

    args = parser.parse_args()
    artifact = train_e4_hybrid_model(
        corpus_path=args.corpus,
        out_model_path=args.out_model,
        holdout_ratio=args.holdout_ratio,
        seed=args.seed,
        max_workers=args.workers,
        limit=args.limit,
    )
    print("Training finished successfully.")
    print("Holdout metrics:", artifact["metrics_holdout"])


if __name__ == "__main__":
    main()

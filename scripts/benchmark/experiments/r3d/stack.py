"""Meta-learner stacker training and inference pipeline for Experiment R3D (Issue #554 / Epic #494).

Learns a meta-classifier over R3C clean LightGBM probabilities, R3F trajectory sequence model
probabilities, and disagreement features (absolute differences, entropies).
Compares multinomial logistic regression vs small LightGBM via grouped CV on train OOF predictions.
Reports baseline probability averaging and geometric mean.
Saves chosen meta-learner artifact to /home/dat/research_v2/R3D/stacker.pkl.
"""

from __future__ import annotations

import argparse
import logging
import os
import pickle
import sys
import time
from pathlib import Path
from typing import Any

import lightgbm as lgb
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import f1_score

REPO_ROOT = Path(__file__).resolve().parents[4]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.benchmark.experiments.r3c.train import GBM_CLASSES  # noqa: E402

logger = logging.getLogger(__name__)

DEFAULT_STACKER_PATH = Path("/home/dat/research_v2/R3D/stacker.pkl")
DEFAULT_OOF_PARQUET = Path("/home/dat/research_v2/R3D/oof_train.parquet")
CLASS_TO_IDX = {c: i for i, c in enumerate(GBM_CLASSES)}


def compute_entropy(probs: np.ndarray, eps: float = 1e-12) -> float:
    """Compute Shannon entropy in nats for a 1D probability distribution."""
    p_safe = np.clip(probs, eps, 1.0)
    return float(-np.sum(p_safe * np.log(p_safe)))


def build_stacker_features(
    data: dict[str, list[Any]] | pa.Table,
    llm_probs: dict[str, list[Any]] | None = None,
) -> tuple[np.ndarray, list[str]]:
    """Build feature matrix for meta-learner.

    Features without LLM:
    - 6: r3c_p_<class>
    - 6: r3f_p_<class>
    - 6: diff_p_<class> = abs(r3c_p - r3f_p)
    - 1: r3c_entropy
    - 1: r3f_entropy
    Total: 20 features.

    Phase 2 LLM extensibility:
    If columns named llm_p_<class> are present in data or llm_probs, appends:
    - 6: llm_p_<class>
    - 6: diff_llm_r3c_<class>
    - 6: diff_llm_r3f_<class>
    - 1: llm_entropy
    If absent, LLM features are omitted.
    """
    if isinstance(data, pa.Table):
        col_dict = data.to_pydict()
    else:
        col_dict = dict(data)

    n_samples = len(col_dict.get("trip_ref", []))
    if n_samples == 0:
        # Check first available column length
        for v in col_dict.values():
            if isinstance(v, list):
                n_samples = len(v)
                break

    feature_names: list[str] = []
    # 1. Base probabilities
    for c in GBM_CLASSES:
        feature_names.append(f"r3c_p_{c}")
    for c in GBM_CLASSES:
        feature_names.append(f"r3f_p_{c}")
    for c in GBM_CLASSES:
        feature_names.append(f"diff_p_{c}")
    feature_names.append("r3c_entropy")
    feature_names.append("r3f_entropy")

    # Check for optional LLM probabilities
    has_llm = False
    llm_cols = [f"llm_p_{c}" for c in GBM_CLASSES]
    if all(col in col_dict for col in llm_cols):
        has_llm = True
    elif llm_probs is not None and all(col in llm_probs for col in llm_cols):
        has_llm = True
        for col in llm_cols:
            col_dict[col] = llm_probs[col]

    if has_llm:
        for c in GBM_CLASSES:
            feature_names.append(f"llm_p_{c}")
        for c in GBM_CLASSES:
            feature_names.append(f"diff_llm_r3c_{c}")
        for c in GBM_CLASSES:
            feature_names.append(f"diff_llm_r3f_{c}")
        feature_names.append("llm_entropy")

    feat_matrix = np.zeros((n_samples, len(feature_names)), dtype=float)

    for i in range(n_samples):
        r3c_vec = np.array([float(col_dict[f"r3c_p_{c}"][i]) for c in GBM_CLASSES], dtype=float)
        r3f_vec = np.array([float(col_dict[f"r3f_p_{c}"][i]) for c in GBM_CLASSES], dtype=float)
        diff_vec = np.abs(r3c_vec - r3f_vec)
        r3c_ent = compute_entropy(r3c_vec)
        r3f_ent = compute_entropy(r3f_vec)

        row_vals = list(r3c_vec) + list(r3f_vec) + list(diff_vec) + [r3c_ent, r3f_ent]

        if has_llm:
            llm_vec = np.array([float(col_dict[f"llm_p_{c}"][i]) for c in GBM_CLASSES], dtype=float)
            diff_llm_r3c = np.abs(llm_vec - r3c_vec)
            diff_llm_r3f = np.abs(llm_vec - r3f_vec)
            llm_ent = compute_entropy(llm_vec)
            row_vals += list(llm_vec) + list(diff_llm_r3c) + list(diff_llm_r3f) + [llm_ent]

        feat_matrix[i] = row_vals

    return feat_matrix, feature_names


def baseline_averaging(data: dict[str, list[Any]] | pa.Table) -> np.ndarray:
    """Predict probabilities by simple arithmetic average of R3C and R3F."""
    if isinstance(data, pa.Table):
        col_dict = data.to_pydict()
    else:
        col_dict = dict(data)

    n_samples = len(col_dict.get("trip_ref", []))
    if n_samples == 0:
        for v in col_dict.values():
            if isinstance(v, list):
                n_samples = len(v)
                break

    out = np.zeros((n_samples, len(GBM_CLASSES)), dtype=float)
    for idx, c in enumerate(GBM_CLASSES):
        r3c_c = np.array(col_dict[f"r3c_p_{c}"], dtype=float)
        r3f_c = np.array(col_dict[f"r3f_p_{c}"], dtype=float)
        out[:, idx] = 0.5 * (r3c_c + r3f_c)

    # Normalize rows
    row_sums = out.sum(axis=1, keepdims=True)
    row_sums[row_sums == 0] = 1.0
    return out / row_sums


def baseline_geometric(data: dict[str, list[Any]] | pa.Table) -> np.ndarray:
    """Predict probabilities by normalized geometric mean of R3C and R3F."""
    if isinstance(data, pa.Table):
        col_dict = data.to_pydict()
    else:
        col_dict = dict(data)

    n_samples = len(col_dict.get("trip_ref", []))
    if n_samples == 0:
        for v in col_dict.values():
            if isinstance(v, list):
                n_samples = len(v)
                break

    out = np.zeros((n_samples, len(GBM_CLASSES)), dtype=float)
    for idx, c in enumerate(GBM_CLASSES):
        r3c_c = np.clip(np.array(col_dict[f"r3c_p_{c}"], dtype=float), 1e-9, 1.0)
        r3f_c = np.clip(np.array(col_dict[f"r3f_p_{c}"], dtype=float), 1e-9, 1.0)
        out[:, idx] = np.sqrt(r3c_c * r3f_c)

    # Normalize rows
    row_sums = out.sum(axis=1, keepdims=True)
    row_sums[row_sums == 0] = 1.0
    return out / row_sums


def evaluate_meta_learner_candidates(
    data: dict[str, list[Any]] | pa.Table,
) -> dict[str, Any]:
    """Evaluate candidate meta-learners and baselines across folds."""
    if isinstance(data, pa.Table):
        col_dict = data.to_pydict()
    else:
        col_dict = dict(data)

    labels = col_dict["label"]
    y_true = np.array([CLASS_TO_IDX[lbl] for lbl in labels], dtype=int)
    folds = np.array(col_dict.get("fold", [0] * len(y_true)), dtype=int)
    unique_folds = np.unique(folds)

    feat_matrix, feat_names = build_stacker_features(col_dict)

    # 1. Baseline: Simple probability averaging
    p_avg = baseline_averaging(col_dict)
    y_pred_avg = np.argmax(p_avg, axis=1)
    macro_f1_avg = float(f1_score(y_true, y_pred_avg, average="macro", zero_division=0))

    # 2. Baseline: Geometric mean
    p_geom = baseline_geometric(col_dict)
    y_pred_geom = np.argmax(p_geom, axis=1)
    macro_f1_geom = float(f1_score(y_true, y_pred_geom, average="macro", zero_division=0))

    # 3. Multinomial Logistic Regression
    lr_oof_preds = np.zeros(len(y_true), dtype=int)
    lr_oof_probs = np.zeros((len(y_true), len(GBM_CLASSES)), dtype=float)

    # 4. Small LightGBM
    lgb_oof_preds = np.zeros(len(y_true), dtype=int)
    lgb_oof_probs = np.zeros((len(y_true), len(GBM_CLASSES)), dtype=float)

    for f_idx in unique_folds:
        val_mask = folds == f_idx
        tr_mask = ~val_mask

        x_tr, y_tr = feat_matrix[tr_mask], y_true[tr_mask]
        x_val = feat_matrix[val_mask]

        if len(x_tr) == 0 or len(x_val) == 0 or len(np.unique(y_tr)) <= 1:
            x_tr, y_tr = feat_matrix, y_true
            x_val = feat_matrix[val_mask]

        # Fit Logistic Regression
        clf_lr = LogisticRegression(
            solver="lbfgs",
            max_iter=1000,
            class_weight="balanced",
            C=5.0,
            random_state=42,
        )
        clf_lr.fit(x_tr, y_tr)
        p_val_lr = clf_lr.predict_proba(x_val)
        lr_oof_probs[val_mask] = p_val_lr
        lr_oof_preds[val_mask] = np.argmax(p_val_lr, axis=1)

        # Fit LightGBM
        clf_lgb = lgb.LGBMClassifier(
            objective="multiclass",
            num_class=len(GBM_CLASSES),
            class_weight="balanced",
            max_depth=3,
            num_leaves=7,
            n_estimators=100,
            learning_rate=0.1,
            subsample=0.8,
            colsample_bytree=0.8,
            random_state=42,
            n_jobs=-1,
            verbose=-1,
        )
        clf_lgb.fit(x_tr, y_tr)
        p_val_lgb = clf_lgb.predict_proba(x_val)
        lgb_oof_probs[val_mask] = p_val_lgb
        lgb_oof_preds[val_mask] = np.argmax(p_val_lgb, axis=1)

    macro_f1_lr = float(f1_score(y_true, lr_oof_preds, average="macro", zero_division=0))
    macro_f1_lgb = float(f1_score(y_true, lgb_oof_preds, average="macro", zero_division=0))

    logger.info("CV Macro-F1 Results across %d folds:", len(unique_folds))
    logger.info("  Baseline Averaging:      %.4f", macro_f1_avg)
    logger.info("  Baseline Geometric Mean:  %.4f", macro_f1_geom)
    logger.info("  Logistic Regression:     %.4f", macro_f1_lr)
    logger.info("  LightGBM:                %.4f", macro_f1_lgb)

    # Pick best meta-learner between Logistic Regression and LightGBM
    best_model = "logistic_regression" if macro_f1_lr >= macro_f1_lgb else "lightgbm"
    best_macro_f1 = max(macro_f1_lr, macro_f1_lgb)

    return {
        "baseline_averaging": {"macro_f1": macro_f1_avg},
        "baseline_geometric": {"macro_f1": macro_f1_geom},
        "logistic_regression": {"macro_f1": macro_f1_lr},
        "lightgbm": {"macro_f1": macro_f1_lgb},
        "best_model": best_model,
        "best_macro_f1": best_macro_f1,
        "feature_names": feat_names,
    }


def fit_meta_learner(
    data: dict[str, list[Any]] | pa.Table,
    model_type: str = "logistic_regression",
    output_path: Path | str | None = None,
) -> dict[str, Any]:
    """Fit chosen meta-learner on all training OOF data and serialize artifact."""
    out_path = Path(output_path) if output_path else DEFAULT_STACKER_PATH
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if isinstance(data, pa.Table):
        col_dict = data.to_pydict()
    else:
        col_dict = dict(data)

    labels = col_dict["label"]
    y_true = np.array([CLASS_TO_IDX[lbl] for lbl in labels], dtype=int)
    x_features, feat_names = build_stacker_features(col_dict)

    if model_type == "logistic_regression":
        model = LogisticRegression(
            solver="lbfgs",
            max_iter=1000,
            class_weight="balanced",
            C=5.0,
            random_state=42,
        )
    elif model_type == "lightgbm":
        model = lgb.LGBMClassifier(
            objective="multiclass",
            num_class=len(GBM_CLASSES),
            class_weight="balanced",
            max_depth=3,
            num_leaves=7,
            n_estimators=100,
            learning_rate=0.1,
            subsample=0.8,
            colsample_bytree=0.8,
            random_state=42,
            n_jobs=-1,
            verbose=-1,
        )
    else:
        raise ValueError(f"Unknown meta-learner model type: {model_type}")

    model.fit(x_features, y_true)

    artifact = {
        "model": model,
        "model_type": model_type,
        "classes": GBM_CLASSES,
        "class_to_idx": CLASS_TO_IDX,
        "feature_names": feat_names,
        "trained_samples": len(x_features),
        "timestamp": time.time(),
    }

    with out_path.open("wb") as f:
        pickle.dump(artifact, f)

    logger.info("Saved trained %s meta-learner artifact to %s", model_type, out_path)
    return artifact


def load_stacker_artifact(artifact_path: Path | str | None = None) -> dict[str, Any] | None:
    """Load meta-learner artifact from R3D_STACKER_PATH or default location."""
    env_path = os.environ.get("R3D_STACKER_PATH")
    path = Path(env_path) if env_path else (Path(artifact_path) if artifact_path else DEFAULT_STACKER_PATH)

    if path.exists():
        try:
            with path.open("rb") as f:
                return pickle.load(f)
        except Exception as e:
            logger.warning("Failed to load stacker artifact from %s: %s", path, e)
    return None


def predict_stacker_probabilities(
    r3c_probs: dict[str, float],
    r3f_probs: dict[str, float],
    artifact: dict[str, Any] | None = None,
    llm_probs: dict[str, float] | None = None,
) -> dict[str, float]:
    """Predict calibrated probabilities across GBM_CLASSES using stacker or averaging fallback."""
    if artifact is not None and "model" in artifact:
        model = artifact["model"]

        # Build single-row feature dict
        sample_dict: dict[str, list[Any]] = {"trip_ref": ["infer_0"]}
        for c in GBM_CLASSES:
            sample_dict[f"r3c_p_{c}"] = [float(r3c_probs.get(c, 0.0))]
            sample_dict[f"r3f_p_{c}"] = [float(r3f_probs.get(c, 0.0))]

        llm_input = None
        if llm_probs is not None:
            llm_input = {f"llm_p_{c}": [float(llm_probs.get(c, 0.0))] for c in GBM_CLASSES}

        try:
            x_sample, _ = build_stacker_features(sample_dict, llm_probs=llm_input)
            probs = model.predict_proba(x_sample)[0]
            classes = artifact.get("classes", GBM_CLASSES)
            out = {classes[i]: float(probs[i]) for i in range(len(classes))}
            s = sum(out.values())
            if s > 0:
                return {c: v / s for c, v in out.items()}
        except Exception as e:
            logger.debug("Stacker predict failed: %s; falling back to probability average", e)

    # Fallback to probability averaging
    out = {}
    for c in GBM_CLASSES:
        p_c = 0.5 * (float(r3c_probs.get(c, 0.0)) + float(r3f_probs.get(c, 0.0)))
        out[c] = p_c

    s = sum(out.values())
    if s > 0:
        return {c: v / s for c, v in out.items()}
    u = 1.0 / len(GBM_CLASSES)
    return {c: u for c in GBM_CLASSES}


def main() -> None:
    parser = argparse.ArgumentParser(description="Train and evaluate R3D meta-learner stacker.")
    parser.add_argument("--oof-parquet", type=Path, default=DEFAULT_OOF_PARQUET)
    parser.add_argument("--out-artifact", type=Path, default=DEFAULT_STACKER_PATH)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    if not args.oof_parquet.exists():
        logger.error("OOF parquet not found at %s. Run oof.py first.", args.oof_parquet)
        sys.exit(1)

    table = pq.read_table(args.oof_parquet)
    logger.info("Loaded %d OOF rows from %s", table.num_rows, args.oof_parquet)

    cv_results = evaluate_meta_learner_candidates(table)
    print("\n" + "=" * 50)
    print("R3D Stacker CV Evaluation Summary:")
    print(f"  Baseline Averaging Macro-F1:       {cv_results['baseline_averaging']['macro_f1']:.4f}")
    print(f"  Baseline Geometric Mean Macro-F1:  {cv_results['baseline_geometric']['macro_f1']:.4f}")
    print(f"  Multinomial Logistic Reg Macro-F1: {cv_results['logistic_regression']['macro_f1']:.4f}")
    print(f"  Small LightGBM Macro-F1:           {cv_results['lightgbm']['macro_f1']:.4f}")
    print(f"  --> Selected Model:                {cv_results['best_model']}")
    print("=" * 50 + "\n")

    fit_meta_learner(table, model_type=cv_results["best_model"], output_path=args.out_artifact)
    logger.info("Successfully trained and saved stacker to %s", args.out_artifact)


if __name__ == "__main__":
    main()

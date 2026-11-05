"""Out-Of-Fold (OOF) prediction pipeline for Experiment R3D (Issue #554 / Epic #494).

Generates 5-fold cross-validated out-of-fold predictions on the train split for base models:
1. R3C clean LightGBM
2. R3F 1D-CNN trajectory sequence classifier

Trips are partitioned strictly by driver_id group so that no driver appears in both train
and validation sets of any fold. Insufficient_evidence is excluded because it is resolved
purely by guardrail short-circuit outside the base models.

Caches OOF predictions to /home/dat/research_v2/R3D/oof_train.parquet.
"""

from __future__ import annotations

import argparse
import json
import logging
import random
import sys
import tempfile
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
from sklearn.model_selection import StratifiedGroupKFold

REPO_ROOT = Path(__file__).resolve().parents[4]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.benchmark import run_10k  # noqa: E402
from scripts.benchmark.driver_ledger import driver_split  # noqa: E402
from scripts.benchmark.experiments.r3c.train import (  # noqa: E402
    GBM_CLASSES,
    fit_gbm_classifier,
)
from src.services.fraud_classifier.features_sequence import (  # noqa: E402
    MODEL_CLASSES,
    NUM_CHANNELS,
    NUM_STATIC_FEATURES,
    NUM_STEPS,
)
from src.services.fraud_classifier.features_tabular import extract_features  # noqa: E402

logger = logging.getLogger(__name__)

DEFAULT_OOF_PARQUET = Path("/home/dat/research_v2/R3D/oof_train.parquet")
CLASS_TO_IDX = {c: i for i, c in enumerate(GBM_CLASSES)}


def create_grouped_folds(
    driver_ids: list[str],
    labels: list[str],
    n_splits: int = 5,
    seed: int = 42,
) -> list[int]:
    """Assign fold index [0..n_splits-1] ensuring disjoint driver_id sets across folds."""
    sgkf = StratifiedGroupKFold(n_splits=n_splits, shuffle=True, random_state=seed)
    folds = np.zeros(len(driver_ids), dtype=int)
    x_dummy = np.zeros(len(driver_ids))

    for fold_idx, (_, val_idx) in enumerate(sgkf.split(x_dummy, labels, groups=driver_ids)):
        folds[val_idx] = fold_idx

    return folds.tolist()


def save_oof_parquet(data: pa.Table | dict[str, list[Any]], output_path: Path | str) -> Path:
    """Save OOF predictions to parquet format."""
    out_path = Path(output_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if isinstance(data, dict):
        table = pa.Table.from_pydict(data)
    else:
        table = data

    pq.write_table(table, out_path)
    logger.info("Saved OOF predictions table (%d rows) to %s", table.num_rows, out_path)
    return out_path


def load_oof_parquet(parquet_path: Path | str) -> pa.Table:
    """Load cached OOF parquet file."""
    path = Path(parquet_path)
    if not path.exists():
        raise FileNotFoundError(f"OOF parquet file not found at {path}")
    return pq.read_table(path)


def load_train_bundles_for_oof(
    corpus_path: Path,
    max_no_violation: int = 7300,
    seed: int = 20261017,
) -> tuple[list[dict[str, Any]], list[str], list[str], list[str]]:
    """Load train split bundles keeping all non-short-circuited minority trips and sampled no_violation.

    Returns:
        (bundles, driver_ids, labels, trip_refs)
    """
    logger.info("Scanning train split from %s...", corpus_path)
    rng = random.Random(seed)
    by_class: dict[str, list[dict[str, Any]]] = defaultdict(list)

    with corpus_path.open("r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            b = json.loads(line)
            split = b.get("split")
            if not split:
                drv_id = str(b.get("driver_id") or b.get("trip_ref") or "unknown")
                split = driver_split(drv_id)

            if split != "train":
                continue

            # Skip guardrail short-circuited trips and insufficient_evidence
            label = str(b.get("label") or "no_violation")
            if label == "insufficient_evidence" or label not in GBM_CLASSES:
                continue

            _, points, _ = run_10k.bundle_to_input(b)
            incident = b.get("platform_incident")
            incidents = [incident] if isinstance(incident, dict) else []
            guardrail = run_10k.evaluate_telemetry_window(points, incidents)
            if run_10k.should_short_circuit(guardrail):
                continue

            by_class[label].append(b)

    logger.info("Found eligible train bundles by class:")
    for c in GBM_CLASSES:
        logger.info("  %s: %d", c, len(by_class[c]))

    selected_bundles: list[dict[str, Any]] = []
    selected_drivers: list[str] = []
    selected_labels: list[str] = []
    selected_refs: list[str] = []

    for c in GBM_CLASSES:
        grp = by_class[c]
        if c == "no_violation" and len(grp) > max_no_violation:
            rng.shuffle(grp)
            grp = grp[:max_no_violation]

        for b in grp:
            selected_bundles.append(b)
            drv = str(b.get("driver_id") or b.get("trip_ref") or "unknown_driver")
            selected_drivers.append(drv)
            selected_labels.append(c)
            selected_refs.append(str(b.get("trip_ref") or ""))

    logger.info(
        "Loaded total %d bundles for OOF generation (%d distinct drivers)",
        len(selected_bundles),
        len(set(selected_drivers)),
    )
    return selected_bundles, selected_drivers, selected_labels, selected_refs


def train_and_eval_r3f_fold(
    train_bundles: list[dict[str, Any]],
    train_labels: list[int],
    val_bundles: list[dict[str, Any]],
    epochs: int = 6,
    batch_size: int = 128,
    lr: float = 1e-3,
    device: str = "cpu",
    seed: int = 42,
) -> np.ndarray:
    """Train R3F sequence model on fold train set and return predicted val probabilities."""
    import torch
    import torch.nn as nn
    from torch.utils.data import DataLoader

    from scripts.benchmark.experiments.r3f.model import R3FTrajectoryClassifier
    from scripts.benchmark.experiments.r3f.train import (
        R3FTorchDataset,
        compute_class_weights,
    )

    torch.manual_seed(seed)
    np.random.seed(seed)

    train_ds = R3FTorchDataset(train_bundles, train_labels, augment=True)
    val_ds = R3FTorchDataset(val_bundles, [0] * len(val_bundles), augment=False)

    train_loader = DataLoader(train_ds, batch_size=batch_size, shuffle=True)
    val_loader = DataLoader(val_ds, batch_size=batch_size, shuffle=False)

    class_weights = compute_class_weights(train_labels, num_classes=len(MODEL_CLASSES)).to(device)
    model = R3FTrajectoryClassifier(
        in_channels=NUM_CHANNELS,
        static_dim=NUM_STATIC_FEATURES,
        num_classes=len(MODEL_CLASSES),
        num_steps=NUM_STEPS,
    ).to(device)

    criterion = nn.CrossEntropyLoss(weight=class_weights)
    optimizer = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=1e-4)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=epochs, eta_min=1e-5)

    for epoch in range(1, epochs + 1):
        model.train()
        for x_seq, x_static, y in train_loader:
            x_seq = x_seq.to(device)
            x_static = x_static.to(device)
            y = y.to(device)

            optimizer.zero_grad()
            logits = model(x_seq, x_static)
            loss = criterion(logits, y)
            loss.backward()
            nn.utils.clip_grad_norm_(model.parameters(), max_norm=2.0)
            optimizer.step()
        scheduler.step()

    # Predict val probabilities
    model.eval()
    val_probs: list[np.ndarray] = []
    with torch.no_grad():
        for x_seq, x_static, _ in val_loader:
            x_seq = x_seq.to(device)
            x_static = x_static.to(device)
            probs = model.predict_probabilities(x_seq, x_static)
            val_probs.append(probs.cpu().numpy())

    if val_probs:
        return np.vstack(val_probs)
    return np.empty((0, len(MODEL_CLASSES)))


def generate_oof_predictions(
    corpus_path: Path,
    output_path: Path | None = None,
    n_splits: int = 5,
    max_no_violation: int = 7300,
    r3f_epochs: int = 6,
    seed: int = 20261017,
) -> pa.Table:
    """Run full 5-fold grouped OOF generation for R3C and R3F."""
    out_path = Path(output_path) if output_path else DEFAULT_OOF_PARQUET
    t0 = time.perf_counter()

    bundles, driver_ids, labels, refs = load_train_bundles_for_oof(
        corpus_path=corpus_path,
        max_no_violation=max_no_violation,
        seed=seed,
    )

    n_samples = len(bundles)
    if n_samples == 0:
        raise ValueError("No eligible train bundles found for OOF generation.")

    folds = np.array(create_grouped_folds(driver_ids, labels, n_splits=n_splits, seed=seed))

    # Pre-extract R3C features
    logger.info("Pre-extracting R3C features for %d samples...", n_samples)
    r3c_features = []
    for b in bundles:
        _, feat = extract_features(b)
        r3c_features.append(feat)
    x_r3c_all = np.array(r3c_features, dtype=float)
    x_r3c_all = np.nan_to_num(x_r3c_all, nan=-999.0, posinf=-999.0, neginf=-999.0)

    label_indices = np.array([CLASS_TO_IDX[lbl] for lbl in labels], dtype=int)

    # Prepare OOF storage arrays
    r3c_oof_probs = np.zeros((n_samples, len(GBM_CLASSES)), dtype=float)
    r3f_oof_probs = np.zeros((n_samples, len(MODEL_CLASSES)), dtype=float)

    for fold_idx in range(n_splits):
        logger.info("=== Running Fold %d/%d ===", fold_idx + 1, n_splits)
        val_mask = folds == fold_idx
        tr_mask = ~val_mask

        val_indices = np.where(val_mask)[0]
        tr_indices = np.where(tr_mask)[0]

        logger.info("Fold %d: %d train samples, %d val samples", fold_idx + 1, len(tr_indices), len(val_indices))

        # 1. Train R3C LightGBM on fold
        t_r3c_0 = time.perf_counter()
        tmp_model_path = Path(tempfile.gettempdir()) / f"r3c_fold_{fold_idx}_{seed}.pkl"
        r3c_art = fit_gbm_classifier(
            x_r3c_all[tr_indices],
            [labels[i] for i in tr_indices],
            output_path=tmp_model_path,
            n_estimators=200,
            learning_rate=0.05,
            random_state=seed + fold_idx,
        )
        r3c_val_p = r3c_art["model"].predict_proba(x_r3c_all[val_indices])
        r3c_oof_probs[val_indices] = r3c_val_p
        logger.info("Fold %d R3C trained & evaluated in %.1fs", fold_idx + 1, time.perf_counter() - t_r3c_0)

        # 2. Train R3F 1D-CNN on fold
        t_r3f_0 = time.perf_counter()
        tr_bundles = [bundles[i] for i in tr_indices]
        tr_y = [label_indices[i] for i in tr_indices]
        val_bundles = [bundles[i] for i in val_indices]

        r3f_val_p = train_and_eval_r3f_fold(
            train_bundles=tr_bundles,
            train_labels=tr_y,
            val_bundles=val_bundles,
            epochs=r3f_epochs,
            batch_size=128,
            seed=seed + fold_idx,
        )
        r3f_oof_probs[val_indices] = r3f_val_p
        logger.info("Fold %d R3F trained & evaluated in %.1fs", fold_idx + 1, time.perf_counter() - t_r3f_0)

    # Assemble parquet table
    out_dict: dict[str, list[Any]] = {
        "trip_ref": refs,
        "driver_id": driver_ids,
        "label": labels,
        "fold": folds.tolist(),
    }
    for idx, c in enumerate(GBM_CLASSES):
        out_dict[f"r3c_p_{c}"] = r3c_oof_probs[:, idx].tolist()
        out_dict[f"r3f_p_{c}"] = r3f_oof_probs[:, idx].tolist()

    table = pa.Table.from_pydict(out_dict)
    save_oof_parquet(table, out_path)

    total_time = time.perf_counter() - t0
    logger.info("OOF generation complete in %.1fs. Cached to %s", total_time, out_path)
    return table


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate OOF predictions for R3C and R3F models.")
    parser.add_argument("--corpus", type=Path, default=Path("/home/dat/releases_v2_1/trips.jsonl"))
    parser.add_argument("--out-parquet", type=Path, default=DEFAULT_OOF_PARQUET)
    parser.add_argument("--max-no-violation", type=int, default=7300)
    parser.add_argument("--r3f-epochs", type=int, default=6)
    parser.add_argument("--seed", type=int, default=20261017)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    generate_oof_predictions(
        corpus_path=args.corpus,
        output_path=args.out_parquet,
        max_no_violation=args.max_no_violation,
        r3f_epochs=args.r3f_epochs,
        seed=args.seed,
    )


if __name__ == "__main__":
    main()

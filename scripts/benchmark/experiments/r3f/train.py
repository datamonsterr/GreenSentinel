"""Training pipeline for R3F trajectory sequence model with domain randomisation."""

from __future__ import annotations

import argparse
import json
import logging
import os
import random
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import numpy as np
from sklearn.metrics import f1_score
from sklearn.model_selection import train_test_split

try:
    import torch
    import torch.nn as nn
    from torch.utils.data import DataLoader, Dataset

    _HAS_TORCH = True
    _DatasetBase = Dataset
except ImportError:
    torch = None  # type: ignore[assignment]
    nn = None  # type: ignore[assignment]
    DataLoader = None  # type: ignore[assignment,misc]
    Dataset = None  # type: ignore[assignment,misc]
    _HAS_TORCH = False
    _DatasetBase = object  # type: ignore[misc,assignment]

REPO_ROOT = Path(__file__).resolve().parents[4]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.benchmark import run_10k  # noqa: E402
from scripts.benchmark.driver_ledger import driver_split  # noqa: E402
from scripts.benchmark.experiments.r3f.model import (  # noqa: E402
    R3FTrajectoryClassifier,
    save_r3f_model,
)
from src.services.fraud_classifier.features_sequence import (  # noqa: E402
    MODEL_CLASSES,
    NUM_CHANNELS,
    NUM_STATIC_FEATURES,
    NUM_STEPS,
    extract_r3f_features,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

CLASS_TO_IDX = {c: i for i, c in enumerate(MODEL_CLASSES)}


class R3FTorchDataset(_DatasetBase):
    """PyTorch Dataset extracting on-the-fly augmented features from bundles."""

    def __init__(self, bundles: list[dict[str, Any]], labels: list[int], augment: bool = True):
        if not _HAS_TORCH:
            raise ImportError("torch is required to instantiate R3FTorchDataset")
        self.bundles = bundles
        self.labels = labels
        self.augment = augment

    def __len__(self) -> int:
        return len(self.bundles)

    def __getitem__(self, idx: int) -> tuple[Any, Any, int]:
        import torch

        bundle = self.bundles[idx]
        seq, static = extract_r3f_features(bundle, augment=self.augment, num_steps=NUM_STEPS)
        return torch.from_numpy(seq), torch.from_numpy(static), self.labels[idx]


def compute_class_weights(labels: list[int], num_classes: int) -> Any:
    """Compute smoothed inverse-frequency class weights for CrossEntropyLoss."""
    import torch

    counts = Counter(labels)
    total = len(labels)
    weights = []
    for c in range(num_classes):
        cnt = counts.get(c, 0)
        if cnt > 0:
            # Square-root smoothed inverse frequency prevents majority starvation
            w = (total / (num_classes * cnt)) ** 0.5
        else:
            w = 1.0
        weights.append(w)
    weights_tensor = torch.tensor(weights, dtype=torch.float32)
    return weights_tensor / weights_tensor.mean()


def load_stratified_train_bundles(
    corpus_path: Path,
    max_no_violation: int = 14000,
    seed: int = 20261017,
) -> tuple[list[dict[str, Any]], list[int], list[str]]:
    """Load train split keeping ALL non-short-circuited minority trips and a realistic sample of no_violation."""
    logger.info("Reading train split from %s...", corpus_path)
    rng = random.Random(seed)

    by_class: dict[str, list[dict[str, Any]]] = defaultdict(list)
    total_lines = 0

    with corpus_path.open("r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            total_lines += 1
            b = json.loads(line)
            split = b.get("split")
            if not split:
                drv_id = str(b.get("driver_id") or b.get("trip_ref") or "unknown")
                split = driver_split(drv_id)

            if split != "train":
                continue

            # Skip guardrail short-circuited trips (insufficient_evidence)
            _, points, _ = run_10k.bundle_to_input(b)
            incident = b.get("platform_incident")
            incidents = [incident] if isinstance(incident, dict) else []
            guardrail = run_10k.evaluate_telemetry_window(points, incidents)
            if run_10k.should_short_circuit(guardrail):
                continue

            lbl = str(b.get("label") or "no_violation")
            if lbl in CLASS_TO_IDX:
                by_class[lbl].append(b)

    logger.info("Scanned %d lines. Found non-short-circuit train class counts:", total_lines)
    for c in MODEL_CLASSES:
        logger.info("  %s: %d", c, len(by_class[c]))

    selected_bundles: list[dict[str, Any]] = []
    selected_labels: list[int] = []
    selected_refs: list[str] = []

    for c in MODEL_CLASSES:
        grp = by_class[c]
        if c == "no_violation" and len(grp) > max_no_violation:
            rng.shuffle(grp)
            grp = grp[:max_no_violation]
        for b in grp:
            selected_bundles.append(b)
            selected_labels.append(CLASS_TO_IDX[c])
            selected_refs.append(str(b.get("trip_ref") or ""))

    logger.info("Selected total %d training samples across %d classes.", len(selected_bundles), len(MODEL_CLASSES))
    return selected_bundles, selected_labels, selected_refs


def evaluate_dataset(
    model: R3FTrajectoryClassifier,
    dataloader: DataLoader,
    device: str = "cpu",
) -> tuple[float, float, dict[str, float]]:
    """Evaluate model on a dataset, returning loss, macro-F1, and per-class F1."""
    model.eval()
    criterion = nn.CrossEntropyLoss()
    total_loss = 0.0
    all_preds: list[int] = []
    all_targets: list[int] = []

    with torch.no_grad():
        for x_seq, x_static, y in dataloader:
            x_seq = x_seq.to(device)
            x_static = x_static.to(device)
            y = y.to(device)

            logits = model(x_seq, x_static)
            loss = criterion(logits, y)
            total_loss += loss.item() * len(y)

            preds = torch.argmax(logits, dim=-1)
            all_preds.extend(preds.cpu().tolist())
            all_targets.extend(y.cpu().tolist())

    n = max(1, len(all_targets))
    mean_loss = total_loss / n
    macro_f1 = float(f1_score(all_targets, all_preds, average="macro", zero_division=0))

    per_class_scores = f1_score(all_targets, all_preds, average=None, zero_division=0)
    per_class_f1 = {MODEL_CLASSES[i]: float(per_class_scores[i]) for i in range(len(MODEL_CLASSES))}

    return mean_loss, macro_f1, per_class_f1


def train_r3f_model(
    corpus_path: Path,
    out_model_path: Path,
    epochs: int = 15,
    batch_size: int = 128,
    lr: float = 1e-3,
    val_ratio: float = 0.15,
    max_no_violation: int = 14000,
    patience: int = 4,
    seed: int = 20261017,
    device: str = "cpu",
) -> dict[str, Any]:
    """Train R3F sequence classifier with early stopping and domain randomisation."""
    torch.manual_seed(seed)
    np.random.seed(seed)
    random.seed(seed)

    t_start = time.perf_counter()

    # 1. Load stratified bundles
    bundles, labels, refs = load_stratified_train_bundles(
        corpus_path,
        max_no_violation=max_no_violation,
        seed=seed,
    )

    if not bundles:
        raise ValueError(f"No train bundles found in {corpus_path}")

    # 2. Stratified train/val split
    indices = np.arange(len(bundles))
    idx_train, idx_val = train_test_split(
        indices,
        test_size=val_ratio,
        stratify=labels,
        random_state=seed,
    )

    train_bundles = [bundles[i] for i in idx_train]
    train_labels = [labels[i] for i in idx_train]
    val_bundles = [bundles[i] for i in idx_val]
    val_labels = [labels[i] for i in idx_val]

    logger.info("Split: %d train trips, %d internal val trips.", len(train_bundles), len(val_bundles))

    # 3. Setup Datasets & DataLoaders
    train_dataset = R3FTorchDataset(train_bundles, train_labels, augment=True)
    val_dataset = R3FTorchDataset(val_bundles, val_labels, augment=False)

    train_loader = DataLoader(train_dataset, batch_size=batch_size, shuffle=True, drop_last=False)
    val_loader = DataLoader(val_dataset, batch_size=batch_size, shuffle=False)

    # 4. Initialize model & class-weighted loss
    class_weights = compute_class_weights(train_labels, num_classes=len(MODEL_CLASSES)).to(device)
    logger.info(
        "Class weights: %s", {MODEL_CLASSES[i]: round(class_weights[i].item(), 3) for i in range(len(MODEL_CLASSES))}
    )

    model = R3FTrajectoryClassifier(
        in_channels=NUM_CHANNELS,
        static_dim=NUM_STATIC_FEATURES,
        num_classes=len(MODEL_CLASSES),
        num_steps=NUM_STEPS,
    ).to(device)

    criterion = nn.CrossEntropyLoss(weight=class_weights)
    optimizer = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=1e-4)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=epochs, eta_min=1e-5)

    best_val_macro_f1 = -1.0
    best_epoch = 0
    patience_counter = 0
    epochs_trained = 0

    for epoch in range(1, epochs + 1):
        epochs_trained = epoch
        model.train()
        epoch_loss = 0.0
        n_batches = 0
        t_epoch0 = time.perf_counter()

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

            epoch_loss += loss.item()
            n_batches += 1

        scheduler.step()
        train_loss = epoch_loss / max(1, n_batches)
        val_loss, val_macro_f1, val_per_class = evaluate_dataset(model, val_loader, device=device)
        epoch_time = time.perf_counter() - t_epoch0

        logger.info(
            "Epoch %d/%d (%.1fs) - Train Loss: %.4f, Val Loss: %.4f, Val Macro-F1: %.4f",
            epoch,
            epochs,
            epoch_time,
            train_loss,
            val_loss,
            val_macro_f1,
        )

        if val_macro_f1 > best_val_macro_f1:
            best_val_macro_f1 = val_macro_f1
            best_epoch = epoch
            patience_counter = 0
            # Save checkpoint
            save_r3f_model(
                model,
                out_model_path,
                metadata={
                    "classes": MODEL_CLASSES,
                    "val_macro_f1": val_macro_f1,
                    "val_per_class_f1": val_per_class,
                    "epoch": epoch,
                    "num_steps": NUM_STEPS,
                },
            )
            logger.info("Saved new best model checkpoint to %s (Val Macro-F1: %.4f)", out_model_path, val_macro_f1)
        else:
            patience_counter += 1
            if patience_counter >= patience:
                logger.info("Early stopping triggered at epoch %d (best epoch was %d)", epoch, best_epoch)
                break

    train_time_s = time.perf_counter() - t_start
    logger.info(
        "Training complete in %.2fs. Best Val Macro-F1: %.4f at epoch %d", train_time_s, best_val_macro_f1, best_epoch
    )

    return {
        "best_val_macro_f1": best_val_macro_f1,
        "best_epoch": best_epoch,
        "epochs_trained": epochs_trained,
        "train_time_s": train_time_s,
        "model_path": str(out_model_path),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Train R3F trajectory sequence classifier.")
    parser.add_argument("--corpus", type=str, default="/home/dat/releases_v2_1/trips.jsonl", help="Path to trips.jsonl")
    parser.add_argument(
        "--out-model",
        type=str,
        default=os.getenv("R3F_MODEL_PATH", "/home/dat/research_v2/R3F/model.pt"),
        help="Path to save trained model.pt",
    )
    parser.add_argument("--epochs", type=int, default=15, help="Number of training epochs")
    parser.add_argument("--batch-size", type=int, default=128, help="Batch size")
    parser.add_argument("--lr", type=float, default=1e-3, help="Learning rate")
    parser.add_argument("--val-ratio", type=float, default=0.15, help="Validation ratio for internal fold")
    parser.add_argument("--max-no-violation", type=int, default=14000, help="Max no_violation train samples")
    parser.add_argument("--patience", type=int, default=4, help="Early stopping patience")
    parser.add_argument("--seed", type=int, default=20261017, help="Random seed")
    args = parser.parse_args()

    train_r3f_model(
        corpus_path=Path(args.corpus),
        out_model_path=Path(args.out_model),
        epochs=args.epochs,
        batch_size=args.batch_size,
        lr=args.lr,
        val_ratio=args.val_ratio,
        max_no_violation=args.max_no_violation,
        patience=args.patience,
        seed=args.seed,
    )


if __name__ == "__main__":
    main()

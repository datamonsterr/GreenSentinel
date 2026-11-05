#!/usr/bin/env python3
"""Export research artifacts (R3C, R3F, R3D) into production formats and generate manifest.

Converts:
- R3F (PyTorch 1D-CNN) -> ONNX format (opset 17, dynamic batch axis)
- R3C (LightGBM) -> Native text model (booster.save_model)
- R3D Stacker (LightGBM) -> Native text model (booster.save_model)

Enforces dev300 parity gate:
- Identical predicted category 300/300
- Max absolute probability difference <= 1e-4
Aborts without writing manifest on gate failure.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import pickle
import sys
from pathlib import Path
from typing import Any

import lightgbm as lgb
import numpy as np
import onnxruntime as ort

try:
    import torch
    import torch.nn as nn

    _HAS_TORCH = True
    _ModuleBase = nn.Module
except ImportError:
    torch = None  # type: ignore[assignment]
    nn = None  # type: ignore[assignment]
    _HAS_TORCH = False
    _ModuleBase = object  # type: ignore[misc,assignment]

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.benchmark.experiments.r3c.train import BENCHMARK_7_CLASSES, GBM_CLASSES  # noqa: E402
from scripts.benchmark.experiments.r3d.stack import compute_entropy  # noqa: E402
from scripts.benchmark.experiments.r3f.model import load_r3f_model  # noqa: E402
from src.services.fraud_classifier.features_sequence import (  # noqa: E402
    MODEL_CLASSES,
    NUM_CHANNELS,
    NUM_STATIC_FEATURES,
    NUM_STEPS,
    extract_r3f_features,
)
from src.services.fraud_classifier.features_tabular import FEATURE_NAMES, extract_features  # noqa: E402
from src.services.fraud_classifier.guardrail import evaluate_bundle_guardrail, normalise_bundle  # noqa: E402

logger = logging.getLogger(__name__)

DEFAULT_R3C_PATH = Path("/home/dat/research_v2/R3C/model.pkl")
DEFAULT_R3F_PATH = Path("/home/dat/research_v2/R3F/model.pt")
DEFAULT_R3D_PATH = Path("/home/dat/research_v2/R3D/stacker.pkl")
DEFAULT_DEV300_PATH = Path("/home/dat/releases_v2_1/dev300.jsonl")
DEFAULT_REF_PRED_PATH = Path("/home/dat/research_v2/FINAL/r3d_dev300_blind/predictions.jsonl")
DEFAULT_OUT_DIR = REPO_ROOT / "models" / "r3d"

CORPUS_SHA256 = "d52e52ff7dd2cc7b6d23631191d1cdbf32d9f1b636f43117ad496809ac0d3fdf"
MODEL_VERSION = "r3d-2026.10.18"

# Portable provenance descriptors. Source paths are CLI inputs only and must never
# be written into the manifest, which is committed and shipped in the container.
SOURCE_RUNS = {
    "r3c": {"experiment": "R3C", "pr": 553, "artifact": "model.pkl"},
    "r3f": {"experiment": "R3F", "pr": 552, "artifact": "model.pt"},
    "r3d": {"experiment": "R3D", "pr": 556, "artifact": "stacker.pkl"},
}


class R3FExportWrapper(_ModuleBase):
    """Wrapper exposing softmax probabilities output for ONNX export."""

    def __init__(self, model: Any):
        super().__init__()
        self.model = model

    def forward(self, x_seq: Any, x_static: Any) -> Any:
        return self.model.predict_probabilities(x_seq, x_static)


def compute_file_sha256(path: Path) -> str:
    """Compute hex SHA256 digest of a file."""
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(1024 * 1024):
            h.update(chunk)
    return h.hexdigest()


def export_r3f_onnx(r3f_ckpt_path: Path, out_onnx_path: Path) -> None:
    """Export R3F PyTorch model checkpoint to ONNX with dynamic batch axis."""
    if not _HAS_TORCH:
        raise ImportError("torch is required to export R3F PyTorch model to ONNX")
    logger.info("Exporting R3F PyTorch model from %s to ONNX %s...", r3f_ckpt_path, out_onnx_path)
    model, _ = load_r3f_model(r3f_ckpt_path, device="cpu")
    model.eval()

    wrapper = R3FExportWrapper(model)
    wrapper.eval()

    dummy_seq = torch.randn(1, NUM_CHANNELS, NUM_STEPS, dtype=torch.float32)
    dummy_static = torch.randn(1, NUM_STATIC_FEATURES, dtype=torch.float32)

    out_onnx_path.parent.mkdir(parents=True, exist_ok=True)
    torch.onnx.export(
        wrapper,
        (dummy_seq, dummy_static),
        str(out_onnx_path),
        input_names=["x_seq", "x_static"],
        output_names=["probabilities"],
        dynamic_axes={
            "x_seq": {0: "batch_size"},
            "x_static": {0: "batch_size"},
            "probabilities": {0: "batch_size"},
        },
        opset_version=17,
        dynamo=False,
    )
    logger.info("R3F ONNX export complete.")


def export_lightgbm_booster(pickle_path: Path, out_text_path: Path) -> None:
    """Load LightGBM classifier from pickle and export native text model."""
    logger.info("Exporting LightGBM booster from %s to %s...", pickle_path, out_text_path)
    with pickle_path.open("rb") as f:
        artifact = pickle.load(f)
    booster = artifact["model"].booster_
    out_text_path.parent.mkdir(parents=True, exist_ok=True)
    booster.save_model(str(out_text_path))
    logger.info("LightGBM booster export complete.")


def run_parity_gate(
    r3c_text_path: Path,
    r3f_onnx_path: Path,
    stacker_text_path: Path,
    dev300_path: Path,
    ref_pred_path: Path,
) -> tuple[int, float]:
    """Verify exported models on dev300 against reference research predictions."""
    logger.info("Executing parity gate against dev300 reference predictions...")

    r3c_booster = lgb.Booster(model_file=str(r3c_text_path))
    ort_sess = ort.InferenceSession(str(r3f_onnx_path), providers=["CPUExecutionProvider"])
    stacker_booster = lgb.Booster(model_file=str(stacker_text_path))

    class_matches = 0
    max_prob_diff = 0.0
    total = 0

    with dev300_path.open() as f_trips, ref_pred_path.open() as f_preds:
        for idx, (trip_line, pred_line) in enumerate(zip(f_trips, f_preds, strict=False)):
            trip = json.loads(trip_line)
            expected = json.loads(pred_line)
            total += 1

            norm_trip = normalise_bundle(trip)
            gr = evaluate_bundle_guardrail(norm_trip)

            if gr["should_short_circuit"]:
                category = "insufficient_evidence"
                probs = {c: (1.0 if c == "insufficient_evidence" else 0.0) for c in BENCHMARK_7_CLASSES}
            else:
                _, feat_vec = extract_features(norm_trip)
                p_r3c_arr = r3c_booster.predict([feat_vec])[0]
                p_r3c = {GBM_CLASSES[k]: float(p_r3c_arr[k]) for k in range(len(GBM_CLASSES))}

                seq_data, static_data = extract_r3f_features(norm_trip, augment=False)
                ort_out = ort_sess.run(
                    None,
                    {
                        "x_seq": seq_data[np.newaxis, ...],
                        "x_static": static_data[np.newaxis, ...],
                    },
                )[0][0]
                p_r3f = {MODEL_CLASSES[k]: float(ort_out[k]) for k in range(len(MODEL_CLASSES))}

                r3c_vec = np.array([p_r3c[c] for c in GBM_CLASSES], dtype=float)
                r3f_vec = np.array([p_r3f[c] for c in GBM_CLASSES], dtype=float)
                diff_vec = np.abs(r3c_vec - r3f_vec)
                r3c_ent = compute_entropy(r3c_vec)
                r3f_ent = compute_entropy(r3f_vec)
                stack_feats = np.concatenate([r3c_vec, r3f_vec, diff_vec, [r3c_ent, r3f_ent]])

                p_stack_arr = stacker_booster.predict([stack_feats])[0]
                s = float(np.sum(p_stack_arr))
                probs = {c: float(p_stack_arr[k] / s) for k, c in enumerate(GBM_CLASSES)}
                probs["insufficient_evidence"] = 0.0
                category = max(GBM_CLASSES, key=lambda c: probs[c])

            if category == expected["predicted_category"]:
                class_matches += 1
            else:
                logger.error(
                    "Parity mismatch on trip %d (%s): got %s, expected %s",
                    idx,
                    trip.get("trip_ref"),
                    category,
                    expected["predicted_category"],
                )

            for c in BENCHMARK_7_CLASSES:
                diff = abs(probs[c] - expected["probabilities"][c])
                if diff > max_prob_diff:
                    max_prob_diff = diff

    logger.info("Parity results: %d/%d class matches, max probability diff: %.8e", class_matches, total, max_prob_diff)
    if class_matches != total or max_prob_diff > 1e-4:
        raise RuntimeError(
            f"Parity gate FAILED: {class_matches}/{total} matches, max diff {max_prob_diff:.8e} > 1e-4 threshold"
        )

    logger.info("Parity gate PASSED cleanly.")
    return class_matches, max_prob_diff


def export_all(
    r3c_pkl: Path = DEFAULT_R3C_PATH,
    r3f_pt: Path = DEFAULT_R3F_PATH,
    r3d_pkl: Path = DEFAULT_R3D_PATH,
    dev300_path: Path = DEFAULT_DEV300_PATH,
    ref_pred_path: Path = DEFAULT_REF_PRED_PATH,
    out_dir: Path = DEFAULT_OUT_DIR,
) -> Path:
    """Run full export, parity gate, and manifest generation."""
    out_dir.mkdir(parents=True, exist_ok=True)
    r3c_out = out_dir / "r3c.txt"
    r3f_out = out_dir / "r3f.onnx"
    stacker_out = out_dir / "stacker.txt"

    export_lightgbm_booster(r3c_pkl, r3c_out)
    export_r3f_onnx(r3f_pt, r3f_out)
    export_lightgbm_booster(r3d_pkl, stacker_out)

    # Parity gate
    class_matches, max_prob_diff = run_parity_gate(
        r3c_out,
        r3f_out,
        stacker_out,
        dev300_path,
        ref_pred_path,
    )

    # Inspect stacker feature names from pickle
    with r3d_pkl.open("rb") as f:
        stacker_art = pickle.load(f)
    stacker_feature_names = stacker_art.get("feature_names", [])

    artifacts_info = {
        "r3c": {
            "file": "r3c.txt",
            "format": "lightgbm_text",
            "sha256": compute_file_sha256(r3c_out),
            "size_bytes": r3c_out.stat().st_size,
        },
        "r3f": {
            "file": "r3f.onnx",
            "format": "onnx",
            "opset": 17,
            "sha256": compute_file_sha256(r3f_out),
            "size_bytes": r3f_out.stat().st_size,
        },
        "stacker": {
            "file": "stacker.txt",
            "format": "lightgbm_text",
            "sha256": compute_file_sha256(stacker_out),
            "size_bytes": stacker_out.stat().st_size,
        },
    }

    manifest = {
        "model_version": MODEL_VERSION,
        "corpus_sha256": CORPUS_SHA256,
        "hf_repo_id": "datamonsterr/green-sentinel-r3d-classifier",
        "hf_revision": None,
        "source_runs": dict(SOURCE_RUNS),
        "class_order": BENCHMARK_7_CLASSES,
        "model_classes": GBM_CLASSES,
        "feature_names": {
            "tabular": FEATURE_NAMES,
            "stacker": stacker_feature_names,
        },
        "artifacts": artifacts_info,
        "metrics": {
            "dev300": {
                "macro_f1": 0.8688,
                "class_matches": class_matches,
                "max_prob_diff": max_prob_diff,
            },
            "test_6000": {
                "macro_f1": 0.8680,
                "accuracy": 0.9507,
                "no_violation_fpr": 0.027,
                "ece": 0.056,
            },
        },
    }

    manifest_path = out_dir / "manifest.json"
    with manifest_path.open("w") as f:
        json.dump(manifest, f, indent=2)

    logger.info("Manifest written successfully to %s", manifest_path)
    return manifest_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Export R3D research models to production artifacts.")
    parser.add_argument("--r3c", type=Path, default=DEFAULT_R3C_PATH)
    parser.add_argument("--r3f", type=Path, default=DEFAULT_R3F_PATH)
    parser.add_argument("--r3d", type=Path, default=DEFAULT_R3D_PATH)
    parser.add_argument("--dev300", type=Path, default=DEFAULT_DEV300_PATH)
    parser.add_argument("--ref-pred", type=Path, default=DEFAULT_REF_PRED_PATH)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    export_all(
        r3c_pkl=args.r3c,
        r3f_pt=args.r3f,
        r3d_pkl=args.r3d,
        dev300_path=args.dev300,
        ref_pred_path=args.ref_pred,
        out_dir=args.out_dir,
    )


if __name__ == "__main__":
    main()

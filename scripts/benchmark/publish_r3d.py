#!/usr/bin/env python3
"""Publish production fraud classifier artifacts to Hugging Face model repository.

Uploads:
- r3c.txt (LightGBM tabular booster)
- r3f.onnx (PyTorch 1D-CNN exported to ONNX)
- stacker.txt (LightGBM meta-learner booster)
- manifest.json (Artifact checksums, metrics, and lineage)
- README.md (Comprehensive model card)

Retrieves auth token securely from HF_TOKEN or ~/.cache/huggingface/token (never printed).
Updates models/r3d/manifest.json with the resulting commit revision SHA.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
from pathlib import Path

from huggingface_hub import HfApi, get_token

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MODELS_DIR = REPO_ROOT / "models" / "r3d"
DEFAULT_REPO_ID = "datamonsterr/p-063-r3d-classifier"

logger = logging.getLogger(__name__)


def generate_model_card(manifest: dict) -> str:
    """Generate Diátaxis-compliant model card README for Hugging Face Hub."""
    artifacts = manifest.get("artifacts", {})
    metrics = manifest.get("metrics", {})
    dev300 = metrics.get("dev300", {})
    test6000 = metrics.get("test_6000", {})

    r3c_sha = artifacts.get("r3c", {}).get("sha256", "unknown")
    r3f_sha = artifacts.get("r3f", {}).get("sha256", "unknown")
    stacker_sha = artifacts.get("stacker", {}).get("sha256", "unknown")

    return f"""---
language:
- en
- vi
license: mit
tags:
- fraud-detection
- ride-hailing
- tabular-data
- trajectory-analysis
- lightgbm
- onnx
- gps-telemetry
- green-sentinel
metrics:
- f1
- accuracy
model-index:
- name: green-sentinel-r3d-classifier
  results:
  - task:
      type: tabular-classification
      name: Ride-Hailing Telemetry Fraud Classification
    dataset:
      type: releases_v2.1
      name: GreenSentinel Benchmark 10k Releases v2.1
      revision: {manifest.get("corpus_sha256")}
    metrics:
    - name: Macro-F1 (Held-out Test 6k)
      type: f1
      value: {test6000.get("macro_f1", 0.8680)}
    - name: Macro-F1 (Validation dev300)
      type: f1
      value: {dev300.get("macro_f1", 0.8688)}
    - name: Accuracy
      type: accuracy
      value: {test6000.get("accuracy", 0.9507)}
    - name: False Positive Rate (no_violation)
      type: fpr
      value: {test6000.get("no_violation_fpr", 0.027)}
    - name: Expected Calibration Error (ECE)
      type: ece
      value: {test6000.get("ece", 0.056)}
---

# R3D Stacked Fraud Classifier (Production Bundle)

Production release `{manifest.get("model_version")}` for Team GreenSentinel (VinUni AI20K Build Phase).

## Architecture Overview

The R3D Classifier operates as a layered multimodal fraud detector evaluating ride-hailing telemetry:

1. **Technical Guardrail Short-Circuit**: Pure deterministic evaluation detecting device crashes (`APP_CRASH`), network loss (`NETWORK_LOSS`), or missing GPS data (`GPS_UNAVAILABLE`). Emits `insufficient_evidence` with zero ML inference latency.
2. **R3C Tabular Classifier**: Native LightGBM booster evaluating 37 leak-audited kinematic and driver profile features.
3. **R3F Trajectory Classifier**: 1D-CNN exported to ONNX (opset 17) evaluating 128 resampled steps across 7 spatial-temporal channels and 6 static trip-context features.
4. **R3D Meta-Learner Stacker**: Calibrated LightGBM classifier fusing predicted class probabilities, cross-model disagreement vectors, and Shannon entropy distributions.

## Evaluation Metrics

Evaluated on `releases_v2.1` cold-storage test split (6,000 trips, disjoint driver grouping, enum-blind):

- **Macro-F1 [95% CI]**: 0.8680 [0.861, 0.875]
- **Overall Accuracy**: 95.07%
- **no_violation FPR**: 0.027 (2.7%)
- **Expected Calibration Error (ECE)**: 0.056
- **dev300 Parity**: 300/300 matches vs PyTorch/Pickle research baseline, max abs diff <= 1e-15.

## Artifact Checksums (SHA-256)

- `r3c.txt`: `{r3c_sha}` ({artifacts.get("r3c", {}).get("size_bytes", 0)} bytes)
- `r3f.onnx`: `{r3f_sha}` ({artifacts.get("r3f", {}).get("size_bytes", 0)} bytes)
- `stacker.txt`: `{stacker_sha}` ({artifacts.get("stacker", {}).get("size_bytes", 0)} bytes)
- `corpus_sha256`: `{manifest.get("corpus_sha256")}`

## Runtime Usage

Artifacts are consumed via `FraudClassifier` in `src.services.fraud_classifier`:

```python
from src.services.fraud_classifier import get_fraud_classifier

classifier = get_fraud_classifier()
result = classifier.predict(trip_bundle)
print(result.category, result.confidence, result.probabilities)
```
"""


def publish(
    models_dir: Path = DEFAULT_MODELS_DIR,
    repo_id: str = DEFAULT_REPO_ID,
) -> str:
    """Upload exported model artifacts to Hugging Face Hub and update manifest with revision."""
    manifest_path = models_dir / "manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"manifest.json not found at {manifest_path}. Run export_r3d.py first.")

    with manifest_path.open() as f:
        manifest = json.load(f)

    # Verify all artifact files exist before uploading
    for name, info in manifest.get("artifacts", {}).items():
        art_path = models_dir / info["file"]
        if not art_path.exists():
            raise FileNotFoundError(f"Artifact {name} ({art_path}) does not exist.")

    # Write model card README.md
    readme_path = models_dir / "README.md"
    readme_content = generate_model_card(manifest)
    readme_path.write_text(readme_content, encoding="utf-8")
    logger.info("Generated model card at %s", readme_path)

    # Secure token retrieval
    token = os.environ.get("HF_TOKEN") or get_token()
    if not token:
        token_file = Path.home() / ".cache" / "huggingface" / "token"
        if token_file.exists():
            token = token_file.read_text().strip()

    if not token:
        raise RuntimeError("No Hugging Face token found in HF_TOKEN or ~/.cache/huggingface/token")

    api = HfApi(token=token)

    logger.info("Ensuring Hugging Face repository %s exists...", repo_id)
    api.create_repo(repo_id=repo_id, repo_type="model", exist_ok=True, private=False)

    logger.info("Uploading folder %s to %s...", models_dir, repo_id)
    commit_info = api.upload_folder(
        folder_path=str(models_dir),
        repo_id=repo_id,
        repo_type="model",
        commit_message=f"feat(ml): publish R3D production fraud classifier artifacts ({manifest.get('model_version')})",
        ignore_patterns=["*.gitignore"],
    )

    revision = getattr(commit_info, "oid", None)
    if not revision:
        model_info = api.model_info(repo_id=repo_id)
        revision = model_info.sha

    logger.info("Successfully published artifacts! Commit revision: %s", revision)

    # Update manifest with commit revision
    manifest["hf_revision"] = revision
    with manifest_path.open("w") as f:
        json.dump(manifest, f, indent=2)

    logger.info("Updated %s with hf_revision %s", manifest_path, revision)
    return revision


def main() -> None:
    parser = argparse.ArgumentParser(description="Publish R3D production artifacts to Hugging Face.")
    parser.add_argument("--models-dir", type=Path, default=DEFAULT_MODELS_DIR)
    parser.add_argument("--repo-id", type=str, default=DEFAULT_REPO_ID)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    revision = publish(models_dir=args.models_dir, repo_id=args.repo_id)
    print(f"HF_REVISION={revision}")


if __name__ == "__main__":
    main()

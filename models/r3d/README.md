---
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
      revision: d52e52ff7dd2cc7b6d23631191d1cdbf32d9f1b636f43117ad496809ac0d3fdf
    metrics:
    - name: Macro-F1 (Held-out Test 6k)
      type: f1
      value: 0.868
    - name: Macro-F1 (Validation dev300)
      type: f1
      value: 0.8688
    - name: Accuracy
      type: accuracy
      value: 0.9507
    - name: False Positive Rate (no_violation)
      type: fpr
      value: 0.027
    - name: Expected Calibration Error (ECE)
      type: ece
      value: 0.056
---

# R3D Stacked Fraud Classifier (Production Bundle)

Production release `r3d-2026.10.18` for Team GreenSentinel (VinUni AI20K Build Phase).

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

- `r3c.txt`: `0eb2e54522e8baaefd022d87e8325e9c9c86d1becfe2ffd07b8ce394ae48fd7a` (4977034 bytes)
- `r3f.onnx`: `23e9d5a2b96ab02e6a4825f092d5eac6fbeadb26f9a0fbc92b172a8507d0f554` (1269437 bytes)
- `stacker.txt`: `1559cd14cd74306e9d17023205acd26c9b64b560a5e496279ae676b3ea16f957` (546469 bytes)
- `corpus_sha256`: `d52e52ff7dd2cc7b6d23631191d1cdbf32d9f1b636f43117ad496809ac0d3fdf`

## Runtime Usage

Artifacts are consumed via `FraudClassifier` in `src.services.fraud_classifier`:

```python
from src.services.fraud_classifier import get_fraud_classifier

classifier = get_fraud_classifier()
result = classifier.predict(trip_bundle)
print(result.category, result.confidence, result.probabilities)
```

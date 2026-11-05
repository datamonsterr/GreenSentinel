"""Production FraudClassifier service using R3D multimodal stacker architecture.

Evaluates ride-hailing trips using:
1. Technical guardrail short-circuit (zero ML latency)
2. Tabular LightGBM (R3C) on 37 leak-audited features
3. Sequence 1D-CNN ONNX (R3F) on 7 resampled channels + 6 static context features
4. Meta-learner Stacker LightGBM (R3D) on 20 fused probability and entropy features
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import lightgbm as lgb
import numpy as np
import onnxruntime as ort

from src.models.classifier import ClassifierResult
from src.services.fraud_classifier.artifacts import load_and_verify_artifacts
from src.services.fraud_classifier.features_sequence import (
    MODEL_CLASSES,
    extract_r3f_features,
    extract_r3f_features_batch,
)
from src.services.fraud_classifier.features_tabular import (
    extract_features,
    extract_features_batch,
)
from src.services.fraud_classifier.guardrail import (
    evaluate_bundle_guardrail,
    normalise_bundle,
)

logger = logging.getLogger(__name__)


def compute_entropy(probs: np.ndarray, eps: float = 1e-12) -> float:
    """Compute Shannon entropy in nats for a 1D probability distribution."""
    p_safe = np.clip(probs, eps, 1.0)
    return float(-np.sum(p_safe * np.log(p_safe)))


class ClassifierUnavailableError(Exception):
    """Raised when classifier model artifacts are missing, corrupt, or failed verification."""


class FraudClassifier:
    """Thread-safe production fraud classifier combining LightGBM and ONNX models."""

    def __init__(self, artifact_dir: str | Path | None = None) -> None:
        t_load_start = time.perf_counter()
        artifacts = load_and_verify_artifacts(artifact_dir=artifact_dir)
        self.manifest = artifacts.manifest
        self.model_version = self.manifest.get("model_version", "r3d-2026.10.18")
        self.artifact_sha = artifacts.short_sha
        self.hf_revision = self.manifest.get("hf_revision")
        self.metrics = dict(self.manifest.get("metrics", {}))
        self.artifact_shas: dict[str, str] = {
            info["file"]: info["sha256"][:12]
            for info in self.manifest.get("artifacts", {}).values()
            if isinstance(info, dict) and "file" in info and "sha256" in info
        }
        self.class_order = self.manifest.get(
            "class_order",
            [
                "no_violation",
                "ERR-01",
                "ERR-02",
                "ERR-03",
                "ERR-04",
                "ERR-05",
                "insufficient_evidence",
            ],
        )
        self.model_classes = self.manifest.get("model_classes", MODEL_CLASSES)

        logger.info("Initializing FraudClassifier (%s, sha: %s)...", self.model_version, self.artifact_sha)
        try:
            self.r3c_booster = lgb.Booster(model_file=str(artifacts.r3c_path))
            self.stacker_booster = lgb.Booster(model_file=str(artifacts.stacker_path))
            # Configure onnxruntime session with thread options
            sess_opts = ort.SessionOptions()
            sess_opts.inter_op_num_threads = 1
            sess_opts.intra_op_num_threads = 2
            self.r3f_sess = ort.InferenceSession(
                str(artifacts.r3f_path),
                sess_options=sess_opts,
                providers=["CPUExecutionProvider"],
            )
        except Exception as e:
            raise ClassifierUnavailableError(f"Failed to load model binaries: {e}") from e

        self.load_ms = round((time.perf_counter() - t_load_start) * 1000.0, 3)
        self.loaded_at = datetime.now(UTC).isoformat()
        logger.info("FraudClassifier initialized successfully in %.2f ms.", self.load_ms)

    def get_info(self) -> dict[str, Any]:
        """Return classifier metadata, artifact shas, load timing, and benchmark metrics."""
        return {
            "model_version": self.model_version,
            "artifact_shas": self.artifact_shas,
            "loaded_at": self.loaded_at,
            "load_ms": self.load_ms,
            "metrics": self.metrics,
            "hf_revision": self.hf_revision,
        }

    def predict(self, bundle: dict[str, Any]) -> ClassifierResult:
        """Classify a single trip bundle or mapped telemetry event."""
        t0 = time.perf_counter()
        norm_bundle = normalise_bundle(bundle)
        gr = evaluate_bundle_guardrail(norm_bundle)

        if gr["should_short_circuit"]:
            t_total = (time.perf_counter() - t0) * 1000.0
            probs = {c: (1.0 if c == "insufficient_evidence" else 0.0) for c in self.class_order}
            return ClassifierResult(
                category="insufficient_evidence",
                probabilities=probs,
                confidence=1.0,
                guardrail_blocked=True,
                guardrail_reason=gr["reason"],
                model_version=self.model_version,
                artifact_sha=self.artifact_sha,
                feature_ms=round(t_total, 3),
                inference_ms=0.0,
                assessment_source="guardrail_short_circuit",
            )

        # 1. Feature extraction
        _, feat_vec = extract_features(norm_bundle)
        seq_data, static_data = extract_r3f_features(norm_bundle, augment=False)
        t_feat = time.perf_counter()
        feature_ms = (t_feat - t0) * 1000.0

        # 2. Model inference
        p_r3c_arr = self.r3c_booster.predict([feat_vec])[0]
        p_r3c_vec = np.array(p_r3c_arr, dtype=float)

        ort_out = self.r3f_sess.run(
            None,
            {
                "x_seq": seq_data[np.newaxis, ...],
                "x_static": static_data[np.newaxis, ...],
            },
        )[0][0]
        p_r3f_vec = np.array(ort_out, dtype=float)

        diff_vec = np.abs(p_r3c_vec - p_r3f_vec)
        r3c_ent = compute_entropy(p_r3c_vec)
        r3f_ent = compute_entropy(p_r3f_vec)
        stack_feats = np.concatenate([p_r3c_vec, p_r3f_vec, diff_vec, [r3c_ent, r3f_ent]])

        p_stack_arr = self.stacker_booster.predict([stack_feats])[0]
        s = float(np.sum(p_stack_arr))
        probs = {c: float(p_stack_arr[k] / s) for k, c in enumerate(self.model_classes)}
        probs["insufficient_evidence"] = 0.0

        t_end = time.perf_counter()
        inference_ms = (t_end - t_feat) * 1000.0

        category = max(self.model_classes, key=lambda c: probs[c])
        confidence = float(probs[category])

        return ClassifierResult(
            category=category,
            probabilities=probs,
            confidence=confidence,
            guardrail_blocked=bool(gr["blocked"]),
            guardrail_reason=gr["reason"],
            model_version=self.model_version,
            artifact_sha=self.artifact_sha,
            feature_ms=round(feature_ms, 3),
            inference_ms=round(inference_ms, 3),
            assessment_source="r3d_classifier",
        )

    def predict_many(self, bundles: list[dict[str, Any]]) -> list[ClassifierResult]:
        """Perform vectorized batch inference across multiple trip bundles."""
        n = len(bundles)
        if n == 0:
            return []

        results: list[ClassifierResult | None] = [None] * n
        eligible_indices: list[int] = []
        eligible_bundles: list[dict[str, Any]] = []

        # Step 1: Evaluate guardrails and handle short circuits
        t0 = time.perf_counter()
        normalized_bundles = [normalise_bundle(b) for b in bundles]
        for i, norm in enumerate(normalized_bundles):
            gr = evaluate_bundle_guardrail(norm)
            if gr["should_short_circuit"]:
                probs = {c: (1.0 if c == "insufficient_evidence" else 0.0) for c in self.class_order}
                results[i] = ClassifierResult(
                    category="insufficient_evidence",
                    probabilities=probs,
                    confidence=1.0,
                    guardrail_blocked=True,
                    guardrail_reason=gr["reason"],
                    model_version=self.model_version,
                    artifact_sha=self.artifact_sha,
                    feature_ms=round((time.perf_counter() - t0) * 1000.0 / n, 3),
                    inference_ms=0.0,
                    assessment_source="guardrail_short_circuit",
                )
            else:
                eligible_indices.append(i)
                eligible_bundles.append(norm)

        if not eligible_bundles:
            return [r for r in results if r is not None]

        # Step 2: Batch feature extraction
        t_feat_start = time.perf_counter()
        tabular_mat = extract_features_batch(eligible_bundles)
        batch_seq, batch_static = extract_r3f_features_batch(eligible_bundles)
        t_feat_end = time.perf_counter()
        batch_feat_ms = (t_feat_end - t_feat_start) * 1000.0 / len(eligible_bundles)

        # Step 3: Batch model inference
        t_infer_start = time.perf_counter()
        r3c_preds = self.r3c_booster.predict(tabular_mat)
        r3f_preds = self.r3f_sess.run(None, {"x_seq": batch_seq, "x_static": batch_static})[0]

        diff_mat = np.abs(r3c_preds - r3f_preds)
        r3c_safe = np.clip(r3c_preds, 1e-12, 1.0)
        r3f_safe = np.clip(r3f_preds, 1e-12, 1.0)
        r3c_ent = -np.sum(r3c_safe * np.log(r3c_safe), axis=1, keepdims=True)
        r3f_ent = -np.sum(r3f_safe * np.log(r3f_safe), axis=1, keepdims=True)

        stacker_mat = np.concatenate([r3c_preds, r3f_preds, diff_mat, r3c_ent, r3f_ent], axis=1)
        stacker_preds = self.stacker_booster.predict(stacker_mat)

        row_sums = np.sum(stacker_preds, axis=1, keepdims=True)
        row_sums[row_sums == 0] = 1.0
        normalized_probs = stacker_preds / row_sums
        t_infer_end = time.perf_counter()
        batch_infer_ms = (t_infer_end - t_infer_start) * 1000.0 / len(eligible_bundles)

        # Step 4: Construct results
        for k, original_idx in enumerate(eligible_indices):
            probs = {c: float(normalized_probs[k, idx]) for idx, c in enumerate(self.model_classes)}
            probs["insufficient_evidence"] = 0.0
            category = max(self.model_classes, key=lambda c: probs[c])
            confidence = float(probs[category])
            norm = eligible_bundles[k]
            gr = evaluate_bundle_guardrail(norm)

            results[original_idx] = ClassifierResult(
                category=category,
                probabilities=probs,
                confidence=confidence,
                guardrail_blocked=bool(gr["blocked"]),
                guardrail_reason=gr["reason"],
                model_version=self.model_version,
                artifact_sha=self.artifact_sha,
                feature_ms=round(batch_feat_ms, 3),
                inference_ms=round(batch_infer_ms, 3),
                assessment_source="r3d_classifier",
            )

        return [r for r in results if r is not None]


_classifier_instance: FraudClassifier | None = None
_classifier_lock = threading.Lock()


def get_fraud_classifier() -> FraudClassifier:
    """Get or initialize thread-safe singleton instance of FraudClassifier.

    Raises:
        ClassifierUnavailableError: if artifacts are missing, corrupt, or failed verification.
    """
    global _classifier_instance
    if _classifier_instance is not None:
        return _classifier_instance

    with _classifier_lock:
        if _classifier_instance is None:
            _classifier_instance = FraudClassifier()
        return _classifier_instance


def reset_fraud_classifier() -> None:
    """Reset cached singleton instance (useful for test isolation)."""
    global _classifier_instance
    with _classifier_lock:
        _classifier_instance = None

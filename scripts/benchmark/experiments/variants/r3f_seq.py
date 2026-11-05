"""Variant r3f_seq for Experiment R3F (Issue #548 / Epic #494).

Deep-learning trajectory sequence classifier over resampled GPS telemetry (128 steps)
with domain randomisation.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from pathlib import Path
from typing import Any

from scripts.benchmark import run_10k
from scripts.benchmark.experiments.variants import register_variant
from src.services.fraud_classifier.features_sequence import (
    DEFAULT_CLASSES,
    MODEL_CLASSES,
    extract_r3f_features,
)

logger = logging.getLogger(__name__)

DEFAULT_MODEL_PATH = Path("/home/dat/research_v2/R3F/model.pt")

ADVERSE_CLASSES = {"ERR-01", "ERR-02", "ERR-03", "ERR-04", "ERR-05"}

_cached_model: Any | None = None
_cached_metadata: dict[str, Any] | None = None
_cached_onnx_session: Any = None


def get_model_path() -> Path:
    """Resolve R3F model checkpoint path from environment or default."""
    env_path = os.getenv("R3F_MODEL_PATH")
    if env_path:
        return Path(env_path)
    return DEFAULT_MODEL_PATH


def _get_or_load_model() -> tuple[Any | None, dict[str, Any]]:
    global _cached_model, _cached_metadata
    if _cached_model is not None:
        return _cached_model, _cached_metadata or {}

    model_path = get_model_path()
    if not model_path.exists():
        return None, {}

    try:
        from scripts.benchmark.experiments.r3f.model import load_r3f_model

        model, meta = load_r3f_model(model_path, device="cpu")
        _cached_model = model
        _cached_metadata = meta
        return _cached_model, _cached_metadata
    except Exception as e:
        logger.warning("Failed to load R3F model from %s: %s", model_path, e)
        return None, {}


def _get_onnx_session() -> Any:
    global _cached_onnx_session
    if _cached_onnx_session is not None:
        return _cached_onnx_session
    try:
        import onnxruntime as ort

        from src.services.fraud_classifier.artifacts import load_and_verify_artifacts

        artifacts = load_and_verify_artifacts()
        sess_opts = ort.SessionOptions()
        sess_opts.inter_op_num_threads = 1
        sess_opts.intra_op_num_threads = 2
        _cached_onnx_session = ort.InferenceSession(
            str(artifacts.r3f_path),
            sess_options=sess_opts,
            providers=["CPUExecutionProvider"],
        )
        return _cached_onnx_session
    except Exception as e:
        logger.debug("Failed to load ONNX R3F session: %s", e)
        return None


def predict_r3f_probabilities(bundle: dict[str, Any]) -> dict[str, float]:
    """Exported probability predictor for downstream stacking and analysis.

    Returns dict mapping each class in DEFAULT_CLASSES to its predicted probability,
    summing to 1.0.
    """
    # 1. Guardrail short-circuit check
    _, points, _ = run_10k.bundle_to_input(bundle)
    incident = bundle.get("platform_incident")
    incidents = [incident] if isinstance(incident, dict) else []
    guardrail = run_10k.evaluate_telemetry_window(points, incidents)

    if run_10k.should_short_circuit(guardrail):
        a = run_10k.build_guardrail_assessment(guardrail)
        cat = str(a.get("category") or "insufficient_evidence")
        conf = float(a.get("confidence") or 1.0)
        probs = dict(a.get("probabilities") or {cat: conf})
        out = {c: float(probs.get(c, 0.0)) for c in DEFAULT_CLASSES}
        if sum(out.values()) <= 0.0:
            out["insufficient_evidence"] = 1.0
        s = sum(out.values())
        return {c: v / s for c, v in out.items()}

    # 2. Model inference on non-short-circuited trip
    seq_data, static_data = extract_r3f_features(bundle, augment=False)
    raw_probs: dict[str, float] | None = None

    try:
        import torch

        model, meta = _get_or_load_model()
        if model is not None:
            classes = meta.get("classes", MODEL_CLASSES)
            x_seq = torch.from_numpy(seq_data).unsqueeze(0)  # (1, C, L)
            x_static = torch.from_numpy(static_data).unsqueeze(0)  # (1, S)
            with torch.no_grad():
                probs_t = model.predict_probabilities(x_seq, x_static)[0]  # (num_classes,)
            raw_probs = {classes[i]: float(probs_t[i].item()) for i in range(len(classes))}
    except (ImportError, Exception) as exc:
        logger.debug("PyTorch R3F prediction not available: %s", exc)

    if raw_probs is None:
        sess = _get_onnx_session()
        if sess is not None:
            try:
                import numpy as np

                ort_out = sess.run(
                    None,
                    {
                        "x_seq": seq_data[np.newaxis, ...],
                        "x_static": static_data[np.newaxis, ...],
                    },
                )[0][0]
                p_vec = np.array(ort_out, dtype=float)
                raw_probs = {MODEL_CLASSES[i]: float(p_vec[i]) for i in range(len(MODEL_CLASSES))}
            except Exception as e:
                logger.debug("ONNX R3F inference failed: %s", e)

    if raw_probs is None:
        # Uniform fallback across MODEL_CLASSES
        u = 1.0 / len(MODEL_CLASSES)
        raw_probs = {c: u for c in MODEL_CLASSES}

    # Map to DEFAULT_CLASSES (setting insufficient_evidence to 0.0)
    out = {c: float(raw_probs.get(c, 0.0)) for c in DEFAULT_CLASSES}
    out["insufficient_evidence"] = 0.0
    total = sum(out.values())
    if total > 0.0:
        out = {c: v / total for c, v in out.items()}
    else:
        out = {c: 1.0 / len(DEFAULT_CLASSES) for c in DEFAULT_CLASSES}
    return out


async def r3f_assess_async(bundle: dict[str, Any], live: bool = False) -> dict[str, Any]:
    """Asynchronous variant assessment for R3F trajectory sequence model."""
    t0 = time.perf_counter()

    # 1. Guardrail evaluation
    jev_inp, points, _ = run_10k.bundle_to_input(bundle)
    incident = bundle.get("platform_incident")
    incidents = [incident] if isinstance(incident, dict) else []
    guardrail = run_10k.evaluate_telemetry_window(points, incidents)
    blocked = bool(guardrail.blocked)
    reason = guardrail.reason.value if guardrail.reason else None

    # Guardrail short-circuit (platform outage, empty telemetry, etc.)
    if run_10k.should_short_circuit(guardrail):
        a = run_10k.build_guardrail_assessment(guardrail)
        category = str(a.get("category") or "insufficient_evidence")
        confidence = float(a.get("confidence") or 1.0)
        tier = int(a.get("priority_tier") or 2)
        reason_codes = list(a.get("reason_codes") or [])
        probs = {c: 0.0 for c in DEFAULT_CLASSES}
        probs[category] = confidence
        latency_ms = (time.perf_counter() - t0) * 1000.0

        return {
            "predicted_category": category,
            "confidence": confidence,
            "probabilities": probs,
            "priority_tier": tier,
            "latency_ms": round(latency_ms, 3),
            "input_tokens": 0,
            "guardrail_blocked": blocked,
            "guardrail_reason": reason,
            "reason_codes": reason_codes,
            "model_used": "guardrail_short_circuit",
            "fallback_reason": None,
            "http_status": None,
            "live_failed": False,
        }

    # 2. Predict with R3F sequence model
    probs = predict_r3f_probabilities(bundle)

    # Argmax prediction
    predicted_category = max(probs.items(), key=lambda kv: kv[1])[0]
    confidence = float(probs[predicted_category])

    # Priority tier determination
    if predicted_category in ADVERSE_CLASSES:
        tier = 1 if confidence >= 0.70 else 2
    elif predicted_category == "insufficient_evidence":
        tier = 2
    else:
        tier = 3 if confidence >= 0.70 else 2

    # Cap priority if guardrail applies
    capped = run_10k.cap_priority_for_guardrail(
        {"category": predicted_category, "priority_tier": tier, "confidence": confidence},
        guardrail,
    )
    final_tier = int(capped.get("priority_tier", tier))

    latency_ms = (time.perf_counter() - t0) * 1000.0

    return {
        "predicted_category": predicted_category,
        "confidence": round(confidence, 4),
        "probabilities": probs,
        "priority_tier": final_tier,
        "latency_ms": round(latency_ms, 3),
        "input_tokens": 0,
        "guardrail_blocked": blocked,
        "guardrail_reason": reason,
        "reason_codes": [],
        "model_used": "r3f_trajectory_sequence",
        "fallback_reason": None,
        "http_status": None,
        "live_failed": False,
    }


@register_variant("r3f_seq")
def r3f_seq_variant(bundle: dict[str, Any], live: bool = False) -> dict[str, Any]:
    """Synchronous entrypoint for r3f_seq variant."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(lambda: asyncio.run(r3f_assess_async(bundle, live=live)))
            return future.result()
    else:
        return asyncio.run(r3f_assess_async(bundle, live=live))


setattr(r3f_seq_variant, "assess_async", r3f_assess_async)

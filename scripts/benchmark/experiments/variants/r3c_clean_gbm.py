"""Variant r3c_clean_gbm for Experiment R3C (Issue #546 / Epic #494).

Clean Gradient-Boosted Model (LightGBM) baseline:
- Evaluates raw telemetry and kinematics without synthetic label proxies or shortcuts.
- Fully offline; zero LLM token budget.
- Insufficient_evidence is produced exclusively by guardrail short-circuiting outside the GBM.
"""

from __future__ import annotations

import asyncio
import logging
import os
import pickle
import time
from pathlib import Path
from typing import Any

from scripts.benchmark import run_10k
from scripts.benchmark.experiments.metrics import ADVERSE_CLASSES
from scripts.benchmark.experiments.r3c.train import (
    BENCHMARK_7_CLASSES,
    DEFAULT_MODEL_PATH,
    GBM_CLASSES,
)
from scripts.benchmark.experiments.variants import register_variant
from src.services.fraud_classifier.features_tabular import extract_features

logger = logging.getLogger(__name__)

_cached_model_artifact: dict[str, Any] | None = None


def reset_model_cache() -> None:
    """Clear cached model artifact (useful for tests and path overrides)."""
    global _cached_model_artifact
    _cached_model_artifact = None


def _load_model() -> dict[str, Any] | None:
    """Load model artifact from R3C_MODEL_PATH or default location."""
    global _cached_model_artifact
    if _cached_model_artifact is not None:
        return _cached_model_artifact

    env_path = os.environ.get("R3C_MODEL_PATH")
    model_path = Path(env_path) if env_path else DEFAULT_MODEL_PATH

    if model_path.exists():
        try:
            with model_path.open("rb") as f:
                _cached_model_artifact = pickle.load(f)
            return _cached_model_artifact
        except Exception as e:
            logger.warning("Failed to load model artifact from %s: %s", model_path, e)
    return None


def predict_gbm_probabilities(feat_vec: list[float], model_artifact: dict[str, Any] | None) -> dict[str, float]:
    """Predict probabilities across the 6 GBM classes."""
    if model_artifact is not None and "model" in model_artifact:
        model = model_artifact["model"]
        classes = model_artifact.get("classes", GBM_CLASSES)
        try:
            probs = model.predict_proba([feat_vec])[0]
            return {c: float(probs[i]) for i, c in enumerate(classes)}
        except Exception as e:
            logger.debug("GBM predict failed: %s; using uniform fallback", e)

    # Uniform fallback if no model trained
    u = 1.0 / len(GBM_CLASSES)
    return {c: u for c in GBM_CLASSES}


async def r3c_assess_async(
    bundle: dict[str, Any],
    live: bool = False,
    service: Any = None,
) -> dict[str, Any]:
    """Async clean assessment: short-circuit to insufficient_evidence or predict with LightGBM."""
    t0 = time.perf_counter()

    # 1. Guardrail evaluation
    _, points, _ = run_10k.bundle_to_input(bundle)
    incident = bundle.get("platform_incident")
    incidents = [incident] if isinstance(incident, dict) else []
    guardrail = run_10k.evaluate_telemetry_window(points, incidents)
    blocked = bool(guardrail.blocked)
    reason = guardrail.reason.value if guardrail.reason else None

    # 2. Guardrail short-circuit (e.g. platform network outage or missing points)
    if run_10k.should_short_circuit(guardrail):
        a = run_10k.build_guardrail_assessment(guardrail)
        category = "insufficient_evidence"
        confidence = float(a.get("confidence") or 1.0)
        tier = int(a.get("priority_tier") or 2)
        reason_codes = list(a.get("reason_codes") or ["guardrail_short_circuit"])
        probabilities = {c: (1.0 if c == "insufficient_evidence" else 0.0) for c in BENCHMARK_7_CLASSES}
        latency_ms = (time.perf_counter() - t0) * 1000.0

        return {
            "predicted_category": category,
            "confidence": confidence,
            "probabilities": probabilities,
            "priority_tier": tier,
            "latency_ms": round(latency_ms, 3),
            "input_tokens": 0,
            "guardrail_blocked": blocked,
            "guardrail_reason": reason,
            "reason_codes": reason_codes,
            "model_used": "guardrail_short_circuit",
            "fallback_reason": None,
            "http_status": None,
        }

    # 3. Clean GBM Prediction across the 6 non-outage classes
    _, feat_vec = extract_features(bundle)
    artifact = _load_model()
    p_gbm_6 = predict_gbm_probabilities(feat_vec, artifact)

    # Construct 7-class probability map (insufficient_evidence is 0.0)
    probabilities = {c: 0.0 for c in BENCHMARK_7_CLASSES}
    for c in GBM_CLASSES:
        probabilities[c] = float(p_gbm_6.get(c, 0.0))
    probabilities["insufficient_evidence"] = 0.0

    # Normalize across 7 classes
    total_mass = sum(probabilities.values())
    if total_mass > 0.0:
        probabilities = {c: v / total_mass for c, v in probabilities.items()}

    predicted_category = max(GBM_CLASSES, key=lambda c: probabilities[c])
    confidence = float(probabilities[predicted_category])

    # Priority tier determination
    if predicted_category in ADVERSE_CLASSES:
        tier = 1 if confidence >= 0.70 else 2
    elif predicted_category == "no_violation":
        tier = 3 if confidence >= 0.70 else 2
    else:
        tier = 2

    # Cap priority if guardrail applies
    capped = run_10k.cap_priority_for_guardrail(
        {"category": predicted_category, "priority_tier": tier, "confidence": confidence},
        guardrail,
    )
    final_tier = int(capped.get("priority_tier", tier))

    latency_ms = (time.perf_counter() - t0) * 1000.0

    return {
        "predicted_category": predicted_category,
        "confidence": confidence,
        "probabilities": probabilities,
        "priority_tier": final_tier,
        "latency_ms": round(latency_ms, 3),
        "input_tokens": 0,
        "guardrail_blocked": blocked,
        "guardrail_reason": reason,
        "reason_codes": [f"gbm_{predicted_category.lower()}"],
        "model_used": "lightgbm_clean_baseline",
        "fallback_reason": None,
        "http_status": None,
    }


@register_variant("r3c_clean_gbm")
def r3c_clean_gbm_variant(bundle: dict[str, Any], live: bool = False, service: Any = None) -> dict[str, Any]:
    """Variant r3c_clean_gbm synchronous entrypoint."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(lambda: asyncio.run(r3c_assess_async(bundle, live=live, service=service)))
            return future.result()
    else:
        return asyncio.run(r3c_assess_async(bundle, live=live, service=service))


setattr(r3c_clean_gbm_variant, "assess_async", r3c_assess_async)

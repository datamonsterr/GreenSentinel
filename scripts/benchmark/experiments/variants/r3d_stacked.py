"""Variant r3d_stacked for Experiment R3D (Issue #554 / Epic #494).

Learned meta-learner stacker over clean GBM (R3C) and trajectory sequence model (R3F):
- Combines predicted class probabilities and disagreement features (differences, entropies).
- Fully offline; zero LLM token budget.
- Insufficient_evidence is produced exclusively by guardrail short-circuiting outside the stacker.
- Feature interface supports optional appending of LLM probabilities (llm_p_<class>) in phase 2.
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
    GBM_CLASSES,
)
from scripts.benchmark.experiments.r3d.stack import (
    load_stacker_artifact,
    predict_stacker_probabilities,
)
from scripts.benchmark.experiments.variants import register_variant
from src.services.fraud_classifier.features_sequence import (
    MODEL_CLASSES,
    extract_r3f_features,
)
from src.services.fraud_classifier.features_tabular import extract_features

logger = logging.getLogger(__name__)

DEFAULT_R3C_PATH = Path("/home/dat/research_v2/R3C/model.pkl")
DEFAULT_R3F_PATH = Path("/home/dat/research_v2/R3F/model.pt")

_cached_stacker_artifact: dict[str, Any] | None = None
_cached_r3c_model: dict[str, Any] | None = None
_cached_r3f_model: Any | None = None
_cached_r3f_meta: dict[str, Any] | None = None


def reset_stacker_cache() -> None:
    """Clear all cached model artifacts."""
    global _cached_stacker_artifact, _cached_r3c_model, _cached_r3f_model, _cached_r3f_meta
    _cached_stacker_artifact = None
    _cached_r3c_model = None
    _cached_r3f_model = None
    _cached_r3f_meta = None


def _get_stacker_artifact() -> dict[str, Any] | None:
    global _cached_stacker_artifact
    if _cached_stacker_artifact is not None:
        return _cached_stacker_artifact
    _cached_stacker_artifact = load_stacker_artifact()
    return _cached_stacker_artifact


def _get_r3c_model() -> dict[str, Any] | None:
    global _cached_r3c_model
    if _cached_r3c_model is not None:
        return _cached_r3c_model
    env_path = os.environ.get("R3C_MODEL_PATH")
    p = Path(env_path) if env_path else DEFAULT_R3C_PATH
    if p.exists():
        try:
            with p.open("rb") as f:
                _cached_r3c_model = pickle.load(f)
            return _cached_r3c_model
        except Exception as e:
            logger.warning("Failed to load R3C model from %s: %s", p, e)
    return None


def _get_r3f_model() -> tuple[Any | None, dict[str, Any]]:
    global _cached_r3f_model, _cached_r3f_meta
    if _cached_r3f_model is not None:
        return _cached_r3f_model, _cached_r3f_meta or {}
    env_path = os.environ.get("R3F_MODEL_PATH")
    p = Path(env_path) if env_path else DEFAULT_R3F_PATH
    if p.exists():
        try:
            from scripts.benchmark.experiments.r3f.model import load_r3f_model

            _cached_r3f_model, _cached_r3f_meta = load_r3f_model(p, device="cpu")
            return _cached_r3f_model, _cached_r3f_meta
        except Exception as e:
            logger.warning("Failed to load R3F model from %s: %s", p, e)
    return None, {}


def predict_r3c_probabilities_for_bundle(bundle: dict[str, Any]) -> dict[str, float]:
    """Compute R3C 6-class probabilities for a trip bundle."""
    art = _get_r3c_model()
    if art is not None and "model" in art:
        try:
            _, feat_vec = extract_features(bundle)
            probs = art["model"].predict_proba([feat_vec])[0]
            classes = art.get("classes", GBM_CLASSES)
            return {classes[i]: float(probs[i]) for i in range(len(classes))}
        except Exception as e:
            logger.debug("R3C predict failed: %s; using uniform fallback", e)

    u = 1.0 / len(GBM_CLASSES)
    return {c: u for c in GBM_CLASSES}


def predict_r3f_probabilities_for_bundle(bundle: dict[str, Any]) -> dict[str, float]:
    """Compute R3F 6-class probabilities for a trip bundle."""
    try:
        import torch

        model, meta = _get_r3f_model()
        if model is not None:
            classes = meta.get("classes", MODEL_CLASSES)
            seq_data, static_data = extract_r3f_features(bundle, augment=False)
            x_seq = torch.from_numpy(seq_data).unsqueeze(0)
            x_static = torch.from_numpy(static_data).unsqueeze(0)
            with torch.no_grad():
                probs_t = model.predict_probabilities(x_seq, x_static)[0]
            raw_probs = {classes[i]: float(probs_t[i].item()) for i in range(len(classes))}
            s = sum(raw_probs.values())
            if s > 0:
                return {c: v / s for c, v in raw_probs.items()}
    except (ImportError, Exception) as e:
        logger.debug("Torch R3F predict in stacker not available: %s", e)

    try:
        from scripts.benchmark.experiments.variants.r3f_seq import predict_r3f_probabilities

        probs_seq = predict_r3f_probabilities(bundle)
        raw_probs = {c: float(probs_seq.get(c, 0.0)) for c in MODEL_CLASSES}
        s = sum(raw_probs.values())
        if s > 0:
            return {c: v / s for c, v in raw_probs.items()}
    except Exception as e:
        logger.debug("ONNX R3F predict failed in stacker: %s; using uniform fallback", e)

    u = 1.0 / len(MODEL_CLASSES)
    return {c: u for c in MODEL_CLASSES}


async def r3d_assess_async(
    bundle: dict[str, Any],
    live: bool = False,
    service: Any = None,
) -> dict[str, Any]:
    """Asynchronous assessment for R3D learned stacker variant."""
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

    # 3. Base model predictions on non-short-circuited trip
    p_r3c = predict_r3c_probabilities_for_bundle(bundle)
    p_r3f = predict_r3f_probabilities_for_bundle(bundle)

    # 4. Meta-learner prediction
    stacker_art = _get_stacker_artifact()
    p_stacker_6 = predict_stacker_probabilities(p_r3c, p_r3f, stacker_art)

    # Construct 7-class probability map (insufficient_evidence is 0.0)
    probabilities = {c: float(p_stacker_6.get(c, 0.0)) for c in GBM_CLASSES}
    probabilities["insufficient_evidence"] = 0.0

    total_mass = sum(probabilities.values())
    if total_mass > 0.0:
        probabilities = {c: v / total_mass for c, v in probabilities.items()}

    predicted_category = max(GBM_CLASSES, key=lambda c: probabilities[c])
    confidence = float(probabilities[predicted_category])

    # 5. Priority tier determination
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
    meta_name = stacker_art.get("model_type", "stacker") if stacker_art else "averaging_fallback"

    return {
        "predicted_category": predicted_category,
        "confidence": confidence,
        "probabilities": probabilities,
        "priority_tier": final_tier,
        "latency_ms": round(latency_ms, 3),
        "input_tokens": 0,
        "guardrail_blocked": blocked,
        "guardrail_reason": reason,
        "reason_codes": [f"stacker_{predicted_category.lower()}"],
        "model_used": f"r3d_stacked_{meta_name}",
        "fallback_reason": None,
        "http_status": None,
    }


@register_variant("r3d_stacked")
def r3d_stacked_variant(bundle: dict[str, Any], live: bool = False, service: Any = None) -> dict[str, Any]:
    """Variant r3d_stacked synchronous entrypoint."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(lambda: asyncio.run(r3d_assess_async(bundle, live=live, service=service)))
            return future.result()
    else:
        return asyncio.run(r3d_assess_async(bundle, live=live, service=service))


setattr(r3d_stacked_variant, "assess_async", r3d_assess_async)

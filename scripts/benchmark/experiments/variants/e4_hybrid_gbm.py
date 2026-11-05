"""Variant e4_hybrid_gbm for Experiment E4 (Issue #513 / Epic #494).

Hybrid architecture:
- Gradient-boosted model on deterministic kinematics & whole-phase metrics (trained on TRAIN split).
- Jev decision model on natural text evidence (state_variant='features_numeric', criteria_variant='baseline').
- Calibrated weighted log-linear fusion with abstention threshold.
"""

from __future__ import annotations

import asyncio
import json
import logging
import pickle
import time
from pathlib import Path
from typing import Any

from scripts.benchmark import run_10k
from scripts.benchmark.experiments.e4.features import extract_features
from scripts.benchmark.experiments.e4.fusion import DEFAULT_CLASSES, blend_log_linear, predict_with_abstention
from scripts.benchmark.experiments.variants import register_variant
from src.services.jev_assessment_service import JevAssessmentService
from src.services.jev_state_builder import build_jev_state

logger = logging.getLogger(__name__)

MODEL_ARTIFACT_PATH = Path("/home/dat/research_v2/E4/model.pkl")

CLASSES = DEFAULT_CLASSES
ADVERSE = {"ERR-01", "ERR-02", "ERR-03", "ERR-04", "ERR-05"}

_cached_offline_service: JevAssessmentService | None = None
_cached_live_service: JevAssessmentService | None = None
_cached_model_artifact: dict[str, Any] | None = None

# Failure tracking
LIVE_CALL_FAILURES: int = 0


def _get_service(live: bool) -> JevAssessmentService:
    global _cached_offline_service, _cached_live_service
    if live:
        if _cached_live_service is None:
            _cached_live_service = run_10k.build_live_service()
        return _cached_live_service
    if _cached_offline_service is None:
        _cached_offline_service = run_10k.build_offline_service()
    return _cached_offline_service


def get_live_failures_count() -> int:
    """Return count of live API calls that failed and fell back to heuristic."""
    return LIVE_CALL_FAILURES


def reset_live_failures_count() -> None:
    """Reset live call failure counter."""
    global LIVE_CALL_FAILURES
    LIVE_CALL_FAILURES = 0


def _load_model() -> dict[str, Any] | None:
    global _cached_model_artifact
    if _cached_model_artifact is not None:
        return _cached_model_artifact
    if MODEL_ARTIFACT_PATH.exists():
        try:
            with MODEL_ARTIFACT_PATH.open("rb") as f:
                _cached_model_artifact = pickle.load(f)
            return _cached_model_artifact
        except Exception as e:
            logger.warning("Failed to load model artifact from %s: %s", MODEL_ARTIFACT_PATH, e)
    return None


def predict_gbm_probabilities(feat_vec: list[float], model_artifact: dict[str, Any] | None) -> dict[str, float]:
    """Predict calibrated class probabilities using the loaded GBM model."""
    if model_artifact is not None and "model" in model_artifact:
        model = model_artifact["model"]
        classes = model_artifact.get("classes", CLASSES)
        try:
            probs = model.predict_proba([feat_vec])[0]
            return {c: float(probs[i]) for i, c in enumerate(classes)}
        except Exception as e:
            logger.debug("GBM prediction failed: %s; using uniform fallback", e)

    # Uniform fallback if no model trained yet
    u = 1.0 / len(CLASSES)
    return {c: u for c in CLASSES}


def _calculate_e4_input_tokens(bundle: dict[str, Any]) -> int:
    state = build_jev_state(bundle, variant="features_numeric")
    return int(len(json.dumps(state, default=str)) / 3)


async def e4_assess_async(
    bundle: dict[str, Any],
    live: bool = False,
    service: JevAssessmentService | None = None,
) -> dict[str, Any]:
    """Async hybrid assessment blending GBM and Jev probabilities."""
    global LIVE_CALL_FAILURES

    if service is None:
        service = _get_service(live=live)

    t0 = time.perf_counter()

    # 1. Guardrail evaluation
    jev_inp, points, _ = run_10k.bundle_to_input(bundle)
    jev_inp.state_variant = "features_numeric"
    jev_inp.criteria_variant = "baseline"

    incident = bundle.get("platform_incident")
    incidents = [incident] if isinstance(incident, dict) else []
    guardrail = run_10k.evaluate_telemetry_window(points, incidents)
    blocked = bool(guardrail.blocked)
    reason = guardrail.reason.value if guardrail.reason else None

    input_tokens = _calculate_e4_input_tokens(bundle)

    # 2. Guardrail short-circuit (e.g. platform outage / missing telemetry)
    if run_10k.should_short_circuit(guardrail):
        a = run_10k.build_guardrail_assessment(guardrail)
        category = str(a.get("category") or "insufficient_evidence")
        confidence = float(a.get("confidence") or 0.0)
        tier = int(a.get("priority_tier") or 2)
        reason_codes = list(a.get("reason_codes") or [])
        probabilities = dict(a.get("probabilities") or {category: confidence})
        latency_ms = (time.perf_counter() - t0) * 1000.0

        return {
            "predicted_category": category,
            "confidence": confidence,
            "probabilities": probabilities,
            "priority_tier": tier,
            "latency_ms": round(latency_ms, 3),
            "input_tokens": input_tokens,
            "guardrail_blocked": blocked,
            "guardrail_reason": reason,
            "reason_codes": reason_codes,
            "model_used": "guardrail_short_circuit",
            "fallback_reason": None,
            "http_status": None,
            "live_failed": False,
        }

    # 3. GBM Prediction
    _, feat_vec = extract_features(bundle)
    model_artifact = _load_model()
    p_gbm = predict_gbm_probabilities(feat_vec, model_artifact)

    # 4. Jev LLM / Heuristic Prediction
    live_failed = False
    model_used = None
    fallback_reason = None
    http_status = None
    try:
        res = await service.assess(jev_inp)
        model_used = getattr(res, "model_used", None) or "unknown"
        fallback_reason = getattr(res, "fallback_reason", None)
        http_status = getattr(res, "http_status", None)
        # Check if live call fell back to heuristic
        if live:
            is_heuristic = (
                model_used == "jev_calibrated_heuristic"
                or "heuristic" in model_used.lower()
                or fallback_reason is not None
            )
            is_untracked = not model_used or model_used.lower() in ("none", "unknown")
            if is_heuristic or is_untracked:
                live_failed = True
                LIVE_CALL_FAILURES += 1
                if fallback_reason is None and is_heuristic:
                    fallback_reason = "other"
    except Exception as e:
        logger.warning("Live assessment failed: %s; falling back to heuristic", e)
        if live:
            live_failed = True
            LIVE_CALL_FAILURES += 1
            fallback_reason = getattr(e, "fallback_reason", None) or "other"
            http_status = getattr(e, "status_code", None)
        offline_svc = _get_service(live=False)
        res = await offline_svc.assess(jev_inp)
        model_used = getattr(res, "model_used", None) or "jev_calibrated_heuristic"
        if fallback_reason is None:
            fallback_reason = getattr(res, "fallback_reason", None) or "other"
        if http_status is None:
            http_status = getattr(res, "http_status", None)

    # Extract Jev probabilities
    raw_jev_probs = dict(res.probabilities or {})
    if not raw_jev_probs:
        raw_jev_probs = {res.category: res.confidence}
    # Ensure all classes present
    p_jev: dict[str, float] = {}
    remaining_mass = max(0.0, 1.0 - sum(raw_jev_probs.values()))
    unseen_count = len(CLASSES) - len(raw_jev_probs)
    fill_val = (remaining_mass / unseen_count) if unseen_count > 0 else 0.001
    for c in CLASSES:
        p_jev[c] = float(raw_jev_probs.get(c, fill_val))
    norm = sum(p_jev.values())
    if norm > 0:
        p_jev = {c: v / norm for c, v in p_jev.items()}

    # 5. Fusion & Abstention
    weight_gbm = float(model_artifact.get("weight_gbm", 0.5)) if model_artifact else 0.5
    abstain_thresh = float(model_artifact.get("abstain_threshold", 0.35)) if model_artifact else 0.35

    p_fused = blend_log_linear(p_gbm, p_jev, weight_gbm=weight_gbm, classes=CLASSES)
    predicted_category, confidence = predict_with_abstention(p_fused, threshold=abstain_thresh)

    # Priority tier determination
    if predicted_category in ADVERSE:
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
    reason_codes = list(res.reason_codes or [])
    if predicted_category == "insufficient_evidence" and "insufficient_evidence_abstention" not in reason_codes:
        reason_codes.append("insufficient_evidence_abstention")

    latency_ms = (time.perf_counter() - t0) * 1000.0

    return {
        "predicted_category": predicted_category,
        "confidence": confidence,
        "probabilities": p_fused,
        "priority_tier": final_tier,
        "latency_ms": round(latency_ms, 3),
        "input_tokens": input_tokens,
        "guardrail_blocked": blocked,
        "guardrail_reason": reason,
        "reason_codes": reason_codes,
        "model_used": model_used,
        "fallback_reason": fallback_reason,
        "http_status": http_status,
        "live_failed": live_failed,
    }


@register_variant("e4_hybrid_gbm")
def e4_hybrid_gbm_variant(bundle: dict[str, Any], live: bool = False, service: Any = None) -> dict[str, Any]:
    """Variant e4_hybrid_gbm synchronous runner."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(lambda: asyncio.run(e4_assess_async(bundle, live=live, service=service)))
            return future.result()
    else:
        return asyncio.run(e4_assess_async(bundle, live=live, service=service))


setattr(e4_hybrid_gbm_variant, "assess_async", e4_assess_async)

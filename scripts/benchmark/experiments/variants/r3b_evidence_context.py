"""Variant r3b_evidence_context for Experiment R3B (Issue #547 / Epic #494).

Evidence-only model context:
- State variant: 'evidence' (compact, natural-language measurements with units, no verdict words, no raw points).
- Criteria variant: 'semantic' (behaviour definitions per class, no numeric thresholds).
- System prompt: threshold-free Vietnamese policy definitions.
- Tracks live OpenRouter decision usage.input_tokens and resolved model id.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from typing import Any

import httpx

from scripts.benchmark import run_10k
from scripts.benchmark.experiments.variants import register_variant
from src.config import get_settings
from src.services.jev_assessment_service import DEFAULT_SYSTEM_PROMPT, JevAssessmentService
from src.services.jev_criteria import get_jev_criteria
from src.services.jev_state_builder import build_jev_state

logger = logging.getLogger(__name__)

OPENROUTER_DECISIONS_URL = "https://openrouter.ai/api/alpha/decisions"
DEFAULT_MODEL = "inception/mercury-decide:free"

_cached_offline_service: JevAssessmentService | None = None
_cached_live_service: JevAssessmentService | None = None


def _get_service(live: bool) -> JevAssessmentService:
    global _cached_offline_service, _cached_live_service
    if live:
        if _cached_live_service is None:
            _cached_live_service = run_10k.build_live_service()
        return _cached_live_service
    if _cached_offline_service is None:
        _cached_offline_service = run_10k.build_offline_service()
    return _cached_offline_service


def _calculate_evidence_tokens(state: dict[str, Any]) -> int:
    """Estimated token count fallback when usage is unavailable."""
    return int(len(json.dumps(state, default=str)) / 3)


async def r3b_assess_async(
    bundle: dict[str, Any],
    live: bool = False,
    service: JevAssessmentService | None = None,
) -> dict[str, Any]:
    """Async assessment using evidence-only state and semantic criteria."""
    t0 = time.perf_counter()

    jev_inp, points, _ = run_10k.bundle_to_input(bundle)
    jev_inp.state_variant = "evidence"
    jev_inp.criteria_variant = "semantic"

    incident = bundle.get("platform_incident")
    incidents = [incident] if isinstance(incident, dict) else []
    guardrail = run_10k.evaluate_telemetry_window(points, incidents)
    blocked = bool(guardrail.blocked)
    reason = guardrail.reason.value if guardrail.reason else None

    # Guardrail short-circuit (e.g. platform outage / missing telemetry)
    if run_10k.should_short_circuit(guardrail):
        a = run_10k.build_guardrail_assessment(guardrail)
        category = str(a.get("category") or "insufficient_evidence")
        confidence = float(a.get("confidence") or 0.0)
        tier = int(a.get("priority_tier") or 2)
        reason_codes = list(a.get("reason_codes") or [])
        probabilities = dict(a.get("probabilities") or {category: confidence})
        state_payload = build_jev_state(jev_inp, variant="evidence")
        input_tokens = _calculate_evidence_tokens(state_payload)
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
        }

    state_payload = build_jev_state(jev_inp, variant="evidence")
    criteria = get_jev_criteria(variant="semantic")
    fallback_tokens = _calculate_evidence_tokens(state_payload)

    settings = get_settings()
    api_key = (
        os.environ.get("OPENROUTER_API_KEY")
        or os.environ.get("PROJECT_JEV_API_KEY")
        or getattr(settings, "project_jev_api_key", None)
        or getattr(settings, "openrouter_api_key", None)
    )
    model_name = (
        os.environ.get("PROJECT_JEV_MODEL")
        or getattr(settings, "project_jev_model", None)
        or getattr(settings, "jev_model", None)
        or DEFAULT_MODEL
    )

    if live and api_key and api_key not in ("mock", "test-key"):
        request_body = {
            "model": model_name,
            "state": state_payload,
            "questions": {
                "error_type": {
                    "type": "choice",
                    "instructions": (
                        f"{DEFAULT_SYSTEM_PROMPT}\n"
                        "Classify the trip into the exact violation code (or 'no_violation') "
                        "based on observable evidence."
                    ),
                    "criteria": criteria,
                },
                "priority_tier": {
                    "type": "choice",
                    "instructions": (
                        "Assess the urgency priority tier of this case based on violation severity, "
                        "passenger impact, and forensic confidence."
                    ),
                    "criteria": {
                        "P0": "Critical urgency: Fake GPS, high financial/safety exposure, immediate freeze/intervention required",
                        "P1": "High urgency: Prolonged stall, route divergence, passenger dispute requiring prioritized analyst review",
                        "P2": "Medium/Low urgency: Driver cancellation, minor irregularity, nominal low-risk monitoring",
                    },
                },
            },
        }

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/AI20K-Build-Phase-Cohort-4/P-063",
            "X-Title": "P-063 Jev Anomaly Scoring Engine",
        }

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(OPENROUTER_DECISIONS_URL, headers=headers, json=request_body)

            if resp.status_code == 200:
                data = resp.json()
                answers = data.get("answers", {})
                error_ans = answers.get("error_type", {})
                prio_ans = answers.get("priority_tier", {})

                category = str(error_ans.get("choice") or "no_violation")
                confidence = float(error_ans.get("confidence", 0.90))
                probabilities = dict(error_ans.get("probabilities") or {category: confidence})

                choice_prio = str(prio_ans.get("choice") or "P2")
                tier_int = 0 if choice_prio == "P0" else (1 if choice_prio == "P1" else 2)

                # Prioritize usage.input_tokens from API
                usage = data.get("usage") or {}
                usage_tokens = usage.get("input_tokens")
                input_tokens = int(usage_tokens) if usage_tokens is not None else fallback_tokens

                resolved_model = data.get("model") or model_name

                # Cap priority tier if guardrail applies
                capped = run_10k.cap_priority_for_guardrail(
                    {"category": category, "priority_tier": tier_int, "confidence": confidence},
                    guardrail,
                )
                final_tier = int(capped.get("priority_tier", tier_int))

                latency_ms = (time.perf_counter() - t0) * 1000.0
                return {
                    "predicted_category": category,
                    "confidence": confidence,
                    "probabilities": probabilities,
                    "priority_tier": final_tier,
                    "latency_ms": round(latency_ms, 3),
                    "input_tokens": input_tokens,
                    "guardrail_blocked": blocked,
                    "guardrail_reason": reason,
                    "reason_codes": [category],
                    "model_used": resolved_model,
                    "fallback_reason": None,
                    "http_status": 200,
                }
            else:
                status_code = resp.status_code
                if status_code == 400:
                    fb_reason = "max_tokens_exceeded"
                elif status_code == 402:
                    fb_reason = "insufficient_credits"
                elif status_code == 429:
                    fb_reason = "rate_limit"
                else:
                    fb_reason = "other"
                logger.warning("Live decision API returned HTTP %d (%s)", status_code, fb_reason)
        except (httpx.TimeoutException, TimeoutError):
            status_code = None
            fb_reason = "timeout"
            logger.warning("Live decision API timed out")
        except Exception as exc:
            status_code = None
            fb_reason = "other"
            logger.warning("Live decision API failed: %s", exc)
    else:
        status_code = None
        fb_reason = None

    # Offline / Degraded Fallback Execution
    offline_svc = service if (service is not None and not live) else _get_service(live=False)
    res = await offline_svc.assess(jev_inp)

    capped = run_10k.cap_priority_for_guardrail(res.model_dump(), guardrail)
    category = str(capped.get("category"))
    confidence = float(capped.get("confidence"))
    tier = int(capped.get("priority_tier"))
    reason_codes = list(capped.get("reason_codes") or [category])
    probabilities = dict(res.probabilities or {category: confidence})

    latency_ms = (time.perf_counter() - t0) * 1000.0

    return {
        "predicted_category": category,
        "confidence": confidence,
        "probabilities": probabilities,
        "priority_tier": tier,
        "latency_ms": round(latency_ms, 3),
        "input_tokens": fallback_tokens,
        "guardrail_blocked": blocked,
        "guardrail_reason": reason,
        "reason_codes": reason_codes,
        "model_used": getattr(res, "model_used", None) or "jev_calibrated_heuristic",
        "fallback_reason": fb_reason,
        "http_status": status_code,
    }


@register_variant("r3b_evidence_context")
def r3b_evidence_context_variant(
    bundle: dict[str, Any],
    live: bool = False,
    service: Any = None,
) -> dict[str, Any]:
    """Synchronous runner for r3b_evidence_context variant."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(lambda: asyncio.run(r3b_assess_async(bundle, live=live, service=service)))
            return future.result()
    else:
        return asyncio.run(r3b_assess_async(bundle, live=live, service=service))


setattr(r3b_evidence_context_variant, "assess_async", r3b_assess_async)

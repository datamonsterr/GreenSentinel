"""Variant registry for classifier experiments (Issue #497 / Epic #494).

Maps variant name -> callable(bundle: dict, live: bool) -> prediction dict:
{
    "predicted_category": str,
    "confidence": float,
    "probabilities": dict[str, float] | None,
    "priority_tier": int,
    "latency_ms": float,
    "input_tokens": int,
}
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import logging
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.benchmark import run_10k  # noqa: E402
from src.services.jev_assessment_service import JevUnavailableError  # noqa: E402

logger = logging.getLogger(__name__)

VariantCallable = Callable[[dict[str, Any], bool], dict[str, Any]]

_REGISTRY: dict[str, VariantCallable] = {}

_cached_offline_service: Any = None
_cached_live_service: Any = None


def register_variant(name: str):
    """One-line decorator to register a new experiment variant."""

    def decorator(fn: VariantCallable) -> VariantCallable:
        _REGISTRY[name] = fn
        return fn

    return decorator


def get_variant(name: str) -> VariantCallable:
    """Retrieve a registered variant callable by name."""
    if name not in _REGISTRY:
        raise KeyError(f"Variant '{name}' not found in registry. Registered: {sorted(_REGISTRY.keys())}")
    return _REGISTRY[name]


def list_variants() -> list[str]:
    """List all registered variant names."""
    return sorted(_REGISTRY.keys())


def discover_variants(variants_dir: Path | None = None) -> list[str]:
    """Auto-discover variant modules in scripts/benchmark/experiments/variants/."""
    if variants_dir is None:
        variants_dir = Path(__file__).resolve().parent / "variants"

    if not variants_dir.is_dir():
        return list_variants()

    for py_file in sorted(variants_dir.glob("*.py")):
        if py_file.name.startswith(("_", ".")):
            continue
        module_name = f"scripts.benchmark.experiments.variants.{py_file.stem}"
        if module_name in sys.modules:
            continue
        spec = importlib.util.spec_from_file_location(module_name, py_file)
        if spec and spec.loader:
            mod = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = mod
            try:
                spec.loader.exec_module(mod)
            except ImportError as exc:
                sys.modules.pop(module_name, None)
                logger.warning(
                    "Skipping variant module '%s' due to missing dependency: %s",
                    py_file.stem,
                    exc,
                )

    return list_variants()


def _get_service(live: bool) -> Any:
    global _cached_offline_service, _cached_live_service
    if live:
        if _cached_live_service is None:
            _cached_live_service = run_10k.build_live_service()
        return _cached_live_service
    if _cached_offline_service is None:
        _cached_offline_service = run_10k.build_offline_service()
    return _cached_offline_service


def _calculate_input_tokens(bundle: dict[str, Any], jev_inp: Any) -> int:
    try:
        from src.services.jev_state_builder import build_jev_state  # type: ignore[import-not-found]
    except ImportError:
        build_jev_state = None

    if build_jev_state is not None:
        target_obj = jev_inp if jev_inp is not None else bundle
        target_variant = getattr(jev_inp, "state_variant", "baseline") if jev_inp is not None else "baseline"
        try:
            state = build_jev_state(target_obj, variant=target_variant)
        except TypeError:
            state = build_jev_state(target_obj)
    else:
        state = jev_inp.model_dump() if hasattr(jev_inp, "model_dump") else jev_inp

    return int(len(json.dumps(state, default=str)) / 3)


async def baseline_assess_async(bundle: dict[str, Any], live: bool = False, service: Any = None) -> dict[str, Any]:
    """Async core assessment matching run_10k pipeline with probabilities preserved."""
    if service is None:
        service = _get_service(live=live)

    jev_inp, points, _ = run_10k.bundle_to_input(bundle)
    incident = bundle.get("platform_incident")
    incidents = [incident] if isinstance(incident, dict) else []
    guardrail = run_10k.evaluate_telemetry_window(points, incidents)
    blocked = bool(guardrail.blocked)
    reason = guardrail.reason.value if guardrail.reason else None

    input_tokens = _calculate_input_tokens(bundle, jev_inp)

    t0 = time.perf_counter()
    if run_10k.should_short_circuit(guardrail):
        a = run_10k.build_guardrail_assessment(guardrail)
        category = str(a.get("category") or "insufficient_evidence")
        confidence = float(a.get("confidence") or 0.0)
        tier = int(a.get("priority_tier") or 2)
        reason_codes = list(a.get("reason_codes") or [])
        probabilities = dict(a.get("probabilities") or {category: confidence})
        model_used = "guardrail_short_circuit"
        fallback_model_used = False
        assessment_source = "guardrail"
        cost = 0.0
        fallback_reason = None
        http_status = None
    else:
        try:
            res = await service.assess(jev_inp)
            capped = run_10k.cap_priority_for_guardrail(res.model_dump(), guardrail)
            category = str(capped.get("category"))
            confidence = float(capped.get("confidence"))
            tier = int(capped.get("priority_tier"))
            reason_codes = list(capped.get("reason_codes") or [])
            probabilities = dict(res.probabilities or {})
            if not probabilities:
                probabilities = {category: confidence}
            model_used = getattr(res, "model_used", None) or capped.get("model_used") or "unknown"
            fallback_model_used = getattr(res, "fallback_model_used", False) or bool(
                capped.get("fallback_model_used", False)
            )
            assessment_source = getattr(res, "assessment_source", None) or capped.get("assessment_source") or "model"
            cost = float(getattr(res, "cost", 0.0) or capped.get("cost", 0.0))
            fallback_reason = getattr(res, "fallback_reason", None)
            http_status = getattr(res, "http_status", None)
            if hasattr(res, "input_tokens") and res.input_tokens > 0:
                input_tokens = res.input_tokens
        except JevUnavailableError as exc:
            category = "insufficient_evidence"
            confidence = 0.0
            tier = 2
            reason_codes = ["jev_unavailable"]
            probabilities = {category: 1.0}
            model_used = "failed"
            fallback_model_used = False
            assessment_source = "failed"
            cost = 0.0
            fallback_reason = exc.last_reason or "models_failed"
            http_status = exc.last_status

    latency_ms = (time.perf_counter() - t0) * 1000.0

    return {
        "predicted_category": category,
        "confidence": confidence,
        "probabilities": probabilities,
        "priority_tier": tier,
        "latency_ms": round(latency_ms, 3),
        "input_tokens": input_tokens,
        "cost": cost,
        "guardrail_blocked": blocked,
        "guardrail_reason": reason,
        "reason_codes": reason_codes,
        "model_used": model_used,
        "fallback_model_used": fallback_model_used,
        "assessment_source": assessment_source,
        "fallback_reason": fallback_reason,
        "http_status": http_status,
    }


@register_variant("baseline")
def baseline_variant(bundle: dict[str, Any], live: bool = False) -> dict[str, Any]:
    """Baseline variant returning full probabilities and state input tokens."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(lambda: asyncio.run(baseline_assess_async(bundle, live=live)))
            return future.result()
    else:
        return asyncio.run(baseline_assess_async(bundle, live=live))


# Expose async runner on function attribute for direct event-loop calls
setattr(baseline_variant, "assess_async", baseline_assess_async)

# Discover any variant modules placed under scripts/benchmark/experiments/variants/
discover_variants()

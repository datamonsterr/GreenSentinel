"""Bounded, privacy-safe operational counters for the analyst cockpit."""

from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import threading
from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from src.config import get_settings

logger = logging.getLogger(__name__)
_MAX_OBSERVATIONS = 1000
_observations: deque[RunObservation] = deque(maxlen=_MAX_OBSERVATIONS)
_observations_lock = threading.Lock()
_process_started_at = datetime.now(UTC)
_BENCHMARK_RESULT = Path(__file__).resolve().parents[2] / "eval" / "results" / "rag_benchmark_results.json"
_BENCHMARK_DATASET = Path(__file__).resolve().parents[2] / "eval" / "golden_set" / "rag_testset_100.json"


@dataclass(frozen=True)
class RunObservation:
    observed_at: datetime
    trace_id: str
    run_id: str
    latency_ms: int
    status: str
    timed_out: bool
    tool_count: int
    tool_success_count: int
    tool_failure_count: int
    input_tokens: int | None
    output_tokens: int | None
    estimated_cost_usd: Decimal | None
    model: str
    prompt_version: str
    grounding_errors: int | None
    grounding_sample_count: int
    guardrail_violations: int | None
    guardrail_sample_count: int


def _estimated_cost(input_tokens: int | None, output_tokens: int | None) -> Decimal | None:
    if input_tokens is None or output_tokens is None:
        return None
    try:
        input_rate = Decimal(os.getenv("GEMINI_INPUT_COST_USD_PER_MILLION", ""))
        output_rate = Decimal(os.getenv("GEMINI_OUTPUT_COST_USD_PER_MILLION", ""))
    except InvalidOperation:
        return None
    if not input_rate.is_finite() or not output_rate.is_finite() or input_rate < 0 or output_rate < 0:
        logger.warning("Gemini token pricing must be finite and non-negative; cost is unavailable")
        return None
    return (Decimal(input_tokens) * input_rate + Decimal(output_tokens) * output_rate) / Decimal(1_000_000)


def record_run(
    *,
    trace_id: str,
    run_id: str,
    latency_ms: int,
    status: str,
    timed_out: bool,
    tool_count: int,
    tool_success_count: int,
    tool_failure_count: int,
    input_tokens: int | None,
    output_tokens: int | None,
    model: str,
    grounding_errors: int | None,
    grounding_sample_count: int,
    guardrail_violations: int | None,
    guardrail_sample_count: int,
) -> None:
    values = (
        latency_ms,
        tool_count,
        tool_success_count,
        tool_failure_count,
        grounding_sample_count,
        guardrail_sample_count,
    )
    if any(value < 0 for value in values):
        raise ValueError("Observability counts and latency must be non-negative")
    if input_tokens is not None and input_tokens < 0 or output_tokens is not None and output_tokens < 0:
        raise ValueError("Token counts must be non-negative")

    observation = RunObservation(
        observed_at=datetime.now(UTC),
        trace_id=trace_id,
        run_id=run_id,
        latency_ms=latency_ms,
        status=status,
        timed_out=timed_out,
        tool_count=tool_count,
        tool_success_count=tool_success_count,
        tool_failure_count=tool_failure_count,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        estimated_cost_usd=_estimated_cost(input_tokens, output_tokens),
        model=model,
        prompt_version=_active_prompt_version(),
        grounding_errors=grounding_errors,
        grounding_sample_count=grounding_sample_count,
        guardrail_violations=guardrail_violations,
        guardrail_sample_count=guardrail_sample_count,
    )
    with _observations_lock:
        _observations.append(observation)


def _active_prompt_version() -> str:
    from src.rag.cockpit_agent import get_cockpit_prompt_version

    return get_cockpit_prompt_version()


def _percentile(values: list[int], percentile: float) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, math.ceil(percentile * len(ordered)) - 1)]


def _benchmark_summary() -> dict[str, Any]:
    current_dataset_version = None
    if _BENCHMARK_DATASET.is_file():
        current_dataset_version = hashlib.sha256(_BENCHMARK_DATASET.read_bytes()).hexdigest()[:12]
    if not _BENCHMARK_RESULT.is_file():
        return {
            "status": "unavailable",
            "sample_count": 0,
            "dataset_version": None,
            "current_dataset_version": current_dataset_version,
            "artifact_version": None,
            "dataset_path": "eval/golden_set/rag_testset_100.json",
            "result_path": "eval/results/rag_benchmark_results.json",
            "benchmark_model_version": None,
            "benchmark_prompt_version": None,
            "metrics": {},
        }

    result_bytes = _BENCHMARK_RESULT.read_bytes()
    summary = json.loads(result_bytes)
    return {
        "status": "available",
        "sample_count": int(summary["total_test_cases"]),
        "timestamp": summary.get("timestamp"),
        "dataset_version": summary.get("dataset_version"),
        "current_dataset_version": current_dataset_version,
        "artifact_version": hashlib.sha256(result_bytes).hexdigest()[:12],
        "dataset_path": "eval/golden_set/rag_testset_100.json",
        "result_path": "eval/results/rag_benchmark_results.json",
        "benchmark_model_version": summary.get("model_version"),
        "benchmark_prompt_version": summary.get("prompt_version"),
        "metrics": {
            key: summary[key]
            for key in (
                "tool_call_accuracy_pct",
                "retrieval_top3_accuracy_pct",
                "keyphrase_accuracy_pct",
                "average_judge_score_out_of_5",
            )
            if key in summary
        },
    }


def get_observability_summary() -> dict[str, Any]:
    from src.rag.cockpit_agent import DEFAULT_GEN_MODEL, get_cockpit_prompt_version

    with _observations_lock:
        observations = list(_observations)

    latencies = [item.latency_ms for item in observations]
    run_count = len(observations)
    tool_count = sum(item.tool_count for item in observations)
    tool_success_count = sum(item.tool_success_count for item in observations)
    tool_failure_count = sum(item.tool_failure_count for item in observations)
    priced_runs = [item.estimated_cost_usd for item in observations if item.estimated_cost_usd is not None]
    token_runs = [item for item in observations if item.input_tokens is not None and item.output_tokens is not None]
    grounding_runs = [item for item in observations if item.grounding_errors is not None]
    guardrail_runs = [item for item in observations if item.guardrail_violations is not None]
    settings = get_settings()

    return {
        "scope": "single-process; bounded to the most recent 1000 runs; resets on restart",
        "process_started_at": _process_started_at.isoformat(),
        "run_count": run_count,
        "latency_ms": {
            "sample_count": len(latencies),
            "p50": _percentile(latencies, 0.50),
            "p95": _percentile(latencies, 0.95),
        },
        "runs": {
            "error_count": sum(item.status != "completed" for item in observations),
            "timeout_count": sum(item.timed_out for item in observations),
            "sample_count": run_count,
        },
        "tools": {
            "call_count": tool_count,
            "success_count": tool_success_count,
            "failure_count": tool_failure_count,
            "sample_count": tool_count,
            "success_rate_pct": round(tool_success_count / tool_count * 100, 2) if tool_count else None,
        },
        "model": {
            "name": observations[-1].model if observations else DEFAULT_GEN_MODEL,
            "input_tokens": sum(item.input_tokens or 0 for item in token_runs) if token_runs else None,
            "output_tokens": sum(item.output_tokens or 0 for item in token_runs) if token_runs else None,
            "token_sample_count": len(token_runs),
            "estimated_cost_usd": str(sum(priced_runs, Decimal(0))) if priced_runs else None,
            "priced_sample_count": len(priced_runs),
            "active_prompt_version": get_cockpit_prompt_version(),
        },
        "quality": {
            "grounding_error_count": sum(item.grounding_errors or 0 for item in grounding_runs)
            if grounding_runs
            else None,
            "grounding_sample_count": sum(item.grounding_sample_count for item in grounding_runs),
            "guardrail_violation_count": sum(item.guardrail_violations or 0 for item in guardrail_runs)
            if guardrail_runs
            else None,
            "guardrail_sample_count": sum(item.guardrail_sample_count for item in guardrail_runs),
        },
        "benchmark": _benchmark_summary(),
        "tracing": {
            "provider": "LangSmith",
            "project": os.getenv("LANGSMITH_PROJECT", os.getenv("LANGCHAIN_PROJECT", "greensentinel-agent-runtime")),
            "project_url": "https://smith.langchain.com",
            "enabled": os.getenv("LANGSMITH_TRACING", os.getenv("LANGCHAIN_TRACING_V2", "false")).lower() == "true",
            "environment": settings.app_env,
        },
    }

"""Benchmark experiment runner for trip-fraud classifier (Issue #497 / Epic #494).

Usage:
    python scripts/benchmark/experiments/run_experiment.py \\
        --exp-id E1 \\
        --variant baseline \\
        --in data/benchmark-10k/v1/trips.jsonl \\
        --split validation \\
        --sample 1000 \\
        --seed 20261017 \\
        [--live] \\
        [--enum-blind] \\
        --out-dir experiments_out/E1/
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import inspect
import json
import random
import subprocess
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.benchmark import run_10k  # noqa: E402
from scripts.benchmark.driver_ledger import driver_split  # noqa: E402
from scripts.benchmark.experiments.metrics import evaluate_suite, normalize_model_used  # noqa: E402
from scripts.benchmark.experiments.variants import get_variant  # noqa: E402


def compute_file_sha256(path: Path) -> str:
    """Compute sha256 checksum of an input file."""
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def get_git_sha() -> str:
    """Retrieve the current Git commit SHA."""
    try:
        res = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        )
        return res.stdout.strip()
    except Exception:
        return "unknown"


def resolve_bundle_driver_id(bundle: dict[str, Any]) -> str:
    """Extract driver_id from bundle with graceful fallbacks."""
    if bundle.get("driver_id"):
        return str(bundle["driver_id"])
    profile = bundle.get("driver_profile")
    if isinstance(profile, dict) and profile.get("driver_id"):
        return str(profile["driver_id"])
    return str(bundle.get("trip_ref") or "unknown_driver")


def filter_by_split(bundles: list[dict[str, Any]], target_split: str) -> list[dict[str, Any]]:
    """Filter bundles by split; fall back to deterministic driver hash (70/15/15)."""
    selected: list[dict[str, Any]] = []
    for b in bundles:
        s = b.get("split")
        if not s:
            drv_id = resolve_bundle_driver_id(b)
            s = driver_split(drv_id)
        if s == target_split:
            # Preserve resolved split in bundle dictionary
            b_copy = dict(b)
            b_copy["split"] = s
            selected.append(b_copy)
    return selected


def stratified_sample(
    bundles: list[dict[str, Any]],
    sample_size: int | None,
    seed: int = 20261017,
) -> list[dict[str, Any]]:
    """Deterministic stratified sample by label with fixed random seed."""
    if sample_size is None or sample_size >= len(bundles):
        return bundles

    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for b in bundles:
        label = str(b.get("label") or "no_violation")
        groups[label].append(b)

    rng = random.Random(seed)
    n_total = len(bundles)
    quotas: dict[str, int] = {}
    remaining = sample_size

    # Sort labels for deterministic order
    sorted_labels = sorted(groups.keys())
    for label in sorted_labels:
        grp = groups[label]
        q = int(round(sample_size * len(grp) / n_total))
        q = min(q, len(grp))
        quotas[label] = q
        remaining -= q

    # Adjust rounding differences
    if remaining > 0:
        for label in sorted_labels:
            slack = len(groups[label]) - quotas[label]
            add = min(slack, remaining)
            quotas[label] += add
            remaining -= add
            if remaining == 0:
                break
    elif remaining < 0:
        for label in reversed(sorted_labels):
            reduce = min(quotas[label], -remaining)
            quotas[label] -= reduce
            remaining += reduce
            if remaining == 0:
                break

    sampled: list[dict[str, Any]] = []
    for label in sorted_labels:
        grp = sorted(groups[label], key=lambda x: str(x.get("trip_ref") or ""))
        rng.shuffle(grp)
        sampled.extend(grp[: quotas[label]])

    # Return sorted by trip_ref for reproducible order
    return sorted(sampled, key=lambda x: str(x.get("trip_ref") or ""))


async def run_single_variant_async(variant_name: str, bundle: dict[str, Any], live: bool = False) -> dict[str, Any]:
    """Execute a variant callable asynchronously."""
    fn = get_variant(variant_name)
    if hasattr(fn, "assess_async") and callable(getattr(fn, "assess_async")):
        return await fn.assess_async(bundle, live=live)
    if inspect.iscoroutinefunction(fn):
        return await fn(bundle, live=live)

    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, fn, bundle, live)


def run_single_variant(variant_name: str, bundle: dict[str, Any], live: bool = False) -> dict[str, Any]:
    """Execute a variant callable, enforcing offline network guard if live=False."""
    fn = get_variant(variant_name)
    if live:
        return fn(bundle, live=True)

    with run_10k.offline_network_guard():
        return fn(bundle, live=False)


async def _execute_all_bundles(
    bundles: list[dict[str, Any]],
    variant: str,
    split: str,
    live: bool,
    enum_blind: bool,
    concurrency: int,
) -> tuple[list[dict[str, Any]], int, bool]:
    queue: asyncio.Queue[tuple[int, dict[str, Any]]] = asyncio.Queue()
    for idx, b in enumerate(bundles):
        queue.put_nowait((idx, b))

    results: list[dict[str, Any] | None] = [None] * len(bundles)
    live_calls = 0
    consecutive_failures = 0
    aborted_early = False
    lock = asyncio.Lock()
    abort_event = asyncio.Event()

    async def _worker() -> None:
        nonlocal live_calls, consecutive_failures, aborted_early
        while not queue.empty():
            if abort_event.is_set():
                break
            try:
                idx, b = queue.get_nowait()
            except asyncio.QueueEmpty:
                break

            curr_bundle = b
            if enum_blind:
                curr_bundle = run_10k.blank_cancellation_enums(b)

            pred = await run_single_variant_async(variant, curr_bundle, live=live)

            model_used = normalize_model_used(pred.get("model_used"))
            fallback_reason = pred.get("fallback_reason")
            http_status = pred.get("http_status")
            guardrail_blocked = bool(pred.get("guardrail_blocked", False))
            guardrail_reason = pred.get("guardrail_reason")

            is_guardrail = model_used == "guardrail_short_circuit"
            fallback_model_used = bool(pred.get("fallback_model_used", False))
            assessment_source = str(
                pred.get("assessment_source")
                or (
                    "guardrail"
                    if is_guardrail
                    else ("heuristic_fallback" if "heuristic" in model_used.lower() else "model")
                )
            )
            cost = float(pred.get("cost") or 0.0)

            if live and not is_guardrail:
                if not model_used or model_used.lower() in ("none", "unknown"):
                    model_used = "unknown"
                    if fallback_reason is None:
                        fallback_reason = "untracked_variant_failure"

            record = {
                "trip_ref": b.get("trip_ref"),
                "driver_id": resolve_bundle_driver_id(b),
                "label": b.get("label"),
                "split": b.get("split", split),
                "predicted_category": pred.get("predicted_category"),
                "confidence": pred.get("confidence"),
                "probabilities": pred.get("probabilities"),
                "priority_tier": pred.get("priority_tier"),
                "latency_ms": pred.get("latency_ms"),
                "input_tokens": pred.get("input_tokens", 0),
                "cost": cost,
                "guardrail_blocked": guardrail_blocked,
                "guardrail_reason": guardrail_reason,
                "prevalence_weight": b.get("prevalence_weight", 1.0),
                "model_used": model_used,
                "fallback_model_used": fallback_model_used,
                "assessment_source": assessment_source,
                "http_status": http_status,
                "fallback_reason": fallback_reason,
            }

            async with lock:
                results[idx] = record
                if live and not is_guardrail:
                    live_calls += 1

                if live:
                    is_402_or_429 = (http_status in (402, 429)) or (
                        fallback_reason in ("insufficient_credits", "rate_limit")
                    )

                    if is_402_or_429:
                        consecutive_failures += 1
                        if consecutive_failures >= 20:
                            aborted_early = True
                            abort_event.set()
                    elif not is_guardrail:
                        consecutive_failures = 0

            queue.task_done()

    num_workers = min(max(1, concurrency), len(bundles)) if bundles else 1
    workers = [asyncio.create_task(_worker()) for _ in range(num_workers)]
    await asyncio.gather(*workers)

    final_results = [r for r in results if r is not None]
    return final_results, live_calls, aborted_early


def run_experiment_pipeline(
    exp_id: str,
    variant: str,
    in_path: Path,
    split: str = "validation",
    sample: int | None = 1000,
    seed: int = 20261017,
    live: bool = False,
    enum_blind: bool = False,
    concurrency: int = 8,
    max_live_failure_rate: float = 0.02,
    out_dir: Path | None = None,
) -> dict[str, Any]:
    """Execute complete experiment pipeline and write artifacts."""
    if out_dir is None:
        out_dir = Path("experiments_out") / exp_id
    out_dir.mkdir(parents=True, exist_ok=True)

    # 1. Load bundles
    bundles: list[dict[str, Any]] = []
    with in_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                bundles.append(json.loads(line))

    # 2. Filter split
    split_bundles = filter_by_split(bundles, split)
    if not split_bundles:
        raise ValueError(f"No trips found for split '{split}' in {in_path}")

    # 3. Stratified sample
    sampled_bundles = stratified_sample(split_bundles, sample_size=sample, seed=seed)

    # 4. Run variant
    t0 = time.perf_counter()

    if live:
        predictions, live_calls, aborted_early = asyncio.run(
            _execute_all_bundles(
                sampled_bundles,
                variant=variant,
                split=split,
                live=True,
                enum_blind=enum_blind,
                concurrency=concurrency,
            )
        )
    else:
        with run_10k.offline_network_guard():
            predictions, live_calls, aborted_early = asyncio.run(
                _execute_all_bundles(
                    sampled_bundles,
                    variant=variant,
                    split=split,
                    live=False,
                    enum_blind=enum_blind,
                    concurrency=concurrency,
                )
            )

    wall_time = time.perf_counter() - t0

    # 5. Write predictions.jsonl
    pred_path = out_dir / "predictions.jsonl"
    with pred_path.open("w", encoding="utf-8") as f:
        for r in predictions:
            f.write(json.dumps(r) + "\n")

    # 6. Compute metrics
    metrics = evaluate_suite(predictions, live_calls=live_calls, live=live, seed=seed)
    metrics["exp_id"] = exp_id
    metrics["variant"] = variant
    metrics["split"] = split
    metrics["sample"] = len(predictions)
    metrics["seed"] = seed
    metrics["live"] = live
    metrics["enum_blind"] = enum_blind
    metrics["concurrency"] = concurrency
    metrics["wall_time_s"] = round(wall_time, 3)
    metrics["corpus_trips_sha256"] = compute_file_sha256(in_path)
    metrics["git_sha"] = get_git_sha()
    metrics["model_id"] = f"{variant}-{'live' if live else 'offline'}"

    metrics["aborted_early"] = aborted_early
    live_failure_rate = float(metrics.get("live_failure_rate", 0.0))
    actual_live_calls = int(metrics.get("live_calls", live_calls))
    provenance = metrics.get("provenance", {})
    heuristic_fallback_count = int(provenance.get("heuristic_fallback_count", 0))
    failed_count = int(provenance.get("failed_count", metrics.get("live_failures", 0)))

    is_valid = not aborted_early and (
        (actual_live_calls > 0 and live_failure_rate <= max_live_failure_rate and heuristic_fallback_count == 0)
        if live
        else True
    )
    metrics["valid"] = is_valid

    # 7. Write metrics.json
    metrics_path = out_dir / "metrics.json"
    with metrics_path.open("w", encoding="utf-8") as f:
        json.dump(metrics, f, indent=2)

    # 8. Check gating and abort if needed
    if aborted_early:
        sys.exit(
            f"Aborted experiment {exp_id}: early abort triggered after 20 consecutive live call failures (402/429)."
        )
    if live and heuristic_fallback_count > 0:
        print(f"HEURISTIC FALLBACK DETECTED: {heuristic_fallback_count}")
        sys.exit(f"Aborted experiment {exp_id}: HEURISTIC FALLBACK DETECTED: {heuristic_fallback_count}.")
    if live and live_failure_rate > max_live_failure_rate:
        print(
            f"FAILED CALL THRESHOLD EXCEEDED: {failed_count} failures (rate {live_failure_rate:.4f} > {max_live_failure_rate})"
        )
        sys.exit(
            f"Aborted experiment {exp_id}: live_failure_rate {live_failure_rate:.4f} exceeds limit {max_live_failure_rate}."
        )

    return metrics


def main():
    parser = argparse.ArgumentParser(description="GreenSentinel Experiment Harness Runner")
    parser.add_argument("--exp-id", required=True, help="Experiment identifier (e.g. E1)")
    parser.add_argument("--variant", required=True, help="Registered variant name")
    parser.add_argument("--in", dest="in_path", required=True, type=Path, help="Input trips.jsonl")
    parser.add_argument("--split", default="validation", choices=["train", "validation", "test"], help="Dataset split")
    parser.add_argument("--sample", type=int, default=1000, help="Stratified sample count")
    parser.add_argument("--seed", type=int, default=20261017, help="Random seed for sampling")
    parser.add_argument("--live", action="store_true", help="Enable live LLM calls")
    parser.add_argument("--enum-blind", action="store_true", help="Blank cancellation enums")
    parser.add_argument("--concurrency", type=int, default=8, help="Assessment concurrency limit")
    parser.add_argument(
        "--max-live-failure-rate",
        type=float,
        default=0.02,
        help="Maximum allowed live failure rate (default: 0.02)",
    )
    parser.add_argument("--out-dir", type=Path, default=None, help="Output directory")

    args = parser.parse_args()
    metrics = run_experiment_pipeline(
        exp_id=args.exp_id,
        variant=args.variant,
        in_path=args.in_path,
        split=args.split,
        sample=args.sample,
        seed=args.seed,
        live=args.live,
        enum_blind=args.enum_blind,
        concurrency=args.concurrency,
        max_live_failure_rate=args.max_live_failure_rate,
        out_dir=args.out_dir,
    )
    print(f"Experiment {args.exp_id} complete. Macro-F1: {metrics.get('macro_f1')}")


if __name__ == "__main__":
    main()

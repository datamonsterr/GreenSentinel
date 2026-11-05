"""Offline 10k-trip benchmark runner (Issue #256).

Runs the production guardrail + Jev heuristic pipeline over
data/benchmark-10k/v1/trips.jsonl with NO live LLM calls.

Offline enforcement:
- Settings constructed with empty project_jev_api_key / openrouter_api_key
  (asserted empty after construction, so env keys cannot leak in).
- every offline run executes inside offline_network_guard, which patches
  httpx/socket to raise on any call (restored afterwards), so even a
  misconfigured key cannot reach the network.

Mapping bundle -> JevAssessmentInput (mirrors telemetry_queue_worker):
- driver = driver_profile, driver_analytics passthrough
- trip_conversation = conversation, driver_reason = driver_objection,
  customer_reports = [customer_report] if present
- telemetry = {stationary_duration_s from measured_features.approach_ssd_s,
  maneuvers = stop maneuver derived from approach_ssd_s (no wrong_direction:
  measured_features carry no detour signal), mock flag from telemetry points,
  max_speed_kmh from points, raw points passthrough}
- trip_data = {lifecycle_state/status from trip.status,
  cancellation_actor/reason from assignment,
  arrived_at/started_at from assignment only when the keys are present
  (preserves unknown-vs-None for enum-blind mode)}
- guardrail = evaluate_telemetry_window(points, [platform_incident]);
  should_short_circuit -> build_guardrail_assessment (insufficient_evidence);
  blocked-but-mock -> assess then cap_priority_for_guardrail.

Usage:
    python scripts/benchmark/run_10k.py --in data/benchmark-10k/v1/trips.jsonl \\
        --out data/benchmark-10k/v1/predictions.jsonl [--sample 2000] [--seed 20261011]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import socket
import sys
import time
from collections import Counter, defaultdict
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# --- Offline guard: HTTP and socket calls are blocked inside offline_network_guard,
# which wraps every offline run (no import-time side effects).
import httpx  # noqa: E402

from scripts.benchmark.experiments.metrics import compute_provenance_metrics  # noqa: E402
from src.config import Settings  # noqa: E402
from src.services.guardrails import (  # noqa: E402
    build_guardrail_assessment,
    cap_priority_for_guardrail,
    evaluate_telemetry_window,
    should_short_circuit,
)
from src.services.jev_assessment_service import (  # noqa: E402
    JevAssessmentInput,
    JevAssessmentService,
)

CLASSES = ["no_violation", "ERR-01", "ERR-02", "ERR-03", "ERR-04", "ERR-05", "insufficient_evidence"]
ADVERSE = {"ERR-01", "ERR-02", "ERR-03", "ERR-04", "ERR-05"}

ERR01_KEYWORDS = ("vô cớ", "từ chối", "unjustified")
ERR04_KEYWORDS = ("ảo", "ghost")

# Generator-metadata keys that must never reach the detector. Keep in sync with
# scripts/analyze_10k.py LEAK_KEYS (audit_bundle asserts a clean projection).
_SCRUB_KEYS = frozenset(
    {
        "label",
        "fraud_propensity",
        "profile_provenance",
        "label_provenance",
        "scenario",
        "expected_category",
        "expected_guardrail",
        "expected_guardrail_reason",
        "expected_outcome",
        "intent",
        "simulation_id",
        "anomaly_type",
        "anomaly_score",
        "simulation_labels",
    }
)
_SCRUB_PREFIXES = ("expected_", "simulation_", "anomaly_")


def _scrub(value):
    """Deep copy with generator-metadata keys removed (evidence boundary)."""
    if isinstance(value, dict):
        return {k: _scrub(v) for k, v in value.items() if k not in _SCRUB_KEYS and not k.startswith(_SCRUB_PREFIXES)}
    if isinstance(value, (list, tuple)):
        return [_scrub(v) for v in value]
    return value


def build_offline_service() -> JevAssessmentService:
    for var in (
        "PROJECT_JEV_API_KEY",
        "PROJECT_JEV_TEST_API_KEY",
        "OPENROUTER_API_KEY",
        "JEV_API_KEY",
    ):
        os.environ.pop(var, None)
    settings = Settings(
        project_jev_api_key="",
        openrouter_api_key="",
        jev_allow_heuristic_fallback=True,
    )
    assert not settings.project_jev_api_key, "offline guard: project_jev_api_key not empty"
    assert not settings.openrouter_api_key, "offline guard: openrouter_api_key not empty"
    return JevAssessmentService(settings=settings)


def build_live_service() -> JevAssessmentService:
    """Real Jev model service (reads provider keys from the environment)."""
    return JevAssessmentService(settings=Settings())


def bundle_to_input(bundle: dict) -> tuple[JevAssessmentInput, list[dict], dict]:
    """Map one benchmark bundle to (JevAssessmentInput, points, trip_data).

    Stationary features come from the detector-side FeatureWindow over raw
    points — never from generator-side measured_features summaries, so mutated
    generator metadata cannot change the detector input (see audit_bundle).
    Uses shared map_telemetry_event_to_jev_input for production parity.
    """
    from src.services.jev_state_builder import map_telemetry_event_to_jev_input

    jev_inp = map_telemetry_event_to_jev_input(bundle)
    points = jev_inp.telemetry.get("points") or []
    return jev_inp, points, jev_inp.trip_data


def blank_cancellation_enums(bundle: dict) -> dict:
    """Deep copy with every cancellation/outcome enum removed (enum-blind, Issue #281).

    Strips status, actor, reason, and the fare/outcome artifacts that would
    otherwise reveal cancelled-vs-completed to the detector.
    """
    import copy

    out = copy.deepcopy(bundle)
    out["trip"].pop("status", None)
    out["trip"].pop("cancelled_at", None)
    out["trip"].pop("completed_at", None)
    out["trip"].pop("fare_amount_vnd", None)
    out["trip"].pop("fare_state", None)
    out["trip"].pop("cancellation_fee_vnd", None)
    for key in (
        "state",
        "cancellation_actor",
        "cancellation_reason",
        "offered_at",
        "accepted_at",
        "arrived_at",
        "started_at",
        "ended_at",
    ):
        out["assignment"].pop(key, None)
    out.pop("lifecycle_state", None)
    return out


def has_keyword(text: str | None, keywords: tuple[str, ...]) -> bool:
    if not text:
        return False
    low = text.lower()
    return any(k.lower() in low for k in keywords)


@contextmanager
def offline_network_guard():
    """Reject provider calls and socket connections only inside benchmark execution."""

    attempted = False

    def blocked(*args, **kwargs):
        nonlocal attempted
        attempted = True
        raise RuntimeError("offline benchmark forbids network access")

    async def async_blocked(*args, **kwargs):
        blocked()

    with (
        patch.object(httpx.AsyncClient, "post", async_blocked),
        patch.object(httpx.AsyncClient, "request", async_blocked),
        patch.object(httpx.Client, "request", blocked),
        patch.object(socket.socket, "connect", blocked),
        patch.object(socket.socket, "connect_ex", blocked),
        patch.object(socket, "create_connection", blocked),
    ):
        yield
    if attempted:
        raise RuntimeError(
            "offline benchmark attempted network access, even though provider fallback swallowed the error"
        )


async def run_bundles(
    bundles: list[dict], service: JevAssessmentService, *, enum_blind: bool = False, live: bool = False
) -> list[dict]:
    if live:
        return await _run_bundles(bundles, service, enum_blind=enum_blind)
    with offline_network_guard():
        return await _run_bundles(bundles, service, enum_blind=enum_blind)


async def _run_bundles(bundles: list[dict], service: JevAssessmentService, *, enum_blind: bool = False) -> list[dict]:
    """Run guardrail + heuristic assess per trip. Returns prediction records."""
    out: list[dict] = []
    for b in bundles:
        if enum_blind:
            b = blank_cancellation_enums(b)
        jev_inp, points, _ = bundle_to_input(b)
        incident = b.get("platform_incident")
        incidents = [incident] if isinstance(incident, dict) else []
        guardrail = evaluate_telemetry_window(points, incidents)
        blocked = bool(guardrail.blocked)
        reason = guardrail.reason.value if guardrail.reason else None
        t0 = time.perf_counter()
        if should_short_circuit(guardrail):
            a = build_guardrail_assessment(guardrail)
            category = a["category"]
            confidence = float(a["confidence"])
            tier = int(a["priority_tier"])
            reason_codes = list(a["reason_codes"])
            model_used = "guardrail_short_circuit"
            fallback_model_used = False
            assessment_source = "guardrail"
            cost = 0.0
            input_tokens = 0
        else:
            res = await service.assess(jev_inp)
            capped = cap_priority_for_guardrail(res.model_dump(), guardrail)
            category = str(capped.get("category"))
            confidence = float(capped.get("confidence"))
            tier = int(capped.get("priority_tier"))
            reason_codes = list(capped.get("reason_codes") or [])
            model_used = getattr(res, "model_used", None) or capped.get("model_used") or "unknown"
            fallback_model_used = getattr(res, "fallback_model_used", False) or bool(
                capped.get("fallback_model_used", False)
            )
            assessment_source = getattr(res, "assessment_source", None) or capped.get("assessment_source") or "model"
            cost = float(getattr(res, "cost", 0.0) or capped.get("cost", 0.0))
            input_tokens = int(getattr(res, "input_tokens", 0) or capped.get("input_tokens", 0))
        latency_ms = (time.perf_counter() - t0) * 1000.0
        sufficiency = (
            "blocked" if blocked else ("unknown" if not points or category == "insufficient_evidence" else "available")
        )
        out.append(
            {
                "trip_ref": b.get("trip_ref"),
                "label": b.get("label"),
                "predicted_category": category,
                "confidence": confidence,
                "uncalibrated_model_confidence": confidence,
                "score_semantics": "uncalibrated_model_confidence",
                "evidence_sufficiency": sufficiency,
                "priority_tier": tier,
                "reason_codes": reason_codes,
                "guardrail_blocked": blocked,
                "guardrail_reason": reason,
                "latency_ms": round(latency_ms, 3),
                "model_used": model_used,
                "fallback_model_used": fallback_model_used,
                "assessment_source": assessment_source,
                "cost": cost,
                "input_tokens": input_tokens,
            }
        )
    return out


def compute_metrics(records: list[dict], bundles_by_ref: dict, live: bool = False) -> dict:
    n = len(records)
    per_class: dict[str, dict] = {}
    for cls in CLASSES:
        tp = sum(1 for r in records if r["label"] == cls and r["predicted_category"] == cls)
        fp = sum(1 for r in records if r["label"] != cls and r["predicted_category"] == cls)
        fn = sum(1 for r in records if r["label"] == cls and r["predicted_category"] != cls)
        prec = tp / (tp + fp) if (tp + fp) else 0.0
        rec = tp / (tp + fn) if (tp + fn) else 0.0
        f1 = 2 * prec * rec / (prec + rec) if (prec + rec) else 0.0
        per_class[cls] = {
            "n": sum(1 for r in records if r["label"] == cls),
            "predicted": sum(1 for r in records if r["predicted_category"] == cls),
            "tp": tp,
            "fp": fp,
            "fn": fn,
            "precision": round(prec, 4),
            "recall": round(rec, 4),
            "f1": round(f1, 4),
        }
    accuracy = sum(1 for r in records if r["label"] == r["predicted_category"]) / n if n else 0.0
    macro_f1 = sum(v["f1"] for v in per_class.values()) / len(per_class)

    confusion = {t: {p: 0 for p in CLASSES} for t in CLASSES}
    for r in records:
        true, pred = r["label"], r["predicted_category"]
        if true in confusion and pred in confusion[true]:
            confusion[true][pred] += 1

    violations = [
        r["trip_ref"] for r in records if r["label"] == "insufficient_evidence" and r["predicted_category"] in ADVERSE
    ]

    tier_dist: dict[str, dict[str, int]] = {}
    for r in records:
        tier_dist.setdefault(r["label"], Counter())[f"P{r['priority_tier']}"] += 1
    tier_dist = {k: dict(v) for k, v in tier_dist.items()}

    # Calibration: correctness of category prediction vs constant confidence.
    n_bins = 10
    bins = [{"n": 0, "acc": 0.0, "conf": 0.0} for _ in range(n_bins)]
    brier_sum = 0.0
    for r in records:
        correct = 1.0 if r["label"] == r["predicted_category"] else 0.0
        conf = float(r["confidence"])
        brier_sum += (conf - correct) ** 2
        idx = min(int(conf * n_bins), n_bins - 1)
        bins[idx]["n"] += 1
        bins[idx]["acc"] += correct
        bins[idx]["conf"] += conf
    ece = 0.0
    bin_rows = []
    for i, b in enumerate(bins):
        if b["n"]:
            acc = b["acc"] / b["n"]
            conf = b["conf"] / b["n"]
            ece += abs(acc - conf) * b["n"] / n
            bin_rows.append(
                {"bin": f"[{i / 10:.1f},{(i + 1) / 10:.1f})", "n": b["n"], "acc": round(acc, 4), "conf": round(conf, 4)}
            )
    brier = brier_sum / n if n else 0.0

    # Gap 1: gridlock SSD false positives (ERR-02 on honest gridlock trips).
    grid = [r for r in records if bundles_by_ref.get(r["trip_ref"], {}).get("gridlock_subset") is True]
    grid_fp = sum(1 for r in grid if r["predicted_category"] == "ERR-02")
    gap_gridlock = {
        "n_gridlock": len(grid),
        "err02_predicted": grid_fp,
        "fp_rate": round(grid_fp / len(grid), 4) if grid else 0.0,
    }

    # Gap 3: keyword brittleness — keyword vs paraphrase recall for ERR-01/ERR-04
    # split by keyword presence in driver_objection text (trap flags not persisted).
    gap_kw: dict[str, dict] = {}
    for cls, kws in (("ERR-01", ERR01_KEYWORDS), ("ERR-04", ERR04_KEYWORDS)):
        kw_rec, par_rec = [], []
        for r in records:
            if r["label"] != cls:
                continue
            obj = (bundles_by_ref.get(r["trip_ref"], {}).get("driver_objection") or {}).get("text")
            (kw_rec if has_keyword(obj, kws) else par_rec).append(r)

        def _recall(rows: list[dict]) -> float:
            return sum(1 for x in rows if x["predicted_category"] == cls) / len(rows) if rows else 0.0

        gap_kw[cls] = {
            "keyword_n": len(kw_rec),
            "keyword_recall": round(_recall(kw_rec), 4),
            "paraphrase_n": len(par_rec),
            "paraphrase_recall": round(_recall(par_rec), 4),
        }

    lat = [r["latency_ms"] for r in records]
    lat_sorted = sorted(lat)

    def _pct(p: float) -> float:
        return lat_sorted[min(int(p / 100 * len(lat_sorted)), len(lat_sorted) - 1)] if lat_sorted else 0.0

    latency = {
        "mean_ms": round(sum(lat) / len(lat), 3) if lat else 0.0,
        "p50_ms": round(_pct(50), 3),
        "p95_ms": round(_pct(95), 3),
        "max_ms": round(max(lat), 3) if lat else 0.0,
    }

    return {
        "n": n,
        "accuracy": round(accuracy, 4),
        "macro_f1": round(macro_f1, 4),
        "per_class": per_class,
        "confusion": confusion,
        "guardrail": {
            "violations": len(violations),
            "violation_refs": violations[:50],
            "blocked_total": sum(1 for r in records if r["guardrail_blocked"]),
        },
        "priority_tier_by_label": tier_dist,
        "evidence_sufficiency_by_label": {
            label: dict(Counter(r["evidence_sufficiency"] for r in records if r["label"] == label))
            for label in sorted({r["label"] for r in records})
        },
        "calibration": {
            "ece_10bin": round(ece, 4),
            "brier": round(brier, 4),
            "bins": bin_rows,
            "caveat": "uncalibrated_model_confidence: heuristic emits constant "
            "confidence per branch, so ECE/Brier diagnose the constant scheme, "
            "not a learned model.",
        },
        "gap_gridlock_ssd_fp": gap_gridlock,
        "gap_clock_jitter": {
            "note": "external figure, no rebuild (--noise stress rebuild of N=500 "
            "too slow). Per docs/data/TELEMETRY_DISTRIBUTION.md finding 3 "
            "(400-trip stress variant): full-stress DIC detection 50%; "
            "without clock jitter 66%; without jitter and stall accuracy "
            "<=15m 73%.",
            "stress_dic_detection": 0.50,
            "stress_no_clock_jitter": 0.66,
        },
        "gap_keyword_brittleness": gap_kw,
        "latency_ms": latency,
        "provenance": compute_provenance_metrics(records, live=live),
    }


def stratified_sample(bundles: list[dict], n: int, seed: int) -> list[dict]:
    import random

    rng = random.Random(seed)
    by_label: dict[str, list[dict]] = defaultdict(list)
    for b in bundles:
        by_label[b.get("label")].append(b)
    total = len(bundles)
    quota = {k: int(round(len(v) / total * n)) for k, v in by_label.items()}
    # Fix rounding drift on largest stratum.
    drift = n - sum(quota.values())
    if drift:
        biggest = max(by_label, key=lambda k: len(by_label[k]))
        quota[biggest] += drift
    out: list[dict] = []
    for k, v in by_label.items():
        out.extend(rng.sample(v, min(quota[k], len(v))))
    rng.shuffle(out)
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Offline 10k benchmark runner (heuristic only)")
    ap.add_argument("--in", dest="inp", default="data/benchmark-10k/v1/trips.jsonl")
    ap.add_argument("--out", dest="out", default="data/benchmark-10k/v1/predictions.jsonl")
    ap.add_argument("--metrics-out", default="notebooks/benchmark10k/metrics.json")
    ap.add_argument("--sample", type=int, default=0, help="0 = full run; else stratified sample size")
    ap.add_argument("--seed", type=int, default=20261011)
    ap.add_argument("--enum-blind", action="store_true", help="strip cancellation enums before detection")
    ap.add_argument(
        "--live", action="store_true", help="use the real Jev model (provider keys from env); default offline"
    )
    args = ap.parse_args(argv)

    inp_path = (REPO_ROOT / args.inp) if not Path(args.inp).is_absolute() else Path(args.inp)
    bundles = [json.loads(line) for line in inp_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    print(f"loaded {len(bundles)} bundles from {inp_path}", flush=True)
    sampled = False
    if args.sample and args.sample < len(bundles):
        bundles = stratified_sample(bundles, args.sample, args.seed)
        sampled = True
        print(f"stratified sample n={len(bundles)} seed={args.seed}", flush=True)

    service = build_live_service() if args.live else build_offline_service()
    t0 = time.time()
    records = asyncio.run(run_bundles(bundles, service, enum_blind=args.enum_blind, live=args.live))
    wall_s = time.time() - t0

    out_path = (REPO_ROOT / args.out) if not Path(args.out).is_absolute() else Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    pred_rows = [
        {
            "trip_ref": r["trip_ref"],
            "predicted_category": r["predicted_category"],
            "confidence": r["confidence"],
            "priority_tier": r["priority_tier"],
            "reason_codes": r["reason_codes"],
            "guardrail_blocked": r["guardrail_blocked"],
            "latency_ms": r["latency_ms"],
            "model_used": r.get("model_used"),
            "fallback_model_used": r.get("fallback_model_used"),
            "assessment_source": r.get("assessment_source"),
        }
        for r in records
    ]
    with open(out_path, "w", encoding="utf-8") as f:
        for row in pred_rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    by_ref = {b.get("trip_ref"): b for b in bundles}
    metrics = compute_metrics(records, by_ref, live=args.live)
    metrics["runtime_wall_s"] = round(wall_s, 1)
    metrics["sampled"] = sampled
    metrics["enum_blind"] = args.enum_blind
    metrics["live"] = args.live
    metrics["sample_seed"] = args.seed if sampled else None
    metrics["input"] = str(inp_path)
    metrics["predictions"] = str(out_path)

    if args.live:
        heuristic_fallback_count = metrics.get("provenance", {}).get("heuristic_fallback_count", 0)
        failed_count = metrics.get("provenance", {}).get("failed_count", 0)
        if heuristic_fallback_count > 0:
            print(f"HEURISTIC FALLBACK DETECTED: {heuristic_fallback_count}")
        metrics["valid"] = not (heuristic_fallback_count > 0 or failed_count > 0)

    m_path = (REPO_ROOT / args.metrics_out) if not Path(args.metrics_out).is_absolute() else Path(args.metrics_out)
    m_path.parent.mkdir(parents=True, exist_ok=True)
    m_path.write_text(json.dumps(metrics, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(
        f"wall {wall_s:.1f}s n={len(records)} acc={metrics['accuracy']} "
        f"macro_f1={metrics['macro_f1']} violations={metrics['guardrail']['violations']} "
        f"ece={metrics['calibration']['ece_10bin']} brier={metrics['calibration']['brier']}"
    )
    print(f"predictions -> {out_path}\nmetrics -> {m_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

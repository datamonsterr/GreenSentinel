"""Deterministic 10k-trip fraud benchmark dataset builder (Issue #254).

Builds data/benchmark-10k/v1/ from config/benchmark_distribution.yaml:
trips.jsonl (one per-trip bundle per line), manifest.json, labels.csv,
sample_100.jsonl. Same seed -> byte-identical manifest checksums.

Usage: python scripts/benchmark/build_10k.py --n 10000 --seed 20261011 \\
    --out data/benchmark-10k --noise happy

Stdlib + numpy + pyyaml only (plus repo-local dialogue_synth,
population_synth, and src.services.feature_engineering).
"""

from __future__ import annotations

import argparse
import copy
import csv
import hashlib
import json
import math
import random
import subprocess
import sys
import time
import uuid
from datetime import UTC, datetime, timedelta
from functools import cache
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.benchmark.dialogue_synth import (  # noqa: E402
    synthesize_customer_report,
    synthesize_dialogue,
    synthesize_objection_reason,
)
from scripts.benchmark.population_synth import (  # noqa: E402
    BENCHMARK_ORG_ID,
    sample_fraud_driver_ids,
    synthesize_driver_analytics,
    synthesize_drivers,
    synthesize_passengers,
)
from scripts.telemetry_generation import (  # noqa: E402
    generate_trip,
    load_config,
    make_rng,
    sample_quantiles,
)
from src.services.feature_engineering import compute_feature_window  # noqa: E402

BUILDER_VERSION = "v2"
CONFIG_PATH = REPO_ROOT / "config" / "benchmark_distribution.yaml"
CLOCK_ORIGIN = datetime(2026, 9, 22, 6, 0, 0, tzinfo=UTC)

CLASS_MIX_10K = {
    "no_violation": 7000,
    "ERR-02": 800,
    "insufficient_evidence": 600,
    "ERR-01": 500,
    "ERR-03": 500,
    "ERR-04": 300,
    "ERR-05": 300,
}

SCENARIO_FOR_LABEL = {
    "no_violation": "normal_trip",
    "ERR-02": "driver_stall_cancel",
    "ERR-01": "driver_stall_cancel",
    "ERR-03": "route_deviation",
    "ERR-04": "normal_trip",  # ghost: normal geometry, completed lifecycle, no pickup
    "ERR-05": "gps_spoofing",
    "insufficient_evidence": "technical_dropout",
}

CONTEXT_FOR_LABEL = {
    "no_violation": "normal_trip",
    "ERR-01": "err01_unjustified_cancel",
    "ERR-02": "err02_stall",
    "ERR-03": "err03_deviation",
    "ERR-04": "err04_phantom",
    "ERR-05": "err05_fake_gps",
    "insufficient_evidence": "technical_dropout",
}

# Fraud-variant subsets (Issues #275/#276): shares of their parent label.
# G1 slow-crawl (traffic clear, low SSD) and G2 loop geometry (tort >= 2)
# are hard cases the SSD/DAVI heuristic misses by construction.
SLOWCRAWL_CONTEXT = "err02_slowcrawl"
LOOP_CONTEXT = "err03_loop"


def scenario_for_label(py_rng: random.Random, label: str, cfg: dict) -> tuple[str, bool, bool]:
    """Return (scenario, slowcrawl_subset, loop_subset) for one trip label."""
    bm = cfg.get("benchmark") or {}
    if label == "ERR-02" and py_rng.random() < float(bm.get("slowcrawl_subset_share", 0.30)):
        return "slow_crawl_fraud", True, False
    if label == "ERR-03" and py_rng.random() < float(bm.get("loop_subset_share", 0.30)):
        return "loop_deviation", False, True
    return SCENARIO_FOR_LABEL[label], False, False


def context_for_trip(label: str, slowcrawl: bool, loop: bool, gridlock: bool) -> str:
    if gridlock:
        return "traffic_gridlock"
    if slowcrawl:
        return SLOWCRAWL_CONTEXT
    if loop:
        return LOOP_CONTEXT
    return CONTEXT_FOR_LABEL[label]


# Hanoi intra-city landmarks (lon/lat WGS84). Coordinates are approximate demo
# values in the generate_synthetic_data.py name style; pairs 1-8 km apart.
LANDMARKS = [
    {"name": "Ho Guom", "lat": 21.0285, "lon": 105.8542, "district": "Hoan Kiem"},
    {"name": "Ga Ha Noi", "lat": 21.0243, "lon": 105.8412, "district": "Dong Da"},
    {"name": "Benh vien Bach Mai", "lat": 21.0015, "lon": 105.8490, "district": "Dong Da"},
    {"name": "Times City", "lat": 21.0030, "lon": 105.8700, "district": "Hai Ba Trung"},
    {"name": "Royal City", "lat": 21.0010, "lon": 105.8170, "district": "Thanh Xuan"},
    {"name": "Vincom Metropolis", "lat": 21.0317, "lon": 105.8127, "district": "Ba Dinh"},
    {"name": "Lotte Center", "lat": 21.0326, "lon": 105.8105, "district": "Ba Dinh"},
    {"name": "Dai hoc Quoc gia", "lat": 21.0375, "lon": 105.7830, "district": "Cau Giay"},
    {"name": "Keangnam Landmark 72", "lat": 21.0167, "lon": 105.7839, "district": "Nam Tu Liem"},
    {"name": "Ben xe My Dinh", "lat": 21.0280, "lon": 105.7710, "district": "Nam Tu Liem"},
    {"name": "Ho Tay", "lat": 21.0550, "lon": 105.8240, "district": "Tay Ho"},
    {"name": "Ben xe Giap Bat", "lat": 20.9910, "lon": 105.8390, "district": "Hoang Mai"},
    {"name": "VinUni Ocean Park", "lat": 21.0150, "lon": 105.9460, "district": "Gia Lam"},
    {"name": "Aeon Mall Long Bien", "lat": 21.0220, "lon": 105.8950, "district": "Long Bien"},
]

PRIOR_TABLE = {
    "speed_mean_trip": "measured-porto 7.55 m/s (Porto path/time); NYC 5.4 reference",
    "speed_moving_gamma": "measured-porto mean 7.0, shape assumption; segment p50 5.84 / p95 23.99",
    "tortuosity_normal": "measured-porto 1.12-1.45 (WGS84); quantile shape assumption",
    "tortuosity_detour": "measured-mipo AiSq p50 1.5622 (StSt10M diverged, excluded)",
    "tortuosity_loop": "assumption loop-tail 2.0-3.9 (#276, geometric: one loop adds ~2πr path)",
    "slowcrawl_share": "assumption 0.30 of ERR-02 (#275); crawl 0.8-2.0 m/s clear traffic",
    "loop_share": "assumption 0.30 of ERR-03 (#276)",
    "duration_distance": "measured-nyc med 703 s / p50 2736 m; Porto path p50 3964 m; normal 300-900 s, 1.5-8 km",
    "scheduler": "measured-nyc hour anchors h04/h05/h17/h18 + full weekday vector; shape fill assumption",
    "honest_implausible_jump": "measured-porto 0.151% segments >50 m/s; threshold 50 kept",
    "dialogue": "measured-multiwoz 4-12 turns cap, passenger p50 11 words",
    "geography": "assumption Hanoi landmarks, pairs 1-8 km",
    "prevalence": "measured-paysim 0.13% reference; mix is ENRICHMENT, not natural prevalence",
    "population": "assumption (no public honest-vs-fraud driver distributions)",
}

REQUIRED_BUNDLE_KEYS = frozenset(
    {
        "trip_ref",
        "trip_id",
        "assignment_id",
        "driver_id",
        "passenger_id",
        "vehicle_id",
        "label",
        "scenario",
        "requested_at",
        "pickup",
        "dropoff",
        "route",
        "telemetry",
        "traffic_observation",
        "platform_incident",
        "trip",
        "assignment",
        "conversation",
        "dialogue_mode",
        "legit_cancel_subset",
        "slowcrawl_subset",
        "loop_subset",
        "customer_actions",
        "passenger_feedback",
        "driver_objection",
        "customer_report",
        "driver_profile",
        "driver_analytics",
        "vehicle",
        "measured_features",
        "label_provenance",
    }
)

LEGIT_CANCEL_SHARE = 0.05

# Benign passenger-side cancel reasons for the no_violation legit-cancel subset
# (Issue #270). Label stays no_violation; only lifecycle flips to cancelled.
LEGIT_CANCEL_REASONS = (
    {"reason": "passenger_plan_changed", "vi": "Đổi kế hoạch nên hủy chuyến", "en": "Plans changed so I cancelled"},
    {
        "reason": "passenger_wrong_pickup",
        "vi": "Đặt nhầm điểm đón nên hủy đặt lại",
        "en": "Wrong pickup point, rebooking",
    },
    {
        "reason": "passenger_found_other_ride",
        "vi": "Đi nhờ xe người quen rồi",
        "en": "Got a ride from a friend instead",
    },
    {
        "reason": "passenger_running_late",
        "vi": "Trễ giờ nên không đi nữa",
        "en": "Running too late, trip no longer needed",
    },
    {
        "reason": "passenger_destination_changed",
        "vi": "Đổi điểm đến vào phút chót",
        "en": "Destination changed last minute",
    },
    {"reason": "passenger_price_too_high", "vi": "Thấy cước cao quá nên thôi", "en": "Fare looked too high, cancelled"},
    {
        "reason": "passenger_driver_too_far",
        "vi": "Tài xế ở xa quá, em hủy nhé",
        "en": "Driver too far away, cancelling",
    },
    {"reason": "passenger_emergency", "vi": "Có việc đột xuất, xin hủy chuyến", "en": "Emergency came up, must cancel"},
    {
        "reason": "passenger_duplicate_booking",
        "vi": "Lỡ đặt trùng 2 cuốc, hủy một",
        "en": "Accidental duplicate booking",
    },
    {"reason": "passenger_heavy_rain", "vi": "Mưa to quá, để lúc khác đi", "en": "Rain too heavy, going another time"},
    {"reason": "passenger_kid_situation", "vi": "Bé quấy quá nên hủy chuyến", "en": "Kid fussing, cancelling the trip"},
    {
        "reason": "passenger_traffic_heavy",
        "vi": "Kẹt xe cứng, em hủy để đi tàu",
        "en": "Gridlock, switching to the train",
    },
)

COMPLAINT_CATEGORIES = ("late_pickup", "rude_driver", "unsafe_driving", "overcharge_dispute", "no_show_ghost")
PRAISE_CATEGORIES = ("polite", "clean_car", "fast_pickup", "safe_driving")
NEUTRAL_CATEGORY = "neutral"

FEEDBACK_BANK_PATH = REPO_ROOT / "data" / "conversation_bank" / "feedback_bank.yaml"


def class_counts_for_n(n: int) -> dict[str, int]:
    """Exact 10k mix; largest-remainder scaling for other n (tests/tiny builds)."""
    if n == 10000:
        return dict(CLASS_MIX_10K)
    total = sum(CLASS_MIX_10K.values())
    raw = {k: v * n / total for k, v in CLASS_MIX_10K.items()}
    counts = {k: int(math.floor(x)) for k, x in raw.items()}
    remainder = n - sum(counts.values())
    for k in sorted(raw, key=lambda k: raw[k] - counts[k], reverse=True)[:remainder]:
        counts[k] += 1
    return counts


def haversine_m(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def det_uuid(rng: random.Random) -> str:
    return str(uuid.UUID(int=rng.getrandbits(128), version=4))


def sample_schedule(py_rng: random.Random, hour_w: list[float], day_w: list[float]) -> datetime:
    day = py_rng.choices(range(7), weights=day_w, k=1)[0]  # 0=Mon
    hour = py_rng.choices(range(24), weights=hour_w, k=1)[0]
    week = py_rng.randrange(4)
    base = datetime(2026, 9, 21, 0, 0, 0, tzinfo=UTC)  # a Monday
    return base + timedelta(days=week * 7 + day, hours=hour, minutes=py_rng.randrange(60), seconds=py_rng.randrange(60))


def sample_landmark_pair(py_rng: random.Random, lo_km: float, hi_km: float) -> tuple[dict, dict]:
    for _ in range(200):
        a, b = py_rng.sample(LANDMARKS, 2)
        d = haversine_m(a["lon"], a["lat"], b["lon"], b["lat"])
        if lo_km * 1000 <= d <= hi_km * 1000:
            return a, b
    # Deterministic fallback: closest pair to 3 km among 200 draws is re-drawn;
    # fall back to the first valid pair found by exhaustive scan.
    best = None
    for a in LANDMARKS:
        for b in LANDMARKS:
            if a is b:
                continue
            d = haversine_m(a["lon"], a["lat"], b["lon"], b["lat"])
            if lo_km * 1000 <= d <= hi_km * 1000 and (best is None or abs(d - 3000) < best[0]):
                best = (abs(d - 3000), a, b)
    assert best is not None
    return best[1], best[2]


def jitter_lonlat(py_rng: random.Random, lon: float, lat: float, max_m: float = 150.0) -> tuple[float, float]:
    dx = py_rng.uniform(-max_m, max_m)
    dy = py_rng.uniform(-max_m, max_m)
    lat2 = lat + math.degrees(dy / 6371000.0)
    lon2 = lon + math.degrees(dx / (6371000.0 * math.cos(math.radians(lat))))
    return round(lon2, 7), round(lat2, 7)


def git_sha() -> str | None:
    try:
        out = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, timeout=10, cwd=REPO_ROOT)
        return out.stdout.strip() or None
    except Exception:
        return None


@cache
def load_feedback_bank() -> dict:
    with open(FEEDBACK_BANK_PATH, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def feedback_pool(category: str) -> tuple:
    bank = load_feedback_bank()
    for group in ("complaint", "praise"):
        entries = (bank.get(group) or {}).get(category)
        if entries:
            return tuple(entries)
    if category == NEUTRAL_CATEGORY:
        return tuple(bank["neutral"]["general"])
    raise ValueError(f"unknown feedback category {category!r}")


def assign_dialogue_mode(py_rng: random.Random, label: str, cfg: dict) -> str:
    modes = (cfg.get("benchmark") or {}).get("dialogue_modes") or {}
    probs = modes.get(label, modes.get("default", {})) or {}
    r = py_rng.random()
    if r < float(probs.get("empty", 0.0)):
        return "empty"
    if r < float(probs.get("empty", 0.0)) + float(probs.get("customer_only", 0.0)):
        return "customer_only"
    return "full"


def feedback_category_for_label(py_rng: random.Random, label: str) -> str:
    if label == "ERR-01":
        return "no_show_ghost" if py_rng.random() < 0.7 else "rude_driver"
    if label == "ERR-02":
        return "late_pickup"
    if label == "ERR-03":
        return "overcharge_dispute"
    if label == "ERR-04":
        return "no_show_ghost"
    if label == "ERR-05":
        return "unsafe_driving"
    if label == "no_violation":
        if py_rng.random() < 0.8:
            return py_rng.choice(list(PRAISE_CATEGORIES))
        return NEUTRAL_CATEGORY
    return NEUTRAL_CATEGORY


def synthesize_passenger_feedback(py_rng: random.Random, label: str) -> dict:
    if py_rng.random() < 0.30:
        rating = None
    else:
        u = py_rng.random()
        if label in ("ERR-01", "ERR-02"):
            rating = py_rng.choice([1, 2]) if u < 0.8 else py_rng.choice([3, 4, 5])
        elif label == "ERR-04":
            rating = 1 if u < 0.7 else (2 if u < 0.9 else py_rng.choice([3, 4, 5]))
        elif label == "no_violation":
            rating = py_rng.choice([4, 5]) if u < 0.7 else py_rng.choice([1, 2, 3])
        elif label in ("ERR-03", "ERR-05"):
            rating = py_rng.choice([1, 2]) if u < 0.6 else py_rng.choice([3, 4, 5])
        else:
            rating = py_rng.choice([2, 3, 4])
    category = feedback_category_for_label(py_rng, label)
    entry = py_rng.choice(feedback_pool(category))
    return {"rating": rating, "category": category, "text": str(entry["text"])}


def build_customer_actions(
    conversation: list[dict], feedback: dict | None, trip_status: str, arrived_at: str | None
) -> list[dict]:
    actions: list[dict] = []
    last_offset = conversation[-1]["sent_at_offset_s"] if conversation else 0
    if conversation:
        actions.append({"action": "chat_opened", "at_offset_s": conversation[0]["sent_at_offset_s"]})
        actions.append({"action": "message_sent", "at_offset_s": last_offset})
    if trip_status == "cancelled" and arrived_at is None:
        actions.append({"action": "cancelled_before_pickup", "at_offset_s": last_offset})
    if (feedback or {}).get("rating") is not None:
        actions.append({"action": "rated", "at_offset_s": last_offset + 60})
    actions.sort(key=lambda a: a["at_offset_s"])
    return actions


def _config_version() -> str:
    try:
        return str(load_config(CONFIG_PATH).get("version", "0.4.0-benchmark"))
    except Exception:
        return "0.4.0-benchmark"


def check_gates(bundles: list[dict], gates: dict) -> list[dict[str, object]]:
    """FeatureWindow acceptance gates. Pure function over measured_features."""

    def subset(pred):
        return [b for b in bundles if pred(b)]

    def frac(rows, key, op, thr):
        if not rows:
            return 1.0, 0
        ok = sum(1 for b in rows if (v := b["measured_features"].get(key)) is not None and op(v, thr))
        return ok / len(rows), len(rows)

    results = []
    err02 = subset(lambda b: b["label"] == "ERR-02" and not b.get("slowcrawl_subset"))
    f, n = frac(err02, "approach_ssd_s", lambda v, t: v >= t, 180)
    results.append(
        {
            "gate": "ERR-02 SSD>=180",
            "required": gates["err02_ssd_cover"],
            "measured": round(f, 4),
            "n": n,
            "pass": bool(f >= gates["err02_ssd_cover"]),
        }
    )
    slow = subset(lambda b: b.get("slowcrawl_subset") is True)
    f, n = frac(slow, "davi", lambda v, t: v > t, gates["slowcrawl_davi_min"])
    results.append(
        {
            "gate": "slowcrawl DAVI>0.3",
            "required": gates["slowcrawl_davi_cover"],
            "measured": round(f, 4),
            "n": n,
            "pass": bool(f >= gates["slowcrawl_davi_cover"]),
        }
    )
    f, n = frac(slow, "approach_ssd_s", lambda v, t: v < t, gates["slowcrawl_ssd_max_s"])
    results.append(
        {
            "gate": "slowcrawl SSD<180",
            "required": gates["slowcrawl_ssd_cover"],
            "measured": round(f, 4),
            "n": n,
            "pass": bool(f >= gates["slowcrawl_ssd_cover"]),
        }
    )
    loop = subset(lambda b: b.get("loop_subset") is True)
    if loop:
        ok = sum(1 for b in loop if (b.get("route") or {}).get("tortuosity", 0) >= gates["loop_tort_min"])
        f = ok / len(loop)
    else:
        f = 1.0
    results.append(
        {
            "gate": "loop tort>=2.0",
            "required": gates["loop_tort_cover"],
            "measured": round(f, 4),
            "n": len(loop),
            "pass": bool(f >= gates["loop_tort_cover"]),
        }
    )
    f, n = frac(loop, "davi", lambda v, t: v < t, gates["loop_davi_max"])
    results.append(
        {
            "gate": "loop DAVI<0",
            "required": gates["loop_davi_cover"],
            "measured": round(f, 4),
            "n": n,
            "pass": bool(f >= gates["loop_davi_cover"]),
        }
    )
    grid = subset(lambda b: b.get("gridlock_subset") is True)
    f, n = frac(grid, "davi", lambda v, t: v > t, gates["gridlock_davi_min"])
    results.append(
        {
            "gate": "gridlock DAVI>0.5",
            "required": gates["gridlock_davi_cover"],
            "measured": round(f, 4),
            "n": n,
            "pass": bool(f >= gates["gridlock_davi_cover"]),
        }
    )
    drop = subset(lambda b: b["label"] == "insufficient_evidence")
    f, n = frac(drop, "max_gap_s", lambda v, t: v > t, gates["dropout_gap_min_s"])
    results.append(
        {"gate": "dropout max_gap>30", "required": 1.0, "measured": round(f, 4), "n": n, "pass": bool(f >= 1.0)}
    )
    spoof = subset(lambda b: b["label"] == "ERR-05")
    f, n = frac(spoof, "mock_ratio", lambda v, t: v >= t, gates["spoof_mock_min"])
    results.append(
        {"gate": "spoof mock>=0.8", "required": 1.0, "measured": round(f, 4), "n": n, "pass": bool(f >= 1.0)}
    )
    normal = subset(lambda b: b["label"] == "no_violation")
    f, n = frac(normal, "approach_ssd_s", lambda v, t: v < t, gates["normal_ssd_max_s"])
    results.append(
        {
            "gate": "normal SSD<60",
            "required": gates["normal_ssd_cover"],
            "measured": round(f, 4),
            "n": n,
            "pass": bool(f >= gates["normal_ssd_cover"]),
        }
    )
    return results


def build_trip(idx: int, label: str, ctx: dict, ref_prefix: str = "bm_v1_") -> dict:
    cfg, seed = ctx["config"], ctx["seed"]
    np_rng = make_rng(cfg, seed=seed, stream=idx)
    py_rng = random.Random((seed % 2**31) * 20011 + idx)
    sched = cfg["benchmark"]["scheduler"]
    geo = cfg["benchmark"]["geography"]

    t0 = sample_schedule(py_rng, sched["hour_weights"], sched["weekday_weights"])
    landmark_sampler = ctx.get("landmark_sampler", sample_landmark_pair)
    lm_a, lm_b = landmark_sampler(py_rng, geo["landmark_pair_km"][0], geo["landmark_pair_km"][1])
    pickup = jitter_lonlat(py_rng, lm_a["lon"], lm_a["lat"])
    dropoff = jitter_lonlat(py_rng, lm_b["lon"], lm_b["lat"])

    scenario = ctx.get("scenario", SCENARIO_FOR_LABEL[label])
    cfg_eff = cfg
    if label == "ERR-01":
        cfg_eff = copy.deepcopy(cfg)
        cfg_eff["scenarios"]["driver_stall_cancel"]["stall_duration_s"] = dict(cfg["benchmark"]["err01_short_stall_s"])
    slowcrawl_subset, loop_subset = False, False
    if label in ("ERR-02", "ERR-03"):
        scenario, slowcrawl_subset, loop_subset = scenario_for_label(py_rng, label, cfg)

    tele = generate_trip(cfg_eff, scenario, pickup, t0, np_rng, noise=ctx["noise"], dropoff_lonlat=dropoff)
    points = tele.points
    if "telemetry_capture" in ctx:
        ctx["telemetry_capture"].append(tele)

    gridlock = label == "no_violation" and py_rng.random() < cfg["benchmark"]["gridlock_subset_share"]
    if "gridlock" in ctx:
        gridlock = ctx["gridlock"]
    legit_cancel = label == "no_violation" and py_rng.random() < LEGIT_CANCEL_SHARE

    # Route record: chord x sampled tortuosity (detour quantiles for ERR-03,
    # loop-tail quantiles for the G2 loop subset).
    if loop_subset:
        tq = cfg["route"]["tortuosity_quantiles"]["loop"]
    else:
        tq = cfg["route"]["tortuosity_quantiles"]["detour" if label == "ERR-03" else "normal"]
    tortuosity = round(sample_quantiles(tq, np_rng), 4)
    chord = haversine_m(pickup[0], pickup[1], dropoff[0], dropoff[1])
    distance_m = int(round(chord * tortuosity))
    duration_s = int(round(distance_m / 7.0)) if distance_m > 0 else 0

    first_ts = points[0]["occurred_at"] if points else t0.isoformat()
    last_ts = points[-1]["occurred_at"] if points else t0.isoformat()

    # Lifecycle per class.
    if label in ("ERR-02", "ERR-01", "ERR-03", "insufficient_evidence"):
        actor = {"ERR-02": "passenger", "ERR-01": "driver", "ERR-03": "passenger", "insufficient_evidence": "platform"}[
            label
        ]
        reason = {
            "ERR-02": "driver_stalled_no_show",
            "ERR-01": "driver_cancelled_unjustified",
            "ERR-03": "route_deviation",
            "insufficient_evidence": "technical_dropout",
        }[label]
        trip_status, cancelled_at, completed_at = "cancelled", last_ts, None
        assign_state, arrived_at, started_at, ended_at = "cancelled", None, None, last_ts
    elif label == "ERR-04":  # ghost: completed without pickup
        trip_status, cancelled_at, completed_at = "completed", None, last_ts
        actor, reason = None, None
        assign_state, arrived_at, started_at, ended_at = "completed", None, None, last_ts
    else:  # no_violation, ERR-05
        if legit_cancel:
            legit_reason = py_rng.choice(LEGIT_CANCEL_REASONS)["reason"]
            trip_status, cancelled_at, completed_at = "cancelled", last_ts, None
            actor, reason = "passenger", legit_reason
            assign_state, arrived_at, started_at, ended_at = "cancelled", None, None, last_ts
        else:
            trip_status, cancelled_at, completed_at = "completed", None, last_ts
            actor, reason = None, None
            assign_state, arrived_at, started_at, ended_at = "completed", first_ts, first_ts, last_ts

    traffic = {
        "congestion_level": "heavy" if gridlock else "clear",
        "source": "synthetic",
        "is_simulated": True,
        "observed_at": first_ts,
    }
    incident = None
    if tele.incidents:
        inc = tele.incidents[0]
        incident = {
            "incident_type": inc["incident_type"],
            "state": "observed",
            "started_at": inc["started_at"],
            "ended_at": inc["ended_at"],
        }

    # Population refs: fraud trips ride fraud-prone drivers when possible.
    drivers, fraud_ids = ctx["drivers"], ctx["fraud_ids"]
    if label not in ("no_violation", "insufficient_evidence") and fraud_ids and py_rng.random() < 0.7:
        driver = drivers[[d["id"] for d in drivers].index(py_rng.choice(fraud_ids))]
    else:
        driver = drivers[py_rng.randrange(len(drivers))]
    passenger = ctx["passengers"][idx % len(ctx["passengers"])]
    vehicle = ctx["vehicles"][drivers.index(driver) % len(ctx["vehicles"])]

    context = context_for_trip(label, slowcrawl_subset, loop_subset, gridlock)
    facts = {"wait_s": 300, "distance_m": distance_m, "pickup_name": lm_a["name"], "dest_name": lm_b["name"]}
    dialogue_mode = assign_dialogue_mode(py_rng, label, cfg)
    conversation = synthesize_dialogue(py_rng, context, facts, mode=dialogue_mode)
    objection = synthesize_objection_reason(py_rng, context, facts)
    report = synthesize_customer_report(py_rng, context, facts)
    feedback = synthesize_passenger_feedback(py_rng, label)
    customer_actions = build_customer_actions(conversation, feedback, trip_status, arrived_at)
    analytics = synthesize_driver_analytics(
        py_rng, driver, {"recent_trips_7d": py_rng.randint(15, 35), "recent_trips_30d": py_rng.randint(60, 140)}
    )

    fw = compute_feature_window(points, pickup)
    measured = {
        "approach_ssd_s": fw.approach_stationary_duration_s,
        "davi": fw.davi,
        "coverage": fw.telemetry_coverage,
        "max_gap_s": fw.max_gap_s,
        "mock_ratio": fw.gps_quality.mock_ratio,
        "arrived_at_pickup": fw.arrived_at_pickup,
        "trip_duration_s": round(tele.plan.duration_s, 1),
    }

    return {
        "trip_ref": f"{ref_prefix}{idx + 1:05d}",
        "trip_id": det_uuid(py_rng),
        "assignment_id": det_uuid(py_rng),
        "driver_id": driver["id"],
        "passenger_id": passenger["id"],
        "vehicle_id": vehicle["id"],
        "label": label,
        "scenario": scenario,
        "gridlock_subset": gridlock,
        "slowcrawl_subset": slowcrawl_subset,
        "loop_subset": loop_subset,
        "requested_at": t0.isoformat(),
        "pickup": {"lon": pickup[0], "lat": pickup[1], "name": lm_a["name"]},
        "dropoff": {"lon": dropoff[0], "lat": dropoff[1], "name": lm_b["name"]},
        "route": {
            "distance_m": distance_m,
            "duration_s": duration_s,
            "tortuosity": tortuosity,
            "chord_m": round(chord, 1),
            "provenance": {"provider": "synthetic", "method": "haversine x sampled tortuosity"},
        },
        "telemetry": points,
        "traffic_observation": traffic,
        "platform_incident": incident,
        "trip": {
            "status": trip_status,
            "cancelled_at": cancelled_at,
            "completed_at": completed_at,
            "fare_amount_vnd": 15000 + int(round(distance_m / 1000 * 12000)),
            "match_type": "now" if py_rng.random() < 0.5 else "auto",
            "pickup_address": f"{lm_a['name']}, {lm_a['district']}, Ha Noi",
            "dropoff_address": f"{lm_b['name']}, {lm_b['district']}, Ha Noi",
            "district": lm_a["district"],
            "ghost_no_pickup": label == "ERR-04",
        },
        "assignment": {
            "state": assign_state,
            "offered_at": t0.isoformat(),
            "accepted_at": first_ts,
            "arrived_at": arrived_at,
            "started_at": started_at,
            "ended_at": ended_at,
            "cancellation_actor": actor,
            "cancellation_reason": reason,
        },
        "conversation": conversation,
        "dialogue_mode": dialogue_mode,
        "legit_cancel_subset": legit_cancel,
        "customer_actions": customer_actions,
        "passenger_feedback": feedback,
        "driver_objection": objection,
        "customer_report": report,
        "driver_profile": driver,
        "driver_analytics": analytics,
        "vehicle": vehicle,
        "measured_features": measured,
        "label_provenance": {
            "synthetic": True,
            "generator": f"build_10k {BUILDER_VERSION}",
            "priors": {
                "geometry": "measured-porto",
                "kinematics": "measured-porto",
                "scheduler": "measured-nyc",
                "dialogue": "measured-multiwoz",
                "population": "assumption",
                "scenario_thresholds": "assumption-gate-tuned",
                "prevalence": "measured-paysim-enrichment",
            },
        },
    }


def build_dataset(
    n: int, seed: int, noise: str, progress_every: int = 2000, ref_prefix: str = "bm_v1_"
) -> tuple[list[dict], dict, list[dict]]:
    cfg = load_config(CONFIG_PATH)
    counts = class_counts_for_n(n)
    labels: list[str] = []
    for label in ("no_violation", "ERR-02", "insufficient_evidence", "ERR-01", "ERR-03", "ERR-04", "ERR-05"):
        labels.extend([label] * counts.get(label, 0))
    # Deterministic interleave (round-robin) so any prefix holds the mix.
    order: list[str] = []
    buckets = {k: counts.get(k, 0) for k in CLASS_MIX_10K}
    while any(buckets.values()):
        for k in ("no_violation", "ERR-02", "insufficient_evidence", "ERR-01", "ERR-03", "ERR-04", "ERR-05"):
            if buckets[k] > 0:
                order.append(k)
                buckets[k] -= 1
    assert len(order) == n

    pool_rng = random.Random((seed % 2**31) * 7919 + 1)
    n_drivers = min(2000, max(8, n // 5))
    drivers = synthesize_drivers(pool_rng, n_drivers)
    passengers = synthesize_passengers(pool_rng, max(n, 8))
    vehicles = [
        {
            "id": det_uuid(pool_rng),
            "organization_id": BENCHMARK_ORG_ID,
            "registration_ref": f"29H-{10000 + i}",
            "vehicle_type": "car",
            "service_class": "standard",
            "telemetry_source": "simulator",
            "model": "VF e34",
            "created_at": "2026-09-22T06:00:00+00:00",
        }
        for i in range(n_drivers)
    ]
    fraud_ids = sample_fraud_driver_ids(pool_rng, drivers)
    ctx = {
        "config": cfg,
        "seed": seed,
        "noise": noise,
        "drivers": drivers,
        "passengers": passengers,
        "vehicles": vehicles,
        "fraud_ids": fraud_ids,
    }

    bundles = []
    t_start = time.time()
    for i, label in enumerate(order):
        bundles.append(build_trip(i, label, ctx, ref_prefix))
        if progress_every and (i + 1) % progress_every == 0:
            print(f"  built {i + 1}/{n} ({time.time() - t_start:.1f}s)", flush=True)
    gates = check_gates(bundles, cfg["benchmark"]["gates"])
    return bundles, counts, gates


def write_output(
    bundles: list[dict],
    counts: dict,
    gates: list[dict],
    seed: int,
    noise: str,
    out_dir: Path,
    batch: str = "v1",
    config_version: str | None = None,
) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(b, sort_keys=True, separators=(",", ":"), ensure_ascii=False) for b in bundles]
    trips_path = out_dir / "trips.jsonl"
    with open(trips_path, "w", encoding="utf-8") as f:
        for line in lines:
            f.write(line + "\n")
    sha = hashlib.sha256(("\n".join(lines) + "\n").encode("utf-8")).hexdigest()

    manifest = {
        "version": batch,
        "builder": f"build_10k {BUILDER_VERSION}",
        "config_version": config_version or _config_version(),
        "seed": seed,
        "noise": noise,
        "generator_git_sha": git_sha(),
        "trip_count": len(bundles),
        "class_counts": counts,
        "trips_sha256": sha,
        "gates": gates,
        "priors": PRIOR_TABLE,
        "prevalence_note": (
            "Class mix is ENRICHMENT for detection benchmarking, not natural prevalence (PaySim fraud 0.13% reference)."
        ),
    }
    with open(out_dir / "manifest.json", "w", encoding="utf-8") as f:
        json.dump(manifest, f, sort_keys=True, indent=2, ensure_ascii=False)
        f.write("\n")
    with open(out_dir / "labels.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["trip_ref", "label"])
        for b in bundles:
            w.writerow([b["trip_ref"], b["label"]])
    with open(out_dir / "sample_100.jsonl", "w", encoding="utf-8") as f:
        for line in lines[:100]:
            f.write(line + "\n")
    return manifest


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Build deterministic fraud benchmark dataset")
    ap.add_argument("--n", type=int, default=10000)
    ap.add_argument("--seed", type=int, default=20261011)
    ap.add_argument("--out", type=str, default="data/benchmark-10k")
    ap.add_argument("--noise", type=str, default="happy", choices=["happy", "stress"])
    ap.add_argument("--batch", type=str, default="v1")
    ap.add_argument("--ref-prefix", type=str, default=None)
    args = ap.parse_args(argv)

    t0 = time.time()
    ref_prefix = args.ref_prefix or f"bm_{args.batch}_"
    bundles, counts, gates = build_dataset(args.n, args.seed, args.noise, ref_prefix=ref_prefix)
    out_dir = Path(args.out) / args.batch
    manifest = write_output(bundles, counts, gates, args.seed, args.noise, out_dir, batch=args.batch)

    print(f"runtime {time.time() - t0:.1f}s n={args.n} seed={args.seed}")
    print(f"counts {json.dumps(counts, sort_keys=True)}")
    print("gate                          required  measured   n  pass")
    ok = True
    for g in gates:
        mark = "PASS" if g["pass"] else "FAIL"
        ok = ok and bool(g["pass"])
        print(f"{g['gate']:<28} {g['required']!s:<9} {g['measured']!s:<9} {g['n']:<3} {mark}")
    print(f"manifest sha256 {manifest['trips_sha256']}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

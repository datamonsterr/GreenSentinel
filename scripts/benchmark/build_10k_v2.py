"""Opt-in benchmark v2: causal evidence, explicit strata, chronological history.

Run ``python scripts/benchmark/build_10k_v2.py --n 10000 --out data/benchmark-10k``.
Output lives under ``profiles/evidence-v2``; named feedback batches stay separate.
JSONL is canonical; Parquet preserves complete nested bundles including nulls.
The default v1 builder and its random stream are unchanged.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.metadata
import json
import platform
import random
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.benchmark import build_10k as v1  # noqa: E402
from scripts.benchmark.dialogue_synth import synthesize_dialogue  # noqa: E402
from scripts.benchmark.driver_ledger import attach_history, driver_split, operational_events  # noqa: E402
from scripts.telemetry_generation import _to_latlon, load_config, plan_start_latlon  # noqa: E402

CONFIG_PATH = REPO_ROOT / "config/benchmark_distribution_v2.yaml"
PORTO_PATH = REPO_ROOT / "tests/fixtures/benchmark/porto_reference.json"

# --- Issue #281 hardening: decoupled operational enums, fare coherence, locale ---
# Cancellation reason/actor are drawn from realistic operational pools that overlap
# across every cancelled class, so (status, actor, reason) cannot reconstruct the
# ground-truth label. Ground truth stays in `label` + `label_provenance` only.
OPERATIONAL_REASON_WEIGHTS: dict[str, tuple[tuple[str, float], ...]] = {
    # Each cancelled class has one signature reason it does NOT own outright: the
    # reason is shared by every class at 0.40/0.15/0.15/0.15/0.15, so no
    # (status, actor, reason) group is label-pure. Expected enum-latch recall
    # per cancelled class ~0.40 (verified: worst 0.48 over 500 10k-size draws).
    "ERR-01": (
        ("driver_requested", 0.40),
        ("driver_no_show", 0.15),
        ("route_unavailable", 0.15),
        ("network_issue", 0.15),
        ("traffic_delay", 0.15),
    ),
    "ERR-02": (
        ("driver_no_show", 0.40),
        ("driver_requested", 0.15),
        ("route_unavailable", 0.15),
        ("network_issue", 0.15),
        ("traffic_delay", 0.15),
    ),
    "ERR-03": (
        ("route_unavailable", 0.40),
        ("driver_requested", 0.15),
        ("driver_no_show", 0.15),
        ("network_issue", 0.15),
        ("traffic_delay", 0.15),
    ),
    "insufficient_evidence": (
        ("network_issue", 0.40),
        ("driver_requested", 0.15),
        ("driver_no_show", 0.15),
        ("route_unavailable", 0.15),
        ("traffic_delay", 0.15),
    ),
    "no_violation": (
        ("traffic_delay", 0.40),
        ("driver_requested", 0.15),
        ("driver_no_show", 0.15),
        ("route_unavailable", 0.15),
        ("network_issue", 0.15),
    ),
}
REASON_TO_ACTOR: dict[str, str] = {
    "passenger_requested": "passenger",
    "driver_requested": "driver",
    "driver_no_show": "driver",
    "driver_unreachable": "driver",
    "vehicle_issue": "driver",
    "route_unavailable": "driver",
    "app_error": "platform",
    "payment_issue": "passenger",
    "traffic_delay": "platform",
    "network_issue": "platform",
}
FARE_BASE_VND = 12000
FARE_PER_KM_VND = 12000
FARE_MAX_PER_KM_VND = 100000


def load_v2_config() -> dict:
    config = load_config(v1.CONFIG_PATH)

    def overlay(target: dict, source: dict) -> None:
        for key, value in source.items():
            if isinstance(value, dict) and isinstance(target.get(key), dict):
                overlay(target[key], value)
            else:
                target[key] = copy.deepcopy(value)

    overlay(config, load_config(CONFIG_PATH))
    return config


def _selection(indices: list[int], share: float, seed: int, namespace: str) -> set[int]:
    """Independent exact-size cohorts, nearest-integer scaling for small builds."""
    digest = hashlib.sha256(f"{seed}:{namespace}".encode()).digest()
    rng = random.Random(int.from_bytes(digest, "big"))
    return set(rng.sample(indices, int(len(indices) * share + 0.5)))


def _porto_sampler(rng: random.Random, low: float, high: float) -> tuple[dict, dict]:
    landmarks = json.loads(PORTO_PATH.read_text())["landmarks"]
    pairs = [
        (a, b)
        for a in landmarks
        for b in landmarks
        if a != b and low * 1000 <= v1.haversine_m(a["lon"], a["lat"], b["lon"], b["lat"]) <= high * 1000
    ]
    return rng.choice(pairs)


def _context(n: int, seed: int, cfg: dict) -> dict:
    rng = random.Random((seed % 2**31) * 7919 + 1)
    drivers = v1.synthesize_drivers(rng, min(2000, max(8, n // 5)))
    passengers = v1.synthesize_passengers(rng, max(n, 8))
    vehicles = [
        {
            "id": v1.det_uuid(rng),
            "organization_id": v1.BENCHMARK_ORG_ID,
            "registration_ref": f"BENCH-{i:05d}",
            "vehicle_type": "car",
            "service_class": "standard",
            "telemetry_source": "simulator",
            "model": "synthetic vehicle",
            "created_at": "2026-09-01T00:00:00+00:00",
        }
        for i in range(len(drivers))
    ]
    return {
        "config": cfg,
        "seed": seed,
        "noise": "happy",
        "drivers": drivers,
        "passengers": passengers,
        "vehicles": vehicles,
        "fraud_ids": v1.sample_fraud_driver_ids(rng, drivers),
    }


def _configure_trip(config: dict, label: str, boundary: bool) -> dict:
    cfg = copy.deepcopy(config)
    if boundary:
        settings = cfg["benchmark_v2"]
        cfg["scenarios"]["traffic_gridlock"]["stop_duration_s"] = settings["boundary_stop_s"]
        cfg["scenarios"]["traffic_gridlock"]["crawl_leg_m"] = 50
        cfg["scenarios"]["traffic_gridlock"]["crawl_speed_mps"] = 1
        cfg["sampling"]["profiles"]["porto_15s"]["cadence_s"] = settings["boundary_cadence_s"]
        cfg["sampling"]["missed_ping_probability"] = 0
        cfg["sampling"]["outage"]["trip_probability"] = 0
        cfg["position"]["accuracy_m"].update({"clip_max": 12, "null_rate": 0})
        cfg["position"]["accuracy_m"]["heavy_tail"]["rate"] = 0
        cfg["scenarios"]["traffic_gridlock"]["health"]["jitter"] = 0
    if label == "ERR-04":
        # A completed claim with a never-arrived trajectory and passenger denial.
        # No fabricated GPS or device-outage confound in this coherent fixture.
        cfg["scenarios"]["driver_stall_cancel"]["stall_distance_to_pickup_m"] = {
            "dist": "uniform",
            "low": 250,
            "high": 450,
        }
        cfg["scenarios"]["driver_stall_cancel"]["move_away_first"]["probability"] = 0
        cfg["scenarios"]["driver_stall_cancel"]["health"] = {
            "crash": 0,
            "offline": 0,
            "degraded": 0,
            "jitter": 0,
            "mock": 0,
        }
        cfg["sampling"]["outage"]["trip_probability"] = 0
    return cfg


def _sample_operational_reason(rng: random.Random, label: str) -> str:
    weights = OPERATIONAL_REASON_WEIGHTS.get(label, OPERATIONAL_REASON_WEIGHTS["no_violation"])
    return rng.choices([r for r, _ in weights], weights=[w for _, w in weights], k=1)[0]


def _harden_trip(bundle: dict, rng: random.Random) -> None:
    """Issue #281: decouple detector-visible enums + enforce fare coherence."""
    label = bundle["label"]
    if bundle["trip"].get("status") == "cancelled":
        reason = _sample_operational_reason(rng, label)
        bundle["assignment"].update(
            cancellation_actor=REASON_TO_ACTOR[reason],
            cancellation_reason=reason,
        )
        bundle["trip"]["fare_amount_vnd"] = None
        bundle["trip"]["fare_state"] = "cancelled_no_charge"
        bundle["trip"]["cancellation_fee_vnd"] = 0
    else:
        km = float(bundle["route"]["distance_m"]) / 1000.0
        fare = int(round(min(FARE_BASE_VND + FARE_PER_KM_VND * km, FARE_MAX_PER_KM_VND * km)))
        bundle["trip"]["fare_amount_vnd"] = fare
        bundle["trip"]["fare_state"] = "completed"
    bundle["label_provenance"]["hardening"] = (
        "operational enums decoupled from label; cancellation fee/no-charge on cancelled trips"
    )
    bundle["label_provenance"]["fare_model"] = "base 12k VND + 12k VND/km, per-km capped at 100k"
    bundle["label_provenance"]["cancellation_narrative"] = "realistic operational pool, shared across classes"


def _enrich(
    bundle: dict,
    tele,
    *,
    index: int,
    seed: int,
    city: str,
    noise: str,
    boundary: bool,
    long_dialogue: bool,
    porto: dict,
    cfg: dict,
    harden: bool = False,
) -> None:
    bundle["trip_ref"] = f"bm_v2_{index + 1:05d}"
    bundle.update(city=city, noise_stratum=noise, gridlock_boundary=boundary)
    pickup = (bundle["pickup"]["lon"], bundle["pickup"]["lat"])
    origin_lat, origin_lon = plan_start_latlon(tele, pickup)
    end_lat, end_lon = _to_latlon(pickup, tele.plan.legs[-1].end)
    duration = tele.plan.duration_s
    distance = sum(float(((leg.end - leg.start) ** 2).sum() ** 0.5) for leg in tele.plan.legs)
    bundle["route"] = {
        "distance_m": round(distance, 3),
        "duration_s": round(duration, 6),
        "provenance": {
            "provider": "synthetic",
            "method": "sum of timed trajectory plan legs",
            "is_shortest_path": False,
        },
    }
    bundle["planned_route"] = {
        "coordinates": [[origin_lon, origin_lat], list(pickup)],
        "provenance": {
            "source": "synthetic_reference",
            "is_shortest_path": False,
            "method": "intended driver start to pickup straight chord; no road routing",
        },
    }
    bundle["generation_audit"] = {
        "planned_origin": [origin_lon, origin_lat],
        "planned_endpoint": [end_lon, end_lat],
        "leg_speeds_mps": [leg.speed_mps for leg in tele.plan.legs if leg.kind == "move"],
        "leg_durations_s": [leg.duration_s for leg in tele.plan.legs],
        "leg_phases": [leg.phase for leg in tele.plan.legs],
        "long_dialogue": long_dialogue,
        "speed_provenance": "Porto measured pooled segment quantiles; moving clip [3,24] m/s assumption; crawl/teleport use scenario priors",
        "boundary_constraints": "happy; 10s cadence; no missed pings/outages; accuracy <=12m; 240s stops"
        if boundary
        else None,
    }
    bundle["geography_provenance"] = {
        "source": porto["source"] if city == "Porto" else "approximate Hanoi demo landmarks",
        "source_url": porto["source_url"] if city == "Porto" else None,
        "license": porto["license"] if city == "Porto" else None,
        "attribution": porto["attribution"] if city == "Porto" else None,
        "template_sha256": hashlib.sha256(PORTO_PATH.read_bytes()).hexdigest() if city == "Porto" else None,
        "method": "geographic anchors only; synthetic trajectories; no shortest-road or transfer-performance claim",
    }
    first, last = bundle["telemetry"][0]["occurred_at"], bundle["telemetry"][-1]["occurred_at"]
    if bundle["gridlock_subset"]:
        bundle["trip"].update(status="cancelled", cancelled_at=last, completed_at=None)
        bundle["assignment"].update(
            state="cancelled",
            arrived_at=None,
            started_at=None,
            ended_at=last,
            cancellation_actor="passenger",
            cancellation_reason="traffic_gridlock",
        )
    elif bundle["label"] == "no_violation":
        arrival = next(
            (p["occurred_at"] for p, phase in zip(bundle["telemetry"], tele.phases, strict=True) if phase == "wait"),
            None,
        )
        started = next(
            (p["occurred_at"] for p, phase in zip(bundle["telemetry"], tele.phases, strict=True) if phase == "on_trip"),
            None,
        )
        bundle["assignment"].update(arrived_at=arrival, started_at=started)
    bundle["traffic_observation"]["source"] = "synthetic scenario traffic observation"
    context = "traffic_gridlock" if bundle["gridlock_subset"] else v1.CONTEXT_FOR_LABEL[bundle["label"]]
    rng = random.Random(f"v2-dialogue:{seed}:{index}")
    turns = synthesize_dialogue(
        rng,
        context,
        {
            "wait_s": duration,
            "distance_m": distance,
            "pickup_name": bundle["pickup"]["name"],
            "dest_name": bundle["dropoff"]["name"],
        },
        turn_count=cfg["benchmark_v2"]["long_dialogue_turns"] if long_dialogue else None,
        split=driver_split(bundle["driver_id"]) if harden else None,
        paraphrase=harden,
    )
    # Preserve order while placing every message within the observed trip.
    horizon = (datetime.fromisoformat(last) - datetime.fromisoformat(first)).total_seconds()
    for i, turn in enumerate(turns):
        turn["sent_at_offset_s"] = round(horizon * (i + 1) / (len(turns) + 1), 6)
    bundle["conversation"] = turns
    bundle["passenger_observation"] = None
    if bundle["label"] == "ERR-04":
        denial = "Tài xế chưa đón tôi nhưng ứng dụng đã báo hoàn thành chuyến."
        next(turn for turn in turns if turn["role"] == "customer")["text"] = denial
        bundle["customer_report"] = denial
        bundle["passenger_observation"] = {
            "source": "synthetic passenger report",
            "observed_at": last,
            "picked_up": False,
            "completed_claim_seen": True,
        }
    bundle["trip"].pop("ghost_no_pickup", None)
    bundle["trip"]["pickup_address"] = f"{bundle['pickup']['name']}, {city}"
    bundle["trip"]["dropoff_address"] = f"{bundle['dropoff']['name']}, {city}"
    if city == "Porto":
        bundle["trip"]["district"] = "Porto"
    bundle["label_provenance"]["generator"] = "build_10k_v2"
    bundle["label_provenance"]["priors"]["kinematics"] = "measured-porto-segment-quantiles-with-explicit-moving-clip"
    bundle["label_provenance"]["priors"]["scenario_thresholds"] = (
        "synthetic scenario assumptions; controlled gridlock boundary subset"
    )
    if harden:
        bundle["geography_provenance"].update(
            city=city,
            locale="pt-PT" if city == "Porto" else "vi-VN",
            country="PT" if city == "Porto" else "VN",
        )
        bundle["trip"]["city"] = city
        _harden_trip(bundle, random.Random(f"v2-harden:{seed}:{index}"))


def _hardening_gates(bundles: list[dict]) -> list[dict]:
    """Issue #281 gates: enum-latch, locale, fare coherence, dialogue uniqueness."""
    from collections import Counter

    def _key(b: dict) -> tuple:
        return (
            b["trip"].get("status"),
            b["assignment"].get("cancellation_actor"),
            b["assignment"].get("cancellation_reason"),
        )

    cancelled = [b for b in bundles if b["trip"].get("status") == "cancelled"]
    gates: list[dict] = []

    # (1) Enum-latch: classifier fit on (status, actor, reason) over train split.
    train = [b for b in cancelled if b.get("split") == "train"]
    n_classes = len({b["label"] for b in cancelled})
    # Only large builds measure reliably; tiny builds would flake on scarcity.
    if len(cancelled) >= 1000 and n_classes >= 2:
        groups: dict[tuple, Counter] = {}
        for b in train:
            groups.setdefault(_key(b), Counter())[b["label"]] += 1
        pred = {k: c.most_common(1)[0][0] for k, c in groups.items()}
        fallback = Counter(b["label"] for b in train).most_common(1)[0][0]
        recall: dict[str, float] = {}
        for label in sorted({b["label"] for b in cancelled}):
            n_lab = sum(1 for b in cancelled if b["label"] == label)
            tp = sum(1 for b in cancelled if b["label"] == label and pred.get(_key(b), fallback) == label)
            recall[label] = round(tp / n_lab, 4) if n_lab else 0.0
        worst = max(recall.values())
        gates.append(
            {
                "gate": "enum-latch label recall < 0.5",
                "required": "<0.5",
                "measured": worst,
                "n": len(cancelled),
                "pass": worst < 0.5,
                "status": "measured",
                "detail": "per-class recall: " + json.dumps(recall, sort_keys=True),
            }
        )
    else:
        gates.append(
            {
                "gate": "enum-latch label recall < 0.5",
                "required": "<0.5",
                "measured": None,
                "n": len(cancelled),
                "pass": None,
                "status": "not_applicable",
            }
        )

    # (2) Locale consistency: telemetry/pickup/dropoff bbox agrees with declared city.
    def _locale_ok(b: dict) -> bool:
        target = b.get("city") == "Porto"
        for p in b["telemetry"]:
            lon, lat = p.get("longitude"), p.get("latitude")
            if lon is None or lat is None:
                continue
            if (lon < 0) != target:
                return False
        for coord in (b["pickup"], b["dropoff"]):
            if (coord["lon"] < 0) != target:
                return False
        return True

    frac_locale = sum(bool(_locale_ok(b)) for b in bundles) / len(bundles) if bundles else None
    gates.append(
        {
            "gate": "locale consistency (bbox within city)",
            "required": 1.0,
            "measured": round(frac_locale, 4) if frac_locale is not None else None,
            "n": len(bundles),
            "pass": frac_locale == 1.0 if frac_locale is not None else None,
            "status": "measured" if bundles else "not_applicable",
        }
    )

    # (3) Fare coherence: cancelled no charge; completed fare derives from the
    # exact published model (not merely the cap it was built from).
    def _fare_ok(b: dict) -> bool:
        fare = b["trip"].get("fare_amount_vnd")
        km = float(b["route"].get("distance_m", 0)) / 1000.0
        if b["trip"].get("status") == "cancelled":
            return fare is None or (isinstance(fare, (int, float)) and fare == 0)
        if not isinstance(fare, int) or fare < 0:
            return False
        expected = int(round(min(FARE_BASE_VND + FARE_PER_KM_VND * km, FARE_MAX_PER_KM_VND * km)))
        return fare == expected

    frac_fare = sum(bool(_fare_ok(b)) for b in bundles) / len(bundles) if bundles else None
    gates.append(
        {
            "gate": "fare coherence (no fare on cancelled, per-km<=100k)",
            "required": 1.0,
            "measured": round(frac_fare, 4) if frac_fare is not None else None,
            "n": len(bundles),
            "pass": frac_fare == 1.0 if frac_fare is not None else None,
            "status": "measured" if bundles else "not_applicable",
        }
    )

    # (4) Dialogue uniqueness fraction (>5%).
    utt = [t["text"] for b in bundles for t in b.get("conversation", [])]
    frac_uniq = len(set(utt)) / len(utt) if utt else None
    gates.append(
        {
            "gate": "dialogue unique utterance fraction > 5%",
            "required": ">0.05",
            "measured": round(frac_uniq, 4) if frac_uniq is not None else None,
            "n": len(utt),
            "pass": frac_uniq > 0.05 if frac_uniq is not None else None,
            "status": "measured" if utt else "not_applicable",
        }
    )
    return gates


def check_gates(bundles: list[dict], harden: bool = False) -> list[dict]:
    """Generation invariants; stress features are reported separately, never retuned."""
    gates = []
    for noise in ("happy", "stress"):
        rows = [b for b in bundles if b["noise_stratum"] == noise]
        for name, cohort, check in (
            (
                "ghost never arrived",
                [b for b in rows if b["label"] == "ERR-04"],
                lambda b: not b["measured_features"]["arrived_at_pickup"],
            ),
            (
                "gridlock boundary SSD>=180",
                [b for b in rows if b["gridlock_boundary"]],
                lambda b: b["measured_features"]["approach_ssd_s"] >= 180,
            ),
            (
                "dropout max_gap>30",
                [b for b in rows if b["label"] == "insufficient_evidence"],
                lambda b: b["measured_features"]["max_gap_s"] > 30,
            ),
            (
                "spoof mock>=0.8",
                [b for b in rows if b["label"] == "ERR-05"],
                lambda b: b["measured_features"]["mock_ratio"] >= 0.8,
            ),
        ):
            fraction = sum(bool(check(b)) for b in cohort) / len(cohort) if cohort else None
            gates.append(
                {
                    "gate": name,
                    "stratum": noise,
                    "n": len(cohort),
                    "required": 1.0,
                    "measured": fraction,
                    "pass": fraction == 1.0 if cohort else None,
                    "status": "measured" if cohort else "not_applicable",
                }
            )
    if harden:
        gates.extend(_hardening_gates(bundles))
    return gates


def build_dataset(
    n: int, seed: int, progress_every: int = 2000, harden: bool = False
) -> tuple[list[dict], dict, list[dict]]:
    if n <= 0:
        raise ValueError("n must be positive")
    cfg = load_v2_config()
    settings = cfg["benchmark_v2"]
    counts = v1.class_counts_for_n(n)
    remaining = dict(counts)
    labels = []
    while any(remaining.values()):
        for label in remaining:
            if remaining[label]:
                labels.append(label)
                remaining[label] -= 1
    indices = list(range(n))
    grid = _selection(
        [i for i, label in enumerate(labels) if label == "no_violation"],
        settings["gridlock_honest_share"],
        seed,
        "gridlock",
    )
    boundary = _selection(sorted(grid), settings["gridlock_boundary_share"], seed, "boundary")
    # Retain exactly n*10% stress while explicitly excluding controlled boundaries.
    eligible = [i for i in indices if i not in boundary]
    stress = _selection(eligible, int(n * settings["stress_share"] + 0.5) / len(eligible), seed, "stress")
    porto_indices = _selection(indices, settings["porto_share"], seed, "city")
    long = _selection(indices, settings["long_dialogue_share"], seed, "dialogue")
    ctx = _context(n, seed, cfg)
    porto = json.loads(PORTO_PATH.read_text())
    bundles = []
    for i, label in enumerate(labels):
        noise = "stress" if i in stress else "happy"
        city = "Porto" if i in porto_indices else "Hanoi"
        capture = []
        trip_ctx = {
            **ctx,
            "config": _configure_trip(cfg, label, i in boundary),
            "noise": noise,
            "gridlock": i in grid,
            "telemetry_capture": capture,
        }
        if i in grid:
            trip_ctx["scenario"] = "traffic_gridlock"
        elif label == "ERR-04":
            trip_ctx["scenario"] = "driver_stall_cancel"
        if city == "Porto":
            trip_ctx["landmark_sampler"] = _porto_sampler
        bundle = v1.build_trip(i, label, trip_ctx)
        _enrich(
            bundle,
            capture[0],
            index=i,
            seed=seed,
            city=city,
            noise=noise,
            boundary=i in boundary,
            long_dialogue=i in long,
            porto=porto,
            cfg=cfg,
            harden=harden,
        )
        bundles.append(bundle)
        if progress_every and (i + 1) % progress_every == 0:
            print(f"built v2 {i + 1}/{n}", flush=True)
    attach_history(bundles)
    return bundles, counts, check_gates(bundles, harden=harden)


def _json_lines(path: Path, rows: list[dict]) -> str:
    with path.open("w", encoding="utf-8") as output:
        for row in rows:
            output.write(json.dumps(row, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def export_parquet(bundles: list[dict], path: Path) -> dict:
    import pyarrow as pa
    import pyarrow.parquet as pq

    table = pa.Table.from_pylist(bundles)
    metadata = {
        **(table.schema.metadata or {}),
        b"canonical_format": b"JSONL",
        b"provenance": b"synthetic benchmark; nested columns; nulls preserved",
    }
    table = table.replace_schema_metadata(metadata)
    pq.write_table(table, path, compression="zstd")
    return {
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "schema": str(table.schema),
        "format": "nested PyArrow table",
        "canonical": "trips.jsonl",
        "rows": len(bundles),
    }


def read_parquet(path: Path) -> list[dict]:
    import pyarrow.parquet as pq

    return pq.read_table(path).to_pylist()


def write_output(
    bundles: list[dict],
    counts: dict,
    gates: list[dict],
    seed: int,
    out_dir: Path,
    *,
    profile: str = "evidence-v2",
    version: str = "v2",
    harden: bool = False,
) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    trips_sha = _json_lines(out_dir / "trips.jsonl", bundles)
    _json_lines(out_dir / "sample_100.jsonl", bundles[:100])
    ledger = operational_events(bundles)
    ledger_sha = _json_lines(out_dir / "driver_ledger.jsonl", ledger)
    parquet = export_parquet(bundles, out_dir / "trips.parquet")
    strata = {}
    for noise in ("happy", "stress"):
        rows = [b for b in bundles if b["noise_stratum"] == noise]
        strata[noise] = {
            "trip_count": len(rows),
            "class_counts": dict(Counter(b["label"] for b in rows)),
            "ssd_ge_180_count": sum(
                b["measured_features"]["approach_ssd_s"] is not None and b["measured_features"]["approach_ssd_s"] >= 180
                for b in rows
            ),
            "gates": [g for g in gates if g.get("stratum") == noise],
        }
    manifest = {
        "version": version,
        "profile": profile,
        "builder": "build_10k_v2",
        "seed": seed,
        "trip_count": len(bundles),
        "class_counts": counts,
        "trips_sha256": trips_sha,
        "gates": gates,
        "strata": strata,
        "city_counts": dict(Counter(b["city"] for b in bundles)),
        "long_dialogue_count": sum(len(b["conversation"]) == 16 for b in bundles),
        "gridlock_count": sum(b["gridlock_subset"] for b in bundles),
        "gridlock_boundary_count": sum(b["gridlock_boundary"] for b in bundles),
        "split_counts": dict(Counter(b["split"] for b in bundles)),
        "ledger_sha256": ledger_sha,
        "parquet": parquet,
        "config_sha256": hashlib.sha256(CONFIG_PATH.read_bytes()).hexdigest(),
        "base_config_sha256": hashlib.sha256(v1.CONFIG_PATH.read_bytes()).hexdigest(),
        "porto_template_sha256": hashlib.sha256(PORTO_PATH.read_bytes()).hexdigest(),
        "environment": {
            "python": platform.python_version(),
            **{
                name: importlib.metadata.version(name) for name in ("numpy", "PyYAML", "pyarrow", "pydantic", "shapely")
            },
        },
        "assumptions": {
            "kinematics": "measured Porto pooled quantiles include stops; linear p05-p95 interpolation and [3,24] moving clipping assumptions; crawl/teleport scenario priors",
            "gridlock": "10% honest; 3% of gridlock controlled SSD boundary fixtures from synthetic 400-trip calibration, not real traffic frequency",
            "noise": "10% stress; AR1 rho=0.9 and accuracy/noise priors are synthetic assumptions; boundary subset excludes stress",
            "geography": "20% Porto anchors from licensed observed taxi template; synthetic geometry, not shortest-road evidence",
            "dialogue": "20% 16-turn, remaining 4-12; local authored banks; within-trip timing synthetic",
            "history": "only earlier terminal operational events; no current/future outcome or labels; profile priors separate",
            "splits": "stable driver hash 70/15/15; no holdout tuning and no claim of unseen-driver generalization",
            "labels": "enriched synthetic class mix; evidence sufficiency remains independent; no existing cases relabeled",
        },
    }
    if harden:
        manifest["hardened"] = True
        manifest["assumptions"].update(
            {
                "enums": "cancellation reason/actor drawn from overlapping operational pools; not label-deterministic",
                "fare": "completed fare = 12k VND + 12k VND/km capped at 100k/km; cancelled trips carry no charge",
                "locale": "per-trip city/country/locale metadata agrees with telemetry bbox",
                "dialogue_holdout": "bank templates partitioned 70/15/15; paraphrase affixes raise surface uniqueness",
                "backend-affected": "frozen profiles v1/v2/v3 and evidence-v2 byte-identical and untouched",
            }
        )
    (out_dir / "manifest.json").write_text(json.dumps(manifest, sort_keys=True, indent=2, ensure_ascii=False) + "\n")
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--n", type=int, default=10000)
    parser.add_argument("--seed", type=int, default=20261011)
    parser.add_argument("--out", type=Path, default=Path("data/benchmark-10k"))
    parser.add_argument(
        "--profile",
        choices=("evidence-v2", "evidence-v4"),
        default="evidence-v2",
        help="evidence-v2 keeps the frozen corpus; evidence-v4 applies Issue #281 hardening",
    )
    args = parser.parse_args(argv)
    harden = args.profile == "evidence-v4"
    version = "v4" if harden else "v2"
    bundles, counts, gates = build_dataset(args.n, args.seed, harden=harden)
    manifest = write_output(
        bundles,
        counts,
        gates,
        args.seed,
        args.out / "profiles" / args.profile,
        profile=args.profile,
        version=version,
        harden=harden,
    )
    print(json.dumps({"trips_sha256": manifest["trips_sha256"], "gates": gates}, sort_keys=True))
    return int(any(g["pass"] is False for g in gates))


if __name__ == "__main__":
    sys.exit(main())

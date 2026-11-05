"""Analyze the 10k-trip fraud benchmark (Issue #255). New file, no commits.

Reads data/benchmark-10k/v1/trips.jsonl + manifest.json and writes
notebooks/benchmark10k/profile.json (counts, quantiles, AUROCs, timings,
leakage verdicts, gridlock geometry check).

Stdlib + numpy only. No matplotlib.

Usage: .venv/bin/python scripts/analyze_10k.py [--trips PATH] [--out PATH]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from copy import deepcopy
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import numpy as np  # noqa: E402

CLASSES = ["no_violation", "ERR-02", "insufficient_evidence", "ERR-01", "ERR-03", "ERR-04", "ERR-05"]

NUM_FEATURES = [
    "approach_ssd_s",
    "davi",
    "coverage",
    "max_gap_s",
    "mock_ratio",
    "tortuosity",
    "turns",
    "utt_words_mean",
]

# Separability spec: (positive class, feature, direction). Direction +1 means
# higher score = more anomalous; -1 negates the raw feature.
SEPARABILITY = [
    ("ERR-02", "approach_ssd_s", +1),
    ("ERR-01", "approach_ssd_s", +1),
    ("ERR-03", "tortuosity", +1),
    ("ERR-03", "davi", -1),
    ("ERR-05", "mock_ratio", +1),
    ("insufficient_evidence", "max_gap_s", +1),
    ("ERR-04", "coverage", -1),
]

LEAK_KEYS = (
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
)


def describe(values: list[float]) -> dict:
    a = np.asarray(values, dtype=float)
    finite = a[np.isfinite(a)]
    out: dict = {"n_total": int(len(a)), "n_finite": int(len(finite)), "n_null": int(len(a) - len(finite))}
    if len(finite):
        qs = np.quantile(finite, [0, 0.05, 0.25, 0.5, 0.75, 0.95, 1])
        for k, v in zip(["min", "p05", "p25", "p50", "p75", "p95", "max"], qs):
            out[k] = round(float(v), 4)
        out["mean"] = round(float(finite.mean()), 4)
        out["std"] = round(float(finite.std()), 4)
    return out


def evaluate(labels: np.ndarray, scores: np.ndarray) -> dict:
    """Same transductive protocol as docs/data/MIPO_EDA.md."""
    positive, negative = scores[labels == 1], scores[labels == 0]
    if not len(positive) or not len(negative):
        return {
            "auroc": float("nan"),
            "average_precision": float("nan"),
            "n_pos": int(len(positive)),
            "n_neg": int(len(negative)),
        }
    auroc = float((positive[:, None] > negative).mean() + 0.5 * (positive[:, None] == negative).mean())
    ap, prev = 0.0, 0.0
    for thr in np.unique(scores)[::-1]:
        sel = scores >= thr
        tp = int(labels[sel].sum())
        rec = tp / len(positive)
        ap += (rec - prev) * tp / int(sel.sum())
        prev = rec
    return {
        "auroc": round(auroc, 4),
        "average_precision": round(float(ap), 4),
        "n_pos": int(len(positive)),
        "n_neg": int(len(negative)),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--trips", default="data/benchmark-10k/v1/trips.jsonl")
    ap.add_argument("--manifest", default="data/benchmark-10k/v1/manifest.json")
    ap.add_argument("--out", default="notebooks/benchmark10k/profile.json")
    args = ap.parse_args()

    t_all = time.perf_counter()
    trips_path = REPO_ROOT / args.trips

    per_class: dict[str, dict[str, list]] = {c: {f: [] for f in NUM_FEATURES} for c in CLASSES}
    counts: dict[str, int] = {c: 0 for c in CLASSES}
    prov_ok = 0
    gridlock_n = gridlock_ssd180 = 0
    leak_hits: dict[str, int] = {
        k: 0
        for k in ("telemetry_has_leak_key", "conversation_has_leak_key", "measured_extra_keys", "profile_has_label_key")
    }
    t_read = time.perf_counter()
    n = 0
    with open(trips_path, encoding="utf-8") as fh:
        for line in fh:
            b = json.loads(line)
            label = b["label"]
            counts[label] += 1
            n += 1
            if isinstance(b.get("label_provenance"), dict) and b["label_provenance"].get("synthetic") is True:
                prov_ok += 1
            mf = b.get("measured_features", {}) or {}
            per_class[label]["approach_ssd_s"].append(
                np.nan if mf.get("approach_ssd_s") is None else float(mf["approach_ssd_s"])
            )
            per_class[label]["davi"].append(np.nan if mf.get("davi") is None else float(mf["davi"]))
            per_class[label]["coverage"].append(np.nan if mf.get("coverage") is None else float(mf["coverage"]))
            per_class[label]["max_gap_s"].append(np.nan if mf.get("max_gap_s") is None else float(mf["max_gap_s"]))
            per_class[label]["mock_ratio"].append(
                np.nan if mf.get("mock_ratio") is None else float(mf.get("mock_ratio", 0.0))
            )
            rt = b.get("route", {}) or {}
            per_class[label]["tortuosity"].append(np.nan if rt.get("tortuosity") is None else float(rt["tortuosity"]))
            conv = b.get("conversation", []) or []
            per_class[label]["turns"].append(float(len(conv)))
            cust = [m for m in conv if isinstance(m, dict) and m.get("role") == "customer"]
            if cust:
                lens = [len(str(m.get("text", "")).split()) for m in cust]
                per_class[label]["utt_words_mean"].append(float(sum(lens) / len(lens)))
            else:
                per_class[label]["utt_words_mean"].append(np.nan)
            # leakage scan: label-derived keys inside detector-consumed fields
            for pt in b.get("telemetry", []) or []:
                if isinstance(pt, dict) and any(k in pt for k in LEAK_KEYS):
                    leak_hits["telemetry_has_leak_key"] += 1
                    break
            for m in conv:
                if isinstance(m, dict) and any(k in m for k in LEAK_KEYS):
                    leak_hits["conversation_has_leak_key"] += 1
                    break
            if set(mf.keys()) - {"approach_ssd_s", "davi", "coverage", "max_gap_s", "mock_ratio", "arrived_at_pickup"}:
                leak_hits["measured_extra_keys"] += 1
            dp = b.get("driver_profile", {}) or {}
            if any(k in dp for k in ("label", "scenario", "expected_category")):
                leak_hits["profile_has_label_key"] += 1
            # gridlock geometry: no_violation + heavy traffic
            traf = b.get("traffic_observation", {}) or {}
            if label == "no_violation" and (
                b.get("gridlock_subset") is True or traf.get("congestion_level") == "heavy"
            ):
                gridlock_n += 1
                ssd = mf.get("approach_ssd_s")
                if ssd is not None and float(ssd) >= 180:
                    gridlock_ssd180 += 1
    read_s = time.perf_counter() - t_read

    t_stat = time.perf_counter()
    distributions = {c: {f: describe(per_class[c][f]) for f in NUM_FEATURES} for c in CLASSES}
    stat_s = time.perf_counter() - t_stat

    t_sep = time.perf_counter()
    separability = []
    neg = "no_violation"
    for cls, feat, direction in SEPARABILITY:
        pos = np.asarray(per_class[cls][feat], dtype=float)
        negv = np.asarray(per_class[neg][feat], dtype=float)
        ok = np.isfinite(pos)
        okn = np.isfinite(negv)
        labels = np.concatenate([np.ones(ok.sum()), np.zeros(okn.sum())])
        scores = direction * np.concatenate([pos[ok], negv[okn]])
        r = evaluate(labels, scores)
        r.update(
            {
                "pos_class": cls,
                "neg_class": neg,
                "feature": feat,
                "direction": direction,
                "pos_null": int((~ok).sum()),
                "neg_null": int((~okn).sum()),
            }
        )
        separability.append(r)
    sep_s = time.perf_counter() - t_sep

    # projection check: anomaly_type/anomaly_score/simulation_labels excluded
    t_leak = time.perf_counter()
    from src.services.model_input_projection import project_model_input

    probe = {
        "trip_id": "t",
        "points": [{"latitude": 1.0, "anomaly_type": "x", "anomaly_score": 0.9}],
        "scenario": "s",
        "expected_category": "e",
        "expected_guardrail": "g",
        "expected_guardrail_reason": "r",
        "expected_outcome": "o",
        "intent": "i",
        "simulation_id": "sid",
        "anomaly_type": "x",
        "anomaly_score": 0.9,
        "simulation_labels": [],
        "label": "ERR-02",
        "measured_features": {},
        "cancellation_reason": "driver_stalled_no_show",
        "cancellation_actor": "passenger",
    }
    proj = project_model_input(probe)
    dropped = [
        k
        for k in LEAK_KEYS
        if k not in proj and all(k not in (p if isinstance(p, dict) else {}) for p in proj.get("points", []))
    ]
    leaked = [
        k
        for k in LEAK_KEYS
        if k in proj or any(k in (p if isinstance(p, dict) else {}) for p in proj.get("points", []))
    ]
    retained = [k for k in ("trip_id", "points", "cancellation_reason", "cancellation_actor") if k in proj]
    leak_s = time.perf_counter() - t_leak

    manifest = json.loads((REPO_ROOT / args.manifest).read_text(encoding="utf-8"))
    profile = {
        "tool": "scripts/analyze_10k.py (issue #255)",
        "trips_file": args.trips,
        "trip_count": n,
        "class_counts": counts,
        "manifest_class_counts": manifest.get("class_counts"),
        "manifest_sha256": manifest.get("trips_sha256"),
        "label_provenance_ok": prov_ok,
        "label_provenance_share": round(prov_ok / n, 6) if n else 0.0,
        "distributions": distributions,
        "separability_vs_no_violation": separability,
        "separability_method": (
            "transductive single-feature ranking, labels eval-only; "
            "AUROC pairwise half-credit ties; AP groups ties; "
            "same as docs/data/MIPO_EDA.md"
        ),
        "gridlock_geometry": {
            "subset": "no_violation AND (gridlock_subset OR heavy traffic)",
            "n": gridlock_n,
            "ssd_ge_180": gridlock_ssd180,
            "share": round(gridlock_ssd180 / gridlock_n, 6) if gridlock_n else 0.0,
        },
        "leakage": {
            "bundle_scan_hits": leak_hits,
            "projection_dropped": dropped,
            "projection_leaked": leaked,
            "projection_retained_operational": retained,
        },
        "timings_s": {
            "read_extract": round(read_s, 2),
            "descriptives": round(stat_s, 2),
            "separability": round(sep_s, 2),
            "leakage": round(leak_s, 4),
            "total": round(time.perf_counter() - t_all, 2),
        },
    }
    out = REPO_ROOT / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(profile, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "n": n,
                "counts": counts,
                "prov_share": profile["label_provenance_share"],
                "gridlock": profile["gridlock_geometry"],
                "leaks": leak_hits,
                "proj_leaked": leaked,
                "sep": [(s["pos_class"], s["feature"], s["auroc"], s["average_precision"]) for s in separability],
                "timings": profile["timings_s"],
                "out": args.out,
            },
            indent=1,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


def leakage_paths(value, path="") -> list[str]:
    """Find prohibited metadata recursively, including future prefixed keys."""
    found = []
    if isinstance(value, dict):
        for key, item in value.items():
            child = f"{path}.{key}" if path else key
            if key in LEAK_KEYS or key.startswith(("expected_", "simulation_", "anomaly_")):
                found.append(child)
            found.extend(leakage_paths(item, child))
    elif isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            found.extend(leakage_paths(item, f"{path}[{index}]"))
    return found


def audit_bundle(bundle: dict) -> dict:
    """Audit actual benchmark model_dump, separately from stored generator metadata."""
    from scripts.benchmark.run_10k import bundle_to_input

    projected = bundle_to_input(bundle)[0].model_dump()
    mutated = deepcopy(bundle)
    mutated.update(
        label="audit-mutated-label",
        scenario="audit-mutated-scenario",
        measured_features={"approach_ssd_s": 999999},
        route={"tortuosity": 999999},
    )
    for key in ("driver_profile", "driver", "driver_analytics"):
        if isinstance(mutated.get(key), dict):
            mutated[key].update(fraud_propensity="audit-mutated", profile_provenance={"source": "audit"})
    return {
        "stored_profile_metadata": leakage_paths(bundle.get("driver_profile") or bundle.get("driver") or {}),
        "detector_leak_paths": leakage_paths(projected),
        "label_mutation_input_unchanged": projected == bundle_to_input(mutated)[0].model_dump(),
    }

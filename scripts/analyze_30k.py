"""Combined 30k analysis across benchmark batches v1+v2+v3.

Reads per-batch trips/labels/predictions/manifests, verifies sha256 +
cross-batch dedup, scores combined offline-heuristic metrics, tabulates
new-subset coverage (dialogue sparsity, legit cancels, feedback, G1/G2).

Outputs: notebooks/benchmark10k/metrics_30k.json (tracked) + regenerates
data/benchmark-10k/combined.json + combined_labels.csv as the true 30k union
(small tracked files; bulk trips stay per-batch, git-ignored).

Usage: python3 scripts/analyze_30k.py
"""

import csv
import hashlib
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "benchmark-10k"
BATCHES = ["v1", "v2", "v3"]


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_labels(version: str) -> dict:
    out = {}
    with open(DATA / version / "labels.csv") as f:
        for row in csv.DictReader(f):
            out[row["trip_ref"]] = row["label"]
    return out


def load_predictions(version: str) -> dict:
    out = {}
    with open(DATA / version / "predictions.jsonl") as f:
        for line in f:
            p = json.loads(line)
            out[p["trip_ref"]] = p
    return out


def prf(y_true: list, y_pred: list, labels: list) -> dict:
    stats = {}
    for lab in labels:
        tp = sum(1 for t, p in zip(y_true, y_pred) if t == lab and p == lab)
        fp = sum(1 for t, p in zip(y_true, y_pred) if t != lab and p == lab)
        fn = sum(1 for t, p in zip(y_true, y_pred) if t == lab and p != lab)
        prec = tp / (tp + fp) if tp + fp else 0.0
        rec = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
        stats[lab] = {
            "precision": round(prec, 4),
            "recall": round(rec, 4),
            "f1": round(f1, 4),
            "support": sum(1 for t in y_true if t == lab),
        }
    macro_f1 = sum(s["f1"] for s in stats.values()) / len(stats)
    acc = sum(1 for t, p in zip(y_true, y_pred) if t == p) / len(y_true)
    return {"accuracy": round(acc, 4), "macro_f1": round(macro_f1, 4), "per_class": stats}


def geom_hash(bundle: dict) -> str:
    pts = bundle.get("telemetry") or []
    seq = [(round(p.get("latitude") or 0, 5), round(p.get("longitude") or 0, 5)) for p in pts]
    return hashlib.sha256(json.dumps(seq).encode()).hexdigest()[:16]


def main() -> int:
    report = {"batches": {}, "combined": {}}
    all_true, all_pred = [], []
    seen_refs: set = set()
    seen_trip_ids: set = set()
    seen_assign: set = set()
    seen_geom: set = set()
    dup = Counter()
    combined_counts = Counter()
    subset_totals = Counter()
    dialogue_totals = Counter()
    feedback_n, feedback_rated = 0, 0
    driver_batches: dict = defaultdict(set)

    for v in BATCHES:
        bdir = DATA / v
        manifest = json.load(open(bdir / "manifest.json"))
        actual_sha = sha256_file(bdir / "trips.jsonl")
        sha_ok = actual_sha == manifest["trips_sha256"]
        labels = load_labels(v)
        preds = load_predictions(v)
        assert set(labels) == set(preds), f"{v}: labels/predictions ref mismatch"

        y_true = [labels[r] for r in sorted(labels)]
        y_pred = [preds[r]["predicted_category"] for r in sorted(labels)]
        classes = sorted(set(y_true) | set(y_pred))
        metrics = prf(y_true, y_pred, classes)
        blocked = sum(1 for p in preds.values() if p.get("guardrail_blocked"))
        counts = Counter(y_true)
        combined_counts.update(counts)
        all_true.extend(y_true)
        all_pred.extend(y_pred)

        coverage = Counter()
        for line in open(bdir / "trips.jsonl"):
            b = json.loads(line)
            ref = b["trip_ref"]
            if ref in seen_refs:
                dup["trip_ref"] += 1
            seen_refs.add(ref)
            for key, store in (("trip_id", seen_trip_ids), ("assignment_id", seen_assign)):
                val = b.get(key)
                if val in store:
                    dup[key] += 1
                store.add(val)
            gh = geom_hash(b)
            if gh in seen_geom:
                dup["geometry"] += 1
            seen_geom.add(gh)
            driver_batches[b.get("driver_id")].add(v)
            dm = b.get("dialogue_mode") or "full-legacy"
            dialogue_totals[f"{v}:{dm}"] += 1
            if b.get("passenger_feedback") is not None:
                feedback_n += 1
                fb = b["passenger_feedback"] or {}
                if fb.get("rating") is not None:
                    feedback_rated += 1
            for s in ("legit_cancel_subset", "slowcrawl_subset", "loop_subset"):
                if b.get(s):
                    coverage[s] += 1
                    subset_totals[f"{v}:{s}"] += 1
            if len(b.get("conversation") or []) == 0:
                coverage["empty_conversation"] += 1

        report["batches"][v] = {
            "n": len(labels),
            "sha_match": sha_ok,
            "trips_sha256": manifest["trips_sha256"],
            "class_counts": dict(sorted(counts.items())),
            "accuracy": metrics["accuracy"],
            "macro_f1": metrics["macro_f1"],
            "guardrail_blocked": blocked,
            "guardrail_block_rate": round(blocked / len(preds), 4),
            "per_class": metrics["per_class"],
            "coverage": dict(sorted(coverage.items())),
        }
        print(
            f"{v}: n={len(labels)} sha_ok={sha_ok} "
            f"acc={metrics['accuracy']} macroF1={metrics['macro_f1']} blocked={blocked}"
        )

    classes = sorted(set(all_true) | set(all_pred))
    combined_metrics = prf(all_true, all_pred, classes)
    multi_batch_drivers = sum(1 for vs in driver_batches.values() if len(vs) > 1)
    report["combined"] = {
        "n": len(all_true),
        "class_counts": dict(sorted(combined_counts.items())),
        "accuracy": combined_metrics["accuracy"],
        "macro_f1": combined_metrics["macro_f1"],
        "per_class": combined_metrics["per_class"],
        "cross_batch_duplicates": dict(dup),
        "distinct_drivers": len(driver_batches),
        "drivers_spanning_batches": multi_batch_drivers,
        "dialogue_modes": dict(sorted(dialogue_totals.items())),
        "subset_totals": dict(sorted(subset_totals.items())),
        "trips_with_feedback_block": feedback_n,
        "trips_with_feedback_rating": feedback_rated,
    }

    out = ROOT / "notebooks" / "benchmark10k" / "metrics_30k.json"
    out.write_text(json.dumps(report, indent=2))
    print(f"wrote {out}")

    # Regenerate true-30k union files at data/benchmark-10k/ root.
    union = {
        "batches": [
            {
                "name": v,
                "n": report["batches"][v]["n"],
                "seed": json.load(open(DATA / v / "manifest.json"))["seed"],
                "trips_sha256": report["batches"][v]["trips_sha256"],
                "class_counts": report["batches"][v]["class_counts"],
            }
            for v in BATCHES
        ],
        "total_trips": len(all_true),
    }
    (DATA / "combined.json").write_text(json.dumps(union, indent=2) + "\n")
    with open(DATA / "combined_labels.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["trip_ref", "label", "batch"])
        for v in BATCHES:
            for ref, lab in sorted(load_labels(v).items()):
                w.writerow([ref, lab, v])
    print("regenerated combined.json + combined_labels.csv (30k union)")
    print(json.dumps(report["combined"]["class_counts"], indent=2))
    print("dup:", dict(dup), "| drivers:", len(driver_batches), "| multi-batch drivers:", multi_batch_drivers)
    print(f"feedback block: {feedback_n} | with rating: {feedback_rated}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

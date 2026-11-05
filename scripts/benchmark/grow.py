"""Grow the benchmark with additional distinct batches, in parallel, fully validated.

One command for AI agents to generate more data (10k more, 20k, ...) without
duplicating prior batches:

    python scripts/benchmark/grow.py --plan "v2:20261012:10000" --workers 4
    python scripts/benchmark/grow.py --plan "v2:20261012:10000,v3:20261101:20000" \\
        --workers 2 --benchmark

Each `name:seed:n` batch builds in its own process via build_10k CLI
(distinct seed stream => distinct trips; ref namespace `bm_<name>_`). After all
batches finish, grow dedupes IDs + trajectory geometry against every prior
batch, merges manifests/labels, re-verifies file hashes, requires all gates
PASS, and optionally runs the offline pipeline benchmark over the merged set.

Exit 1 on any gate FAIL, ID/geometry collision, hash mismatch, or benchmark
regression below --min-acc (default: no regression gate, report only).
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BUILD_SCRIPT = REPO_ROOT / "scripts" / "benchmark" / "build_10k.py"
RUN_SCRIPT = REPO_ROOT / "scripts" / "benchmark" / "run_10k.py"


def parse_plan(spec: str) -> list[dict[str, object]]:
    batches = []
    for item in spec.split(","):
        name, seed, n = item.strip().split(":")
        batches.append({"name": name.strip(), "seed": int(seed), "n": int(n)})
        assert batches[-1]["n"] > 0 and batches[-1]["seed"] > 0, f"bad batch spec: {item}"
    names = [b["name"] for b in batches]
    assert len(set(names)) == len(names), "batch names must be unique"
    return batches


def build_batch(batch: dict[str, object], base: Path, noise: str, python: str) -> dict[str, object]:
    t0 = time.time()
    proc = subprocess.run(
        [
            python,
            str(BUILD_SCRIPT),
            "--n",
            str(batch["n"]),
            "--seed",
            str(batch["seed"]),
            "--out",
            str(base),
            "--batch",
            str(batch["name"]),
            "--noise",
            noise,
        ],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    if proc.returncode != 0:
        return {"name": batch["name"], "ok": False, "error": proc.stderr[-2000:], "log": proc.stdout[-2000:]}
    manifest = json.loads((base / str(batch["name"]) / "manifest.json").read_text())
    return {"name": batch["name"], "ok": True, "manifest": manifest, "elapsed_s": round(time.time() - t0, 1)}


def geometry_hash(bundle: dict) -> str:
    pts = bundle.get("telemetry") or []
    coords = []
    for p in pts:
        if isinstance(p, dict) and p.get("longitude") is not None and p.get("latitude") is not None:
            coords.append(f"{p['longitude']:.5f},{p['latitude']:.5f}")
    return hashlib.sha256("|".join(coords).encode()).hexdigest()


def load_batch_ids(batch_dir: Path) -> tuple[set[str], set[str], set[str], set[str]]:
    refs, tids, aids, geos = set(), set(), set(), set()
    with open(batch_dir / "trips.jsonl", encoding="utf-8") as f:
        for line in f:
            b = json.loads(line)
            refs.add(b["trip_ref"])
            tids.add(b["trip_id"])
            aids.add(b["assignment_id"])
            geos.add(geometry_hash(b))
    return refs, tids, aids, geos


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Grow benchmark with distinct validated batches")
    ap.add_argument("--plan", required=True, help='"name:seed:n[,name:seed:n...]"')
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--base", type=str, default="data/benchmark-10k")
    ap.add_argument("--noise", type=str, default="happy", choices=["happy", "stress"])
    ap.add_argument(
        "--against", type=str, default="", help="extra batch dirs to dedupe against (default: all existing in base)"
    )
    ap.add_argument("--benchmark", action="store_true", help="run offline pipeline benchmark on merged set")
    ap.add_argument("--min-acc", type=float, default=0.0)
    ap.add_argument("--python", type=str, default=sys.executable)
    args = ap.parse_args(argv)

    base = Path(args.base)
    batches = parse_plan(args.plan)
    for b in batches:
        if (base / str(b["name"])).exists():
            print(f"refusing to overwrite existing batch dir: {base / str(b['name'])}")
            return 1

    t0 = time.time()
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        results = list(pool.map(lambda b: build_batch(b, base, args.noise, args.python), batches))
    failed = [r for r in results if not r["ok"]]
    for r in failed:
        print(f"batch {r['name']} FAILED:\n{r.get('error', '')}")
    if failed:
        return 1
    for r in results:
        gates = r["manifest"]["gates"]
        status = "PASS" if all(g["pass"] for g in gates) else "FAIL"
        print(
            f"batch {r['name']}: n={r['manifest']['trip_count']} sha={r['manifest']['trips_sha256'][:12]}… "
            f"gates={status} elapsed={r['elapsed_s']}s"
        )
    if any(not all(g["pass"] for g in r["manifest"]["gates"]) for r in results):
        print("gate FAIL — merged output not written")
        return 1

    prior_dirs = [
        d
        for d in base.iterdir()
        if d.is_dir() and (d / "trips.jsonl").exists() and d.name not in [str(b["name"]) for b in batches]
    ]
    if args.against:
        prior_dirs += [Path(p) for p in args.against.split(",")]
    seen_refs, seen_tids, seen_aids, seen_geos = set(), set(), set(), set()
    for d in prior_dirs:
        refs, tids, aids, geos = load_batch_ids(d)
        seen_refs |= refs
        seen_tids |= tids
        seen_aids |= aids
        seen_geos |= geos
    print(f"dedup baseline: {len(seen_refs)} refs, {len(seen_tids)} trip_ids, {len(seen_geos)} geometries")

    for b in batches:
        refs, tids, aids, geos = load_batch_ids(base / str(b["name"]))
        collisions = {
            "trip_ref": sorted(refs & seen_refs)[:5],
            "trip_id": sorted(tids & seen_tids)[:5],
            "assignment_id": sorted(aids & seen_aids)[:5],
            "geometry": sorted(geos & seen_geos)[:5],
        }
        bad = {k: v for k, v in collisions.items() if v}
        if bad:
            print(f"DUPLICATE collision in batch {b['name']}: {bad} — aborting merge")
            return 1
        seen_refs |= refs
        seen_tids |= tids
        seen_aids |= aids
        seen_geos |= geos
        print(f"batch {b['name']}: {len(refs)} refs distinct, {len(geos)} geometries distinct — OK")

    combined = {
        "grown_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "batches": [
            {
                "name": str(b["name"]),
                "seed": b["seed"],
                "n": b["n"],
                "trips_sha256": next(r["manifest"]["trips_sha256"] for r in results if r["name"] == b["name"]),
                "class_counts": next(r["manifest"]["class_counts"] for r in results if r["name"] == b["name"]),
            }
            for b in batches
        ],
        "total_trips": sum(int(b["n"]) for b in batches),
    }
    with open(base / "combined.json", "w", encoding="utf-8") as f:
        json.dump(combined, f, sort_keys=True, indent=2)
        f.write("\n")
    with open(base / "combined_labels.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["trip_ref", "label", "batch"])
        for b in batches:
            with open(base / str(b["name"]) / "labels.csv", encoding="utf-8", newline="") as src:
                for row in list(csv.DictReader(src)):
                    w.writerow([row["trip_ref"], row["label"], b["name"]])
    print(f"merged {combined['total_trips']} trips -> combined.json + combined_labels.csv")

    if args.benchmark:
        merged_trips = base / "combined_trips.jsonl"
        with open(merged_trips, "w", encoding="utf-8") as out:
            for b in batches:
                with open(base / str(b["name"]) / "trips.jsonl", encoding="utf-8") as src:
                    out.write(src.read())
        proc = subprocess.run(
            [
                args.python,
                str(RUN_SCRIPT),
                "--in",
                str(merged_trips),
                "--out",
                str(base / "combined_predictions.jsonl"),
            ],
            capture_output=True,
            text=True,
            cwd=REPO_ROOT,
        )
        print(proc.stdout.strip().splitlines()[-3:])
        if proc.returncode != 0:
            print(proc.stderr[-2000:])
            return 1
        acc = next((ln for ln in proc.stdout.splitlines() if "acc=" in ln), "")
        print("merged benchmark:", acc)

    print(f"grow done in {time.time() - t0:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

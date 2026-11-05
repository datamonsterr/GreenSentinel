"""Dataset builder and CLI entrypoint for releases_v2 corpus."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import pyarrow as pa  # noqa: E402
import pyarrow.parquet as pq  # noqa: E402

from scripts.benchmark.build_v2.config import GeneratorV2Config  # noqa: E402
from scripts.benchmark.build_v2.generator import build_v2_trip  # noqa: E402
from scripts.benchmark.build_v2.geometry import load_corridors  # noqa: E402
from scripts.benchmark.population_synth import synthesize_drivers, synthesize_passengers  # noqa: E402


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def generate_v2_dataset(
    out_dir: Path,
    config: GeneratorV2Config | None = None,
) -> tuple[Path, str, dict[str, Any]]:
    cfg = config or GeneratorV2Config()
    out_dir.mkdir(parents=True, exist_ok=True)
    corridors = load_corridors(cfg.corridors_path)

    rng = random.Random(cfg.seed)

    # 1. Driver population and disjoint split partition (70% train, 15% val, 15% test)
    total_drivers = cfg.total_drivers
    drivers = synthesize_drivers(random.Random(cfg.seed + 101), total_drivers)
    passengers = synthesize_passengers(random.Random(cfg.seed + 202), cfg.total_passengers)

    n_train_dr = int(round(total_drivers * cfg.split_ratios["train"]))
    n_val_dr = int(round(total_drivers * cfg.split_ratios["validation"]))

    train_drivers = drivers[:n_train_dr]
    val_drivers = drivers[n_train_dr : n_train_dr + n_val_dr]
    test_drivers = drivers[n_train_dr + n_val_dr :]

    train_dr_ids = {d["id"] for d in train_drivers}
    val_dr_ids = {d["id"] for d in val_drivers}
    test_dr_ids = {d["id"] for d in test_drivers}

    # Verify zero driver leakage
    assert len(train_dr_ids & val_dr_ids) == 0
    assert len(train_dr_ids & test_dr_ids) == 0
    assert len(val_dr_ids & test_dr_ids) == 0

    # 2. Split trips and label mix
    total_trips = cfg.n_trips
    class_counts = cfg.calculate_class_counts(total_trips)

    target_labels: list[str] = []
    for cls, count in class_counts.items():
        target_labels.extend([cls] * count)

    rng.shuffle(target_labels)

    train_n = int(round(total_trips * cfg.split_ratios["train"]))
    val_n = int(round(total_trips * cfg.split_ratios["validation"]))

    trips_path = out_dir / "trips.jsonl"
    labels_csv_path = out_dir / "labels.csv"
    sample_100_jsonl = out_dir / "sample_100.jsonl"
    sample_100_parquet = out_dir / "sample_100.parquet"
    manifest_path = out_dir / "manifest.json"
    checksums_path = out_dir / "checksums.json"

    trips_hasher = hashlib.sha256()
    sample_rows: list[dict[str, Any]] = []

    actual_class_counts: dict[str, int] = {}
    actual_split_counts: dict[str, int] = {"train": 0, "validation": 0, "test": 0}
    actual_severity_counts: dict[str, int] = {}
    profile_point_counts: dict[float, list[int]] = {p[0]: [] for p in cfg.ping_profiles}

    t_start = time.time()
    with (
        open(trips_path, "w", encoding="utf-8") as f_trips,
        open(labels_csv_path, "w", encoding="utf-8", newline="") as f_csv,
    ):
        csv_writer = csv.writer(f_csv)
        csv_writer.writerow(["trip_ref", "label", "release", "split", "prevalence_weight"])

        for idx, label in enumerate(target_labels):
            if idx < train_n:
                split = "train"
                driver_pool = train_drivers
            elif idx < train_n + val_n:
                split = "validation"
                driver_pool = val_drivers
            else:
                split = "test"
                driver_pool = test_drivers

            driver = driver_pool[idx % len(driver_pool)]
            passenger = passengers[idx % len(passengers)]

            trip_seed = (cfg.seed % (2**31)) * 31337 + idx
            trip_rng = random.Random(trip_seed)

            trip = build_v2_trip(
                idx=idx,
                label=label,
                split=split,
                driver=driver,
                passenger=passenger,
                corridors=corridors,
                config=cfg,
                trip_rng=trip_rng,
            )

            actual_class_counts[label] = actual_class_counts.get(label, 0) + 1
            actual_split_counts[split] += 1
            sev = trip.get("severity") or trip.get("simulation_audit", {}).get("severity") or "None"
            actual_severity_counts[sev] = actual_severity_counts.get(sev, 0) + 1

            cadence = trip.get("simulation_audit", {}).get("ping_profile_s")
            if cadence in profile_point_counts:
                profile_point_counts[cadence].append(len(trip["telemetry"]))

            line_str = json.dumps(trip, ensure_ascii=False) + "\n"
            line_bytes = line_str.encode("utf-8")
            f_trips.write(line_str)
            trips_hasher.update(line_bytes)

            csv_writer.writerow(
                [trip["trip_ref"], trip["label"], trip["release"], trip["split"], trip["prevalence_weight"]]
            )

            if len(sample_rows) < 100:
                sample_rows.append(trip)

            if (idx + 1) % 5000 == 0:
                elapsed = time.time() - t_start
                rate = (idx + 1) / max(0.1, elapsed)
                print(f"Generated {idx + 1}/{total_trips} trips ({rate:.1f} trips/s)...")

    trips_sha256 = trips_hasher.hexdigest()

    # Write sample_100.jsonl and sample_100.parquet
    with open(sample_100_jsonl, "w", encoding="utf-8") as f:
        for s in sample_rows:
            f.write(json.dumps(s, ensure_ascii=False) + "\n")

    # Serialize sample to parquet preserving nested json
    sample_flat = []
    for s in sample_rows:
        sample_flat.append(
            {
                "trip_ref": s["trip_ref"],
                "trip_id": s["trip_id"],
                "release": s["release"],
                "split": s["split"],
                "label": s["label"],
                "severity": s.get("severity") or s.get("simulation_audit", {}).get("severity"),
                "prevalence_weight": s["prevalence_weight"],
                "bundle_json": json.dumps(s, ensure_ascii=False),
            }
        )
    pq_table = pa.Table.from_pylist(sample_flat)
    pq.write_table(pq_table, sample_100_parquet)

    ping_profile_summary = {}
    for cad, pt_list in profile_point_counts.items():
        if pt_list:
            sorted_pts = sorted(pt_list)
            n_prof = len(sorted_pts)
            ping_profile_summary[f"{cad:.1f}s"] = {
                "trips": n_prof,
                "points_mean": round(float(sum(sorted_pts) / n_prof), 1),
                "points_p50": sorted_pts[int(n_prof * 0.50)],
                "points_p90": sorted_pts[int(n_prof * 0.90)],
                "points_max": sorted_pts[-1],
            }
        else:
            ping_profile_summary[f"{cad:.1f}s"] = {"trips": 0}

    manifest = {
        "release": cfg.release_name,
        "generator_version": cfg.generator_version,
        "seed": cfg.seed,
        "total_trips": total_trips,
        "trips_sha256": trips_sha256,
        "class_counts": actual_class_counts,
        "split_counts": actual_split_counts,
        "severity_counts": actual_severity_counts,
        "ping_profiles": ping_profile_summary,
        "drivers": {
            "total": len(drivers),
            "train": len(train_drivers),
            "validation": len(val_drivers),
            "test": len(test_drivers),
            "leakage": 0,
        },
        "passengers": {
            "total": len(passengers),
        },
        "corridors_count": len(corridors),
        "created_at": datetime.now(UTC).isoformat(),
    }

    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)

    checksums = {
        "trips.jsonl": trips_sha256,
        "labels.csv": sha256_file(labels_csv_path),
        "manifest.json": sha256_file(manifest_path),
        "sample_100.jsonl": sha256_file(sample_100_jsonl),
        "sample_100.parquet": sha256_file(sample_100_parquet),
    }

    with open(checksums_path, "w", encoding="utf-8") as f:
        json.dump(checksums, f, indent=2)

    return out_dir, trips_sha256, manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate releases_v2 realistic corpus")
    parser.add_argument("--n", type=int, default=40000, help="Number of trips to generate (default: 40000)")
    parser.add_argument(
        "--out", type=Path, default=REPO_ROOT / "data" / "benchmark-10k" / "releases_v2", help="Output directory"
    )
    parser.add_argument("--seed", type=int, default=20261017, help="RNG seed")
    parser.add_argument("--drivers", type=int, default=2000, help="Number of drivers")
    parser.add_argument("--max-points", type=int, default=None, help="Downsample points per trip to at most N points")
    args = parser.parse_args(argv)

    cfg = GeneratorV2Config(
        seed=args.seed,
        n_trips=args.n,
        total_drivers=args.drivers,
        max_points_per_trip=args.max_points,
    )
    print(f"Building {args.n} trips to {args.out} with seed {args.seed}...")
    t0 = time.time()
    out_dir, sha, manifest = generate_v2_dataset(args.out, config=cfg)
    elapsed = time.time() - t0
    print(f"Done in {elapsed:.1f}s!")
    print(f"Output: {out_dir}")
    print(f"trips_sha256: {sha}")
    print(f"Classes: {manifest['class_counts']}")
    print(f"Splits: {manifest['split_counts']}")
    print(f"Ping profiles: {manifest.get('ping_profiles')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

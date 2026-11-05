"""Stratified Porto Taxi UCI EDA for 10k fraud-benchmark priors; streams zip, no extract.

Sample: seed 63, n=50k max, proportional allocation over
CALL_TYPE (A/B/C) x weekday/weekend (UTC arithmetic from TIMESTAMP),
per-stratum reservoir sampling in file order. Geometry/kinematics +
missingness only; Porto has no intent/fraud labels.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import platform
import time
import zipfile
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
ZIP_PATH = ROOT / "data/raw/porto_taxi_uci/train.csv.zip"
INNER = "train.csv"
SEED = 63
N_SAMPLE = 50_000
CADENCE_S = 15.0
STOP_DISP_M = 15.0  # FEATURE_PARAMS segment_min_displacement_m; stop run = consecutive segs < this
IMPLAUSIBLE_MPS = 50.0  # FEATURE_PARAMS implausible_speed_mps
ERR02_SSD_S = 180.0
EARTH_R_M = 6_371_008.8


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def describe(values: Any) -> dict[str, float | int]:
    a = np.asarray(values, dtype=float)
    finite = a[np.isfinite(a)]
    result: dict[str, float | int] = {"count": len(a), "nonfinite": int(len(a) - len(finite))}
    if len(finite):
        result.update(
            {
                k: float(v)
                for k, v in zip(
                    ["min", "p05", "p25", "p50", "p75", "p95", "max"],
                    np.quantile(finite, [0, 0.05, 0.25, 0.5, 0.75, 0.95, 1]),
                )
            }
        )
        result.update(mean=float(finite.mean()), std=float(finite.std()))
    return result


def haversine_m(lon1: np.ndarray, lat1: np.ndarray, lon2: np.ndarray, lat2: np.ndarray) -> np.ndarray:
    r = np.radians
    dlat, dlon = r(lat2 - lat1), r(lon2 - lon1)
    h = np.sin(dlat / 2) ** 2 + np.cos(r(lat1)) * np.cos(r(lat2)) * np.sin(dlon / 2) ** 2
    return 2 * EARTH_R_M * np.arcsin(np.sqrt(h))


def parse_polyline(raw: str) -> np.ndarray:
    pts = json.loads(raw) if raw else []
    a = np.asarray(pts, dtype=float)
    if a.size == 0:
        return np.empty((0, 2))
    if a.ndim != 2 or a.shape[1] != 2 or not np.isfinite(a).all():
        raise ValueError("Non-finite or malformed POLYLINE")
    return a


def trip_features(poly: np.ndarray) -> dict[str, Any]:
    n = len(poly)
    if n < 2:
        return {
            "segments": np.empty(0),
            "path_m": 0.0 if n else float("nan"),
            "endpoint_m": float("nan"),
            "tortuosity": float("nan"),
        }
    seg = haversine_m(poly[:-1, 0], poly[:-1, 1], poly[1:, 0], poly[1:, 1])
    path = float(seg.sum())
    end = float(haversine_m(poly[:1, 0], poly[:1, 1], poly[-1:, 0], poly[-1:, 1])[0])
    return {"segments": seg, "path_m": path, "endpoint_m": end, "tortuosity": path / end if end > 0 else float("nan")}


def max_stop_run_s(seg: np.ndarray) -> float:
    if len(seg) == 0:
        return 0.0
    stopped = seg < STOP_DISP_M
    if not stopped.any():
        return 0.0
    runs = np.diff(np.concatenate(([0], stopped.view(np.int8), [0])))
    lengths = np.where(runs == -1)[0] - np.where(runs == 1)[0]
    return float(lengths.max() * CADENCE_S)


def open_rows():
    z = zipfile.ZipFile(ZIP_PATH)
    return z, csv.DictReader(io.TextIOWrapper(z.open(INNER), encoding="utf-8"))


def stratum_key(call_type: str, ts: int) -> str:
    days = ts // 86_400
    weekend = (days + 3) % 7 >= 5  # 1970-01-01 was Thursday; UTC date
    return f"{call_type}x{'wke' if weekend else 'wkd'}"


def run() -> dict[str, Any]:
    t_start = time.perf_counter()
    if digest(ZIP_PATH.read_bytes()) != "210dd0a20da66a8fc2de3440aecd84670921bc257591f8365a4475e31453c5ea":
        raise ValueError("Porto zip checksum mismatch")

    # Pass 1: strata counts, driver counts, MISSING_DATA census, empty rate.
    strata: Counter = Counter()
    drivers: Counter = Counter()
    missing_true_points: list[int] = []
    total, empty = 0, 0
    z, rows = open_rows()
    with z:
        for row in rows:
            total += 1
            ts = int(row["TIMESTAMP"])
            strata[stratum_key(row["CALL_TYPE"], ts)] += 1
            drivers[row["TAXI_ID"]] += 1
            raw = row["POLYLINE"]
            if raw == "[]" or not raw:
                empty += 1
            if row["MISSING_DATA"] == "True":
                missing_true_points.append(len(parse_polyline(raw)))
    pass1_s = time.perf_counter() - t_start

    # Proportional allocation, largest remainder, exact N_SAMPLE.
    order = sorted(strata)
    quotas = {s: strata[s] / total * N_SAMPLE for s in order}
    alloc = {s: int(quotas[s]) for s in order}
    remainder = N_SAMPLE - sum(alloc.values())
    for s in sorted(order, key=lambda s: quotas[s] - alloc[s], reverse=True)[:remainder]:
        alloc[s] += 1

    # Pass 2: per-stratum reservoir sampling, seed 63, file order.
    rng = np.random.default_rng(SEED)
    seen: Counter = Counter()
    reservoir: dict[str, list[dict[str, str]]] = {s: [] for s in order}
    z, rows = open_rows()
    with z:
        for row in rows:
            s = stratum_key(row["CALL_TYPE"], int(row["TIMESTAMP"]))
            k = alloc[s]
            if k == 0:
                continue
            seen[s] += 1
            i = seen[s]
            keep = {
                "call": row["CALL_TYPE"],
                "taxi": row["TAXI_ID"],
                "ts": row["TIMESTAMP"],
                "missing": row["MISSING_DATA"],
                "poly": row["POLYLINE"],
            }
            if i <= k:
                reservoir[s].append(keep)
            else:
                j = int(rng.integers(0, i))
                if j < k:
                    reservoir[s][j] = keep
    pass2_s = time.perf_counter() - t_start - pass1_s
    sample = [r for s in order for r in reservoir[s]]
    assert len(sample) == N_SAMPLE, (len(sample), N_SAMPLE)

    # Metrics on sample.
    t_feat = time.perf_counter()
    feats, seg_pool = [], []
    for r in sample:
        poly = parse_polyline(r["poly"])
        f = trip_features(poly)
        seg = f["segments"]
        seg_pool.append(seg)
        ts = int(r["ts"])
        feats.append(
            {
                "points": len(poly),
                "duration_s": len(poly) * CADENCE_S,
                "path_m": f["path_m"],
                "endpoint_m": f["endpoint_m"],
                "tortuosity": f["tortuosity"],
                "speed_max_mps": float((seg / CADENCE_S).max()) if len(seg) else float("nan"),
                "speed_share_gt50": float(((seg / CADENCE_S) > IMPLAUSIBLE_MPS).mean()) if len(seg) else float("nan"),
                "zero_seg_fraction": float((seg == 0).mean()) if len(seg) else float("nan"),
                "max_stop_run_s": max_stop_run_s(seg),
                "call": r["call"],
                "taxi": r["taxi"],
                "hour_utc": (ts % 86_400) // 3_600,
                "weekend": stratum_key(r["call"], ts).endswith("wke"),
                "missing": r["missing"] == "True",
            }
        )
    seg_all = np.concatenate([s for s in seg_pool if len(s)]) if any(len(s) for s in seg_pool) else np.empty(0)
    speed_all = seg_all / CADENCE_S
    feat_s = time.perf_counter() - t_feat
    feat = {
        k: np.array([f[k] for f in feats], dtype=float)
        for k in [
            "points",
            "duration_s",
            "path_m",
            "endpoint_m",
            "tortuosity",
            "speed_max_mps",
            "speed_share_gt50",
            "zero_seg_fraction",
            "max_stop_run_s",
        ]
    }
    night = np.array([h >= 22 or h < 6 for h in [f["hour_utc"] for f in feats]])
    wkend = np.array([f["weekend"] for f in feats])
    calls = [f["call"] for f in feats]
    geo = int((feat["points"] >= 2).sum())

    report: dict[str, Any] = {
        "provenance": {
            "dataset": "Taxi Service Trajectory, ECML PKDD 2015 (Porto Taxi)",
            "url": "https://archive.ics.uci.edu/ml/machine-learning-databases/00339/train.csv.zip",
            "dataset_page": "https://archive.ics.uci.edu/dataset/339/taxi+",
            "doi": "10.24432/C55W25",
            "license": "CC BY 4.0; credit Moreira-Matias et al., UCI",
            "file_sha256": "210dd0a20da66a8fc2de3440aecd84670921bc257591f8365a4475e31453c5ea",
            "total_trips": total,
            "empty_polyline_full": empty,
            "seed": SEED,
            "sample_rows": len(sample),
            "strata_full": dict(sorted(strata.items())),
            "allocation": alloc,
            "sampling": "proportional CALL_TYPE(A/B/C)xweekday/weekend, per-stratum reservoir in file order",
            "cadence_s_nominal": CADENCE_S,
            "no_extract": "streamed via zipfile; no extracted files left on disk",
        },
        "environment": {
            "python": platform.python_version(),
            "numpy": np.__version__,
            "platform": platform.platform(),
            "logical_cpus": os.cpu_count(),
        },
        "rows": len(sample),
        "points": int(feat["points"].sum()),
        "trips_with_geometry_pts_ge2": geo,
        "empty_polyline_in_sample": int((feat["points"] == 0).sum()),
        "distributions": {
            "points": describe(feat["points"]),
            "duration_s": describe(feat["duration_s"]),
            "path_m": describe(feat["path_m"]),
            "endpoint_m": describe(feat["endpoint_m"]),
            "tortuosity": describe(feat["tortuosity"]),
            "per_trip_speed_max_mps": describe(feat["speed_max_mps"]),
            "per_trip_speed_share_gt50": describe(feat["speed_share_gt50"]),
            "per_trip_zero_seg_fraction": describe(feat["zero_seg_fraction"]),
            "per_trip_max_stop_run_s": describe(feat["max_stop_run_s"]),
        },
        "segment_speed_mps_pooled": describe(speed_all),
        "segments_total": int(len(speed_all)),
        "segments_zero_displacement": int((seg_all == 0).sum()),
        "segments_gt50": int((speed_all > IMPLAUSIBLE_MPS).sum()),
        "by_call_type": {
            c: {
                "n": sum(1 for x in calls if x == c),
                "points": describe(feat["points"][[x == c for x in calls]]),
                "path_m": describe(feat["path_m"][[x == c for x in calls]]),
                "tortuosity": describe(feat["tortuosity"][[x == c for x in calls]]),
            }
            for c in ["A", "B", "C"]
        },
        "missing_data": {
            "rate_full": len(missing_true_points) / total,
            "n_true_full": len(missing_true_points),
            "point_counts_true_census": sorted(missing_true_points),
            "n_true_in_sample": int(sum(f["missing"] for f in feats)),
        },
        "drivers": {
            "n_distinct_full": len(drivers),
            "trips_per_driver_full": describe(list(drivers.values())),
            "n_distinct_sample": len({f["taxi"] for f in feats}),
        },
        "split": {
            "night_share_sample": float(night.mean()),
            "night_def": "start hour_utc >= 22 or < 6 (UTC; Lisbon local differs, see limitations)",
            "weekend_share_sample": float(wkend.mean()),
            "weekend_def": "(days_since_epoch + 3) % 7 >= 5 on UTC date",
        },
        "threshold_checks": {
            "segment_share_speed_gt50": float((speed_all > IMPLAUSIBLE_MPS).mean()) if len(speed_all) else 0.0,
            "trip_share_max_stop_ge180s": float((feat["max_stop_run_s"] >= ERR02_SSD_S).mean()),
            "trip_share_zero_seg_gt0": float((feat["zero_seg_fraction"] > 0).mean()),
            "stop_criterion": f"run of consecutive segs with displacement < {STOP_DISP_M} m x {CADENCE_S:.0f} s",
        },
        "benchmark": {
            "design": "Two streaming passes over 509 MB zip + numpy metrics on 50k sample; no train/test claim",
            "pass1_strata_counts_s": pass1_s,
            "pass2_reservoir_s": pass2_s,
            "feature_extraction_s": feat_s,
            "total_s": time.perf_counter() - t_start,
        },
    }
    cpu = Path("/proc/cpuinfo")
    if cpu.exists():
        report["environment"]["cpu_model"] = next(
            (x.split(":", 1)[1].strip() for x in cpu.read_text().splitlines() if x.startswith("model name")), "unknown"
        )
    out = ROOT / "notebooks/porto"
    out.mkdir(parents=True, exist_ok=True)
    (out / "profile.json").write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    print(
        json.dumps(
            {
                k: report[k]
                for k in [
                    "rows",
                    "points",
                    "trips_with_geometry_pts_ge2",
                    "segments_total",
                    "threshold_checks",
                    "missing_data",
                    "benchmark",
                ]
            },
            indent=2,
        )
    )
    return report


if __name__ == "__main__":
    run()

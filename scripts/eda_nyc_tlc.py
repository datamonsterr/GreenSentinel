"""NYC TLC yellow 2024-01 EDA: duration/distance/fare priors + time-of-day scheduler shape.

Reads data/raw/nyc_tlc_sample/yellow_tripdata_2024-01.parquet (public domain,
tabular, no GPS). Writes notebooks/nyc/profile.json. Requires pandas+pyarrow.
"""

from __future__ import annotations

import hashlib
import json
import platform
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
PARQUET = ROOT / "data/raw/nyc_tlc_sample/yellow_tripdata_2024-01.parquet"
OUT = ROOT / "notebooks/nyc/profile.json"
MILES_TO_M = 1609.344
MAX_DUR_S = 10800  # 3 h validity cap
MAX_DIST_MI = 100


def q(v: pd.Series) -> dict:
    a = v.to_numpy(dtype=float)
    a = a[np.isfinite(a)]
    qs = np.quantile(a, [0, 0.05, 0.25, 0.5, 0.75, 0.95, 0.99, 1.0])
    return {k: float(x) for k, x in zip(["min", "p05", "p25", "p50", "p75", "p95", "p99", "max"], qs)} | {
        "mean": float(a.mean()),
        "std": float(a.std()),
        "count": int(len(a)),
    }


def run() -> dict:
    df = pd.read_parquet(PARQUET)
    n_raw = len(df)
    dur = (df["tpep_dropoff_datetime"] - df["tpep_pickup_datetime"]).dt.total_seconds()
    df = df.assign(duration_s=dur, distance_m=df["trip_distance"] * MILES_TO_M)
    invalid = {
        "duration_le0": int((dur <= 0).sum()),
        "duration_gt_3h": int((dur > MAX_DUR_S).sum()),
        "distance_le0": int((df["trip_distance"] <= 0).sum()),
        "distance_gt_100mi": int((df["trip_distance"] > MAX_DIST_MI).sum()),
        "fare_le0": int((df["fare_amount"] <= 0).sum()),
    }
    v = df[
        (df["duration_s"] > 0)
        & (df["duration_s"] <= MAX_DUR_S)
        & (df["trip_distance"] > 0)
        & (df["trip_distance"] <= MAX_DIST_MI)
        & (df["fare_amount"] > 0)
    ].copy()
    v["weekday"] = v["tpep_pickup_datetime"].dt.dayofweek  # Mon=0
    v["hour"] = v["tpep_pickup_datetime"].dt.hour
    v["speed_mps"] = v["distance_m"] / v["duration_s"]
    report = {
        "source": "data/raw/nyc_tlc_sample/yellow_tripdata_2024-01.parquet",
        "sha256": hashlib.sha256(PARQUET.read_bytes()).hexdigest(),
        "rows_raw": n_raw,
        "rows_valid": len(v),
        "validity_rule": "0<duration_s<=10800, 0<trip_distance_mi<=100, fare_amount>0",
        "invalid_counts": invalid,
        "environment": {"python": platform.python_version(), "pandas": pd.__version__},
        "duration_s": q(v["duration_s"]),
        "distance_mi": q(v["trip_distance"]),
        "distance_m": q(v["distance_m"]),
        "fare_amount": q(v["fare_amount"]),
        "total_amount": q(v["total_amount"]),
        "speed_mps": q(v["speed_mps"]),
        "weekday_share": {str(k): float(x) for k, x in v["weekday"].value_counts(normalize=True).sort_index().items()},
        "hour_share": {str(k): float(x) for k, x in v["hour"].value_counts(normalize=True).sort_index().items()},
        "weekend_share": float((v["weekday"] >= 5).mean()),
        "payment_mix": {str(k): float(x) for k, x in v["payment_type"].value_counts(normalize=True).items()},
        "payment_counts": {str(k): int(x) for k, x in v["payment_type"].value_counts().items()},
        "store_and_fwd": {
            "counts": {str(k): int(x) for k, x in v["store_and_fwd_flag"].value_counts(dropna=False).items()},
            "y_share": float((v["store_and_fwd_flag"] == "Y").mean()),
        },
        "dropout_cancellation_signal": "NONE: completed trips only; no cancellation/dropout columns",
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, indent=2) + "\n")
    print(
        json.dumps(
            {k: report[k] for k in ["rows_raw", "rows_valid", "duration_s", "distance_m", "fare_amount"]}, indent=2
        )
    )
    return report


if __name__ == "__main__":
    run()

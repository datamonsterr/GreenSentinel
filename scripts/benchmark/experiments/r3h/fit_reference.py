"""Fit reference distribution quantiles and class medians from train split (Issue #551 / #494).

Streams the TRAIN split only of /home/dat/releases_v2_1/trips.jsonl, builds the
'evidence' measurements per trip, and fits quantiles
(p01, p05, p10, p25, p50, p75, p90, p95, p99) over no_violation train trips.
Also computes train-split medians per violation class.
Writes JSON artifact to src/services/data/jev_reference_quantiles.json.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sys
from concurrent.futures import ProcessPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[4]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.benchmark.driver_ledger import driver_split  # noqa: E402
from scripts.benchmark.run_10k import bundle_to_input  # noqa: E402
from src.services.jev_state_builder import (  # noqa: E402
    _extract_lon_lat,
    build_evidence_measurements,
    compute_time_windowed_metrics,
    compute_whole_phase_metrics,
    derive_kinematics,
)

logger = logging.getLogger(__name__)

QUANTILES_LEVELS = [0.01, 0.05, 0.10, 0.25, 0.50, 0.75, 0.90, 0.95, 0.99]
QUANTILES_NAMES = ["p01", "p05", "p10", "p25", "p50", "p75", "p90", "p95", "p99"]


def compute_file_sha256(path: Path) -> str:
    """Compute sha256 checksum of an input file."""
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def extract_trip_measurements(bundle: dict[str, Any]) -> tuple[str, str, dict[str, float | None]]:
    """Extract evidence measurement numeric values from a single trip bundle."""
    label = str(bundle.get("label") or "no_violation")
    split = str(bundle.get("split") or "")
    if not split:
        drv_id = bundle.get("driver_id") or (bundle.get("driver_profile") or {}).get("driver_id") or "unknown"
        split = driver_split(str(drv_id))

    inp, points, _ = bundle_to_input(bundle)
    pickup_tuple = _extract_lon_lat(inp.trip_data.get("pickup") or bundle.get("pickup"))
    dropoff_tuple = _extract_lon_lat(inp.trip_data.get("dropoff") or bundle.get("dropoff"))

    kinematics = derive_kinematics(points)
    windows = compute_time_windowed_metrics(points, pickup=pickup_tuple, dropoff=dropoff_tuple, window_size_s=60.0)
    whole_phase = compute_whole_phase_metrics(points, bundle, pickup=pickup_tuple, dropoff=dropoff_tuple)
    has_mock = bool(inp.telemetry.get("mock_location_reported", False))

    raw_measurements = build_evidence_measurements(
        kinematics=kinematics,
        windows=windows,
        whole_phase=whole_phase,
        mock_location_reported=has_mock,
    )

    numeric_vals: dict[str, float | None] = {}
    for k, v in raw_measurements.items():
        val = v.get("value")
        if isinstance(val, (int, float)) and not isinstance(val, bool):
            numeric_vals[k] = float(val)
        else:
            numeric_vals[k] = None

    return split, label, numeric_vals


def _process_chunk_of_lines(lines: list[str]) -> list[tuple[str, str, dict[str, float | None]]]:
    """Helper for parallel processing of JSON lines."""
    results = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            b = json.loads(line)
            results.append(extract_trip_measurements(b))
        except Exception:
            continue
    return results


def compute_measurement_quantiles(values: list[float]) -> dict[str, float]:
    """Compute standard percentiles p01..p99 over a list of numeric values."""
    if not values:
        return {name: 0.0 for name in QUANTILES_NAMES}
    arr = np.array(values, dtype=float)
    arr = arr[np.isfinite(arr)]
    if len(arr) == 0:
        return {name: 0.0 for name in QUANTILES_NAMES}

    qs = np.quantile(arr, QUANTILES_LEVELS, method="linear")
    return {name: round(float(q), 4) for name, q in zip(QUANTILES_NAMES, qs)}


def compute_class_medians(class_values: dict[str, list[float]]) -> dict[str, float]:
    """Compute median value for each class."""
    medians: dict[str, float] = {}
    for cls_name, vals in sorted(class_values.items()):
        if not vals:
            continue
        arr = np.array(vals, dtype=float)
        arr = arr[np.isfinite(arr)]
        if len(arr) > 0:
            medians[cls_name] = round(float(np.median(arr)), 4)
    return medians


def fit_reference_distributions(
    in_path: Path | str,
    out_path: Path | str | None = None,
    split: str = "train",
    max_workers: int = 4,
    chunk_size: int = 200,
) -> dict[str, Any]:
    """Stream train split of trips corpus, compute evidence quantiles and class medians."""
    in_p = Path(in_path)
    if not in_p.exists():
        raise FileNotFoundError(f"Input corpus not found at {in_p}")

    corpus_sha = compute_file_sha256(in_p)

    nv_measurement_values: dict[str, list[float]] = {}
    class_measurement_values: dict[str, dict[str, list[float]]] = {}
    total_train_trips = 0
    total_nv_train_trips = 0

    # Stream file in chunks
    with in_p.open("r", encoding="utf-8") as f:
        if max_workers > 1:
            with ProcessPoolExecutor(max_workers=max_workers) as executor:
                chunk = []
                futures = []
                for line in f:
                    chunk.append(line)
                    if len(chunk) >= chunk_size:
                        futures.append(executor.submit(_process_chunk_of_lines, chunk))
                        chunk = []
                if chunk:
                    futures.append(executor.submit(_process_chunk_of_lines, chunk))

                for fut in futures:
                    for s, label, meas in fut.result():
                        if s != split:
                            continue
                        total_train_trips += 1
                        is_nv = label == "no_violation"
                        if is_nv:
                            total_nv_train_trips += 1

                        for m_name, m_val in meas.items():
                            if m_val is None:
                                continue
                            if is_nv:
                                nv_measurement_values.setdefault(m_name, []).append(m_val)
                            class_measurement_values.setdefault(m_name, {}).setdefault(label, []).append(m_val)
        else:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                b = json.loads(line)
                s, label, meas = extract_trip_measurements(b)
                if s != split:
                    continue
                total_train_trips += 1
                is_nv = label == "no_violation"
                if is_nv:
                    total_nv_train_trips += 1

                for m_name, m_val in meas.items():
                    if m_val is None:
                        continue
                    if is_nv:
                        nv_measurement_values.setdefault(m_name, []).append(m_val)
                    class_measurement_values.setdefault(m_name, {}).setdefault(label, []).append(m_val)

    # Compute quantiles over no_violation train trips
    fitted_quantiles: dict[str, dict[str, float]] = {}
    for m_name, vals in sorted(nv_measurement_values.items()):
        fitted_quantiles[m_name] = compute_measurement_quantiles(vals)

    # Compute class medians over train trips
    fitted_class_medians: dict[str, dict[str, float]] = {}
    for m_name, cls_dict in sorted(class_measurement_values.items()):
        fitted_class_medians[m_name] = compute_class_medians(cls_dict)

    result_artifact: dict[str, Any] = {
        "corpus_trips_sha256": corpus_sha,
        "split": split,
        "n": total_nv_train_trips,
        "total_train_trips": total_train_trips,
        "fitted_at": datetime.now(UTC).isoformat(),
        "quantiles": fitted_quantiles,
        "class_medians": fitted_class_medians,
    }

    if out_path is not None:
        out_p = Path(out_path)
        out_p.parent.mkdir(parents=True, exist_ok=True)
        with out_p.open("w", encoding="utf-8") as f:
            json.dump(result_artifact, f, indent=2, ensure_ascii=False)
        logger.info(
            "Fitted reference quantiles saved to %s (n_nv=%d, total_train=%d)",
            out_p,
            total_nv_train_trips,
            total_train_trips,
        )

    return result_artifact


def main() -> None:
    parser = argparse.ArgumentParser(description="Fit reference quantiles from train split of trips corpus")
    parser.add_argument(
        "--in",
        dest="in_path",
        default="/home/dat/releases_v2_1/trips.jsonl",
        type=Path,
        help="Input trips.jsonl corpus path",
    )
    parser.add_argument(
        "--out",
        dest="out_path",
        default="src/services/data/jev_reference_quantiles.json",
        type=Path,
        help="Output JSON artifact path",
    )
    parser.add_argument(
        "--split",
        default="train",
        help="Target split to fit on (default: train)",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=8,
        help="Worker concurrency for streaming (default: 8)",
    )

    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    res = fit_reference_distributions(
        in_path=args.in_path,
        out_path=args.out_path,
        split=args.split,
        max_workers=args.workers,
    )
    print(f"Fit complete. Output saved to {args.out_path} with {res['n']} no_violation trips.")


if __name__ == "__main__":
    main()

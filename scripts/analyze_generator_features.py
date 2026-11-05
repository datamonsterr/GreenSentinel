#!/usr/bin/env python3
"""Measure FeatureWindow outputs per scenario, for the DA-06 generator or the seed.

``--source module`` (default) generates N trips per config scenario with
``scripts/telemetry_generation.py`` and reproduces the pass-rate tables in
docs/data/TELEMETRY_DISTRIBUTION.md (section 4.3). ``--source seed`` measures the seed
dataset, whose telemetry comes from the #82 road dataset. Nothing is written.

Usage:
    python scripts/analyze_generator_features.py [--noise happy|stress] [--seed N] [--trips N]
    python scripts/analyze_generator_features.py --source seed
"""

from __future__ import annotations

import argparse
import statistics
import sys
from collections import defaultdict
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import telemetry_generation as tg  # noqa: E402

from src.services.feature_engineering import FeatureWindow, compute_feature_window  # noqa: E402

PICKUP = (105.8542, 21.0285)  # (lon, lat)
T0 = datetime(2026, 9, 27, 8, 0, tzinfo=UTC)


def _wkt_point(value: Any) -> list[float] | None:
    """Parse ``POINT(lon lat)`` strings."""
    if isinstance(value, str) and value.startswith("POINT(") and value.endswith(")"):
        lon, lat = value[6:-1].split()
        return [float(lon), float(lat)]
    return None


def _median(windows: list[FeatureWindow], getter: Callable[[FeatureWindow], float | None]) -> str:
    values = [v for w in windows if (v := getter(w)) is not None]
    return f"{statistics.median(values):.2f}" if values else "null"


def _p95(windows: list[FeatureWindow], getter: Callable[[FeatureWindow], float | None]) -> str:
    values = sorted(v for w in windows if (v := getter(w)) is not None)
    return f"{values[min(len(values) - 1, round(0.95 * (len(values) - 1)))]:.0f}" if values else "null"


def _share(windows: list[FeatureWindow], predicate: Callable[[FeatureWindow], bool]) -> str:
    return f"{sum(predicate(w) for w in windows) / len(windows):.0%}"


def _module_windows(noise: str, seed: int | None, trips: int) -> dict[str, list[FeatureWindow]]:
    config = tg.load_config()
    return {
        scenario: [
            compute_feature_window(
                tg.generate_trip(config, scenario, PICKUP, T0, tg.make_rng(config, seed, stream=i), noise=noise).points,
                PICKUP,
            )
            for i in range(trips)
        ]
        for scenario in sorted(config["scenarios"])
    }


def _seed_windows() -> dict[str, list[FeatureWindow]]:
    import generate_synthetic_data

    dataset = generate_synthetic_data.generate_synthetic_dataset()
    trips = {t["id"]: t for t in dataset["trips"]}
    assignments = {a["id"]: a for a in dataset["trip_assignments"]}
    labels = {label["assignment_id"]: label for label in dataset["simulation_labels"]}
    scenarios = {run["id"]: run["scenario"] for run in dataset.get("simulation_runs", [])}

    points: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for point in dataset["telemetry_points"]:
        flat = {k: v for k, v in point.items() if k != "position"}
        coord = _wkt_point(point.get("position"))
        if coord:
            flat["longitude"], flat["latitude"] = coord
        points[point["assignment_id"]].append(flat)

    by_scenario: dict[str, list[FeatureWindow]] = defaultdict(list)
    for assignment_id, trip_points in points.items():
        scenario = scenarios.get(labels.get(assignment_id, {}).get("simulation_run_id"), "unknown")
        pickup = _wkt_point(trips[assignments[assignment_id]["trip_id"]]["pickup"])
        by_scenario[scenario].append(compute_feature_window(trip_points, pickup))
    return by_scenario


def main() -> None:
    parser = argparse.ArgumentParser(description="Measure FeatureWindow per scenario")
    parser.add_argument("--source", choices=("module", "seed"), default="module")
    parser.add_argument("--noise", choices=tg.NOISE_MODES, default="happy", help="module source only")
    parser.add_argument("--seed", type=int, default=None, help="module source only")
    parser.add_argument("--trips", type=int, default=400, help="trips per scenario, module source only")
    args = parser.parse_args()

    if args.source == "module":
        by_scenario = _module_windows(args.noise, args.seed, args.trips)
        print(f"source=module noise={args.noise} seed={args.seed if args.seed is not None else 'config'}")
    else:
        by_scenario = _seed_windows()
        print("source=seed (telemetry from the #82 road dataset)")
    print(
        "| Scenario | n | approach SSD s (p50 / p95 / max) | SSD >= 180 s | DAVI | coverage | max gap s "
        "| mean speed m/s | mock ratio | jitter ratio |"
    )
    print("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for scenario, windows in sorted(by_scenario.items()):
        ssd_values = [w.approach_stationary_duration_s for w in windows if w.approach_stationary_duration_s is not None]
        ssd_max = f"{max(ssd_values):.0f}" if ssd_values else "null"
        print(
            f"| `{scenario}` | {len(windows)} "
            f"| {_median(windows, lambda w: w.approach_stationary_duration_s)} / "
            f"{_p95(windows, lambda w: w.approach_stationary_duration_s)} / {ssd_max} "
            f"| {_share(windows, lambda w: (w.approach_stationary_duration_s or 0) >= 180)} "
            f"| {_median(windows, lambda w: w.davi)} "
            f"| {_median(windows, lambda w: w.telemetry_coverage)} "
            f"| {_median(windows, lambda w: w.max_gap_s)} "
            f"| {_median(windows, lambda w: w.speed.mean_mps)} "
            f"| {_median(windows, lambda w: w.gps_quality.mock_ratio)} "
            f"| {_median(windows, lambda w: w.gps_quality.jitter_ratio)} |"
        )


if __name__ == "__main__":
    main()

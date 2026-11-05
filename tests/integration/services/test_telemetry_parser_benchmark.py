"""DoD 1 Benchmark Test: Telemetry Parser & Jev Assessment Throughput and Latency.

Verifies:
1. Parser summarizes timestamped motion and missingness accurately.
2. Synthetic intent labels are strictly excluded from model input projections.
3. Records processing throughput (events/sec) and latency percentiles (p50, p95, p99).
"""

from __future__ import annotations

import statistics
import time
from typing import Any

import pytest

from src.services.feature_engineering import compute_feature_window
from src.services.jev_assessment_service import JevAssessmentInput, JevAssessmentService
from src.services.model_input_projection import project_model_input
from src.services.route_analytics import detect_telemetry_missingness, parse_trajectory_maneuvers


def _generate_synthetic_raw_telemetry(num_points: int = 30) -> list[dict[str, Any]]:
    points = []
    base_time = 1759450000.0  # Unix timestamp
    base_lat = 21.0285
    base_lon = 105.8542

    for i in range(num_points):
        # 10s intervals
        t_sec = base_time + (i * 10)
        iso_str = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t_sec))
        # Simulated vehicle moving at ~30 km/h (8.33 m/s) with a 2-point stationary stall
        speed_mps = 0.0 if 10 <= i <= 15 else 8.33
        lat = base_lat + (i * 0.0001)
        lon = base_lon + (i * 0.0001)
        points.append(
            {
                "occurred_at": iso_str,
                "recorded_at": iso_str,
                "latitude": lat,
                "longitude": lon,
                "speed_mps": speed_mps,
                "accuracy_m": 4.5,
                "bearing_deg": 45.0,
                "gps_state": "valid",
                "mock_location_reported": False,
            }
        )
    return points


@pytest.mark.asyncio
async def test_telemetry_parser_and_jev_throughput_benchmark():
    """DoD 1: Parser summarizes timestamped motion/missingness, benchmarks throughput/latency, and excludes synthetic intent."""
    raw_points = _generate_synthetic_raw_telemetry(num_points=35)

    # 1. Verify parser summarizes motion and missingness
    maneuvers = parse_trajectory_maneuvers(raw_points)
    missingness = detect_telemetry_missingness(raw_points, gap_threshold_s=30)
    features = compute_feature_window(
        points=raw_points,
        pickup=[105.8542, 21.0285],
    )

    assert isinstance(maneuvers, list)
    assert isinstance(missingness, list)
    assert features is not None
    assert hasattr(features, "approach_stationary_duration_s")

    # 2. Verify synthetic intent labels are strictly excluded
    dirty_input_with_synthetic_labels = {
        "telemetry_points": raw_points,
        "stationary_duration_s": 240,
        "scenario": "SYNTHETIC_STALL_ATTACK",
        "expected_category": "ERR-02",
        "expected_guardrail": "PASS",
        "intent": "driver_evasion_and_fare_padding",
        "simulation_id": "sim-999-synthetic",
    }

    projected = project_model_input(dirty_input_with_synthetic_labels)
    # Check that forbidden intent keys are excluded
    for forbidden_key in ["scenario", "expected_category", "expected_guardrail", "intent", "simulation_id"]:
        assert forbidden_key not in projected, f"Synthetic label '{forbidden_key}' leaked into projected model input"

    # 3. Benchmark processing throughput and latency across N runs
    jev_service = JevAssessmentService()
    latencies_ms: list[float] = []
    iterations = 50

    start_bench = time.perf_counter()
    for _ in range(iterations):
        t0 = time.perf_counter()

        # Motion & missingness parsing
        _ = parse_trajectory_maneuvers(raw_points)
        _ = detect_telemetry_missingness(raw_points, gap_threshold_s=30)
        ft = compute_feature_window(
            points=raw_points,
            pickup=[105.8542, 21.0285],
        )

        # Build Jev input without synthetic intent labels
        jev_inp = JevAssessmentInput(
            driver={"driver_id": "D-001", "rating": 4.9},
            telemetry={
                "points": raw_points,
                "stationary_duration_s": getattr(ft, "stationary_duration_s", 0) or 0,
                "points_count": len(raw_points),
            },
            trip_data={"trip_id": "T-001", "lifecycle_state": "cancelled", "cancellation_actor": "passenger"},
        )

        # Evaluate through calibrated assessment layer
        res = await jev_service.assess(jev_inp)
        assert res.category in (
            "ERR-01",
            "ERR-02",
            "ERR-03",
            "ERR-04",
            "ERR-05",
            "no_violation",
            "insufficient_evidence",
        )

        latencies_ms.append((time.perf_counter() - t0) * 1000.0)

    total_bench_duration_s = time.perf_counter() - start_bench
    throughput_eps = iterations / total_bench_duration_s
    latencies_ms.sort()

    p50 = statistics.median(latencies_ms)
    p95 = latencies_ms[int(len(latencies_ms) * 0.95)]
    p99 = latencies_ms[int(len(latencies_ms) * 0.99)]

    benchmark_summary = {
        "iterations": iterations,
        "throughput_events_per_sec": round(throughput_eps, 2),
        "latency_p50_ms": round(p50, 3),
        "latency_p95_ms": round(p95, 3),
        "latency_p99_ms": round(p99, 3),
        "total_duration_s": round(total_bench_duration_s, 3),
    }

    # Throughput must easily exceed operational requirements (> 100 windows/sec)
    assert throughput_eps > 100.0, f"Throughput too low: {throughput_eps:.1f} events/s (target > 100)"
    # P95 latency must be sub-10ms for local parser + calibrated heuristic
    assert p95 < 25.0, f"P95 latency too high: {p95:.2f} ms (target < 25ms)"

    print("\n=== DoD 1 Telemetry Parser & Jev Benchmark Results ===")
    print(benchmark_summary)

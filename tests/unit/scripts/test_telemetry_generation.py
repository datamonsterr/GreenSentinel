"""Tests for the calibrated telemetry generator (S1-DA-06).

Expectations come from the ``expect`` blocks in config/telemetry_distribution.yaml and are
checked with FeatureWindow (PR #43) and the technical guardrail. Streams are fixed
(seed from the config, stream = trip index), so pass rates are deterministic.
"""

from __future__ import annotations

import statistics
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import pytest

from scripts import telemetry_generation as tg
from scripts.simulate_trip_stream import build_trip_lifecycle_frames
from src.models.schemas import TelemetryPayload
from src.services.feature_engineering import FeatureWindow, compute_feature_window
from src.services.guardrails import GuardrailResult, evaluate_telemetry_window, should_short_circuit

PICKUP = (105.8542, 21.0285)  # (lon, lat)
T0 = datetime(2026, 9, 27, 8, 0, tzinfo=UTC)
N_PER_SCENARIO = 400  # rates are ~96-100%; 100 trips is too few to estimate them against 95%
MIN_PASS_RATE = 0.95

CONFIG = tg.load_config()


def _trips(scenario: str, noise: str = "happy", n: int = N_PER_SCENARIO, seed: int | None = None) -> list[Any]:
    return [
        tg.generate_trip(CONFIG, scenario, PICKUP, T0, tg.make_rng(CONFIG, seed, stream=i), noise=noise)
        for i in range(n)
    ]


def _evaluate(trip: Any) -> tuple[FeatureWindow, GuardrailResult]:
    return compute_feature_window(trip.points, PICKUP), evaluate_telemetry_window(trip.points, trip.incidents)


def _ssd(w: FeatureWindow) -> float:
    return w.approach_stationary_duration_s if w.approach_stationary_duration_s is not None else -1.0


EXPECTATIONS: dict[str, Callable[[FeatureWindow, GuardrailResult], bool]] = {
    "driver_stall_cancel": lambda w, g: _ssd(w) >= 185 and not w.arrived_at_pickup,
    "traffic_gridlock": lambda w, g: (w.davi if w.davi is not None else -1) > 0.5,
    "technical_dropout": lambda w, g: (w.max_gap_s or 0) > 30 and g.blocked,
    "gps_jitter": lambda w, g: 0.3 <= (w.gps_quality.jitter_ratio or 0) <= 0.6 and not g.blocked,
    "gps_spoofing": lambda w, g: (w.gps_quality.mock_ratio or 0) >= 0.8 and not should_short_circuit(g),
    "normal_trip": lambda w, g: (w.davi if w.davi is not None else -1) > 0.5 and 0 <= _ssd(w) < 60,
    "route_deviation": lambda w, g: (w.davi if w.davi is not None else 1) < 0.0 and not g.blocked,
}


# ---------------------------------------------------------------------------
# Reproducibility and contract
# ---------------------------------------------------------------------------
def test_same_seed_is_identical_and_other_seed_differs():
    first = [t.points for t in _trips("driver_stall_cancel", n=5)]
    again = [t.points for t in _trips("driver_stall_cancel", n=5)]
    other = [t.points for t in _trips("driver_stall_cancel", n=5, seed=CONFIG["seed"] + 1)]
    assert first == again
    assert first != other


@pytest.mark.parametrize("scenario", sorted(CONFIG["scenarios"]))
@pytest.mark.parametrize("noise", tg.NOISE_MODES)
def test_points_validate_and_are_ordered(scenario, noise):
    for trip in _trips(scenario, noise=noise, n=10):
        assert trip.points
        times = [datetime.fromisoformat(p["occurred_at"]) for p in trip.points]
        assert all(b > a for a, b in zip(times, times[1:], strict=False))
        assert [p["sequence"] for p in trip.points] == list(range(len(trip.points)))
        for point in trip.points:
            TelemetryPayload(**tg.to_payload(point))
            assert point["distance_to_pickup_m"] is None
            assert point["davi_score"] is None
            assert point["data_gap_s"] is None


def test_aliases_keep_consumer_scenario_names():
    assert tg.canonical_scenario("intentional_dic", CONFIG) == "driver_stall_cancel"
    assert tg.canonical_scenario("fake_gps", CONFIG) == "gps_spoofing"
    assert tg.canonical_scenario("traffic_gridlock", CONFIG) == "traffic_gridlock"
    assert tg.canonical_scenario("unknown_scenario", CONFIG) == "normal_trip"


# ---------------------------------------------------------------------------
# Happy mode: every scenario lands on the intended side of FEATURE_PARAMS
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("scenario", sorted(EXPECTATIONS))
def test_happy_mode_meets_scenario_expectations(scenario):
    trips = _trips(scenario)
    passed = sum(EXPECTATIONS[scenario](*_evaluate(t)) for t in trips)
    assert passed / len(trips) >= MIN_PASS_RATE, f"{scenario}: {passed}/{len(trips)}"


# ---------------------------------------------------------------------------
# Large-sample statistics against the config
# ---------------------------------------------------------------------------
def test_accuracy_median_and_cadence_share():
    points = [p for t in _trips("normal_trip", n=200) for p in t.points]
    accuracies = [p["accuracy_m"] for p in points if p["accuracy_m"] is not None and p["gps_state"] != "jitter"]
    # lognormal(mu=2.66) median is exp(2.66) = 14.3 m
    assert statistics.median(accuracies) == pytest.approx(14.3, rel=0.15)

    cadence = CONFIG["sampling"]["profiles"][CONFIG["sampling"]["default_profile"]]["cadence_s"]
    intervals = []
    for trip in _trips("normal_trip", n=200):
        times = [datetime.fromisoformat(p["occurred_at"]) for p in trip.points]
        intervals += [(b - a).total_seconds() for a, b in zip(times, times[1:], strict=False)]
    assert sum(abs(i - cadence) < 1e-6 for i in intervals) / len(intervals) >= 0.90


# ---------------------------------------------------------------------------
# Stress mode: runs and reports, no threshold assertions
# ---------------------------------------------------------------------------
def test_stress_mode_runs_and_reports(capsys):
    rows = []
    for scenario, check in sorted(EXPECTATIONS.items()):
        trips = _trips(scenario, noise="stress", n=40)
        rows.append((scenario, sum(check(*_evaluate(t)) for t in trips) / len(trips)))
    with capsys.disabled():
        print("\nstress-mode expectation pass rates (report only):")
        for scenario, rate in rows:
            print(f"  {scenario:20s} {rate:.0%}")
    assert len(rows) == len(EXPECTATIONS)


# ---------------------------------------------------------------------------
# Live simulator frames
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("scenario", ["driver_stall_cancel", "gps_spoofing", "normal_trip", "phantom_booking"])
def test_simulator_frames_have_timestamps_and_valid_payloads(scenario):
    frames = build_trip_lifecycle_frames("trip-1", "asgn-1", "drv-1", scenario, (21.0285, 105.8542), (21.035, 105.86))
    assert len(frames) == 3
    for frame in frames:
        assert frame["points"]
        for point in frame["points"]:
            assert point["occurred_at"] and isinstance(point["sequence"], int)
            TelemetryPayload(**tg.to_payload(point))


def test_simulator_stall_frame_declares_ground_truth_not_a_constant():
    durations = {
        build_trip_lifecycle_frames(f"trip-{i}", "a", "d", "intentional_dic", (21.0285, 105.8542), (21.03, 105.86))[2][
            "stationary_duration_s"
        ]
        for i in range(5)
    }
    assert len(durations) > 1  # varies with the simulated stall, no hard-coded 210
    assert all(230 <= d <= 420 for d in durations)


# ---------------------------------------------------------------------------
# G1/G2 fraud variants (Issues #275/#276, benchmark overlay config only)
# ---------------------------------------------------------------------------
def _bench_config():
    from pathlib import Path as _Path

    return tg.load_config(_Path(__file__).resolve().parents[3] / "config" / "benchmark_distribution.yaml")


def _bench_trips(scenario: str, n: int = 200, seed: int = 7) -> list[Any]:
    cfg = _bench_config()
    return [tg.generate_trip(cfg, scenario, PICKUP, T0, tg.make_rng(cfg, seed, stream=i)) for i in range(n)]


def test_slow_crawl_fraud_moves_toward_pickup_below_stall_threshold():
    trips = _bench_trips("slow_crawl_fraud")
    davi_ok = sum((compute_feature_window(t.points, PICKUP).davi or -1) > 0.3 for t in trips)
    ssd_ok = sum((_ssd(compute_feature_window(t.points, PICKUP))) < 180 for t in trips)
    assert davi_ok / len(trips) >= 0.90, f"davi>0.3: {davi_ok}/{len(trips)}"
    assert ssd_ok / len(trips) >= 0.95, f"ssd<180: {ssd_ok}/{len(trips)}"


def test_loop_deviation_stays_negative_davi():
    trips = _bench_trips("loop_deviation")
    neg = sum((compute_feature_window(t.points, PICKUP).davi or 1) < 0.0 for t in trips)
    assert neg / len(trips) >= 0.90, f"davi<0: {neg}/{len(trips)}"


def test_new_scenarios_validate_and_are_ordered():
    for scenario in ("slow_crawl_fraud", "loop_deviation"):
        for trip in _bench_trips(scenario, n=10):
            assert trip.points
            times = [datetime.fromisoformat(p["occurred_at"]) for p in trip.points]
            assert all(b > a for a, b in zip(times, times[1:], strict=False))
            assert [p["sequence"] for p in trip.points] == list(range(len(trip.points)))
            for point in trip.points:
                TelemetryPayload(**tg.to_payload(point))

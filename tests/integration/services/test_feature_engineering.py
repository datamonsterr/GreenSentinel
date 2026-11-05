"""Tests for telemetry feature engineering (S1-DA-02).

Expected values are hand-calculated from the synthetic geometry: points are placed N metres
north/east of the pickup using 111,320 m per degree, so haversine distances differ from the
nominal metres by ~0.1%; tolerances cover that.
"""

from __future__ import annotations

import asyncio
import json
import math
import random
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest

from src.services import telemetry_queue_worker as worker
from src.services.feature_engineering import FEATURE_PARAMS, FEATURE_VERSION, compute_feature_window
from tests.support.repo import REPO_ROOT

PICKUP = (105.85, 21.03)  # (lon, lat)
_M_PER_DEG = 111_320.0
_T0 = datetime(2026, 9, 27, 8, 0, tzinfo=UTC)

FIXTURES = REPO_ROOT / "tests" / "fixtures" / "features"


def pt(north_m: float, east_m: float = 0.0, t: float | None = None, **overrides: Any) -> dict[str, Any]:
    """Flat telemetry frame ``north_m``/``east_m`` metres from the pickup, at ``t`` seconds."""
    point: dict[str, Any] = {
        "latitude": PICKUP[1] + north_m / _M_PER_DEG,
        "longitude": PICKUP[0] + east_m / (_M_PER_DEG * math.cos(math.radians(PICKUP[1]))),
        "app_state": "foreground",
        "network_state": "online",
        "gps_state": "valid",
    }
    if t is not None:
        point["occurred_at"] = (_T0 + timedelta(seconds=t)).isoformat()
    point.update(overrides)
    return point


# ---------------------------------------------------------------------------
# Required scenarios
# ---------------------------------------------------------------------------
def test_stationary_200s_next_to_pickup():
    w = compute_feature_window([pt(40, t=t) for t in range(0, 201, 10)], PICKUP)
    assert w.approach_stationary_duration_s == 200.0
    assert w.stationary_duration_total_s == 200.0
    assert w.stationary_distance_to_pickup_m == pytest.approx(40, abs=0.5)
    assert w.davi is None  # DATA_MODEL: DAVI is null while stationary
    assert "davi" in w.missing_features
    assert w.arrived_at_pickup is False
    assert w.speed.mean_mps == pytest.approx(0.0, abs=0.01)


def test_waiting_at_pickup_is_not_approach_ssd():
    # Already at the pickup and waiting 200 s: legitimate waiting, not an ERR-02 stall.
    w = compute_feature_window([pt(10, t=t) for t in range(0, 201, 10)], PICKUP)
    assert w.arrived_at_pickup is True
    assert w.arrival_index == 0
    assert w.approach_stationary_duration_s is None  # approach window is a single point
    assert "approach_stationary_duration_s" in w.missing_features
    assert w.stationary_duration_total_s == 200.0


def test_drive_in_then_wait_at_pickup():
    drive_in = [pt(300 - 50 * i, t=10 * i) for i in range(6)]  # reaches 50 m at t=50
    wait = [pt(10, t=60 + 10 * i) for i in range(21)]  # 200 s at the pickup
    w = compute_feature_window(drive_in + wait, PICKUP)
    assert w.arrival_index == 6
    assert w.approach_stationary_duration_s == 0.0  # measured moving before pickup
    assert w.stationary_duration_total_s == 200.0


def test_stop_on_trip_after_pickup_does_not_touch_approach_ssd():
    approach = [pt(300 - 100 * i, t=10 * i) for i in range(4)]  # arrives at t=30
    moving = [pt(-100 * i, t=30 + 10 * i) for i in range(1, 4)]  # 300 m south by t=60
    red_light = [pt(-300, t=60 + 10 * i) for i in range(1, 10)]  # 90 s stop
    w = compute_feature_window(approach + moving + red_light, PICKUP)
    assert w.approach_stationary_duration_s == 0.0
    assert w.stationary_duration_total_s == 90.0


def test_driving_straight_to_pickup_davi_plus_one():
    w = compute_feature_window([pt(1000 - 10 * t, t=t) for t in range(0, 61, 10)], PICKUP)
    assert w.davi == pytest.approx(1.0, abs=1e-3)
    assert w.davi_segment_count == 6
    assert w.distance_to_pickup_m.first_m == pytest.approx(1000, rel=2e-3)
    assert w.distance_to_pickup_m.last_m == pytest.approx(400, rel=2e-3)
    assert w.speed.mean_mps == pytest.approx(10, rel=2e-3)
    assert w.approach_stationary_duration_s == 0.0  # measured moving, not unknown


def test_driving_away_from_pickup_davi_minus_one():
    w = compute_feature_window([pt(300 + 10 * t, t=t) for t in range(0, 61, 10)], PICKUP)
    assert w.davi == pytest.approx(-1.0, abs=1e-3)
    assert w.distance_to_pickup_m.min_m == pytest.approx(300, rel=2e-3)


def test_perpendicular_motion_davi_near_zero():
    # 500 m north of pickup, driving east 60 m: nearly perpendicular to the pickup vector.
    w = compute_feature_window([pt(500, 10 * t, t=t) for t in range(0, 7)], PICKUP)
    assert abs(w.davi) < 0.15


def test_gap_60s_breaks_chains_and_lowers_coverage():
    points = [pt(500, t=0), pt(500, t=10), pt(500, t=70), pt(500, t=80)]
    w = compute_feature_window(points, PICKUP)
    assert w.max_gap_s == 60.0
    # Only the two 10 s intervals are <= 30 s: 20 / 80.
    assert w.telemetry_coverage == pytest.approx(0.25)
    assert w.approach_stationary_duration_s == 10.0  # the 60 s gap splits two 10 s chains


def test_reported_speed_zero_but_coordinates_move():
    w = compute_feature_window([pt(1000 - 10 * t, t=t, speed_mps=0.0) for t in range(0, 61, 10)], PICKUP)
    assert w.speed.mean_mps == pytest.approx(10, rel=2e-3)
    assert w.speed.reported_mean_mps == 0.0
    assert w.approach_stationary_duration_s == 0.0


def test_no_valid_points_gives_none_not_zero():
    points = [
        pt(100, t=0, network_state="offline"),  # guardrail-blocked
        {"latitude": math.nan, "longitude": 105.85, "occurred_at": _T0.isoformat(), **_healthy()},
        {"latitude": True, "longitude": 105.85, **_healthy()},
    ]
    w = compute_feature_window(points, PICKUP)
    assert w.geometric_point_count == 0
    assert w.approach_stationary_duration_s is None
    assert w.stationary_duration_total_s is None
    assert w.davi is None
    assert w.distance_to_pickup_m.min_m is None
    assert w.speed.mean_mps is None
    for name in ("approach_stationary_duration_s", "stationary_duration_total_s", "davi", "speed"):
        assert name in w.missing_features
    # Invalid points still count toward coverage: two timestamps at the same instant -> no span.
    assert w.telemetry_coverage is None
    assert "insufficient_samples" in w.quality_flags


def test_empty_window():
    w = compute_feature_window([], PICKUP)
    assert w.point_count == 0
    assert w.telemetry_coverage is None and w.max_gap_s is None
    assert w.gps_quality.mock_ratio is None
    assert "insufficient_samples" in w.quality_flags


# ---------------------------------------------------------------------------
# Additional scenarios (review C)
# ---------------------------------------------------------------------------
def test_full_trip_davi_uses_approach_window_only():
    approach = [pt(600 - 100 * i, t=10 * i) for i in range(7)]
    on_trip = [pt(-100 * i, t=60 + 10 * i) for i in range(1, 11)]
    w = compute_feature_window(approach + on_trip, PICKUP)
    assert w.arrived_at_pickup is True
    assert w.arrival_index == 6
    assert w.davi == pytest.approx(1.0, abs=1e-3)
    assert w.distance_to_pickup_m.last_m == pytest.approx(0.0, abs=0.5)


def test_lifecycle_state_ends_approach_window():
    approach = [pt(600 - 100 * i, t=10 * i, lifecycle_state="coming") for i in range(3)]
    # Picked up 400 m away (e.g. passenger walked over), then driven away from the pickup pin.
    on_trip = [pt(400 + 100 * i, t=30 + 10 * i, lifecycle_state="picked_up") for i in range(5)]
    w = compute_feature_window(approach + on_trip, PICKUP)
    assert w.arrival_index == 3
    assert w.davi == pytest.approx(1.0, abs=1e-3)


def test_1s_sampling_small_steps_still_yields_davi():
    w = compute_feature_window([pt(400 - 8 * t, t=t) for t in range(40)], PICKUP)
    assert w.davi is not None
    assert w.davi == pytest.approx(1.0, abs=1e-3)
    assert w.speed.mean_mps == pytest.approx(8, rel=5e-3)


def test_stationary_with_jitter_does_not_inflate_speed():
    rng = random.Random(7)
    points = [pt(60 + rng.uniform(-5, 5), rng.uniform(-5, 5), t=t) for t in range(0, 201, 10)]
    w = compute_feature_window(points, PICKUP)
    assert w.approach_stationary_duration_s == pytest.approx(200, abs=10)
    assert w.speed.p95_mps < 0.5
    assert w.davi is None


def test_no_timestamps_order_features_only():
    w = compute_feature_window([pt(1000 - 100 * i) for i in range(6)], PICKUP)
    assert w.davi == pytest.approx(1.0, abs=1e-3)
    assert w.distance_to_pickup_m.first_m == pytest.approx(1000, rel=2e-3)
    assert w.approach_stationary_duration_s is None
    assert w.speed.mean_mps is None
    assert w.telemetry_coverage is None
    assert {"approach_stationary_duration_s", "speed", "telemetry_coverage", "max_gap_s"} <= set(w.missing_features)


def test_sequence_orders_points_without_timestamps():
    points = [pt(1000 - 100 * i, sequence=i) for i in range(6)]
    w = compute_feature_window(list(reversed(points)), PICKUP)
    assert w.davi == pytest.approx(1.0, abs=1e-3)


def test_slow_crawl_is_not_stationary():
    # 0.4 m/s for 200 s covers 80 m: well beyond the 15 m anchor radius.
    w = compute_feature_window([pt(200 - 0.4 * t, t=t) for t in range(0, 201, 10)], PICKUP)
    assert w.approach_stationary_duration_s < 60
    assert w.speed.mean_mps == pytest.approx(0.4, rel=5e-3)


def test_anchor_radius_adapts_to_accuracy():
    # 25 m drift at accuracy 40 m stays inside R = 40; at unknown accuracy R = 15 breaks it.
    drift = [pt(300 + 2.5 * i, t=10 * i) for i in range(11)]
    loose = compute_feature_window([{**p, "accuracy_m": 40.0} for p in drift], PICKUP)
    strict = compute_feature_window(drift, PICKUP)
    assert loose.approach_stationary_duration_s == 100.0
    assert strict.approach_stationary_duration_s < 100.0


def test_all_mock_points_geometry_null():
    w = compute_feature_window([pt(500 - 10 * t, t=t, mock_location_reported=True) for t in range(0, 61, 10)], PICKUP)
    assert w.geometric_point_count == 0
    assert w.gps_quality.mock_ratio == 1.0
    assert w.davi is None and w.approach_stationary_duration_s is None
    assert w.distance_to_pickup_m.first_m is None
    assert {"davi", "approach_stationary_duration_s", "distance_to_pickup_m", "speed"} <= set(w.missing_features)
    assert w.telemetry_coverage == 1.0  # mock points still count as observations


def test_implausible_speed_is_counted_not_dropped():
    w = compute_feature_window([pt(2000 - 600 * i, t=10 * i) for i in range(3)], PICKUP)
    assert w.speed.max_mps == pytest.approx(60, rel=2e-3)
    assert w.speed.implausible_speed_segments == 2


def test_accepts_all_three_position_shapes():
    lat, lon = PICKUP[1] + 500 / _M_PER_DEG, PICKUP[0]
    shapes = [
        {"latitude": lat, "longitude": lon},
        {"position": {"latitude": lat, "longitude": lon}},
        {"position": {"type": "Point", "coordinates": [lon, lat]}},
    ]
    for shape in shapes:
        w = compute_feature_window([{**shape, **_healthy()}], PICKUP)
        assert w.distance_to_pickup_m.first_m == pytest.approx(500, rel=2e-3)


def test_params_and_version_recorded():
    w = compute_feature_window([pt(10, t=0)], PICKUP)
    dumped = w.model_dump(mode="json")
    assert dumped["feature_version"] == FEATURE_VERSION == "v1.0.0"
    assert dumped["params"] == FEATURE_PARAMS


def test_no_pickup_means_no_pickup_features():
    w = compute_feature_window([pt(1000 - 10 * t, t=t) for t in range(0, 61, 10)], None)
    assert w.davi is None and w.distance_to_pickup_m.first_m is None
    # No pickup: the approach window is the whole window.
    assert w.approach_stationary_duration_s == w.stationary_duration_total_s == 0.0
    assert w.speed.mean_mps is not None


# ---------------------------------------------------------------------------
# Shared fixtures for team cross-checks
# ---------------------------------------------------------------------------
def _dig(obj: dict[str, Any], dotted: str) -> Any:
    for key in dotted.split("."):
        obj = obj[key]
    return obj


@pytest.mark.parametrize("path", sorted(FIXTURES.glob("*.json")), ids=lambda p: p.stem)
def test_fixture_expected_values(path):
    case = json.loads(path.read_text(encoding="utf-8"))
    dumped = compute_feature_window(case["input"]["points"], case["input"]["pickup"]).model_dump(mode="json")
    for key, expected in case["expected"].items():
        actual = _dig(dumped, key)
        tolerance = case.get("tolerance", {}).get(key)
        if tolerance is not None:
            assert actual == pytest.approx(expected, abs=tolerance), key
        else:
            assert actual == expected, key


# ---------------------------------------------------------------------------
# Worker wiring: app.feature_sets receives computed values
# ---------------------------------------------------------------------------
class _Cursor:
    def __init__(self, log: list[tuple[str, Any]]) -> None:
        self.log = log

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql: str, params: Any = None) -> None:
        self.log.append((sql, params))

    def fetchone(self):
        # Mirror INSERT ... RETURNING event_id for a fresh ingest row; everything else is absent.
        sql, params = self.log[-1] if self.log else ("", None)
        if "INSERT INTO app.ingest_events" in sql and "RETURNING event_id" in sql:
            return {"event_id": params[0]}
        return None


class _Conn:
    def __init__(self) -> None:
        self.log: list[tuple[str, Any]] = []

    def cursor(self):
        return _Cursor(self.log)

    def commit(self) -> None: ...

    def rollback(self) -> None: ...

    def close(self) -> None: ...


class _DbService:
    def __init__(self, conn: _Conn) -> None:
        self.conn = conn
        self.settings = SimpleNamespace(app_env="test", openrouter_api_key=None)
        self._telemetry_points: list[dict[str, Any]] = []
        self._trips: dict[str, Any] = {}
        self._assignments: dict[str, Any] = {}
        self._cases: dict[str, Any] = {}
        self._model_assessments: dict[str, Any] = {}
        self._analysts: dict[str, Any] = {}

    def is_driver_suspended(self, driver_id: str) -> bool:
        return False

    def _get_db_connection(self) -> _Conn:
        return self.conn


def _feature_insert(conn: _Conn) -> tuple[Any, ...]:
    return next(params for sql, params in conn.log if "INSERT INTO app.feature_sets" in sql)


def test_worker_persists_computed_features(monkeypatch):
    monkeypatch.delenv("TELEMETRY_GUARDRAIL_ENABLED", raising=False)
    conn = _Conn()
    event = {
        "scenario": "driver_stall_cancel",
        "lifecycle_state": "cancelled",
        "stationary_duration_s": 999,  # producer claim; must not reach the column
        "pickup": list(PICKUP),
        "dropoff": [105.86, 21.04],
        "points": [pt(40, t=t, accuracy_m=5.0) for t in range(0, 201, 10)],
    }
    asyncio.run(worker.process_telemetry_event(event, case_service=_DbService(conn)))

    (_, _, version, _, _, coverage, max_gap, davi, ssd, quality_flags, features, _) = _feature_insert(conn)
    assert version == "v1.0.0"
    assert (coverage, max_gap, davi, ssd) == (1.0, 10, None, 200)
    assert json.loads(quality_flags) == []
    features = json.loads(features)
    assert features["declared_stationary_duration_s"] == 999
    assert features["approach_stationary_duration_s"] == 200.0
    assert features["params"] == FEATURE_PARAMS
    assert features["guardrail"]["blocked"] is False


def test_worker_missing_timestamps_flag_insufficient_samples(monkeypatch):
    monkeypatch.delenv("TELEMETRY_GUARDRAIL_ENABLED", raising=False)
    conn = _Conn()
    event = {
        "scenario": "driver_stall_cancel",
        "lifecycle_state": "cancelled",
        "stationary_duration_s": 210,
        "pickup": list(PICKUP),
        "dropoff": [105.86, 21.04],
        "points": [pt(40, speed_mps=0.0)],
    }
    asyncio.run(worker.process_telemetry_event(event, case_service=_DbService(conn)))

    (_, _, _, _, _, coverage, max_gap, _, ssd, quality_flags, features, _) = _feature_insert(conn)
    assert (coverage, max_gap, ssd) == (0.0, 0, None)  # NOT NULL placeholders; SSD stays null
    assert "insufficient_samples" in json.loads(quality_flags)
    features = json.loads(features)
    assert features["telemetry_coverage"] is None
    assert {"telemetry_coverage", "max_gap_s", "approach_stationary_duration_s"} <= set(features["missing_features"])


def test_worker_waiting_at_pickup_leaves_ssd_column_null(monkeypatch):
    monkeypatch.delenv("TELEMETRY_GUARDRAIL_ENABLED", raising=False)
    conn = _Conn()
    event = {
        "scenario": "normal_trip",
        "lifecycle_state": "cancelled",
        "cancellation_actor": "driver",  # opens a case, so the feature set is persisted
        "pickup": list(PICKUP),
        "dropoff": [105.86, 21.04],
        "points": [pt(10, t=t, accuracy_m=5.0) for t in range(0, 201, 10)],
    }
    asyncio.run(worker.process_telemetry_event(event, case_service=_DbService(conn)))

    (_, _, _, _, _, _, _, _, ssd, _, features, _) = _feature_insert(conn)
    assert ssd is None
    features = json.loads(features)
    assert features["approach_stationary_duration_s"] is None
    assert features["stationary_duration_total_s"] == 200.0


def _healthy() -> dict[str, str]:
    return {"app_state": "foreground", "network_state": "online", "gps_state": "valid"}

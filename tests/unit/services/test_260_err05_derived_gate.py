"""Issue #260 DoD-2/3 RED: ERR-05 gate on derived kinematics + branch reorder.

Contract under test (src/services/jev_assessment_service.py heuristic):
- DoD-2: ERR-05 requires mock flag OR derived-speed jump. A reported
  speed_mps spike alone (stationary coordinates) must NOT yield ERR-05.
  A derived jump (coordinates ~555 m apart in 5 s, reported speed calm)
  MUST yield ERR-05 even with no mock flag.
- DoD-3: stall/cancel evaluated before speed-only spoofing. A prolonged
  stall (>=180 s, non-completed lifecycle) with only a reported spike and
  no mock must reach ERR-02, not ERR-05.
- Mock flag alone still yields ERR-05 (gate preservation, green pre-fix).
"""

from scripts.benchmark.run_10k import build_offline_service
from src.services.jev_assessment_service import JevAssessmentInput


def _stationary_spoofed_points() -> list[dict]:
    return [
        {
            "latitude": 21.0285,
            "longitude": 105.8542,
            "accuracy_m": 8,
            "occurred_at": "2026-10-09T18:47:21+00:00",
            "sequence": 0,
            "speed_mps": 57.5,
            "gps_state": "valid",
        },
        {
            "latitude": 21.0285,
            "longitude": 105.8542,
            "accuracy_m": 8,
            "occurred_at": "2026-10-09T18:47:31+00:00",
            "sequence": 1,
            "speed_mps": 57.5,
            "gps_state": "valid",
        },
    ]


def _derived_jump_points() -> list[dict]:
    # ~0.005 deg latitude ~= 555 m in 5 s => ~111 m/s derived, reported calm.
    return [
        {
            "latitude": 21.0285,
            "longitude": 105.8542,
            "accuracy_m": 8,
            "occurred_at": "2026-10-09T18:47:21+00:00",
            "sequence": 0,
            "speed_mps": 0.0,
            "gps_state": "valid",
        },
        {
            "latitude": 21.0335,
            "longitude": 105.8542,
            "accuracy_m": 8,
            "occurred_at": "2026-10-09T18:47:26+00:00",
            "sequence": 1,
            "speed_mps": 0.0,
            "gps_state": "valid",
        },
    ]


async def test_reported_spike_alone_is_not_err05():
    pts = _stationary_spoofed_points()
    service = build_offline_service()
    inp = JevAssessmentInput(
        driver={},
        telemetry={"points": pts, "max_speed_kmh": 57.5 * 3.6},
        trip_data={"lifecycle_state": "completed", "status": "completed"},
    )
    result = await service.assess(inp)
    assert result.category != "ERR-05"


async def test_derived_jump_without_mock_is_err05():
    pts = _derived_jump_points()
    service = build_offline_service()
    inp = JevAssessmentInput(
        driver={},
        telemetry={"points": pts, "max_speed_kmh": 0.0},
        trip_data={"lifecycle_state": "completed", "status": "completed"},
    )
    result = await service.assess(inp)
    assert result.category == "ERR-05"


def _jitter_points() -> list[dict]:
    # Same teleport-scale displacement as _derived_jump_points (~555 m in 5 s)
    # but endpoint accuracy (~900 m) explains it as GPS jitter, not spoofing.
    return [
        {
            "latitude": 21.0285,
            "longitude": 105.8542,
            "accuracy_m": 32.8,
            "occurred_at": "2026-10-09T18:47:21+00:00",
            "sequence": 0,
            "speed_mps": 0.0,
            "gps_state": "valid",
        },
        {
            "latitude": 21.0335,
            "longitude": 105.8542,
            "accuracy_m": 939.0,
            "occurred_at": "2026-10-09T18:47:26+00:00",
            "sequence": 1,
            "speed_mps": 0.0,
            "gps_state": "valid",
        },
    ]


async def test_jitter_jump_with_bad_accuracy_is_not_err05():
    pts = _jitter_points()
    service = build_offline_service()
    inp = JevAssessmentInput(
        driver={},
        telemetry={"points": pts, "max_speed_kmh": 0.0},
        trip_data={"lifecycle_state": "completed", "status": "completed"},
    )
    result = await service.assess(inp)
    assert result.category != "ERR-05"


async def test_mock_flag_still_err05():
    pts = [dict(_stationary_spoofed_points()[0], mock_location_reported=True)]
    service = build_offline_service()
    inp = JevAssessmentInput(
        driver={},
        telemetry={"points": pts, "max_speed_kmh": 0.0, "mock_location_reported": True},
        trip_data={"lifecycle_state": "completed", "status": "completed"},
    )
    result = await service.assess(inp)
    assert result.category == "ERR-05"


async def test_stall_evaluated_before_speed_only_spoof():
    pts = _stationary_spoofed_points()
    service = build_offline_service()
    inp = JevAssessmentInput(
        driver={},
        telemetry={
            "points": pts,
            "max_speed_kmh": 57.5 * 3.6,
            "stationary_duration_s": 200,
            "maneuvers": [{"action": "stop", "duration_s": 200}],
        },
        trip_data={
            "lifecycle_state": "cancelled",
            "status": "cancelled",
            "cancellation_actor": "passenger",
            "cancellation_reason": "driver stalling",
        },
    )
    result = await service.assess(inp)
    assert result.category == "ERR-02"

"""TDD Tests for Map Full Features:
1. Shortest path & 3 top candidate routes (DAVI, SDD, distance, traffic signals)
2. Timeline tracking & milestones
3. Traffic mock & multi-driver corroboration
4. Data missingness alert detection
5. Telemetry worker & CaseService integration
"""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from src.config import Settings
from src.services.case_service import CaseService
from src.services.telemetry_queue_worker import (
    build_trip_timeline_milestones,
    corroborate_traffic_claim,
    detect_telemetry_missingness,
    parse_trajectory_maneuvers,
    process_telemetry_event,
)

pytestmark = pytest.mark.docker


@pytest.fixture
def in_memory_case_service(monkeypatch):
    """Keep fixture-focused detail tests off an injected database fixture."""
    monkeypatch.setattr(CaseService, "_get_db_connection", lambda self: None)


def test_missing_traffic_sources_remain_inconclusive():
    result = corroborate_traffic_claim(
        road_segment="unknown",
        observed_at="2026-09-22T08:12:00Z",
        suspect={"speed_kmh": 0.0, "stall_duration_s": 210},
    )

    assert result["verdict"] == "inconclusive"
    assert result["peer_drivers"] == []
    assert result["public_service"] is None
    assert "unavailable" in result["verdict_detail"].lower()


def test_timeline_and_maneuvers_do_not_invent_missing_coordinates():
    points = [{"occurred_at": "2026-09-22T08:12:00Z", "speed_mps": 0.0}]

    assert build_trip_timeline_milestones(points, pickup_pos=None, dropoff_pos=None, stall_duration_s=210) == []
    assert parse_trajectory_maneuvers(points, stall_duration_s=210) == []


def test_pickup_milestone_uses_first_destination_leg_transition():
    """Pickup milestone time is the recorded departure from pickup, not points[-2]."""
    base_time = datetime(2026, 9, 22, 8, 0, 0, tzinfo=UTC)
    points = [
        {
            "occurred_at": (base_time + timedelta(seconds=0)).isoformat(),
            "sequence": 1,
            "leg": "pickup",
            "latitude": 21.0200,
            "longitude": 105.8500,
            "speed_mps": 0.0,
        },
        {
            "occurred_at": (base_time + timedelta(seconds=10)).isoformat(),
            "sequence": 2,
            "leg": "pickup",
            "latitude": 21.0260,
            "longitude": 105.8512,
            "speed_mps": 8.0,
        },
        {
            "occurred_at": (base_time + timedelta(seconds=20)).isoformat(),
            "sequence": 3,
            "leg": "pickup",
            "latitude": 21.0265,
            "longitude": 105.8515,
            "speed_mps": 2.0,
        },
        {
            "occurred_at": (base_time + timedelta(seconds=40)).isoformat(),
            "sequence": 4,
            "leg": "destination",
            "latitude": 21.0270,
            "longitude": 105.8520,
            "speed_mps": 9.0,
        },
        {
            "occurred_at": (base_time + timedelta(seconds=120)).isoformat(),
            "sequence": 5,
            "leg": "destination",
            "latitude": 21.0400,
            "longitude": 105.8300,
            "speed_mps": 12.0,
        },
        {
            "occurred_at": (base_time + timedelta(seconds=600)).isoformat(),
            "sequence": 6,
            "leg": "destination",
            "latitude": 21.2243,
            "longitude": 105.8082,
            "speed_mps": 15.0,
        },
    ]

    milestones = build_trip_timeline_milestones(
        points,
        pickup_pos=[105.8515, 21.0265],
        dropoff_pos=[105.8082, 21.2243],
        ended_at=(base_time + timedelta(seconds=600)).isoformat(),
        trip_status="completed",
        assignment_state="completed",
    )
    pickup = next(m for m in milestones if m["type"] == "pickup")
    dropoff = next(m for m in milestones if m["type"] == "dropoff_destination")

    assert pickup["timestamp"] == (base_time + timedelta(seconds=40)).isoformat()
    assert pickup["timestamp"] != (base_time + timedelta(seconds=120)).isoformat()
    assert dropoff["timestamp"] == (base_time + timedelta(seconds=600)).isoformat()


def test_pickup_milestone_has_no_fabricated_timestamp_without_lifecycle_or_transition():
    """Unlabeled telemetry cannot establish pickup from an arbitrary sample."""
    base_time = datetime(2026, 9, 22, 8, 0, 0, tzinfo=UTC)
    points = [
        {
            "occurred_at": (base_time + timedelta(seconds=0)).isoformat(),
            "sequence": 1,
            "latitude": 21.0200,
            "longitude": 105.8500,
            "speed_mps": 0.0,
        },
        {
            "occurred_at": (base_time + timedelta(seconds=30)).isoformat(),
            "sequence": 2,
            "latitude": 21.0260,
            "longitude": 105.8512,
            "speed_mps": 8.0,
        },
        {
            "occurred_at": (base_time + timedelta(seconds=90)).isoformat(),
            "sequence": 3,
            "latitude": 21.0265,
            "longitude": 105.8515,
            "speed_mps": 2.0,
        },
        {
            "occurred_at": (base_time + timedelta(seconds=600)).isoformat(),
            "sequence": 4,
            "latitude": 21.2243,
            "longitude": 105.8082,
            "speed_mps": 15.0,
        },
    ]

    milestones = build_trip_timeline_milestones(points, pickup_pos=[105.8515, 21.0265], dropoff_pos=[105.8082, 21.2243])
    assert not any(m["type"] == "pickup" for m in milestones)
    assert not any(m["type"] == "dropoff_destination" for m in milestones)


def test_pickup_milestone_uses_recorded_lifecycle_without_leg_transition():
    """Lifecycle arrived_at/ended_at override the point approximation when present."""
    base_time = datetime(2026, 9, 22, 8, 0, 0, tzinfo=UTC)
    arrived = (base_time + timedelta(seconds=35)).isoformat()
    ended = (base_time + timedelta(seconds=605)).isoformat()
    points = [
        {
            "occurred_at": (base_time + timedelta(seconds=0)).isoformat(),
            "sequence": 1,
            "latitude": 21.0200,
            "longitude": 105.8500,
            "speed_mps": 0.0,
        },
        {
            "occurred_at": (base_time + timedelta(seconds=30)).isoformat(),
            "sequence": 2,
            "latitude": 21.0260,
            "longitude": 105.8512,
            "speed_mps": 8.0,
        },
        {
            "occurred_at": (base_time + timedelta(seconds=90)).isoformat(),
            "sequence": 3,
            "latitude": 21.0265,
            "longitude": 105.8515,
            "speed_mps": 2.0,
        },
        {
            "occurred_at": (base_time + timedelta(seconds=600)).isoformat(),
            "sequence": 4,
            "latitude": 21.2243,
            "longitude": 105.8082,
            "speed_mps": 15.0,
        },
    ]

    milestones = build_trip_timeline_milestones(
        points,
        pickup_pos=[105.8515, 21.0265],
        dropoff_pos=[105.8082, 21.2243],
        arrived_at=arrived,
        ended_at=ended,
        trip_status="completed",
        assignment_state="completed",
    )
    pickup = next(m for m in milestones if m["type"] == "pickup")
    dropoff = next(m for m in milestones if m["type"] == "dropoff_destination")

    assert pickup["timestamp"] == arrived
    assert dropoff["timestamp"] == ended
    assert pickup["speed_mps"] is None
    assert pickup["sequence"] is None
    assert dropoff["speed_mps"] is None
    assert dropoff["sequence"] is None


def test_lifecycle_checkpoints_render_without_telemetry():
    milestones = build_trip_timeline_milestones(
        [],
        [105.851, 21.021],
        [105.86, 21.03],
        arrived_at="2026-09-22T08:01:00+00:00",
        ended_at="2026-09-22T08:02:00+00:00",
        trip_status="completed",
        assignment_state="completed",
    )
    assert [m["type"] for m in milestones] == ["pickup", "dropoff_destination"]
    assert all(m["sequence"] is None and m["speed_mps"] is None for m in milestones)


def test_invalid_lifecycle_values_are_ignored_without_gps_completion_fallback():
    points = [{"occurred_at": "2026-09-22T08:00:00+00:00", "sequence": 7, "latitude": 21.02, "longitude": 105.85}]
    milestones = build_trip_timeline_milestones(
        points,
        [105.851, 21.021],
        [105.86, 21.03],
        arrived_at="not-a-date",
        ended_at="also-invalid",
        trip_status="completed",
        assignment_state="completed",
    )
    assert not any(m["type"] == "pickup" for m in milestones)
    assert not any(m["type"] == "dropoff_destination" for m in milestones)


def test_non_string_lifecycle_values_are_ignored():
    milestones = build_trip_timeline_milestones(
        [],
        [105.851, 21.021],
        [105.86, 21.03],
        arrived_at=123,
        ended_at=456,
        trip_status="completed",
        assignment_state="completed",
    )
    assert milestones == []


def test_no_points_uses_assignment_completion_when_trip_status_absent():
    milestones = build_trip_timeline_milestones(
        [],
        [105.851, 21.021],
        [105.86, 21.03],
        ended_at="2026-09-22T08:02:00+00:00",
        trip_status=None,
        assignment_state="completed",
    )
    assert [m["type"] for m in milestones] == ["dropoff_destination"]


def test_pickup_milestone_tolerates_missing_occurred_at():
    """A leg transition without occurred_at must not crash or fabricate a time."""
    base_time = datetime(2026, 9, 22, 8, 0, 0, tzinfo=UTC)
    points = [
        {
            "occurred_at": (base_time + timedelta(seconds=0)).isoformat(),
            "sequence": 1,
            "leg": "pickup",
            "latitude": 21.0200,
            "longitude": 105.8500,
            "speed_mps": 0.0,
        },
        {"sequence": 2, "leg": "destination", "latitude": 21.0270, "longitude": 105.8520, "speed_mps": 9.0},
        {
            "occurred_at": (base_time + timedelta(seconds=600)).isoformat(),
            "sequence": 3,
            "leg": "destination",
            "latitude": 21.2243,
            "longitude": 105.8082,
            "speed_mps": 15.0,
        },
    ]

    milestones = build_trip_timeline_milestones(points, pickup_pos=[105.8515, 21.0265], dropoff_pos=[105.8082, 21.2243])
    assert not any(m["type"] == "pickup" for m in milestones)


def test_cancelled_trip_does_not_turn_ended_at_into_dropoff():
    points = [{"occurred_at": "2026-09-22T08:00:00+00:00", "sequence": 1, "latitude": 21.02, "longitude": 105.85}]
    milestones = build_trip_timeline_milestones(
        points,
        [105.851, 21.021],
        [105.86, 21.03],
        arrived_at="2026-09-22T08:01:00+00:00",
        ended_at="2026-09-22T08:02:00+00:00",
        trip_status="cancelled",
        assignment_state="cancelled",
    )
    assert not any(m["type"] == "dropoff_destination" for m in milestones)


def test_unknown_trip_status_with_recorded_end_does_not_create_dropoff():
    milestones = build_trip_timeline_milestones(
        [],
        [105.851, 21.021],
        [105.86, 21.03],
        ended_at="2026-09-22T08:02:00+00:00",
        trip_status=None,
        assignment_state=None,
    )

    assert not any(m["type"] == "dropoff_destination" for m in milestones)


def test_completed_trip_uses_recorded_lifecycle_timestamps_only():
    points = [{"occurred_at": "2026-09-22T08:00:00+00:00", "sequence": 1, "latitude": 21.02, "longitude": 105.85}]
    milestones = build_trip_timeline_milestones(
        points,
        [105.851, 21.021],
        [105.86, 21.03],
        arrived_at="2026-09-22T08:01:00+00:00",
        ended_at="2026-09-22T08:02:00+00:00",
        trip_status="completed",
        assignment_state="completed",
    )
    assert next(m for m in milestones if m["type"] == "pickup")["timestamp"] == "2026-09-22T08:01:00+00:00"
    assert next(m for m in milestones if m["type"] == "dropoff_destination")["timestamp"] == "2026-09-22T08:02:00+00:00"


def test_completed_trip_keeps_known_terminal_time_when_terminal_gps_is_null():
    points = [
        {"occurred_at": "2026-09-22T08:00:00+00:00", "sequence": 1, "latitude": 21.02, "longitude": 105.85},
        {"occurred_at": None, "sequence": 2, "latitude": None, "longitude": None},
    ]
    milestones = build_trip_timeline_milestones(
        points,
        [105.851, 21.021],
        [105.86, 21.03],
        ended_at="2026-09-22T08:02:00+00:00",
        trip_status="completed",
        assignment_state="completed",
    )
    dropoff = next(m for m in milestones if m["type"] == "dropoff_destination")
    assert dropoff["timestamp"] == "2026-09-22T08:02:00+00:00"


def test_cancelled_trip_wins_over_completed_assignment_for_dropoff():
    points = [{"occurred_at": "2026-09-22T08:00:00+00:00", "sequence": 1, "latitude": 21.02, "longitude": 105.85}]
    milestones = build_trip_timeline_milestones(
        points,
        [105.851, 21.021],
        [105.86, 21.03],
        ended_at="2026-09-22T08:02:00+00:00",
        trip_status="cancelled",
        assignment_state="completed",
    )
    assert not any(m["type"] == "dropoff_destination" for m in milestones)


@pytest.mark.asyncio
async def test_fixture_case_detail_uses_same_lifecycle_gate_as_builder(in_memory_case_service):
    service = CaseService(Settings(app_env="test", database_url="postgresql://configured", _env_file=None))
    case_id = "fixture-case-8921"
    assignment_id = "assignment-8921"
    service._cases[case_id] = {"id": case_id, "assignment_id": assignment_id, "status": "ready"}
    service._assignments[assignment_id] = {"id": assignment_id, "trip_id": "trip-8921", "driver_id": "driver-8921"}
    service._trips["trip-8921"] = {
        "id": "trip-8921",
        "pickup": {"coordinates": [105.851, 21.021]},
        "dropoff": {"coordinates": [105.86, 21.03]},
    }
    assignment = service._assignments[assignment_id]
    trip = service._trips["trip-8921"]
    service._telemetry_points = [
        {
            "assignment_id": assignment_id,
            "occurred_at": "2026-09-22T08:00:00+00:00",
            "latitude": 21.02,
            "longitude": 105.85,
        },
        {"assignment_id": assignment_id, "occurred_at": None, "latitude": None, "longitude": None},
    ]
    assignment.update(
        {"state": "cancelled", "arrived_at": "2026-09-22T08:01:00+00:00", "ended_at": "2026-09-22T08:02:00+00:00"}
    )
    trip["status"] = "cancelled"
    service._timeline_milestones.clear()

    detail = await service.get_case_detail(case_id)

    assert not any(m["type"] == "dropoff_destination" for m in detail.timeline_milestones)
    assert detail.missingness_alerts[-1]["end_time"] == "2026-09-22T08:02:00+00:00"


@pytest.mark.asyncio
async def test_fixture_case_detail_unknown_status_does_not_complete_recorded_end(in_memory_case_service):
    service = CaseService(Settings(app_env="test", database_url="postgresql://configured", _env_file=None))
    case_id = "fixture-case-8921"
    assignment_id = "assignment-8921"
    service._cases[case_id] = {"id": case_id, "assignment_id": assignment_id, "status": "ready"}
    service._assignments[assignment_id] = {"id": assignment_id, "trip_id": "trip-8921", "driver_id": "driver-8921"}
    service._trips["trip-8921"] = {
        "id": "trip-8921",
        "pickup": {"coordinates": [105.851, 21.021]},
        "dropoff": {"coordinates": [105.86, 21.03]},
    }
    assignment = service._assignments[assignment_id]
    trip = service._trips[str(assignment["trip_id"])]
    assignment.update({"state": None, "arrived_at": None, "ended_at": "2026-09-22T08:02:00+00:00"})
    trip.pop("status", None)
    service._timeline_milestones.clear()

    detail = await service.get_case_detail(case_id)

    assert not any(m["type"] == "dropoff_destination" for m in detail.timeline_milestones)


@pytest.mark.asyncio
async def test_case_detail_rebuilds_stale_cached_timeline_with_recorded_lifecycle(in_memory_case_service):
    service = CaseService(Settings(app_env="test", database_url="postgresql://configured", _env_file=None))
    case_id = "fixture-case-8921"
    assignment_id = "assignment-8921"
    service._cases[case_id] = {"id": case_id, "assignment_id": assignment_id, "status": "ready"}
    service._assignments[assignment_id] = {"id": assignment_id, "trip_id": "trip-8921", "driver_id": "driver-8921"}
    service._trips["trip-8921"] = {
        "id": "trip-8921",
        "pickup": {"coordinates": [105.851, 21.021]},
        "dropoff": {"coordinates": [105.86, 21.03]},
    }
    assignment = service._assignments[assignment_id]
    trip = service._trips[str(assignment["trip_id"])]
    assignment.update(
        {
            "state": "completed",
            "arrived_at": "2026-09-22T08:01:00+00:00",
            "ended_at": "2026-09-22T08:02:00+00:00",
        }
    )
    trip["status"] = "completed"
    trip["pickup"] = {"coordinates": [105.851, 21.021]}
    trip["dropoff"] = {"coordinates": [105.86, 21.03]}
    service._timeline_milestones[case_id] = [
        {"id": "stale", "type": "pickup", "timestamp": "2026-09-22T07:00:00+00:00"}
    ]

    detail = await service.get_case_detail(case_id)

    pickup = next(m for m in detail.timeline_milestones if m["type"] == "pickup")
    dropoff = next(m for m in detail.timeline_milestones if m["type"] == "dropoff_destination")
    assert pickup["timestamp"] == "2026-09-22T08:01:00+00:00"
    assert dropoff["timestamp"] == "2026-09-22T08:02:00+00:00"


@pytest.mark.asyncio
async def test_case_detail_recomputes_nonempty_stale_missingness_cache_to_recorded_end(in_memory_case_service):
    service = CaseService(Settings(app_env="test", database_url="postgresql://configured", _env_file=None))
    case_id = "fixture-case-8921"
    assignment_id = "assignment-8921"
    service._cases[case_id] = {"id": case_id, "assignment_id": assignment_id, "status": "ready"}
    service._assignments[assignment_id] = {
        "id": assignment_id,
        "trip_id": "trip-8921",
        "driver_id": "driver-8921",
        "ended_at": "2026-09-22T08:02:00+00:00",
    }
    service._trips["trip-8921"] = {"id": "trip-8921"}
    service._telemetry_points = [
        {
            "assignment_id": assignment_id,
            "occurred_at": "2026-09-22T08:01:00+00:00",
            "latitude": None,
            "longitude": None,
            "gps_state": "unavailable",
        }
    ]
    service._missingness_alerts[case_id] = [
        {
            "alert_id": "stale-alert",
            "start_time": "2026-09-22T07:00:00+00:00",
            "end_time": "2026-09-22T07:01:00+00:00",
            "gap_duration_s": 60,
            "reason": "stale",
            "severity": "critical",
        }
    ]

    detail = await service.get_case_detail(case_id)

    assert detail.missingness_alerts[0]["end_time"] == "2026-09-22T08:02:00+00:00"


def test_recorded_lifecycle_timestamps_must_be_chronological():
    milestones = build_trip_timeline_milestones(
        [],
        [105.851, 21.021],
        [105.86, 21.03],
        arrived_at="2026-09-22T08:02:00+00:00",
        ended_at="2026-09-22T08:01:00+00:00",
        trip_status="completed",
        assignment_state="completed",
    )

    assert milestones == []


def test_invalid_lifecycle_order_keeps_observed_gps_milestones():
    points = [
        {
            "occurred_at": "2026-09-22T08:00:00+00:00",
            "sequence": 1,
            "latitude": 21.02,
            "longitude": 105.85,
            "speed_mps": 0.0,
        },
        {
            "occurred_at": "2026-09-22T08:02:00+00:00",
            "sequence": 2,
            "latitude": 21.021,
            "longitude": 105.851,
            "speed_mps": 0.0,
        },
    ]

    milestones = build_trip_timeline_milestones(
        points,
        [105.851, 21.021],
        [105.86, 21.03],
        stall_duration_s=60,
        arrived_at="2026-09-22T08:03:00+00:00",
        ended_at="2026-09-22T08:01:00+00:00",
        trip_status="completed",
        assignment_state="completed",
    )

    assert [milestone["type"] for milestone in milestones] == ["start_match", "stall_anomaly"]
    assert all(milestone.get("sequence") is not None for milestone in milestones)
    assert not any(milestone["type"] in {"pickup", "dropoff_destination"} for milestone in milestones)


def test_detect_telemetry_missingness():
    """Verify data missingness / network error alerts when gap > threshold."""
    base_time = datetime(2026, 9, 22, 8, 10, 0, tzinfo=UTC)
    points = [
        {
            "occurred_at": (base_time + timedelta(seconds=0)).isoformat(),
            "sequence": 1,
            "latitude": 21.0250,
            "longitude": 105.8512,
            "speed_mps": 8.0,
            "network_state": "online",
        },
        {
            "occurred_at": (base_time + timedelta(seconds=10)).isoformat(),
            "sequence": 2,
            "latitude": 21.0260,
            "longitude": 105.8520,
            "speed_mps": 7.5,
            "network_state": "online",
        },
        # 45s gap between point 2 (at +10s) and point 3 (at +55s)
        {
            "occurred_at": (base_time + timedelta(seconds=55)).isoformat(),
            "sequence": 3,
            "latitude": 21.0270,
            "longitude": 105.8530,
            "speed_mps": 0.0,
            "network_state": "degraded",
        },
    ]

    alerts = detect_telemetry_missingness(points, gap_threshold_s=30)
    assert len(alerts) == 1
    alert = alerts[0]
    assert alert["gap_duration_s"] == 45
    assert "network" in alert["reason"].lower() or "telemetry" in alert["reason"].lower()
    assert alert["severity"] in ("warning", "critical")


def test_terminal_invalid_gps_gap_ends_at_recorded_lifecycle_time():
    points = [
        {"occurred_at": "2026-09-22T08:00:00+00:00", "latitude": 21.02, "longitude": 105.85},
        {"occurred_at": "2026-09-22T08:01:00+00:00", "latitude": None, "longitude": None, "gps_state": "unavailable"},
    ]
    alerts = detect_telemetry_missingness(points, end_time="2026-09-22T08:02:00+00:00")
    assert alerts[-1]["start_time"] == "2026-09-22T08:01:00+00:00"
    assert alerts[-1]["end_time"] == "2026-09-22T08:02:00+00:00"


def test_terminal_invalid_gps_without_recorded_end_has_no_inferred_gap():
    points = [
        {"occurred_at": "2026-09-22T08:01:00+00:00", "latitude": None, "longitude": None, "gps_state": "unavailable"}
    ]
    assert detect_telemetry_missingness(points) == []


def test_terminal_valid_point_before_recorded_end_has_no_gap_alert():
    points = [
        {
            "occurred_at": "2026-09-22T08:01:00+00:00",
            "latitude": 21.02,
            "longitude": 105.85,
            "gps_state": "valid",
            "network_state": "online",
        }
    ]

    assert detect_telemetry_missingness(points, end_time="2026-09-22T08:02:00+00:00") == []


def test_terminal_explicit_failure_at_exact_threshold_remains_available_as_short_outage():
    points = [
        {
            "occurred_at": "2026-09-22T08:01:00+00:00",
            "latitude": None,
            "longitude": None,
            "gps_state": "unavailable",
        }
    ]

    alerts = detect_telemetry_missingness(
        points,
        gap_threshold_s=30,
        end_time="2026-09-22T08:01:30+00:00",
    )

    assert len(alerts) == 1
    assert alerts[0]["gap_duration_s"] == 30


def test_single_terminal_invalid_sample_uses_recorded_end_bound():
    points = [
        {
            "occurred_at": "2026-09-22T08:01:30+00:00",
            "latitude": None,
            "longitude": None,
            "gps_state": "unavailable",
        }
    ]
    alerts = detect_telemetry_missingness(points, end_time="2026-09-22T08:11:00+00:00")
    assert len(alerts) == 1
    assert alerts[0]["gap_duration_s"] == 570


def test_corroborate_traffic_claim_refuted():
    """When suspect driver stalls claiming traffic, but peer drivers pass smoothly, refute claim."""
    suspect = {
        "driver_id": "drv-001",
        "speed_kmh": 0.0,
        "stall_duration_s": 210,
        "claimed_reason": "Kẹt xe nghiêm trọng",
    }
    peers = [
        {
            "driver_id": "drv-002",
            "vehicle_plate": "29A-111.22",
            "speed_kmh": 34.0,
            "passed_at": "08:12:00",
            "status": "clear",
        },
        {
            "driver_id": "drv-003",
            "vehicle_plate": "29E-333.44",
            "speed_kmh": 32.0,
            "passed_at": "08:13:00",
            "status": "clear",
        },
    ]
    traffic_service = {
        "provider": "test-fixture",
        "average_speed_kmh": 33.0,
        "congestion": "clear",
        "signal_status": "green_wave",
    }

    result = corroborate_traffic_claim(
        road_segment="Phố Bà Triệu - Lý Thường Kiệt",
        observed_at="2026-09-22T08:12:00Z",
        suspect=suspect,
        peers=peers,
        public_service=traffic_service,
    )
    assert result["verdict"] == "refuted"
    assert "refuted" in result["verdict_detail"].lower() or "vi phạm" in result["verdict_detail"].lower()


def test_corroborate_traffic_claim_corroborated():
    """When traffic is genuinely congested and peer drivers are also stalled/slow, corroborate."""
    suspect = {
        "driver_id": "drv-001",
        "speed_kmh": 0.0,
        "stall_duration_s": 210,
        "claimed_reason": "Kẹt xe do tai nạn giao thông",
    }
    peers = [
        {
            "driver_id": "drv-002",
            "vehicle_plate": "29A-111.22",
            "speed_kmh": 3.0,
            "passed_at": "08:12:00",
            "status": "gridlock",
        },
        {
            "driver_id": "drv-003",
            "vehicle_plate": "29E-333.44",
            "speed_kmh": 0.0,
            "passed_at": "08:13:00",
            "status": "gridlock",
        },
    ]
    traffic_service = {
        "provider": "test-fixture",
        "average_speed_kmh": 2.5,
        "congestion": "heavy",
        "signal_status": "red_extended",
    }

    result = corroborate_traffic_claim(
        road_segment="Phố Bà Triệu - Lý Thường Kiệt",
        observed_at="2026-09-22T08:12:00Z",
        suspect=suspect,
        peers=peers,
        public_service=traffic_service,
    )
    assert result["verdict"] == "corroborated"


def test_build_trip_timeline_milestones():
    """Verify timeline milestones from matching to destination including anomalies."""
    base_time = datetime(2026, 9, 22, 8, 10, 0, tzinfo=UTC)
    points = [
        {
            "occurred_at": (base_time + timedelta(seconds=0)).isoformat(),
            "speed_mps": 0.0,
            "latitude": 21.0250,
            "longitude": 105.8512,
            "sequence": 0,
        },
        {
            "occurred_at": (base_time + timedelta(seconds=120)).isoformat(),
            "speed_mps": 0.0,
            "latitude": 21.0268,
            "longitude": 105.8520,
            "sequence": 1,
        },
        {
            "occurred_at": (base_time + timedelta(seconds=330)).isoformat(),
            "speed_mps": 8.0,
            "latitude": 21.0285,
            "longitude": 105.8542,
            "sequence": 2,
        },
        {
            "occurred_at": (base_time + timedelta(seconds=600)).isoformat(),
            "speed_mps": 11.0,
            "latitude": 21.0350,
            "longitude": 105.8600,
            "sequence": 3,
        },
    ]

    milestones = build_trip_timeline_milestones(
        points=points,
        pickup_pos=[105.8542, 21.0285],
        dropoff_pos=[105.8600, 21.0350],
        stall_duration_s=210,
        arrived_at=(base_time + timedelta(seconds=330)).isoformat(),
        ended_at=(base_time + timedelta(seconds=600)).isoformat(),
        trip_status="completed",
        assignment_state="completed",
    )

    types = [m["type"] for m in milestones]
    assert "start_match" in types
    assert "pickup" in types
    assert "dropoff_destination" in types
    assert "stall_anomaly" in types


@pytest.mark.asyncio
async def test_telemetry_queue_worker_keeps_unavailable_route_and_traffic_absent():
    """Telemetry must not create pretend road routes or traffic corroboration."""
    service = CaseService(
        Settings(
            app_env="test",
            database_url="",
            fraud_classifier_enabled=False,
            _env_file=None,
        )
    )
    service.get_redis_client = lambda: None
    case_id = str(uuid4())
    trip_id = str(uuid4())
    assignment_id = str(uuid4())

    event_data = {
        "case_id": case_id,
        "trip_id": trip_id,
        "assignment_id": assignment_id,
        "driver_id": "018f2f4e-3000-7000-8000-000000000002",
        "scenario": "driver_stall_cancel",
        "stationary_duration_s": 210,
        "pickup": [105.8542, 21.0285],
        "dropoff": [105.8600, 21.0350],
        "points": [
            {
                "latitude": 21.0250,
                "longitude": 105.8512,
                "speed_mps": 6.5,
                "bearing_deg": 178.0,
                "occurred_at": "2026-09-22T08:10:00Z",
                "app_state": "foreground",
                "network_state": "online",
                "gps_state": "valid",
            },
            {
                "latitude": 21.0268,
                "longitude": 105.8520,
                "speed_mps": 0.0,
                "bearing_deg": 178.0,
                "occurred_at": "2026-09-22T08:12:00Z",
                "app_state": "foreground",
                "network_state": "online",
                "gps_state": "valid",
            },
            {
                "latitude": 21.0285,
                "longitude": 105.8542,
                "speed_mps": 0.0,
                "bearing_deg": 178.0,
                "occurred_at": "2026-09-22T08:15:30Z",
                "app_state": "foreground",
                "network_state": "online",
                "gps_state": "valid",
            },
        ],
    }

    res = await process_telemetry_event(event_data, service)
    assert res["status"] == "processed"

    # Now fetch case detail from CaseService and verify all enriched map properties
    detail = await service.get_case_detail(case_id)
    assert detail.candidate_routes == []
    assert detail.traffic_corroboration is None
    assert assignment_id not in service._route_snapshots
    assert detail.timeline_milestones is not None
    assert len(detail.timeline_milestones) >= 3
    assert detail.destination == {"latitude": 21.0350, "longitude": 105.8600, "label": "Destination"}


def test_missingness_time_boundary():
    base_time = datetime(2026, 9, 22, 8, 10, 0, tzinfo=UTC)
    points = [
        {"occurred_at": base_time.isoformat(), "latitude": 21.0, "longitude": 105.0},
        {
            "occurred_at": (base_time + timedelta(seconds=29, milliseconds=999)).isoformat(),
            "latitude": 21.1,
            "longitude": 105.1,
        },
        {"occurred_at": (base_time + timedelta(seconds=60)).isoformat(), "latitude": 21.2, "longitude": 105.2},
    ]
    alerts = detect_telemetry_missingness(points, gap_threshold_s=30)
    assert len(alerts) == 1
    assert alerts[0]["gap_duration_s"] == 30.001


def test_missingness_explicit_outage():
    base_time = datetime(2026, 9, 22, 8, 10, 0, tzinfo=UTC)
    points = [
        {"occurred_at": base_time.isoformat(), "latitude": 21.0, "longitude": 105.0},
        {
            "occurred_at": (base_time + timedelta(seconds=10)).isoformat(),
            "latitude": 21.1,
            "longitude": 105.1,
            "network_state": "offline",
        },
        {"occurred_at": (base_time + timedelta(seconds=20)).isoformat(), "latitude": 21.2, "longitude": 105.2},
    ]
    alerts = detect_telemetry_missingness(points, gap_threshold_s=30)
    assert len(alerts) == 2
    assert alerts[0]["gap_duration_s"] == 10
    assert alerts[1]["gap_duration_s"] == 10
    assert alerts[0]["reason"].startswith("Mạng di động")


def test_missingness_invalid_coordinate():
    base_time = datetime(2026, 9, 22, 8, 10, 0, tzinfo=UTC)
    points = [
        {"occurred_at": base_time.isoformat(), "latitude": 21.0, "longitude": 105.0},
        {"occurred_at": (base_time + timedelta(seconds=15)).isoformat(), "latitude": None, "longitude": 105.1},
        {"occurred_at": (base_time + timedelta(seconds=25)).isoformat(), "latitude": 21.2, "longitude": 105.2},
    ]
    alerts = detect_telemetry_missingness(points, gap_threshold_s=30)
    assert len(alerts) == 2
    assert alerts[0]["gap_duration_s"] == 15
    assert alerts[1]["gap_duration_s"] == 10
    assert alerts[0]["reason"].startswith("Dữ liệu tọa độ không hợp lệ")


def test_missingness_invalid_time_ordering():
    base_time = datetime(2026, 9, 22, 8, 10, 0, tzinfo=UTC)
    points = [
        {"occurred_at": base_time.isoformat(), "latitude": 21.0, "longitude": 105.0},
        {
            "occurred_at": (base_time - timedelta(seconds=10)).isoformat(),
            "latitude": 21.1,
            "longitude": 105.1,
            "network_state": "offline",
        },
    ]
    alerts = detect_telemetry_missingness(points, gap_threshold_s=30)
    assert len(alerts) == 0


def test_detect_telemetry_missingness_healthy_gap():
    """Verify that a 31s gap between valid online/foreground points reports missing telemetry without asserting network offline or crash."""
    base_time = datetime(2026, 9, 22, 8, 10, 0, tzinfo=UTC)
    points = [
        {
            "occurred_at": base_time.isoformat(),
            "sequence": 1,
            "latitude": 21.0250,
            "longitude": 105.8512,
            "speed_mps": 8.0,
            "network_state": "online",
            "app_state": "foreground",
            "gps_state": "active",
        },
        {
            "occurred_at": (base_time + timedelta(seconds=31)).isoformat(),
            "sequence": 2,
            "latitude": 21.0260,
            "longitude": 105.8520,
            "speed_mps": 7.5,
            "network_state": "online",
            "app_state": "foreground",
            "gps_state": "active",
        },
    ]

    alerts = detect_telemetry_missingness(points, gap_threshold_s=30)
    assert len(alerts) == 1
    alert = alerts[0]
    assert alert["gap_duration_s"] == 31.0
    assert alert["severity"] == "warning"
    assert "network" not in alert["reason"].lower()
    assert "crash" not in alert["reason"].lower()
    assert "mạng" not in alert["reason"].lower()
    assert "telemetry" in alert["reason"].lower()
    assert (
        "unknown" in alert["reason"].lower()
        or "không xác định" in alert["reason"].lower()
        or "chưa rõ" in alert["reason"].lower()
    )

"""Tests for GPS trajectory maneuver parsing, turn detection, stationary clustering, and narrative generation."""

from datetime import UTC, datetime, timedelta

import pytest

from src.services.route_analytics import (
    calculate_bearing_deg,
    format_maneuvers_for_llm,
    haversine_distance_m,
    heading_diff_deg,
    parse_trajectory_maneuvers,
)
from src.services.telemetry_queue_worker import JevAssessmentAgent


def test_haversine_and_bearing_helpers():
    """Verify distance and angle calculations between GPS coordinates."""
    p_origin = (105.8542, 21.0285)
    p_north = (105.8542, 21.0375)  # ~1000m north
    dist = haversine_distance_m(p_origin, p_north)
    assert 990 <= dist <= 1010

    bearing = calculate_bearing_deg(p_origin, p_north)
    assert abs(bearing - 0.0) < 1.0 or abs(bearing - 360.0) < 1.0

    # East bearing
    p_east = (105.8642, 21.0285)
    bearing_east = calculate_bearing_deg(p_origin, p_east)
    assert 88.0 <= bearing_east <= 92.0

    # Heading difference
    assert heading_diff_deg(0.0, 90.0) == 90.0  # Turn right
    assert heading_diff_deg(90.0, 0.0) == -90.0  # Turn left
    assert abs(heading_diff_deg(10.0, 190.0)) == 180.0  # U-turn


def test_parse_trajectory_maneuvers_straight_and_turns():
    """Verify trajectory stream correctly aggregates straight segments and turn maneuvers."""
    t0 = datetime(2026, 9, 24, 8, 0, 0, tzinfo=UTC)
    points = [
        # Segment 1: Heading North (~0 deg), moving ~8 m/s (~29 km/h)
        {
            "longitude": 105.8500,
            "latitude": 21.0200,
            "speed_mps": 8.0,
            "bearing_deg": 0.0,
            "occurred_at": (t0).isoformat(),
        },
        {
            "longitude": 105.8500,
            "latitude": 21.0210,
            "speed_mps": 8.5,
            "bearing_deg": 0.0,
            "occurred_at": (t0 + timedelta(seconds=10)).isoformat(),
        },
        {
            "longitude": 105.8500,
            "latitude": 21.0220,
            "speed_mps": 8.0,
            "bearing_deg": 0.0,
            "occurred_at": (t0 + timedelta(seconds=20)).isoformat(),
        },
        # Turn Right to East (~90 deg)
        {
            "longitude": 105.8510,
            "latitude": 21.0220,
            "speed_mps": 5.0,
            "bearing_deg": 90.0,
            "occurred_at": (t0 + timedelta(seconds=25)).isoformat(),
        },
        # Continue East
        {
            "longitude": 105.8520,
            "latitude": 21.0220,
            "speed_mps": 8.0,
            "bearing_deg": 90.0,
            "occurred_at": (t0 + timedelta(seconds=35)).isoformat(),
        },
    ]

    maneuvers = parse_trajectory_maneuvers(points, pickup=[105.8540, 21.0250])
    assert len(maneuvers) >= 3

    # First maneuver should be straight
    assert maneuvers[0]["action"] == "go_straight"
    assert "Đi thẳng" in maneuvers[0]["instruction"]
    assert maneuvers[0]["distance_m"] > 100

    # Second maneuver should be right turn
    turn_maneuver = [m for m in maneuvers if m["action"] == "turn_right"]
    assert len(turn_maneuver) == 1
    assert "Rẽ phải" in turn_maneuver[0]["instruction"]


def test_parse_trajectory_maneuvers_stationary_stall():
    """Verify stationary points are clustered into a stop maneuver with violation flag when >= 180s."""
    t0 = datetime(2026, 9, 24, 8, 0, 0, tzinfo=UTC)
    points = [
        # Initial short drive
        {
            "longitude": 105.8500,
            "latitude": 21.0200,
            "speed_mps": 7.0,
            "bearing_deg": 45.0,
            "occurred_at": t0.isoformat(),
        },
        {
            "longitude": 105.8505,
            "latitude": 21.0205,
            "speed_mps": 7.0,
            "bearing_deg": 45.0,
            "occurred_at": (t0 + timedelta(seconds=10)).isoformat(),
        },
        # Driver stops for 240 seconds near pickup point
        {
            "longitude": 105.8510,
            "latitude": 21.0210,
            "speed_mps": 0.0,
            "bearing_deg": 45.0,
            "occurred_at": (t0 + timedelta(seconds=20)).isoformat(),
        },
        {
            "longitude": 105.8510,
            "latitude": 21.0210,
            "speed_mps": 0.0,
            "bearing_deg": 45.0,
            "occurred_at": (t0 + timedelta(seconds=140)).isoformat(),
        },
        {
            "longitude": 105.8510,
            "latitude": 21.0210,
            "speed_mps": 0.0,
            "bearing_deg": 45.0,
            "occurred_at": (t0 + timedelta(seconds=260)).isoformat(),
        },
    ]

    pickup = [105.8520, 21.0215]
    maneuvers = parse_trajectory_maneuvers(points, pickup=pickup)
    stops = [m for m in maneuvers if m["action"] == "stop"]
    assert len(stops) == 1
    stop = stops[0]
    assert stop["duration_s"] >= 240
    assert stop["is_anomaly"] is True
    assert "Dừng đỗ" in stop["instruction"]
    assert "Điều 14.2" in stop["instruction"]
    assert "cách điểm đón" in stop["instruction"]


def test_format_maneuvers_for_llm_narrative():
    """Verify generated LLM prompt narrative contains structured metrics and step-by-step maneuvers."""
    t0 = datetime(2026, 9, 24, 8, 0, 0, tzinfo=UTC)
    points = [
        {"longitude": 105.8500, "latitude": 21.0200, "speed_mps": 0.0, "occurred_at": t0.isoformat()},
        {
            "longitude": 105.8500,
            "latitude": 21.0200,
            "speed_mps": 0.0,
            "occurred_at": (t0 + timedelta(seconds=210)).isoformat(),
        },
    ]
    event_data = {
        "scenario": "driver_stall",
        "pickup": [105.8510, 21.0210],
        "dropoff": [105.8600, 21.0300],
        "cancellation_reason": "Tài xế dừng quá lâu không đón",
        "cancellation_actor": "passenger",
    }
    maneuvers = parse_trajectory_maneuvers(points, pickup=event_data["pickup"], stall_duration_s=210)
    narrative = format_maneuvers_for_llm(maneuvers, event_data)

    assert "HỒ SƠ PHÂN TÍCH ĐỘNG HỌC & ĐIỀU HƯỚNG TÀI XẾ" in narrative
    assert "Dừng đỗ 210s" in narrative
    assert "CẢNH BÁO ĐIỀU 14.2" in narrative
    assert "Tài xế dừng quá lâu không đón" in narrative


@pytest.mark.asyncio
async def test_jev_assessment_agent_populates_maneuvers():
    """Verify JevAssessmentAgent extracts maneuvers and populates them in the assessment result."""
    agent = JevAssessmentAgent()
    event_data = {
        "scenario": "driver_stall",
        "stationary_duration_s": 220,
        "pickup": [105.8542, 21.0285],
        "dropoff": [105.8600, 21.0350],
        "points": [
            {"latitude": 21.0285, "longitude": 105.8540, "speed_mps": 0.0},
        ],
    }
    assessment = await agent.assess(event_data)
    assert assessment["category"] == "ERR-02"
    assert "maneuvers" in assessment
    assert len(assessment["maneuvers"]) > 0
    assert "maneuver_narrative" in assessment
    assert "Dừng đỗ 220s" in assessment["maneuver_narrative"]


def test_parse_trajectory_maneuvers_wrong_direction():
    """Verify driver moving at speed away from pickup is flagged as wrong direction under Điều 16.1."""
    t0 = datetime(2026, 9, 24, 8, 0, 0, tzinfo=UTC)
    # Pickup is at North-East [105.8600, 21.0350]
    pickup = [105.8600, 21.0350]
    # Driver moves South-West [105.8500, 21.0250] -> [105.8470, 21.0220] (opposite direction)
    points = [
        {
            "longitude": 105.8500,
            "latitude": 21.0250,
            "speed_mps": 8.0,
            "bearing_deg": 225.0,
            "occurred_at": t0.isoformat(),
        },
        {
            "longitude": 105.8490,
            "latitude": 21.0240,
            "speed_mps": 8.5,
            "bearing_deg": 225.0,
            "occurred_at": (t0 + timedelta(seconds=10)).isoformat(),
        },
        {
            "longitude": 105.8480,
            "latitude": 21.0230,
            "speed_mps": 8.0,
            "bearing_deg": 225.0,
            "occurred_at": (t0 + timedelta(seconds=20)).isoformat(),
        },
        {
            "longitude": 105.8470,
            "latitude": 21.0220,
            "speed_mps": 8.0,
            "bearing_deg": 225.0,
            "occurred_at": (t0 + timedelta(seconds=30)).isoformat(),
        },
    ]

    maneuvers = parse_trajectory_maneuvers(points, pickup=pickup)
    assert len(maneuvers) == 1
    m0 = maneuvers[0]
    assert m0["action"] == "wrong_direction"
    assert m0["is_anomaly"] is True
    assert m0["policy_tag"] == "Điều 16.1 (ERR-03)"
    assert "ngược hướng" in m0["instruction"]
    assert round(m0["distance_m"], 1) == 456.3
    assert m0["duration_s"] == 30
    assert round(m0["avg_speed_kmh"], 1) == 29.2
    assert round(m0["max_speed_kmh"], 1) == 30.6


@pytest.mark.asyncio
async def test_jev_assessment_agent_detects_wrong_direction_err03():
    """Verify JevAssessmentAgent automatically classifies wrong direction trajectory as ERR-03."""
    t0 = datetime(2026, 9, 24, 8, 0, 0, tzinfo=UTC)
    pickup = [105.8600, 21.0350]
    points = [
        {
            "longitude": 105.8500,
            "latitude": 21.0250,
            "speed_mps": 8.0,
            "bearing_deg": 225.0,
            "occurred_at": t0.isoformat(),
        },
        {
            "longitude": 105.8490,
            "latitude": 21.0240,
            "speed_mps": 8.5,
            "bearing_deg": 225.0,
            "occurred_at": (t0 + timedelta(seconds=10)).isoformat(),
        },
        {
            "longitude": 105.8480,
            "latitude": 21.0230,
            "speed_mps": 8.0,
            "bearing_deg": 225.0,
            "occurred_at": (t0 + timedelta(seconds=20)).isoformat(),
        },
        {
            "longitude": 105.8470,
            "latitude": 21.0220,
            "speed_mps": 8.0,
            "bearing_deg": 225.0,
            "occurred_at": (t0 + timedelta(seconds=30)).isoformat(),
        },
    ]
    agent = JevAssessmentAgent()
    # Scenario not explicitly set to route_deviation, kinematic stream alone drives detection
    event_data = {
        "scenario": "normal_trip",
        "pickup": pickup,
        "dropoff": [105.8700, 21.0400],
        "points": points,
    }
    assessment = await agent.assess(event_data)
    assert assessment["category"] == "ERR-03"
    assert assessment["priority_tier"] == 1
    assert assessment["priority_label"] == "P1"
    assert assessment["priority_score"] == 88
    assert assessment["confidence"] == 0.88
    assert "wrong_direction_divergence_from_pickup" in assessment["reason_codes"]
    assert "Điều 16.1" in assessment["forensic_brief"]


def test_parse_trajectory_maneuvers_left_turn():
    """Verify trajectory turn detection correctly identifies left turn maneuvers."""
    t0 = datetime(2026, 9, 24, 8, 0, 0, tzinfo=UTC)
    points = [
        # Heading North (~0 deg)
        {
            "longitude": 105.8500,
            "latitude": 21.0200,
            "speed_mps": 8.0,
            "bearing_deg": 0.0,
            "occurred_at": t0.isoformat(),
        },
        {
            "longitude": 105.8500,
            "latitude": 21.0210,
            "speed_mps": 8.0,
            "bearing_deg": 0.0,
            "occurred_at": (t0 + timedelta(seconds=10)).isoformat(),
        },
        # Turn Left to West (~270 deg / -90 deg delta)
        {
            "longitude": 105.8490,
            "latitude": 21.0210,
            "speed_mps": 5.0,
            "bearing_deg": 270.0,
            "occurred_at": (t0 + timedelta(seconds=15)).isoformat(),
        },
        # Continue West
        {
            "longitude": 105.8480,
            "latitude": 21.0210,
            "speed_mps": 7.5,
            "bearing_deg": 270.0,
            "occurred_at": (t0 + timedelta(seconds=25)).isoformat(),
        },
    ]

    maneuvers = parse_trajectory_maneuvers(points)
    left_turns = [m for m in maneuvers if m["action"] == "turn_left"]
    assert len(left_turns) == 1
    assert "Rẽ trái" in left_turns[0]["instruction"]
    assert left_turns[0]["duration_s"] > 0
    assert left_turns[0]["distance_m"] > 0


def test_parse_trajectory_maneuvers_malformed_input():
    """Verify parser gracefully handles malformed telemetry without crashing or corrupting output."""
    # 1. Empty points list
    assert parse_trajectory_maneuvers([]) == []

    # 2. Points with missing/None coordinates
    malformed_points = [
        {"speed_mps": 5.0, "occurred_at": "2026-09-24T08:00:00Z"},
        {"latitude": None, "longitude": None, "speed_mps": 5.0},
        {"latitude": "not-a-float", "longitude": 105.85, "speed_mps": 5.0},
        {"latitude": 95.0, "longitude": 105.85, "speed_mps": 5.0},  # out-of-range lat
        {"latitude": 21.02, "longitude": 200.0, "speed_mps": 5.0},  # out-of-range lon
        {"latitude": float("nan"), "longitude": 105.85, "speed_mps": 5.0},
        {"latitude": 21.02, "longitude": float("inf"), "speed_mps": 5.0},
    ]
    assert parse_trajectory_maneuvers(malformed_points) == []

    # 3. Points with invalid/string speeds
    t0 = datetime(2026, 9, 24, 8, 0, 0, tzinfo=UTC)
    points_bad_speeds = [
        {"latitude": 21.0200, "longitude": 105.8500, "speed_mps": "invalid", "occurred_at": t0.isoformat()},
        {
            "latitude": 21.0210,
            "longitude": 105.8500,
            "speed_mps": None,
            "occurred_at": (t0 + timedelta(seconds=10)).isoformat(),
        },
    ]
    # Should not crash; defaults speed to 0.0 or handles gracefully
    maneuvers = parse_trajectory_maneuvers(points_bad_speeds)
    assert isinstance(maneuvers, list)


def test_parse_trajectory_maneuvers_unavailable_telemetry():
    """Verify behavior when telemetry is unavailable or minimal."""
    # Single point with 0 speed and no stall duration returns empty list (unavailable movement)
    p_single = [{"latitude": 21.0285, "longitude": 105.8542, "speed_mps": 0.0, "occurred_at": "2026-09-24T08:00:00Z"}]
    assert parse_trajectory_maneuvers(p_single, stall_duration_s=0) == []

    # Single point with known stall duration returns single stationary stop
    m_stall = parse_trajectory_maneuvers(p_single, stall_duration_s=200)
    assert len(m_stall) == 1
    assert m_stall[0]["action"] == "stop"
    assert m_stall[0]["duration_s"] == 200


def test_parse_trajectory_maneuvers_zero_fabricated_points():
    """Verify every coordinate in returned maneuvers strictly originates from the input stream (zero hallucination)."""
    t0 = datetime(2026, 9, 24, 8, 0, 0, tzinfo=UTC)
    input_coords = [
        [105.8500, 21.0200],
        [105.8500, 21.0210],
        [105.8500, 21.0220],
        [105.8510, 21.0220],
        [105.8520, 21.0220],
    ]
    points = [
        {
            "longitude": c[0],
            "latitude": c[1],
            "speed_mps": 7.0,
            "occurred_at": (t0 + timedelta(seconds=i * 10)).isoformat(),
        }
        for i, c in enumerate(input_coords)
    ]

    maneuvers = parse_trajectory_maneuvers(points)
    input_coord_set = {tuple(round(x, 5) for x in c) for c in input_coords}

    for m in maneuvers:
        for coord in m["coordinates"]:
            coord_tuple = tuple(round(x, 5) for x in coord)
            assert coord_tuple in input_coord_set, f"Fabricated coordinate detected: {coord_tuple}"

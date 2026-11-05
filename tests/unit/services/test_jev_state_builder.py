"""Comprehensive unit tests for Jev state builder (Issue #496).

Tests cover:
1. Hand-computed fixtures for implied speed, smoothing, percentiles, disagreement
2. Teleport jump detection (count, max speed, threshold at 200 km/h)
3. Time-windowed metrics (60s default windows: moving vs stationary, speed, heading change, pickup dist)
4. Whole-phase metrics (SSD, DAVI, progress ratio, detour ratio with road route vs chord estimate)
5. Risk band threshold edge cases and {value, unit, band, formula} structure
6. Natural-language rendering snapshot in Vietnamese with human units
7. Cleaning (no PII keys, no generator metadata, no raw points)
8. Variant selection ('baseline' byte-for-byte parity, 'features_numeric', 'features_nl', 'features_both')
9. Token count reduction (features_nl < 40% of baseline)
10. Mapper parity between benchmark run_10k and production telemetry_queue_worker
"""

import json
import math
from datetime import UTC, datetime

from src.services.jev_assessment_service import JevAssessmentInput
from src.services.jev_state_builder import (
    build_jev_state,
    classify_metric_risk_band,
    clean_state_payload,
    compute_time_windowed_metrics,
    compute_whole_phase_metrics,
    derive_kinematics,
    map_telemetry_event_to_jev_input,
    render_natural_language_summary,
)

# ---------------------------------------------------------------------------
# Hand-computed Kinematics Fixtures
# ---------------------------------------------------------------------------


def test_derived_kinematics_hand_computed() -> None:
    """Verify per-step implied speed = haversine / dt (km/h), smoothing, p50, p95, disagreement."""
    # 3 points moving eastward along equator: lat=0.0
    # Equator: 1 degree lon ~ 111,319.49 m
    # lon 0.0 -> 0.001: approx 111.3195 m
    # dt = 10s -> implied speed ~ 11.132 m/s = 40.075 km/h
    points = [
        {"occurred_at": "2026-10-17T10:00:00Z", "longitude": 0.0, "latitude": 0.0, "speed_mps": 10.0},
        {"occurred_at": "2026-10-17T10:00:10Z", "longitude": 0.001, "latitude": 0.0, "speed_mps": 11.0},
        {"occurred_at": "2026-10-17T10:00:20Z", "longitude": 0.002, "latitude": 0.0, "speed_mps": 12.0},
    ]

    kin = derive_kinematics(points)
    assert kin["step_count"] == 2
    assert kin["teleport_jump_count"] == 0
    assert kin["teleport_jump_max_kmh"] == 0.0

    # Implied speed should be ~ 40.08 km/h
    implied = kin["implied_speeds_kmh"]
    assert len(implied) == 2
    assert 40.0 <= implied[0] <= 40.2
    assert 40.0 <= implied[1] <= 40.2

    # Percentiles
    assert 40.0 <= kin["speed_p50_kmh"] <= 40.2
    assert 40.0 <= kin["speed_p95_kmh"] <= 40.2

    # Reported vs implied speed disagreement
    # reported: [10.0*3.6=36.0, 11.0*3.6=39.6, 12.0*3.6=43.2]
    # step 0: reported ~39.6 vs implied ~40.08 -> abs diff ~0.48 km/h
    assert "mean_disagreement_kmh" in kin
    assert "max_disagreement_kmh" in kin
    assert kin["max_disagreement_kmh"] < 10.0


def test_teleport_jump_detection() -> None:
    """Verify teleport jumps (>200 km/h) detection, count, and max jump speed."""
    # Point 0 to Point 1: 10s, moves 1000m -> 100 m/s = 360 km/h (teleport jump!)
    # Point 1 to Point 2: 10s, moves 50m -> 5 m/s = 18 km/h (normal)
    # Point 2 to Point 3: 5s, moves 400m -> 80 m/s = 288 km/h (teleport jump!)
    t0 = datetime(2026, 10, 17, 10, 0, 0, tzinfo=UTC)
    # At equator: 1 deg lat = 110,574 m. 1000m ~ 0.0090437 deg lat
    lat0 = 0.0
    lat1 = 1000.0 / 110574.0
    lat2 = lat1 + (50.0 / 110574.0)
    lat3 = lat2 + (400.0 / 110574.0)

    points = [
        {"occurred_at": t0.isoformat(), "longitude": 0.0, "latitude": lat0},
        {"occurred_at": datetime(2026, 10, 17, 10, 0, 10, tzinfo=UTC).isoformat(), "longitude": 0.0, "latitude": lat1},
        {"occurred_at": datetime(2026, 10, 17, 10, 0, 20, tzinfo=UTC).isoformat(), "longitude": 0.0, "latitude": lat2},
        {"occurred_at": datetime(2026, 10, 17, 10, 0, 25, tzinfo=UTC).isoformat(), "longitude": 0.0, "latitude": lat3},
    ]

    kin = derive_kinematics(points)
    assert kin["teleport_jump_count"] == 2
    assert kin["teleport_jump_max_kmh"] > 350.0


def test_teleport_jump_threshold_edge() -> None:
    """Implied speed exactly <= 200 km/h does not count as teleport jump, >200 km/h does."""
    # Earth radius ~ 6371000m -> 1 deg lat = pi*6371000/180 = 111194.9266m
    # 190 km/h in 10s = 527.78m -> 527.78 / 111194.93 deg
    # 210 km/h in 10s = 583.33m -> 583.33 / 111194.93 deg
    deg_per_m = 180.0 / (math.pi * 6371000.0)
    lat_190 = (190.0 / 3.6 * 10.0) * deg_per_m
    lat_210 = (210.0 / 3.6 * 10.0) * deg_per_m

    p_below = [
        {"occurred_at": "2026-10-17T10:00:00Z", "longitude": 0.0, "latitude": 0.0},
        {"occurred_at": "2026-10-17T10:00:10Z", "longitude": 0.0, "latitude": lat_190},
    ]
    kin_below = derive_kinematics(p_below)
    assert kin_below["teleport_jump_count"] == 0

    p_above = [
        {"occurred_at": "2026-10-17T10:00:00Z", "longitude": 0.0, "latitude": 0.0},
        {"occurred_at": "2026-10-17T10:00:10Z", "longitude": 0.0, "latitude": lat_210},
    ]
    kin_above = derive_kinematics(p_above)
    assert kin_above["teleport_jump_count"] == 1
    assert kin_above["teleport_jump_max_kmh"] > 200.0


# ---------------------------------------------------------------------------
# Time-Windowed Metrics Fixtures
# ---------------------------------------------------------------------------


def test_time_windowed_metrics() -> None:
    """Verify 60s windows: distance-to-pickup change, moving vs stationary, median implied speed, heading change."""
    pickup = (105.8542, 21.0300)  # lon, lat
    # 3 windows (180s total):
    # Window 0 (0-60s): moving toward pickup
    # Window 1 (60-120s): stationary (speed=0)
    # Window 2 (120-180s): moving away from pickup
    pts = []
    base_t = datetime(2026, 10, 17, 10, 0, 0, tzinfo=UTC)
    # 0-60s (points at 0s, 20s, 40s, 60s): lat moves 21.0200 -> 21.0250 (closer to 21.0300)
    for i, t in enumerate([0, 20, 40, 60]):
        pt_time = datetime.fromtimestamp(base_t.timestamp() + t, tz=UTC)
        pts.append(
            {
                "occurred_at": pt_time.isoformat(),
                "longitude": 105.8542,
                "latitude": 21.0200 + i * 0.0015,
                "speed_mps": 8.0 if i > 0 else 0.0,
            }
        )
    # 60-120s (points at 80s, 100s, 120s): stationary at lat=21.0245
    for t in [80, 100, 120]:
        pt_time = datetime.fromtimestamp(base_t.timestamp() + t, tz=UTC)
        pts.append(
            {
                "occurred_at": pt_time.isoformat(),
                "longitude": 105.8542,
                "latitude": 21.0245,
                "speed_mps": 0.0,
            }
        )
    # 120-180s (points at 140s, 160s, 180s): moving southward away from pickup (lat decreasing)
    for i, t in enumerate([140, 160, 180], start=1):
        pt_time = datetime.fromtimestamp(base_t.timestamp() + t, tz=UTC)
        pts.append(
            {
                "occurred_at": pt_time.isoformat(),
                "longitude": 105.8542,
                "latitude": 21.0245 - i * 0.002,
                "speed_mps": 10.0,
            }
        )

    windows = compute_time_windowed_metrics(pts, pickup=pickup, window_size_s=60.0)
    assert len(windows) >= 3

    # Window 0: moved closer (distance to pickup decreased -> distance_to_pickup_change_m is negative)
    w0 = windows[0]
    assert w0["window_index"] == 0
    assert w0["start_s"] == 0.0
    assert w0["end_s"] == 60.0
    assert w0["distance_to_pickup_change_m"] < 0
    assert w0["moving_seconds"] > 0

    # Window 1: stationary
    w1 = windows[1]
    assert w1["window_index"] == 1
    assert w1["stationary_seconds"] >= 40.0
    assert w1["median_implied_speed_kmh"] < 1.0

    # Window 2: moved away (distance to pickup increased -> distance_to_pickup_change_m is positive)
    w2 = windows[2]
    assert w2["window_index"] == 2
    assert w2["distance_to_pickup_change_m"] > 0
    assert w2["moving_seconds"] > 0


# ---------------------------------------------------------------------------
# Whole-Phase Metrics Fixtures
# ---------------------------------------------------------------------------


def test_whole_phase_metrics() -> None:
    """Verify approach SSD, DAVI, progress ratio, detour ratio (road route vs straight chord x 1.3)."""
    pickup = (105.8542, 21.0300)
    dropoff = (105.8642, 21.0400)

    # Path starting at (105.8542, 21.0200), ending at (105.8542, 21.0280)
    pts = [
        {"occurred_at": "2026-10-17T10:00:00Z", "longitude": 105.8542, "latitude": 21.0200},
        {"occurred_at": "2026-10-17T10:01:00Z", "longitude": 105.8542, "latitude": 21.0240},
        {"occurred_at": "2026-10-17T10:02:00Z", "longitude": 105.8542, "latitude": 21.0280},
    ]

    # Test with real road route in planned_route
    bundle_road = {
        "planned_route": {"distance_m": 1200.0, "is_estimated": False},
        "pickup": list(pickup),
        "dropoff": list(dropoff),
    }
    metrics_road = compute_whole_phase_metrics(pts, bundle_road, pickup=pickup, dropoff=dropoff)
    assert metrics_road["detour_ratio"]["value"] is not None
    assert not metrics_road["detour_ratio"]["is_estimated"]
    assert metrics_road["progress_ratio"]["value"] is not None
    # Progress ratio should be positive since car moved closer to pickup
    assert metrics_road["progress_ratio"]["value"] > 0.0

    # Test with no planned route: fallback to straight chord x 1.3
    bundle_no_route = {
        "pickup": list(pickup),
        "dropoff": list(dropoff),
    }
    metrics_chord = compute_whole_phase_metrics(pts, bundle_no_route, pickup=pickup, dropoff=dropoff)
    assert metrics_chord["detour_ratio"]["is_estimated"] is True
    assert metrics_chord["detour_ratio"]["value"] > 0.0


# ---------------------------------------------------------------------------
# Risk Bands Edge Thresholds
# ---------------------------------------------------------------------------


def test_risk_bands_threshold_edges() -> None:
    """Verify documented thresholds at edges:
    - detour ratio <=1.15 normal, 1.15-1.35 elevated, >1.35 high
    - approach SSD <90 s normal, 90-179 elevated, >=180 high
    - DAVI >0.3 normal, -0.2..0.3 elevated, < -0.2 high
    - teleport jump: none normal, implied 120-200 km/h elevated, >200 km/h or mock high
    Each metric carries {value, unit, band, formula}.
    """
    # Detour ratio
    assert classify_metric_risk_band("detour_ratio", 1.00)["band"] == "normal"
    assert classify_metric_risk_band("detour_ratio", 1.15)["band"] == "normal"
    assert classify_metric_risk_band("detour_ratio", 1.16)["band"] == "elevated"
    assert classify_metric_risk_band("detour_ratio", 1.35)["band"] == "elevated"
    assert classify_metric_risk_band("detour_ratio", 1.36)["band"] == "high"

    # Approach SSD
    assert classify_metric_risk_band("approach_ssd", 0.0)["band"] == "normal"
    assert classify_metric_risk_band("approach_ssd", 89.9)["band"] == "normal"
    assert classify_metric_risk_band("approach_ssd", 90.0)["band"] == "elevated"
    assert classify_metric_risk_band("approach_ssd", 179.9)["band"] == "elevated"
    assert classify_metric_risk_band("approach_ssd", 180.0)["band"] == "high"
    assert classify_metric_risk_band("approach_ssd", 300.0)["band"] == "high"

    # DAVI
    assert classify_metric_risk_band("davi", 0.8)["band"] == "normal"
    assert classify_metric_risk_band("davi", 0.31)["band"] == "normal"
    assert classify_metric_risk_band("davi", 0.30)["band"] == "elevated"
    assert classify_metric_risk_band("davi", 0.0)["band"] == "elevated"
    assert classify_metric_risk_band("davi", -0.20)["band"] == "elevated"
    assert classify_metric_risk_band("davi", -0.21)["band"] == "high"
    assert classify_metric_risk_band("davi", -0.9)["band"] == "high"

    # Teleport jump / mock
    res_normal = classify_metric_risk_band("teleport_jump", {"count": 0, "max_speed_kmh": 60.0, "mock": False})
    assert res_normal["band"] == "normal"

    res_elevated = classify_metric_risk_band("teleport_jump", {"count": 0, "max_speed_kmh": 150.0, "mock": False})
    assert res_elevated["band"] == "elevated"

    res_high_speed = classify_metric_risk_band("teleport_jump", {"count": 1, "max_speed_kmh": 250.0, "mock": False})
    assert res_high_speed["band"] == "high"

    res_high_mock = classify_metric_risk_band("teleport_jump", {"count": 0, "max_speed_kmh": 30.0, "mock": True})
    assert res_high_mock["band"] == "high"

    # Structure check: {value, unit, band, formula}
    for item in [res_normal, res_elevated, res_high_speed, res_high_mock]:
        assert "value" in item
        assert "unit" in item
        assert "band" in item
        assert "formula" in item


# ---------------------------------------------------------------------------
# Natural Language Rendering Snapshot
# ---------------------------------------------------------------------------


def test_natural_language_rendering_snapshot() -> None:
    """Verify Vietnamese sentences per window and per metric, rounded human units, and summary."""
    windows = [
        {
            "window_index": 0,
            "start_s": 0.0,
            "end_s": 180.0,
            "distance_to_pickup_change_m": 370.0,
            "moving_seconds": 120.0,
            "stationary_seconds": 60.0,
            "median_implied_speed_kmh": 22.5,
            "heading_change_deg": 45.0,
        }
    ]
    metrics = {
        "approach_ssd": {"value": 190.0, "unit": "s", "band": "high", "formula": "longest_stationary_chain"},
        "detour_ratio": {"value": 1.42, "unit": "ratio", "band": "high", "formula": "actual_path / planned_route"},
        "davi": {"value": -0.59, "unit": "ratio", "band": "high", "formula": "weighted_cosine"},
        "teleport_jump": {"value": 0, "unit": "count", "band": "normal", "formula": "speed_over_200"},
    }

    nl = render_natural_language_summary(windows, metrics)
    assert "windows_sentences" in nl
    assert "metrics_sentences" in nl
    assert "summary_paragraph" in nl

    # Check that sentences are in Vietnamese and use human units
    w_text = " ".join(nl["windows_sentences"])
    assert "phút" in w_text or "giây" in w_text or "m" in w_text
    assert "370" in w_text or "DAVI" in w_text or "ra xa" in w_text

    summary = nl["summary_paragraph"]
    assert len(summary) > 20
    assert "rủi ro cao" in summary or "vi phạm" in summary or "cảnh báo" in summary


# ---------------------------------------------------------------------------
# Cleaning: Drop PII, Generator Metadata & Raw Points
# ---------------------------------------------------------------------------


def test_clean_state_payload() -> None:
    """Verify dropping avatar_url, display_name, ids, organization_id, external_ref,
    birth_date, raw points, generator metadata while keeping aggregates, conversation, reports."""
    dirty_state = {
        "driver": {
            "id": "018f2f4e-1000-7000-8000-000000000001",
            "driver_id": "drv_123",
            "display_name": "Nguyen Van A",
            "avatar_url": "https://img.example.com/avatar.png",
            "birth_date": "1990-01-01",
            "phone": "+84901234567",
            "email": "driver@example.com",
            "tenure_months": 24,
            "rating": 4.85,
            "cancellation_rate": 0.03,
            "prior_sanctions_count": 0,
        },
        "driver_analytics": {
            "driver_id": "drv_123",
            "total_trips": 1500,
            "completion_rate": 0.97,
            "prior_sanctions_count": 0,
        },
        "trip_conversation": [
            {"sender": "passenger", "text": "Toi dang o sanh toa nha"},
            {"sender": "driver", "text": "Vang toi den ngay"},
        ],
        "customer_reports": "Khach bao tai xe di sai duong",
        "telemetry": {
            "points": [
                {"longitude": 105.85, "latitude": 21.02, "speed_mps": 5.0},
                {"longitude": 105.86, "latitude": 21.03, "speed_mps": 6.0},
            ],
            "stationary_duration_s": 30,
            "max_speed_kmh": 45.0,
            "mock_location_reported": False,
        },
        "trip_data": {
            "trip_id": "trip_abc_123",
            "assignment_id": "asg_xyz_789",
            "organization_id": "018f2f4e-0000-7000-8000-000000000001",
            "external_ref": "ext_999",
            "lifecycle_state": "completed",
            "cancellation_reason": None,
            "cancellation_actor": None,
        },
        "scenario": "test_scenario_123",
        "generator_version": "v1.0",
        "label": "no_violation",
        "label_provenance": "synthetic",
    }

    cleaned = clean_state_payload(dirty_state)

    # Check dropped top-level metadata
    assert "scenario" not in cleaned
    assert "generator_version" not in cleaned
    assert "label" not in cleaned
    assert "label_provenance" not in cleaned

    # Check dropped PII in driver
    drv = cleaned.get("driver", {})
    assert "avatar_url" not in drv
    assert "display_name" not in drv
    assert "birth_date" not in drv
    assert "phone" not in drv
    assert "email" not in drv
    assert "id" not in drv
    assert "driver_id" not in drv
    # Retained driver aggregates
    assert drv.get("tenure_months") == 24
    assert drv.get("rating") == 4.85
    assert drv.get("cancellation_rate") == 0.03

    # Check dropped raw telemetry points
    telem = cleaned.get("telemetry", {})
    assert "points" not in telem
    assert telem.get("stationary_duration_s") == 30
    assert telem.get("max_speed_kmh") == 45.0

    # Check dropped IDs in trip_data
    trip = cleaned.get("trip_data", {})
    assert "trip_id" not in trip
    assert "assignment_id" not in trip
    assert "organization_id" not in trip
    assert "external_ref" not in trip
    assert trip.get("lifecycle_state") == "completed"

    # Retained conversations and reports
    assert cleaned.get("trip_conversation") == dirty_state["trip_conversation"]
    assert cleaned.get("customer_reports") == dirty_state["customer_reports"]


# ---------------------------------------------------------------------------
# Variants & Parity
# ---------------------------------------------------------------------------


def test_build_jev_state_baseline_regression_parity() -> None:
    """Variant 'baseline' must be byte-for-byte identical to the raw production state payload."""
    inp = JevAssessmentInput(
        driver={"id": "drv_1", "display_name": "Tài xế", "avatar_url": "http://img.jpg"},
        driver_analytics={"total_trips": 100},
        trip_conversation=[{"sender": "passenger", "text": "Hello"}],
        driver_reason_and_agent_conversation="Ly do ca nhan",
        customer_reports="Khieu nai",
        telemetry={"points": [{"lat": 21.0, "lon": 105.0}], "stationary_duration_s": 10},
        trip_data={"trip_id": "trip_1", "status": "completed"},
    )

    baseline_state = build_jev_state(inp, variant="baseline")
    assert baseline_state == {
        "driver": inp.driver,
        "driver_analytics": inp.driver_analytics,
        "trip_conversation": inp.trip_conversation,
        "driver_reason_and_agent_conversation": inp.driver_reason_and_agent_conversation,
        "customer_reports": inp.customer_reports,
        "telemetry": inp.telemetry,
        "trip_data": inp.trip_data,
    }


def test_build_jev_state_features_variants() -> None:
    """Verify 'features_numeric', 'features_nl', and 'features_both' output shapes."""
    raw_bundle = {
        "driver": {"id": "drv_1", "display_name": "Tài xế", "rating": 4.9},
        "driver_analytics": {"total_trips": 100},
        "conversation": [{"sender": "passenger", "text": "Alo"}],
        "customer_report": "Khieu nai",
        "telemetry": [
            {"occurred_at": "2026-10-17T10:00:00Z", "longitude": 105.85, "latitude": 21.02, "speed_mps": 0.0},
            {"occurred_at": "2026-10-17T10:01:00Z", "longitude": 105.85, "latitude": 21.025, "speed_mps": 5.0},
        ],
        "pickup": [105.85, 21.03],
        "dropoff": [105.86, 21.04],
        "trip": {"status": "completed"},
        "assignment": {"driver_id": "drv_1"},
    }

    # Numeric variant
    num_state = build_jev_state(raw_bundle, variant="features_numeric")
    assert "points" not in num_state.get("telemetry", {})
    assert "kinematics" in num_state["telemetry"]
    assert "risk_bands" in num_state["telemetry"]
    assert "narrative" not in num_state["telemetry"]

    # NL variant
    nl_state = build_jev_state(raw_bundle, variant="features_nl")
    assert "points" not in nl_state.get("telemetry", {})
    assert "narrative" in nl_state["telemetry"]
    assert "kinematics" not in nl_state["telemetry"]

    # Both variant
    both_state = build_jev_state(raw_bundle, variant="features_both")
    assert "points" not in both_state.get("telemetry", {})
    assert "kinematics" in both_state["telemetry"]
    assert "risk_bands" in both_state["telemetry"]
    assert "narrative" in both_state["telemetry"]


def test_token_count_features_nl_below_40_percent_of_baseline() -> None:
    """Token count of features_nl must be < 40% of baseline on a fixture trip."""
    # Build fixture trip with 60 raw points (~15 min trip at 15s interval)
    pts = []
    base_time = datetime(2026, 10, 17, 10, 0, 0, tzinfo=UTC)
    for i in range(60):
        t = datetime.fromtimestamp(base_time.timestamp() + i * 15, tz=UTC)
        pts.append(
            {
                "occurred_at": t.isoformat(),
                "longitude": 105.8500 + i * 0.0002,
                "latitude": 21.0200 + i * 0.0002,
                "speed_mps": 8.5,
                "heading": 45.0,
                "accuracy_m": 5.0,
                "mock_location_reported": False,
            }
        )

    fixture_bundle = {
        "driver": {
            "id": "018f2f4e-3000-7000-8000-000000000001",
            "display_name": "Tài xế Nguyễn Văn B",
            "avatar_url": "https://img.greensm.vn/drivers/avatar_large_12345.png",
            "rating": 4.92,
            "tenure_months": 18,
            "prior_sanctions_count": 0,
        },
        "driver_analytics": {"total_trips": 820, "cancellation_rate": 0.02},
        "conversation": [
            {"sender": "passenger", "text": "Em đứng ở cửa số 3 rồi anh ơi"},
            {"sender": "driver", "text": "Vâng xe em đang tới, 2 phút nữa đến ạ"},
        ],
        "customer_report": None,
        "telemetry": pts,
        "pickup": [105.8500, 21.0200],
        "dropoff": [105.8620, 21.0320],
        "trip": {"status": "completed"},
        "assignment": {"id": "asg_999"},
    }

    baseline_state = build_jev_state(fixture_bundle, variant="baseline")
    nl_state = build_jev_state(fixture_bundle, variant="features_nl")

    baseline_json = json.dumps(baseline_state, ensure_ascii=False)
    nl_json = json.dumps(nl_state, ensure_ascii=False)

    baseline_len = len(baseline_json)
    nl_len = len(nl_json)

    ratio = nl_len / baseline_len
    # Token count / JSON size must be < 40% of baseline
    assert ratio < 0.40, f"Expected NL ratio < 0.40, got {ratio:.3f} (baseline={baseline_len}, nl={nl_len})"


def test_shared_mapper_parity() -> None:
    """Verify that map_telemetry_event_to_jev_input produces identical output whether called
    via run_10k bundle_to_input or telemetry_queue_worker."""
    from scripts.benchmark.run_10k import bundle_to_input

    bundle = {
        "trip_id": "tr_1",
        "assignment_id": "asg_1",
        "trip": {"status": "completed", "cancellation_reason": "test"},
        "assignment": {"cancellation_actor": "driver", "arrived_at": "2026-10-17T10:05:00Z"},
        "driver_profile": {"name": "Test Driver", "rating": 4.8},
        "driver_analytics": {"total_trips": 50},
        "conversation": [{"sender": "driver", "text": "hi"}],
        "customer_report": "detour complaint",
        "pickup": [105.85, 21.02],
        "dropoff": [105.86, 21.03],
        "telemetry": [
            {"occurred_at": "2026-10-17T10:00:00Z", "longitude": 105.85, "latitude": 21.02, "speed_mps": 0.0},
            {"occurred_at": "2026-10-17T10:01:00Z", "longitude": 105.852, "latitude": 21.022, "speed_mps": 6.0},
        ],
    }

    inp_from_run_10k, points_run_10k, trip_data_run_10k = bundle_to_input(bundle)
    inp_from_shared = map_telemetry_event_to_jev_input(bundle)

    assert inp_from_run_10k.telemetry["maneuvers"] == inp_from_shared.telemetry["maneuvers"]
    assert inp_from_run_10k.telemetry["stationary_duration_s"] == inp_from_shared.telemetry["stationary_duration_s"]
    assert inp_from_run_10k.telemetry["mock_location_reported"] == inp_from_shared.telemetry["mock_location_reported"]
    assert inp_from_run_10k.trip_data == inp_from_shared.trip_data


# ---------------------------------------------------------------------------
# TDD Tests: Review Fixes (Label Leak, Per-Phase Detour, Missing Bands)
# ---------------------------------------------------------------------------


def test_leak_keys_absent_from_every_build_jev_state_variant() -> None:
    """Verify that generator metadata, label leaks, ground truth and simulation keys
    are absent from build_jev_state output across ALL variants."""
    bundle_with_leaks = {
        "driver_profile": {
            "name": "Driver",
            "fraud_propensity": 0.85,
            "profile_provenance": {"origin": "generator", "fraud_propensity": 0.85},
            "nested": {"simulation_id": "sim_123", "expected_category": "ERR-02"},
        },
        "driver_analytics": {
            "total_trips": 100,
            "fraud_propensity": 0.1,
            "profile_provenance": {"source": "leak"},
        },
        "conversation": [{"role": "passenger", "text": "hello", "simulation_x": 1}],
        "driver_objection": {"dispute_text": "I followed route", "expected_outcome": "accept"},
        "customer_report": {"complaint": "wrong way", "anomaly_type": "detour"},
        "label": "ERR-02",
        "scenario": "ghost_ride",
        "generation_audit": {"engine": "v2"},
        "measured_features": {"davi": 0.1, "approach_ssd_s": 200},
        "telemetry": [
            {
                "occurred_at": "2026-10-17T10:00:00Z",
                "longitude": 105.85,
                "latitude": 21.02,
                "speed_mps": 0.0,
                "anomaly_score": 0.9,
            },
            {
                "occurred_at": "2026-10-17T10:01:00Z",
                "longitude": 105.852,
                "latitude": 21.022,
                "speed_mps": 6.0,
                "expected_speed": 30,
            },
        ],
        "trip": {"status": "completed"},
        "assignment": {"id": "asg_1", "started_at": "2026-10-17T10:00:30Z"},
        "pickup": [105.85, 21.02],
        "dropoff": [105.86, 21.03],
    }

    variants = ["evidence_classref", "evidence", "baseline", "features_numeric", "features_nl", "features_both"]
    prohibited_keys = [
        "fraud_propensity",
        "profile_provenance",
        "label_provenance",
        "generation_audit",
        "measured_features",
        "expected_category",
        "expected_outcome",
        "expected_speed",
        "simulation_id",
        "simulation_x",
        "anomaly_score",
        "anomaly_type",
    ]

    for variant in variants:
        state = build_jev_state(bundle_with_leaks, variant=variant)
        json_str = json.dumps(state)
        for key in prohibited_keys:
            assert key not in json_str, f"Leak key '{key}' found in variant '{variant}': {json_str}"


def test_per_phase_detour_ratio_fixtures() -> None:
    """Verify separate detour ratios for approach (before pickup) and in-trip (after started_at),
    is_estimated flag when not a real road route, and null when a phase has no points."""
    pickup = (105.8500, 21.0200)
    dropoff = (105.8600, 21.0300)

    # 1. Both phases present
    pts_both = [
        {"occurred_at": "2026-10-17T10:00:00Z", "longitude": 105.8450, "latitude": 21.0150},  # approach
        {"occurred_at": "2026-10-17T10:01:00Z", "longitude": 105.8480, "latitude": 21.0180},  # approach
        {"occurred_at": "2026-10-17T10:02:00Z", "longitude": 105.8500, "latitude": 21.0200},  # at pickup / started_at
        {"occurred_at": "2026-10-17T10:03:00Z", "longitude": 105.8550, "latitude": 21.0250},  # in-trip
        {"occurred_at": "2026-10-17T10:04:00Z", "longitude": 105.8600, "latitude": 21.0300},  # in-trip
    ]
    bundle_both = {
        "started_at": "2026-10-17T10:02:00Z",
        "pickup": list(pickup),
        "dropoff": list(dropoff),
        "planned_route": {"distance_m": 1500.0, "is_estimated": False},
    }
    metrics = compute_whole_phase_metrics(pts_both, bundle_both, pickup=pickup, dropoff=dropoff)
    detour = metrics["detour_ratio"]

    # Must contain per-phase ratios
    assert "approach" in detour
    assert "in_trip" in detour
    assert detour["approach"]["value"] is not None
    assert detour["approach"]["is_estimated"] is True  # chord start->pickup
    assert detour["in_trip"]["value"] is not None
    assert detour["in_trip"]["is_estimated"] is False  # real road route

    # 2. Approach has no points (all points after started_at)
    pts_no_approach = [
        {"occurred_at": "2026-10-17T10:03:00Z", "longitude": 105.8550, "latitude": 21.0250},
        {"occurred_at": "2026-10-17T10:04:00Z", "longitude": 105.8600, "latitude": 21.0300},
    ]
    bundle_no_approach = {
        "started_at": "2026-10-17T10:02:00Z",
        "pickup": list(pickup),
        "dropoff": list(dropoff),
        "planned_route": {"distance_m": 1500.0, "is_estimated": False},
    }
    metrics_no_app = compute_whole_phase_metrics(pts_no_approach, bundle_no_approach, pickup=pickup, dropoff=dropoff)
    assert metrics_no_app["detour_ratio"]["approach"]["value"] is None  # null when phase has no points
    assert metrics_no_app["detour_ratio"]["in_trip"]["value"] is not None

    # 3. In-trip has no points (trip never started / started_at is None)
    pts_no_trip = [
        {"occurred_at": "2026-10-17T10:00:00Z", "longitude": 105.8450, "latitude": 21.0150},
        {"occurred_at": "2026-10-17T10:01:00Z", "longitude": 105.8480, "latitude": 21.0180},
    ]
    bundle_no_trip = {
        "started_at": None,
        "pickup": list(pickup),
        "dropoff": list(dropoff),
    }
    metrics_no_trip = compute_whole_phase_metrics(pts_no_trip, bundle_no_trip, pickup=pickup, dropoff=dropoff)
    assert metrics_no_trip["detour_ratio"]["approach"]["value"] is not None
    assert metrics_no_trip["detour_ratio"]["in_trip"]["value"] is None  # null when phase has no points


def test_missing_values_banded_as_unknown() -> None:
    """Verify that missing values (None) map to 'unknown' band, not 'normal',
    and render as 'không đủ dữ liệu' in Vietnamese natural language."""
    # Classify None values
    davi_res = classify_metric_risk_band("davi", None)
    assert davi_res["band"] == "unknown"
    assert davi_res["value"] is None

    detour_res = classify_metric_risk_band("detour_ratio", None)
    assert detour_res["band"] == "unknown"
    assert detour_res["value"] is None

    ssd_res = classify_metric_risk_band("approach_ssd", None)
    assert ssd_res["band"] == "unknown"
    assert ssd_res["value"] is None

    teleport_res = classify_metric_risk_band("teleport_jump", None)
    assert teleport_res["band"] == "unknown"
    assert teleport_res["value"] is None

    # Natural-language rendering check
    windows = [
        {
            "window_index": 0,
            "start_s": 0.0,
            "end_s": 60.0,
            "distance_to_pickup_change_m": 0.0,
            "moving_seconds": 0.0,
            "stationary_seconds": 60.0,
            "median_implied_speed_kmh": 0.0,
            "heading_change_deg": 0.0,
        }
    ]
    metrics = {
        "approach_ssd": ssd_res,
        "detour_ratio": detour_res,
        "davi": davi_res,
        "teleport_jump": teleport_res,
    }

    nl = render_natural_language_summary(windows, metrics)
    metrics_text = " ".join(nl["metrics_sentences"])
    assert "không đủ dữ liệu" in metrics_text


def test_build_jev_state_default_is_evidence_classref() -> None:
    bundle = {
        "pickup": [105.85, 21.02],
        "dropoff": [105.86, 21.03],
        "telemetry": [
            {"occurred_at": "2026-10-17T10:00:00Z", "longitude": 105.85, "latitude": 21.02, "speed_mps": 0.0},
            {"occurred_at": "2026-10-17T10:01:00Z", "longitude": 105.852, "latitude": 21.022, "speed_mps": 6.0},
        ],
    }
    default_res = build_jev_state(bundle)
    classref_res = build_jev_state(bundle, variant="evidence_classref")
    assert default_res == classref_res
    assert "measurements" in default_res["telemetry"]
    assert "unit" in default_res["telemetry"]["measurements"]["speed_p50"]
    assert "class_medians" in default_res["telemetry"]["measurements"]["speed_p50"]


def test_production_default_state_variant_is_evidence_classref() -> None:
    from src.services.jev_assessment_service import JevAssessmentInput
    from src.services.jev_state_builder import map_telemetry_event_to_jev_input

    inp = JevAssessmentInput()
    assert inp.state_variant == "evidence_classref"

    mapped = map_telemetry_event_to_jev_input({})
    assert mapped.state_variant == "evidence_classref"


def test_selectable_variants_preserved() -> None:
    from src.services.jev_state_builder import map_telemetry_event_to_jev_input

    bundle = {
        "pickup": [105.85, 21.02],
        "dropoff": [105.86, 21.03],
        "telemetry": [
            {"occurred_at": "2026-10-17T10:00:00Z", "longitude": 105.85, "latitude": 21.02, "speed_mps": 0.0},
        ],
    }

    # "evidence" without class medians
    ev_state = build_jev_state(bundle, variant="evidence")
    assert "measurements" in ev_state["telemetry"]
    assert "class_medians" not in ev_state["telemetry"]["measurements"]["speed_p50"]

    # "baseline" preserves raw points
    base_state = build_jev_state(bundle, variant="baseline")
    assert "points" in base_state["telemetry"] or isinstance(base_state["telemetry"], list)

    # mapper supports overrides
    ev_mapped = map_telemetry_event_to_jev_input({"state_variant": "evidence"})
    assert ev_mapped.state_variant == "evidence"

    base_mapped = map_telemetry_event_to_jev_input({"state_variant": "baseline"})
    assert base_mapped.state_variant == "baseline"

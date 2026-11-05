"""Jev State Builder (Issue #496).

Pure functions (no DB, network, or file IO) providing:
1. Derived kinematics from GPS coordinates and timestamps:
   - per-step implied speed = haversine / dt (km/h), smoothed
   - reported-vs-implied speed disagreement metrics
   - teleport jump detection (count and max speed for consecutive implied speed > 200 km/h)
   - speed percentiles (p50, p95)
2. Time-windowed metrics (default 60s windows):
   - distance-to-pickup change
   - moving vs stationary seconds
   - median implied speed
   - heading change
   Whole-phase metrics:
   - approach stationary duration (SSD)
   - DAVI (directional approach vector index)
   - progress ratio = (d_start - d_end) / path_length
   - detour ratio = actual path length / planned route length (road route or chord x 1.3 estimate)
   - max data gap, coverage, mock ratio, guardrail state
3. Risk bands:
   - versioned config table mapping metrics to normal / elevated / high
   - standardized {value, unit, band, formula} structure
4. Natural-language rendering:
   - Vietnamese sentences per window and per metric, summary paragraph
   - human units (m, km, phút, giây, km/h)
5. Cleaning:
   - drop PII (avatar_url, display_name, ids, organization_id, external_ref, birth_date, etc.)
   - drop raw GPS points and generator evaluation metadata
   - preserve driver aggregates, conversations, reports, trip lifecycle
6. Variants:
   - build_jev_state(bundle_or_event, variant) with variant in:
     {"evidence_classref", "evidence", "baseline", "features_numeric", "features_nl", "features_both"}
7. Shared mapper:
   - map_telemetry_event_to_jev_input unifying production and benchmark paths
"""

from __future__ import annotations

import copy
import json
import logging
import math
from pathlib import Path
from typing import Any

from src.services.feature_engineering import _cosine, _planar_vector, compute_feature_window
from src.services.guardrails import evaluate_telemetry_window, extract_position, is_valid_coordinate
from src.services.jev_assessment_service import JevAssessmentInput
from src.services.route_analytics import (
    calculate_bearing_deg,
    haversine_distance_m,
    heading_diff_deg,
    parse_timestamp,
    parse_trajectory_maneuvers,
)

# ---------------------------------------------------------------------------
# Risk Bands Versioned Config Table
# ---------------------------------------------------------------------------

RISK_BANDS_CONFIG_V1: dict[str, dict[str, Any]] = {
    "detour_ratio": {
        "unit": "ratio",
        "formula": "actual_path_length / planned_route_length",
        "normal": "<= 1.15",
        "elevated": "1.15 - 1.35",
        "high": "> 1.35",
    },
    "approach_ssd": {
        "unit": "s",
        "formula": "longest_stationary_chain_seconds_before_pickup",
        "normal": "< 90 s",
        "elevated": "90 - 179 s",
        "high": ">= 180 s",
    },
    "davi": {
        "unit": "ratio",
        "formula": "weighted_cosine_vector_displacement_to_pickup",
        "normal": "> 0.30",
        "elevated": "-0.20 to 0.30",
        "high": "< -0.20",
    },
    "teleport_jump": {
        "unit": "count",
        "formula": "consecutive_implied_speed_over_200_kmh_or_mock",
        "normal": "count == 0 and max_speed < 120 km/h and not mock",
        "elevated": "count == 0 and 120 <= max_speed <= 200 km/h and not mock",
        "high": "count > 0 or max_speed > 200 km/h or mock",
    },
}

PII_KEYS: frozenset[str] = frozenset(
    {
        "avatar_url",
        "display_name",
        "name",
        "first_name",
        "last_name",
        "full_name",
        "email",
        "phone",
        "phone_number",
        "birth_date",
        "dob",
        "external_ref",
        "organization_id",
        "org_id",
        "vehicle_id",
        "license_plate",
        "driver_id",
        "passenger_id",
        "id",
        "assignment_id",
        "trip_id",
        "case_id",
    }
)

GENERATOR_METADATA_KEYS: frozenset[str] = frozenset(
    {
        "scenario",
        "expected_category",
        "intent",
        "simulation_id",
        "generator_version",
        "label",
        "label_provenance",
        "gridlock_subset",
        "measured_features",
    }
)

SCRUB_KEYS: frozenset[str] = frozenset(
    {
        "label",
        "fraud_propensity",
        "profile_provenance",
        "label_provenance",
        "generation_audit",
        "measured_features",
        "scenario",
        "expected_category",
        "expected_guardrail",
        "expected_guardrail_reason",
        "expected_outcome",
        "intent",
        "simulation_id",
        "anomaly_type",
        "anomaly_score",
        "simulation_labels",
    }
)
SCRUB_PREFIXES: tuple[str, ...] = ("expected_", "simulation_", "anomaly_")


def scrub_evaluation_labels(value: Any) -> Any:
    """Recursively scrub evaluation labels, ground truth, and generator metadata at any depth."""
    if isinstance(value, dict):
        return {
            k: scrub_evaluation_labels(v)
            for k, v in value.items()
            if k not in SCRUB_KEYS and not k.startswith(SCRUB_PREFIXES)
        }
    if isinstance(value, (list, tuple)):
        return [scrub_evaluation_labels(v) for v in value]
    return value


def _extract_lon_lat(point: Any) -> tuple[float, float] | None:
    """Extract valid (lon, lat) tuple from a telemetry point, coordinate dict, or list/tuple."""
    if point is None:
        return None

    if isinstance(point, (list, tuple)) and len(point) == 2:
        try:
            c0, c1 = float(point[0]), float(point[1])
            if is_valid_coordinate(c1, c0):  # [lon, lat]
                return c0, c1
            if is_valid_coordinate(c0, c1):  # [lat, lon]
                return c1, c0
        except (ValueError, TypeError):
            pass
        return None

    if not isinstance(point, dict):
        return None

    pos = extract_position(point)
    if pos is not None and len(pos) == 2 and pos[0] is not None and pos[1] is not None:
        try:
            plat, plon = float(pos[0]), float(pos[1])
            if is_valid_coordinate(plat, plon):
                return plon, plat
            if is_valid_coordinate(plon, plat):
                return plat, plon
        except (ValueError, TypeError):
            pass

    # Support lon/lng/longitude and lat/latitude
    lon = point.get("longitude")
    if lon is None:
        lon = point.get("lon")
    if lon is None:
        lon = point.get("lng")

    lat = point.get("latitude")
    if lat is None:
        lat = point.get("lat")

    if lon is not None and lat is not None:
        try:
            flon, flat = float(lon), float(lat)
            if is_valid_coordinate(flat, flon):
                return flon, flat
            if is_valid_coordinate(flon, flat):
                return flat, flon
        except (ValueError, TypeError):
            pass

    coords = point.get("coordinates") or point.get("coords")
    if isinstance(coords, (list, tuple)) and len(coords) == 2:
        try:
            c0, c1 = float(coords[0]), float(coords[1])
            if is_valid_coordinate(c1, c0):
                return c0, c1
            if is_valid_coordinate(c0, c1):
                return c1, c0
        except (ValueError, TypeError):
            pass

    return None


def _to_timestamp_s(occurred_at: Any) -> float | None:
    """Parse timestamp into epoch seconds."""
    if occurred_at is None:
        return None
    if isinstance(occurred_at, (int, float)):
        return float(occurred_at)
    dt = parse_timestamp(occurred_at)
    return dt.timestamp() if dt else None


def _percentile(values: list[float], q: float) -> float | None:
    """Linear interpolated percentile."""
    if not values:
        return None
    ordered = sorted(values)
    pos = (len(ordered) - 1) * q
    lo, hi = math.floor(pos), math.ceil(pos)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (pos - lo)


# ---------------------------------------------------------------------------
# 1. Derived Kinematics
# ---------------------------------------------------------------------------


def derive_kinematics(points: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute derived kinematics from coordinates and timestamps.

    - Per-step implied speed = haversine / dt (km/h) (skip dt <= 0 or missing coords)
    - Smoothed implied speed (rolling 3-step average)
    - Reported vs implied speed disagreement
    - Teleport jumps (consecutive implied speed > 200 km/h: count and max jump)
    - Speed p50 and p95
    """
    valid_points: list[tuple[float, tuple[float, float], float | None]] = []
    for p in points:
        if not isinstance(p, dict):
            continue
        ts_s = _to_timestamp_s(p.get("occurred_at"))
        coords = _extract_lon_lat(p)
        if ts_s is not None and coords is not None:
            rep_sp = p.get("speed_mps")
            rep_kmh = float(rep_sp) * 3.6 if rep_sp is not None and math.isfinite(float(rep_sp)) else None
            valid_points.append((ts_s, coords, rep_kmh))

    # Sort chronologically
    valid_points.sort(key=lambda item: item[0])

    implied_speeds_kmh: list[float] = []
    smoothed_speeds_kmh: list[float] = []
    disagreements_kmh: list[float] = []
    teleport_jump_count = 0
    teleport_jump_max_kmh = 0.0

    for i in range(1, len(valid_points)):
        t_prev, c_prev, rep_prev = valid_points[i - 1]
        t_curr, c_curr, rep_curr = valid_points[i]
        dt = t_curr - t_prev
        if dt <= 0:
            continue
        dist_m = haversine_distance_m(c_prev, c_curr)
        speed_kmh = (dist_m / dt) * 3.6
        implied_speeds_kmh.append(speed_kmh)

        # Teleport jump check: implied speed > 200 km/h
        if speed_kmh > 200.0:
            teleport_jump_count += 1
            if speed_kmh > teleport_jump_max_kmh:
                teleport_jump_max_kmh = speed_kmh

        # Smoothing: rolling 3-step average
        window_speeds = implied_speeds_kmh[max(0, len(implied_speeds_kmh) - 3) :]
        smoothed_speeds_kmh.append(sum(window_speeds) / len(window_speeds))

        # Disagreement
        rep_target = rep_curr if rep_curr is not None else rep_prev
        if rep_target is not None:
            disagreements_kmh.append(abs(rep_target - speed_kmh))

    p50 = _percentile(implied_speeds_kmh, 0.50)
    p95 = _percentile(implied_speeds_kmh, 0.95)
    mean_speed = sum(implied_speeds_kmh) / len(implied_speeds_kmh) if implied_speeds_kmh else 0.0
    mean_disagreement = sum(disagreements_kmh) / len(disagreements_kmh) if disagreements_kmh else 0.0
    max_disagreement = max(disagreements_kmh) if disagreements_kmh else 0.0
    disagreement_ratio = mean_disagreement / (mean_speed + 1e-3) if implied_speeds_kmh else 0.0

    return {
        "step_count": len(implied_speeds_kmh),
        "implied_speeds_kmh": [round(s, 2) for s in implied_speeds_kmh],
        "smoothed_speeds_kmh": [round(s, 2) for s in smoothed_speeds_kmh],
        "speed_p50_kmh": round(p50, 2) if p50 is not None else 0.0,
        "speed_p95_kmh": round(p95, 2) if p95 is not None else 0.0,
        "teleport_jump_count": teleport_jump_count,
        "teleport_jump_max_kmh": round(teleport_jump_max_kmh, 2),
        "mean_disagreement_kmh": round(mean_disagreement, 2),
        "max_disagreement_kmh": round(max_disagreement, 2),
        "disagreement_ratio": round(disagreement_ratio, 3),
    }


# ---------------------------------------------------------------------------
# 2. Phase Segmentation & Time-Windowed Metrics
# ---------------------------------------------------------------------------

ACCURACY_FLOOR_M: float = 25.0
"""Empirical GPS accuracy floor in metres.

Derived from empirical GPS accuracy distributions across urban ride-hailing telemetry
(p95 of reported accuracy is 26.6m in the release v2.1 corpus). Accounts for standard civil
GPS receiver error, urban canyon multipath reflection, and curb/lobby setback distance
from nominal geocoded building centroids when device-reported accuracy is unrealistically low.
"""


def _extract_point_accuracy_m(p: dict[str, Any], floor: float = ACCURACY_FLOOR_M) -> float:
    """Extract reported GPS accuracy with empirical floor."""
    acc = p.get("accuracy_m")
    if acc is None and isinstance(p.get("position"), dict):
        acc = p["position"].get("accuracy_m")
    if acc is not None:
        try:
            val = float(acc)
            if not math.isnan(val) and val >= 0:
                return max(val, floor)
        except (ValueError, TypeError):
            pass
    return floor


def segment_trip_phases(
    points: list[dict[str, Any]],
    pickup: tuple[float, float] | list[float] | dict[str, Any] | None = None,
    dropoff: tuple[float, float] | list[float] | dict[str, Any] | None = None,
    accuracy_floor_m: float = ACCURACY_FLOOR_M,
) -> dict[str, Any]:
    """Segment telemetry into approach phase (before reaching pickup) and trip phase (after reaching pickup).

    Pure measurement-driven segmentation without hardcoded verdicts:
    - Approach phase: telemetry before the driver first reaches the pickup (first point whose
      haversine distance to pickup is at or below that point's reported GPS accuracy, with
      an empirical floor of 25.0m derived from corpus accuracy p95 = 26.6m).
    - If the trip never reaches pickup, the whole track is approach.
    - Trip phase: telemetry after reaching pickup.
    """
    pickup_tuple = _extract_lon_lat(pickup)
    dropoff_tuple = _extract_lon_lat(dropoff)

    valid_points: list[tuple[float, tuple[float, float], dict[str, Any]]] = []
    for p in points:
        if not isinstance(p, dict):
            continue
        ts_s = _to_timestamp_s(p.get("occurred_at"))
        coords = _extract_lon_lat(p)
        if coords is not None:
            valid_points.append((ts_s if ts_s is not None else 0.0, coords, p))

    valid_points.sort(key=lambda x: x[0])

    if not valid_points:
        return {
            "valid_points": [],
            "reach_idx": None,
            "reached_pickup": False,
            "reached_pickup_time": None,
            "approach_duration_s": 0.0,
            "approach_points": [],
            "trip_points": [],
            "pickup_tuple": pickup_tuple,
            "dropoff_tuple": dropoff_tuple,
        }

    reach_idx: int | None = None
    reached_time_raw: Any = None

    if pickup_tuple:
        for idx, (_ts, coord, raw_p) in enumerate(valid_points):
            d_pick = haversine_distance_m(coord, pickup_tuple)
            eff_acc = _extract_point_accuracy_m(raw_p, floor=accuracy_floor_m)
            if d_pick <= eff_acc:
                reach_idx = idx
                reached_time_raw = raw_p.get("occurred_at")
                break

    if reach_idx is not None:
        reached_pickup = True
        if reach_idx == 0:
            approach_points = [valid_points[0]]
            trip_points = valid_points
            approach_duration_s = 0.0
        else:
            approach_points = valid_points[: reach_idx + 1]
            trip_points = valid_points[reach_idx:]
            approach_duration_s = max(0.0, valid_points[reach_idx][0] - valid_points[0][0])
    else:
        reached_pickup = False
        reached_time_raw = None
        approach_points = valid_points
        trip_points = []
        if len(valid_points) >= 2:
            approach_duration_s = max(0.0, valid_points[-1][0] - valid_points[0][0])
        else:
            approach_duration_s = 0.0

    return {
        "valid_points": valid_points,
        "reach_idx": reach_idx,
        "reached_pickup": reached_pickup,
        "reached_pickup_time": str(reached_time_raw) if reached_time_raw is not None else None,
        "approach_duration_s": round(approach_duration_s, 1),
        "approach_points": approach_points,
        "trip_points": trip_points,
        "pickup_tuple": pickup_tuple,
        "dropoff_tuple": dropoff_tuple,
    }


def _longest_stationary_seconds(pts: list[tuple[float, tuple[float, float], dict[str, Any]]]) -> float:
    """Compute duration in seconds of longest continuous stationary segment (speed < 3.6 km/h)."""
    if len(pts) < 2:
        return 0.0
    longest_s = 0.0
    curr_s = 0.0
    for i in range(1, len(pts)):
        dt = pts[i][0] - pts[i - 1][0]
        if dt <= 0:
            continue
        step_dist = haversine_distance_m(pts[i - 1][1], pts[i][1])
        step_sp_kmh = (step_dist / dt) * 3.6
        if step_sp_kmh < 3.6:  # < 1.0 m/s
            curr_s += dt
            if curr_s > longest_s:
                longest_s = curr_s
        else:
            curr_s = 0.0
    return round(longest_s, 1)


def compute_time_windowed_metrics(
    points: list[dict[str, Any]],
    pickup: tuple[float, float] | list[float] | dict[str, Any] | None = None,
    dropoff: tuple[float, float] | list[float] | dict[str, Any] | None = None,
    window_size_s: float = 60.0,
) -> list[dict[str, Any]]:
    """Compute time-windowed metrics in fixed windows (default 60s).

    Phase-aware:
    - Approach phase (before reaching pickup): distance change relative to pickup
    - Trip phase (after reaching pickup): distance change relative to dropoff
    """
    seg = segment_trip_phases(points, pickup=pickup, dropoff=dropoff)
    valid_points = seg["valid_points"]
    reach_idx = seg["reach_idx"]
    reach_time_s = valid_points[reach_idx][0] if reach_idx is not None else None
    pickup_tuple = seg["pickup_tuple"]
    dropoff_tuple = seg["dropoff_tuple"]

    if not valid_points:
        return []

    t_start = valid_points[0][0]
    t_end = valid_points[-1][0]
    total_duration = max(t_end - t_start, 0.0)
    num_windows = max(1, math.ceil(total_duration / window_size_s)) if total_duration > 0 else 1

    # Group points into windows
    windows_data: list[list[tuple[float, tuple[float, float], dict[str, Any]]]] = [[] for _ in range(num_windows)]
    for ts, coords, raw_p in valid_points:
        rel_t = ts - t_start
        w_idx = min(int(rel_t // window_size_s), num_windows - 1)
        windows_data[w_idx].append((ts, coords, raw_p))

    windows: list[dict[str, Any]] = []
    for w_idx, pts in enumerate(windows_data):
        w_start_s = w_idx * window_size_s
        w_end_s = (w_idx + 1) * window_size_s
        abs_start_s = t_start + w_start_s
        abs_end_s = t_start + w_end_s

        # Determine window phase
        if reach_idx is None:
            phase = "approach"
        elif reach_idx == 0:
            phase = "trip"
        else:
            assert reach_time_s is not None
            if abs_end_s <= reach_time_s:
                phase = "approach"
            elif abs_start_s >= reach_time_s:
                phase = "trip"
            else:
                # Straddles reaching pickup
                if (reach_time_s - abs_start_s) >= (abs_end_s - reach_time_s):
                    phase = "approach"
                else:
                    phase = "trip"

        target_name = "dropoff" if phase == "trip" else "pickup"
        target_tuple = dropoff_tuple if phase == "trip" else pickup_tuple

        if not pts:
            windows.append(
                {
                    "window_index": w_idx,
                    "start_s": round(w_start_s, 1),
                    "end_s": round(w_end_s, 1),
                    "phase": phase,
                    "target": target_name,
                    "distance_to_target_change_m": 0.0,
                    "distance_to_pickup_change_m": 0.0,
                    "distance_to_dropoff_change_m": 0.0,
                    "moving_seconds": 0.0,
                    "stationary_seconds": round(window_size_s, 1),
                    "median_implied_speed_kmh": 0.0,
                    "heading_change_deg": 0.0,
                }
            )
            continue

        # Distance to target change
        dist_change_m = 0.0
        if target_tuple and len(pts) >= 1:
            if phase == "approach":
                app_pts = [p for p in pts if p[0] <= reach_time_s] if reach_time_s is not None else pts
                end_pt = app_pts[-1] if app_pts else pts[-1]
                d_first = haversine_distance_m(pts[0][1], target_tuple)
                d_last = haversine_distance_m(end_pt[1], target_tuple)
                dist_change_m = d_last - d_first
            else:
                tr_pts = [p for p in pts if p[0] >= reach_time_s] if reach_time_s is not None else pts
                start_pt = tr_pts[0] if tr_pts else pts[0]
                d_first = haversine_distance_m(start_pt[1], target_tuple)
                d_last = haversine_distance_m(pts[-1][1], target_tuple)
                dist_change_m = d_last - d_first

        # Moving vs stationary seconds & implied speeds & headings
        moving_s = 0.0
        stationary_s = 0.0
        step_speeds: list[float] = []
        heading_changes: list[float] = []
        last_bearing: float | None = None

        if len(pts) >= 2:
            for i in range(1, len(pts)):
                dt = pts[i][0] - pts[i - 1][0]
                if dt <= 0:
                    continue
                step_dist = haversine_distance_m(pts[i - 1][1], pts[i][1])
                step_sp_kmh = (step_dist / dt) * 3.6
                step_speeds.append(step_sp_kmh)

                if step_sp_kmh >= 3.6:  # >= 1.0 m/s
                    moving_s += dt
                else:
                    stationary_s += dt

                bearing = calculate_bearing_deg(pts[i - 1][1], pts[i][1])
                if last_bearing is not None:
                    heading_changes.append(abs(heading_diff_deg(last_bearing, bearing)))
                last_bearing = bearing
        else:
            stationary_s = window_size_s

        med_speed = _percentile(step_speeds, 0.50) if step_speeds else 0.0

        windows.append(
            {
                "window_index": w_idx,
                "start_s": round(w_start_s, 1),
                "end_s": round(w_end_s, 1),
                "phase": phase,
                "target": target_name,
                "distance_to_target_change_m": round(dist_change_m, 1),
                "distance_to_pickup_change_m": round(dist_change_m if phase == "approach" else 0.0, 1),
                "distance_to_dropoff_change_m": round(dist_change_m if phase == "trip" else 0.0, 1),
                "moving_seconds": round(moving_s, 1),
                "stationary_seconds": round(stationary_s, 1),
                "median_implied_speed_kmh": round(med_speed or 0.0, 1),
                "heading_change_deg": round(sum(heading_changes), 1),
            }
        )

    return windows


# ---------------------------------------------------------------------------
# 3. Whole-Phase Metrics
# ---------------------------------------------------------------------------


def compute_whole_phase_metrics(
    points: list[dict[str, Any]],
    bundle_or_event: dict[str, Any],
    pickup: tuple[float, float] | list[float] | dict[str, Any] | None = None,
    dropoff: tuple[float, float] | list[float] | dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Compute whole-phase metrics:
    - reached_pickup (bool) and reached_pickup_time
    - approach_duration_s
    - approach stationary duration (SSD)
    - DAVI
    - pickup progress ratio = (d_start - d_end) / approach_path_length
    - dropoff progress ratio = (d_start - d_end) / trip_path_length
    - detour ratio split into approach (before pickup) and in-trip (after pickup)
    - max data gap
    - coverage
    - mock ratio
    - guardrail state
    """
    seg = segment_trip_phases(points, pickup=pickup, dropoff=dropoff)
    valid_points = seg["valid_points"]
    reach_idx = seg["reach_idx"]
    reached_pickup = seg["reached_pickup"]
    reached_pickup_time = seg["reached_pickup_time"]
    approach_duration_s = seg["approach_duration_s"]
    approach_pts = seg["approach_points"]
    trip_pts = seg["trip_points"]
    pickup_tuple = seg["pickup_tuple"]
    dropoff_tuple = seg["dropoff_tuple"]

    valid_coords = [vp[1] for vp in valid_points]
    ts_list = [vp[0] for vp in valid_points if vp[0] != 0.0]

    mock_count = sum(
        1
        for vp in valid_points
        if bool(vp[2].get("mock_location_reported")) or str(vp[2].get("gps_state") or "").lower() == "mock_reported"
    )

    # -----------------------------------------------------------------------
    # Phase splitting for Detour Ratio
    # -----------------------------------------------------------------------
    started_at_present = False
    started_at_raw = None
    for src in (
        bundle_or_event,
        bundle_or_event.get("assignment"),
        bundle_or_event.get("trip"),
        bundle_or_event.get("trip_data"),
    ):
        if isinstance(src, dict) and "started_at" in src:
            started_at_present = True
            started_at_raw = src["started_at"]
            break

    started_at_s = _to_timestamp_s(started_at_raw) if started_at_raw is not None else None

    if started_at_present:
        if started_at_s is not None:
            detour_app_pts = [vp for vp in valid_points if vp[0] <= started_at_s]
            detour_trip_pts = [vp for vp in valid_points if vp[0] >= started_at_s]
        else:
            detour_app_pts = valid_points
            detour_trip_pts = []
    else:
        if reach_idx is not None:
            if reach_idx == 0:
                detour_app_pts = [valid_points[0]]
                detour_trip_pts = valid_points
            else:
                detour_app_pts = valid_points[: reach_idx + 1]
                detour_trip_pts = valid_points[reach_idx:]
        else:
            has_planned_route = isinstance(bundle_or_event.get("planned_route"), dict)
            if has_planned_route:
                detour_app_pts = []
                detour_trip_pts = valid_points
            else:
                detour_app_pts = valid_points
                detour_trip_pts = []

    # 1. Approach path & detour
    approach_has_points = len(detour_app_pts) > 0
    approach_actual_path = None
    approach_planned_dist = None
    approach_is_estimated = False
    approach_ratio = None

    if approach_has_points:
        app_coords = [p[1] for p in detour_app_pts]
        approach_actual_path = (
            sum(haversine_distance_m(app_coords[i - 1], app_coords[i]) for i in range(1, len(app_coords)))
            if len(app_coords) >= 2
            else 0.0
        )
        app_route_obj = bundle_or_event.get("planned_approach_route") or bundle_or_event.get("approach_route")
        if (
            isinstance(app_route_obj, dict)
            and app_route_obj.get("distance_m")
            and not app_route_obj.get("is_estimated")
        ):
            try:
                approach_planned_dist = float(app_route_obj["distance_m"])
            except (ValueError, TypeError):
                approach_planned_dist = None

        if approach_planned_dist is None or approach_planned_dist <= 0:
            approach_is_estimated = True
            if pickup_tuple and app_coords:
                chord = haversine_distance_m(app_coords[0], pickup_tuple)
            elif len(app_coords) >= 2:
                chord = haversine_distance_m(app_coords[0], app_coords[-1])
            else:
                chord = 0.0
            approach_planned_dist = max(chord * 1.3, 10.0)

        if approach_planned_dist > 0:
            approach_ratio = round(approach_actual_path / approach_planned_dist, 3)

    # 2. In-trip path & detour
    in_trip_has_points = len(detour_trip_pts) > 0
    in_trip_actual_path = None
    in_trip_planned_dist = None
    in_trip_is_estimated = False
    in_trip_ratio = None

    if in_trip_has_points:
        trip_coords = [p[1] for p in detour_trip_pts]
        in_trip_actual_path = (
            sum(haversine_distance_m(trip_coords[i - 1], trip_coords[i]) for i in range(1, len(trip_coords)))
            if len(trip_coords) >= 2
            else 0.0
        )
        route_obj = bundle_or_event.get("planned_route") or bundle_or_event.get("route")
        if isinstance(route_obj, dict) and route_obj.get("distance_m") and not route_obj.get("is_estimated"):
            try:
                in_trip_planned_dist = float(route_obj["distance_m"])
            except (ValueError, TypeError):
                in_trip_planned_dist = None

        if in_trip_planned_dist is None or in_trip_planned_dist <= 0:
            in_trip_is_estimated = True
            if pickup_tuple and dropoff_tuple:
                chord = haversine_distance_m(pickup_tuple, dropoff_tuple)
            elif len(trip_coords) >= 2:
                chord = haversine_distance_m(trip_coords[0], trip_coords[-1])
            else:
                chord = 0.0
            in_trip_planned_dist = max(chord * 1.3, 10.0)

        if in_trip_planned_dist > 0:
            in_trip_ratio = round(in_trip_actual_path / in_trip_planned_dist, 3)

    # Primary detour ratio (prefers in_trip if available, otherwise approach)
    if in_trip_has_points and in_trip_ratio is not None:
        primary_ratio = in_trip_ratio
        primary_is_estimated = in_trip_is_estimated
        primary_actual_path = in_trip_actual_path
        primary_planned_dist = in_trip_planned_dist
    else:
        primary_ratio = approach_ratio
        primary_is_estimated = approach_is_estimated
        primary_actual_path = approach_actual_path
        primary_planned_dist = approach_planned_dist

    # 3. Pickup-relative measurements (over approach_pts only)
    app_meas_coords = [p[1] for p in approach_pts]
    app_meas_path = (
        sum(haversine_distance_m(app_meas_coords[i - 1], app_meas_coords[i]) for i in range(1, len(app_meas_coords)))
        if len(app_meas_coords) >= 2
        else 0.0
    )
    if reached_pickup and reach_idx == 0:
        pickup_progress_val = 1.0
        davi_val = 1.0
        approach_ssd_val = 0.0
    elif app_meas_coords and pickup_tuple:
        d_start = haversine_distance_m(app_meas_coords[0], pickup_tuple)
        d_end = haversine_distance_m(app_meas_coords[-1], pickup_tuple)
        if app_meas_path > 0:
            pickup_progress_val = round((d_start - d_end) / app_meas_path, 3)
        elif d_start == d_end:
            pickup_progress_val = 1.0 if d_start <= ACCURACY_FLOOR_M else 0.0
        else:
            pickup_progress_val = 0.0

        if len(app_meas_coords) >= 2:
            weighted, total = 0.0, 0.0
            for i in range(1, len(app_meas_coords)):
                p_prev = app_meas_coords[i - 1]
                p_curr = app_meas_coords[i]
                step_disp = haversine_distance_m(p_prev, p_curr)
                if step_disp < 1.0:
                    continue
                u = _planar_vector(p_prev, p_curr)
                v = _planar_vector(p_prev, pickup_tuple)
                cos = _cosine(u, v)
                if cos is not None:
                    weighted += step_disp * cos
                    total += step_disp
            if total > 0:
                davi_val = round(weighted / total, 4)
            else:
                d_pick = haversine_distance_m(app_meas_coords[0], pickup_tuple)
                davi_val = 1.0 if d_pick <= ACCURACY_FLOOR_M else 0.0
        else:
            d_pick = haversine_distance_m(app_meas_coords[0], pickup_tuple)
            davi_val = 1.0 if d_pick <= ACCURACY_FLOOR_M else 0.0

        approach_ssd_val = _longest_stationary_seconds(approach_pts)
    else:
        pickup_progress_val = None
        davi_val = None
        approach_ssd_val = 0.0

    # 4. Dropoff-relative measurements (over trip_pts only)
    trip_meas_coords = [p[1] for p in trip_pts]
    trip_meas_path = (
        sum(haversine_distance_m(trip_meas_coords[i - 1], trip_meas_coords[i]) for i in range(1, len(trip_meas_coords)))
        if len(trip_meas_coords) >= 2
        else 0.0
    )
    if trip_meas_coords and dropoff_tuple:
        d_start_drop = haversine_distance_m(trip_meas_coords[0], dropoff_tuple)
        d_end_drop = haversine_distance_m(trip_meas_coords[-1], dropoff_tuple)
        if trip_meas_path > 0:
            dropoff_progress_val = round((d_start_drop - d_end_drop) / trip_meas_path, 3)
        elif d_start_drop == d_end_drop:
            dropoff_progress_val = 1.0 if d_start_drop <= ACCURACY_FLOOR_M else 0.0
        else:
            dropoff_progress_val = 0.0
    else:
        dropoff_progress_val = None

    # 5. Min distance to pickup
    min_dist_to_pickup_m = None
    if pickup_tuple and valid_coords:
        min_dist_to_pickup_m = round(min(haversine_distance_m(c, pickup_tuple) for c in valid_coords), 1)

    # 6. Telemetry metadata
    fw = compute_feature_window(points, pickup_tuple, dropoff_tuple)
    max_gap_s = fw.max_gap_s
    if max_gap_s is None and len(ts_list) >= 2:
        ts_sorted = sorted(ts_list)
        max_gap_s = max(ts_sorted[i] - ts_sorted[i - 1] for i in range(1, len(ts_sorted)))

    coverage_val = fw.telemetry_coverage
    if coverage_val is None and len(ts_list) >= 2:
        expected_pings = max(1, int((max(ts_list) - min(ts_list)) / 15.0) + 1)
        coverage_val = min(1.0, len(ts_list) / expected_pings)

    mock_ratio = mock_count / len(points) if points else 0.0

    incident = bundle_or_event.get("platform_incident") or bundle_or_event.get("platform_outage")
    incidents = [incident] if isinstance(incident, dict) else []
    guardrail_res = evaluate_telemetry_window(points, incidents)
    guardrail_state = (
        "nominal" if not guardrail_res.blocked else (guardrail_res.reason.value if guardrail_res.reason else "blocked")
    )

    detour_ratio_dict = {
        "value": primary_ratio,
        "unit": "ratio",
        "is_estimated": primary_is_estimated,
        "actual_path_length_m": round(primary_actual_path, 1) if primary_actual_path is not None else None,
        "planned_route_length_m": round(primary_planned_dist, 1) if primary_planned_dist is not None else None,
        "formula": "actual_path_length / planned_route_length",
        "approach": {
            "value": approach_ratio,
            "unit": "ratio",
            "is_estimated": approach_is_estimated,
            "actual_path_length_m": round(approach_actual_path, 1) if approach_has_points else None,
            "planned_route_length_m": round(approach_planned_dist, 1) if approach_has_points else None,
            "formula": "approach_path_length / planned_or_chord_start_to_pickup",
        },
        "in_trip": {
            "value": in_trip_ratio,
            "unit": "ratio",
            "is_estimated": in_trip_is_estimated,
            "actual_path_length_m": round(in_trip_actual_path, 1) if in_trip_has_points else None,
            "planned_route_length_m": round(in_trip_planned_dist, 1) if in_trip_has_points else None,
            "formula": "in_trip_path_length / planned_pickup_to_dropoff",
        },
    }

    return {
        "reached_pickup": reached_pickup,
        "reached_pickup_time": reached_pickup_time,
        "approach_duration_s": approach_duration_s,
        "approach_ssd": {
            "value": approach_ssd_val,
            "unit": "s",
            "formula": "longest_stationary_chain_seconds_before_pickup",
        },
        "davi": {
            "value": davi_val,
            "unit": "ratio",
            "formula": "weighted_cosine_vector_displacement_to_pickup",
        },
        "progress_ratio": {
            "value": pickup_progress_val,
            "unit": "ratio",
            "formula": "(d_start - d_end) / path_length",
        },
        "dropoff_progress_ratio": {
            "value": dropoff_progress_val,
            "unit": "ratio",
            "formula": "(d_start_dropoff - d_end_dropoff) / in_trip_path_length",
        },
        "detour_ratio": detour_ratio_dict,
        "detour_ratio_approach": detour_ratio_dict["approach"],
        "detour_ratio_in_trip": detour_ratio_dict["in_trip"],
        "min_distance_to_pickup_m": min_dist_to_pickup_m,
        "max_data_gap_s": round(max_gap_s, 1) if max_gap_s is not None else 0.0,
        "coverage": round(coverage_val, 3) if coverage_val is not None else 1.0,
        "mock_ratio": round(mock_ratio, 3),
        "guardrail_state": guardrail_state,
    }


# ---------------------------------------------------------------------------
# 4. Risk Bands Classification
# ---------------------------------------------------------------------------


def classify_metric_risk_band(metric_name: str, value: Any) -> dict[str, Any]:
    """Map a metric value to normal / elevated / high band with documented thresholds.

    Missing values (None) map to 'unknown' band with value None.
    """
    cfg = RISK_BANDS_CONFIG_V1.get(metric_name, {})
    unit = cfg.get("unit", "")
    formula = cfg.get("formula", "")

    if value is None:
        return {"value": None, "unit": unit, "band": "unknown", "formula": formula}

    if metric_name in ("detour_ratio", "detour_ratio_approach", "detour_ratio_in_trip"):
        try:
            val = float(value)
        except (ValueError, TypeError):
            return {"value": None, "unit": unit, "band": "unknown", "formula": formula}
        if val <= 1.15:
            band = "normal"
        elif val <= 1.35:
            band = "elevated"
        else:
            band = "high"
        return {"value": round(val, 3), "unit": unit, "band": band, "formula": formula}

    elif metric_name == "approach_ssd":
        try:
            val = float(value)
        except (ValueError, TypeError):
            return {"value": None, "unit": unit, "band": "unknown", "formula": formula}
        if val < 90.0:
            band = "normal"
        elif val < 180.0:
            band = "elevated"
        else:
            band = "high"
        return {"value": round(val, 1), "unit": unit, "band": band, "formula": formula}

    elif metric_name == "davi":
        try:
            val = float(value)
        except (ValueError, TypeError):
            return {"value": None, "unit": unit, "band": "unknown", "formula": formula}
        if val > 0.30:
            band = "normal"
        elif val >= -0.20:
            band = "elevated"
        else:
            band = "high"
        return {"value": round(val, 3), "unit": unit, "band": band, "formula": formula}

    elif metric_name == "teleport_jump":
        if isinstance(value, dict):
            if value.get("count") is None and value.get("max_speed_kmh") is None and not value.get("mock"):
                return {
                    "value": None,
                    "max_speed_kmh": 0.0,
                    "mock": False,
                    "unit": unit,
                    "band": "unknown",
                    "formula": formula,
                }
            count = int(value.get("count", 0))
            max_speed = float(value.get("max_speed_kmh", 0.0))
            mock = bool(value.get("mock", False))
        elif isinstance(value, (int, float)):
            count = int(value)
            max_speed = 0.0
            mock = False
        else:
            return {
                "value": None,
                "max_speed_kmh": 0.0,
                "mock": False,
                "unit": unit,
                "band": "unknown",
                "formula": formula,
            }

        if mock or count > 0 or max_speed > 200.0:
            band = "high"
        elif max_speed >= 120.0:
            band = "elevated"
        else:
            band = "normal"
        return {
            "value": count,
            "max_speed_kmh": round(max_speed, 1),
            "mock": mock,
            "unit": unit,
            "band": band,
            "formula": formula,
        }

    return {"value": value, "unit": unit, "band": "unknown" if value is None else "normal", "formula": formula}


# ---------------------------------------------------------------------------
# 5. Natural Language Rendering (Vietnamese)
# ---------------------------------------------------------------------------


def render_natural_language_summary(
    windows: list[dict[str, Any]],
    metrics: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Render metrics and window progression into natural Vietnamese narrative."""
    windows_sentences: list[str] = []
    for w in windows:
        t0 = int(round(w["start_s"] / 60.0))
        t1 = int(round(w["end_s"] / 60.0))
        phase = w.get("phase", "approach")
        phase_label = "Giai đoạn chở khách" if phase == "trip" else "Giai đoạn tiếp cận điểm đón"
        target_label = "điểm trả" if phase == "trip" else "điểm đón"
        dist_ch = w.get("distance_to_target_change_m")
        if dist_ch is None:
            dist_ch = (
                w.get("distance_to_pickup_change_m", 0.0)
                if phase == "approach"
                else w.get("distance_to_dropoff_change_m", 0.0)
            )
        v_med = w.get("median_implied_speed_kmh", 0.0)
        stat_s = int(round(w.get("stationary_seconds", 0.0)))

        if dist_ch > 50.0:
            windows_sentences.append(
                f"Từ phút thứ {t0} đến {t1} ({phase_label}), xe đi ra xa {target_label} {int(round(dist_ch))} m "
                f"(vận tốc trung vị {v_med:.1f} km/h)."
            )
        elif dist_ch < -50.0:
            windows_sentences.append(
                f"Từ phút thứ {t0} đến {t1} ({phase_label}), xe tiếp cận gần {target_label} thêm {int(round(abs(dist_ch)))} m "
                f"(vận tốc trung vị {v_med:.1f} km/h)."
            )
        elif stat_s >= 40:
            windows_sentences.append(
                f"Từ phút thứ {t0} đến {t1} ({phase_label}), xe đứng yên {stat_s} giây tại chỗ (vận tốc trung vị {v_med:.1f} km/h)."
            )
        else:
            windows_sentences.append(
                f"Từ phút thứ {t0} đến {t1} ({phase_label}), xe duy trì di chuyển ổn định với vận tốc trung vị {v_med:.1f} km/h."
            )

    metrics_sentences: list[str] = []
    band_vn_map = {
        "normal": "bình thường",
        "elevated": "rủi ro tăng",
        "high": "rủi ro cao",
        "unknown": "không đủ dữ liệu",
    }

    # Detour
    detour = metrics.get("detour_ratio", {})
    detour_app = metrics.get("detour_ratio_approach")
    detour_trip = metrics.get("detour_ratio_in_trip")

    if detour_app or detour_trip:
        if detour_app:
            val = detour_app.get("value")
            band = band_vn_map.get(detour_app.get("band", "unknown"), "không đủ dữ liệu")
            if val is not None:
                metrics_sentences.append(
                    f"Tỷ lệ lộ trình tiếp cận (approach detour): {val:.2f} ({band}, chuẩn <= 1.15, vượt > 1.35 là bất thường)."
                )
            else:
                metrics_sentences.append(
                    f"Tỷ lệ lộ trình tiếp cận (approach detour): {band} (chuẩn <= 1.15, vượt > 1.35 là bất thường)."
                )
        if detour_trip:
            val = detour_trip.get("value")
            band = band_vn_map.get(detour_trip.get("band", "unknown"), "không đủ dữ liệu")
            if val is not None:
                metrics_sentences.append(
                    f"Tỷ lệ lộ trình trong chuyến (in-trip detour): {val:.2f} ({band}, chuẩn <= 1.15, vượt > 1.35 là bất thường)."
                )
            else:
                metrics_sentences.append(
                    f"Tỷ lệ lộ trình trong chuyến (in-trip detour): {band} (chuẩn <= 1.15, vượt > 1.35 là bất thường)."
                )
    elif detour:
        val = detour.get("value")
        band = band_vn_map.get(detour.get("band", "unknown"), "không đủ dữ liệu")
        if val is not None:
            metrics_sentences.append(
                f"Tỷ lệ lộ trình di chuyển (detour ratio): {val:.2f} ({band}, chuẩn <= 1.15, vượt > 1.35 là bất thường)."
            )
        else:
            metrics_sentences.append(
                f"Tỷ lệ lộ trình di chuyển (detour ratio): {band} (chuẩn <= 1.15, vượt > 1.35 là bất thường)."
            )

    # Approach SSD
    ssd = metrics.get("approach_ssd", {})
    if ssd:
        val = ssd.get("value")
        band = band_vn_map.get(ssd.get("band", "unknown"), "không đủ dữ liệu")
        if val is not None:
            metrics_sentences.append(
                f"Thời gian dừng đỗ tiếp cận (SSD): {val:.0f} giây ({band}, quy chế quy định >= 180s là dừng đỗ kéo dài)."
            )
        else:
            metrics_sentences.append(
                f"Thời gian dừng đỗ tiếp cận (SSD): {band} (quy chế quy định >= 180s là dừng đỗ kéo dài)."
            )

    # DAVI
    davi = metrics.get("davi", {})
    if davi:
        val = davi.get("value")
        band = band_vn_map.get(davi.get("band", "unknown"), "không đủ dữ liệu")
        if val is not None:
            metrics_sentences.append(
                f"Chỉ số định hướng tiếp cận (DAVI): {val:.2f} ({band}, giá trị âm thể hiện di chuyển lệch hướng điểm đón)."
            )
        else:
            metrics_sentences.append(
                f"Chỉ số định hướng tiếp cận (DAVI): {band} (giá trị âm thể hiện di chuyển lệch hướng điểm đón)."
            )

    # Teleport
    teleport = metrics.get("teleport_jump", {})
    if teleport:
        val = teleport.get("value")
        band = band_vn_map.get(teleport.get("band", "unknown"), "không đủ dữ liệu")
        if val is not None:
            count = int(val)
            max_sp = teleport.get("max_speed_kmh", 0.0)
            mock = teleport.get("mock", False)
            if count > 0 or mock or max_sp > 120.0:
                metrics_sentences.append(
                    f"Bước nhảy viễn thông bất thường (teleport): ghi nhận {count} lần (tốc độ tối đa {max_sp:.1f} km/h, "
                    f"mock={mock}; {band})."
                )
            else:
                metrics_sentences.append("Bước nhảy viễn thông: không phát hiện bước nhảy vận tốc hoặc giả lập GPS.")
        else:
            metrics_sentences.append(f"Bước nhảy viễn thông: {band}.")

    # Summary paragraph
    high_risks = [k for k, v in metrics.items() if v.get("band") == "high"]
    elevated_risks = [k for k, v in metrics.items() if v.get("band") == "elevated"]

    if high_risks:
        summary_paragraph = (
            f"Tóm tắt hành trình: Phát hiện rủi ro cao ở các chỉ số: {', '.join(high_risks)}. "
            f"Hành vi viễn thông cho thấy sự bất thường rõ rệt so với hành trình di chuyển chuẩn."
        )
    elif elevated_risks:
        summary_paragraph = (
            f"Tóm tắt hành trình: Ghi nhận mức độ rủi ro tăng ở các chỉ số: {', '.join(elevated_risks)}. "
            f"Chuyến xe cần chuyên viên xem xét thêm bối cảnh giao thông và trao đổi khách hàng."
        )
    else:
        summary_paragraph = (
            "Tóm tắt hành trình: Toàn bộ các chỉ số động học, thời gian dừng đỗ và lộ trình di chuyển "
            "đều nằm trong ngưỡng bình thường danh định hoặc chưa đủ dữ liệu cảnh báo."
        )

    return {
        "windows_sentences": windows_sentences,
        "metrics_sentences": metrics_sentences,
        "summary_paragraph": summary_paragraph,
    }


logger = logging.getLogger(__name__)

REFERENCE_ARTIFACT_PATH = Path(__file__).resolve().parent / "data" / "jev_reference_quantiles.json"


def load_reference_artifact(path: Path | str | None = None) -> dict[str, Any] | None:
    """Load empirical reference quantiles and class medians from JSON artifact.

    Returns None gracefully if the file is absent or unreadable.
    """
    target_path = Path(path) if path is not None else REFERENCE_ARTIFACT_PATH
    if not target_path.exists():
        return None
    try:
        with open(target_path, encoding="utf-8") as f:
            return json.load(f)
    except Exception as exc:
        logger.warning("Failed to load reference artifact from %s: %s", target_path, exc)
        return None


def compute_empirical_percentile(value: float, quantiles: dict[str, float]) -> int:
    """Compute empirical percentile rank (1-99) of value against fitted quantiles."""
    q_levels = [
        ("p01", 1),
        ("p05", 5),
        ("p10", 10),
        ("p25", 25),
        ("p50", 50),
        ("p75", 75),
        ("p90", 90),
        ("p95", 95),
        ("p99", 99),
    ]
    points = [(float(quantiles[k]), pct) for k, pct in q_levels if k in quantiles]
    if not points:
        return 50

    points.sort(key=lambda x: x[0])
    vals = [p[0] for p in points]
    pcts = [p[1] for p in points]

    if value <= vals[0]:
        return pcts[0]
    if value >= vals[-1]:
        return pcts[-1]

    for i in range(len(vals) - 1):
        v_lo, v_hi = vals[i], vals[i + 1]
        p_lo, p_hi = pcts[i], pcts[i + 1]
        if v_lo <= value <= v_hi:
            if v_hi == v_lo:
                return p_lo
            frac = (value - v_lo) / (v_hi - v_lo)
            return int(round(p_lo + frac * (p_hi - p_lo)))

    return 50


def format_reference_position(name: str, value: float, quantiles: dict[str, float]) -> str:
    """Render empirical reference position in Vietnamese without verdict words or hardcoded thresholds."""
    p = compute_empirical_percentile(value, quantiles)
    if p < 50:
        higher_pct = 100 - p
        return f"thấp hơn {higher_pct}% chuyến bình thường (tham chiếu tập train)"
    elif p > 50:
        return f"cao hơn {p}% chuyến bình thường (tham chiếu tập train)"
    else:
        return "ở mức trung vị chuyến bình thường (tham chiếu tập train)"


def build_evidence_measurements(
    kinematics: dict[str, Any],
    windows: list[dict[str, Any]],
    whole_phase: dict[str, Any],
    mock_location_reported: bool = False,
    reference_artifact: dict[str, Any] | None = None,
    include_class_medians: bool = False,
) -> dict[str, dict[str, Any]]:
    """Build neutral telemetry measurements where every field carries value, unit, and description without verdict bands."""
    reached_pickup = bool(whole_phase.get("reached_pickup", False))
    reached_pickup_time = whole_phase.get("reached_pickup_time")
    approach_duration_s = whole_phase.get("approach_duration_s", 0.0)

    detour_obj = whole_phase.get("detour_ratio", {})
    actual_path = detour_obj.get("actual_path_length_m")
    planned_dist = detour_obj.get("planned_route_length_m")
    detour_val = detour_obj.get("value")

    ssd_obj = whole_phase.get("approach_ssd", {})
    ssd_val = ssd_obj.get("value")

    davi_obj = whole_phase.get("davi", {})
    davi_val = davi_obj.get("value")

    progress_obj = whole_phase.get("progress_ratio", {})
    progress_val = progress_obj.get("value")

    dropoff_prog_obj = whole_phase.get("dropoff_progress_ratio", {})
    dropoff_prog_val = dropoff_prog_obj.get("value")

    min_dist_val = whole_phase.get("min_distance_to_pickup_m")

    total_stat_s = round(sum(w.get("stationary_seconds", 0.0) for w in windows), 1) if windows else 0.0

    meas = {
        "reached_pickup": {
            "value": reached_pickup,
            "time": reached_pickup_time,
            "unit": "boolean",
            "description": "Trạng thái đã tiếp cận điểm đón",
        },
        "approach_duration": {
            "value": approach_duration_s,
            "unit": "s",
            "description": "Thời lượng tiếp cận điểm đón",
        },
        "speed_p50": {
            "value": kinematics.get("speed_p50_kmh", 0.0),
            "unit": "km/h",
            "description": "Vận tốc trung vị",
        },
        "speed_p95": {
            "value": kinematics.get("speed_p95_kmh", 0.0),
            "unit": "km/h",
            "description": "Vận tốc phân vị 95",
        },
        "approach_stationary_duration": {
            "value": ssd_val if ssd_val is not None else 0.0,
            "unit": "s",
            "description": "Dừng đỗ dài nhất trước đón",
        },
        "total_stationary_duration": {
            "value": total_stat_s,
            "unit": "s",
            "description": "Tổng thời gian dừng đỗ",
        },
        "route_detour_ratio": {
            "value": detour_val,
            "unit": "ratio",
            "description": "Tỷ lệ lộ trình thực tế/dự kiến",
        },
        "actual_path_length": {
            "value": actual_path,
            "unit": "m",
            "description": "Chiều dài thực tế di chuyển",
        },
        "planned_route_length": {
            "value": planned_dist,
            "unit": "m",
            "description": "Chiều dài dự kiến",
        },
        "directional_approach_vector_index": {
            "value": davi_val,
            "unit": "ratio",
            "description": "Chỉ số hướng tiếp cận",
        },
        "pickup_progress_ratio": {
            "value": progress_val,
            "unit": "ratio",
            "description": "Tỷ lệ tiến về điểm đón",
        },
        "dropoff_progress_ratio": {
            "value": dropoff_prog_val,
            "unit": "ratio",
            "description": "Tỷ lệ tiến về điểm trả",
        },
        "min_distance_to_pickup": {
            "value": min_dist_val,
            "unit": "m",
            "description": "Khoảng cách ngắn nhất tới đón",
        },
        "teleport_jump_count": {
            "value": kinematics.get("teleport_jump_count", 0),
            "unit": "count",
            "description": "Số bước nhảy vận tốc",
        },
        "max_implied_speed": {
            "value": kinematics.get("teleport_jump_max_kmh", 0.0),
            "unit": "km/h",
            "description": "Vận tốc tức thời cực đại",
        },
        "mock_location_reported": {
            "value": bool(mock_location_reported),
            "unit": "boolean",
            "description": "Cờ giả lập GPS",
        },
        "telemetry_data_gap_max": {
            "value": whole_phase.get("max_data_gap_s", 0.0),
            "unit": "s",
            "description": "Khoảng cách dữ liệu lớn nhất",
        },
        "telemetry_coverage": {
            "value": whole_phase.get("coverage", 1.0),
            "unit": "ratio",
            "description": "Tỷ lệ phủ dữ liệu nhận được",
        },
    }

    if reference_artifact is not None:
        quantiles_table = reference_artifact.get("quantiles", {})
        class_medians_table = reference_artifact.get("class_medians", {})

        for name, m_dict in meas.items():
            val = m_dict.get("value")
            if not isinstance(val, (int, float)) or isinstance(val, bool):
                continue
            q_dict = quantiles_table.get(name)
            if q_dict:
                m_dict["reference_position"] = format_reference_position(name, float(val), q_dict)

            if include_class_medians:
                cls_meds = class_medians_table.get(name)
                if cls_meds:
                    m_dict["class_medians"] = cls_meds
                    cls_summary = ", ".join(f"trung vị {c}: {v}" for c, v in sorted(cls_meds.items()))
                    m_dict["class_medians_summary"] = f"{cls_summary} (tham chiếu tập train)"

    return meas


def _format_window_narrative_line(w: dict[str, Any]) -> str:
    """Format single 60-second window into phase-aware narrative without verdict words."""
    t0 = int(round(w["start_s"] / 60.0))
    t1 = int(round(w["end_s"] / 60.0))
    phase = w.get("phase", "approach")
    phase_label = "Giai đoạn chở khách" if phase == "trip" else "Giai đoạn tiếp cận điểm đón"
    target_label = "điểm trả" if phase == "trip" else "điểm đón"

    dist_ch = w.get("distance_to_target_change_m")
    if dist_ch is None:
        dist_ch = (
            w.get("distance_to_pickup_change_m", 0.0)
            if phase == "approach"
            else w.get("distance_to_dropoff_change_m", 0.0)
        )
    v_med = w.get("median_implied_speed_kmh", 0.0)
    stat_s = int(round(w.get("stationary_seconds", 0.0)))

    if dist_ch > 50.0:
        return (
            f"Phút {t0} đến {t1} ({phase_label}): Khoảng cách đến {target_label} tăng thêm {int(round(dist_ch))} m "
            f"(vận tốc {v_med:.1f} km/h, dừng {stat_s}s)."
        )
    elif dist_ch < -50.0:
        return (
            f"Phút {t0} đến {t1} ({phase_label}): Khoảng cách đến {target_label} giảm bớt {int(round(abs(dist_ch)))} m "
            f"(vận tốc {v_med:.1f} km/h, dừng {stat_s}s)."
        )
    elif stat_s >= 40:
        return f"Phút {t0} đến {t1} ({phase_label}): Xe dừng {stat_s}s (vận tốc {v_med:.1f} km/h)."
    else:
        return f"Phút {t0} đến {t1} ({phase_label}): Xe di chuyển với vận tốc {v_med:.1f} km/h (dừng {stat_s}s)."


def render_evidence_window_narratives(windows: list[dict[str, Any]], max_windows: int = 15) -> list[str]:
    """Render 60-second window measurements into objective narrative sentences without verdict words."""
    if not windows:
        return []

    if len(windows) > max_windows:
        head = windows[:8]
        tail = windows[-7:]
        skip_count = len(windows) - 15
        selected_windows = head
        has_skip = True
    else:
        selected_windows = windows
        has_skip = False

    narratives: list[str] = [_format_window_narrative_line(w) for w in selected_windows]

    if has_skip:
        t_skip_start = int(round(head[-1]["end_s"] / 60.0))
        t_skip_end = int(round(tail[0]["start_s"] / 60.0))
        narratives.append(
            f"Phút {t_skip_start} đến {t_skip_end}: Tiếp tục di chuyển qua {skip_count} cửa sổ thời gian tương tự."
        )
        for w in tail:
            narratives.append(_format_window_narrative_line(w))

    return narratives


def render_evidence_measurement_summary(
    measurements: dict[str, dict[str, Any]],
) -> str:
    """Render summary of measured telemetry without verdict words."""
    parts = []
    reached = measurements.get("reached_pickup", {}).get("value")
    reached_time = measurements.get("reached_pickup", {}).get("time")
    app_dur = measurements.get("approach_duration", {}).get("value")
    if reached is True:
        parts.append(
            "Tiếp cận điểm đón: đạt"
            + (f" ({reached_time})" if reached_time else "")
            + (f", {app_dur:.0f}s." if app_dur is not None else ".")
        )
    elif reached is False:
        parts.append("Tiếp cận điểm đón: chưa đạt" + (f", {app_dur:.0f}s." if app_dur is not None else "."))

    p50 = measurements.get("speed_p50", {}).get("value")
    p95 = measurements.get("speed_p95", {}).get("value")
    if p50 is not None:
        parts.append(f"Vận tốc: {p50} km/h (p95 {p95} km/h).")

    ssd = measurements.get("approach_stationary_duration", {}).get("value")
    if ssd is not None and ssd > 0:
        parts.append(f"Dừng trước đón: {ssd:.0f}s.")

    detour = measurements.get("route_detour_ratio", {}).get("value")
    if detour is not None:
        parts.append(f"Lộ trình thực tế/dự kiến: {detour:.2f}.")

    dropoff_prog = measurements.get("dropoff_progress_ratio", {}).get("value")
    if dropoff_prog is not None:
        parts.append(f"Tiến độ trả: {dropoff_prog:.2f}.")

    davi = measurements.get("directional_approach_vector_index", {}).get("value")
    if davi is not None:
        parts.append(f"Chỉ số DAVI: {davi:.2f}.")

    min_dist = measurements.get("min_distance_to_pickup", {}).get("value")
    if min_dist is not None:
        parts.append(f"Gần nhất tới đón: {min_dist:.1f} m.")

    jumps = measurements.get("teleport_jump_count", {}).get("value")
    max_jump = measurements.get("max_implied_speed", {}).get("value")
    mock = measurements.get("mock_location_reported", {}).get("value")
    if jumps:
        parts.append(f"Bước nhảy tọa độ: {jumps} lần ({max_jump} km/h).")
    if mock:
        parts.append("Mock GPS: True.")

    gap = measurements.get("telemetry_data_gap_max", {}).get("value")
    cov = measurements.get("telemetry_coverage", {}).get("value")
    if gap is not None and cov is not None:
        parts.append(f"Khoảng cách dữ liệu max: {gap:.0f}s, phủ: {cov:.2f}.")

    return " ".join(parts)


# ---------------------------------------------------------------------------
# 6. Cleaning
# ---------------------------------------------------------------------------


def clean_state_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Clean payload by dropping PII keys, raw points, and generator metadata at any depth."""
    # Recursively drop generator metadata, evaluation labels, and simulation keys at any depth
    cleaned = scrub_evaluation_labels(copy.deepcopy(payload))

    # Drop PII keys at top-level
    for key in list(cleaned.keys()):
        if key in GENERATOR_METADATA_KEYS or key in PII_KEYS:
            cleaned.pop(key, None)

    # Clean driver profile
    if "driver" in cleaned and isinstance(cleaned["driver"], dict):
        drv = cleaned["driver"]
        for pii in PII_KEYS:
            drv.pop(pii, None)

    if "driver_analytics" in cleaned and isinstance(cleaned["driver_analytics"], dict):
        drv_ana = cleaned["driver_analytics"]
        for pii in PII_KEYS:
            drv_ana.pop(pii, None)

    # Clean trip_data
    if "trip_data" in cleaned and isinstance(cleaned["trip_data"], dict):
        trip = cleaned["trip_data"]
        for pii in PII_KEYS:
            trip.pop(pii, None)

    # Clean telemetry (strip raw points list)
    if "telemetry" in cleaned and isinstance(cleaned["telemetry"], dict):
        telem = cleaned["telemetry"]
        telem.pop("points", None)
        telem.pop("telemetry_points", None)
        telem.pop("raw_points", None)
        telem.pop("samples", None)

    return cleaned


# ---------------------------------------------------------------------------
# 7. Shared Mapper (run_10k + telemetry_queue_worker parity)
# ---------------------------------------------------------------------------


def map_telemetry_event_to_jev_input(event_or_bundle: dict[str, Any]) -> JevAssessmentInput:
    """Map a telemetry event or benchmark bundle into a unified JevAssessmentInput.

    Ensures benchmark and production use one shared mapper with:
    - parse_trajectory_maneuvers (including wrong_direction detection)
    - approach stationary duration (SSD) via FeatureWindow
    - derived speed calculation
    - ghost-trip arrival presence
    - recursive evaluation label and generator ground truth scrubbing
    """
    ev = event_or_bundle
    points = ev.get("points") or ev.get("telemetry") or ev.get("samples") or []
    pickup_raw = (
        ev.get("pickup")
        or (ev.get("trip") if isinstance(ev.get("trip"), dict) else {}).get("pickup")
        or (ev.get("assignment") if isinstance(ev.get("assignment"), dict) else {}).get("pickup")
    )
    dropoff_raw = (
        ev.get("dropoff")
        or (ev.get("trip") if isinstance(ev.get("trip"), dict) else {}).get("dropoff")
        or (ev.get("assignment") if isinstance(ev.get("assignment"), dict) else {}).get("dropoff")
    )
    pickup_coords = _extract_lon_lat(pickup_raw)
    dropoff_coords = _extract_lon_lat(dropoff_raw)

    pickup_list = [pickup_coords[0], pickup_coords[1]] if pickup_coords else None
    dropoff_list = [dropoff_coords[0], dropoff_coords[1]] if dropoff_coords else None

    # Stationary duration via feature engineering
    fw = compute_feature_window(points, pickup_coords, dropoff_coords)
    ssd = int(fw.approach_stationary_duration_s or fw.stationary_duration_total_s or 0)
    stationary_duration = int(ev.get("stationary_duration_s") or ssd or 0)

    # Parse trajectory maneuvers (including wrong_direction)
    maneuvers = parse_trajectory_maneuvers(
        points,
        pickup=pickup_list,
        dropoff=dropoff_list,
        stall_duration_s=stationary_duration,
    )

    has_mock = bool(ev.get("mock_location_reported")) or any(
        bool(p.get("mock_location_reported")) or p.get("gps_state") == "mock_reported"
        for p in points
        if isinstance(p, dict)
    )

    # Speed calculation (Issue #260): producer-reported speed_mps is untrusted
    # (TELEMETRY_DISTRIBUTION.md section 3: "Features derive speed from
    # positions and ignore this field"). Use derived FeatureWindow kinematics
    # only; 0.0 when no derived signal rather than trusting the producer.
    max_speed_kmh = float(fw.speed.max_mps or 0.0) * 3.6

    trip = ev.get("trip") if isinstance(ev.get("trip"), dict) else {}
    assignment = ev.get("assignment") if isinstance(ev.get("assignment"), dict) else {}

    lifecycle = str(
        ev.get("lifecycle_state") or trip.get("status") or trip.get("lifecycle_state") or ev.get("status") or "complete"
    ).lower()

    actor = ev.get("cancellation_actor") or assignment.get("cancellation_actor") or trip.get("cancellation_actor")
    reason = ev.get("cancellation_reason") or assignment.get("cancellation_reason") or trip.get("cancellation_reason")

    trip_data: dict[str, Any] = {
        "trip_id": ev.get("trip_id") or trip.get("id"),
        "assignment_id": ev.get("assignment_id") or assignment.get("id"),
        "case_id": ev.get("case_id"),
        "lifecycle_state": lifecycle,
        "status": lifecycle,
        "cancellation_actor": actor,
        "cancellation_reason": reason,
        "pickup": pickup_list,
        "dropoff": dropoff_list,
        "passenger_rating": (ev.get("passenger_feedback") or {}).get("rating"),
    }

    # Ghost-trip arrival presence
    if "arrived_at" in assignment:
        trip_data["arrived_at"] = assignment.get("arrived_at")
    elif "arrived_at" in ev:
        trip_data["arrived_at"] = ev.get("arrived_at")
    if "started_at" in assignment:
        trip_data["started_at"] = assignment.get("started_at")
    elif "started_at" in ev:
        trip_data["started_at"] = ev.get("started_at")

    has_wrong_dir = any(m.get("action") == "wrong_direction" for m in maneuvers) or bool(ev.get("wrong_direction"))

    telemetry_dict: dict[str, Any] = {
        "points": points,
        "maneuvers": maneuvers,
        "stationary_duration_s": stationary_duration,
        "max_speed_kmh": round(max_speed_kmh, 1),
        "mock_location_reported": has_mock,
        "platform_outage": ev.get("platform_outage", False),
        "gps_degraded": ev.get("gps_degraded", False),
        "wrong_direction": has_wrong_dir,
    }

    driver_profile = ev.get("driver") or ev.get("driver_profile") or {}
    driver_analytics = ev.get("driver_analytics") or {}
    trip_conv = ev.get("trip_conversation") or ev.get("conversation")
    driver_dispute = (
        ev.get("driver_reason_and_agent_conversation") or ev.get("driver_dispute") or ev.get("driver_objection")
    )
    customer_rep = ev.get("customer_reports") or ev.get("complaints") or ev.get("customer_report")

    # Scrub evaluation labels, ground truth and generator metadata from all fields
    scrubbed_driver = scrub_evaluation_labels(driver_profile if isinstance(driver_profile, dict) else {})
    scrubbed_driver_analytics = scrub_evaluation_labels(driver_analytics if isinstance(driver_analytics, dict) else {})
    scrubbed_conv = scrub_evaluation_labels(trip_conv)
    scrubbed_dispute = scrub_evaluation_labels(driver_dispute)
    scrubbed_reports = scrub_evaluation_labels(customer_rep)
    scrubbed_telemetry = scrub_evaluation_labels(telemetry_dict)
    scrubbed_trip_data = scrub_evaluation_labels(trip_data)

    extra_kwargs: dict[str, Any] = {}
    if "state_variant" in ev and ev["state_variant"]:
        extra_kwargs["state_variant"] = str(ev["state_variant"])
    if "criteria_variant" in ev and ev["criteria_variant"]:
        extra_kwargs["criteria_variant"] = str(ev["criteria_variant"])

    return JevAssessmentInput(
        driver=scrubbed_driver,
        driver_analytics=scrubbed_driver_analytics,
        trip_conversation=scrubbed_conv,
        driver_reason_and_agent_conversation=scrubbed_dispute,
        customer_reports=scrubbed_reports,
        telemetry=scrubbed_telemetry,
        trip_data=scrubbed_trip_data,
        **extra_kwargs,
    )


# ---------------------------------------------------------------------------
# 8. Main Builder Entrypoint
# ---------------------------------------------------------------------------


def build_jev_state(
    bundle_or_event: Any,
    variant: str = "evidence_classref",
) -> dict[str, Any]:
    """Build the state dictionary sent to the Jev decision model.

    Variants:
    - 'evidence_classref': (default) compact, token-efficient natural-language measurements with units,
      empirical reference percentiles, and per-class reference medians.
    - 'evidence': compact measurements with empirical reference percentiles without class medians.
    - 'baseline': byte-for-byte legacy state payload (preserves raw points & structure)
    - 'features_numeric': cleaned state (no PII, no raw points) + derived kinematics, windows & risk bands
    - 'features_nl': cleaned state + natural-language rendered narrative (summary, windows, metrics)
    - 'features_both': cleaned state + both structured numeric features and natural-language narrative
    """
    # 1. Normalize input to JevAssessmentInput if given a raw dict
    if isinstance(bundle_or_event, JevAssessmentInput):
        inp = bundle_or_event
        # Recover bundle context if available
        raw_bundle: dict[str, Any] = inp.trip_data
    else:
        inp = map_telemetry_event_to_jev_input(bundle_or_event)
        raw_bundle = bundle_or_event if isinstance(bundle_or_event, dict) else {}

    # Variant 'baseline': byte-for-byte production state (scrubbed of generator ground truth)
    if variant == "baseline":
        return scrub_evaluation_labels(
            {
                "driver": inp.driver,
                "driver_analytics": inp.driver_analytics,
                "trip_conversation": inp.trip_conversation,
                "driver_reason_and_agent_conversation": inp.driver_reason_and_agent_conversation,
                "customer_reports": inp.customer_reports,
                "telemetry": inp.telemetry,
                "trip_data": inp.trip_data,
            }
        )

    # Extract points and pickup/dropoff
    points = inp.telemetry.get("points") or []
    pickup_raw = inp.trip_data.get("pickup") or raw_bundle.get("pickup")
    dropoff_raw = inp.trip_data.get("dropoff") or raw_bundle.get("dropoff")
    pickup_tuple = _extract_lon_lat(pickup_raw)
    dropoff_tuple = _extract_lon_lat(dropoff_raw)

    # Compute features
    kinematics = derive_kinematics(points)
    windows = compute_time_windowed_metrics(points, pickup=pickup_tuple, dropoff=dropoff_tuple, window_size_s=60.0)
    whole_phase = compute_whole_phase_metrics(points, raw_bundle, pickup=pickup_tuple, dropoff=dropoff_tuple)

    # Risk bands
    risk_bands: dict[str, dict[str, Any]] = {
        "detour_ratio": classify_metric_risk_band("detour_ratio", whole_phase["detour_ratio"]["value"]),
        "detour_ratio_approach": classify_metric_risk_band(
            "detour_ratio", whole_phase["detour_ratio"]["approach"]["value"]
        ),
        "detour_ratio_in_trip": classify_metric_risk_band(
            "detour_ratio", whole_phase["detour_ratio"]["in_trip"]["value"]
        ),
        "approach_ssd": classify_metric_risk_band("approach_ssd", whole_phase["approach_ssd"]["value"]),
        "davi": classify_metric_risk_band("davi", whole_phase["davi"]["value"]),
        "teleport_jump": classify_metric_risk_band(
            "teleport_jump",
            {
                "count": kinematics["teleport_jump_count"],
                "max_speed_kmh": kinematics["teleport_jump_max_kmh"],
                "mock": inp.telemetry.get("mock_location_reported", False),
            },
        ),
    }

    # Base state payload
    base_state = {
        "driver": inp.driver,
        "driver_analytics": inp.driver_analytics,
        "trip_conversation": inp.trip_conversation,
        "driver_reason_and_agent_conversation": inp.driver_reason_and_agent_conversation,
        "customer_reports": inp.customer_reports,
        "telemetry": copy.deepcopy(inp.telemetry),
        "trip_data": inp.trip_data,
    }

    # Clean PII and drop raw points
    cleaned_state = clean_state_payload(base_state)
    telem = cleaned_state.setdefault("telemetry", {})

    if variant in ("evidence", "evidence_classref"):
        ref_artifact = load_reference_artifact()
        is_classref = variant == "evidence_classref"
        measurements = build_evidence_measurements(
            kinematics=kinematics,
            windows=windows,
            whole_phase=whole_phase,
            mock_location_reported=inp.telemetry.get("mock_location_reported", False),
            reference_artifact=ref_artifact,
            include_class_medians=is_classref,
        )
        window_narratives = render_evidence_window_narratives(windows)
        summary = render_evidence_measurement_summary(measurements)

        cleaned_state["telemetry"] = {
            "measurements": measurements,
            "window_progression": window_narratives,
            "summary": summary,
        }

    elif variant == "features_numeric":
        telem["kinematics"] = kinematics
        telem["windows"] = windows
        telem["whole_phase"] = whole_phase
        telem["risk_bands"] = risk_bands

    elif variant == "features_nl":
        telem["narrative"] = render_natural_language_summary(windows, risk_bands)

    elif variant == "features_both":
        telem["kinematics"] = kinematics
        telem["windows"] = windows
        telem["whole_phase"] = whole_phase
        telem["risk_bands"] = risk_bands
        telem["narrative"] = render_natural_language_summary(windows, risk_bands)

    else:
        raise ValueError(f"Unknown state variant: {variant}")

    return cleaned_state

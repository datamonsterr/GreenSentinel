"""Clean, leak-audited tabular feature extraction for R3C / R3D fraud classifier.

Computes 37 deterministic measurements directly from raw telemetry points, pickup/dropoff
coordinates, planned route, and driver history without accessing or leaking synthetic label
proxies, incident kinds, objection text/presence, risk bands, or generator-computed scores.
"""

from __future__ import annotations

import math
from datetime import datetime
from typing import Any

import numpy as np

from src.services.fraud_classifier.guardrail import normalise_bundle

# All candidate features computed directly from raw signals
CANDIDATE_FEATURE_NAMES: list[str] = [
    # Kinematics & Speeds
    "speed_mean_kmh",
    "speed_median_kmh",
    "speed_std_kmh",
    "speed_p95_kmh",
    "speed_max_kmh",
    "speed_disagreement_mean_kmh",
    "speed_disagreement_max_kmh",
    "speed_disagreement_ratio_gt_20kmh",
    # Headings
    "heading_change_total_deg",
    "heading_change_mean_deg",
    "heading_change_max_deg",
    # Stops & Stationary
    "stationary_duration_total_s",
    "stationary_duration_max_s",
    "stop_count_gt_60s",
    "stop_count_gt_180s",
    "stationary_ratio",
    # Gaps & Teleport Jumps
    "data_gap_max_s",
    "data_gap_mean_s",
    "data_gap_count_gt_30s",
    "teleport_jump_count",
    "teleport_jump_max_kmh",
    # Mock Location Flags
    "mock_location_count",
    "mock_location_ratio",
    "has_mock_location",
    # Path & Detour Geometry
    "actual_path_length_m",
    "planned_route_length_m",
    "detour_ratio",
    "detour_excess_m",
    # Pickup Proximity & Directional Trends
    "initial_pickup_distance_m",
    "min_pickup_distance_m",
    "final_pickup_distance_m",
    "reached_pickup",
    "pickup_dist_trend_first_half",
    "pickup_dist_trend_second_half",
    "wrong_direction_ratio",
    # Dropoff Proximity
    "min_distance_to_dropoff_m",
    "final_distance_to_dropoff_m",
    "reached_dropoff",
    # Basic Telemetry Counts
    "point_count",
    "trip_duration_s",
    # Driver Profile & History
    "driver_rating",
    "driver_total_trips",
    "driver_acceptance_rate",
    "driver_cancellation_rate",
    "driver_w7_cancellation_rate",
    "driver_w30_cancellation_rate",
    "driver_dispute_history_count",
    "driver_prior_sanctions_count",
]

# Features kept after leak audit (univariate validation macro-F1 <= 0.30).
FEATURE_NAMES: list[str] = [
    "speed_std_kmh",
    "speed_p95_kmh",
    "speed_max_kmh",
    "speed_disagreement_mean_kmh",
    "speed_disagreement_max_kmh",
    "speed_disagreement_ratio_gt_20kmh",
    "heading_change_total_deg",
    "heading_change_mean_deg",
    "heading_change_max_deg",
    "stop_count_gt_60s",
    "stop_count_gt_180s",
    "data_gap_max_s",
    "data_gap_mean_s",
    "data_gap_count_gt_30s",
    "teleport_jump_count",
    "teleport_jump_max_kmh",
    "mock_location_count",
    "mock_location_ratio",
    "has_mock_location",
    "planned_route_length_m",
    "detour_ratio",
    "detour_excess_m",
    "min_pickup_distance_m",
    "reached_pickup",
    "pickup_dist_trend_first_half",
    "wrong_direction_ratio",
    "reached_dropoff",
    "point_count",
    "trip_duration_s",
    "driver_rating",
    "driver_total_trips",
    "driver_acceptance_rate",
    "driver_cancellation_rate",
    "driver_w7_cancellation_rate",
    "driver_w30_cancellation_rate",
    "driver_dispute_history_count",
    "driver_prior_sanctions_count",
]


def haversine_distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Compute great-circle distance between two GPS coordinates in meters."""
    earth_radius_m = 6371000.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2.0) ** 2
    return 2.0 * earth_radius_m * math.asin(math.sqrt(min(1.0, max(0.0, a))))


def calculate_bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate forward azimuth bearing in degrees [0, 360)."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dlon = math.radians(lon2 - lon1)
    y = math.sin(dlon) * math.cos(phi2)
    x = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(dlon)
    return (math.degrees(math.atan2(y, x)) + 360.0) % 360.0


def _parse_timestamp(ts: Any) -> float:
    """Parse ISO timestamp or float into epoch seconds."""
    if ts is None:
        return 0.0
    if isinstance(ts, (int, float)):
        return float(ts)
    s = str(ts).strip()
    if not s:
        return 0.0
    try:
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        return datetime.fromisoformat(s).timestamp()
    except Exception:
        return 0.0


def _to_float(val: Any, default: float = 0.0) -> float:
    """Safely convert value to finite float."""
    if val is None:
        return default
    try:
        f = float(val)
        return f if math.isfinite(f) else default
    except (ValueError, TypeError):
        return default


def extract_candidate_features(bundle: dict[str, Any]) -> dict[str, float]:
    """Extract all candidate raw telemetry and profile features from bundle."""
    bundle = normalise_bundle(bundle)
    pts = bundle.get("telemetry") or []
    n_pts = len(pts)

    times = [_parse_timestamp(p.get("occurred_at") or p.get("timestamp")) for p in pts]
    lats = [_to_float(p.get("latitude") if "latitude" in p else p.get("lat")) for p in pts]
    lons = [_to_float(p.get("longitude") if "longitude" in p else p.get("lon")) for p in pts]
    rep_speeds_kmh = [_to_float(p.get("speed_mps")) * 3.6 for p in pts]
    mocks = [1.0 if bool(p.get("mock_location_reported") or p.get("is_mock")) else 0.0 for p in pts]

    trip_dur = max(0.0, times[-1] - times[0]) if len(times) > 1 else 0.0

    dists: list[float] = []
    dts: list[float] = []
    derived_speeds: list[float] = []
    disagreements: list[float] = []
    teleport_count = 0.0
    teleport_max_kmh = 0.0
    stops_60 = 0.0
    stops_180 = 0.0
    total_stat_s = 0.0
    max_stat_s = 0.0
    cur_stat_s = 0.0

    for i in range(1, n_pts):
        d = haversine_distance_m(lats[i - 1], lons[i - 1], lats[i], lons[i])
        dt = max(0.001, times[i] - times[i - 1])
        dists.append(d)
        dts.append(dt)
        spd = (d / dt) * 3.6
        derived_speeds.append(spd)
        disagree = abs(rep_speeds_kmh[i] - spd)
        disagreements.append(disagree)

        # Teleport jump detection (> 120 km/h or > 500m in < 10s)
        if spd > 120.0 or (d > 500.0 and dt < 10.0):
            teleport_count += 1.0
            teleport_max_kmh = max(teleport_max_kmh, spd)

        # Stationary detection (speed < 3 km/h or dist < 5m)
        if spd < 3.0 or d < 5.0:
            cur_stat_s += dt
            total_stat_s += dt
        else:
            if cur_stat_s >= 60.0:
                stops_60 += 1.0
            if cur_stat_s >= 180.0:
                stops_180 += 1.0
            max_stat_s = max(max_stat_s, cur_stat_s)
            cur_stat_s = 0.0

    if cur_stat_s >= 60.0:
        stops_60 += 1.0
    if cur_stat_s >= 180.0:
        stops_180 += 1.0
    max_stat_s = max(max_stat_s, cur_stat_s)

    # Speed statistics
    if derived_speeds:
        sorted_speeds = sorted(derived_speeds)
        speed_mean = sum(derived_speeds) / len(derived_speeds)
        speed_med = sorted_speeds[len(sorted_speeds) // 2]
        p95_idx = min(len(sorted_speeds) - 1, int(0.95 * len(sorted_speeds)))
        speed_p95 = sorted_speeds[p95_idx]
        speed_max = sorted_speeds[-1]
        variance = sum((s - speed_mean) ** 2 for s in derived_speeds) / len(derived_speeds)
        speed_std = math.sqrt(variance)
    else:
        speed_mean = speed_med = speed_p95 = speed_max = speed_std = 0.0

    # Disagreements between sensor-reported speed and GPS-derived speed
    if disagreements:
        disagree_mean = sum(disagreements) / len(disagreements)
        disagree_max = max(disagreements)
        disagree_gt_20 = sum(1 for d in disagreements if d > 20.0) / len(disagreements)
    else:
        disagree_mean = disagree_max = disagree_gt_20 = 0.0

    # Time gaps
    if dts:
        gap_max = max(dts)
        gap_mean = sum(dts) / len(dts)
        gap_gt_30 = float(sum(1 for dt in dts if dt > 30.0))
    else:
        gap_max = gap_mean = gap_gt_30 = 0.0

    # Headings
    headings: list[float] = []
    for i in range(1, n_pts):
        headings.append(calculate_bearing_deg(lats[i - 1], lons[i - 1], lats[i], lons[i]))
    h_changes = [abs((headings[i] - headings[i - 1] + 180.0) % 360.0 - 180.0) for i in range(1, len(headings))]
    if h_changes:
        h_tot = sum(h_changes)
        h_mean = h_tot / len(h_changes)
        h_max = max(h_changes)
    else:
        h_tot = h_mean = h_max = 0.0

    # Path & Route length
    actual_path = float(sum(dists))
    pr = bundle.get("planned_route") or {}
    rt = bundle.get("route") or {}
    plan_len = _to_float(pr.get("distance_m") or rt.get("distance_m"), 0.0)

    # Pickup & Dropoff coordinates
    pickup = bundle.get("pickup") or {}
    dropoff = bundle.get("dropoff") or {}
    if isinstance(pickup, dict):
        p_lat = _to_float(pickup.get("latitude") or pickup.get("lat"))
        p_lon = _to_float(pickup.get("longitude") or pickup.get("lon"))
    elif isinstance(pickup, (list, tuple)) and len(pickup) >= 2:
        p_lon = _to_float(pickup[0])
        p_lat = _to_float(pickup[1])
    else:
        p_lat = p_lon = 0.0

    if isinstance(dropoff, dict):
        d_lat = _to_float(dropoff.get("latitude") or dropoff.get("lat"))
        d_lon = _to_float(dropoff.get("longitude") or dropoff.get("lon"))
    elif isinstance(dropoff, (list, tuple)) and len(dropoff) >= 2:
        d_lon = _to_float(dropoff[0])
        d_lat = _to_float(dropoff[1])
    else:
        d_lat = d_lon = 0.0

    if plan_len <= 1.0 and p_lat != 0.0 and d_lat != 0.0:
        plan_len = haversine_distance_m(p_lat, p_lon, d_lat, d_lon)
    detour_ratio = (actual_path / max(100.0, plan_len)) if plan_len > 0.0 else 1.0
    detour_excess = max(0.0, actual_path - plan_len)

    # Pickup distance trend
    if p_lat != 0.0 and p_lon != 0.0 and n_pts > 0:
        dist_pickup = [haversine_distance_m(lats[i], lons[i], p_lat, p_lon) for i in range(n_pts)]
        init_pickup = dist_pickup[0]
        min_pickup = min(dist_pickup)
        final_pickup = dist_pickup[-1]
        reached_pickup = 1.0 if min_pickup < 50.0 else 0.0

        half = n_pts // 2
        trend_first = (dist_pickup[half] - dist_pickup[0]) if half < n_pts else 0.0
        trend_second = (dist_pickup[-1] - dist_pickup[half]) if half < n_pts else 0.0
        wrong_dir_cnt = sum(1 for i in range(1, n_pts) if dist_pickup[i] > dist_pickup[i - 1] + 10.0)
        wrong_dir_ratio = wrong_dir_cnt / max(1, n_pts - 1)
    else:
        init_pickup = min_pickup = final_pickup = reached_pickup = 0.0
        trend_first = trend_second = wrong_dir_ratio = 0.0

    # Dropoff distance
    if d_lat != 0.0 and d_lon != 0.0 and n_pts > 0:
        dist_dropoff = [haversine_distance_m(lats[i], lons[i], d_lat, d_lon) for i in range(n_pts)]
        min_dropoff = min(dist_dropoff)
        final_dropoff = dist_dropoff[-1]
        reached_dropoff = 1.0 if min_dropoff < 100.0 else 0.0
    else:
        min_dropoff = final_dropoff = reached_dropoff = 0.0

    mock_cnt = float(sum(mocks))

    # Driver profile & historical analytics
    profile = bundle.get("driver_profile") or {}
    analytics = bundle.get("driver_analytics") or {}
    w7 = analytics.get("window_7d") or {}
    w30 = analytics.get("window_30d") or {}

    drv_rating = _to_float(profile.get("rating"), 4.8)
    drv_total_trips = _to_float(profile.get("total_trips"), 100.0)
    drv_accept = _to_float(profile.get("acceptance_rate"), 95.0)
    drv_cancel = _to_float(profile.get("cancellation_rate"), 0.02)
    drv_w7_cancel = _to_float(w7.get("cancellation_rate"), drv_cancel)
    drv_w30_cancel = _to_float(w30.get("cancellation_rate"), drv_cancel)
    drv_disputes = _to_float(analytics.get("dispute_history_count"), 0.0)
    drv_sanctions = _to_float(analytics.get("prior_sanctions_count"), 0.0)

    return {
        "speed_mean_kmh": speed_mean,
        "speed_median_kmh": speed_med,
        "speed_std_kmh": speed_std,
        "speed_p95_kmh": speed_p95,
        "speed_max_kmh": speed_max,
        "speed_disagreement_mean_kmh": disagree_mean,
        "speed_disagreement_max_kmh": disagree_max,
        "speed_disagreement_ratio_gt_20kmh": disagree_gt_20,
        "heading_change_total_deg": h_tot,
        "heading_change_mean_deg": h_mean,
        "heading_change_max_deg": h_max,
        "stationary_duration_total_s": total_stat_s,
        "stationary_duration_max_s": max_stat_s,
        "stop_count_gt_60s": stops_60,
        "stop_count_gt_180s": stops_180,
        "stationary_ratio": (total_stat_s / max(1.0, trip_dur)),
        "data_gap_max_s": gap_max,
        "data_gap_mean_s": gap_mean,
        "data_gap_count_gt_30s": gap_gt_30,
        "teleport_jump_count": teleport_count,
        "teleport_jump_max_kmh": teleport_max_kmh,
        "mock_location_count": mock_cnt,
        "mock_location_ratio": mock_cnt / max(1.0, float(n_pts)),
        "has_mock_location": 1.0 if mock_cnt > 0.0 else 0.0,
        "actual_path_length_m": actual_path,
        "planned_route_length_m": plan_len,
        "detour_ratio": detour_ratio,
        "detour_excess_m": detour_excess,
        "initial_pickup_distance_m": init_pickup,
        "min_pickup_distance_m": min_pickup,
        "final_pickup_distance_m": final_pickup,
        "reached_pickup": reached_pickup,
        "pickup_dist_trend_first_half": trend_first,
        "pickup_dist_trend_second_half": trend_second,
        "wrong_direction_ratio": wrong_dir_ratio,
        "min_distance_to_dropoff_m": min_dropoff,
        "final_distance_to_dropoff_m": final_dropoff,
        "reached_dropoff": reached_dropoff,
        "point_count": float(n_pts),
        "trip_duration_s": trip_dur,
        "driver_rating": drv_rating,
        "driver_total_trips": drv_total_trips,
        "driver_acceptance_rate": drv_accept,
        "driver_cancellation_rate": drv_cancel,
        "driver_w7_cancellation_rate": drv_w7_cancel,
        "driver_w30_cancellation_rate": drv_w30_cancel,
        "driver_dispute_history_count": drv_disputes,
        "driver_prior_sanctions_count": drv_sanctions,
    }


def extract_features(bundle: dict[str, Any]) -> tuple[dict[str, float], list[float]]:
    """Extract clean feature dict and float vector matching FEATURE_NAMES.

    Returns:
        (feature_dict, feature_vector)
    """
    candidates = extract_candidate_features(bundle)
    feat_dict = {f: candidates.get(f, 0.0) for f in FEATURE_NAMES}
    feat_vec = [feat_dict[f] for f in FEATURE_NAMES]
    return feat_dict, feat_vec


def extract_features_batch(bundles: list[dict[str, Any]]) -> np.ndarray:
    """Extract 2D float array (N, 37) of tabular features for a list of bundles."""
    n = len(bundles)
    mat = np.zeros((n, len(FEATURE_NAMES)), dtype=np.float32)
    for i, b in enumerate(bundles):
        _, vec = extract_features(b)
        mat[i] = vec
    return mat

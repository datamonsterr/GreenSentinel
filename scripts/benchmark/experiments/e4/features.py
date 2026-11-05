"""Feature extraction for Experiment E4 Hybrid GBM (Issue #513 / Epic #494).

Builds flattened numeric feature vectors from jev_state_builder features_numeric
state without leaking any ground-truth or cancellation label-proxy fields.
"""

from __future__ import annotations

import copy
import math
from typing import Any

from scripts.benchmark import run_10k
from src.services.jev_state_builder import build_jev_state

FEATURE_NAMES: list[str] = [
    # Kinematics
    "step_count",
    "speed_p50_kmh",
    "speed_p95_kmh",
    "teleport_jump_count",
    "teleport_jump_max_kmh",
    "mean_disagreement_kmh",
    "max_disagreement_kmh",
    "disagreement_ratio",
    # Whole-phase metrics
    "approach_ssd",
    "davi",
    "progress_ratio",
    "detour_ratio",
    "detour_ratio_approach",
    "detour_ratio_in_trip",
    "detour_actual_path_length_m",
    "detour_planned_route_length_m",
    "detour_is_estimated",
    "max_data_gap_s",
    "coverage",
    "mock_ratio",
    "guardrail_nominal",
    "guardrail_blocked",
    # Telemetry basics
    "stationary_duration_s",
    "max_speed_kmh",
    "mock_location_reported",
    "platform_outage",
    "gps_degraded",
    "wrong_direction",
    "maneuvers_count",
    "has_wrong_dir_maneuver",
    "has_stop_maneuver",
    # Risk bands
    "risk_band_detour_ratio",
    "risk_band_detour_ratio_approach",
    "risk_band_detour_ratio_in_trip",
    "risk_band_approach_ssd",
    "risk_band_davi",
    "risk_band_teleport_jump",
    # Windows
    "num_windows",
    "windows_total_moving_s",
    "windows_total_stationary_s",
    "windows_max_stationary_s",
    "windows_max_moving_s",
    "windows_max_median_speed",
    "windows_mean_median_speed",
    "windows_total_dist_change_m",
    "windows_max_dist_change_m",
    "windows_total_heading_change",
    "windows_max_heading_change",
    # Driver profile & analytics
    "driver_rating",
    "driver_acceptance_rate",
    "driver_cancellation_rate",
    "driver_total_trips",
    "driver_window_7d_trips",
    "driver_window_7d_cancellations",
    "driver_window_7d_cancellation_rate",
    "driver_window_7d_complaints",
    "driver_window_30d_trips",
    "driver_window_30d_cancellations",
    "driver_window_30d_cancellation_rate",
    "driver_window_30d_complaints",
    "driver_dispute_history_count",
    "driver_prior_sanctions_count",
    "driver_historical_cancellation_ratio",
    # Text length & presence
    "has_trip_conversation",
    "trip_conversation_len",
    "has_driver_dispute",
    "driver_dispute_len",
    "has_customer_report",
    "customer_report_len",
    "passenger_rating",
]

_RISK_BAND_MAP: dict[str, float] = {
    "normal": 0.0,
    "elevated": 1.0,
    "high": 2.0,
    "unknown": -1.0,
}


def _to_float(val: Any, default: float = float("nan")) -> float:
    if val is None:
        return default
    try:
        f = float(val)
        return f if math.isfinite(f) else default
    except (ValueError, TypeError):
        return default


def _risk_band_to_num(band_dict: Any) -> float:
    if isinstance(band_dict, dict):
        band_str = str(band_dict.get("band") or "unknown").lower()
        return _RISK_BAND_MAP.get(band_str, -1.0)
    return -1.0


def extract_features(bundle: dict[str, Any]) -> tuple[dict[str, float], list[float]]:
    """Extract flattened numeric features from a bundle.

    1. Applies run_10k._scrub and blank_cancellation_enums to remove label proxies and metadata.
    2. Builds features_numeric state via jev_state_builder.
    3. Returns (feature_dict, feature_vector) aligned with FEATURE_NAMES.
    """
    cleaned_input = copy.deepcopy(bundle)
    cleaned_input.setdefault("trip", {})
    cleaned_input.setdefault("assignment", {})
    scrubbed = run_10k.blank_cancellation_enums(run_10k._scrub(cleaned_input))
    state = build_jev_state(scrubbed, variant="features_numeric")

    telem = state.get("telemetry") or {}
    kin = telem.get("kinematics") or {}
    wp = telem.get("whole_phase") or {}
    rb = telem.get("risk_bands") or {}
    windows = telem.get("windows") or []
    maneuvers = telem.get("maneuvers") or []
    driver = state.get("driver") or {}
    analytics = state.get("driver_analytics") or {}
    trip_data = state.get("trip_data") or {}

    # Kinematics
    step_count = _to_float(kin.get("step_count"), 0.0)
    speed_p50 = _to_float(kin.get("speed_p50_kmh"), 0.0)
    speed_p95 = _to_float(kin.get("speed_p95_kmh"), 0.0)
    teleport_cnt = _to_float(kin.get("teleport_jump_count"), 0.0)
    teleport_max = _to_float(kin.get("teleport_jump_max_kmh"), 0.0)
    mean_disagree = _to_float(kin.get("mean_disagreement_kmh"), 0.0)
    max_disagree = _to_float(kin.get("max_disagreement_kmh"), 0.0)
    disagree_ratio = _to_float(kin.get("disagreement_ratio"), 0.0)

    # Whole phase
    approach_ssd = _to_float((wp.get("approach_ssd") or {}).get("value"), 0.0)
    davi = _to_float((wp.get("davi") or {}).get("value"), 0.0)
    progress_ratio = _to_float((wp.get("progress_ratio") or {}).get("value"), 0.0)

    detour_dict = wp.get("detour_ratio") or {}
    detour_val = _to_float(detour_dict.get("value"), 1.0)
    detour_app = _to_float(((detour_dict.get("approach") or {}).get("value")), 1.0)
    detour_trip = _to_float(((detour_dict.get("in_trip") or {}).get("value")), 1.0)
    detour_act = _to_float(detour_dict.get("actual_path_length_m"), 0.0)
    detour_plan = _to_float(detour_dict.get("planned_route_length_m"), 0.0)
    detour_est = 1.0 if detour_dict.get("is_estimated") else 0.0

    max_data_gap = _to_float(wp.get("max_data_gap_s"), 0.0)
    coverage = _to_float(wp.get("coverage"), 1.0)
    mock_ratio = _to_float(wp.get("mock_ratio"), 0.0)

    gstate = str(wp.get("guardrail_state") or "nominal").lower()
    guardrail_nom = 1.0 if gstate == "nominal" else 0.0
    guardrail_blk = 1.0 if gstate != "nominal" else 0.0

    # Telemetry basics
    stationary_duration = _to_float(telem.get("stationary_duration_s"), 0.0)
    max_speed = _to_float(telem.get("max_speed_kmh"), 0.0)
    mock_loc = 1.0 if telem.get("mock_location_reported") else 0.0
    plat_out = 1.0 if telem.get("platform_outage") else 0.0
    gps_deg = 1.0 if telem.get("gps_degraded") else 0.0
    wrong_dir = 1.0 if telem.get("wrong_direction") else 0.0

    maneuvers_count = float(len(maneuvers))
    has_wrong_dir_m = 1.0 if any(m.get("action") == "wrong_direction" for m in maneuvers) else 0.0
    has_stop_m = 1.0 if any(m.get("action") == "stop" and m.get("duration_s", 0) >= 180 for m in maneuvers) else 0.0

    # Risk bands
    rb_detour = _risk_band_to_num(rb.get("detour_ratio"))
    rb_detour_app = _risk_band_to_num(rb.get("detour_ratio_approach"))
    rb_detour_trip = _risk_band_to_num(rb.get("detour_ratio_in_trip"))
    rb_ssd = _risk_band_to_num(rb.get("approach_ssd"))
    rb_davi = _risk_band_to_num(rb.get("davi"))
    rb_teleport = _risk_band_to_num(rb.get("teleport_jump"))

    # Windows
    num_win = float(len(windows))
    mov_s = sum(_to_float(w.get("moving_seconds"), 0.0) for w in windows)
    stat_s = sum(_to_float(w.get("stationary_seconds"), 0.0) for w in windows)
    max_stat_s = max([_to_float(w.get("stationary_seconds"), 0.0) for w in windows], default=0.0)
    max_mov_s = max([_to_float(w.get("moving_seconds"), 0.0) for w in windows], default=0.0)
    speeds = [_to_float(w.get("median_implied_speed_kmh"), 0.0) for w in windows]
    max_v_med = max(speeds, default=0.0)
    mean_v_med = sum(speeds) / len(speeds) if speeds else 0.0
    dist_ch = [_to_float(w.get("distance_to_pickup_change_m"), 0.0) for w in windows]
    total_dist_ch = sum(dist_ch)
    max_dist_ch = max(dist_ch, default=0.0)
    hd_ch = [_to_float(w.get("heading_change_deg"), 0.0) for w in windows]
    total_hd_ch = sum(hd_ch)
    max_hd_ch = max(hd_ch, default=0.0)

    # Driver profile & analytics
    drv_rating = _to_float(driver.get("rating"), 4.5)
    drv_accept = _to_float(driver.get("acceptance_rate"), 90.0)
    drv_cancel = _to_float(driver.get("cancellation_rate"), 0.0)
    drv_trips = _to_float(driver.get("total_trips"), 0.0)

    w7 = analytics.get("window_7d") or {}
    w7_trips = _to_float(w7.get("trips"), 0.0)
    w7_cancels = _to_float(w7.get("cancellations"), 0.0)
    w7_crate = _to_float(w7.get("cancellation_rate"), 0.0)
    w7_complaints = _to_float(w7.get("complaints"), 0.0)

    w30 = analytics.get("window_30d") or {}
    w30_trips = _to_float(w30.get("trips"), 0.0)
    w30_cancels = _to_float(w30.get("cancellations"), 0.0)
    w30_crate = _to_float(w30.get("cancellation_rate"), 0.0)
    w30_complaints = _to_float(w30.get("complaints"), 0.0)

    drv_disputes = _to_float(analytics.get("dispute_history_count"), 0.0)
    drv_sanctions = _to_float(analytics.get("prior_sanctions_count"), 0.0)
    drv_hist_crate = _to_float(analytics.get("historical_cancellation_ratio"), 0.0)

    # Text length & presence
    trip_conv = state.get("trip_conversation")
    has_conv = 1.0 if trip_conv else 0.0
    conv_len = float(len(str(trip_conv))) if trip_conv else 0.0

    drv_dispute = state.get("driver_reason_and_agent_conversation")
    has_dispute = 1.0 if drv_dispute else 0.0
    dispute_len = float(len(str(drv_dispute))) if drv_dispute else 0.0

    cust_rep = state.get("customer_reports")
    has_rep = 1.0 if cust_rep else 0.0
    rep_len = float(len(str(cust_rep))) if cust_rep else 0.0

    passenger_rating = _to_float(trip_data.get("passenger_rating"), 5.0)

    feat_dict: dict[str, float] = {
        "step_count": step_count,
        "speed_p50_kmh": speed_p50,
        "speed_p95_kmh": speed_p95,
        "teleport_jump_count": teleport_cnt,
        "teleport_jump_max_kmh": teleport_max,
        "mean_disagreement_kmh": mean_disagree,
        "max_disagreement_kmh": max_disagree,
        "disagreement_ratio": disagree_ratio,
        "approach_ssd": approach_ssd,
        "davi": davi,
        "progress_ratio": progress_ratio,
        "detour_ratio": detour_val,
        "detour_ratio_approach": detour_app,
        "detour_ratio_in_trip": detour_trip,
        "detour_actual_path_length_m": detour_act,
        "detour_planned_route_length_m": detour_plan,
        "detour_is_estimated": detour_est,
        "max_data_gap_s": max_data_gap,
        "coverage": coverage,
        "mock_ratio": mock_ratio,
        "guardrail_nominal": guardrail_nom,
        "guardrail_blocked": guardrail_blk,
        "stationary_duration_s": stationary_duration,
        "max_speed_kmh": max_speed,
        "mock_location_reported": mock_loc,
        "platform_outage": plat_out,
        "gps_degraded": gps_deg,
        "wrong_direction": wrong_dir,
        "maneuvers_count": maneuvers_count,
        "has_wrong_dir_maneuver": has_wrong_dir_m,
        "has_stop_maneuver": has_stop_m,
        "risk_band_detour_ratio": rb_detour,
        "risk_band_detour_ratio_approach": rb_detour_app,
        "risk_band_detour_ratio_in_trip": rb_detour_trip,
        "risk_band_approach_ssd": rb_ssd,
        "risk_band_davi": rb_davi,
        "risk_band_teleport_jump": rb_teleport,
        "num_windows": num_win,
        "windows_total_moving_s": mov_s,
        "windows_total_stationary_s": stat_s,
        "windows_max_stationary_s": max_stat_s,
        "windows_max_moving_s": max_mov_s,
        "windows_max_median_speed": max_v_med,
        "windows_mean_median_speed": mean_v_med,
        "windows_total_dist_change_m": total_dist_ch,
        "windows_max_dist_change_m": max_dist_ch,
        "windows_total_heading_change": total_hd_ch,
        "windows_max_heading_change": max_hd_ch,
        "driver_rating": drv_rating,
        "driver_acceptance_rate": drv_accept,
        "driver_cancellation_rate": drv_cancel,
        "driver_total_trips": drv_trips,
        "driver_window_7d_trips": w7_trips,
        "driver_window_7d_cancellations": w7_cancels,
        "driver_window_7d_cancellation_rate": w7_crate,
        "driver_window_7d_complaints": w7_complaints,
        "driver_window_30d_trips": w30_trips,
        "driver_window_30d_cancellations": w30_cancels,
        "driver_window_30d_cancellation_rate": w30_crate,
        "driver_window_30d_complaints": w30_complaints,
        "driver_dispute_history_count": drv_disputes,
        "driver_prior_sanctions_count": drv_sanctions,
        "driver_historical_cancellation_ratio": drv_hist_crate,
        "has_trip_conversation": has_conv,
        "trip_conversation_len": conv_len,
        "has_driver_dispute": has_dispute,
        "driver_dispute_len": dispute_len,
        "has_customer_report": has_rep,
        "customer_report_len": rep_len,
        "passenger_rating": passenger_rating,
    }

    feat_vec = [feat_dict[k] for k in FEATURE_NAMES]
    return feat_dict, feat_vec

"""Deterministic generator for synthesized_vietnam_trip benchmark profile.

Generates 1,000 distinct Vietnam street trips grounded in lawful pinned OSRM road geometry:
- 700 no_violation (nominal baseline, severity None)
- 300 violations:
  - 30 P0 (ERR-05: Fake GPS / teleportation)
  - 135 P1 (70 ERR-02: prolonged stall >= 180s, 65 ERR-03: route deviation)
  - 135 P2 (75 ERR-01: unjustified cancel after short stall, 60 ERR-04: phantom trip)
  - Total violations: 270 P1/P2 (90%) and 30 P0 (10%).
  - 0 insufficient_evidence.

Grounded in documented Vietnamese road geometry & street names (Hanoi & Ho Chi Minh City).
Driver train/test split: 80% train, 20% test (strictly disjoint drivers).
Deterministic rerun guaranteed by seed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import sys
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import pyarrow as pa  # noqa: E402
import pyarrow.parquet as pq  # noqa: E402
import yaml  # noqa: E402

from scripts.benchmark.dialogue_synth import (  # noqa: E402
    synthesize_customer_report,
    synthesize_dialogue,
    synthesize_objection_reason,
)
from scripts.benchmark.population_synth import (  # noqa: E402
    synthesize_drivers,
    synthesize_passengers,
)

BENCHMARK_CONFIG_PATH = REPO_ROOT / "config" / "benchmark_distribution.yaml"


def load_benchmark_config() -> dict[str, Any]:
    if BENCHMARK_CONFIG_PATH.exists():
        with open(BENCHMARK_CONFIG_PATH, encoding="utf-8") as f:
            return yaml.safe_load(f)
    return {
        "benchmark": {
            "scheduler": {
                "hour_weights": [
                    0.018,
                    0.012,
                    0.008,
                    0.006,
                    0.0053,
                    0.0061,
                    0.014,
                    0.028,
                    0.040,
                    0.046,
                    0.050,
                    0.053,
                    0.055,
                    0.052,
                    0.050,
                    0.053,
                    0.060,
                    0.0698,
                    0.0719,
                    0.062,
                    0.052,
                    0.047,
                    0.035,
                    0.025,
                ],
                "weekday_weights": [0.1370, 0.1565, 0.1676, 0.1451, 0.1381, 0.1419, 0.1138],
            }
        }
    }


from src.services.feature_engineering import compute_feature_window  # noqa: E402

GENERATOR_VERSION = "v1.1.0-vietnam-road"
DEFAULT_SEED = 20261015

SEVERITY_POLICY = {
    "no_violation": None,
    "ERR-01": "P2",
    "ERR-02": "P1",
    "ERR-03": "P1",
    "ERR-04": "P2",
    "ERR-05": "P0",
}

SCENARIO_FOR_LABEL = {
    "no_violation": "normal_trip",
    "ERR-01": "driver_stall_cancel",
    "ERR-02": "driver_stall_cancel",
    "ERR-03": "route_deviation",
    "ERR-04": "normal_trip",
    "ERR-05": "gps_spoofing",
}

CONTEXT_FOR_LABEL = {
    "no_violation": "normal_trip",
    "ERR-01": "err01_unjustified_cancel",
    "ERR-02": "err02_stall",
    "ERR-03": "err03_deviation",
    "ERR-04": "err04_phantom",
    "ERR-05": "err05_fake_gps",
}

CORRIDORS_PATHS = (
    REPO_ROOT / "tests" / "fixtures" / "road_telemetry" / "vietnam_road_corridors.json",
    REPO_ROOT / "data" / "benchmark-10k" / "vietnam_road_corridors.json",
)


def load_pinned_corridors() -> list[dict[str, Any]]:
    for path in CORRIDORS_PATHS:
        if path.exists():
            with open(path, encoding="utf-8") as f:
                corridors = json.load(f)
            if corridors and isinstance(corridors, list):
                return corridors
    raise FileNotFoundError(
        "Lawful Vietnam road corridors fixture missing. "
        "Road-source outages fail build or use explicitly verified cached fixtures; "
        "never silently invent road traces."
    )


def haversine_m(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 2 * r * math.asin(min(1.0, math.sqrt(a)))


def bearing_deg(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dlon = math.radians(lon2 - lon1)
    y = math.sin(dlon) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dlon)
    return (math.degrees(math.atan2(y, x)) + 360.0) % 360.0


def polyline_cumulative_distances(coords: list[list[float]]) -> list[float]:
    dist = [0.0]
    for i in range(1, len(coords)):
        d = haversine_m(coords[i - 1][0], coords[i - 1][1], coords[i][0], coords[i][1])
        dist.append(dist[-1] + d)
    return dist


def interpolate_along_polyline(
    coords: list[list[float]], cum_dist: list[float], target_m: float
) -> tuple[float, float, int]:
    total = cum_dist[-1]
    target_m = max(0.0, min(target_m, total))
    for i in range(1, len(cum_dist)):
        if cum_dist[i] >= target_m:
            seg_len = cum_dist[i] - cum_dist[i - 1]
            if seg_len < 1e-9:
                return float(coords[i][0]), float(coords[i][1]), i
            frac = (target_m - cum_dist[i - 1]) / seg_len
            lon = coords[i - 1][0] + frac * (coords[i][0] - coords[i - 1][0])
            lat = coords[i - 1][1] + frac * (coords[i][1] - coords[i - 1][1])
            return lon, lat, i
    return float(coords[-1][0]), float(coords[-1][1]), len(coords) - 1


def point_to_segment_distance_m(
    p_lon: float, p_lat: float, a_lon: float, a_lat: float, b_lon: float, b_lat: float
) -> float:
    lat_mid = (a_lat + b_lat) / 2.0
    cos_lat = math.cos(math.radians(lat_mid))
    m_per_deg_lat = 111139.0
    m_per_deg_lon = 111139.0 * cos_lat

    ax, ay = a_lon * m_per_deg_lon, a_lat * m_per_deg_lat
    bx, by = b_lon * m_per_deg_lon, b_lat * m_per_deg_lat
    px, py = p_lon * m_per_deg_lon, p_lat * m_per_deg_lat

    dx, dy = bx - ax, by - ay
    seg_len_sq = dx * dx + dy * dy
    if seg_len_sq < 1e-6:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / seg_len_sq))
    proj_x = ax + t * dx
    proj_y = ay + t * dy
    return math.hypot(px - proj_x, py - proj_y)


def point_to_polyline_min_distance_m(p_lon: float, p_lat: float, coords: list[list[float]]) -> float:
    if len(coords) < 2:
        return 0.0
    min_d = float("inf")
    for i in range(len(coords) - 1):
        d = point_to_segment_distance_m(p_lon, p_lat, coords[i][0], coords[i][1], coords[i + 1][0], coords[i + 1][1])
        if d < min_d:
            min_d = d
    return min_d


def get_street_at_distance(steps: list[dict[str, Any]], d_m: float) -> str:
    cur = 0.0
    for s in steps:
        cur += s.get("distance_m", 0.0)
        if cur >= d_m:
            name = s.get("name")
            if name and name != "Unnamed Road":
                return name
    for s in steps:
        name = s.get("name")
        if name and name != "Unnamed Road":
            return name
    return "Đường phố Hà Nội"


def extract_subpolyline(
    coords: list[list[float]], cum_dist: list[float], s_start: float, s_end: float
) -> list[list[float]]:
    p_start_lon, p_start_lat, idx_start = interpolate_along_polyline(coords, cum_dist, s_start)
    p_end_lon, p_end_lat, idx_end = interpolate_along_polyline(coords, cum_dist, s_end)

    sub = [[round(p_start_lon, 7), round(p_start_lat, 7)]]
    for i in range(idx_start, idx_end):
        if s_start < cum_dist[i] < s_end:
            sub.append([round(coords[i][0], 7), round(coords[i][1], 7)])
    sub.append([round(p_end_lon, 7), round(p_end_lat, 7)])
    if len(sub) < 2:
        sub.append([round(coords[-1][0], 7), round(coords[-1][1], 7)])
    return sub


def build_vietnam_trip(
    idx: int,
    label: str,
    split: str,
    driver: dict[str, Any],
    passenger: dict[str, Any],
    cfg: dict,
    master_seed: int,
    corridors: list[dict[str, Any]],
) -> dict[str, Any]:
    trip_seed = (master_seed % (2**31)) * 31337 + idx
    rng = random.Random(trip_seed)

    corr = corridors[trip_seed % len(corridors)]
    coords = corr["coordinates"]
    cum_dist = polyline_cumulative_distances(coords)
    total_m = cum_dist[-1]
    steps = corr.get("steps", [])

    min_trip_m = min(1200.0, total_m * 0.5)
    max_trip_m = total_m
    trip_distance_m = rng.uniform(min_trip_m, max_trip_m)
    s_start = rng.uniform(0.0, max(0.0, total_m - trip_distance_m))
    s_end = s_start + trip_distance_m

    p_start_lon, p_start_lat, _ = interpolate_along_polyline(coords, cum_dist, s_start)
    p_end_lon, p_end_lat, _ = interpolate_along_polyline(coords, cum_dist, s_end)

    sub_polyline = extract_subpolyline(coords, cum_dist, s_start, s_end)

    start_street = get_street_at_distance(steps, s_start)
    end_street = get_street_at_distance(steps, s_end)

    city = corr["city"]
    pickup = {
        "lat": round(p_start_lat, 7),
        "lon": round(p_start_lon, 7),
        "name": f"{start_street}, {city}",
        "street": start_street,
        "city": city,
    }
    dropoff = {
        "lat": round(p_end_lat, 7),
        "lon": round(p_end_lon, 7),
        "name": f"{end_street}, {city}",
        "street": end_street,
        "city": city,
    }

    # Scheduled origin time
    hour_w = cfg["benchmark"]["scheduler"]["hour_weights"]
    day_w = cfg["benchmark"]["scheduler"]["weekday_weights"]
    day = rng.choices(range(7), weights=day_w, k=1)[0]
    hour = rng.choices(range(24), weights=hour_w, k=1)[0]
    week = rng.randrange(4)
    base_dt = datetime(2026, 10, 1, 0, 0, 0, tzinfo=UTC)
    t0 = base_dt + timedelta(
        days=week * 7 + day,
        hours=hour,
        minutes=rng.randrange(60),
        seconds=rng.randrange(60),
    )

    cadence_s = 10.0
    avg_speed_mps = rng.uniform(8.0, 12.0)
    nominal_duration_s = max(60.0, trip_distance_m / avg_speed_mps)
    n_points = max(12, int(round(nominal_duration_s / cadence_s)))

    points: list[dict[str, Any]] = []
    cross_track_residuals: list[float] = []

    m_per_deg_lat = 111139.0
    cos_lat = math.cos(math.radians(p_start_lat))
    m_per_deg_lon = 111139.0 * cos_lat

    departure_mode = "none"

    if label == "no_violation":
        for k in range(n_points):
            frac = k / max(1, n_points - 1)
            target_m = s_start + frac * trip_distance_m
            lon_raw, lat_raw, _ = interpolate_along_polyline(coords, cum_dist, target_m)

            noise_lat_m = max(-3.5, min(3.5, rng.gauss(0.0, 1.2)))
            noise_lon_m = max(-3.5, min(3.5, rng.gauss(0.0, 1.2)))

            lon_cur = round(lon_raw + noise_lon_m / m_per_deg_lon, 7)
            lat_cur = round(lat_raw + noise_lat_m / m_per_deg_lat, 7)
            ts = t0 + timedelta(seconds=k * cadence_s)

            if k == 0:
                speed = 0.0
                bear = bearing_deg(lon_raw, lat_raw, sub_polyline[1][0], sub_polyline[1][1])
            else:
                prev = points[-1]
                dt = (ts - datetime.fromisoformat(prev["occurred_at"])).total_seconds()
                d_seg = haversine_m(prev["longitude"], prev["latitude"], lon_cur, lat_cur)
                speed = round(d_seg / max(1e-6, dt), 2)
                bear = round(bearing_deg(prev["longitude"], prev["latitude"], lon_cur, lat_cur), 1)

            res_m = point_to_polyline_min_distance_m(lon_cur, lat_cur, sub_polyline)
            cross_track_residuals.append(res_m)

            points.append(
                {
                    "occurred_at": ts.isoformat().replace("+00:00", "Z"),
                    "latitude": lat_cur,
                    "longitude": lon_cur,
                    "speed_mps": speed,
                    "bearing_deg": bear,
                    "accuracy_m": round(rng.uniform(3.0, 8.0), 1),
                    "sequence": k + 1,
                    "mock_location_reported": False,
                    "app_state": "FOREGROUND",
                    "network_state": "CONNECTED_4G",
                    "gps_state": "FINE",
                    "latency_ms": int(rng.uniform(40, 120)),
                    "data_gap_s": 0.0,
                    "davi_score": 0.02,
                    "distance_to_pickup_m": 0.0,
                }
            )

    elif label == "ERR-01":
        # Driver unjustified cancel after short stall (45s-90s)
        stall_points = rng.randint(5, 9)
        for k in range(stall_points):
            noise_lat_m = max(-1.5, min(1.5, rng.gauss(0.0, 0.5)))
            noise_lon_m = max(-1.5, min(1.5, rng.gauss(0.0, 0.5)))
            lon_cur = round(p_start_lon + noise_lon_m / m_per_deg_lon, 7)
            lat_cur = round(p_start_lat + noise_lat_m / m_per_deg_lat, 7)
            ts = t0 + timedelta(seconds=k * cadence_s)
            speed = 0.0
            bear = round(rng.uniform(0.0, 360.0), 1)

            res_m = point_to_polyline_min_distance_m(lon_cur, lat_cur, sub_polyline)
            cross_track_residuals.append(res_m)

            points.append(
                {
                    "occurred_at": ts.isoformat().replace("+00:00", "Z"),
                    "latitude": lat_cur,
                    "longitude": lon_cur,
                    "speed_mps": speed,
                    "bearing_deg": bear,
                    "accuracy_m": round(rng.uniform(3.0, 6.0), 1),
                    "sequence": k + 1,
                    "mock_location_reported": False,
                    "app_state": "FOREGROUND",
                    "network_state": "CONNECTED_4G",
                    "gps_state": "FINE",
                    "latency_ms": int(rng.uniform(40, 120)),
                    "data_gap_s": 0.0,
                    "davi_score": 0.05,
                    "distance_to_pickup_m": 0.0,
                }
            )

    elif label == "ERR-02":
        # Prolonged stall (200s - 320s)
        stall_points = rng.randint(20, 32)
        for k in range(stall_points):
            noise_lat_m = max(-2.0, min(2.0, rng.gauss(0.0, 0.6)))
            noise_lon_m = max(-2.0, min(2.0, rng.gauss(0.0, 0.6)))
            lon_cur = round(p_start_lon + noise_lon_m / m_per_deg_lon, 7)
            lat_cur = round(p_start_lat + noise_lat_m / m_per_deg_lat, 7)
            ts = t0 + timedelta(seconds=k * cadence_s)
            speed = 0.0
            bear = round(rng.uniform(0.0, 360.0), 1)

            res_m = point_to_polyline_min_distance_m(lon_cur, lat_cur, sub_polyline)
            cross_track_residuals.append(res_m)

            points.append(
                {
                    "occurred_at": ts.isoformat().replace("+00:00", "Z"),
                    "latitude": lat_cur,
                    "longitude": lon_cur,
                    "speed_mps": speed,
                    "bearing_deg": bear,
                    "accuracy_m": round(rng.uniform(3.0, 6.0), 1),
                    "sequence": k + 1,
                    "mock_location_reported": False,
                    "app_state": "FOREGROUND",
                    "network_state": "CONNECTED_4G",
                    "gps_state": "FINE",
                    "latency_ms": int(rng.uniform(40, 120)),
                    "data_gap_s": 0.0,
                    "davi_score": 0.12,
                    "distance_to_pickup_m": 0.0,
                }
            )

    elif label == "ERR-03":
        # Route deviation: departures are intentional
        departure_mode = "intentional_detour"
        k_depart = max(3, int(n_points * 0.3))
        detour_heading = None
        for k in range(n_points):
            frac = min(1.0, k / max(1, n_points - 1))
            target_m = s_start + frac * trip_distance_m
            lon_raw, lat_raw, _ = interpolate_along_polyline(coords, cum_dist, target_m)

            if k < k_depart:
                lon_cur = round(lon_raw + rng.gauss(0, 1.0) / m_per_deg_lon, 7)
                lat_cur = round(lat_raw + rng.gauss(0, 1.0) / m_per_deg_lat, 7)
            else:
                steps_away = k - k_depart + 1
                detour_dist_m = min(400.0, steps_away * 35.0)
                if detour_heading is None:
                    nominal_b = bearing_deg(lon_raw, lat_raw, sub_polyline[-1][0], sub_polyline[-1][1])
                    detour_heading = (nominal_b + 90.0) % 360.0
                rad = math.radians(detour_heading)
                d_lon = detour_dist_m * math.sin(rad)
                d_lat = detour_dist_m * math.cos(rad)
                lon_cur = round(lon_raw + d_lon / m_per_deg_lon, 7)
                lat_cur = round(lat_raw + d_lat / m_per_deg_lat, 7)

            ts = t0 + timedelta(seconds=k * cadence_s)
            if k == 0:
                speed = 0.0
                bear = bearing_deg(lon_raw, lat_raw, sub_polyline[1][0], sub_polyline[1][1])
            else:
                prev = points[-1]
                dt = (ts - datetime.fromisoformat(prev["occurred_at"])).total_seconds()
                d_seg = haversine_m(prev["longitude"], prev["latitude"], lon_cur, lat_cur)
                speed = round(d_seg / max(1e-6, dt), 2)
                bear = round(bearing_deg(prev["longitude"], prev["latitude"], lon_cur, lat_cur), 1)

            res_m = point_to_polyline_min_distance_m(lon_cur, lat_cur, sub_polyline)
            cross_track_residuals.append(res_m)

            points.append(
                {
                    "occurred_at": ts.isoformat().replace("+00:00", "Z"),
                    "latitude": lat_cur,
                    "longitude": lon_cur,
                    "speed_mps": speed,
                    "bearing_deg": bear,
                    "accuracy_m": round(rng.uniform(4.0, 10.0), 1),
                    "sequence": k + 1,
                    "mock_location_reported": False,
                    "app_state": "FOREGROUND",
                    "network_state": "CONNECTED_4G",
                    "gps_state": "FINE",
                    "latency_ms": int(rng.uniform(40, 120)),
                    "data_gap_s": 0.0,
                    "davi_score": 0.45 if k >= k_depart else 0.02,
                    "distance_to_pickup_m": 0.0,
                }
            )

    elif label == "ERR-04":
        # Phantom trip (ghost ride on road without passenger)
        for k in range(n_points):
            frac = k / max(1, n_points - 1)
            target_m = s_start + frac * trip_distance_m
            lon_raw, lat_raw, _ = interpolate_along_polyline(coords, cum_dist, target_m)

            noise_lat_m = max(-3.0, min(3.0, rng.gauss(0.0, 1.0)))
            noise_lon_m = max(-3.0, min(3.0, rng.gauss(0.0, 1.0)))
            lon_cur = round(lon_raw + noise_lon_m / m_per_deg_lon, 7)
            lat_cur = round(lat_raw + noise_lat_m / m_per_deg_lat, 7)
            ts = t0 + timedelta(seconds=k * cadence_s)

            if k == 0:
                speed = 0.0
                bear = bearing_deg(lon_raw, lat_raw, sub_polyline[1][0], sub_polyline[1][1])
            else:
                prev = points[-1]
                dt = (ts - datetime.fromisoformat(prev["occurred_at"])).total_seconds()
                d_seg = haversine_m(prev["longitude"], prev["latitude"], lon_cur, lat_cur)
                speed = round(d_seg / max(1e-6, dt), 2)
                bear = round(bearing_deg(prev["longitude"], prev["latitude"], lon_cur, lat_cur), 1)

            res_m = point_to_polyline_min_distance_m(lon_cur, lat_cur, sub_polyline)
            cross_track_residuals.append(res_m)

            points.append(
                {
                    "occurred_at": ts.isoformat().replace("+00:00", "Z"),
                    "latitude": lat_cur,
                    "longitude": lon_cur,
                    "speed_mps": speed,
                    "bearing_deg": bear,
                    "accuracy_m": round(rng.uniform(3.0, 8.0), 1),
                    "sequence": k + 1,
                    "mock_location_reported": False,
                    "app_state": "FOREGROUND",
                    "network_state": "CONNECTED_4G",
                    "gps_state": "FINE",
                    "latency_ms": int(rng.uniform(40, 120)),
                    "data_gap_s": 0.0,
                    "davi_score": 0.03,
                    "distance_to_pickup_m": 0.0,
                }
            )

    elif label == "ERR-05":
        # Fake GPS / Spoofing: intentional teleportation departure
        departure_mode = "gps_teleportation_spoof"
        k_teleport = max(3, int(n_points * 0.4))
        for k in range(n_points):
            frac = k / max(1, n_points - 1)
            target_m = s_start + frac * trip_distance_m
            lon_raw, lat_raw, _ = interpolate_along_polyline(coords, cum_dist, target_m)

            if k < k_teleport:
                lon_cur = round(lon_raw + rng.gauss(0, 1.0) / m_per_deg_lon, 7)
                lat_cur = round(lat_raw + rng.gauss(0, 1.0) / m_per_deg_lat, 7)
                mock = False
            else:
                jump_m = 1200.0 + (k - k_teleport) * 200.0
                lon_cur = round(lon_raw + jump_m / m_per_deg_lon, 7)
                lat_cur = round(lat_raw + jump_m / m_per_deg_lat, 7)
                mock = True

            ts = t0 + timedelta(seconds=k * cadence_s)
            if k == 0:
                speed = 0.0
                bear = bearing_deg(lon_raw, lat_raw, sub_polyline[1][0], sub_polyline[1][1])
            else:
                prev = points[-1]
                dt = (ts - datetime.fromisoformat(prev["occurred_at"])).total_seconds()
                d_seg = haversine_m(prev["longitude"], prev["latitude"], lon_cur, lat_cur)
                speed = round(d_seg / max(1e-6, dt), 2)
                bear = round(bearing_deg(prev["longitude"], prev["latitude"], lon_cur, lat_cur), 1)

            res_m = point_to_polyline_min_distance_m(lon_cur, lat_cur, sub_polyline)
            cross_track_residuals.append(res_m)

            points.append(
                {
                    "occurred_at": ts.isoformat().replace("+00:00", "Z"),
                    "latitude": lat_cur,
                    "longitude": lon_cur,
                    "speed_mps": speed,
                    "bearing_deg": bear,
                    "accuracy_m": 0.5 if mock else round(rng.uniform(3.0, 8.0), 1),
                    "sequence": k + 1,
                    "mock_location_reported": mock,
                    "app_state": "BACKGROUND" if mock else "FOREGROUND",
                    "network_state": "DISCONNECTED" if mock else "CONNECTED_4G",
                    "gps_state": "SPOOFED" if mock else "FINE",
                    "latency_ms": int(rng.uniform(10, 40) if mock else rng.uniform(40, 120)),
                    "data_gap_s": 0.0,
                    "davi_score": 0.95 if mock else 0.02,
                    "distance_to_pickup_m": 0.0,
                }
            )

    first_ts = points[0]["occurred_at"]
    last_ts = points[-1]["occurred_at"]

    # Lifecycle per class
    if label in ("ERR-01", "ERR-02", "ERR-03"):
        actor = {"ERR-01": "driver", "ERR-02": "passenger", "ERR-03": "passenger"}[label]
        reason = {
            "ERR-01": "driver_cancelled_unjustified",
            "ERR-02": "driver_stalled_no_show",
            "ERR-03": "route_deviation",
        }[label]
        trip_status, cancelled_at, completed_at = "cancelled", last_ts, None
        assign_state, arrived_at, started_at, ended_at = "cancelled", None, None, last_ts
    elif label == "ERR-04":
        trip_status, cancelled_at, completed_at = "completed", None, last_ts
        actor, reason = None, None
        assign_state, arrived_at, started_at, ended_at = "completed", None, None, last_ts
    else:  # no_violation, ERR-05
        trip_status, cancelled_at, completed_at = "completed", None, last_ts
        actor, reason = None, None
        assign_state, arrived_at, started_at, ended_at = "completed", first_ts, first_ts, last_ts

    traffic = {
        "congestion_level": "heavy" if (label == "no_violation" and rng.random() < 0.1) else "clear",
        "source": "synthetic",
        "is_simulated": True,
        "observed_at": first_ts,
    }

    platform_incident = (
        {
            "id": f"inc-{trip_seed}",
            "kind": "TELEMETRY_ANOMALY",
            "occurred_at": first_ts,
            "resolved_at": last_ts,
            "severity": "P0",
        }
        if label == "ERR-05"
        else None
    )

    incidents = [platform_incident] if platform_incident else []
    try:
        compute_feature_window(points, incidents)
    except Exception:
        pass

    # Dialogue synthesis
    context = CONTEXT_FOR_LABEL[label]
    conv_split = "test" if split == "test" else "train"
    facts = {
        "pickup_name": pickup["name"],
        "dropoff_name": dropoff["name"],
        "street_name": start_street,
    }
    try:
        dialogue = synthesize_dialogue(rng, context, facts, split=conv_split)
    except Exception:
        dialogue = []

    cust_report = synthesize_customer_report(rng, context, facts) if label != "no_violation" else None
    driver_objection = synthesize_objection_reason(rng, context, facts) if label in ("ERR-01", "ERR-02") else None

    # Trip and assignment identifiers (UUID5 for determinism)
    trip_ref = f"vn_trip_{idx + 1:04d}"
    ns = uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8")
    trip_id = str(uuid.uuid5(ns, f"greensentinel:vietnam:trip:{trip_ref}"))
    assign_id = str(uuid.uuid5(ns, f"greensentinel:vietnam:assignment:{trip_ref}"))

    # Driver profile: portable without organization_id (tenant assigned at execution)
    clean_driver = dict(driver)
    clean_driver["organization_id"] = None

    fare_amount = max(35000, int(round((trip_distance_m / 1000.0) * 14000 + 15000, -3)))

    max_cross_track = max(cross_track_residuals) if cross_track_residuals else 0.0

    return {
        "trip_id": trip_id,
        "trip_ref": trip_ref,
        "release": "synthesized_vietnam_trip",
        "split": split,
        "city": city,
        "label": label,
        "severity": SEVERITY_POLICY[label],
        "requested_at": t0.isoformat().replace("+00:00", "Z"),
        "pickup": pickup,
        "dropoff": dropoff,
        "route": {
            "distance_m": int(round(trip_distance_m)),
            "duration_s": int(round(nominal_duration_s)),
            "geometry": {"type": "LineString", "coordinates": sub_polyline},
            "corridor_id": corr["corridor_id"],
            "street_names": [s for s in corr.get("street_names", []) if s],
        },
        "planned_route": {
            "distance_m": int(round(trip_distance_m)),
            "duration_s": int(round(nominal_duration_s)),
            "geometry": {"type": "LineString", "coordinates": sub_polyline},
            "provider": "osrm",
            "license": "ODbL - OpenStreetMap contributors",
        },
        "telemetry": points,
        "trip": {
            "id": trip_id,
            "status": trip_status,
            "fare_amount": fare_amount,
            "currency": "VND",
            "cancelled_at": cancelled_at,
            "completed_at": completed_at,
        },
        "assignment": {
            "id": assign_id,
            "state": assign_state,
            "offered_at": t0.isoformat().replace("+00:00", "Z"),
            "accepted_at": t0.isoformat().replace("+00:00", "Z"),
            "arrived_at": arrived_at,
            "started_at": started_at,
            "ended_at": ended_at,
            "cancellation_actor": actor,
            "cancellation_reason": reason,
        },
        "vehicle": {
            "id": clean_driver.get("vehicle_id", f"veh-vn-{idx + 1:04d}"),
            "license_plate": f"{29 if city == 'Hanoi' else 51}{rng.choice(['A', 'E', 'F', 'G'])}-{rng.randint(100, 999)}.{rng.randint(10, 99)}",
            "make": rng.choice(["VinFast", "Toyota", "Hyundai", "Honda"]),
            "model": rng.choice(["VF e34", "VF 5 Plus", "Vios", "Accent", "City"]),
        },
        "vehicle_id": clean_driver.get("vehicle_id", f"veh-vn-{idx + 1:04d}"),
        "driver_id": clean_driver["id"],
        "driver_profile": clean_driver,
        "passenger_id": passenger["id"],
        "scenario": SCENARIO_FOR_LABEL[label],
        "conversation": dialogue,
        "customer_report": cust_report,
        "driver_objection": driver_objection,
        "traffic_observation": traffic,
        "platform_incident": platform_incident,
        "geography_provenance": {
            "country": "VN",
            "city": city,
            "locale": "vi-VN",
            "provider": "OSRM / OpenStreetMap contributors",
            "license": "ODbL",
            "attribution": "© OpenStreetMap contributors",
            "corridor_id": corr["corridor_id"],
        },
        "generation_audit": {
            "generator_version": GENERATOR_VERSION,
            "seed": trip_seed,
            "corridor_id": corr["corridor_id"],
            "departure_mode": departure_mode,
            "max_cross_track_m": round(max_cross_track, 2),
        },
    }


def generate_vietnam_dataset(
    out_dir: Path,
    seed: int = DEFAULT_SEED,
) -> tuple[Path, str, dict[str, Any]]:
    out_dir.mkdir(parents=True, exist_ok=True)
    cfg = load_benchmark_config()
    corridors = load_pinned_corridors()

    # Exact requirements:
    # 700 no_violation
    # 300 violations:
    #   30 P0 (ERR-05)
    #   135 P1 (70 ERR-02, 65 ERR-03)
    #   135 P2 (75 ERR-01, 60 ERR-04)
    # Total = 1000
    target_labels: list[str] = (
        ["no_violation"] * 700 + ["ERR-01"] * 75 + ["ERR-02"] * 70 + ["ERR-03"] * 65 + ["ERR-04"] * 60 + ["ERR-05"] * 30
    )

    rng = random.Random(seed)
    rng.shuffle(target_labels)

    # Synthetic population: 200 distinct drivers (160 train, 40 test)
    # PII-free synthetic Vietnamese profiles
    total_drivers = 200
    drivers = synthesize_drivers(random.Random(seed + 101), total_drivers)
    passengers = synthesize_passengers(random.Random(seed + 202), 500)

    train_drivers = drivers[:160]
    test_drivers = drivers[160:]
    train_driver_ids = {d["id"] for d in train_drivers}
    test_driver_ids = {d["id"] for d in test_drivers}

    # 800 train, 200 test trips
    trips: list[dict[str, Any]] = []
    for idx, label in enumerate(target_labels):
        split = "train" if idx < 800 else "test"
        driver_pool = train_drivers if split == "train" else test_drivers
        driver = driver_pool[idx % len(driver_pool)]
        passenger = passengers[idx % len(passengers)]

        trip = build_vietnam_trip(
            idx=idx,
            label=label,
            split=split,
            driver=driver,
            passenger=passenger,
            cfg=cfg,
            master_seed=seed,
            corridors=corridors,
        )
        trips.append(trip)

    trips_jsonl = out_dir / "trips.jsonl"
    labels_csv = out_dir / "labels.csv"

    hasher = hashlib.sha256()
    with trips_jsonl.open("w", encoding="utf-8") as f_jsonl:
        for t in trips:
            line = json.dumps(t, ensure_ascii=False) + "\n"
            f_jsonl.write(line)
            hasher.update(line.encode("utf-8"))
    trips_sha256 = hasher.hexdigest()

    l_hasher = hashlib.sha256()
    with labels_csv.open("w", encoding="utf-8") as f_csv:
        f_csv.write("trip_ref,label,release,split\n")
        l_hasher.update(b"trip_ref,label,release,split\n")
        for t in trips:
            row = f"{t['trip_ref']},{t['label']},{t['release']},{t['split']}\n"
            f_csv.write(row)
            l_hasher.update(row.encode("utf-8"))
    labels_sha256 = l_hasher.hexdigest()

    # Sample 100
    sample_100_jsonl = out_dir / "sample_100.jsonl"
    with sample_100_jsonl.open("w", encoding="utf-8") as f_s100:
        for t in trips[:100]:
            f_s100.write(json.dumps(t, ensure_ascii=False) + "\n")

    sample_100_parquet = out_dir / "sample_100.parquet"
    sample_table = pa.Table.from_pylist(
        [
            {
                "trip_ref": t["trip_ref"],
                "label": t["label"],
                "split": t["split"],
                "pickup_lat": t["pickup"]["lat"],
                "pickup_lon": t["pickup"]["lon"],
                "dropoff_lat": t["dropoff"]["lat"],
                "dropoff_lon": t["dropoff"]["lon"],
                "distance_m": t["route"]["distance_m"],
                "duration_s": t["route"]["duration_s"],
                "telemetry_count": len(t["telemetry"]),
            }
            for t in trips[:100]
        ]
    )
    pq.write_table(sample_table, sample_100_parquet)

    # Class and severity breakdown
    class_counts = {
        "no_violation": sum(1 for t in trips if t["label"] == "no_violation"),
        "ERR-01": sum(1 for t in trips if t["label"] == "ERR-01"),
        "ERR-02": sum(1 for t in trips if t["label"] == "ERR-02"),
        "ERR-03": sum(1 for t in trips if t["label"] == "ERR-03"),
        "ERR-04": sum(1 for t in trips if t["label"] == "ERR-04"),
        "ERR-05": sum(1 for t in trips if t["label"] == "ERR-05"),
    }
    severity_counts = {
        "P0": sum(1 for t in trips if t["severity"] == "P0"),
        "P1": sum(1 for t in trips if t["severity"] == "P1"),
        "P2": sum(1 for t in trips if t["severity"] == "P2"),
        "no_violation": sum(1 for t in trips if t["severity"] is None),
    }

    manifest = {
        "release": "synthesized_vietnam_trip",
        "generator_version": GENERATOR_VERSION,
        "seed": seed,
        "total_trips": len(trips),
        "class_counts": class_counts,
        "severity_counts": severity_counts,
        "splits": {
            "train": sum(1 for t in trips if t["split"] == "train"),
            "test": sum(1 for t in trips if t["split"] == "test"),
        },
        "drivers": {
            "distinct_drivers": len(train_driver_ids | test_driver_ids),
            "train_drivers": len(train_driver_ids),
            "test_drivers": len(test_driver_ids),
            "leakage": len(train_driver_ids & test_driver_ids),
        },
        "geography_bounds": {
            "Vietnam": {"min_lat": 8.0, "max_lat": 24.0, "min_lon": 102.0, "max_lon": 110.0},
            "Hanoi": {"min_lat": 20.90, "max_lat": 21.30, "min_lon": 105.70, "max_lon": 106.00},
            "Ho Chi Minh City": {"min_lat": 10.65, "max_lat": 10.90, "min_lon": 106.55, "max_lon": 106.85},
        },
        "trips_sha256": trips_sha256,
        "generated_at": datetime.now(UTC).isoformat(),
    }

    manifest_path = out_dir / "manifest.json"
    manifest_bytes = json.dumps(manifest, indent=2).encode("utf-8")
    manifest_path.write_bytes(manifest_bytes)
    manifest_sha256 = hashlib.sha256(manifest_bytes).hexdigest()

    checksums = {
        "trips.jsonl": trips_sha256,
        "labels.csv": labels_sha256,
        "manifest.json": manifest_sha256,
    }
    checksums_path = out_dir / "checksums.json"
    checksums_path.write_text(json.dumps(checksums, indent=2), encoding="utf-8")

    return out_dir, trips_sha256, manifest


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--out",
        type=Path,
        default=REPO_ROOT / "data" / "benchmark-10k" / "profiles" / "synthesized_vietnam_trip",
        help="Destination directory",
    )
    ap.add_argument("--seed", type=int, default=DEFAULT_SEED, help="RNG seed")
    args = ap.parse_args(argv)

    dest, sha, manifest = generate_vietnam_dataset(args.out, seed=args.seed)
    print(f"Generated {manifest['total_trips']} Vietnam trips into {dest}")
    print(f"trips.jsonl sha256: {sha}")
    print("Class counts:", manifest["class_counts"])
    print("Severity counts:", manifest["severity_counts"])
    print("Splits:", manifest["splits"])
    return 0


if __name__ == "__main__":
    sys.exit(main())

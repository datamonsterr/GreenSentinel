"""Sequence and static trajectory channel extraction for R3F 1D-CNN classifier.

Resamples raw telemetry trajectory to 128 uniform steps across 7 channels:
1. Normalized derived speed (speed_mps / 30.0)
2. Normalized heading delta (wrap_to_pi(curr - prev) / pi)
3. Log pickup distance (log1p(dist_m) / 10.0)
4. Log dropoff distance (log1p(dist_m) / 10.0)
5. Normalized accuracy (min(acc_m, 100) / 50.0)
6. Normalized dt gap (min(dt_s, 60) / 10.0)
7. Mock location flag (1.0 or 0.0)

Plus 6 static trip-context features:
1. Log chord distance (log1p(chord_m) / 10.0)
2. Log duration (log1p(duration_s) / 8.0)
3. Log total path length (log1p(path_m) / 10.0)
4. Tortuosity ratio (min(path / disp, 10.0) / 5.0)
5. Dropoff progress clipped in [-2.0, 2.0]
6. Log min pickup distance (log1p(min_pickup_m) / 10.0)
"""

from __future__ import annotations

import datetime
import math
from typing import Any

import numpy as np

from src.services.fraud_classifier.guardrail import normalise_bundle

NUM_STEPS = 128
NUM_CHANNELS = 7
NUM_STATIC_FEATURES = 6

DEFAULT_CLASSES: list[str] = [
    "no_violation",
    "ERR-01",
    "ERR-02",
    "ERR-03",
    "ERR-04",
    "ERR-05",
    "insufficient_evidence",
]

MODEL_CLASSES: list[str] = [
    "no_violation",
    "ERR-01",
    "ERR-02",
    "ERR-03",
    "ERR-04",
    "ERR-05",
]


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Haversine distance between two coordinates in meters."""
    r = 6371000.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)

    a = math.sin(dphi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2.0) ** 2
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(max(0.0, 1.0 - a)))
    return r * c


def compute_bearing_rad(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Compute compass bearing from (lat1, lon1) to (lat2, lon2) in radians [-pi, pi]."""
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dlambda = math.radians(lon2 - lon1)

    y = math.sin(dlambda) * math.cos(phi2)
    x = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(dlambda)
    return math.atan2(y, x)


def wrap_to_pi(angle_rad: float) -> float:
    """Wrap angle in radians to [-pi, pi]."""
    return (angle_rad + math.pi) % (2.0 * math.pi) - math.pi


def extract_coords(obj: Any) -> tuple[float, float] | None:
    """Extract valid (lat, lon) from dict or sequence."""
    if not obj:
        return None
    if isinstance(obj, dict):
        lat = obj.get("lat") if "lat" in obj else obj.get("latitude")
        lon = obj.get("lon") if "lon" in obj else obj.get("longitude")
        if lat is not None and lon is not None:
            try:
                fl_lat, fl_lon = float(lat), float(lon)
                if -90.0 <= fl_lat <= 90.0 and -180.0 <= fl_lon <= 180.0:
                    return fl_lat, fl_lon
            except (ValueError, TypeError):
                return None
    elif isinstance(obj, (list, tuple)) and len(obj) >= 2:
        try:
            v0, v1 = float(obj[0]), float(obj[1])
            if abs(v0) > abs(v1) and v0 > 90.0 and -90.0 <= v1 <= 90.0:
                return v1, v0
            if -90.0 <= v0 <= 90.0 and -180.0 <= v1 <= 180.0:
                return v0, v1
        except (ValueError, TypeError):
            return None
    return None


def parse_timestamp_to_seconds(ts: Any) -> float:
    """Parse timestamp representation into float epoch seconds."""
    if isinstance(ts, (int, float)):
        return float(ts)
    if isinstance(ts, str):
        cleaned = ts.replace("Z", "+00:00")
        try:
            dt = datetime.datetime.fromisoformat(cleaned)
            return dt.timestamp()
        except Exception:
            pass
    return 0.0


def extract_raw_points(bundle: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract clean raw telemetry points."""
    pts = bundle.get("telemetry") or bundle.get("points") or []
    out: list[dict[str, Any]] = []

    for p in pts:
        if not isinstance(p, dict):
            continue
        lat = p.get("latitude") if "latitude" in p else p.get("lat")
        lon = p.get("longitude") if "longitude" in p else p.get("lon")
        if lat is None or lon is None:
            continue
        try:
            fl_lat = float(lat)
            fl_lon = float(lon)
        except (ValueError, TypeError):
            continue

        if not (-90.0 <= fl_lat <= 90.0 and -180.0 <= fl_lon <= 180.0):
            continue

        t_sec = parse_timestamp_to_seconds(p.get("occurred_at") or p.get("timestamp") or 0.0)
        acc = p.get("accuracy_m") or p.get("accuracy")
        try:
            fl_acc = float(acc) if acc is not None else 10.0
        except (ValueError, TypeError):
            fl_acc = 10.0

        mock = bool(p.get("mock_location_reported") or p.get("is_mock"))

        out.append(
            {
                "lat": fl_lat,
                "lon": fl_lon,
                "t": t_sec,
                "accuracy_m": fl_acc,
                "mock": mock,
            }
        )

    out.sort(key=lambda x: x["t"])
    return out


def resample_telemetry(
    raw_points: list[dict[str, Any]],
    num_steps: int = NUM_STEPS,
) -> list[dict[str, Any]]:
    """Resample telemetry trajectory to exactly num_steps points via linear interpolation."""
    if raw_points and ("latitude" in raw_points[0] or "occurred_at" in raw_points[0]):
        raw_points = extract_raw_points({"telemetry": raw_points})

    if not raw_points:
        return [
            {
                "lat": 0.0,
                "lon": 0.0,
                "t": float(i),
                "accuracy_m": 50.0,
                "mock": False,
            }
            for i in range(num_steps)
        ]

    n = len(raw_points)
    if n == 1:
        p0 = raw_points[0]
        return [
            {
                "lat": p0["lat"],
                "lon": p0["lon"],
                "t": float(i),
                "accuracy_m": p0["accuracy_m"],
                "mock": p0["mock"],
            }
            for i in range(num_steps)
        ]

    t0 = raw_points[0]["t"]
    t_arr = np.array([p["t"] - t0 for p in raw_points], dtype=np.float64)
    lat_arr = np.array([p["lat"] for p in raw_points], dtype=np.float64)
    lon_arr = np.array([p["lon"] for p in raw_points], dtype=np.float64)
    acc_arr = np.array([p["accuracy_m"] for p in raw_points], dtype=np.float64)
    mock_arr = np.array([1.0 if p["mock"] else 0.0 for p in raw_points], dtype=np.float64)

    if t_arr[-1] <= t_arr[0]:
        t_arr = np.linspace(0.0, float(n - 1), n)

    total_time = t_arr[-1]
    t_query = np.linspace(0.0, total_time, num_steps)

    res_lat = np.interp(t_query, t_arr, lat_arr)
    res_lon = np.interp(t_query, t_arr, lon_arr)
    res_acc = np.interp(t_query, t_arr, acc_arr)
    res_mock = np.interp(t_query, t_arr, mock_arr) >= 0.5

    out: list[dict[str, Any]] = []
    for i in range(num_steps):
        out.append(
            {
                "lat": float(res_lat[i]),
                "lon": float(res_lon[i]),
                "t": float(t_query[i]),
                "accuracy_m": float(res_acc[i]),
                "mock": bool(res_mock[i]),
            }
        )
    return out


def extract_r3f_features(
    bundle: dict[str, Any],
    augment: bool = False,
    num_steps: int = NUM_STEPS,
) -> tuple[np.ndarray, np.ndarray]:
    """Extract normalized sequence (NUM_CHANNELS, NUM_STEPS) and static vector (NUM_STATIC_FEATURES,).

    Returns:
        (seq_data, static_data) as float32 numpy arrays.
    """
    bundle = normalise_bundle(bundle)
    raw_points = extract_raw_points(bundle)
    pickup = extract_coords(bundle.get("pickup"))
    dropoff = extract_coords(bundle.get("dropoff"))

    resampled = resample_telemetry(raw_points, num_steps=num_steps)

    p_lat = pickup[0] if pickup else (resampled[0]["lat"] if resampled else 21.0)
    p_lon = pickup[1] if pickup else (resampled[0]["lon"] if resampled else 105.8)
    d_lat = dropoff[0] if dropoff else (resampled[-1]["lat"] if resampled else 21.0)
    d_lon = dropoff[1] if dropoff else (resampled[-1]["lon"] if resampled else 105.8)

    seq_data = np.zeros((NUM_CHANNELS, num_steps), dtype=np.float32)

    total_path_m = 0.0
    prev_bearing: float | None = None
    min_pickup_m = 1e9

    d_dropoff_start = haversine_m(resampled[0]["lat"], resampled[0]["lon"], d_lat, d_lon)
    d_dropoff_end = haversine_m(resampled[-1]["lat"], resampled[-1]["lon"], d_lat, d_lon)

    for i in range(num_steps):
        curr = resampled[i]
        c_lat, c_lon = curr["lat"], curr["lon"]

        if i == 0:
            dt_s = 0.0
            speed_mps = 0.0
            heading_ch = 0.0
        else:
            prev = resampled[i - 1]
            dt_s = max(0.001, curr["t"] - prev["t"])
            step_dist = haversine_m(prev["lat"], prev["lon"], c_lat, c_lon)
            total_path_m += step_dist
            speed_mps = min(step_dist / dt_s, 60.0)

            if step_dist > 0.5:
                curr_bearing = compute_bearing_rad(prev["lat"], prev["lon"], c_lat, c_lon)
                if prev_bearing is not None:
                    heading_ch = wrap_to_pi(curr_bearing - prev_bearing) / math.pi
                else:
                    heading_ch = 0.0
                prev_bearing = curr_bearing
            else:
                heading_ch = 0.0

        dist_pickup = haversine_m(c_lat, c_lon, p_lat, p_lon)
        dist_dropoff = haversine_m(c_lat, c_lon, d_lat, d_lon)
        if dist_pickup < min_pickup_m:
            min_pickup_m = dist_pickup

        acc = min(float(curr["accuracy_m"]), 100.0) / 50.0
        gap = min(float(dt_s), 60.0) / 10.0
        mock = 1.0 if curr["mock"] else 0.0

        seq_data[0, i] = float(speed_mps / 30.0)
        seq_data[1, i] = float(heading_ch)
        seq_data[2, i] = float(math.log1p(dist_pickup) / 10.0)
        seq_data[3, i] = float(math.log1p(dist_dropoff) / 10.0)
        seq_data[4, i] = float(acc)
        seq_data[5, i] = float(gap)
        seq_data[6, i] = float(mock)

    chord_m = haversine_m(p_lat, p_lon, d_lat, d_lon)
    duration_s = max(1.0, resampled[-1]["t"] - resampled[0]["t"]) if len(resampled) > 1 else 1.0
    disp_m = haversine_m(resampled[0]["lat"], resampled[0]["lon"], resampled[-1]["lat"], resampled[-1]["lon"])
    tortuosity = total_path_m / max(disp_m, 50.0)
    dropoff_progress = (d_dropoff_start - d_dropoff_end) / max(chord_m, 10.0)

    static_data = np.zeros(NUM_STATIC_FEATURES, dtype=np.float32)
    static_data[0] = float(math.log1p(chord_m) / 10.0)
    static_data[1] = float(math.log1p(duration_s) / 8.0)
    static_data[2] = float(math.log1p(total_path_m) / 10.0)
    static_data[3] = float(min(tortuosity, 10.0) / 5.0)
    static_data[4] = float(np.clip(dropoff_progress, -2.0, 2.0))
    static_data[5] = float(math.log1p(min_pickup_m) / 10.0)

    return seq_data, static_data


def extract_r3f_features_batch(
    bundles: list[dict[str, Any]],
    num_steps: int = NUM_STEPS,
) -> tuple[np.ndarray, np.ndarray]:
    """Extract batch arrays for sequence and static features."""
    n = len(bundles)
    batch_seq = np.zeros((n, NUM_CHANNELS, num_steps), dtype=np.float32)
    batch_static = np.zeros((n, NUM_STATIC_FEATURES), dtype=np.float32)

    for i, b in enumerate(bundles):
        seq, stat = extract_r3f_features(b, num_steps=num_steps)
        batch_seq[i] = seq
        batch_static[i] = stat

    return batch_seq, batch_static

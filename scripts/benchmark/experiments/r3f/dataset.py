"""Dataset utilities, resampling, feature extraction, and domain randomisation for R3F.

Imports core channels and feature extraction logic from src.services.fraud_classifier.features_sequence
to maintain a single source of truth across research and production.
"""

from __future__ import annotations

import math
import random
from typing import Any

import numpy as np

from src.services.fraud_classifier.features_sequence import (
    DEFAULT_CLASSES,
    MODEL_CLASSES,
    NUM_CHANNELS,
    NUM_STATIC_FEATURES,
    NUM_STEPS,
    compute_bearing_rad,
    extract_coords,
    extract_raw_points,
    haversine_m,
    parse_timestamp_to_seconds,
    resample_telemetry,
    wrap_to_pi,
)
from src.services.fraud_classifier.features_sequence import (
    extract_r3f_features as _extract_r3f_features_base,
)

__all__ = [
    "DEFAULT_CLASSES",
    "MODEL_CLASSES",
    "NUM_CHANNELS",
    "NUM_STATIC_FEATURES",
    "NUM_STEPS",
    "apply_domain_randomisation",
    "compute_bearing_rad",
    "extract_coords",
    "extract_r3f_features",
    "extract_raw_points",
    "haversine_m",
    "parse_timestamp_to_seconds",
    "resample_telemetry",
    "wrap_to_pi",
]


def apply_domain_randomisation(
    points: list[dict[str, Any]],
    pickup: tuple[float, float] | None = None,
    dropoff: tuple[float, float] | None = None,
    enable_noise: bool = True,
    enable_rotation: bool = True,
    enable_dropout: bool = True,
    enable_timewarp: bool = True,
    enable_rate_jitter: bool = True,
) -> tuple[list[dict[str, Any]], tuple[float, float] | None, tuple[float, float] | None]:
    """Apply domain randomisation augmentations to raw points and reference coords."""
    if not points:
        return points, pickup, dropoff

    pts = [dict(p) for p in points]
    n = len(pts)

    # 1. Sampling-rate jitter: downsample raw pings to simulate sparse ping profiles (15-50 points)
    if enable_rate_jitter and n > 25 and random.random() < 0.85:
        target_k = random.randint(15, min(n - 1, 55))
        mid_indices = np.sort(np.random.choice(np.arange(1, n - 1), size=target_k - 2, replace=False))
        chosen_indices = [0] + mid_indices.tolist() + [n - 1]
        pts = [pts[i] for i in chosen_indices]
        n = len(pts)

    # 1b. Approach & window variation: cross-generator robustness for start/end offsets
    if pickup and n > 5 and random.random() < 0.70:
        d_start_p = haversine_m(pts[0]["lat"], pts[0]["lon"], pickup[0], pickup[1])
        if d_start_p < 200.0:
            app_dist = random.uniform(600.0, 1800.0)
            app_bearing = random.uniform(-math.pi, math.pi)
            start_lat = pickup[0] - (app_dist / 111000.0) * math.cos(app_bearing)
            start_lon = pickup[1] - (app_dist / (111000.0 * max(0.1, math.cos(math.radians(pickup[0]))))) * math.sin(
                app_bearing
            )
            n_app = random.randint(6, 14)
            dt_app = random.uniform(8.0, 20.0)
            t_base = pts[0]["t"] - n_app * dt_app
            app_pts = []
            for k in range(n_app):
                a = k / float(n_app)
                app_pts.append(
                    {
                        "lat": start_lat + a * (pts[0]["lat"] - start_lat),
                        "lon": start_lon + a * (pts[0]["lon"] - start_lon),
                        "t": t_base + k * dt_app,
                        "accuracy_m": random.uniform(5.0, 15.0),
                        "mock": False,
                    }
                )
            pts = app_pts + pts
            n = len(pts)

    if n > 20 and random.random() < 0.60:
        crop_ratio = random.uniform(0.40, 0.95)
        keep_n = max(12, int(n * crop_ratio))
        pts = pts[:keep_n]
        n = len(pts)

    # 2. Global rotation around centroid
    if enable_rotation and n > 0:
        theta = random.uniform(-math.pi, math.pi)
        mean_lat = sum(p["lat"] for p in pts) / n
        mean_lon = sum(p["lon"] for p in pts) / n
        cos_lat = max(0.1, math.cos(math.radians(mean_lat)))

        def rotate_coords(lat: float, lon: float) -> tuple[float, float]:
            x = (lon - mean_lon) * 111000.0 * cos_lat
            y = (lat - mean_lat) * 111000.0
            x_rot = x * math.cos(theta) - y * math.sin(theta)
            y_rot = x * math.sin(theta) + y * math.cos(theta)
            new_lon = mean_lon + x_rot / (111000.0 * cos_lat)
            new_lat = mean_lat + y_rot / 111000.0
            return new_lat, new_lon

        for p in pts:
            p["lat"], p["lon"] = rotate_coords(p["lat"], p["lon"])
        if pickup:
            pickup = rotate_coords(pickup[0], pickup[1])
        if dropoff:
            dropoff = rotate_coords(dropoff[0], dropoff[1])

    # 3. Gaussian position noise (5-30m std per trip)
    if enable_noise and n > 0:
        sigma_m = random.uniform(5.0, 30.0)
        mean_lat = pts[0]["lat"]
        cos_lat = max(0.1, math.cos(math.radians(mean_lat)))
        sigma_lat = sigma_m / 111000.0
        sigma_lon = sigma_m / (111000.0 * cos_lat)

        for p in pts:
            p["lat"] += random.gauss(0.0, sigma_lat)
            p["lon"] += random.gauss(0.0, sigma_lon)

    # 4. Time warp
    if enable_timewarp and n > 2:
        t0 = pts[0]["t"]
        t_span = max(1.0, pts[-1]["t"] - t0)
        gamma = random.uniform(0.7, 1.4)
        for p in pts:
            s = (p["t"] - t0) / t_span
            s_warped = s**gamma
            p["t"] = t0 + s_warped * t_span

    # 5. Random dropout gaps (simulate GPS freeze / loss)
    if enable_dropout and n >= 20 and random.random() < 0.50:
        gap_len = random.randint(5, min(20, n // 3))
        start_idx = random.randint(0, n - gap_len)
        freeze_lat = pts[start_idx]["lat"]
        freeze_lon = pts[start_idx]["lon"]
        for j in range(start_idx, start_idx + gap_len):
            pts[j]["lat"] = freeze_lat
            pts[j]["lon"] = freeze_lon
            pts[j]["accuracy_m"] = min(pts[j]["accuracy_m"] * 2.0, 100.0)

    return pts, pickup, dropoff


def extract_r3f_features(
    bundle: dict[str, Any],
    augment: bool = False,
    num_steps: int = NUM_STEPS,
) -> tuple[np.ndarray, np.ndarray]:
    """Extract normalized sequence (NUM_CHANNELS, NUM_STEPS) and static vector (NUM_STATIC_FEATURES,)."""
    if not augment:
        return _extract_r3f_features_base(bundle, augment=False, num_steps=num_steps)

    raw_points = extract_raw_points(bundle)
    pickup = extract_coords(bundle.get("pickup"))
    dropoff = extract_coords(bundle.get("dropoff"))

    raw_points, pickup, dropoff = apply_domain_randomisation(
        raw_points,
        pickup=pickup,
        dropoff=dropoff,
        enable_noise=True,
        enable_rotation=True,
        enable_dropout=True,
        enable_timewarp=True,
        enable_rate_jitter=True,
    )

    augmented_bundle = {
        "telemetry": raw_points,
        "pickup": pickup,
        "dropoff": dropoff,
    }
    return _extract_r3f_features_base(augmented_bundle, augment=False, num_steps=num_steps)

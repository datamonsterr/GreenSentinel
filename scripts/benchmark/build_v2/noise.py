"""Telemetry noise model: GPS accuracy, multipath canyon outliers, interval mixture, and speed consistency."""

from __future__ import annotations

import math
import random

from scripts.benchmark.build_v2.config import GeneratorV2Config


def sample_ping_cadence(rng: random.Random, config: GeneratorV2Config) -> float:
    profiles = config.ping_profiles
    cadences = [p[0] for p in profiles]
    weights = [p[1] for p in profiles]
    return rng.choices(cadences, weights=weights, k=1)[0]


def sample_step_interval(
    rng: random.Random,
    nominal_cadence_s: float,
    config: GeneratorV2Config,
    allow_misses: bool = True,
) -> float:
    misses = 0
    if allow_misses and rng.random() < config.missed_ping_prob:
        # Geometric number of misses (mean 1-2 pings)
        while rng.random() < 0.5:
            misses += 1
        misses += 1

    jitter = rng.gauss(0.0, config.clock_jitter_sd)
    jitter = max(-0.8, min(0.8, jitter))

    interval = (1 + misses) * nominal_cadence_s + jitter
    return max(0.1, round(interval, 2))


def sample_accuracy_m(rng: random.Random, config: GeneratorV2Config) -> tuple[float | None, float]:
    """Sample reported accuracy and effective noise standard deviation.

    Returns: (reported_accuracy_m, effective_sigma_m)
    """
    if rng.random() < config.accuracy_null_rate:
        # Null reported accuracy (Android 0.0 mapped to null)
        eff_acc = math.exp(config.accuracy_lognormal_mu)  # ~11.6m
        return None, eff_acc / 2.0

    raw = rng.lognormvariate(config.accuracy_lognormal_mu, config.accuracy_lognormal_sigma)
    acc = min(raw, config.accuracy_clip_max)
    reported = round(acc, 1)
    return reported, reported / 2.0


def apply_gps_noise(
    rng: random.Random,
    lon: float,
    lat: float,
    config: GeneratorV2Config,
    is_stationary: bool = False,
    force_outlier: bool = False,
) -> tuple[float, float, float | None, bool]:
    """Apply realistic GPS noise with accuracy scaling and optional multipath outliers.

    Returns: (noisy_lon, noisy_lat, reported_accuracy_m, is_multipath_outlier)
    """
    reported_acc, eff_sigma = sample_accuracy_m(rng, config)

    m_per_deg_lat = 111139.0
    cos_lat = math.cos(math.radians(lat))
    m_per_deg_lon = 111139.0 * cos_lat

    is_outlier = force_outlier or (rng.random() < config.multipath_outlier_rate and not is_stationary)

    if is_outlier:
        # Urban canyon multipath outlier jump (50-200m)
        dist_m = rng.uniform(config.multipath_min_m, config.multipath_max_m)
        angle = rng.uniform(0.0, 2.0 * math.pi)
        d_lon_m = dist_m * math.cos(angle)
        d_lat_m = dist_m * math.sin(angle)
        noisy_lon = lon + d_lon_m / m_per_deg_lon
        noisy_lat = lat + d_lat_m / m_per_deg_lat
        return round(noisy_lon, 7), round(noisy_lat, 7), reported_acc, True

    if is_stationary:
        # Stationary receiver fixes have tight correlated anchor noise (~1.5m sd)
        d_lon_m = rng.gauss(0.0, 1.5)
        d_lat_m = rng.gauss(0.0, 1.5)
    else:
        # Moving receiver noise scales with accuracy
        d_lon_m = rng.gauss(0.0, eff_sigma)
        d_lat_m = rng.gauss(0.0, eff_sigma)

    noisy_lon = lon + d_lon_m / m_per_deg_lon
    noisy_lat = lat + d_lat_m / m_per_deg_lat
    return round(noisy_lon, 7), round(noisy_lat, 7), reported_acc, False


def calculate_device_speed(
    rng: random.Random,
    disp_m: float,
    dt_s: float,
    config: GeneratorV2Config,
    is_stationary: bool = False,
    true_speed_mps: float | None = None,
) -> float | None:
    """Reported device speed_mps consistent with physical vehicle speed and urban caps."""
    if is_stationary:
        return 0.0

    if rng.random() < config.device_speed_null_rate:
        return None

    if true_speed_mps is not None:
        base_speed = true_speed_mps
    else:
        base_speed = disp_m / max(1e-3, dt_s)

    if base_speed < 0.4:
        return 0.0

    noise = rng.gauss(0.0, config.device_speed_noise_sd)
    reported = base_speed + noise
    cap = getattr(config, "speed_device_cap_mps", 23.6)
    reported = max(0.0, min(cap, reported))
    return round(reported, 2)


def calculate_device_bearing(
    rng: random.Random,
    true_bearing: float,
    is_stationary: bool = False,
    config: GeneratorV2Config | None = None,
) -> float | None:
    if is_stationary:
        return None
    sd = config.bearing_noise_sd if config else 5.0
    return round((true_bearing + rng.gauss(0.0, sd)) % 360.0, 1)

"""Scenario telemetry generation from config/telemetry_distribution.yaml (S1-DA-06).

Pure functions shared by ``generate_synthetic_data.py`` (seed file) and
``simulate_trip_stream.py`` (live frames). No database, network, or file writes.

A trip is planned as a continuous piecewise trajectory in local metres (pickup at the
origin), then sampled at ping times drawn from the sampling model, with per-ping
accuracy, position noise, and device states from the config. Every point carries
``occurred_at`` and ``sequence``. Producer-declared derived fields
(``distance_to_pickup_m``, ``davi_score``, ``data_gap_s``) are always null: the
server computes them in ``FeatureWindow``.

Scenario names from the seed and simulator map onto config names through
``SCENARIO_ALIASES``; consumers keep their existing names.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import yaml

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent.parent / "config" / "telemetry_distribution.yaml"
NOISE_MODES = ("happy", "stress")
_EARTH_RADIUS_M = 6371000.0

SCENARIO_ALIASES = {
    "intentional_dic": "driver_stall_cancel",
    "stall": "driver_stall_cancel",
    "fake_gps": "gps_spoofing",
    "clean": "normal_trip",
    "normal": "normal_trip",
    "detour": "route_deviation",
    "wrong_direction": "route_deviation",
}


def load_config(path: str | Path | None = None) -> dict[str, Any]:
    with open(path or DEFAULT_CONFIG_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


def canonical_scenario(name: str, config: dict[str, Any]) -> str:
    """Map a consumer scenario name onto a config scenario; unknown names become normal_trip."""
    resolved = SCENARIO_ALIASES.get(name, name)
    return resolved if resolved in config["scenarios"] else "normal_trip"


def make_rng(config: dict[str, Any], seed: int | None = None, stream: int = 0) -> np.random.Generator:
    """Independent, reproducible stream per trip: same (seed, stream) gives identical output."""
    return np.random.default_rng([config["seed"] if seed is None else seed, stream])


# ---------------------------------------------------------------------------
# Distribution sampling
# ---------------------------------------------------------------------------
def sample(spec: Any, rng: np.random.Generator) -> float:
    """Draw one value from a config distribution spec (or return a constant)."""
    if not isinstance(spec, dict):
        return float(spec)
    dist = spec["dist"]
    if dist == "uniform":
        return float(rng.uniform(spec["low"], spec["high"]))
    if dist == "uniform_int":
        return float(rng.integers(spec["low"], spec["high"] + 1))
    if dist == "normal":
        value = float(rng.normal(spec.get("mean", 0.0), spec["sd"]))
        return float(np.clip(value, -spec["clip"], spec["clip"])) if "clip" in spec else value
    if dist == "gamma":
        shape = spec["shape"]
        return float(rng.gamma(shape, spec["mean"] / shape))
    if dist == "lognormal":
        mu = spec["mu"] if "mu" in spec else math.log(spec["median"])
        return float(rng.lognormal(mu, spec["sigma"]))
    raise ValueError(f"unsupported distribution {dist!r}")


def sample_quantiles(quantiles: dict[str, float], rng: np.random.Generator) -> float:
    """Inverse-CDF sample by linear interpolation between p05..p95 (clamped at the ends)."""
    points = sorted((int(k[1:]) / 100.0, v) for k, v in quantiles.items())
    probs, values = zip(*points, strict=True)
    return float(np.interp(rng.uniform(probs[0], probs[-1]), probs, values))


def sample_accuracy(config: dict[str, Any], rng: np.random.Generator) -> float | None:
    acc = config["position"]["accuracy_m"]
    if rng.random() < acc["null_rate"]:
        return None
    tail = acc["heavy_tail"]
    if rng.random() < tail["rate"]:
        return round(float(rng.uniform(tail["low"], tail["high"])), 1)
    return round(min(sample(acc, rng), acc["clip_max"]), 1)


# ---------------------------------------------------------------------------
# Trajectory plan (local metres, pickup at the origin)
# ---------------------------------------------------------------------------
@dataclass
class Leg:
    kind: str  # "move" or "stop"
    start: np.ndarray
    end: np.ndarray
    duration_s: float
    phase: str = "approach"

    @property
    def speed_mps(self) -> float:
        return float(np.linalg.norm(self.end - self.start) / self.duration_s) if self.duration_s > 0 else 0.0


@dataclass
class Plan:
    legs: list[Leg] = field(default_factory=list)
    cursor: np.ndarray = field(default_factory=lambda: np.zeros(2))
    gaps: list[tuple[float, float]] = field(default_factory=list)  # (start_s, end_s) with no pings
    dropout: dict[str, Any] | None = None

    @property
    def duration_s(self) -> float:
        return sum(leg.duration_s for leg in self.legs)

    def move_to(self, target: np.ndarray, speed_mps: float, phase: str = "approach") -> None:
        distance = float(np.linalg.norm(target - self.cursor))
        if distance > 0:
            self.legs.append(Leg("move", self.cursor.copy(), target.copy(), distance / speed_mps, phase))
            self.cursor = target.copy()

    def stop(self, duration_s: float, phase: str = "approach") -> None:
        self.legs.append(Leg("stop", self.cursor.copy(), self.cursor.copy(), duration_s, phase))

    def truncate(self, max_duration_s: float) -> None:
        kept, elapsed = [], 0.0
        for leg in self.legs:
            if elapsed + leg.duration_s <= max_duration_s:
                kept.append(leg)
                elapsed += leg.duration_s
                continue
            remaining = max_duration_s - elapsed
            if remaining > 0:
                frac = remaining / leg.duration_s
                kept.append(Leg(leg.kind, leg.start, leg.start + (leg.end - leg.start) * frac, remaining, leg.phase))
            break
        self.legs = kept

    def state_at(self, t: float) -> tuple[np.ndarray, Leg]:
        elapsed = 0.0
        for leg in self.legs:
            if t <= elapsed + leg.duration_s or leg is self.legs[-1]:
                frac = 0.0 if leg.duration_s <= 0 else min(1.0, max(0.0, (t - elapsed) / leg.duration_s))
                return leg.start + (leg.end - leg.start) * frac, leg
            elapsed += leg.duration_s
        raise ValueError("empty plan")


def _unit(angle_rad: float) -> np.ndarray:
    return np.array([math.cos(angle_rad), math.sin(angle_rad)])


def _moving_speed(config: dict[str, Any], rng: np.random.Generator, vehicle_mode: str) -> float:
    speed_cfg = config["speed"]
    low, high = speed_cfg["moving_speed_clip_mps"]
    return float(np.clip(sample(speed_cfg["moving_speed_mps"][vehicle_mode], rng), low, high))


def _approach_via_waypoint(
    plan: Plan, target: np.ndarray, tortuosity: float, speed: float, rng: np.random.Generator
) -> None:
    """Reach ``target`` through one lateral waypoint so path length / chord = tortuosity."""
    chord = target - plan.cursor
    length = float(np.linalg.norm(chord))
    if length == 0:
        return
    offset = 0.5 * length * math.sqrt(max(tortuosity**2 - 1.0, 0.0))
    normal = np.array([-chord[1], chord[0]]) / length * (1 if rng.random() < 0.5 else -1)
    plan.move_to(plan.cursor + chord / 2 + normal * offset, speed)
    plan.move_to(target, speed)


def plan_trip(
    config: dict[str, Any],
    scenario: str,
    rng: np.random.Generator,
    *,
    dropoff_m: np.ndarray | None = None,
    vehicle_mode: str = "car",
    max_duration_s: float | None = None,
) -> Plan:
    """Build the true trajectory for one scenario (section 4.1 of TELEMETRY_DISTRIBUTION.md)."""
    sc = config["scenarios"][scenario]
    route = config["route"]
    plan = Plan()
    heading = rng.uniform(0, 2 * math.pi)  # direction from pickup to the driver's start
    speed = _moving_speed(config, rng, vehicle_mode)

    def start_at(distance_m: float) -> None:
        plan.cursor = _unit(heading) * distance_m

    def on_trip(duration_s: float) -> None:
        direction = dropoff_m if dropoff_m is not None and np.linalg.norm(dropoff_m) > 0 else _unit(heading + math.pi)
        direction = direction / np.linalg.norm(direction)
        plan.move_to(plan.cursor + direction * speed * duration_s, speed, phase="on_trip")

    if scenario == "driver_stall_cancel":
        stall_r = sample(sc["stall_distance_to_pickup_m"], rng)
        if rng.random() < sc["move_away_first"]["probability"]:
            away = sample(sc["move_away_first"]["distance_m"], rng)
            start_at(max(sc["min_start_distance_m"], stall_r - away))
            plan.move_to(_unit(heading) * stall_r, speed)
        else:
            start_at(stall_r + speed * sample(sc["approach_s"], rng))
            plan.move_to(_unit(heading) * stall_r, speed)
        plan.stop(sample(sc["stall_duration_s"], rng), phase="stall")
    elif scenario == "traffic_gridlock":
        start_at(sample(route["start_distance_to_pickup_m"], rng))
        budget = sample(sc["duration_s"], rng)
        while plan.duration_s < budget and np.linalg.norm(plan.cursor) > sc["crawl_leg_min_m"] + 30:
            plan.stop(sample(sc["stop_duration_s"], rng))
            leg = sample(sc["crawl_leg_m"], rng)
            plan.move_to(plan.cursor * (1 - leg / np.linalg.norm(plan.cursor)), sample(sc["crawl_speed_mps"], rng))
    elif scenario == "route_deviation":
        start_at(sample(route["start_distance_to_pickup_m"], rng))
        toward = sample(sc["toward_first_m"], rng)
        plan.move_to(plan.cursor * (1 - toward / np.linalg.norm(plan.cursor)), speed)
        away_dir = _unit(heading + rng.uniform(-sc["away_angle_spread_rad"], sc["away_angle_spread_rad"]))
        plan.move_to(plan.cursor + away_dir * sample(sc["detour_away_m"], rng), speed)
    elif scenario == "slow_crawl_fraud":
        # G1 (Issue #275): walking-pace crawl toward pickup under clear traffic.
        # Micro-stops (10-40 s) stay far below the 180 s SSD anchor on purpose.
        start_at(sample(sc["start_distance_m"], rng))
        end_gap = sample(sc["end_gap_m"], rng)
        budget = sample(sc["duration_s"], rng)
        while plan.duration_s < budget and np.linalg.norm(plan.cursor) > end_gap + sc["crawl_leg_min_m"]:
            plan.stop(sample(sc["stop_duration_s"], rng))
            if plan.duration_s >= budget:
                break
            leg = min(sample(sc["crawl_leg_m"], rng), np.linalg.norm(plan.cursor) - end_gap)
            if leg < sc["crawl_leg_min_m"]:
                break
            plan.move_to(plan.cursor * (1 - leg / np.linalg.norm(plan.cursor)), sample(sc["crawl_speed_mps"], rng))
    elif scenario == "loop_deviation":
        # G2 (Issue #276): 1-2 city-block loops, then the away leg dominates DAVI.
        start_at(sample(route["start_distance_to_pickup_m"], rng))
        toward = sample(sc["toward_first_m"], rng)
        plan.move_to(plan.cursor * (1 - toward / np.linalg.norm(plan.cursor)), speed)
        for _ in range(int(sample(sc["loop_count"], rng))):
            radius = sample(sc["loop_radius_m"], rng)
            segments = int(sc["loop_segments"])
            center = plan.cursor.copy()
            for i in range(1, segments + 1):
                angle = 2 * math.pi * i / segments
                waypoint = center + np.array([radius * math.cos(angle), radius * math.sin(angle)])
                plan.move_to(waypoint, speed)
            plan.move_to(center, speed)
        # Away leg scales with the loop path so the fraud legs dominate DAVI
        # (loops average cosine ~0 and would otherwise dilute the signal).
        loop_path = sum(float(np.linalg.norm(leg.end - leg.start)) for leg in plan.legs if leg.phase == "approach")
        away_dir = _unit(heading + rng.uniform(-sc["away_angle_spread_rad"], sc["away_angle_spread_rad"]))
        plan.move_to(plan.cursor + away_dir * (sample(sc["detour_away_m"], rng) + loop_path), speed)
    elif scenario == "technical_dropout":
        start_at(sample(route["start_distance_to_pickup_m"], rng))
        _approach_via_waypoint(
            plan, np.zeros(2), sample_quantiles(route["tortuosity_quantiles"]["normal"], rng), speed, rng
        )
        approach_end = plan.duration_s
        gap_start = approach_end * rng.uniform(*sc["dropout_at_fraction_of_approach"])
        gap = sample(sc["gap_s"], rng)
        resumes = rng.random() < sc["resume_after_gap_probability"]
        kind = "app_crash" if rng.random() < sc["dropout_kind"]["app_crash"] else "network_loss"
        plan.gaps.append((gap_start, gap_start + gap))
        plan.dropout = {"kind": kind, "start_s": gap_start, "end_s": gap_start + gap, "resumes": resumes}
        if resumes:
            # Continue past the gap (waiting at pickup) so post-gap pings exist.
            plan.stop(max(gap_start + gap - plan.duration_s, 0.0) + sample(sc["after_gap_s"], rng), phase="wait")
        else:
            # The trip does not continue; the app reconnects once at the end of the gap
            # (a single ping at the last position), so the gap itself is observable.
            plan.truncate(gap_start)
            plan.stop(gap, phase="dropout")
    else:  # normal_trip, gps_jitter (approach, wait, trip) and gps_spoofing
        start_at(sample(route["start_distance_to_pickup_m"], rng))
        arrival = _unit(rng.uniform(0, 2 * math.pi)) * sample(
            config["scenarios"]["normal_trip"]["arrival_distance_m"], rng
        )
        _approach_via_waypoint(
            plan, arrival, sample_quantiles(route["tortuosity_quantiles"]["normal"], rng), speed, rng
        )
        if scenario == "gps_spoofing":
            for _ in range(int(sample(sc["teleport_jumps"]["count"], rng))):
                jump = _unit(rng.uniform(0, 2 * math.pi)) * sample(sc["teleport_jump_m"], rng)
                plan.move_to(plan.cursor + jump, sample(sc["teleport_jumps"]["speed_mps"], rng), phase="teleport")
        else:
            plan.stop(sample(config["scenarios"]["normal_trip"]["wait_at_pickup_s"], rng), phase="wait")
            on_trip(sample(config["scenarios"]["normal_trip"]["on_trip_s"], rng))

    if max_duration_s is not None and plan.duration_s > max_duration_s:
        plan.truncate(max_duration_s)
    return plan


# ---------------------------------------------------------------------------
# Sampling pings
# ---------------------------------------------------------------------------
def ping_times(
    config: dict[str, Any], plan: Plan, rng: np.random.Generator, noise: str, cadence_s: float
) -> list[float]:
    """Ping offsets (s): cadence x (1 + missed pings) + clock jitter, minus outage/dropout gaps."""
    sampling = config["sampling"]
    jitter = config["noise_modes"][noise]["clock_jitter_s"]
    total = plan.duration_s
    gaps = list(plan.gaps)
    if rng.random() < sampling["outage"]["trip_probability"] and total > 0:
        start = rng.uniform(0, total)
        gaps.append((start, start + sample(sampling["outage"]["duration_s"], rng)))
    times, t = [0.0], 0.0
    while True:
        missed = int(rng.geometric(1 - sampling["missed_ping_probability"])) - 1
        t += cadence_s * (1 + missed) + sample(jitter, rng)
        if t > total:
            break
        if not any(start <= t < end for start, end in gaps):
            times.append(t)
    return times


def _to_latlon(pickup_lonlat: tuple[float, float], xy: np.ndarray) -> tuple[float, float]:
    lon0, lat0 = pickup_lonlat
    lat = lat0 + math.degrees(xy[1] / _EARTH_RADIUS_M)
    lon = lon0 + math.degrees(xy[0] / (_EARTH_RADIUS_M * math.cos(math.radians(lat0))))
    return lat, lon


def _heading_deg(leg: Leg) -> float:
    d = leg.end - leg.start
    return (math.degrees(math.atan2(d[0], d[1])) + 360.0) % 360.0  # east=x, north=y


@dataclass
class TripTelemetry:
    scenario: str
    points: list[dict[str, Any]]
    incidents: list[dict[str, Any]]
    plan: Plan
    # Simulation ground truth per point (approach/stall/wait/on_trip/teleport/dropout),
    # kept out of the point dicts so detectors never see it.
    phases: list[str] = field(default_factory=list)


def generate_trip(
    config: dict[str, Any],
    scenario: str,
    pickup_lonlat: tuple[float, float],
    start_time: datetime,
    rng: np.random.Generator,
    *,
    noise: str = "happy",
    dropoff_lonlat: tuple[float, float] | None = None,
    vehicle_mode: str = "car",
    max_duration_s: float | None = None,
    profile: str | None = None,
) -> TripTelemetry:
    """Generate timestamped, sequenced telemetry points for one trip.

    Points are flat frames (``latitude``/``longitude`` + ``TelemetryPayload`` fields +
    ``occurred_at`` ISO string + ``sequence``). Use ``to_payload`` for the nested shape.
    """
    if noise not in NOISE_MODES:
        raise ValueError(f"noise must be one of {NOISE_MODES}")
    scenario = canonical_scenario(scenario, config)
    sc = config["scenarios"][scenario]
    mode = config["noise_modes"][noise]
    cadence = config["sampling"]["profiles"][profile or config["sampling"]["default_profile"]]["cadence_s"]

    dropoff_m = None
    if dropoff_lonlat is not None:
        lon0, lat0 = pickup_lonlat
        dropoff_m = np.array(
            [
                math.radians(dropoff_lonlat[0] - lon0) * _EARTH_RADIUS_M * math.cos(math.radians(lat0)),
                math.radians(dropoff_lonlat[1] - lat0) * _EARTH_RADIUS_M,
            ]
        )
    plan = plan_trip(
        config, scenario, rng, dropoff_m=dropoff_m, vehicle_mode=vehicle_mode, max_duration_s=max_duration_s
    )
    times = ping_times(config, plan, rng, noise, cadence)
    if plan.dropout is not None and not plan.dropout["resumes"] and times[-1] < plan.duration_s:
        times.append(plan.duration_s)

    health = sc["health"]
    jitter_share = sample(health["jitter"], rng) if isinstance(health["jitter"], dict) else health["jitter"]
    n = len(times)
    jitter_count = round(jitter_share * n)
    if isinstance(health["jitter"], dict):  # keep the realised share inside the configured range
        jitter_count = min(
            max(jitter_count, math.ceil(health["jitter"]["low"] * n)), math.floor(health["jitter"]["high"] * n)
        )
    jitter_idx = set(rng.choice(n, size=jitter_count, replace=False).tolist()) if n and jitter_count else set()
    ar = np.zeros(2)
    rho = mode["ar1_rho"]
    points: list[dict[str, Any]] = []
    phases: list[str] = []
    for seq, t in enumerate(times):
        true_xy, leg = plan.state_at(t)
        phases.append(leg.phase)
        moving = leg.kind == "move"
        is_jitter = seq in jitter_idx
        if is_jitter and "jitter_accuracy_m" in sc:
            accuracy = round(sample(sc["jitter_accuracy_m"], rng), 1)
        else:
            accuracy = sample_accuracy(config, rng)
            if leg.phase == "stall" and "stall_accuracy_max_m" in sc and mode["clip_stall_accuracy"]:
                accuracy = min(accuracy, sc["stall_accuracy_max_m"]) if accuracy is not None else None
        noise_sd = (accuracy if accuracy is not None else config["position"]["unknown_accuracy_noise_m"]) * config[
            "position"
        ]["noise_sd_fraction_of_accuracy"]
        slow = leg.kind == "move" and leg.speed_mps < mode.get("slow_move_threshold_mps", 0.0)
        if (leg.kind == "stop" or slow) and mode["stop_noise_sd_m"] is not None:
            noise_sd = mode["stop_noise_sd_m"]
        if rho > 0:  # stress: AR(1) with long-run sd = noise_sd
            ar = rho * ar + math.sqrt(1 - rho**2) * rng.normal(0, noise_sd, 2)
            offset = ar
        else:
            cap = accuracy if accuracy is not None else noise_sd * 2
            offset = np.clip(rng.normal(0, noise_sd, 2), -cap, cap)
        lat, lon = _to_latlon(pickup_lonlat, true_xy + offset)

        mock = scenario == "gps_spoofing" and rng.random() < health["mock"]
        app_state, network_state, gps_state = "foreground", "online", "valid"
        if rng.random() < health["offline"]:
            network_state = "offline"
        elif rng.random() < health["degraded"]:
            network_state = "degraded"
        if is_jitter:
            gps_state = "jitter"
        if mock:
            gps_state = "mock_reported"
        mock_flag: bool | None = mock
        if not mock and rng.random() < config["mock_location_reported_null_rate"]:
            mock_flag = None

        reported_speed: float | None = None
        if rng.random() >= config["speed"]["reported_speed_null_rate"]:
            reported_speed = (
                round(sample({"dist": "gamma", "shape": 2.0, "mean": leg.speed_mps}, rng), 2)
                if moving and leg.speed_mps > 0
                else 0.0
            )
        bearing = None
        if moving:
            bearing = round((_heading_deg(leg) + sample(config["bearing"]["moving_noise_deg"], rng)) % 360.0, 1)
            bearing = 0.0 if bearing >= 360.0 else bearing

        points.append(
            {
                "sequence": seq,
                "occurred_at": (start_time + timedelta(seconds=t)).isoformat(),
                "latitude": round(lat, 7),
                "longitude": round(lon, 7),
                "accuracy_m": accuracy,
                "speed_mps": reported_speed,
                "bearing_deg": bearing,
                "app_state": app_state,
                "network_state": network_state,
                "gps_state": gps_state,
                "mock_location_reported": mock_flag,
                "latency_ms": round(sample(config["latency_ms"], rng), 1),
                "distance_to_pickup_m": None,
                "davi_score": None,
                "data_gap_s": None,
            }
        )

    incidents: list[dict[str, Any]] = []
    if plan.dropout is not None:
        # The last ping before the gap carries the blocking device state.
        before = [p for p, t in zip(points, times, strict=True) if t < plan.dropout["start_s"]]
        if before:
            last = before[-1]
            if plan.dropout["kind"] == "app_crash":
                last.update(
                    {
                        "app_state": "crashed",
                        "latitude": None,
                        "longitude": None,
                        "speed_mps": None,
                        "bearing_deg": None,
                    }
                )
            else:
                last.update({"network_state": "offline"})
        incidents.append(
            {
                "incident_type": plan.dropout["kind"],
                "started_at": (start_time + timedelta(seconds=plan.dropout["start_s"])).isoformat(),
                "ended_at": (start_time + timedelta(seconds=plan.dropout["end_s"])).isoformat(),
            }
        )
    return TripTelemetry(scenario=scenario, points=points, incidents=incidents, plan=plan, phases=phases)


_PAYLOAD_KEYS = (
    "speed_mps",
    "bearing_deg",
    "app_state",
    "network_state",
    "gps_state",
    "mock_location_reported",
    "latency_ms",
    "distance_to_pickup_m",
    "davi_score",
    "data_gap_s",
)


def to_payload(point: dict[str, Any]) -> dict[str, Any]:
    """Nested ``TelemetryPayload`` shape for a flat generated point."""
    position = None
    if point.get("latitude") is not None and point.get("longitude") is not None:
        position = {"latitude": point["latitude"], "longitude": point["longitude"], "accuracy_m": point["accuracy_m"]}
    return {"position": position, **{k: point.get(k) for k in _PAYLOAD_KEYS}}


def plan_start_latlon(trip: TripTelemetry, pickup_lonlat: tuple[float, float]) -> tuple[float, float]:
    """True (noise-free) start of the driver's trajectory as (lat, lon)."""
    start = trip.plan.legs[0].start if trip.plan.legs else np.zeros(2)
    return _to_latlon(pickup_lonlat, start)


def to_wkt(point: dict[str, Any]) -> str | None:
    if point.get("latitude") is None or point.get("longitude") is None:
        return None
    return f"POINT({point['longitude']:.7f} {point['latitude']:.7f})"

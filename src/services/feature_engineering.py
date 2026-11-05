"""Telemetry feature engineering (S1-DA-02).

Pure functions: no database, network, or file IO. Turns a trip's telemetry points into a
versioned ``FeatureWindow`` persisted in ``app.feature_sets``.

Definitions follow docs/architecture/DATA_MODEL.md ("Feature semantics") and
docs/data/MIPO_FRAUD_RESEARCH.md ("Suggested feature definitions"):

- Missing evidence is ``None`` and listed in ``missing_features``; never a fabricated 0.
- Geometric features (SSD, DAVI, speed, distance to pickup) use only *geometric points*:
  valid WGS84 position, not blocked by the technical guardrail, and no mock location
  (a mock coordinate may be fabricated). Coverage and gaps use every timestamped point.
- DAVI and distance to pickup need point order only; SSD, speed, coverage, and gaps need
  timestamps.
- DAVI is measured against the straight line to pickup, not a road route. On one-way
  streets a legitimate approach can start by moving away, so a negative DAVI is evidence
  for analyst review, not proof.

Thresholds are versioned demo configuration (POC_DESIGN: "Thresholds are versioned demo
configuration until Fraud Operations approves policy"), stored with every feature set.
"""

from __future__ import annotations

import math
from datetime import datetime
from typing import Any, cast

from pydantic import BaseModel, Field

from src.services.guardrails import evaluate_telemetry_point, extract_position, is_valid_coordinate
from src.services.route_analytics import haversine_distance_m, parse_timestamp

FEATURE_VERSION = "v1.0.0"

FEATURE_PARAMS: dict[str, float] = {
    # Approach window ends at the first geometric point this close to pickup.
    "arrival_radius_m": 30.0,
    # SSD anchor radius: min(max_m, max(min_m, anchor accuracy_m)); min_m when accuracy is unknown.
    "stationary_radius_min_m": 15.0,
    "stationary_radius_max_m": 50.0,
    # A gap longer than this breaks SSD chains and motion segments (matches detect_telemetry_missingness).
    "max_sample_gap_s": 30.0,
    # Consecutive points merge into one motion segment until displaced this far from its start.
    "segment_min_displacement_m": 15.0,
    # Segments starting closer than this to pickup carry no reliable direction and are skipped for DAVI.
    "davi_min_distance_to_pickup_m": 20.0,
    # Segments faster than this are kept but counted as implausible.
    "implausible_speed_mps": 50.0,
}

# Lifecycle states that mean the passenger has been reached; the approach window ends there.
_POST_ARRIVAL_STATES = {"picked_up", "on_trip", "complete", "completed", "dropped_off"}


class DistanceToPickup(BaseModel):
    first_m: float | None = None
    last_m: float | None = None
    min_m: float | None = None


class SpeedStats(BaseModel):
    mean_mps: float | None = None
    p95_mps: float | None = None
    max_mps: float | None = None
    segment_count: int = 0
    implausible_speed_segments: int = 0
    reported_mean_mps: float | None = Field(
        default=None,
        description="Mean of producer-reported speed_mps; informational, never mixed into derived speed.",
    )


class GpsQuality(BaseModel):
    accuracy_p50_m: float | None = None
    accuracy_p95_m: float | None = None
    accuracy_unknown_ratio: float | None = None
    jitter_ratio: float | None = None
    mock_ratio: float | None = None


class FeatureWindow(BaseModel):
    """Versioned telemetry features for one trip window."""

    feature_version: str = FEATURE_VERSION
    params: dict[str, float] = Field(default_factory=lambda: dict(FEATURE_PARAMS))

    point_count: int = 0
    geometric_point_count: int = 0
    timestamped_point_count: int = 0

    arrived_at_pickup: bool = False
    arrival_index: int | None = Field(
        default=None, description="Index, in ordered points, where the approach window ends."
    )

    approach_stationary_duration_s: float | None = Field(
        default=None,
        description=(
            "SSD before reaching pickup; the ERR-02 feature persisted to feature_sets.stationary_duration_s. "
            "Equals the whole window when there is no pickup."
        ),
    )
    stationary_distance_to_pickup_m: float | None = Field(
        default=None, description="Distance from the approach SSD anchor to pickup."
    )
    stationary_duration_total_s: float | None = Field(
        default=None,
        description="SSD over the whole window, including waiting at pickup and stops on trip. JSON only.",
    )

    davi: float | None = Field(default=None, ge=-1.0, le=1.0)
    davi_segment_count: int = 0
    distance_to_pickup_m: DistanceToPickup = Field(default_factory=DistanceToPickup)

    speed: SpeedStats = Field(default_factory=SpeedStats)
    gps_quality: GpsQuality = Field(default_factory=GpsQuality)

    telemetry_coverage: float | None = Field(default=None, ge=0.0, le=1.0)
    max_gap_s: float | None = Field(default=None, ge=0.0)

    missing_features: list[str] = Field(default_factory=list)
    quality_flags: list[str] = Field(default_factory=list)


class _Point:
    __slots__ = ("accuracy_m", "coord", "geometric", "index", "lifecycle", "mock", "reported_speed", "ts")

    def __init__(self, raw: dict[str, Any], index: int) -> None:
        self.index = index
        self.ts = parse_timestamp(raw.get("occurred_at"))
        self.lifecycle = str(raw.get("lifecycle_state") or "").lower() or None
        self.mock = bool(raw.get("mock_location_reported")) or str(raw.get("gps_state") or "").lower() == (
            "mock_reported"
        )
        position = extract_position(raw)
        self.coord: tuple[float, float] | None = None  # (lon, lat)
        if position is not None and is_valid_coordinate(*position):
            self.coord = (float(position[1]), float(position[0]))
        self.geometric = self.coord is not None and not self.mock and not evaluate_telemetry_point(raw).blocked
        self.accuracy_m = _non_negative(raw.get("accuracy_m"))
        if self.accuracy_m is None and isinstance(raw.get("position"), dict):
            self.accuracy_m = _non_negative(raw["position"].get("accuracy_m"))
        self.reported_speed = _non_negative(raw.get("speed_mps"))

    @property
    def position(self) -> tuple[float, float]:
        """Coordinates for callers that have selected geometric points."""
        assert self.coord is not None
        return self.coord

    @property
    def timestamp(self) -> datetime:
        """Timestamp for callers that have selected timestamped points."""
        assert self.ts is not None
        return self.ts


def _non_negative(value: Any) -> float | None:
    if value is None or isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not math.isfinite(value) or value < 0:
        return None
    return float(value)


def _percentile(values: list[float], q: float) -> float | None:
    """Linear-interpolated percentile (same convention as numpy's default)."""
    if not values:
        return None
    ordered = sorted(values)
    pos = (len(ordered) - 1) * q
    lo, hi = math.floor(pos), math.ceil(pos)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (pos - lo)


def _order_points(points: list[_Point], raw_points: list[dict[str, Any]]) -> list[_Point]:
    """Order by occurred_at when every point has one, else by sequence, else list order."""
    if points and all(p.ts is not None for p in points):
        return sorted(points, key=lambda p: p.timestamp)
    sequences = [raw_points[p.index].get("sequence") for p in points]
    if points and all(isinstance(s, (int, float)) and not isinstance(s, bool) for s in sequences):
        return [p for _, p in sorted(zip(sequences, points, strict=True), key=lambda pair: cast(float | int, pair[0]))]
    return list(points)


def _planar_vector(origin: tuple[float, float], target: tuple[float, float]) -> tuple[float, float]:
    """East/north metres from origin to target (equirectangular; fine at trip scale)."""
    mean_lat = math.radians((origin[1] + target[1]) / 2.0)
    metres_per_degree = 6371000.0 * math.pi / 180.0
    return (
        (target[0] - origin[0]) * metres_per_degree * math.cos(mean_lat),
        (target[1] - origin[1]) * metres_per_degree,
    )


def _cosine(u: tuple[float, float], v: tuple[float, float]) -> float | None:
    nu, nv = math.hypot(*u), math.hypot(*v)
    if nu == 0 or nv == 0:
        return None
    return max(-1.0, min(1.0, (u[0] * v[0] + u[1] * v[1]) / (nu * nv)))


def _gap_breaks(prev: _Point, curr: _Point) -> bool:
    if prev.ts is None or curr.ts is None:
        return False
    return (curr.ts - prev.ts).total_seconds() > FEATURE_PARAMS["max_sample_gap_s"]


def _motion_segments(points: list[_Point]) -> list[tuple[_Point, _Point, float]]:
    """Merge consecutive points into segments of at least ``segment_min_displacement_m``.

    A segment runs from an anchor to the first later point displaced that far from it; a
    sample gap resets the anchor and drops the partial segment. Returns (start, end, metres).
    """
    segments: list[tuple[_Point, _Point, float]] = []
    if not points:
        return segments
    anchor = prev = points[0]
    for curr in points[1:]:
        if _gap_breaks(prev, curr):
            anchor = prev = curr
            continue
        displacement = haversine_distance_m(anchor.position, curr.position)
        if displacement >= FEATURE_PARAMS["segment_min_displacement_m"]:
            segments.append((anchor, curr, displacement))
            anchor = curr
        prev = curr
    return segments


def _longest_stationary_chain(points: list[_Point]) -> tuple[float, _Point] | None:
    """Longest anchored stationary chain over timestamped geometric points.

    The chain stays open while each point lies within R of the chain's anchor, with
    R = min(max_m, max(min_m, anchor accuracy)), and no sample gap exceeds the limit.
    Returns (duration seconds, anchor) or None with fewer than two points.
    """
    if len(points) < 2:
        return None
    best_duration, best_anchor = 0.0, points[0]
    anchor = prev = points[0]
    for curr in points[1:]:
        radius = min(
            FEATURE_PARAMS["stationary_radius_max_m"],
            max(FEATURE_PARAMS["stationary_radius_min_m"], anchor.accuracy_m or 0.0),
        )
        if _gap_breaks(prev, curr) or haversine_distance_m(anchor.position, curr.position) > radius:
            anchor = curr
        else:
            duration = (curr.timestamp - anchor.timestamp).total_seconds()
            if duration > best_duration:
                best_duration, best_anchor = duration, anchor
        prev = curr
    return best_duration, best_anchor


def _approach_cut(ordered: list[_Point], pickup: tuple[float, float] | None) -> int | None:
    """Index where the approach window ends: first geometric point within the arrival
    radius of pickup, or the first point in a post-arrival lifecycle state."""
    for i, p in enumerate(ordered):
        if p.lifecycle in _POST_ARRIVAL_STATES:
            return i
        if (
            pickup is not None
            and p.geometric
            and haversine_distance_m(p.position, pickup) <= FEATURE_PARAMS["arrival_radius_m"]
        ):
            return i
    return None


def _round(value: float | None, digits: int = 3) -> float | None:
    return None if value is None else round(value, digits)


def compute_feature_window(
    points: list[Any],
    pickup: tuple[float, float] | list[float] | None,
    dropoff: tuple[float, float] | list[float] | None = None,
) -> FeatureWindow:
    """Compute telemetry features for one trip window.

    ``pickup``/``dropoff`` are ``(lon, lat)``. ``dropoff`` is accepted for interface
    stability and is not used by v1.0.0 features.
    """
    del dropoff  # reserved for a later feature version
    raw_points = [p.model_dump() if isinstance(p, BaseModel) else p for p in points if isinstance(p, (dict, BaseModel))]
    pickup_coord = (float(pickup[0]), float(pickup[1])) if pickup and len(pickup) == 2 else None
    if pickup_coord is not None and not is_valid_coordinate(pickup_coord[1], pickup_coord[0]):
        pickup_coord = None

    ordered = _order_points([_Point(raw, i) for i, raw in enumerate(raw_points)], raw_points)
    geometric = [p for p in ordered if p.geometric]
    timed_all = sorted((p for p in ordered if p.ts is not None), key=lambda p: p.timestamp)
    timed_geometric = [p for p in timed_all if p.geometric]

    window = FeatureWindow(
        point_count=len(ordered),
        geometric_point_count=len(geometric),
        timestamped_point_count=len(timed_all),
    )
    missing: list[str] = []

    # Approach window (order-based).
    cut = _approach_cut(ordered, pickup_coord)
    window.arrived_at_pickup = cut is not None
    window.arrival_index = cut
    approach = ordered if cut is None else ordered[: cut + 1]
    approach_geometric = [p for p in approach if p.geometric]

    # Distance to pickup (order-based, approach window).
    if pickup_coord is not None and approach_geometric:
        distances = [haversine_distance_m(p.position, pickup_coord) for p in approach_geometric]
        window.distance_to_pickup_m = DistanceToPickup(
            first_m=_round(distances[0], 1), last_m=_round(distances[-1], 1), min_m=_round(min(distances), 1)
        )
    else:
        missing.append("distance_to_pickup_m")

    # DAVI (order-based, approach window, merged segments).
    if pickup_coord is not None:
        weighted, total = 0.0, 0.0
        for start, end, metres in _motion_segments(approach_geometric):
            if haversine_distance_m(start.position, pickup_coord) < FEATURE_PARAMS["davi_min_distance_to_pickup_m"]:
                continue
            cos = _cosine(_planar_vector(start.position, end.position), _planar_vector(start.position, pickup_coord))
            if cos is None:
                continue
            weighted += metres * cos
            total += metres
            window.davi_segment_count += 1
        window.davi = _round(weighted / total, 4) if total > 0 else None
    if window.davi is None:
        missing.append("davi")

    # SSD (time-based). ERR-02 is stalling before pickup, so the approach window is the
    # persisted value; the whole-window total also covers waiting at pickup and trip stops.
    approach_ids = {id(p) for p in approach}
    approach_chain = _longest_stationary_chain([p for p in timed_geometric if id(p) in approach_ids])
    if approach_chain is not None:
        duration, anchor = approach_chain
        window.approach_stationary_duration_s = _round(duration, 1)
        if pickup_coord is not None:
            window.stationary_distance_to_pickup_m = _round(haversine_distance_m(anchor.position, pickup_coord), 1)
    else:
        missing.append("approach_stationary_duration_s")
    total_chain = _longest_stationary_chain(timed_geometric)
    if total_chain is not None:
        window.stationary_duration_total_s = _round(total_chain[0], 1)
    else:
        missing.append("stationary_duration_total_s")

    # Speed (time-based, merged segments over the whole window).
    speeds = [
        metres / elapsed
        for start, end, metres in _motion_segments(timed_geometric)
        if (elapsed := (end.timestamp - start.timestamp).total_seconds()) > 0
    ]
    if len(timed_geometric) >= 2 and not speeds:
        # Displaced less than one segment length over the window: measure the net drift
        # rather than report no speed, so a stationary vehicle reads as ~0, not unknown.
        first, last = timed_geometric[0], timed_geometric[-1]
        elapsed = (last.timestamp - first.timestamp).total_seconds()
        if elapsed > 0:
            speeds = [haversine_distance_m(first.position, last.position) / elapsed]
    reported = [p.reported_speed for p in geometric if p.reported_speed is not None]
    window.speed = SpeedStats(
        mean_mps=_round(sum(speeds) / len(speeds)) if speeds else None,
        p95_mps=_round(_percentile(speeds, 0.95)),
        max_mps=_round(max(speeds)) if speeds else None,
        segment_count=len(speeds),
        implausible_speed_segments=sum(s > FEATURE_PARAMS["implausible_speed_mps"] for s in speeds),
        reported_mean_mps=_round(sum(reported) / len(reported)) if reported else None,
    )
    if not speeds:
        missing.append("speed")

    # GPS quality (all points).
    if ordered:
        accuracies = [p.accuracy_m for p in ordered if p.accuracy_m is not None]
        raw_states = [str(raw_points[p.index].get("gps_state") or "").lower() for p in ordered]
        window.gps_quality = GpsQuality(
            accuracy_p50_m=_round(_percentile(accuracies, 0.5), 2),
            accuracy_p95_m=_round(_percentile(accuracies, 0.95), 2),
            accuracy_unknown_ratio=_round(1 - len(accuracies) / len(ordered), 4),
            jitter_ratio=_round(raw_states.count("jitter") / len(ordered), 4),
            mock_ratio=_round(sum(p.mock for p in ordered) / len(ordered), 4),
        )
        if not accuracies:
            missing.append("gps_accuracy")
    else:
        missing.append("gps_quality")

    # Coverage and gaps (time-based, every timestamped point including invalid ones).
    if len(timed_all) >= 2 and (span := (timed_all[-1].timestamp - timed_all[0].timestamp).total_seconds()) > 0:
        gaps = [(b.timestamp - a.timestamp).total_seconds() for a, b in zip(timed_all, timed_all[1:], strict=False)]
        window.max_gap_s = _round(max(gaps), 1)
        covered = sum(g for g in gaps if g <= FEATURE_PARAMS["max_sample_gap_s"])
        window.telemetry_coverage = _round(covered / span, 4)
    else:
        missing += ["telemetry_coverage", "max_gap_s"]
        window.quality_flags.append("insufficient_samples")

    window.missing_features = missing
    return window

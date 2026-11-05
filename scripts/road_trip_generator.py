"""
Road-constrained trip generator for T1 (normal trip: origin → pickup → destination).

Public API (canonical contract seams):
  - RoadTripFixture.load(fixture_dir)  — load pinned OSRM geometry; never interpolates
  - sample_route_points(coords, n, seed, t0_s, total_duration_s) — deterministic sampler
  - RoadTripManifest.build(fixture, seed)  — produce canonical JSON artifact
  - validate_road_trip(manifest_dict)  — behavioral validator with named tolerances

All coordinates WGS84 GeoJSON [lon, lat].
Timestamps UTC ISO-8601 with Z suffix.
Speed derived from haversine(segment) / elapsed_time — never hardcoded.
"""

from __future__ import annotations

import hashlib
import json
import math
import random
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

GENERATOR_VERSION = "v1.0.0-road-t1"
OSRM_PROVIDER = "osrm"
OSRM_PROFILE = "driving"

# Fixed clock origin for deterministic generation (matches existing generator)
BASE_TIME = datetime(2026, 9, 22, 6, 0, 0, tzinfo=UTC)

# Canonical org/entity IDs shared with existing seed data
ORG_ID = "018f2f4e-0000-7000-8000-000000000001"

# Number of telemetry points sampled per leg (cadence).
# Road-fixture choice, distinct from the porto_15s default profile in
# config/telemetry_distribution.yaml; gap/SSD thresholds (30 s) apply to both.
CADENCE_S = 10

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _haversine_m(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    """Haversine great-circle distance in metres."""
    earth_r = 6_371_000.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return earth_r * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _bearing_deg(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    """Initial bearing from (lon1,lat1) to (lon2,lat2), degrees [0,360)."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dlam = math.radians(lon2 - lon1)
    y = math.sin(dlam) * math.cos(phi2)
    x = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(dlam)
    return (math.degrees(math.atan2(y, x)) + 360.0) % 360.0


def _polyline_cumulative_distances(coords: list[list[float]]) -> list[float]:
    """Cumulative arc-length in metres along a [lon,lat] polyline."""
    dist = [0.0]
    for i in range(1, len(coords)):
        d = _haversine_m(coords[i - 1][0], coords[i - 1][1], coords[i][0], coords[i][1])
        dist.append(dist[-1] + d)
    return dist


def _interpolate_along_polyline(
    coords: list[list[float]], cum_dist: list[float], target_m: float
) -> tuple[float, float]:
    """Return (lon,lat) at target_m metres along polyline."""
    total = cum_dist[-1]
    target_m = max(0.0, min(target_m, total))
    for i in range(1, len(cum_dist)):
        if cum_dist[i] >= target_m:
            seg_len = cum_dist[i] - cum_dist[i - 1]
            if seg_len < 1e-9:
                return float(coords[i][0]), float(coords[i][1])
            frac = (target_m - cum_dist[i - 1]) / seg_len
            lon = coords[i - 1][0] + frac * (coords[i][0] - coords[i - 1][0])
            lat = coords[i - 1][1] + frac * (coords[i][1] - coords[i - 1][1])
            return lon, lat
    return float(coords[-1][0]), float(coords[-1][1])


def _sha256_coords(coords: list[list[float]]) -> str:
    """Deterministic SHA-256 of the coordinate list (JSON canonical form)."""
    raw = json.dumps(coords, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()


def _utc_z(dt: datetime) -> str:
    """Return ISO-8601 string with Z suffix for UTC datetime."""
    return dt.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _stable_uuid(namespace: str, name: str) -> str:
    return str(uuid.uuid5(uuid.UUID("6ba7b810-9dad-11d1-80b4-00c04fd430c8"), f"{namespace}:{name}"))


# ---------------------------------------------------------------------------
# SEAM 1: RoadTripFixture
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RoadTripFixture:
    """Loaded OSRM geometry — immutable, never interpolated.

    Attributes
    ----------
    pickup_leg : GeoJSON LineString geometry dict for driver_origin→pickup.
    destination_leg : GeoJSON LineString geometry dict for pickup→destination.
    pickup_distance_m : OSRM-reported distance in metres.
    pickup_duration_s : OSRM-reported duration in seconds.
    destination_distance_m : OSRM-reported distance in metres.
    destination_duration_s : OSRM-reported duration in seconds.
    provenance : dict with provider, base_url, profile, capture metadata.
    """

    pickup_leg: dict[str, Any]
    destination_leg: dict[str, Any]
    pickup_distance_m: float
    pickup_duration_s: float
    destination_distance_m: float
    destination_duration_s: float
    provenance: dict[str, Any]

    @classmethod
    def load(cls, fixture_dir: Path) -> RoadTripFixture:
        """Load pinned OSRM fixture from ``fixture_dir``.

        Raises
        ------
        FileNotFoundError
            If fixture_dir or any required file is absent.
        ValueError
            If JSON structure is invalid (OSRM response malformed).
        """
        fixture_dir = Path(fixture_dir)
        if not fixture_dir.exists():
            raise FileNotFoundError(f"Fixture directory not found: {fixture_dir}")

        prov_path = fixture_dir / "PROVENANCE.json"
        pickup_path = fixture_dir / "osrm_leg_pickup.json"
        dest_path = fixture_dir / "osrm_leg_destination.json"

        for p in (prov_path, pickup_path, dest_path):
            if not p.exists():
                raise FileNotFoundError(f"Required fixture file missing: {p}")

        with open(prov_path, encoding="utf-8") as f:
            provenance = json.load(f)

        pickup_geom, pickup_dist, pickup_dur = cls._parse_osrm_file(pickup_path)
        dest_geom, dest_dist, dest_dur = cls._parse_osrm_file(dest_path)

        return cls(
            pickup_leg=pickup_geom,
            destination_leg=dest_geom,
            pickup_distance_m=pickup_dist,
            pickup_duration_s=pickup_dur,
            destination_distance_m=dest_dist,
            destination_duration_s=dest_dur,
            provenance=provenance,
        )

    @staticmethod
    def _parse_osrm_file(path: Path) -> tuple[dict[str, Any], float, float]:
        """Parse an OSRM route response JSON; return (geometry, distance_m, duration_s)."""
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if data.get("code") != "Ok":
            raise ValueError(f"OSRM response code not Ok in {path}: {data.get('code')}")
        routes = data.get("routes") or []
        if not routes:
            raise ValueError(f"No routes in OSRM response: {path}")
        route = routes[0]
        geom = route.get("geometry")
        if not isinstance(geom, dict) or geom.get("type") != "LineString":
            raise ValueError(f"Expected GeoJSON LineString geometry in {path}")
        coords = geom.get("coordinates")
        if not isinstance(coords, list) or len(coords) < 2:
            raise ValueError(f"Geometry must have ≥2 coordinates: {path}")
        # Validate all coords are [lon, lat] within bounds
        for i, c in enumerate(coords):
            if len(c) < 2:
                raise ValueError(f"Coordinate {i} has fewer than 2 values in {path}")
            lon, lat = float(c[0]), float(c[1])
            if not (-180.0 <= lon <= 180.0 and -90.0 <= lat <= 90.0):
                raise ValueError(f"Coordinate {i} out of WGS84 bounds: [{lon},{lat}]")
        distance = float(route.get("distance", 0))
        duration = float(route.get("duration", 0))
        if distance <= 0 or duration <= 0:
            raise ValueError(f"Invalid distance/duration in {path}: {distance}/{duration}")
        return geom, distance, duration


# ---------------------------------------------------------------------------
# SEAM 2: sample_route_points()
# ---------------------------------------------------------------------------


def sample_route_points(
    coords: list[list[float]],
    n: int,
    seed: int,
    t0_s: float,
    total_duration_s: float,
) -> list[dict[str, Any]]:
    """Sample ``n`` telemetry points along a GeoJSON [lon,lat] polyline.

    Points are evenly distributed along the arc length with jitter applied
    via ``seed``. Speed is derived as haversine(segment)/elapsed_time.
    Timestamps are monotonically increasing from ``t0_s``.

    Parameters
    ----------
    coords : list[list[float]]
        GeoJSON [lon, lat] coordinate pairs — the OSRM polyline.
    n : int
        Number of sample points to return.
    seed : int
        RNG seed for deterministic jitter.
    t0_s : float
        Offset of first point (seconds since BASE_TIME).
    total_duration_s : float
        Total duration of this leg in seconds — controls timestamp spacing.

    Returns
    -------
    list[dict]
        Each dict: longitude, latitude, timestamp_s, speed_mps, bearing_deg.
    """
    if n < 1:
        return []
    if len(coords) < 2:
        raise ValueError("coords must have at least 2 points")

    rng = random.Random(seed)
    cum_dist = _polyline_cumulative_distances(coords)
    total_dist = cum_dist[-1]

    # Even spacing with small jitter (±5% of spacing)
    if total_duration_s <= 0:
        raise ValueError("total_duration_s must be positive")
    spacing = total_dist / max(n - 1, 1)
    points = []

    for i in range(n):
        base_m = spacing * i
        jitter = rng.uniform(-0.05 * spacing, 0.05 * spacing) if 0 < i < n - 1 else 0.0
        target_m = max(0.0, min(base_m + jitter, total_dist))
        lon, lat = _interpolate_along_polyline(coords, cum_dist, target_m)

        # Time: proportional to arc-distance fraction
        frac = target_m / total_dist if total_dist > 0 else (i / max(n - 1, 1))
        ts = t0_s + frac * total_duration_s

        points.append((ts, target_m, lon, lat))

    # Sort by timestamp to guarantee monotonicity
    points.sort(key=lambda p: p[0])

    result = []
    for idx, (ts, dist_m, lon, lat) in enumerate(points):
        # Speed: derived from distance to previous point / time delta
        if idx == 0:
            # For first point, use next segment
            if len(points) > 1:
                next_ts, next_m, next_lon, next_lat = points[1]
                dt = max(next_ts - ts, 1e-6)
                seg_m = _haversine_m(lon, lat, next_lon, next_lat)
                speed = seg_m / dt
                bear = _bearing_deg(lon, lat, next_lon, next_lat)
            else:
                speed = 0.0
                bear = 0.0
        else:
            prev_ts, prev_m, prev_lon, prev_lat = points[idx - 1]
            dt = max(ts - prev_ts, 1e-6)
            seg_m = _haversine_m(prev_lon, prev_lat, lon, lat)
            speed = seg_m / dt
            bear = _bearing_deg(prev_lon, prev_lat, lon, lat)

        result.append(
            {
                "longitude": round(lon, 7),
                "latitude": round(lat, 7),
                "timestamp_s": ts,
                "speed_mps": round(speed, 3),
                "bearing_deg": round(bear % 360.0, 2) % 360.0,
            }
        )

    return result


# ---------------------------------------------------------------------------
# SEAM 3: RoadTripManifest
# ---------------------------------------------------------------------------


@dataclass
class RoadTripManifest:
    """Canonical JSON artifact for a single normal road-constrained trip.

    Attributes match the canonical contract: WGS84 lon/lat GeoJSON,
    producer payload uses 'latitude'/'longitude' keys, UTC Z timestamps,
    speed/distance in m/s and metres, stable UUIDs for trip/assignment/case/events.
    """

    trip_id: str
    assignment_id: str
    case_id: str
    event_ids: list[str]
    _dict: dict[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def build(cls, fixture: RoadTripFixture, seed: int = 42) -> RoadTripManifest:
        """Build the manifest from a loaded fixture with fixed seed.

        Parameters
        ----------
        fixture : RoadTripFixture
            Loaded OSRM geometry (both legs).
        seed : int
            Deterministic seed — controls point sampling and UUID generation.
        """
        # Stable IDs derived from seed
        ns = f"p063:road-t1:seed{seed}"
        trip_id = _stable_uuid(ns, "trip")
        assignment_id = _stable_uuid(ns, "assignment")
        case_id = _stable_uuid(ns, "case")

        # Timing: use BASE_TIME as simulated clock origin
        requested_at = BASE_TIME
        # Pickup leg starts at t=0, duration = pickup_duration_s
        pickup_start = requested_at
        pickup_end = pickup_start + timedelta(seconds=fixture.pickup_duration_s)
        # Driver arrives at pickup = pickup_end; destination leg follows
        dest_start = pickup_end
        dest_end = dest_start + timedelta(seconds=fixture.destination_duration_s)

        # Sample telemetry for each leg
        pickup_pts = sample_route_points(
            coords=fixture.pickup_leg["coordinates"],
            n=math.ceil(fixture.pickup_duration_s / CADENCE_S) + 1,
            seed=seed,
            t0_s=0.0,
            total_duration_s=fixture.pickup_duration_s,
        )
        dest_pts = sample_route_points(
            coords=fixture.destination_leg["coordinates"],
            n=math.ceil(fixture.destination_duration_s / CADENCE_S) + 1,
            seed=seed + 1,  # different seed for destination leg
            t0_s=fixture.pickup_duration_s,
            total_duration_s=fixture.destination_duration_s,
        )

        # Build ingest events
        ingest_events: list[dict[str, Any]] = []
        event_ids: list[str] = []
        driver_id = f"018f2f4e-3000-7000-8000-{1:012d}"  # driver 1 (matches seed data)

        for leg_name, pts, leg_offset_s in [
            ("pickup", pickup_pts, 0.0),
            ("destination", dest_pts, fixture.pickup_duration_s),
        ]:
            for step, pt in enumerate(pts):
                if leg_name == "destination" and step == 0:
                    continue  # Pickup endpoint is already observed at this timestamp.
                ev_id = _stable_uuid(ns, f"event:{leg_name}:{step}")
                event_ids.append(ev_id)
                occurred_dt = requested_at + timedelta(seconds=pt["timestamp_s"])
                received_dt = occurred_dt + timedelta(milliseconds=200)
                ingest_events.append(
                    {
                        "event_id": ev_id,
                        "organization_id": ORG_ID,
                        "schema_version": 1,
                        "event_type": "telemetry.observed",
                        "source": "smartphone-app",
                        "occurred_at": _utc_z(occurred_dt),
                        "received_at": _utc_z(received_dt),
                        "correlation_id": _stable_uuid(ns, "correlation"),
                        "causation_id": None,
                        "simulation_run_id": _stable_uuid(ns, "sim-run"),
                        "trip_id": trip_id,
                        "assignment_id": assignment_id,
                        "driver_id": driver_id,
                        "sequence": len(event_ids),
                        "producer_sequence": len(event_ids),
                        "leg": leg_name,
                        "payload": {
                            "position": {
                                "latitude": pt["latitude"],
                                "longitude": pt["longitude"],
                                "accuracy_m": 8.0,
                            },
                            "speed_mps": pt["speed_mps"],
                            "bearing_deg": pt["bearing_deg"],
                            "app_state": "foreground",
                            "network_state": "online",
                            "gps_state": "valid",
                            "mock_location_reported": False,
                        },
                    }
                )

        # Route snapshots
        route_snapshots = [
            {
                "id": _stable_uuid(ns, "snap:pickup"),
                "assignment_id": assignment_id,
                "leg": "pickup",
                "calculated_at": _utc_z(requested_at),
                "provider": OSRM_PROVIDER,
                "routing_profile": OSRM_PROFILE,
                "map_version": fixture.provenance.get("map_version", "unknown"),
                "route_geojson": fixture.pickup_leg,
                "distance_m": int(round(fixture.pickup_distance_m)),
                "duration_s": int(round(fixture.pickup_duration_s)),
                "provenance": {
                    "source": "osrm",
                    "status": "ok",
                    "fixture_file": "osrm_leg_pickup.json",
                    "is_shortest_path": False,
                    "fallback": False,
                },
            },
            {
                "id": _stable_uuid(ns, "snap:destination"),
                "assignment_id": assignment_id,
                "leg": "destination",
                "calculated_at": _utc_z(pickup_end),
                "provider": OSRM_PROVIDER,
                "routing_profile": OSRM_PROFILE,
                "map_version": fixture.provenance.get("map_version", "unknown"),
                "route_geojson": fixture.destination_leg,
                "distance_m": int(round(fixture.destination_distance_m)),
                "duration_s": int(round(fixture.destination_duration_s)),
                "provenance": {
                    "source": "osrm",
                    "status": "ok",
                    "fixture_file": "osrm_leg_destination.json",
                    "is_shortest_path": False,
                    "fallback": False,
                },
            },
        ]

        # Trip and assignment
        trip = {
            "id": trip_id,
            "organization_id": ORG_ID,
            "passenger_id": f"018f2f4e-2000-7000-8000-{1:012d}",
            "requested_at": _utc_z(requested_at),
            "origin": {"type": "Point", "coordinates": fixture.pickup_leg["coordinates"][0]},
            "pickup": {"type": "Point", "coordinates": fixture.pickup_leg["coordinates"][-1]},
            "dropoff": {"type": "Point", "coordinates": fixture.destination_leg["coordinates"][-1]},
            "status": "completed",
            "completed_at": _utc_z(dest_end),
            "created_at": _utc_z(requested_at),
        }

        trip_assignment = {
            "id": assignment_id,
            "trip_id": trip_id,
            "driver_id": driver_id,
            "vehicle_id": f"018f2f4e-4000-7000-8000-{1:012d}",
            "state": "completed",
            "offered_at": _utc_z(requested_at),
            "accepted_at": _utc_z(pickup_end),
            "arrived_at": _utc_z(pickup_end),
            "started_at": _utc_z(dest_start),
            "ended_at": _utc_z(dest_end),
            "cancellation_actor": None,
            "cancellation_reason": None,
            "created_at": _utc_z(requested_at),
        }

        fraud_case = {
            "id": case_id,
            "organization_id": ORG_ID,
            "assignment_id": assignment_id,
            "status": "ready",
            "suspected_category": "no_violation",
            "priority_tier": 2,
            "priority_score": 10,
            "created_at": _utc_z(pickup_end),
            "resolved_at": None,
        }

        # Checksums
        pickup_checksum = _sha256_coords(fixture.pickup_leg["coordinates"])
        dest_checksum = _sha256_coords(fixture.destination_leg["coordinates"])

        manifest_meta = {
            "seed": seed,
            "generator_version": GENERATOR_VERSION,
            "simulated_clock_origin": _utc_z(BASE_TIME),
            "dataset_version": "road-t1-v1",
            "units": {
                "coordinates": "WGS84 longitude,latitude",
                "timestamp": "UTC ISO-8601",
                "distance": "m",
                "duration": "s",
                "speed": "m/s",
            },
            "provider": OSRM_PROVIDER,
            "routing_profile": OSRM_PROFILE,
            "map_version": fixture.provenance.get("map_version", "unknown"),
            "route_checksums": {
                "pickup": pickup_checksum,
                "destination": dest_checksum,
            },
            "validation_tolerances": {
                "max_off_route_m": 30.0,
                "min_speed_mps": 0.0,
                "max_speed_mps": 50.0,
                "max_timestamp_gap_s": fixture.pickup_duration_s + fixture.destination_duration_s + 60,
                "speed_tolerance_mps": 0.05,
                "endpoint_tolerance_m": 30.0,
            },
            "cadence": {
                "cadence_s": CADENCE_S,
                "max_interval_s": CADENCE_S * 1.1 + 0.002,
                "spacing": "arc-length-even-with-5pct-jitter",
            },
            "captured_at_utc": fixture.provenance.get("captured_at_utc", ""),
        }

        result_dict: dict[str, Any] = {
            "manifest": manifest_meta,
            "trip": trip,
            "trip_assignment": trip_assignment,
            "fraud_case": fraud_case,
            "route_snapshots": route_snapshots,
            "ingest_events": ingest_events,
        }

        obj = cls(
            trip_id=trip_id,
            assignment_id=assignment_id,
            case_id=case_id,
            event_ids=event_ids,
        )
        obj._dict = result_dict
        return obj

    def to_dict(self) -> dict[str, Any]:
        """Return the full canonical manifest as a plain dict."""
        return self._dict


# ---------------------------------------------------------------------------
# SEAM 4: validate_road_trip()
# ---------------------------------------------------------------------------


def _point_to_segment_dist_m(px: float, py: float, ax: float, ay: float, bx: float, by: float) -> float:
    """Distance from point P to line segment AB, approximated in metres via haversine."""
    # Use parametric projection; approximate as planar for small segments
    dx, dy = bx - ax, by - ay
    seg_sq = dx * dx + dy * dy
    if seg_sq < 1e-18:
        return _haversine_m(px, py, ax, ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / seg_sq))
    cx = ax + t * dx
    cy = ay + t * dy
    return _haversine_m(px, py, cx, cy)


def _min_dist_to_polyline_segments_m(lon: float, lat: float, coords: list[list[float]]) -> float:
    """Min distance from (lon,lat) to any segment of the polyline."""
    if len(coords) == 1:
        return _haversine_m(lon, lat, float(coords[0][0]), float(coords[0][1]))
    min_d = float("inf")
    for i in range(len(coords) - 1):
        d = _point_to_segment_dist_m(
            lon,
            lat,
            float(coords[i][0]),
            float(coords[i][1]),
            float(coords[i + 1][0]),
            float(coords[i + 1][1]),
        )
        if d < min_d:
            min_d = d
    return min_d


def validate_road_trip(manifest: dict[str, Any]) -> dict[str, Any]:
    """Validate a road-trip manifest dict.

    Checks:
    - Route snapshots have both 'pickup' and 'destination' legs.
    - All telemetry timestamps are monotonically increasing.
    - All points lie within ``max_off_route_m`` of their respective leg polyline.
    - All speeds are non-negative and ≤ ``max_speed_mps``.

    Returns
    -------
    dict with keys:
      - passed (bool)
      - failures (list[str])
      - tolerances (dict with named tolerance values)
    """
    tols = (manifest.get("manifest") or {}).get("validation_tolerances") or {}
    max_off_m: float = float(tols.get("max_off_route_m", 30.0))
    min_speed: float = float(tols.get("min_speed_mps", 0.0))
    max_speed: float = float(tols.get("max_speed_mps", 50.0))
    cadence = (manifest.get("manifest") or {}).get("cadence") or {}
    max_interval_s = float(cadence.get("max_interval_s", CADENCE_S * 1.1 + 0.002))

    failures: list[str] = []
    metadata = manifest.get("manifest") or {}
    units = metadata.get("units") or {}
    if units.get("coordinates") != "WGS84 longitude,latitude" or units.get("timestamp") != "UTC ISO-8601":
        failures.append("coordinate CRS/order and timestamp units must be WGS84 longitude,latitude and UTC ISO-8601")

    def is_number(value: Any) -> bool:
        return isinstance(value, (float, int)) and not isinstance(value, bool) and math.isfinite(value)

    def valid_coordinates(coords: Any) -> bool:
        return (
            isinstance(coords, list)
            and len(coords) >= 2
            and all(
                isinstance(point, list)
                and len(point) == 2
                and all(is_number(value) for value in point)
                and -180 <= point[0] <= 180
                and -90 <= point[1] <= 90
                for point in coords
            )
        )

    def valid_utc(value: Any) -> bool:
        if not isinstance(value, str) or not value.endswith("Z"):
            return False
        try:
            datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return False
        return True

    for row in [manifest.get(name) or {} for name in ("trip", "trip_assignment", "fraud_case")]:
        for key, value in row.items():
            if key.endswith("_at") and value is not None and not valid_utc(value):
                failures.append(f"{key} must be a valid UTC Z timestamp")
    for snapshot in manifest.get("route_snapshots") or []:
        geometry = snapshot.get("route_geojson") or {}
        if geometry.get("type") != "LineString" or not valid_coordinates(geometry.get("coordinates")):
            failures.append("route geometry must be a valid WGS84 LineString")
        for metric in ("distance_m", "duration_s"):
            if not is_number(snapshot.get(metric)) or snapshot[metric] <= 0:
                failures.append(f"route {metric} must be positive and finite")
        provenance = snapshot.get("provenance") or {}
        if snapshot.get("provider") != "osrm" or provenance.get("source") != "osrm" or provenance.get("status") != "ok":
            failures.append("route must retain successful OSRM provenance")
        if not valid_utc(snapshot.get("calculated_at")):
            failures.append("route calculated_at must be a valid UTC Z timestamp")
    for index, event in enumerate(manifest.get("ingest_events") or []):
        for time_key in ("occurred_at", "received_at"):
            if not valid_utc(event.get(time_key)):
                failures.append(f"event[{index}] {time_key} must be a valid UTC Z timestamp")
    if failures:
        return {"passed": False, "failures": failures, "tolerances": tols}
    assignment = manifest.get("trip_assignment") or {}
    trip = manifest.get("trip") or {}
    case = manifest.get("fraud_case") or {}
    if assignment.get("trip_id") != trip.get("id"):
        failures.append("assignment trip_id does not match trip")
    if case.get("assignment_id") != assignment.get("id"):
        failures.append("case assignment_id does not match assignment")

    # 1. Check both legs present in route_snapshots
    snaps = manifest.get("route_snapshots") or []
    leg_names = {s.get("leg") for s in snaps}
    if "pickup" not in leg_names:
        failures.append("route_snapshots missing 'pickup' leg")
    if "destination" not in leg_names:
        failures.append("route_snapshots missing 'destination' leg")

    # Build leg geometry lookup
    leg_coords: dict[str, list[list[float]]] = {}
    for snap in snaps:
        if snap.get("assignment_id") != assignment.get("id"):
            failures.append("route assignment_id does not match assignment")
        leg = snap.get("leg")
        geojson = snap.get("route_geojson") or {}
        coords = geojson.get("coordinates")
        if leg and coords:
            leg_coords[leg] = coords

    trip = manifest.get("trip") or {}
    endpoint_tolerance = float(tols.get("endpoint_tolerance_m", 30.0))
    for point, leg, index in (("origin", "pickup", 0), ("pickup", "pickup", -1), ("dropoff", "destination", -1)):
        declared = (trip.get(point) or {}).get("coordinates")
        coords = leg_coords.get(leg)
        if not declared or not coords or _haversine_m(*declared, *coords[index]) > endpoint_tolerance:
            failures.append(f"{point} does not match road endpoint")
    if leg_coords.get("pickup") and leg_coords.get("destination"):
        if _haversine_m(*leg_coords["pickup"][-1], *leg_coords["destination"][0]) > endpoint_tolerance:
            failures.append("route legs are disconnected")

    observation_routes = dict(leg_coords)
    actual_route = (manifest.get("manifest", {}).get("actual_routes") or {}).get("actual_route")
    if actual_route:
        observation_routes["pickup"] = actual_route["geometry"]["coordinates"]
        if _haversine_m(*trip["origin"]["coordinates"], *observation_routes["pickup"][0]) > endpoint_tolerance:
            failures.append("actual route does not start at origin")

    # 2. Gather telemetry events and validate
    events = manifest.get("ingest_events") or []
    if not events:
        failures.append("telemetry is empty")
    if events and trip.get("status") == "completed":
        observed_pickup = [event for event in events if event.get("leg") == "pickup"]
        for name, event in (
            ("origin", events[0]),
            ("pickup", observed_pickup[-1] if observed_pickup else {}),
            ("destination", events[-1]),
        ):
            position = (event.get("payload") or {}).get("position") or {}
            waypoint = trip.get("dropoff" if name == "destination" else name) or {}
            coords = waypoint.get("coordinates")
            if (
                not coords
                or not is_number(position.get("longitude"))
                or not is_number(position.get("latitude"))
                or _haversine_m(position["longitude"], position["latitude"], *coords) > endpoint_tolerance
            ):
                failures.append(f"completed trip has no observed {name} waypoint")
    if len({event.get("event_id") for event in events}) != len(events):
        failures.append("duplicate event_id")
    if len({event.get("sequence") for event in events}) != len(events):
        failures.append("duplicate producer sequence")
    timestamps = [ev.get("occurred_at", "") for ev in events]

    # Monotonic timestamps
    for i in range(1, len(timestamps)):
        if timestamps[i] <= timestamps[i - 1]:
            failures.append(
                f"timestamp not monotonically increasing at index {i}: {timestamps[i - 1]} >= {timestamps[i]}"
            )

    # Per-event checks
    for i, ev in enumerate(events):
        for relation_key, expected in (
            ("assignment_id", assignment.get("id")),
            ("trip_id", trip.get("id")),
            ("driver_id", assignment.get("driver_id")),
        ):
            if ev.get(relation_key) != expected:
                failures.append(f"event[{i}] {relation_key} does not match assignment")
        payload = ev.get("payload") or {}
        pos = payload.get("position") or {}
        speed = payload.get("speed_mps")
        lat = pos.get("latitude")
        lon = pos.get("longitude")
        leg = ev.get("leg")

        if leg not in observation_routes:
            failures.append(f"event[{i}] unknown leg")
        if (
            lat is None
            or lon is None
            or not math.isfinite(lat)
            or not math.isfinite(lon)
            or not (-90 <= lat <= 90 and -180 <= lon <= 180)
        ):
            failures.append(f"event[{i}] invalid position")
            continue
        if speed is None or not math.isfinite(speed):
            failures.append(f"event[{i}] invalid speed")
            continue
        if i:
            prev = events[i - 1]
            previous_position = (prev.get("payload") or {}).get("position") or {}
            dt = (
                datetime.fromisoformat(ev["occurred_at"].replace("Z", "+00:00"))
                - datetime.fromisoformat(prev["occurred_at"].replace("Z", "+00:00"))
            ).total_seconds()
            declared_gap = any(
                gap.get("after_sequence") == prev.get("sequence")
                and gap.get("before_sequence") == ev.get("sequence")
                and abs(float(gap["interval_s"]) - dt) <= 0.002
                for gap in cadence.get("intentional_gaps", [])
            )
            if dt > max_interval_s and not declared_gap:
                failures.append(f"event[{i}] exceeds declared cadence interval {max_interval_s}s")
            if (
                dt > 0
                and previous_position.get("longitude") is not None
                and previous_position.get("latitude") is not None
            ):
                derived = _haversine_m(previous_position["longitude"], previous_position["latitude"], lon, lat) / dt
                # First destination observation follows the shared pickup endpoint.
                if abs(speed - derived) > float(tols.get("speed_tolerance_mps", 0.05)):
                    failures.append(f"event[{i}] speed disagrees with distance/time")

        # Speed checks
        if speed is not None:
            if speed < min_speed:
                failures.append(f"event[{i}] speed_mps {speed} < min {min_speed}")
            if speed > max_speed:
                failures.append(f"event[{i}] speed_mps {speed} > max {max_speed}")

        # Off-route check — use segment-based distance so interpolated points pass
        if lat is not None and lon is not None and leg in observation_routes:
            coords_for_leg = observation_routes[leg]
            min_d = _min_dist_to_polyline_segments_m(lon, lat, coords_for_leg)
            if min_d > max_off_m:
                failures.append(
                    f"event[{i}] (leg={leg}) point [{lon},{lat}] is {min_d:.1f}m off route (max {max_off_m}m)"
                )

    return {
        "passed": len(failures) == 0,
        "failures": failures,
        "tolerances": {
            "max_off_route_m": max_off_m,
            "min_speed_mps": min_speed,
            "max_speed_mps": max_speed,
            "max_interval_s": max_interval_s,
        },
    }

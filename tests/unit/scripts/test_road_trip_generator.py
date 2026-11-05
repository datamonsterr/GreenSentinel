"""
T1 Road-Constrained Trip Dataset — Behavioral Tests (TDD: RED first).

Seams under test (approved):
  1. RoadTripFixture  — loads pinned OSRM fixture, never interpolates
  2. sample_route_points() — deterministic sampler on OSRM geometry
  3. RoadTripManifest  — canonical JSON artifact with full provenance
  4. validate_road_trip() — structural/geo/temporal behavioral validator

All coordinates WGS84 (lon, lat) per GeoJSON spec.
Speed derived from segment distance / time, NOT hardcoded.
Timestamps UTC ISO-8601, monotonically increasing.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import pytest

from scripts.road_trip_generator import (
    RoadTripFixture,
    RoadTripManifest,
    sample_route_points,
    validate_road_trip,
)
from tests.support.repo import REPO_ROOT

# -- paths ----------------------------------------------------------------
FIXTURE_DIR = REPO_ROOT / "tests/fixtures/road_telemetry"

# =========================================================================
# SEAM 1: RoadTripFixture — fixture loading
# =========================================================================


class TestRoadTripFixture:
    """Fixture loads genuine OSRM geometry; never fabricates or interpolates."""

    def test_fixture_loads_pickup_leg(self) -> None:
        f = RoadTripFixture.load(FIXTURE_DIR)
        leg = f.pickup_leg
        # Must be a GeoJSON LineString geometry dict
        assert leg["type"] == "LineString"
        coords = leg["coordinates"]
        assert isinstance(coords, list)
        assert len(coords) >= 2

    def test_fixture_loads_destination_leg(self) -> None:
        f = RoadTripFixture.load(FIXTURE_DIR)
        leg = f.destination_leg
        assert leg["type"] == "LineString"
        assert len(leg["coordinates"]) >= 2

    def test_pickup_leg_coordinates_are_lon_lat(self) -> None:
        """All coords must be [lon, lat] — lon in (-180,180), lat in (-90,90)."""
        f = RoadTripFixture.load(FIXTURE_DIR)
        for lon, lat in f.pickup_leg["coordinates"]:
            assert -180.0 <= lon <= 180.0, f"lon out of range: {lon}"
            assert -90.0 <= lat <= 90.0, f"lat out of range: {lat}"

    def test_destination_leg_coordinates_are_lon_lat(self) -> None:
        f = RoadTripFixture.load(FIXTURE_DIR)
        for lon, lat in f.destination_leg["coordinates"]:
            assert -180.0 <= lon <= 180.0
            assert -90.0 <= lat <= 90.0

    def test_fixture_exposes_distances_and_durations(self) -> None:
        f = RoadTripFixture.load(FIXTURE_DIR)
        assert f.pickup_distance_m > 0
        assert f.pickup_duration_s > 0
        assert f.destination_distance_m > 0
        assert f.destination_duration_s > 0

    def test_fixture_exposes_provenance(self) -> None:
        f = RoadTripFixture.load(FIXTURE_DIR)
        p = f.provenance
        assert p["provider"] == "osrm"
        assert "base_url" in p
        assert "profile" in p

    def test_fixture_raises_if_fixture_dir_missing(self, tmp_path: Path) -> None:
        with pytest.raises((FileNotFoundError, OSError)):
            RoadTripFixture.load(tmp_path / "nonexistent")

    def test_fixture_never_falls_back_to_interpolation(self, tmp_path: Path) -> None:
        """If OSRM JSON missing, must raise — not silently degrade to straight line."""
        # Create dir but no files
        (tmp_path / "road_telemetry").mkdir()
        with pytest.raises((FileNotFoundError, KeyError, ValueError)):
            RoadTripFixture.load(tmp_path / "road_telemetry")

    def test_pickup_leg_coords_near_hanoi(self) -> None:
        """Sanity: route should be in Hanoi (lat 20.8..21.4, lon 105.6..106.0)."""
        f = RoadTripFixture.load(FIXTURE_DIR)
        for lon, lat in f.pickup_leg["coordinates"]:
            assert 20.8 <= lat <= 21.5, f"lat not in Hanoi: {lat}"
            assert 105.5 <= lon <= 106.1, f"lon not in Hanoi: {lon}"


# =========================================================================
# SEAM 2: sample_route_points() — deterministic sampler
# =========================================================================


class TestSampleRoutePoints:
    """Samples telemetry points along OSRM geometry; deterministic for same seed."""

    def _pickup_coords(self) -> list[list[float]]:
        f = RoadTripFixture.load(FIXTURE_DIR)
        return f.pickup_leg["coordinates"]

    def test_returns_list_of_points(self) -> None:
        coords = self._pickup_coords()
        pts = sample_route_points(coords, n=8, seed=42, t0_s=0.0, total_duration_s=772.0)
        assert isinstance(pts, list)
        assert len(pts) == 8

    def test_each_point_has_required_fields(self) -> None:
        coords = self._pickup_coords()
        pts = sample_route_points(coords, n=5, seed=42, t0_s=0.0, total_duration_s=772.0)
        for pt in pts:
            assert "longitude" in pt
            assert "latitude" in pt
            assert "timestamp_s" in pt  # seconds since t0
            assert "speed_mps" in pt
            assert "bearing_deg" in pt

    def test_timestamps_are_monotonically_increasing(self) -> None:
        coords = self._pickup_coords()
        pts = sample_route_points(coords, n=10, seed=42, t0_s=0.0, total_duration_s=772.0)
        ts = [p["timestamp_s"] for p in pts]
        for i in range(1, len(ts)):
            assert ts[i] > ts[i - 1], f"non-monotonic at index {i}: {ts[i - 1]} >= {ts[i]}"

    def test_speed_derived_not_hardcoded(self) -> None:
        """Speed must differ between points — proof it's computed from geometry."""
        coords = self._pickup_coords()
        pts = sample_route_points(coords, n=10, seed=42, t0_s=0.0, total_duration_s=772.0)
        speeds = [p["speed_mps"] for p in pts]
        # At minimum, not all identical
        assert len(set(speeds)) > 1, "all speeds identical — speed must be derived from segment geometry"

    def test_coordinates_are_on_route_within_tolerance(self) -> None:
        """All sampled points must lie within 30m of the OSRM polyline."""
        coords = self._pickup_coords()
        pts = sample_route_points(coords, n=8, seed=42, t0_s=0.0, total_duration_s=772.0)
        for pt in pts:
            min_dist = _min_dist_to_polyline_m(pt["longitude"], pt["latitude"], coords)
            assert min_dist < 30.0, f"point [{pt['longitude']},{pt['latitude']}] is {min_dist:.1f}m off route"

    def test_deterministic_for_same_seed(self) -> None:
        coords = self._pickup_coords()
        pts_a = sample_route_points(coords, n=8, seed=42, t0_s=0.0, total_duration_s=772.0)
        pts_b = sample_route_points(coords, n=8, seed=42, t0_s=0.0, total_duration_s=772.0)
        assert pts_a == pts_b

    def test_different_seeds_produce_different_results(self) -> None:
        coords = self._pickup_coords()
        pts_42 = sample_route_points(coords, n=8, seed=42, t0_s=0.0, total_duration_s=772.0)
        pts_99 = sample_route_points(coords, n=8, seed=99, t0_s=0.0, total_duration_s=772.0)
        assert pts_42 != pts_99

    def test_speed_non_negative(self) -> None:
        coords = self._pickup_coords()
        pts = sample_route_points(coords, n=10, seed=42, t0_s=0.0, total_duration_s=772.0)
        for pt in pts:
            assert pt["speed_mps"] >= 0.0

    def test_bearing_in_range(self) -> None:
        coords = self._pickup_coords()
        pts = sample_route_points(coords, n=10, seed=42, t0_s=0.0, total_duration_s=772.0)
        for pt in pts:
            assert 0.0 <= pt["bearing_deg"] < 360.0


# =========================================================================
# SEAM 3: RoadTripManifest — canonical JSON artifact
# =========================================================================


class TestRoadTripManifest:
    """Manifest exposes the complete canonical contract."""

    def _build(self) -> RoadTripManifest:
        f = RoadTripFixture.load(FIXTURE_DIR)
        return RoadTripManifest.build(fixture=f, seed=42)

    def test_manifest_builds_without_error(self) -> None:
        m = self._build()
        assert m is not None

    def test_manifest_has_trip_id(self) -> None:
        m = self._build()
        assert isinstance(m.trip_id, str)
        assert len(m.trip_id) > 0

    def test_manifest_has_assignment_id(self) -> None:
        m = self._build()
        assert isinstance(m.assignment_id, str)

    def test_manifest_has_case_id(self) -> None:
        m = self._build()
        assert isinstance(m.case_id, str)

    def test_manifest_has_event_ids(self) -> None:
        m = self._build()
        assert isinstance(m.event_ids, list)
        assert len(m.event_ids) > 0

    def test_trip_assignment_case_event_all_linked(self) -> None:
        """All event IDs reference the same assignment_id; case references assignment."""
        m = self._build()
        d = m.to_dict()
        for ev in d["ingest_events"]:
            assert ev["assignment_id"] == m.assignment_id
        assert d["fraud_case"]["assignment_id"] == m.assignment_id
        assert d["trip_assignment"]["trip_id"] == m.trip_id

    def test_manifest_has_two_legs(self) -> None:
        m = self._build()
        d = m.to_dict()
        legs = {s["leg"] for s in d["route_snapshots"]}
        assert "pickup" in legs
        assert "destination" in legs

    def test_route_snapshots_have_provider_and_profile(self) -> None:
        m = self._build()
        for snap in m.to_dict()["route_snapshots"]:
            assert snap["provider"] == "osrm"
            assert snap["routing_profile"] == "driving"

    def test_timestamps_are_utc_iso8601(self) -> None:
        """Every timestamp field must be parseable as UTC ISO-8601 with Z suffix."""
        import re

        m = self._build()
        d = m.to_dict()
        iso_re = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z$")
        for ev in d["ingest_events"]:
            assert iso_re.match(ev["occurred_at"]), f"bad timestamp: {ev['occurred_at']}"

    def test_telemetry_points_on_pickup_leg_before_pickup_timestamp(self) -> None:
        """All pickup-leg telemetry occurred_at < pickup_at."""
        m = self._build()
        d = m.to_dict()
        pickup_at = d["trip_assignment"]["accepted_at"]
        pickup_events = [e for e in d["ingest_events"] if e.get("leg") == "pickup"]
        for ev in pickup_events:
            assert ev["occurred_at"] <= pickup_at, f"pickup telemetry {ev['occurred_at']} after pickup_at {pickup_at}"

    def test_telemetry_points_have_longitude_latitude_keys(self) -> None:
        """Payload uses 'longitude'/'latitude' keys (producer naming in contract)."""
        m = self._build()
        d = m.to_dict()
        for ev in d["ingest_events"]:
            pos = ev["payload"]["position"]
            assert "latitude" in pos, "missing 'latitude' in payload.position"
            assert "longitude" in pos, "missing 'longitude' in payload.position"

    def test_speed_mps_in_payload(self) -> None:
        m = self._build()
        d = m.to_dict()
        for ev in d["ingest_events"]:
            assert "speed_mps" in ev["payload"]
            assert ev["payload"]["speed_mps"] >= 0.0

    def test_manifest_seed_in_metadata(self) -> None:
        m = self._build()
        d = m.to_dict()
        meta = d["manifest"]
        assert meta["seed"] == 42

    def test_manifest_has_generator_version(self) -> None:
        m = self._build()
        d = m.to_dict()
        assert "generator_version" in d["manifest"]

    def test_manifest_has_route_checksums(self) -> None:
        m = self._build()
        d = m.to_dict()
        meta = d["manifest"]
        assert "route_checksums" in meta
        assert "pickup" in meta["route_checksums"]
        assert "destination" in meta["route_checksums"]

    def test_manifest_serializable_to_json(self) -> None:
        m = self._build()
        blob = json.dumps(m.to_dict())
        roundtrip = json.loads(blob)
        assert roundtrip["manifest"]["seed"] == 42

    def test_manifest_deterministic_for_same_seed(self) -> None:
        f = RoadTripFixture.load(FIXTURE_DIR)
        m1 = RoadTripManifest.build(fixture=f, seed=42)
        m2 = RoadTripManifest.build(fixture=f, seed=42)
        assert m1.to_dict() == m2.to_dict()

    def test_manifest_route_checksums_match_fixture_coords(self) -> None:
        """Checksums are sha256 of the raw OSRM coordinate list."""
        import hashlib

        f = RoadTripFixture.load(FIXTURE_DIR)
        m = RoadTripManifest.build(fixture=f, seed=42)
        d = m.to_dict()

        for leg_name, coords_key in [("pickup", f.pickup_leg), ("destination", f.destination_leg)]:
            raw = json.dumps(coords_key["coordinates"], separators=(",", ":")).encode()
            expected = hashlib.sha256(raw).hexdigest()
            actual = d["manifest"]["route_checksums"][leg_name]
            assert actual == expected, f"{leg_name} checksum mismatch"


# =========================================================================
# SEAM 4: validate_road_trip() — behavioral validator
# =========================================================================


class TestValidateRoadTrip:
    """validate_road_trip(manifest) returns a dict of named tolerances and pass/fail."""

    def _manifest_dict(self) -> dict[str, Any]:
        f = RoadTripFixture.load(FIXTURE_DIR)
        m = RoadTripManifest.build(fixture=f, seed=42)
        return m.to_dict()

    def test_validate_returns_result_dict(self) -> None:
        d = self._manifest_dict()
        result = validate_road_trip(d)
        assert isinstance(result, dict)

    def test_validate_passes_for_valid_manifest(self) -> None:
        d = self._manifest_dict()
        result = validate_road_trip(d)
        assert result["passed"] is True, f"Validation failed: {result.get('failures')}"

    def test_validate_reports_named_tolerances(self) -> None:
        d = self._manifest_dict()
        result = validate_road_trip(d)
        tols = result["tolerances"]
        assert "max_off_route_m" in tols
        assert "min_speed_mps" in tols
        assert "max_speed_mps" in tols

    def test_manifest_declares_bounded_temporal_jitter(self) -> None:
        d = self._manifest_dict()
        cadence = d["manifest"]["cadence"]
        assert cadence["cadence_s"] == 10
        assert cadence["max_interval_s"] == pytest.approx(11.002)

    def test_validate_rejects_an_undeclared_observation_gap(self) -> None:
        d = self._manifest_dict()
        del d["ingest_events"][5:10]
        result = validate_road_trip(d)
        assert result["passed"] is False
        assert any("cadence" in failure for failure in result["failures"])

    @pytest.mark.parametrize("field", ["assignment_id", "trip_id", "driver_id"])
    def test_validate_rejects_foreign_event_relationships(self, field: str) -> None:
        d = self._manifest_dict()
        d["ingest_events"][0][field] = "foreign-id"
        result = validate_road_trip(d)
        assert result["passed"] is False
        assert any(field in failure for failure in result["failures"])

    def test_validate_rejects_duplicate_event_identity(self) -> None:
        d = self._manifest_dict()
        d["ingest_events"][1]["event_id"] = d["ingest_events"][0]["event_id"]
        assert validate_road_trip(d)["passed"] is False

    @pytest.mark.parametrize("occurred_at", ["invalid", "2026-09-22T06:00:00", "2026-09-22T13:00:00+07:00"])
    def test_validate_reports_invalid_or_non_utc_timestamps(self, occurred_at: str) -> None:
        d = self._manifest_dict()
        d["ingest_events"][0]["occurred_at"] = occurred_at
        result = validate_road_trip(d)
        assert not result["passed"]
        assert any("UTC" in failure for failure in result["failures"])

    @pytest.mark.parametrize("field,value", [("distance_m", 0), ("duration_s", -1), ("provider", "invented")])
    def test_validate_rejects_invalid_routing_metadata(self, field: str, value: Any) -> None:
        d = self._manifest_dict()
        d["route_snapshots"][0][field] = value
        assert not validate_road_trip(d)["passed"]

    def test_validate_reports_malformed_route_geometry(self) -> None:
        d = self._manifest_dict()
        d["route_snapshots"][0]["route_geojson"] = {"type": "Point", "coordinates": [106, 21]}
        assert not validate_road_trip(d)["passed"]

    def test_completed_trip_requires_observed_destination(self) -> None:
        d = self._manifest_dict()
        del d["ingest_events"][-10:]
        result = validate_road_trip(d)
        assert not result["passed"]
        assert any("destination" in failure for failure in result["failures"])

    def test_validate_catches_non_monotonic_timestamps(self) -> None:
        d = self._manifest_dict()
        # Swap first two timestamps to break monotonicity
        events = d["ingest_events"]
        if len(events) >= 2:
            events[0]["occurred_at"], events[1]["occurred_at"] = (
                events[1]["occurred_at"],
                events[0]["occurred_at"],
            )
        result = validate_road_trip(d)
        assert result["passed"] is False
        assert any("monoton" in f.lower() or "timestamp" in f.lower() for f in result["failures"])

    def test_validate_catches_point_off_route(self) -> None:
        d = self._manifest_dict()
        # Teleport one event to Hanoi outskirts (far off route)
        for ev in d["ingest_events"][:1]:
            ev["payload"]["position"]["latitude"] = 20.0
            ev["payload"]["position"]["longitude"] = 104.0
        result = validate_road_trip(d)
        assert result["passed"] is False
        assert any("off" in f.lower() or "route" in f.lower() for f in result["failures"])

    def test_validate_catches_negative_speed(self) -> None:
        d = self._manifest_dict()
        d["ingest_events"][0]["payload"]["speed_mps"] = -1.0
        result = validate_road_trip(d)
        assert result["passed"] is False

    def test_validate_catches_missing_pickup_leg(self) -> None:
        d = self._manifest_dict()
        d["route_snapshots"] = [s for s in d["route_snapshots"] if s["leg"] != "pickup"]
        result = validate_road_trip(d)
        assert result["passed"] is False

    def test_validate_catches_missing_destination_leg(self) -> None:
        d = self._manifest_dict()
        d["route_snapshots"] = [s for s in d["route_snapshots"] if s["leg"] != "destination"]
        result = validate_road_trip(d)
        assert result["passed"] is False

    def test_validate_failures_is_list_of_strings(self) -> None:
        d = self._manifest_dict()
        result = validate_road_trip(d)
        assert isinstance(result["failures"], list)
        for f in result["failures"]:
            assert isinstance(f, str)


# =========================================================================
# helpers
# =========================================================================


def _haversine_m(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    earth_r = 6371000.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return earth_r * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _point_to_segment_m(px: float, py: float, ax: float, ay: float, bx: float, by: float) -> float:
    dx, dy = bx - ax, by - ay
    seg_sq = dx * dx + dy * dy
    if seg_sq < 1e-18:
        return _haversine_m(px, py, ax, ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / seg_sq))
    return _haversine_m(px, py, ax + t * dx, ay + t * dy)


def _min_dist_to_polyline_m(lon: float, lat: float, coords: list[list[float]]) -> float:
    """Min distance from (lon,lat) to any segment of the polyline."""
    if len(coords) == 1:
        return _haversine_m(lon, lat, float(coords[0][0]), float(coords[0][1]))
    return min(
        _point_to_segment_m(
            lon,
            lat,
            float(coords[i][0]),
            float(coords[i][1]),
            float(coords[i + 1][0]),
            float(coords[i + 1][1]),
        )
        for i in range(len(coords) - 1)
    )

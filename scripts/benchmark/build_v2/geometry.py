"""Geometry, corridor extraction, and spatial distance utilities for Vietnam road networks."""

from __future__ import annotations

import json
import math
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any


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


@dataclass
class PinnedCorridor:
    corridor_id: str
    city: str
    origin_name: str
    destination_name: str
    coords: list[list[float]]
    cum_dist: list[float]
    total_distance_m: float
    steps: list[dict[str, Any]]
    street_names: list[str]

    # Reversed direction for bidirectional corridor traffic
    rev_coords: list[list[float]]
    rev_cum_dist: list[float]

    def get_street_at_distance(self, d_m: float, is_reversed: bool = False) -> str:
        d = (self.total_distance_m - d_m) if is_reversed else d_m
        cur = 0.0
        for s in self.steps:
            cur += s.get("distance_m", 0.0)
            if cur >= d:
                name = s.get("name")
                if name and name != "Unnamed Road":
                    return name
        for s in self.steps:
            name = s.get("name")
            if name and name != "Unnamed Road":
                return name
        return "Đường phố"


_CACHED_CORRIDORS: list[PinnedCorridor] | None = None


def load_corridors(corridors_path: Path) -> list[PinnedCorridor]:
    global _CACHED_CORRIDORS
    if _CACHED_CORRIDORS is not None:
        return _CACHED_CORRIDORS

    if not corridors_path.exists():
        # Fallback check
        alt_paths = [
            corridors_path,
            Path("data/benchmark-10k/vietnam_road_corridors.json"),
            Path("tests/fixtures/road_telemetry/vietnam_road_corridors.json"),
        ]
        found = None
        for p in alt_paths:
            if p.exists():
                found = p
                break
        if not found:
            raise FileNotFoundError(f"Corridors file not found at {corridors_path}")
        corridors_path = found

    with open(corridors_path, encoding="utf-8") as f:
        data = json.load(f)

    corridors = []
    for item in data:
        coords = item.get("geometry", {}).get("coordinates") or item.get("coordinates", [])
        if not coords or len(coords) < 2:
            continue
        cum_dist = polyline_cumulative_distances(coords)
        total_m = cum_dist[-1]

        rev_coords = list(reversed(coords))
        rev_cum_dist = polyline_cumulative_distances(rev_coords)

        steps = item.get("steps", [])
        street_names = item.get("street_names", [])

        corridors.append(
            PinnedCorridor(
                corridor_id=item["corridor_id"],
                city=item.get("city", "Vietnam"),
                origin_name=item.get("origin", {}).get("name", "Origin"),
                destination_name=item.get("destination", {}).get("name", "Destination"),
                coords=coords,
                cum_dist=cum_dist,
                total_distance_m=total_m,
                steps=steps,
                street_names=[s for s in street_names if s],
                rev_coords=rev_coords,
                rev_cum_dist=rev_cum_dist,
            )
        )

    _CACHED_CORRIDORS = corridors
    return corridors


def sample_sub_corridor(
    rng: random.Random,
    corridors: list[PinnedCorridor],
    min_dist_m: float = 1000.0,
    max_dist_m: float = 12000.0,
) -> tuple[PinnedCorridor, list[list[float]], float, str, str, bool]:
    """Sample a random sub-path from one of the pinned corridors.

    Returns: (corridor, sub_polyline, distance_m, start_street, end_street, is_reversed)
    """
    corr = rng.choice(corridors)
    is_reversed = rng.random() < 0.5
    coords = corr.rev_coords if is_reversed else corr.coords
    cum_dist = corr.rev_cum_dist if is_reversed else corr.cum_dist
    total_m = corr.total_distance_m

    min_m = min(min_dist_m, total_m * 0.4)
    max_m = min(max_dist_m, total_m)
    trip_distance_m = rng.uniform(min_m, max_m)
    s_start = rng.uniform(0.0, max(0.0, total_m - trip_distance_m))
    s_end = s_start + trip_distance_m

    sub_polyline = extract_subpolyline(coords, cum_dist, s_start, s_end)
    start_street = corr.get_street_at_distance(s_start, is_reversed=is_reversed)
    end_street = corr.get_street_at_distance(s_end, is_reversed=is_reversed)

    return corr, sub_polyline, trip_distance_m, start_street, end_street, is_reversed

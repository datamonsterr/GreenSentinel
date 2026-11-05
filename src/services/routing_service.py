"""Application routing seam; typed adapter failures map to legacy ``None``."""

from __future__ import annotations

import os
from typing import Any

from src.services.geoapify_adapter import GeoapifyAdapter
from src.services.osrm_adapter import OSRMAdapter
from src.services.route_provider import RouteProvider, RouteRequest, RouteSuccess, RouteType, TrafficModel, TravelMode
from src.services.routing_http import safe_urlopen as urlopen


def fetch_osrm_route(start: list[float], end: list[float], timeout: float = 8.0) -> dict[str, Any] | None:
    """Keep single-line OSRM consumers compatible; gaps degrade to unavailable."""
    result = fetch_route(start, end, timeout, provider=OSRMAdapter(opener=urlopen), mode="drive")
    return result if result and result["geometry"]["type"] == "LineString" else None


def fetch_route(
    start: list[float],
    end: list[float],
    timeout: float = 8.0,
    *,
    provider: RouteProvider | None = None,
    mode: TravelMode | None = None,
    route_type: RouteType = "balanced",
    traffic: TrafficModel = "free_flow",
    instruction_details: bool = True,
) -> dict[str, Any] | None:
    """Select a server-side port. OSRM remains the default for existing consumers."""
    if provider is None:
        name = os.getenv("ROUTING_PROVIDER", "osrm")
        if name == "osrm":
            provider = OSRMAdapter(opener=urlopen)
        elif name == "geoapify":
            provider = GeoapifyAdapter(opener=urlopen)
        else:
            return None
    selected_mode = mode or ("drive" if provider.name == "osrm" else "motorcycle")
    result = provider.route(RouteRequest(start, end, selected_mode, route_type, traffic, instruction_details, timeout))
    return dict(result.data) if isinstance(result, RouteSuccess) else None


def _same_point(p1: list[float], p2: list[float], tol: float = 1e-4) -> bool:
    """Compare coordinates with floating-point tolerance (~11m at 1e-4 deg)."""
    return len(p1) >= 2 and len(p2) >= 2 and abs(p1[0] - p2[0]) <= tol and abs(p1[1] - p2[1]) <= tol


def _stitch_legs(legs: list[dict[str, Any]]) -> tuple[dict[str, Any], int, float]:
    stitched_lines: list[list[list[float]]] = []
    current_line: list[list[float]] = []

    for leg in legs:
        g = leg.get("geometry", {})
        if g.get("type") == "LineString":
            coords = g.get("coordinates", [])
            if not current_line:
                current_line = list(coords)
            elif coords and _same_point(current_line[-1], coords[0], tol=1e-4):
                current_line.extend(coords[1:])
            else:
                stitched_lines.append(current_line)
                current_line = list(coords)
        elif g.get("type") == "MultiLineString":
            if current_line:
                stitched_lines.append(current_line)
                current_line = []
            stitched_lines.extend(g.get("coordinates", []))

    if current_line:
        stitched_lines.append(current_line)

    if len(stitched_lines) == 1:
        geometry = {"type": "LineString", "coordinates": stitched_lines[0]}
    else:
        geometry = {"type": "MultiLineString", "coordinates": stitched_lines}

    total_distance = sum(int(leg.get("distance_m", 0)) for leg in legs)
    total_duration = sum(float(leg.get("duration_s", 0.0)) for leg in legs)
    return geometry, total_distance, total_duration


def resolve_trip_route(
    origin: list[float],
    pickup: list[float],
    destination: list[float],
    timeout: float = 8.0,
    *,
    provider: RouteProvider | None = None,
    waypoints: list[dict[str, Any] | Any | list[float]] | None = None,
) -> dict[str, Any] | None:
    """Resolve road legs for origin -> [pickup_wps...] -> pickup -> [dest_wps...] -> destination."""
    from src.models.test_simulation import MAX_START_TO_PICKUP_M

    pickup_wps: list[dict[str, Any]] = []
    dest_wps: list[dict[str, Any]] = []

    for wp in waypoints or []:
        if isinstance(wp, (list, tuple)) and len(wp) >= 2:
            pickup_wps.append({"lon": float(wp[0]), "lat": float(wp[1]), "leg": "pickup"})
        elif hasattr(wp, "lon") and hasattr(wp, "lat"):
            leg = getattr(wp, "leg", "pickup")
            entry = {"lon": float(wp.lon), "lat": float(wp.lat), "leg": leg}
            if leg == "destination":
                dest_wps.append(entry)
            else:
                pickup_wps.append(entry)
        elif isinstance(wp, dict):
            leg = wp.get("leg", "pickup")
            entry = {"lon": float(wp.get("lon", 0.0)), "lat": float(wp.get("lat", 0.0)), "leg": leg}
            if leg == "destination":
                dest_wps.append(entry)
            else:
                pickup_wps.append(entry)

    pickup_stops = [origin] + [[wp["lon"], wp["lat"]] for wp in pickup_wps] + [pickup]
    pickup_legs: list[dict[str, Any]] = []
    for i in range(len(pickup_stops) - 1):
        leg = fetch_route(pickup_stops[i], pickup_stops[i + 1], timeout, provider=provider)
        if leg is None:
            return None
        pickup_legs.append(leg)

    dest_stops = [pickup] + [[wp["lon"], wp["lat"]] for wp in dest_wps] + [destination]
    dest_legs: list[dict[str, Any]] = []
    for i in range(len(dest_stops) - 1):
        leg = fetch_route(dest_stops[i], dest_stops[i + 1], timeout, provider=provider)
        if leg is None:
            return None
        dest_legs.append(leg)

    pickup_geometry, pickup_distance, pickup_duration = _stitch_legs(pickup_legs)
    dest_geometry, dest_distance, dest_duration = _stitch_legs(dest_legs)

    if (
        pickup_geometry["type"] == "LineString"
        and dest_geometry.get("type") == "LineString"
        and _same_point(pickup_geometry["coordinates"][-1], dest_geometry["coordinates"][0], tol=1e-4)
    ):
        combined = {
            "type": "LineString",
            "coordinates": pickup_geometry["coordinates"] + dest_geometry["coordinates"][1:],
        }
    else:
        first_legs = (
            pickup_geometry["coordinates"]
            if pickup_geometry["type"] == "MultiLineString"
            else [pickup_geometry["coordinates"]]
        )
        second_legs = (
            dest_geometry["coordinates"]
            if dest_geometry.get("type") == "MultiLineString"
            else [dest_geometry.get("coordinates", [])]
        )
        combined = {"type": "MultiLineString", "coordinates": first_legs + second_legs}

    return {
        "route_geometry": combined,
        "pickup_route": {
            "coordinates": pickup_geometry["coordinates"],
            "distance_m": pickup_distance,
            "duration_s": pickup_duration,
            "provider": pickup_legs[0]["provider"],
            "traffic_model": pickup_legs[0].get("traffic_model", "free_flow"),
            "provenance": pickup_legs[0].get("provenance", {}),
        },
        "destination_route": {
            "coordinates": dest_geometry["coordinates"],
            "distance_m": dest_distance,
            "duration_s": dest_duration,
            "provider": dest_legs[0]["provider"],
            "traffic_model": dest_legs[0].get("traffic_model", "free_flow"),
            "provenance": dest_legs[0].get("provenance", {}),
        },
        "provider": pickup_legs[0]["provider"],
        "waypoints": pickup_wps + dest_wps,
        "max_start_to_pickup_m": MAX_START_TO_PICKUP_M,
    }

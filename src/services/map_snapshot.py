"""Deterministic, evidence-revision-bound case map snapshot artifact.

Server adapter for ``get_case_map_snapshot``. Renders a Static Maps request
(markers S/P/D/stall, traveled polyline, planned dashed route, gap overlays),
GET under URL limits with a POST fallback for complex geometries, and returns
version-bound data refs. The artifact is derived only from the frozen
``evidence_snapshots`` revision; a new revision always produces a new artifact
and never mutates sent minutes.
"""

from __future__ import annotations

import base64
import hashlib
import json
import math
from datetime import UTC, datetime
from typing import Any, Literal, TypedDict, cast
from urllib.error import HTTPError, URLError

from src.services.guardrails import is_valid_coordinate
from src.services.routing_http import safe_urlopen, safe_urlpost

Style = Literal["osm-bright"]
_STYLE: Style = "osm-bright"
_ATTRIBUTION = "© OpenStreetMap contributors (ODbL), © Geoapify"
_GET_URL_LIMIT = 2048
_WIDTH = 800
_HEIGHT = 600

# Failure union: every unavailable path is explicit, safe and retry-guidable.
UnavailableCode = Literal[
    "no_geometry",
    "no_telemetry",
    "provider_unavailable",
    "provider_timeout",
    "quota_exceeded",
    "revision_mismatch",
    "malformed_input",
]


class Unavailable(TypedDict):
    code: UnavailableCode
    message: str
    retry_guidance: str
    retryable: bool


class MapSnapshot(TypedDict):
    """Typed snapshot result surfaced by the tool adapter."""

    case_id: str
    evidence_snapshot_id: str
    snapshot_version: int
    snapshot_hash: str
    route_refs: list[dict[str, Any]]
    checkpoint_times: list[dict[str, Any]]
    gap_windows: list[dict[str, Any]]
    traveled_path: list[dict[str, Any]]
    planned_routes: list[dict[str, Any]]
    provider: str
    style: Style
    rendered_at: str
    image_ref: str | None
    image_preview: str | None
    attribution: str
    cost_credits: int
    unavailable: Unavailable | None
    deterministic_key: str


# ─── Geometry helpers ────────────────────────────────────────────────────────


def _flatten_points(geometry: dict[str, Any] | None) -> list[list[float]]:
    """Extract [lon, lat] vertices from LineString/MultiLineString geometry."""
    if not isinstance(geometry, dict):
        return []
    kind = geometry.get("type")
    coords = geometry.get("coordinates")
    if not isinstance(coords, list):
        return []
    legs: list[list[list[float]]] = [coords] if kind == "LineString" else coords
    points: list[list[float]] = []
    for leg in legs:
        if not isinstance(leg, list):
            continue
        for vertex in leg:
            if isinstance(vertex, list) and len(vertex) >= 2:
                lon, lat = vertex[0], vertex[1]
                if is_valid_coordinate(float(lat), float(lon)):
                    points.append([float(lon), float(lat)])
    return points


def _decode_route(routes: dict[str, Any] | None) -> list[tuple[str, dict[str, Any]]]:
    """Return [(leg, geometry)] pairs from the stored route_geometry dict."""
    if not isinstance(routes, dict):
        return []
    out: list[tuple[str, dict[str, Any]]] = []
    for leg in ("pickup_route", "destination_route"):
        entry = routes.get(leg)
        if not isinstance(entry, dict):
            continue
        route = entry.get("route")
        if isinstance(route, dict) and route.get("type") in {"LineString", "MultiLineString"}:
            out.append((leg, route))
    return out


def _bounds(points: list[list[float]]) -> tuple[float, float, float, float]:
    if not points:
        return (0.0, 0.0, 0.0, 0.0)
    min_lon = min(p[0] for p in points)
    max_lon = max(p[0] for p in points)
    min_lat = min(p[1] for p in points)
    max_lat = max(p[1] for p in points)
    span_lon = max(max_lon - min_lon, 1e-6)
    span_lat = max(max_lat - min_lat, 1e-6)
    return min_lon, min_lat, span_lon, span_lat


def _zoom_for_span(span_lon: float, span_lat: float) -> int:
    span = max(span_lon, span_lat)
    if span <= 0.002:
        return 16
    if span <= 0.01:
        return 14
    if span <= 0.05:
        return 12
    return 10


def _encode_polyline(precision_points: list[list[float]], precision: int = 5) -> str:
    """Encode [[lat, lon]] to a Geoapify-compatible polyline string."""
    if not precision_points:
        return ""
    encode = 10**precision
    out: list[str] = []
    prev_lat = 0
    prev_lon = 0

    def _chunk(value: int) -> str:
        value = ((value << 1) ^ (value >> 31)) & 0xFFFFFFFF if value < 0 else value << 1
        chars: list[str] = []
        while value >= 0x20:
            chars.append(chr((0x20 | (value & 0x1F)) + 63))
            value >>= 5
        chars.append(chr(value + 63))
        return "".join(chars)

    for lat, lon in precision_points:
        dlat = round(lat * encode) - prev_lat
        dlon = round(lon * encode) - prev_lon
        prev_lat = round(lat * encode)
        prev_lon = round(lon * encode)
        out.append(_chunk(dlat) + _chunk(dlon))
    return "".join(out)


class PolylineEncoder:
    """Deterministic Google-polyline encoder used for static map geometry."""

    @staticmethod
    def encode_latlon(lonlats: list[list[float]], precision: int = 5) -> str:
        return _encode_polyline([[lat, lon] for lon, lat in lonlats], precision)


# ─── Gap window / checkpoint derivation ────────────────────────────────────


def _telemetry_points(
    snapshot_dossier: dict[str, Any], telemetry_samples: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Return ordered lon/lat/occurred_at observations from available evidence."""
    points: list[dict[str, Any]] = []
    for sample in telemetry_samples or []:
        position = sample.get("position") if isinstance(sample, dict) else None
        if not isinstance(position, dict):
            continue
        coords = position.get("coordinates")
        if not (isinstance(coords, list) and len(coords) >= 2):
            continue
        lon, lat = coords[0], coords[1]
        if not is_valid_coordinate(float(lat), float(lon)):
            continue
        points.append(
            {
                "lon": float(lon),
                "lat": float(lat),
                "occurred_at": sample.get("occurred_at"),
                "event_id": sample.get("event_id"),
                "anomaly_type": sample.get("anomaly_type"),
            }
        )
    points.sort(key=lambda p: str(p.get("occurred_at") or ""))
    return points


def _gap_windows(points: list[dict[str, Any]], gap_threshold_s: float = 30.0) -> list[dict[str, Any]]:
    windows: list[dict[str, Any]] = []
    for index in range(1, len(points)):
        prev_at = points[index - 1].get("occurred_at")
        curr_at = points[index].get("occurred_at")
        if not prev_at or not curr_at:
            continue
        try:
            delta = (
                datetime.fromisoformat(str(curr_at).replace("Z", "+00:00"))
                - datetime.fromisoformat(str(prev_at).replace("Z", "+00:00"))
            ).total_seconds()
        except (TypeError, ValueError):
            continue
        if delta >= gap_threshold_s:
            window: dict[str, Any] = {
                "start_at": prev_at,
                "end_at": curr_at,
                "gap_seconds": round(delta, 1),
            }
            prev = points[index - 1]
            if "lon" in prev and "lat" in prev:
                window["start_lon"] = prev["lon"]
                window["start_lat"] = prev["lat"]
            windows.append(window)
    return windows


def _checkpoint_times(points: list[dict[str, Any]], milestones: Any) -> list[dict[str, Any]]:
    milestones = milestones or []
    checkpoints: list[dict[str, Any]] = []
    for milestone in milestones:
        if not isinstance(milestone, dict):
            continue
        checkpoints.append(
            {
                "id": milestone.get("id"),
                "type": milestone.get("type"),
                "occurred_at": milestone.get("timestamp"),
                "lat": milestone.get("lat"),
                "lon": milestone.get("lon"),
                "sequence": milestone.get("sequence"),
            }
        )
    for point in points:
        if point.get("anomaly_type") in {"stationary_stall", "stall"}:
            checkpoints.append(
                {
                    "id": f"stall-{point.get('event_id', '')[:8]}",
                    "type": "stall",
                    "occurred_at": point.get("occurred_at"),
                    "lat": point["lat"],
                    "lon": point["lon"],
                    "sequence": None,
                }
            )
    return checkpoints


# ─── Static Maps request builders ───────────────────────────────────────────


def _marker(lon: float, lat: float, color: str, text: str, icon: str | None = None) -> str:
    parts = [f"lonlat:{lon},{lat}", f"color:{color}", "type:material", "size:medium"]
    if icon:
        parts.append(f"icon:{icon}")
        parts.append("icontype:material")
    else:
        parts.append(f"text:{text}")
        parts.append("contentcolor:white")
    return ";".join(parts)


def build_get_url(
    *,
    center_lon: float,
    center_lat: float,
    zoom: int,
    markers: list[dict[str, Any]],
    traveled_polyline: list[list[float]],
    gap_segments: list[list[list[float]]],
    planned_routes: list[dict[str, Any]],
    api_key: str,
    width: int = _WIDTH,
    height: int = _HEIGHT,
) -> str | None:
    """Build a Static Maps GET request; None if URL would exceed the provider limit."""
    marker_param = "|".join(_marker(m["lon"], m["lat"], m["color"], m.get("text", ""), m.get("icon")) for m in markers)
    block: list[str] = [f"marker={marker_param}"]

    features: list[dict[str, Any]] = []
    if len(traveled_polyline) >= 2:
        features.append(
            {
                "type": "Feature",
                "properties": {"linecolor": "%232563EB", "linewidth": 4, "linestyle": "solid"},
                "geometry": {"type": "LineString", "coordinates": [[lon, lat] for lon, lat in traveled_polyline]},
            }
        )
    for segment in gap_segments:
        if len(segment) >= 3:
            features.append(
                {
                    "type": "Feature",
                    "properties": {
                        "linecolor": "%23E11D48",
                        "linewidth": 2,
                        "linestyle": "dashed",
                        "fillcolor": "%23E11D48",
                        "fillopacity": 0.25,
                    },
                    "geometry": {"type": "Polygon", "coordinates": [[[lon, lat] for lon, lat in segment]]},
                }
            )
    for planned in planned_routes:
        points = planned.get("points") or []
        if len(points) >= 2:
            features.append(
                {
                    "type": "Feature",
                    "properties": {"linecolor": "%23BA1A1A", "linewidth": 3, "linestyle": "dashed"},
                    "geometry": {"type": "LineString", "coordinates": [[lon, lat] for lon, lat in points]},
                }
            )
    if features:
        block.append("geojson=" + json.dumps({"type": "FeatureCollection", "features": features}))

    params = (
        f"style={_STYLE}&width={width}&height={height}"
        f"&center=lonlat:{center_lon},{center_lat}&zoom={zoom}"
        f"&{'&'.join(block)}&apiKey={api_key}"
    )
    url = "https://maps.geoapify.com/v1/staticmap?" + params
    # geojson block needs URL encoding; keep encode for measurement explicit.
    return url if len(url) <= _GET_URL_LIMIT else None


def build_post_payload(
    *,
    center_lon: float,
    center_lat: float,
    zoom: int,
    markers: list[dict[str, Any]],
    traveled_polyline: list[list[float]],
    planned_routes: list[dict[str, Any]],
    width: int = _WIDTH,
    height: int = _HEIGHT,
) -> dict[str, Any]:
    """Deterministic POST body for complex geometries that exceed GET limits."""
    features: list[dict[str, Any]] = []
    if len(traveled_polyline) >= 2:
        features.append(
            {
                "type": "polyline6",
                "linecolor": "#2563EB",
                "linewidth": 4,
                "linestyle": "solid",
                "value": _encode_polyline([[lat, lon] for lon, lat in traveled_polyline], 6),
            }
        )
    for planned in planned_routes:
        points = planned.get("points") or []
        if len(points) >= 2:
            features.append(
                {
                    "type": "polyline6",
                    "linecolor": "#BA1A1A",
                    "linewidth": 3,
                    "linestyle": "dashed",
                    "value": _encode_polyline([[lat, lon] for lon, lat in points], 6),
                }
            )
    return {
        "style": _STYLE,
        "width": width,
        "height": height,
        "center": {"lon": center_lon, "lat": center_lat},
        "zoom": zoom,
        "markers": [
            {"lon": m["lon"], "lat": m["lat"], "color": m["color"], "type": "material", "size": "medium"}
            for m in markers
        ],
        "geometries": features,
    }


# ─── Provider render / unavailable union ────────────────────────────────────


def _gap_overlay(start: list[float], end: list[float], width_deg: float = 0.0005) -> list[list[float]]:
    """Deterministic rectangular polygon overlay marking a telemetry gap.

    ``width_deg`` is roughly 55 m at Hanoi latitude; the resulting ring is a
    closed 5-vertex polygon so Static Maps draws it as a gap area, not a line.
    """
    sx, sy = start
    ex, ey = end
    dx, dy = ex - sx, ey - sy
    norm = math.hypot(dx, dy) or 1.0
    px, py = -dy / norm * width_deg, dx / norm * width_deg
    return [
        [sx, sy],
        [sx + px, sy + py],
        [ex + px, ey + py],
        [ex, ey],
        [sx, sy],
    ]


def _unavailable(code: UnavailableCode, message: str, retry_guidance: str, retryable: bool) -> Unavailable:
    return {"code": code, "message": message, "retry_guidance": retry_guidance, "retryable": retryable}


def render_static_map(
    *,
    url: str | None,
    post_payload: dict[str, Any] | None,
    api_key: str,
    opener: Any = safe_urlopen,
    poster: Any = safe_urlpost,
    timeout: float = 8.0,
) -> tuple[bytes | None, Unavailable | None, int]:
    """Fetch the rendered map. Returns (bytes, unavailable, credits).

    No blank image is ever presented as evidence: empty geometry returns a
    structured ``no_geometry`` unavailable, and provider HTTP failures map to
    quota/provider codes with retry guidance.
    """
    has_geometry = url is not None or (
        post_payload is not None and bool(post_payload.get("geometries") or post_payload.get("markers"))
    )
    if not has_geometry:
        return (
            None,
            _unavailable("no_geometry", "No map request could be built", "Provide route or telemetry geometry", False),
            0,
        )
    cost_credits = 1
    try:
        if url is not None:
            with opener(url, timeout=timeout) as response:
                if response.status != 200:
                    return (
                        None,
                        _unavailable(
                            _http_code(response.status),
                            "Provider rejected the map request",
                            _http_retry_guidance(response.status),
                            response.status in (429, 500, 502, 503, 504),
                        ),
                        0,
                    )
                return response.read(), None, cost_credits
        if post_payload is not None:
            target = "https://maps.geoapify.com/v1/staticmap?apiKey=" + api_key
            with poster(target, json.dumps(post_payload).encode(), timeout=timeout) as response:
                if response.status != 200:
                    return (
                        None,
                        _unavailable(
                            _http_code(response.status),
                            "Provider rejected the map request",
                            _http_retry_guidance(response.status),
                            response.status in (429, 500, 502, 503, 504),
                        ),
                        0,
                    )
                return response.read(), None, cost_credits
        return (
            None,
            _unavailable("no_geometry", "No map request could be built", "Provide route or telemetry geometry", False),
            0,
        )
    except TimeoutError:
        return (
            None,
            _unavailable(
                "provider_timeout", "Map provider timed out", "Retry once; reduce geometry span if repeated", True
            ),
            0,
        )
    except HTTPError as exc:
        return (
            None,
            _unavailable(
                _http_code(exc.code),
                "Provider rejected the map request",
                _http_retry_guidance(exc.code),
                exc.code in (429, 500, 502, 503, 504),
            ),
            0,
        )
    except URLError as exc:
        if isinstance(exc.reason, TimeoutError):
            return (
                None,
                _unavailable(
                    "provider_timeout", "Map provider timed out", "Retry once; reduce geometry span if repeated", True
                ),
                0,
            )
        return (
            None,
            _unavailable(
                "provider_unavailable", "Map provider is unavailable", "Retry later; check provider status", True
            ),
            0,
        )
    except Exception:
        return (
            None,
            _unavailable(
                "provider_unavailable", "Map provider is unavailable", "Retry later; check provider status", True
            ),
            0,
        )


def _http_code(status: int) -> UnavailableCode:
    code = {401: "provider_unavailable", 403: "provider_unavailable", 429: "quota_exceeded"}.get(
        status, "provider_unavailable"
    )
    return cast(UnavailableCode, code)


def _http_retry_guidance(status: int) -> str:
    if status == 429:
        return "Quota exceeded; retry after the provider limit resets"
    if status >= 500:
        return "Provider error; retry once with backoff"
    return "Check map request parameters"


# ─── Snapshot assembly ──────────────────────────────────────────────────────


def deterministic_key(revision: int, hash_val: str) -> str:
    """Stable artifact identity for one frozen revision (deterministic ref)."""
    return hashlib.sha256(f"case-map:v1:{revision}:{hash_val}".encode()).hexdigest()[:24]


def build_map_snapshot(
    *,
    case_id: str,
    evidence_snapshot: dict[str, Any],
    route_refs: list[dict[str, Any]],
    telemetry_samples: list[dict[str, Any]],
    milestones: Any,
    planned_routes_geometry: dict[str, Any] | None,
    api_key: str,
    opener: Any = safe_urlopen,
    poster: Any = safe_urlpost,
    render: bool = True,
) -> MapSnapshot:
    """Assemble the deterministic artifact from one frozen evidence revision.

    ``render=False`` builds refs only (unit/contract tests keep transport off).
    """
    snapshot_id = str(evidence_snapshot.get("id") or "")
    revision = int(evidence_snapshot.get("version") or 0)
    hash_val = evidence_snapshot.get("hash") or ""
    if isinstance(hash_val, bytes):
        hash_val = hash_val.hex()
    cutoff = evidence_snapshot.get("cutoff_at")
    rendered_at = (
        cutoff
        if isinstance(cutoff, str)
        else (cutoff.isoformat() if isinstance(cutoff, datetime) else datetime.now(UTC).isoformat())
    )

    points = _telemetry_points(evidence_snapshot.get("dossier") or {}, telemetry_samples)
    checkpoints = _checkpoint_times(points, milestones)
    gaps = _gap_windows(points)
    planned_legs = _decode_route(planned_routes_geometry)
    planned_sets = [{"leg": leg, "points": _flatten_points(geometry)} for leg, geometry in planned_legs]

    all_points = [{"lon": p["lon"], "lat": p["lat"]} for p in points]
    for planned in planned_sets:
        all_points.extend({"lon": lon, "lat": lat} for lon, lat in planned["points"])
    min_lon, min_lat, span_lon, span_lat = _bounds([[p["lon"], p["lat"]] for p in all_points])
    center_lon = min_lon + span_lon / 2
    center_lat = min_lat + span_lat / 2
    zoom = _zoom_for_span(span_lon, span_lat)

    markers: list[dict[str, Any]] = []
    if points:
        markers.append(
            {"lon": points[0]["lon"], "lat": points[0]["lat"], "color": "green", "text": "S", "icon": "flag"}
        )
        markers.append({"lon": points[-1]["lon"], "lat": points[-1]["lat"], "color": "blue", "text": "D"})
    for checkpoint in checkpoints:
        if checkpoint.get("type") == "stall" and checkpoint.get("lat") is not None:
            markers.append({"lon": checkpoint["lon"], "lat": checkpoint["lat"], "color": "red", "text": "STALL"})
    if planned_legs:
        pickup_points = _flatten_points(planned_legs[0][1])
        if pickup_points:
            markers.append({"lon": pickup_points[0][0], "lat": pickup_points[0][1], "color": "purple", "text": "P"})

    traveled_polyline = [[p["lon"], p["lat"]] for p in points]
    gap_segments: list[list[list[float]]] = []
    for gap in gaps:
        if "start_lon" not in gap:
            continue
        start = [gap["start_lon"], gap["start_lat"]]
        following = next(
            (p for p in points if str(p.get("occurred_at") or "") > str(gap["start_at"] or "")),
            points[-1] if points else None,
        )
        if following is None:
            continue
        gap_segments.append(_gap_overlay(start, [following["lon"], following["lat"]]))
    has_any_geometry = bool(points or planned_sets)

    url = (
        build_get_url(
            center_lon=center_lon,
            center_lat=center_lat,
            zoom=zoom,
            markers=markers,
            traveled_polyline=traveled_polyline,
            gap_segments=gap_segments,
            planned_routes=planned_sets,
            api_key=api_key,
        )
        if has_any_geometry
        else None
    )
    post_payload = build_post_payload(
        center_lon=center_lon,
        center_lat=center_lat,
        zoom=zoom,
        markers=markers,
        traveled_polyline=traveled_polyline,
        planned_routes=planned_sets,
    )

    unavailable: Unavailable | None = None
    image_ref: str | None = None
    image_preview: str | None = None
    cost_credits = 0
    if render:
        bytes_data, unavailable, cost_credits = render_static_map(
            url=url, post_payload=post_payload, api_key=api_key, opener=opener, poster=poster
        )
        if bytes_data is not None:
            mime = "image/png" if bytes_data[:8] == b"\x89PNG\r\n\x1a\n" else "image/jpeg"
            image_ref = f"data:{mime};base64," + base64.b64encode(bytes_data).decode()
            image_preview = image_ref[:120] + "..." if len(image_ref) > 120 else image_ref
    elif url is None and not has_any_geometry:
        unavailable = _unavailable(
            "no_geometry", "No observed or planned geometry", "Wait for telemetry ingestion or recorded route", False
        )

    return {
        "case_id": case_id,
        "evidence_snapshot_id": snapshot_id,
        "snapshot_version": revision,
        "snapshot_hash": hash_val,
        "route_refs": [_route_ref(leg, geometry) for leg, geometry in planned_legs],
        "checkpoint_times": checkpoints,
        "gap_windows": gaps,
        "traveled_path": points,
        "planned_routes": planned_sets,
        "provider": "geoapify",
        "style": _STYLE,
        "rendered_at": rendered_at,
        "image_ref": image_ref,
        "image_preview": image_preview,
        "attribution": _ATTRIBUTION,
        "cost_credits": cost_credits,
        "unavailable": unavailable,
        "deterministic_key": deterministic_key(revision, hash_val),
    }


def _route_ref(leg: str, geometry: dict[str, Any]) -> dict[str, Any]:
    return {"leg": leg, "geometry_type": geometry.get("type"), "vertex_count": len(_flatten_points(geometry))}

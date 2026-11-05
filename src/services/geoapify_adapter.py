"""Server-side Geoapify routing adapter; modeled traffic is advisory evidence."""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal, cast
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode

from src.services.route_provider import (
    RouteFailure,
    RouteRequest,
    RouteResult,
    RouteSuccess,
    http_failure,
    normalize_geometry,
    positive_metric,
    validate_request,
)
from src.services.routing_http import safe_urlopen, safe_urlpost

# Structured provider result unions for the read-only data operations. They
# reuse the closed failure vocabulary so tool adapters never see raw HTTP.
GeocodeCandidate = dict[str, Any]
MatchType = Literal["matched", "unmatched", "interpolated"]


@dataclass(frozen=True)
class GeocodeSuccess:
    candidates: list[GeocodeCandidate]
    query: str
    status: Literal["ok"] = field(default="ok", init=False)


@dataclass(frozen=True)
class GeocodeFailure:
    """Closed, safe failure vocabulary: never store URLs, bodies, headers or errors."""

    code: Literal[
        "invalid_input",
        "missing_key",
        "unauthorized",
        "forbidden",
        "rate_limited",
        "timeout",
        "unavailable",
        "malformed_payload",
        "no_result",
    ]
    http_status: int | None = None
    status: Literal["error"] = field(default="error", init=False)


GeocodeResult = GeocodeSuccess | GeocodeFailure


@dataclass(frozen=True)
class MapMatchWaypoint:
    """Per-point match result; original GPS is always preserved by callers."""

    original_index: int
    location: list[float]
    original_location: list[float]
    match_type: MatchType
    match_distance_m: float | None = None
    leg_index: int | None = None
    step_index: int | None = None


@dataclass(frozen=True)
class MapMatchSuccess:
    geometry: dict[str, Any]
    distance_m: int
    duration_s: float
    waypoints: list[MapMatchWaypoint]
    count_matched: int
    count_unmatched: int
    count_interpolated: int
    status: Literal["ok"] = field(default="ok", init=False)


@dataclass(frozen=True)
class MapMatchFailure:
    """Closed, safe failure vocabulary for the map-matching operation."""

    code: Literal[
        "invalid_input",
        "missing_key",
        "unauthorized",
        "forbidden",
        "rate_limited",
        "timeout",
        "unavailable",
        "malformed_payload",
        "no_match",
    ]
    http_status: int | None = None
    status: Literal["error"] = field(default="error", init=False)


MapMatchResult = MapMatchSuccess | MapMatchFailure


class GeoapifyAdapter:
    name = "geoapify"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        opener: Callable[..., Any] = safe_urlopen,
        poster: Callable[..., Any] = safe_urlpost,
    ):
        self._api_key = api_key if api_key is not None else os.getenv("GEOAPIFY_API_KEY", "")
        self._opener = opener
        self._poster = poster

    def route(self, request: RouteRequest) -> RouteResult:
        failure = validate_request(request)
        if failure:
            return failure
        if not self._api_key:
            return RouteFailure("missing_key")
        params = {
            "waypoints": f"{request.start[1]},{request.start[0]}|{request.end[1]},{request.end[0]}",
            "mode": request.mode,
            "type": request.route_type,
            "traffic": request.traffic,
            "format": "geojson",
            "units": "metric",
            "apiKey": self._api_key,
        }
        if request.instruction_details:
            params["details"] = "instruction_details"
        url = "https://api.geoapify.com/v1/routing?" + urlencode(params)
        try:
            with self._opener(url, timeout=max(0.1, min(float(request.timeout), 10.0))) as response:
                if response.status != 200:
                    return http_failure(response.status)
                payload = json.loads(response.read())
            if not isinstance(payload, dict) or not isinstance(payload.get("features"), list):
                return RouteFailure("malformed_payload")
            if not payload["features"]:
                return RouteFailure("no_route")
            feature = payload["features"][0]
            if not isinstance(feature, dict):
                return RouteFailure("malformed_payload")
            geometry, properties = normalize_geometry(feature.get("geometry")), feature.get("properties")
            if geometry is None or not isinstance(properties, dict):
                return RouteFailure("malformed_payload")
            distance, duration = positive_metric(properties.get("distance")), positive_metric(properties.get("time"))
            if distance is None or duration is None:
                return RouteFailure("malformed_payload")
            return RouteSuccess(
                {
                    "geometry": geometry,
                    "distance_m": int(round(distance)),
                    "duration_s": duration,
                    "provider": "geoapify",
                    "traffic_model": request.traffic,
                    "provenance": {
                        "source": "geoapify",
                        "status": "ok",
                        "mode": request.mode,
                        "route_type": request.route_type,
                        "traffic_observation": "modeled" if request.traffic == "approximated" else "free_flow_estimate",
                        "advisory": True,
                    },
                }
            )
        except TimeoutError:
            return RouteFailure("timeout")
        except HTTPError as exc:
            return http_failure(exc.code)
        except URLError as exc:
            return RouteFailure("timeout" if isinstance(exc.reason, TimeoutError) else "unavailable")
        except (ValueError, TypeError, KeyError, OverflowError):
            return RouteFailure("malformed_payload")
        except Exception:
            return RouteFailure("unavailable")

    # ─── Read-only data operations (geocode, reverse, map matching) ──────────

    def _geocode_entries(self, payload: Any) -> list[dict[str, Any]] | None:
        """Accept GeoJSON ``features`` or legacy ``results`` provider response."""
        if not isinstance(payload, dict):
            return None
        features = payload.get("features")
        if isinstance(features, list):
            return features
        results = payload.get("results")
        if isinstance(results, list):
            return results
        return None

    def _geocode_candidate(self, entry: Any, *, reverse: bool) -> GeocodeCandidate | None:
        if not isinstance(entry, dict):
            return None
        props = entry.get("properties")
        geometry = entry.get("geometry")
        lon: Any
        lat: Any
        if (
            isinstance(geometry, dict)
            and isinstance(geometry.get("coordinates"), list)
            and len(geometry.get("coordinates", [])) >= 2
        ):
            coords = geometry["coordinates"]
            lon, lat = coords[0], coords[1]
        else:
            lon, lat = entry.get("lon"), entry.get("lat")
        if (
            isinstance(lon, bool)
            or isinstance(lat, bool)
            or not isinstance(lon, (int, float))
            or not isinstance(lat, (int, float))
        ):
            return None
        p: dict[str, Any] = props if isinstance(props, dict) else entry
        rank: dict[str, Any] = p["rank"] if isinstance(p.get("rank"), dict) else {}
        datasource: dict[str, Any] = p["datasource"] if isinstance(p.get("datasource"), dict) else {}
        confidence = rank.get("confidence")
        return {
            "formatted": p.get("formatted") or p.get("name") or "",
            "lon": float(lon),
            "lat": float(lat),
            "result_type": p.get("result_type"),
            "country_code": p.get("country_code"),
            "distance_m": p.get("distance"),
            "confidence": float(confidence) if isinstance(confidence, (int, float)) else None,
            "match_type": rank.get("match_type"),
            "attribution": datasource.get("attribution"),
        }

    def geocode(self, text: str, *, limit: int = 5, timeout: float = 5.0) -> GeocodeResult:
        """Forward geocode; candidates carry confidence and lookup metadata."""
        if not isinstance(text, str) or not text.strip():
            return GeocodeFailure("invalid_input")
        if not self._api_key:
            return GeocodeFailure("missing_key")
        params = {"text": text, "limit": str(max(1, min(int(limit), 10))), "apiKey": self._api_key}
        url = "https://api.geoapify.com/v1/geocode/search?" + urlencode(params)
        try:
            with self._opener(url, timeout=max(0.1, min(float(timeout), 10.0))) as response:
                if response.status != 200:
                    return GeocodeFailure(_geocode_http_code(response.status), response.status)
                payload = json.loads(response.read())
            entries = self._geocode_entries(payload)
            if entries is None:
                return GeocodeFailure("malformed_payload")
            candidates: list[GeocodeCandidate] = []
            for entry in entries[: max(1, min(int(limit), 10))]:
                candidate = self._geocode_candidate(entry, reverse=False)
                if candidate is not None:
                    candidates.append(candidate)
            if not candidates:
                return GeocodeFailure("no_result")
            return GeocodeSuccess(candidates, text)
        except TimeoutError:
            return GeocodeFailure("timeout")
        except HTTPError as exc:
            return GeocodeFailure(_geocode_http_code(exc.code), exc.code)
        except URLError as exc:
            return GeocodeFailure("timeout" if isinstance(exc.reason, TimeoutError) else "unavailable")
        except (ValueError, TypeError, KeyError, OverflowError):
            return GeocodeFailure("malformed_payload")
        except Exception:
            return GeocodeFailure("unavailable")

    def reverse_geocode(self, lon: float, lat: float, *, limit: int = 5, timeout: float = 5.0) -> GeocodeResult:
        """Reverse geocode; candidates include provider distance to the query point."""
        if not _valid_coordinate(lon, lat):
            return GeocodeFailure("invalid_input")
        if not self._api_key:
            return GeocodeFailure("missing_key")
        params = {"lon": lon, "lat": lat, "limit": str(max(1, min(int(limit), 10))), "apiKey": self._api_key}
        url = "https://api.geoapify.com/v1/geocode/reverse?" + urlencode(params)
        try:
            with self._opener(url, timeout=max(0.1, min(float(timeout), 10.0))) as response:
                if response.status != 200:
                    return GeocodeFailure(_geocode_http_code(response.status), response.status)
                payload = json.loads(response.read())
            entries = self._geocode_entries(payload)
            if entries is None:
                return GeocodeFailure("malformed_payload")
            candidates: list[GeocodeCandidate] = []
            for entry in entries[: max(1, min(int(limit), 10))]:
                candidate = self._geocode_candidate(entry, reverse=True)
                if candidate is not None:
                    candidates.append(candidate)
            if not candidates:
                return GeocodeFailure("no_result")
            return GeocodeSuccess(candidates, f"{lon},{lat}")
        except TimeoutError:
            return GeocodeFailure("timeout")
        except HTTPError as exc:
            return GeocodeFailure(_geocode_http_code(exc.code), exc.code)
        except URLError as exc:
            return GeocodeFailure("timeout" if isinstance(exc.reason, TimeoutError) else "unavailable")
        except (ValueError, TypeError, KeyError, OverflowError):
            return GeocodeFailure("malformed_payload")
        except Exception:
            return GeocodeFailure("unavailable")

    def map_match(
        self,
        waypoints: list[dict[str, Any]],
        *,
        mode: str = "drive",
        timeout: float = 5.0,
    ) -> MapMatchResult:
        """Snap stored GPS to the road network; originals are never written back."""
        if not isinstance(waypoints, list) or len(waypoints) < 2:
            return MapMatchFailure("invalid_input")
        clean: list[dict[str, Any]] = []
        for wp in waypoints:
            location = wp.get("location") if isinstance(wp, dict) else None
            if not (isinstance(location, list) and len(location) >= 2):
                return MapMatchFailure("invalid_input")
            lon, lat = location[0], location[1]
            if not _valid_coordinate(lon, lat):
                return MapMatchFailure("invalid_input")
            point: dict[str, Any] = {"location": [float(lon), float(lat)]}
            timestamp = wp.get("timestamp")
            if timestamp:
                point["timestamp"] = timestamp
            clean.append(point)
        if not self._api_key:
            return MapMatchFailure("missing_key")
        body = json.dumps({"mode": mode, "waypoints": clean}).encode()
        url = "https://api.geoapify.com/v1/mapmatching?apiKey=" + self._api_key
        try:
            with self._poster(url, body, timeout=max(0.1, min(float(timeout), 10.0))) as response:
                if response.status != 200:
                    return MapMatchFailure(_geocode_http_code(response.status), response.status)
                payload = json.loads(response.read())
            features = payload.get("features") if isinstance(payload, dict) else None
            if not isinstance(features, list) or not features:
                return MapMatchFailure("no_match")
            feature = features[0]
            geometry = normalize_geometry(feature.get("geometry"))
            properties = feature.get("properties")
            if geometry is None or not isinstance(properties, dict):
                return MapMatchFailure("malformed_payload")
            distance, duration = positive_metric(properties.get("distance")), positive_metric(properties.get("time"))
            if distance is None or duration is None:
                return MapMatchFailure("malformed_payload")
            raw_waypoints = properties.get("waypoints")
            if not isinstance(raw_waypoints, list):
                return MapMatchFailure("malformed_payload")
            waypoint_results: list[MapMatchWaypoint] = []
            matched = unmatched = interpolated = 0
            for index, wp in enumerate(raw_waypoints):
                if not isinstance(wp, dict):
                    continue
                match_type = wp.get("match_type")
                if match_type not in ("matched", "unmatched", "interpolated"):
                    match_type = "unmatched"
                counts = {"matched": matched, "unmatched": unmatched, "interpolated": interpolated}
                counts[match_type] += 1
                matched, unmatched, interpolated = counts["matched"], counts["unmatched"], counts["interpolated"]
                match_distance = wp.get("match_distance")
                waypoint_results.append(
                    MapMatchWaypoint(
                        original_index=wp.get("original_index", index),
                        location=wp.get("location") or [],
                        original_location=wp.get("original_location") or [],
                        match_type=cast(MatchType, match_type),
                        match_distance_m=float(match_distance) if isinstance(match_distance, (int, float)) else None,
                        leg_index=wp.get("leg_index"),
                        step_index=wp.get("step_index"),
                    )
                )
            return MapMatchSuccess(
                geometry=geometry,
                distance_m=int(round(distance)),
                duration_s=duration,
                waypoints=waypoint_results,
                count_matched=matched,
                count_unmatched=unmatched,
                count_interpolated=interpolated,
            )
        except TimeoutError:
            return MapMatchFailure("timeout")
        except HTTPError as exc:
            return MapMatchFailure(_geocode_http_code(exc.code), exc.code)
        except URLError as exc:
            return MapMatchFailure("timeout" if isinstance(exc.reason, TimeoutError) else "unavailable")
        except (ValueError, TypeError, KeyError, OverflowError):
            return MapMatchFailure("malformed_payload")
        except Exception:
            return MapMatchFailure("unavailable")


def _valid_coordinate(lon: Any, lat: Any) -> bool:
    if (
        isinstance(lon, bool)
        or isinstance(lat, bool)
        or not isinstance(lon, (int, float))
        or not isinstance(lat, (int, float))
    ):
        return False
    return -180 <= float(lon) <= 180 and -90 <= float(lat) <= 90


def _geocode_http_code(status: int) -> Literal["unauthorized", "forbidden", "rate_limited", "unavailable"]:
    code = {401: "unauthorized", 403: "forbidden", 429: "rate_limited"}.get(status, "unavailable")
    return cast(Literal["unauthorized", "forbidden", "rate_limited", "unavailable"], code)

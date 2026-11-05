"""OSRM implementation of the routing port with legacy rounding preserved."""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from typing import Any
from urllib.error import HTTPError, URLError

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
from src.services.routing_http import safe_urlopen


class OSRMAdapter:
    name = "osrm"

    def __init__(self, *, opener: Callable[..., Any] = safe_urlopen):
        self._opener = opener

    def route(self, request: RouteRequest) -> RouteResult:
        failure = validate_request(request)
        if failure:
            return failure
        if request.mode != "drive" or request.traffic != "free_flow" or request.route_type != "balanced":
            return RouteFailure("unsupported_option")
        start_lon, start_lat = map(float, request.start)
        end_lon, end_lat = map(float, request.end)

        base = os.getenv("OSRM_BASE_URL", "https://router.project-osrm.org").rstrip("/")
        url = f"{base}/route/v1/driving/{start_lon},{start_lat};{end_lon},{end_lat}?overview=full&geometries=geojson"
        try:
            with self._opener(url, timeout=max(0.1, min(float(request.timeout), 10.0))) as response:
                if response.status != 200:
                    return http_failure(response.status)
                payload = json.loads(response.read())
            if not isinstance(payload, dict) or not isinstance(payload.get("routes"), list):
                return RouteFailure("malformed_payload")
            if not payload["routes"]:
                return RouteFailure("no_route")
            route = payload["routes"][0]
            if not isinstance(route, dict):
                return RouteFailure("malformed_payload")
            geometry = normalize_geometry(route.get("geometry"))
            if geometry is None:
                return RouteFailure("malformed_payload")
            distance, duration = positive_metric(route.get("distance")), positive_metric(route.get("duration"))
            if distance is None or duration is None:
                return RouteFailure("malformed_payload")
            return RouteSuccess(
                {
                    "geometry": geometry,
                    "distance_m": int(round(distance)),
                    "duration_s": int(round(duration)),
                    "provider": "osrm",
                    "traffic_model": "free_flow",
                    "provenance": {"source": "osrm", "status": "ok"},
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

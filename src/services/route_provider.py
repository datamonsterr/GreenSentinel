"""Replaceable server-side routing port; adapters never expose provider exceptions."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, TypeAlias, TypedDict

TravelMode: TypeAlias = Literal["drive", "scooter", "motorcycle"]
TrafficModel: TypeAlias = Literal["free_flow", "approximated"]
RouteType: TypeAlias = Literal["balanced", "short"]
FailureCode: TypeAlias = Literal[
    "invalid_input",
    "unsupported_option",
    "missing_key",
    "unauthorized",
    "forbidden",
    "rate_limited",
    "timeout",
    "unavailable",
    "malformed_payload",
    "no_route",
]


@dataclass(frozen=True)
class RouteRequest:
    """WGS84 longitude/latitude inputs. GreenSM Bike defaults to motorcycle."""

    start: list[float]
    end: list[float]
    mode: TravelMode = "motorcycle"
    route_type: RouteType = "balanced"
    traffic: TrafficModel = "free_flow"
    instruction_details: bool = True
    timeout: float = 5.0


class RouteData(TypedDict):
    geometry: dict[str, Any]
    distance_m: int
    duration_s: float
    provider: str
    traffic_model: TrafficModel
    provenance: dict[str, Any]


@dataclass(frozen=True)
class RouteSuccess:
    data: RouteData
    status: Literal["ok"] = field(default="ok", init=False)


@dataclass(frozen=True)
class RouteFailure:
    """Closed, safe failure vocabulary: never store URLs, bodies, headers or errors."""

    code: FailureCode
    http_status: int | None = None
    status: Literal["error"] = field(default="error", init=False)


RouteResult: TypeAlias = RouteSuccess | RouteFailure


class RouteProvider(Protocol):
    name: str

    def route(self, request: RouteRequest) -> RouteResult: ...


def coordinate(value: Any) -> list[float] | None:
    """Validate WGS84 lon/lat. A swapped Hanoi pair has latitude over 90."""
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        return None
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) for v in value):
        return None
    lon, lat = value
    if not (-180 <= lon <= 180 and -90 <= lat <= 90) or not math.isfinite(lon) or not math.isfinite(lat):
        return None
    return [float(lon), float(lat)]


def validate_request(request: RouteRequest) -> RouteFailure | None:
    if coordinate(request.start) is None or coordinate(request.end) is None:
        return RouteFailure("invalid_input")
    if (
        isinstance(request.timeout, bool)
        or not isinstance(request.timeout, (int, float))
        or not 0 < request.timeout <= 1e9
        or not math.isfinite(request.timeout)
    ):
        return RouteFailure("invalid_input")
    if (
        request.mode not in ("drive", "scooter", "motorcycle")
        or request.route_type not in ("balanced", "short")
        or request.traffic not in ("free_flow", "approximated")
        or not isinstance(request.instruction_details, bool)
    ):
        return RouteFailure("unsupported_option")
    return None


def http_failure(status: int) -> RouteFailure:
    failures: dict[int, FailureCode] = {401: "unauthorized", 403: "forbidden", 429: "rate_limited"}
    code = failures.get(status, "unavailable")
    return RouteFailure(code, status)


def positive_metric(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not 0 < value <= 1e15 or not math.isfinite(value):
        return None
    return float(value)


def normalize_geometry(value: Any) -> dict[str, Any] | None:
    """Retain only contiguous valid runs; never join legs or bridge a bad vertex."""
    if not isinstance(value, dict) or value.get("type") not in {"LineString", "MultiLineString"}:
        return None
    coordinates = value.get("coordinates")
    if not isinstance(coordinates, list):
        return None
    legs = [coordinates] if value["type"] == "LineString" else coordinates
    runs: list[list[list[float]]] = []
    for leg in legs:
        if not isinstance(leg, list):
            continue
        run: list[list[float]] = []
        for vertex in leg:
            point = coordinate(vertex)
            if point is not None:
                run.append(point)
            else:
                if len(run) >= 2:
                    runs.append(run)
                run = []
        if len(run) >= 2:
            runs.append(run)
    if not runs:
        return None
    if value["type"] == "LineString" and len(runs) == 1:
        return {"type": "LineString", "coordinates": runs[0]}
    return {"type": "MultiLineString", "coordinates": runs}

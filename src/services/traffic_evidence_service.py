"""First-party historical traffic and non-retained external incident evidence."""

import asyncio
import json
import math
import statistics
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit

import httpx

from src.config import get_settings

_MAX_BODY = 512 * 1024
_MAX_INCIDENTS = 100


def _incident_unavailable(reason: str) -> dict[str, Any]:
    return {
        "status": "unavailable",
        "reason": reason,
        "historical_absence_proven": False,
        "retention": "memory_only",
    }


class TrafficEvidenceService:
    """Assess peer telemetry and fetch bounded external incident evidence."""

    def __init__(self, settings: Any | None = None, *, client: httpx.AsyncClient | None = None) -> None:
        self.settings = settings or get_settings()
        self._client = client

    async def fetch_corridor_historical_traffic(
        self,
        bbox: list[float],
        start_time: str,
        end_time: str,
        *,
        peer_trip_speeds_kmh: list[float] | None = None,
    ) -> dict[str, Any]:
        error = _validate_query(bbox, start_time, end_time)
        if error:
            return error
        speeds = [_number(value) for value in (peer_trip_speeds_kmh or [])]
        valid_speeds = [value for value in speeds if value is not None and value >= 0]
        if len(valid_speeds) < 3:
            return {"status": "unavailable", "reason": "insufficient_peer_evidence"}
        observed = statistics.median(valid_speeds)
        ordered = sorted(valid_speeds)
        rank = 0.85 * (len(ordered) - 1)
        lower = math.floor(rank)
        upper = math.ceil(rank)
        free_flow = ordered[lower] + (ordered[upper] - ordered[lower]) * (rank - lower)
        if free_flow <= 0:
            return {"status": "unavailable", "reason": "insufficient_peer_evidence"}
        ratio = max(0.0, min(1.0, 1.0 - observed / free_flow))
        return {
            "status": "available",
            "source_type": "first_party_peer_telemetry",
            "peer_count": len(valid_speeds),
            "observed_speed_kmh": round(observed, 6),
            "free_flow_speed_kmh": round(free_flow, 6),
            "congestion_ratio": round(ratio, 6),
            "congested": ratio >= 0.3,
            "window_start": start_time,
            "window_end": end_time,
            "method": "median_peer_trip_speed_vs_p85_peer_baseline",
        }

    async def query_traffic_incident_feed(self, bbox: list[float], start_time: str, end_time: str) -> dict[str, Any]:
        error = _validate_query(bbox, start_time, end_time)
        if error:
            return error
        url = _safe_url(getattr(self.settings, "traffic_incidents_url", ""))
        if not url:
            return _incident_unavailable("provider_not_configured")
        payload = await self._request(url, bbox, start_time, end_time)
        if payload.get("status") != "available":
            return payload
        raw = payload.get("incidents")
        if not isinstance(raw, list):
            return _incident_unavailable("provider_unreachable")
        incidents = [_normalize_incident(item) for item in raw[:_MAX_INCIDENTS]]
        if any(item is None for item in incidents):
            return _incident_unavailable("provider_unreachable")
        observed_at = datetime.now(UTC).isoformat()
        if not incidents:
            return {
                "status": "available",
                "incidents": [],
                "congested": False,
                "observed_at": observed_at,
                "historical_absence_proven": False,
                "retention": "memory_only",
            }
        congested = payload.get("congested")
        if not isinstance(congested, bool):
            return _incident_unavailable("provider_unreachable")
        return {
            "status": "available",
            "incidents": incidents,
            "congested": congested,
            "observed_at": observed_at,
            "historical_absence_proven": False,
            "retention": "memory_only",
        }

    async def _request(self, url: str, bbox: list[float], start: str, end: str) -> dict[str, Any]:
        params = {"bbox": ",".join(str(value) for value in bbox), "start_time": start, "end_time": end}
        headers = {"Accept": "application/json"}
        api_key = str(getattr(self.settings, "traffic_api_key", "") or "")
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        timeout = min(float(getattr(self.settings, "traffic_timeout_seconds", 3.0)), 8.0)

        async def read(client: httpx.AsyncClient) -> dict[str, Any]:
            async with client.stream("GET", url, params=params, headers=headers, follow_redirects=False) as response:
                if not 200 <= response.status_code < 300:
                    return _incident_unavailable("provider_unreachable")
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    if len(body) + len(chunk) > _MAX_BODY:
                        return _incident_unavailable("provider_unreachable")
                    body.extend(chunk)
                data = json.loads(body)
                if not isinstance(data, dict) or data.get("status", "available") != "available":
                    return _incident_unavailable("provider_unreachable")
                data["status"] = "available"
                return data

        try:
            async with asyncio.timeout(timeout):
                if self._client is not None:
                    return await read(self._client)
                async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
                    return await read(client)
        except (TimeoutError, httpx.HTTPError, ValueError, TypeError):
            return _incident_unavailable("provider_unreachable")


def _safe_url(value: Any) -> str:
    if not isinstance(value, str) or not value:
        return ""
    try:
        parts = urlsplit(value)
        hostname = parts.hostname
        # Accessing port validates malformed/out-of-range port values.
        _ = parts.port
    except ValueError:
        return ""
    if parts.scheme != "https" or not hostname or parts.username or parts.password or parts.query or parts.fragment:
        return ""
    return value


def _validate_query(bbox: Any, start: str, end: str) -> dict[str, str] | None:
    if (
        not isinstance(bbox, list)
        or len(bbox) != 4
        or any(isinstance(value, bool) or not isinstance(value, (int, float)) for value in bbox)
    ):
        return {"status": "validation_error", "reason": "invalid_request"}
    try:
        values = [float(value) for value in bbox]
    except (TypeError, ValueError):
        return {"status": "validation_error", "reason": "invalid_request"}
    min_lon, min_lat, max_lon, max_lat = values
    if any(not math.isfinite(value) for value in values) or values == [0.0, 0.0, 0.0, 0.0]:
        return {"status": "validation_error", "reason": "invalid_request"}
    if not (-180 <= min_lon < max_lon <= 180 and -90 <= min_lat < max_lat <= 90):
        return {"status": "validation_error", "reason": "invalid_request"}
    try:
        start_dt = datetime.fromisoformat(start.replace("Z", "+00:00"))
        end_dt = datetime.fromisoformat(end.replace("Z", "+00:00"))
        if start_dt.tzinfo is None or end_dt.tzinfo is None or start_dt >= end_dt:
            raise ValueError
    except (AttributeError, TypeError, ValueError):
        return {"status": "validation_error", "reason": "invalid_request"}
    return None


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _safe_timestamp(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return value if parsed.tzinfo else None


def _normalize_incident(item: Any) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None
    result: dict[str, Any] = {}
    for key in ("id", "type", "severity", "description", "status"):
        value = item.get(key)
        if isinstance(value, (str, int, float)) and not isinstance(value, bool):
            text = str(value).replace("\x00", "")[:500]
            result[key] = text
    for key in ("start_time", "end_time", "updated_at"):
        timestamp = _safe_timestamp(item.get(key))
        if timestamp:
            result[key] = timestamp
    return result or None


async def fetch_corridor_historical_traffic(
    bbox: list[float],
    start_time: str,
    end_time: str,
    *,
    peer_trip_speeds_kmh: list[float] | None = None,
) -> dict[str, Any]:
    """Assess first-party peer telemetry supplied by trusted dispatch."""
    return await TrafficEvidenceService().fetch_corridor_historical_traffic(
        bbox, start_time, end_time, peer_trip_speeds_kmh=peer_trip_speeds_kmh
    )


async def query_traffic_incident_feed(bbox: list[float], start_time: str, end_time: str) -> dict[str, Any]:
    """Default gateway used by trusted tool dispatch."""
    return await TrafficEvidenceService().query_traffic_incident_feed(bbox, start_time, end_time)

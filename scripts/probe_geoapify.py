"""Bounded, sanitized Geoapify capability probe (server-side use only)."""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

CAPABILITIES = ("geocode", "reverse_geocode", "routing", "map_matching", "map_style", "mcp_tools")
_ENDPOINT = "https://api.geoapify.com/v1"


@dataclass(frozen=True)
class ProbeRequest:
    operation: str
    method: str
    endpoint: str
    parameters: dict[str, Any] | None = None
    body: dict[str, Any] | None = None


def build_requests() -> list[ProbeRequest]:
    return [
        ProbeRequest(
            "geocode",
            "GET",
            f"{_ENDPOINT}/geocode/search",
            {"text": "Hoan Kiem Lake, Hanoi, Vietnam", "filter": "countrycode:vn", "limit": 1},
        ),
        ProbeRequest(
            "reverse_geocode", "GET", f"{_ENDPOINT}/geocode/reverse", {"lat": 21.0278, "lon": 105.8342, "limit": 1}
        ),
        ProbeRequest(
            "routing",
            "GET",
            f"{_ENDPOINT}/routing",
            {"waypoints": "21.0278,105.8342|21.0285,105.8443", "mode": "drive", "traffic": "free_flow"},
        ),
        ProbeRequest(
            "map_matching",
            "POST",
            f"{_ENDPOINT}/mapmatching",
            body={
                "mode": "drive",
                "waypoints": [
                    {"location": [105.8342, 21.0278], "timestamp": "2026-10-08T08:00:00Z"},
                    {"location": [105.8352, 21.028], "timestamp": "2026-10-08T08:00:30Z"},
                    {"location": [105.8362, 21.0282], "timestamp": "2026-10-08T08:01:00Z"},
                ],
            },
        ),
        ProbeRequest("map_style", "GET", "https://maps.geoapify.com/v1/styles/osm-bright/style.json"),
        ProbeRequest("mcp_tools", "POST", f"{_ENDPOINT}/mcp", body={"jsonrpc": "2.0", "id": 1, "method": "tools/list"}),
    ]


def classify_failure(status: int | None, *, malformed: bool = False, timed_out: bool = False) -> str:
    if timed_out:
        return "timeout"
    if malformed:
        return "malformed_response"
    return {401: "unauthorized", 403: "forbidden", 429: "rate_limited"}.get(status, "provider_unavailable")


class HanoiTransport:
    """urllib transport plus deterministic offline failure fixture."""

    def __init__(self, failure_mode: bool = False):
        self.failure_mode = failure_mode
        self._index = 0

    def request(self, request: ProbeRequest, key: str | None, timeout: float = 10.0) -> tuple[int, Any]:
        if self.failure_mode:
            failure = [401, 403, 429, "malformed", "timeout", 599][self._index]
            self._index += 1
            if failure == "timeout":
                raise TimeoutError
            if failure == "malformed":
                return 200, {"unexpected": True}
            return failure, {}
        params = dict(request.parameters or {})
        params["apiKey"] = key or ""
        url = request.endpoint + (
            "?" + urllib.parse.urlencode(params) if params else "?apiKey=" + urllib.parse.quote(key or "")
        )
        data = json.dumps(request.body).encode() if request.body is not None else None
        headers = {"Content-Type": "application/json"} if data else {}
        if request.operation == "mcp_tools":
            headers["x-api-key"] = key or ""
            url = request.endpoint
        req = urllib.request.Request(url, data=data, headers=headers, method=request.method)
        try:

            class _NoRedirect(urllib.request.HTTPRedirectHandler):
                def redirect_request(self, req, fp, code, msg, headers, new_url):
                    raise urllib.error.HTTPError(req.full_url, code, "redirect blocked", headers, fp)

            with urllib.request.build_opener(_NoRedirect()).open(req, timeout=timeout) as response:
                raw = response.read(2 * 1024 * 1024 + 1)
                if len(raw) > 2 * 1024 * 1024:
                    raise ValueError("response too large")
                return response.status, json.loads(raw)
        except urllib.error.HTTPError as exc:
            return exc.code, {}


def _valid_position(coordinates: Any) -> bool:
    return (
        isinstance(coordinates, list)
        and len(coordinates) in (2, 3)
        and all(type(value) in (int, float) and -1e308 <= value <= 1e308 for value in coordinates)
        and -180 <= coordinates[0] <= 180
        and -90 <= coordinates[1] <= 90
    )


def _valid_line(coordinates: Any) -> bool:
    return (
        isinstance(coordinates, list)
        and len(coordinates) >= 2
        and all(_valid_position(position) for position in coordinates)
    )


def _valid_geometry(geometry: Any, operation: str) -> bool:
    if not isinstance(geometry, dict):
        return False
    geometry_type = geometry.get("type")
    coordinates = geometry.get("coordinates")
    if operation in ("geocode", "reverse_geocode"):
        return geometry_type == "Point" and _valid_position(coordinates)
    if operation == "routing" and geometry_type == "LineString":
        return _valid_line(coordinates)
    return (
        geometry_type == "MultiLineString"
        and isinstance(coordinates, list)
        and bool(coordinates)
        and all(_valid_line(line) for line in coordinates)
    )


def _success(request: ProbeRequest, status: int, payload: Any) -> dict[str, Any] | None:
    if status != 200 or not isinstance(payload, dict):
        return None
    result: dict[str, Any] = {"operation": request.operation, "http_status": status}
    if request.operation in {"geocode", "reverse_geocode", "routing", "map_matching"}:
        features = payload.get("features")
        if (
            not isinstance(features, list)
            or not features
            or not all(
                isinstance(feature, dict) and _valid_geometry(feature.get("geometry"), request.operation)
                for feature in features
            )
        ):
            return None
        result["feature_count"] = len(features)
        if features:
            geometry = features[0].get("geometry")
            if isinstance(geometry, dict) and geometry.get("type") in {"Point", "LineString", "MultiLineString"}:
                result["geometry_type"] = geometry["type"]
            else:
                return None
            properties = features[0].get("properties")
            if isinstance(properties, dict):
                for name in ("distance", "time"):
                    value = properties.get(name)
                    if (
                        isinstance(value, (int, float))
                        and not isinstance(value, bool)
                        and 0 <= value <= 1e15
                        and math.isfinite(value)
                    ):
                        result[name] = value
                for name, allowed in (
                    ("mode", ("drive", "scooter", "motorcycle")),
                    ("traffic", ("free_flow", "approximated")),
                    ("country_code", ("vn",)),
                ):
                    if properties.get(name) in allowed:
                        result[name] = properties[name]
                if request.operation == "map_matching" and isinstance(properties.get("waypoints"), list):
                    result["match_types"] = [
                        waypoint.get("match_type")
                        if isinstance(waypoint, dict)
                        and waypoint.get("match_type") in ("matched", "unmatched", "interpolated")
                        else "unknown"
                        for waypoint in properties["waypoints"]
                    ]
    elif request.operation == "map_style":
        sources, layers = payload.get("sources"), payload.get("layers")
        if (
            type(payload.get("version")) is not int
            or payload["version"] != 8
            or not isinstance(sources, dict)
            or not sources
            or not all(isinstance(source, dict) for source in sources.values())
            or not isinstance(layers, list)
            or not layers
            or not all(isinstance(layer, dict) for layer in layers)
        ):
            return None
        result.update(
            {
                "style_version": 8,
                "source_count": len(sources),
                "layer_count": len(layers),
            }
        )
    elif request.operation == "mcp_tools":
        if payload.get("jsonrpc") != "2.0" or not isinstance(payload.get("result"), dict) or "error" in payload:
            return None
        tools = payload["result"].get("tools")
        if not isinstance(tools, list) or not tools or not all(isinstance(tool, dict) for tool in tools):
            return None
        result["tool_count"] = len(tools)
    return result


def run_probes(transport: HanoiTransport, *, live: bool, env_file: Path | None = None) -> list[dict[str, Any]]:
    results = []
    try:
        key = (_read_key(env_file) if env_file is not None else _read_key()) if live else None
    except Exception:
        key = None
    for request in build_requests():
        if live and not key:
            results.append({"operation": request.operation, "failure": "missing_key"})
            continue
        try:
            status, payload = transport.request(request, key)
            item = _success(request, status, payload)
            results.append(
                item
                or {
                    "operation": request.operation,
                    "failure": classify_failure(status, malformed=status == 200),
                    **({"http_status": status} if status in {401, 403, 429} else {}),
                }
            )
        except TimeoutError:
            results.append({"operation": request.operation, "failure": "timeout"})
        except urllib.error.URLError as exc:
            results.append(
                {
                    "operation": request.operation,
                    "failure": "timeout" if isinstance(exc.reason, TimeoutError) else "provider_unavailable",
                }
            )
        except OSError:
            results.append({"operation": request.operation, "failure": "provider_unavailable"})
        except (ValueError, RuntimeError, TypeError, AttributeError):
            results.append({"operation": request.operation, "failure": "malformed_response"})
        except Exception:
            results.append({"operation": request.operation, "failure": "provider_unavailable"})
        if live:
            time.sleep(0.21)
    return results


def _read_key(env_file: Path = Path(".env")) -> str:
    key = os.getenv("GEOAPIFY_API_KEY")
    if key:
        return key
    if not env_file.is_file() or not _ignored(env_file):
        return ""
    from dotenv import dotenv_values

    return dotenv_values(env_file, interpolate=False).get("GEOAPIFY_API_KEY") or ""


def _ignored(path: Path) -> bool:
    try:
        result = subprocess.run(
            ["git", "-C", str(path.resolve().parent), "check-ignore", "-q", str(path.resolve())],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=2,
            check=False,
        )
        if result.returncode not in (0, 1):
            print(
                f"Unable to verify git ignore status for {path}: git check-ignore returned code {result.returncode}; "
                "refusing credential file.",
                file=sys.stderr,
            )
            return False
        return result.returncode == 0
    except (OSError, subprocess.SubprocessError) as exc:
        print(
            f"Unable to verify git ignore status for {path}: git unavailable ({exc}); refusing credential file.",
            file=sys.stderr,
        )
        return False


def _revision() -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=2,
            check=False,
        )
        value = result.stdout.strip()
        return value if re.fullmatch(r"[0-9a-f]{40}", value) else None
    except (OSError, subprocess.SubprocessError):
        return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--live", action="store_true")
    group.add_argument("--offline-failures", action="store_true")
    parser.add_argument("--env-file", type=Path, default=Path(".env"))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    results = run_probes(HanoiTransport(args.offline_failures), live=args.live, env_file=args.env_file)
    record = {
        "evidence_class": "bounded_live_provider_probe_summary" if args.live else "offline_failure_fixture",
        "source_revision": _revision(),
        "environment": "local opt-in public Hanoi sample locations"
        if args.live
        else "local deterministic transport fixture",
        "transport": "Python standard-library urllib.request; sequential; timeout 10 seconds; no retries",
        "limitations": [
            "Credentials and raw provider responses are omitted.",
            "Account plan, national coverage, application UI and hosted acceptance are unverified.",
            "Map-matching timestamps are authored public examples, not measured historical telemetry.",
            "No live invalid-key or paid route-details requests; failure cases use fixture transport.",
        ],
        "operations": list(CAPABILITIES),
        "results": results,
        "checked_at": datetime.now(UTC).isoformat(),
    }
    output = json.dumps(record, indent=2) + "\n"
    if args.output:
        args.output.write_text(output)
    else:
        print(output, end="")
    return int(args.live and any("failure" in result for result in results))


if __name__ == "__main__":
    raise SystemExit(main())

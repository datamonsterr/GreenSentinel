"""Trusted canonical dispatch. Every data adapter reads an authorized source."""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import os
import time
from datetime import UTC, datetime
from typing import Any, get_args

import httpx
import psycopg
from fastapi import HTTPException
from jsonschema import ValidationError as SchemaError
from jsonschema import validate
from psycopg.rows import dict_row
from pydantic import ValidationError

from src.config import get_settings
from src.models.tool_contracts import EvidenceProvenance, ToolError, ToolExecutionContext, ToolResult
from src.services.case_context import build_case_context
from src.services.tool_catalog import get_tool_catalog

logger = logging.getLogger(__name__)

_workflow_service = None
WORKFLOWS = {
    "draft_evidence_request",
    "draft_case_minutes",
    "preview_case_minutes",
    "request_action_approval",
    "ask_interactive_question",
    "get_action_status",
}


class ToolValidationError(ValueError):
    code = "VALIDATION_ERROR"


_PUBLIC_TRAFFIC_FIELDS = {
    "fetch_corridor_historical_traffic": (
        "status",
        "reason",
        "source_type",
        "peer_count",
        "observed_speed_kmh",
        "free_flow_speed_kmh",
        "congestion_ratio",
        "congested",
        "window_start",
        "window_end",
        "method",
    ),
    "query_traffic_incident_feed": (
        "status",
        "reason",
        "congested",
        "observed_at",
        "historical_absence_proven",
        "retention",
    ),
}


def _public_tool_output(tool_id: str, data: dict[str, Any]) -> dict[str, Any] | None:
    fields = _PUBLIC_TRAFFIC_FIELDS.get(tool_id)
    if fields is None:
        return None
    output = {field: data[field] for field in fields if field in data}
    if tool_id == "query_traffic_incident_feed" and isinstance(data.get("incidents"), list):
        output["incident_count"] = len(data["incidents"])
    return output


def set_workflow_service(service):
    global _workflow_service
    _workflow_service = service


ANALYST_ROLES = frozenset({"analyst", "fraud_analyst", "senior_analyst", "admin"})
PRIVILEGED_ANALYST_ROLES = frozenset({"senior_analyst", "admin"})


def _rows(query: str, params: tuple) -> list[dict[str, Any]]:
    with psycopg.connect(get_settings().database_url, row_factory=dict_row, connect_timeout=5) as conn:
        with conn.cursor() as cur:
            cur.execute("SET LOCAL statement_timeout='5s'")
            cur.execute("SET search_path = app, extensions, public;")
            cur.execute(query, params)
            return json.loads(json.dumps(cur.fetchall(), default=str))


def _scope(ctx):
    if not ctx.organization_id or not str(ctx.organization_id).strip():
        raise HTTPException(403, "Organization scope required")
    if not ctx.case_id or str(ctx.case_id).strip() in {"", "none", "null"}:
        if "driver" in ctx.roles:
            return {
                "id": "",
                "organization_id": ctx.organization_id,
                "assignment_id": None,
                "assigned_analyst_id": None,
                "driver_id": ctx.driver_id or ctx.actor_id,
                "trip_id": None,
                "vehicle_id": None,
                "principal_id": ctx.actor_id,
                "version": 1,
                "status": "active",
            }
        raise HTTPException(404, "Case not found")
    settings = get_settings()
    test_fallback_allowed = settings.app_env == "test" and settings.test_auth_enabled

    row = None
    try:
        rows = _rows(
            """SELECT c.id,c.organization_id,c.assignment_id,c.assigned_analyst_id,a.driver_id,a.trip_id,a.vehicle_id,
                 d.principal_id,c.version,c.status FROM app.fraud_cases c JOIN app.trip_assignments a ON a.id=c.assignment_id
                 JOIN app.drivers d ON d.id=a.driver_id WHERE c.id=%s::uuid AND c.organization_id=%s::uuid""",
            (ctx.case_id, ctx.organization_id),
        )
        if rows:
            row = rows[0]
    except Exception:
        logger.exception("tool scope lookup failed for case %s", ctx.case_id)
        if not test_fallback_allowed:
            raise HTTPException(503, "Authorization database unavailable") from None

    if not row:
        if not test_fallback_allowed:
            raise HTTPException(404, "Case not found")
        # Decoupled / test fallback to case_service in-memory cases
        from src.services.case_service import get_case_service

        cs = get_case_service()
        case = cs._cases.get(ctx.case_id)
        if not case:
            raise HTTPException(404, "Case not found")
        c_driver = case.get("driver_id") or (
            case.get("driver", {}).get("id") if isinstance(case.get("driver"), dict) else None
        )
        row = {
            "id": case.get("id", ctx.case_id),
            "organization_id": case.get("organization_id", ctx.organization_id),
            "assignment_id": case.get("assignment_id"),
            "assigned_analyst_id": case.get("assigned_analyst_id"),
            "driver_id": c_driver,
            "trip_id": case.get("trip_id"),
            "vehicle_id": case.get("vehicle_id"),
            "principal_id": ctx.actor_id,
            "version": case.get("version", 1),
            "status": case.get("status", "open"),
        }

    if not ctx.roles.intersection(ANALYST_ROLES | {"driver"}):
        raise HTTPException(403, "Role cannot invoke case tools")
    if ctx.roles.intersection(ANALYST_ROLES):
        if (
            ctx.roles.intersection({"analyst", "fraud_analyst"})
            and not ctx.roles.intersection(PRIVILEGED_ANALYST_ROLES)
            and row["assigned_analyst_id"] != ctx.actor_id
        ):
            raise HTTPException(403, "Case assigned to another analyst")
    elif not row.get("driver_id") or not ctx.driver_id or row["driver_id"] != ctx.driver_id:
        raise HTTPException(404, "Case not found")
    return row


def _failed(tool, ctx, code, message, retryable=False):
    logger.warning(
        "tool_execution_failed tool_id=%s code=%s tool_call_id=%s retryable=%s",
        tool,
        code,
        ctx.tool_call_id,
        retryable,
    )
    return ToolResult(
        status="failed",
        tool_id=tool,
        tool_call_id=ctx.tool_call_id,
        error=ToolError(code=code, message=message, retryable=retryable),
        provenance=[EvidenceProvenance(kind="unavailable", source=tool, retrieved_at=datetime.now(UTC).isoformat())],
    )


async def _emit(callback, event):
    if callback:
        out = callback(event)
        if inspect.isawaitable(out):
            await out


async def execute_tool(
    tool_id: str, arguments: dict[str, Any], context: ToolExecutionContext, on_event=None
) -> ToolResult:
    entry = next((e for e in get_tool_catalog() if e.canonical_id == tool_id or tool_id in e.surface_names), None)
    if not entry:
        return _failed(tool_id, context, "VALIDATION_ERROR", "Unknown tool")
    tool_id = entry.canonical_id
    if not entry.model_selectable:
        return _failed(tool_id, context, "FORBIDDEN", "Requires explicit human command")
    actor = "analyst" if context.roles.intersection(ANALYST_ROLES) else "driver"
    if entry.actor not in {actor, "both"}:
        return _failed(tool_id, context, "FORBIDDEN", "Tool not permitted for this actor")
    if not isinstance(arguments, dict):
        return _failed(tool_id, context, "VALIDATION_ERROR", "Arguments must be an object")
    for field in {"actor_id", "organization_id", "roles", "permissions", "runtime_context"}:
        if field in arguments:
            return _failed(tool_id, context, "FORBIDDEN", "Authority cannot be model supplied")
    # Resource ownership is identity (driver_id): a model-supplied mismatch is
    # rejected outright. Resource scope (case_id) is runtime-bound by the
    # trusted chat context: a model-omitted or hallucinated/wrong case_id is
    # corrected to the authorized context case rather than erroring, so
    # driver tools (weather/traffic/trip checks) never fail a turn just
    # because the LLM forgot or mis-stated the case id (R3).
    if arguments.get("driver_id") and arguments["driver_id"] != context.driver_id:
        return _failed(tool_id, context, "FORBIDDEN", "Resource must match authorized case")
    if context.case_id and arguments.get("case_id") and arguments["case_id"] != context.case_id:
        logger.info(
            "Tool %s: model-supplied case_id %r overridden by authorized context case_id %r",
            tool_id,
            arguments["case_id"],
            context.case_id,
        )
    # LLM tool callers commonly fill unset optional JSON schema args with
    # `null` rather than omitting them; drop those before validation so an
    # omitted-vs-null optional arg never turns into a false VALIDATION_ERROR
    # (observed: driver's `list_my_cases` with model-supplied `status: null`).
    args = {k: v for k, v in arguments.items() if v is not None}
    props = entry.input_schema.get("properties", {})
    if context.case_id and "case_id" in props:
        args["case_id"] = context.case_id
    if "driver_id" in props:
        args.setdefault("driver_id", context.driver_id)
    try:
        validate(args, entry.input_schema)
        scope = await asyncio.to_thread(_scope, context)
    except SchemaError:
        return _failed(tool_id, context, "VALIDATION_ERROR", "Invalid tool arguments")
    except HTTPException as e:
        return _failed(tool_id, context, "NOT_FOUND" if e.status_code == 404 else "FORBIDDEN", e.detail)
    except Exception:
        return _failed(tool_id, context, "PERSISTENCE_UNAVAILABLE", "Cannot verify case access", True)
    started = time.monotonic()
    await _emit(on_event, {"type": "tool_start", "tool_id": tool_id, "tool_call_id": context.tool_call_id})
    try:
        for attempt in range(2 if tool_id not in WORKFLOWS else 1):
            try:
                data, provenance = await asyncio.wait_for(
                    _dispatch(tool_id, args, context, scope), entry.timeout_seconds
                )
                validate(data, entry.output_schema)
                result = ToolResult(
                    status="succeeded",
                    tool_id=tool_id,
                    tool_call_id=context.tool_call_id,
                    data=data,
                    provenance=provenance,
                )
                break
            except (HTTPException, PermissionError) as e:
                code = (
                    "FORBIDDEN"
                    if isinstance(e, PermissionError) or e.status_code == 403
                    else "NOT_FOUND"
                    if e.status_code == 404
                    else "CONFLICT"
                    if e.status_code == 409
                    else "SOURCE_UNAVAILABLE"
                )
                result = _failed(
                    tool_id, context, code, str(e.detail) if isinstance(e, HTTPException) else "Access denied"
                )
                break
            except (ValidationError, SchemaError):
                result = _failed(
                    tool_id, context, "VALIDATION_ERROR", "Source result does not match the published contract"
                )
                break
            except httpx.HTTPStatusError as e:
                transient = e.response.status_code in {429, 500, 502, 503, 504}
                result = _failed(tool_id, context, "PROVIDER_UNAVAILABLE", "Source provider unavailable", transient)
                if not transient or attempt:
                    break
                await asyncio.sleep(0.25)
            except (TimeoutError, httpx.TimeoutException, httpx.TransportError):
                result = _failed(tool_id, context, "PROVIDER_TIMEOUT", "Source timed out", True)
                if attempt or tool_id in WORKFLOWS:
                    break
                await asyncio.sleep(0.25)
            except Exception as e:
                # Domain codes are safe and stable; exception strings are never published.
                code = getattr(
                    e, "code", "PERSISTENCE_UNAVAILABLE" if isinstance(e, psycopg.Error) else "SOURCE_UNAVAILABLE"
                )
                if code not in get_args(ToolError.model_fields["code"].annotation):
                    code = "INTERNAL_ERROR"
                result = _failed(tool_id, context, code, "Operation unavailable; retain case for review", False)
                break
    except asyncio.CancelledError:
        await _emit(
            on_event,
            {
                "type": "tool_end",
                "tool_id": tool_id,
                "tool_call_id": context.tool_call_id,
                "status": "failed",
                "duration_ms": int((time.monotonic() - started) * 1000),
                "error": {"code": "INTERRUPTED", "message": "Interrupted", "retryable": True},
            },
        )
        raise
    end_event = {
        "type": "tool_end",
        "tool_id": tool_id,
        "tool_call_id": context.tool_call_id,
        "status": result.status,
        "duration_ms": int((time.monotonic() - started) * 1000),
        "error": result.error.model_dump() if result.error else None,
    }
    if result.status == "succeeded" and result.data:
        output = _public_tool_output(tool_id, result.data)
        if output is not None:
            end_event["output"] = output
    await _emit(on_event, end_event)
    return result


def _provenance(source, ids, *, kind="database", observed_at=None, citations=None):
    return [
        EvidenceProvenance(
            kind=kind,
            source=source,
            record_ids=[str(i) for i in ids if i],
            observed_at=observed_at,
            retrieved_at=datetime.now(UTC).isoformat(),
            citation_ids=citations or [],
        )
    ]


def _geoapify_key() -> str:
    return os.getenv("GEOAPIFY_API_KEY", "")


def _geoapify_provider():
    from src.services.geoapify_adapter import GeoapifyAdapter

    return GeoapifyAdapter(api_key=_geoapify_key())


def _telemetry_points_for_routes(evidence: dict[str, Any]) -> list[dict[str, Any]]:
    """Normalize observed GPS points to lon/lat/occurred_at dicts from case evidence."""
    from src.services.map_snapshot import _telemetry_points

    return _telemetry_points({}, evidence.get("telemetry_samples", []))


async def _match_summary_for_compare(ctx, s, telemetry, args) -> dict[str, Any] | None:
    """Run map matching over observed points and preserve match_type counts.

    Read-only; stored originals are never written. A provider failure degrades
    to ``None`` so route context remains advisory without fabricating match data.
    """
    from src.services.geoapify_adapter import MapMatchSuccess

    if not _geoapify_key() or len(telemetry) < 2:
        return None
    rows = await asyncio.to_thread(_match_telemetry_rows, s["assignment_id"], int(args.get("match_limit", 30)))
    if len(rows) < 2:
        return None
    waypoints = [
        {
            "location": [float(row["lon"]), float(row["lat"])],
            "timestamp": row["occurred_at"].isoformat().replace("+00:00", "Z") if row["occurred_at"] else None,
        }
        for row in rows
    ]
    result = await asyncio.to_thread(_geoapify_provider().map_match, waypoints)
    if not isinstance(result, MapMatchSuccess):
        return None
    by_index = {w.original_index: w.match_distance_m for w in result.waypoints if w.match_distance_m is not None}
    return {
        "advisory_only": True,
        "point_count": len(rows),
        "matched_count": result.count_matched,
        "unmatched_count": result.count_unmatched,
        "interpolated_count": result.count_interpolated,
        "match_distance_m_by_index": by_index,
    }


def _route_progress_metrics(telemetry: list[dict[str, Any]], route_geometry: Any) -> dict[str, Any] | None:
    """Compute progress/away metrics from observed telemetry against planned route.

    Route context is advisory; the metrics never assert driver intent.
    """
    if len(telemetry) < 2:
        return None
    try:
        from src.services.route_analytics import haversine_distance_m
    except Exception:
        return None
    points = [(float(p["lon"]), float(p["lat"])) for p in telemetry]
    cumulative = 0.0
    for i in range(len(points) - 1):
        cumulative += haversine_distance_m(points[i], points[i + 1])
    legs = _route_geometry_legs(route_geometry)
    metrics: dict[str, Any] = {
        "advisory_only": True,
        "distance_observed_m": round(cumulative, 1),
        "legs": [],
    }
    for leg in legs:
        leg_points = leg["points"]
        distance_to_legs = []
        for pt in points:
            distance_to_legs.append(min(haversine_distance_m(pt, lp) for lp in leg_points[:50]))
        metrics["legs"].append(
            {
                "leg": leg["leg"],
                "closest_distance_m": round(min(distance_to_legs), 1) if distance_to_legs else None,
            }
        )
    return metrics


def _route_geometry_legs(route_geometry: Any) -> list[dict[str, Any]]:
    if not isinstance(route_geometry, dict):
        return []
    out: list[dict[str, Any]] = []
    for leg in ("pickup_route", "destination_route"):
        entry = route_geometry.get(leg)
        if not isinstance(entry, dict):
            continue
        route = entry.get("route")
        if not isinstance(route, dict):
            continue
        coords = route.get("coordinates")
        if not isinstance(coords, list):
            continue
        lines = coords if route.get("type") == "MultiLineString" else [coords]
        flat = []
        for line in lines:
            if not isinstance(line, list):
                continue
            for vertex in line:
                if isinstance(vertex, list) and len(vertex) >= 2:
                    flat.append((float(vertex[0]), float(vertex[1])))
        out.append(
            {
                "leg": leg,
                "points": flat,
                "provider": entry.get("provider"),
                "traffic_model": entry.get("traffic_model"),
            }
        )
    return out


async def _geocode_address_tool(ctx, s, e, args) -> dict[str, Any]:
    from src.services.geoapify_adapter import GeocodeSuccess

    address = args.get("address")
    if not isinstance(address, str) or not address.strip():
        raise HTTPException(422, "Address is required")
    provider = _geoapify_provider()
    result = await asyncio.to_thread(provider.geocode, address, limit=int(args.get("limit", 5)))
    if isinstance(result, GeocodeSuccess):
        return {
            "case_id": ctx.case_id,
            "query": result.query,
            "results": result.candidates,
            "count": len(result.candidates),
            "lookup_is_not_location_proof": True,
        }
    code = _geoapify_failure_to_http(result)
    raise HTTPException(code, _geoapify_failure_message(result.code))


async def _reverse_geocode_tool(ctx, s, e, args) -> dict[str, Any]:
    from src.services.geoapify_adapter import GeocodeSuccess

    lon = args.get("longitude")
    lat = args.get("latitude")
    if (
        isinstance(lon, bool)
        or isinstance(lat, bool)
        or not isinstance(lon, (int, float))
        or not isinstance(lat, (int, float))
    ):
        raise HTTPException(422, "Valid longitude/latitude are required")
    provider = _geoapify_provider()
    result = await asyncio.to_thread(provider.reverse_geocode, float(lon), float(lat), limit=int(args.get("limit", 5)))
    if isinstance(result, GeocodeSuccess):
        return {
            "case_id": ctx.case_id,
            "query": result.query,
            "results": result.candidates,
            "count": len(result.candidates),
            "lookup_is_not_location_proof": True,
        }
    code = _geoapify_failure_to_http(result)
    raise HTTPException(code, _geoapify_failure_message(result.code))


async def _match_trip_telemetry_tool(ctx, s, e, args) -> dict[str, Any]:
    from src.services.geoapify_adapter import MapMatchSuccess

    points_rows = await asyncio.to_thread(_match_telemetry_rows, s["assignment_id"], int(args.get("limit", 30)))
    if len(points_rows) < 2:
        return {
            "case_id": ctx.case_id,
            "point_count": len(points_rows),
            "matched_count": 0,
            "unmatched_count": len(points_rows),
            "interpolated_count": 0,
            "match_distance_m_by_index": {},
            "originals_never_overwritten": True,
        }
    waypoints = [
        {
            "location": [float(row["lon"]), float(row["lat"])],
            "timestamp": row["occurred_at"].isoformat().replace("+00:00", "Z") if row["occurred_at"] else None,
        }
        for row in points_rows
    ]
    provider = _geoapify_provider()
    result = await asyncio.to_thread(provider.map_match, waypoints)
    if isinstance(result, MapMatchSuccess):
        by_index = {w.original_index: w.match_distance_m for w in result.waypoints if w.match_distance_m is not None}
        return {
            "case_id": ctx.case_id,
            "point_count": len(points_rows),
            "matched_count": result.count_matched,
            "unmatched_count": result.count_unmatched,
            "interpolated_count": result.count_interpolated,
            "match_distance_m_by_index": by_index,
            "originals_never_overwritten": True,
        }
    code = _geoapify_failure_to_http(result)
    raise HTTPException(code, _geoapify_failure_message(result.code))


def _match_telemetry_rows(assignment_id: str, limit: int) -> list[dict[str, Any]]:
    with psycopg.connect(get_settings().database_url, row_factory=dict_row, connect_timeout=5) as conn:
        with conn.cursor() as cur:
            cur.execute("SET search_path = app, extensions, public;")
            cur.execute(
                """SELECT event_id, occurred_at,
                          ST_X(position::geometry) AS lon,
                          ST_Y(position::geometry) AS lat
                   FROM app.telemetry_points
                   WHERE assignment_id=%s AND position IS NOT NULL
                   ORDER BY occurred_at LIMIT %s""",
                (assignment_id, max(2, min(int(limit), 100))),
            )
            return list(cur.fetchall())


def _geoapify_failure_to_http(result) -> int:
    code = result.code
    if code in {"timeout", "unavailable"}:
        return 503
    if code == "rate_limited":
        return 429
    if code == "unauthorized":
        return 502
    if code in {"invalid_input", "no_result"}:
        return 422
    return 502


def _geoapify_failure_message(code: str) -> str:
    messages = {
        "missing_key": "Geoapify is not configured",
        "invalid_input": "Geocode request is invalid",
        "no_result": "Provider returned no candidates",
        "timeout": "Geoapify timed out",
        "unavailable": "Geoapify is unavailable",
        "rate_limited": "Geoapify quota exceeded",
        "unauthorized": "Geoapify rejected the request",
        "forbidden": "Geoapify denied the request",
        "malformed_payload": "Geoapify returned an unexpected response",
        "no_match": "Provider returned no matched route",
    }
    return messages.get(code, "Geoapify requested resource is unavailable")


def _unavailable_revision(case_id: str, requested: str, current: str) -> dict[str, Any]:
    """Structured revision-mismatch result; never renders a blank image as evidence."""
    return {
        "code": "revision_mismatch",
        "message": (
            f"Requested evidence snapshot {requested} does not match the case's frozen "
            f"revision {current}; re-render against the current revision"
        ),
        "retry_guidance": "Request the map with the current evidence_snapshot_id",
        "retryable": False,
    }


def _traffic_timestamp(value: Any) -> str:
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
    return str(value)


async def _case_traffic_scope(assignment_id: str, args: dict[str, Any]) -> dict[str, Any]:
    rows = await asyncio.to_thread(
        _rows,
        """SELECT min(tp.occurred_at) AS window_start,
                  max(tp.occurred_at) AS window_end,
                  min(ST_X(tp.position::geometry)) AS west,
                  min(ST_Y(tp.position::geometry)) AS south,
                  max(ST_X(tp.position::geometry)) AS east,
                  max(ST_Y(tp.position::geometry)) AS north
           FROM app.telemetry_points tp
           WHERE tp.assignment_id=%s AND tp.position IS NOT NULL""",
        (assignment_id,),
    )
    row = rows[0] if rows else {}
    values = [row.get(key) for key in ("west", "south", "east", "north")]
    if row.get("window_start") is None or row.get("window_end") is None or any(value is None for value in values):
        if not all(key in args for key in ("bbox", "start_time", "end_time")):
            raise ToolValidationError("Case telemetry or a complete corridor scope is required")
        return {"bbox": args["bbox"], "start_time": args["start_time"], "end_time": args["end_time"]}

    west, south, east, north = (float(value) for value in values)
    if west == east:
        west, east = west - 0.0001, east + 0.0001
    if south == north:
        south, north = south - 0.0001, north + 0.0001
    return {
        "bbox": [west, south, east, north],
        "start_time": _traffic_timestamp(row["window_start"]),
        "end_time": _traffic_timestamp(row["window_end"]),
    }


async def _dispatch(tool, args, ctx, s):
    if tool in WORKFLOWS:
        from src.services.agent_workflow_service import get_agent_workflow_service

        service = _workflow_service or get_agent_workflow_service()
        data = await service.invoke(tool, args, ctx.model_dump(mode="json"))
        return json.loads(json.dumps(data, default=str)), _provenance(
            "app.workflow",
            [
                data.get("question_id")
                or data.get("minutes_id")
                or data.get("record_id")
                or data.get("action_request_id")
                or data.get("draft_id")
            ],
        )
    if tool == "list_cases":
        rows = await asyncio.to_thread(
            _rows,
            "SELECT id,status,suspected_category,priority_score,version FROM app.fraud_cases WHERE organization_id=%s AND assigned_analyst_id=%s ORDER BY priority_score DESC LIMIT %s",
            (ctx.organization_id, ctx.actor_id, args.get("limit", 20)),
        )
        return {"cases": rows, "count": len(rows)}, _provenance("app.fraud_cases", [r["id"] for r in rows])
    if tool == "get_case_context":
        data = await build_case_context(ctx)
        return data, _provenance("app.evidence_snapshots", [data["evidence_snapshot"]["id"]])
    if tool == "inspect_trip_telemetry":
        from src.services.context_budget import bounded_evidence

        rows = await asyncio.to_thread(
            _rows,
            """SELECT event_id,occurred_at,speed_mps,accuracy_m,gps_state,network_state,app_state,
                      mock_location_reported,ST_AsGeoJSON(position)::jsonb AS position,
                      count(*) OVER() AS _total_samples,
                      min(speed_mps) OVER() AS _min_speed_mps,
                      max(speed_mps) OVER() AS _max_speed_mps,
                      count(*) FILTER (WHERE mock_location_reported IS TRUE) OVER() AS _mock_count,
                      min(occurred_at) OVER() AS _window_start,
                      max(occurred_at) OVER() AS _window_end
               FROM app.telemetry_points WHERE assignment_id=%s
               ORDER BY occurred_at,event_id LIMIT 2000""",
            (s["assignment_id"],),
        )
        measured = rows[0] if rows else {}
        total = int(measured.get("_total_samples", 0))
        summary = {
            "point_count": total,
            "min_speed_mps": measured.get("_min_speed_mps"),
            "max_speed_mps": measured.get("_max_speed_mps"),
            "mock_location_reported_count": measured.get("_mock_count", 0),
            "window_start": measured.get("_window_start"),
            "window_end": measured.get("_window_end"),
        }
        points = [{key: value for key, value in row.items() if not key.startswith("_")} for row in rows]
        data = bounded_evidence(ctx.case_id, "points", points, summary, total_samples=total)
        return data, _provenance(
            "app.telemetry_points",
            [r["event_id"] for r in data["points"]],
            observed_at=rows[0]["occurred_at"] if rows else None,
        )
    if tool == "get_trip_lifecycle_evidence":
        from src.services.context_budget import bounded_evidence

        rows = await asyncio.to_thread(
            _rows,
            "SELECT id,event_type,actor_type,occurred_at,payload,count(*) OVER() AS _total_samples FROM app.trip_events WHERE assignment_id=%s ORDER BY occurred_at,id LIMIT 2000",
            (s["assignment_id"],),
        )
        total = int(rows[0]["_total_samples"]) if rows else 0
        events = [{key: value for key, value in row.items() if key != "_total_samples"} for row in rows]
        data = bounded_evidence(ctx.case_id, "events", events, {"event_count": total}, total_samples=total)
        return data, _provenance("app.trip_events", [r["id"] for r in data["events"]])
    if tool == "get_driver_history":
        rows = await asyncio.to_thread(
            _rows,
            "SELECT d.id,d.account_status,d.partner_type,count(a.id)::int AS assignments,count(a.id) FILTER(WHERE a.state='completed')::int AS completed FROM app.drivers d LEFT JOIN app.trip_assignments a ON a.driver_id=d.id WHERE d.id=%s GROUP BY d.id",
            (s["driver_id"],),
        )
        return {"case_id": ctx.case_id, "driver": rows[0]}, _provenance(
            "app.drivers/app.trip_assignments", [s["driver_id"]]
        )
    if tool == "check_related_cases_to_vehicle":
        rows = await asyncio.to_thread(
            _rows,
            "SELECT c.id,c.status,c.suspected_category,c.version FROM app.fraud_cases c JOIN app.trip_assignments a ON a.id=c.assignment_id WHERE a.vehicle_id=%s AND c.organization_id=%s AND c.id<>%s ORDER BY c.created_at DESC LIMIT 30",
            (s["vehicle_id"], ctx.organization_id, ctx.case_id),
        )
        return {"case_id": ctx.case_id, "cases": rows}, _provenance(
            "app.fraud_cases/app.trip_assignments", [r["id"] for r in rows]
        )
    if tool == "fetch_corridor_historical_traffic":
        from src.services import traffic_evidence_service

        traffic_scope = await _case_traffic_scope(s["assignment_id"], args)
        west, south, east, north = traffic_scope["bbox"]
        peers = await asyncio.to_thread(
            _rows,
            """SELECT tp.assignment_id::text,
                      percentile_cont(0.5) WITHIN GROUP (ORDER BY tp.speed_mps) * 3.6 AS median_speed_kmh
               FROM app.telemetry_points tp
               JOIN app.trip_assignments a ON a.id=tp.assignment_id
               JOIN app.trips t ON t.id=a.trip_id
               WHERE t.organization_id=%s::uuid
                 AND tp.assignment_id<>%s::uuid
                 AND tp.occurred_at BETWEEN %s::timestamptz AND %s::timestamptz
                 AND tp.position IS NOT NULL
                 AND ST_Intersects(tp.position, ST_MakeEnvelope(%s,%s,%s,%s,4326)::geography)
                 AND tp.speed_mps IS NOT NULL
                 AND tp.gps_state='valid'
                 AND COALESCE(tp.mock_location_reported,false)=false
                 AND (tp.accuracy_m IS NULL OR tp.accuracy_m<=100)
               GROUP BY tp.assignment_id
               ORDER BY tp.assignment_id
               LIMIT 200""",
            (
                ctx.organization_id,
                s["assignment_id"],
                traffic_scope["start_time"],
                traffic_scope["end_time"],
                west,
                south,
                east,
                north,
            ),
        )
        data = await traffic_evidence_service.fetch_corridor_historical_traffic(
            bbox=traffic_scope["bbox"],
            start_time=traffic_scope["start_time"],
            end_time=traffic_scope["end_time"],
            peer_trip_speeds_kmh=[row["median_speed_kmh"] for row in peers],
        )
        kind = "unavailable" if data.get("status") != "available" else "database"
        return data, _provenance(
            "app.telemetry_points",
            [row["assignment_id"] for row in peers],
            kind=kind,
            observed_at=traffic_scope["end_time"],
        )
    if tool == "query_traffic_incident_feed":
        from src.services import traffic_evidence_service

        traffic_scope = await _case_traffic_scope(s["assignment_id"], args)
        data = await traffic_evidence_service.query_traffic_incident_feed(
            bbox=traffic_scope["bbox"],
            start_time=traffic_scope["start_time"],
            end_time=traffic_scope["end_time"],
        )
        kind = "unavailable" if data.get("status") != "available" else "provider"
        return data, _provenance(
            "external_traffic_provider_memory_only", [], kind=kind, observed_at=data.get("observed_at")
        )
    if tool == "check_traffic_situation":
        if "driver" in ctx.roles or args.get("trip_id"):
            from src.agents.tools.driver_tools import check_traffic_situation as _t_traffic

            data = await _t_traffic.ainvoke(
                {
                    "case_id": args.get("case_id") or ctx.case_id,
                    "trip_id": args.get("trip_id"),
                    "driver_id": ctx.driver_id or ctx.actor_id,
                    "organization_id": ctx.organization_id,
                    "start_lat": args.get("start_lat") or args.get("latitude"),
                    "start_lon": args.get("start_lon") or args.get("longitude"),
                    "end_lat": args.get("end_lat"),
                    "end_lon": args.get("end_lon"),
                }
            )
            if data.get("error_type") == "FORBIDDEN":
                raise HTTPException(403, data.get("error"))
            if data.get("error_type") == "NOT_FOUND":
                raise HTTPException(404, data.get("error"))
            return data, _provenance("OSRM", [args.get("case_id") or ctx.case_id or "traffic"], kind="provider")

        rows = await asyncio.to_thread(
            _rows,
            "SELECT id,observed_at,valid_until,average_speed_mps,congestion_level,source,is_simulated,provenance FROM app.traffic_observations WHERE assignment_id=%s ORDER BY observed_at",
            (s["assignment_id"],),
        )
        if not rows:
            raise HTTPException(503, "No traffic observation is recorded; route geometry is not traffic evidence")
        return {"case_id": ctx.case_id, "observations": rows}, _provenance(
            "app.traffic_observations",
            [r["id"] for r in rows],
            kind="dataset" if all(r["is_simulated"] for r in rows) else "database",
            observed_at=rows[0]["observed_at"],
        )
    if tool == "search_policy_documents":
        if "driver" in ctx.roles:
            # Driver policy FAQ ("Dieu 12.2 quy dinh gi ve ket xe?") is a
            # general-regulation lookup over the static driver guideline set,
            # not the analyst's case-scoped evidence-snapshot policy version.
            # It must work with or without a bound case (Issue: PR #603
            # Railway preview — the analyst-only `build_case_context(ctx)`
            # path below requires a real case_id and raised for a caseless
            # driver, surfacing as "Tool execution failed").
            from src.agents.tools.driver_tools import query_driver_policy as _t_policy

            raw = await _t_policy.ainvoke({"query": args["query"]})
            if raw.get("error"):
                raise HTTPException(503, raw["error"])
            policies = raw.get("relevant_policies") or []
            citations = [
                {
                    "doc_id": p.get("article"),
                    "document_title": p.get("title"),
                    "snippet": p.get("snippet"),
                    "source_ref": p.get("article"),
                    "section_ref": p.get("title"),
                }
                for p in policies
            ]
            data = {**raw, "results": citations, "citations": citations}
            return data, _provenance("driver_policy_guidelines", [p.get("article") for p in policies], kind="dataset")
        # Policy search is case-scoped. The frozen evidence snapshot is the
        # trusted seam that binds a case to one published policy version.
        case_context = await build_case_context(ctx)
        snapshot = case_context.get("evidence_snapshot") or {}
        policy_version_id = snapshot.get("policy_version_id")
        if not policy_version_id:
            return {
                "case_id": ctx.case_id,
                "query": args["query"],
                "results": [],
                "citations": [],
                "status": "uncertain",
                "abstention": "No policy version is recorded for this case.",
            }, _provenance("app.evidence_snapshots", [snapshot.get("id")])
        rows = await asyncio.to_thread(
            _rows,
            "SELECT pc.id,pc.policy_version_id,pc.source_ref,pc.section_ref,pc.content,pv.version,pv.effective_from,pv.effective_to,pv.is_demo_policy FROM app.policy_chunks pc JOIN app.policy_versions pv ON pv.id=pc.policy_version_id WHERE pc.policy_version_id=%s::uuid AND pv.id=%s::uuid AND pv.status='published' AND pc.content ILIKE %s ESCAPE '\\' ORDER BY pc.id LIMIT 5",
            (
                policy_version_id,
                policy_version_id,
                "%" + args["query"].replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%",
            ),
        )
        citations = [
            {
                "doc_id": r["id"],
                "document_title": r["source_ref"],
                "snippet": r["content"],
                "source_ref": r["source_ref"],
                "section_ref": r["section_ref"],
                "policy_version_id": str(r["policy_version_id"]),
                "policy_version": r["version"],
                "is_demo_policy": r["is_demo_policy"],
            }
            for r in rows
        ]
        status = "succeeded" if citations else "uncertain"
        data = {
            "case_id": ctx.case_id,
            "query": args["query"],
            "results": citations,
            "citations": citations,
            "status": status,
            "abstention": "" if citations else "No matching clause exists in the case policy version.",
        }
        return data, _provenance("app.policy_chunks", [r["id"] for r in rows], citations=[r["id"] for r in rows])
    if tool == "check_weather_condition":
        if "driver" in ctx.roles or args.get("trip_id"):
            from src.agents.tools.driver_tools import check_weather_condition as _t_weather

            data = await _t_weather.ainvoke(
                {
                    "case_id": args.get("case_id") or ctx.case_id,
                    "trip_id": args.get("trip_id"),
                    "driver_id": ctx.driver_id or ctx.actor_id,
                    "organization_id": ctx.organization_id,
                    "lat": args.get("latitude") or args.get("lat"),
                    "lon": args.get("longitude") or args.get("lon"),
                }
            )
            if data.get("error_type") == "FORBIDDEN":
                raise HTTPException(403, data.get("error"))
            if data.get("error_type") == "NOT_FOUND":
                raise HTTPException(404, data.get("error"))
            return data, _provenance("Open-Meteo", [args.get("case_id") or ctx.case_id or "weather"], kind="provider")

        rows = await asyncio.to_thread(
            _rows,
            "SELECT occurred_at,ST_X(position::geometry) AS lon,ST_Y(position::geometry) AS lat FROM app.telemetry_points WHERE assignment_id=%s ORDER BY occurred_at LIMIT 1",
            (s["assignment_id"],),
        )
        if not rows:
            raise HTTPException(503, "Trip location/time unavailable")
        point = rows[0]
        date = point["occurred_at"][:10]
        # Historical conditions, rather than current forecast presented as incident evidence.
        async with httpx.AsyncClient(timeout=8) as client:
            response = await client.get(
                "https://archive-api.open-meteo.com/v1/archive",
                params={
                    "latitude": point["lat"],
                    "longitude": point["lon"],
                    "start_date": date,
                    "end_date": date,
                    "hourly": "temperature_2m,precipitation,wind_speed_10m",
                    "timezone": "UTC",
                },
            )
            response.raise_for_status()
            raw = response.json()
        if not raw.get("hourly") or not raw.get("hourly_units"):
            raise HTTPException(503, "Historical weather unavailable")
        return {
            "case_id": ctx.case_id,
            "observation_date": date,
            "hourly": raw["hourly"],
            "units": raw["hourly_units"],
            "source_type": "historical_reanalysis",
        }, _provenance("Open-Meteo historical archive", [str(response.url)], kind="provider", observed_at=date)
    if tool in {
        "compare_trip_routes",
        "check_system_error_guardrail",
        "get_case_map_snapshot",
        "verify_exoneration_rules",
        "geocode_address",
        "reverse_geocode_coordinates",
        "match_trip_telemetry",
    }:
        data = await build_case_context(ctx)
        e = data["evidence"]
        if tool == "compare_trip_routes":
            from src.services.map_snapshot import _decode_route, _flatten_points

            telemetry = _telemetry_points_for_routes(e)
            planned = _decode_route(e.get("route_geometry"))
            planned_segments = [
                {
                    "leg": leg,
                    "geometry_type": geometry.get("type"),
                    "vertex_count": len(_flatten_points(geometry)),
                    "provider": e.get("route_geometry", {}).get(leg, {}).get("provider"),
                    "traffic_model": e.get("route_geometry", {}).get(leg, {}).get("traffic_model"),
                }
                for leg, geometry in planned
            ]
            progress = _route_progress_metrics(telemetry, e.get("route_geometry"))
            match_summary = await _match_summary_for_compare(ctx, s, telemetry, args)
            out = {
                "case_id": ctx.case_id,
                "route_geometry": e.get("route_geometry"),
                "planned_segments": planned_segments,
                "observed": telemetry,
                "progress_metrics": progress,
                "missingness": e.get("missingness_alerts", []),
                "match_summary": match_summary,
            }
        elif tool == "geocode_address":
            out = await _geocode_address_tool(ctx, s, e, args)
        elif tool == "reverse_geocode_coordinates":
            out = await _reverse_geocode_tool(ctx, s, e, args)
        elif tool == "match_trip_telemetry":
            out = await _match_trip_telemetry_tool(ctx, s, e, args)
        elif tool == "check_system_error_guardrail":
            out = {
                "case_id": ctx.case_id,
                "guardrails": e.get("guardrails"),
                "missingness": e.get("missingness_alerts", []),
            }
        elif tool == "verify_exoneration_rules":
            out = {
                "case_id": ctx.case_id,
                "advisory_only": True,
                "action": "REQUIRES_ANALYST_REVIEW",
                "guardrails": e.get("guardrails"),
            }
        else:
            from src.services.map_snapshot import build_map_snapshot

            snapshot = data["evidence_snapshot"]
            requested = args.get("evidence_snapshot_id") or args.get("evidence_snapshot_version")
            if requested and str(snapshot.get("id") or "") != str(requested):
                err = _unavailable_revision(ctx.case_id, str(requested), str(snapshot.get("id") or ""))
                out = {
                    "case_id": ctx.case_id,
                    "evidence_snapshot_id": str(snapshot.get("id") or ""),
                    "snapshot_version": snapshot.get("version") or 0,
                    "snapshot_hash": "",
                    "route_refs": [],
                    "checkpoint_times": [],
                    "gap_windows": [],
                    "traveled_path": [],
                    "planned_routes": [],
                    "provider": "geoapify",
                    "style": "osm-bright",
                    "rendered_at": "",
                    "image_ref": None,
                    "attribution": "© OpenStreetMap contributors (ODbL), © Geoapify",
                    "cost_credits": 0,
                    "unavailable": err,
                    "deterministic_key": "",
                }
            else:
                rendered = build_map_snapshot(
                    case_id=ctx.case_id,
                    evidence_snapshot=snapshot,
                    route_refs=[],
                    telemetry_samples=e.get("telemetry_samples", []),
                    milestones=e.get("timeline_milestones", []),
                    planned_routes_geometry=e.get("route_geometry"),
                    api_key=_geoapify_key(),
                )
                out = {
                    "case_id": ctx.case_id,
                    "evidence_snapshot_id": rendered["evidence_snapshot_id"],
                    "snapshot_version": rendered["snapshot_version"],
                    "snapshot_hash": rendered["snapshot_hash"],
                    "route_refs": rendered["route_refs"],
                    "checkpoint_times": rendered["checkpoint_times"],
                    "gap_windows": rendered["gap_windows"],
                    "traveled_path": rendered["traveled_path"],
                    "planned_routes": rendered["planned_routes"],
                    "provider": rendered["provider"],
                    "style": rendered["style"],
                    "rendered_at": rendered["rendered_at"],
                    "image_ref": rendered["image_ref"] if not rendered["unavailable"] else None,
                    "attribution": rendered["attribution"],
                    "cost_credits": rendered["cost_credits"],
                    "unavailable": rendered["unavailable"],
                    "deterministic_key": rendered["deterministic_key"],
                }
        if tool in {"geocode_address", "reverse_geocode_coordinates", "match_trip_telemetry"}:
            return out, _provenance("geoapify", [], kind="provider")
        return out, _provenance("app.evidence_snapshots/app.telemetry_points", [data["evidence_snapshot"]["id"]])
    if tool == "get_dispute_dossier":
        rows = await asyncio.to_thread(
            _rows,
            "SELECT id,status,statement,received_at,provenance FROM app.driver_submissions WHERE case_id=%s ORDER BY received_at",
            (ctx.case_id,),
        )
        return {"case_id": ctx.case_id, "statements": rows}, _provenance(
            "app.driver_submissions", [r["id"] for r in rows]
        )
    if tool == "search_case_precedents":
        rows = await asyncio.to_thread(
            _rows,
            "SELECT a.id,a.case_id,a.outcome,a.rationale,a.policy_version_id,a.approved_at FROM app.adjudications a JOIN app.fraud_cases c ON c.id=a.case_id WHERE c.organization_id=%s AND c.id<>%s ORDER BY approved_at DESC LIMIT 10",
            (ctx.organization_id, ctx.case_id),
        )
        return {"case_id": ctx.case_id, "precedents": rows, "role": "historical_decisions_only"}, _provenance(
            "app.adjudications", [r["id"] for r in rows]
        )
    if tool == "list_my_cases":
        from src.agents.tools.driver_tools import list_my_cases as _t_list_cases

        data = await _t_list_cases.ainvoke(
            {
                "driver_id": ctx.driver_id or ctx.actor_id,
                "organization_id": ctx.organization_id,
                "status": args.get("status"),
            }
        )
        if data.get("error_type") == "FORBIDDEN":
            raise HTTPException(403, data.get("error"))
        if data.get("error_type") == "NOT_FOUND":
            raise HTTPException(404, data.get("error"))
        return data, _provenance("app.fraud_cases", [ctx.driver_id or ctx.actor_id], kind="database")
    if tool == "get_case_timeline":
        from src.agents.tools.driver_tools import get_case_timeline as _t_case_timeline

        data = await _t_case_timeline.ainvoke(
            {
                "case_id": args.get("case_id") or ctx.case_id,
                "driver_id": ctx.driver_id or ctx.actor_id,
                "organization_id": ctx.organization_id,
            }
        )
        if data.get("error_type") == "FORBIDDEN":
            raise HTTPException(403, data.get("error"))
        if data.get("error_type") == "NOT_FOUND":
            raise HTTPException(404, data.get("error"))
        return data, _provenance("app.case_timeline", [args.get("case_id") or ctx.case_id], kind="database")
    if tool == "explain_case_status":
        from src.agents.tools.driver_tools import explain_case_status as _t_explain_status

        data = await _t_explain_status.ainvoke(
            {
                "case_id": args.get("case_id") or ctx.case_id,
                "driver_id": ctx.driver_id or ctx.actor_id,
                "organization_id": ctx.organization_id,
                "locale": args.get("locale", "vi"),
            }
        )
        if data.get("error_type") == "FORBIDDEN":
            raise HTTPException(403, data.get("error"))
        if data.get("error_type") == "NOT_FOUND":
            raise HTTPException(404, data.get("error"))
        return data, _provenance("app.fraud_cases", [args.get("case_id") or ctx.case_id], kind="database")
    if tool == "get_my_scorecard":
        from src.agents.tools.driver_tools import get_my_scorecard as _t_scorecard

        data = await _t_scorecard.ainvoke(
            {
                "driver_id": ctx.driver_id or ctx.actor_id,
                "organization_id": ctx.organization_id,
            }
        )
        if data.get("error_type") == "FORBIDDEN":
            raise HTTPException(403, data.get("error"))
        if data.get("error_type") == "NOT_FOUND":
            raise HTTPException(404, data.get("error"))
        return data, _provenance("app.driver_scorecard", [ctx.driver_id or ctx.actor_id], kind="database")
    if tool == "list_my_trips":
        from src.agents.tools.driver_tools import list_my_trips as _t_list_trips

        data = await _t_list_trips.ainvoke(
            {
                "driver_id": ctx.driver_id or ctx.actor_id,
                "organization_id": ctx.organization_id,
                "cursor": args.get("cursor"),
                "limit": args.get("limit", 20),
                "status": args.get("status"),
            }
        )
        if data.get("error_type") == "FORBIDDEN":
            raise HTTPException(403, data.get("error"))
        if data.get("error_type") == "NOT_FOUND":
            raise HTTPException(404, data.get("error"))
        return data, _provenance("app.driver_trips", [ctx.driver_id or ctx.actor_id], kind="database")
    if tool == "get_trip_summary":
        from src.agents.tools.driver_tools import get_trip_summary as _t_trip_summary

        data = await _t_trip_summary.ainvoke(
            {
                "trip_id": args.get("trip_id"),
                "driver_id": ctx.driver_id or ctx.actor_id,
                "organization_id": ctx.organization_id,
            }
        )
        if data.get("error_type") == "FORBIDDEN":
            raise HTTPException(403, data.get("error"))
        if data.get("error_type") == "NOT_FOUND":
            raise HTTPException(404, data.get("error"))
        return data, _provenance("app.driver_trips", [args.get("trip_id")], kind="database")
    if tool == "get_forensic_brief":
        from src.agents.tools.driver_tools import get_forensic_brief as _t_brief

        data = await _t_brief.ainvoke(
            {
                "case_id": args.get("case_id") or ctx.case_id,
                "driver_id": ctx.driver_id or ctx.actor_id,
                "organization_id": ctx.organization_id,
            }
        )
        if data.get("error_type") == "FORBIDDEN":
            raise HTTPException(403, data.get("error"))
        if data.get("error_type") == "NOT_FOUND":
            raise HTTPException(404, data.get("error"))
        return data, _provenance("app.forensic_brief", [args.get("case_id") or ctx.case_id], kind="database")
    if tool == "suggest_dispute_path":
        from src.agents.tools.driver_tools import suggest_dispute_path as _t_suggest

        data = await _t_suggest.ainvoke(
            {
                "case_id": args.get("case_id") or ctx.case_id,
                "driver_id": ctx.driver_id or ctx.actor_id,
                "organization_id": ctx.organization_id,
            }
        )
        if data.get("error_type") == "FORBIDDEN":
            raise HTTPException(403, data.get("error"))
        if data.get("error_type") == "NOT_FOUND":
            raise HTTPException(404, data.get("error"))
        return data, _provenance("app.dispute_path", [args.get("case_id") or ctx.case_id], kind="database")
    if tool == "assess_statement_completeness":
        from src.agents.tools.driver_tools import assess_statement_completeness as _t_assess

        data = await _t_assess.ainvoke(
            {
                "incident_type": args.get("incident_type"),
                "description": args.get("description"),
                "corroborations": args.get("corroborations"),
                "no_evidence_declared": bool(args.get("no_evidence_declared")),
            }
        )
        return data, _provenance("checklist", ["driver_statement"], kind="dataset")
    if tool == "get_appeal_options":
        from src.agents.tools.driver_tools import get_appeal_options as _t_appeal

        data = await _t_appeal.ainvoke(
            {
                "case_id": args.get("case_id") or ctx.case_id,
                "driver_id": ctx.driver_id or ctx.actor_id,
                "organization_id": ctx.organization_id,
            }
        )
        if data.get("error_type") == "FORBIDDEN":
            raise HTTPException(403, data.get("error"))
        if data.get("error_type") == "NOT_FOUND":
            raise HTTPException(404, data.get("error"))
        return data, _provenance("app.appeal_options", [args.get("case_id") or ctx.case_id], kind="database")
    raise HTTPException(503, "No adapter for this catalog operation")

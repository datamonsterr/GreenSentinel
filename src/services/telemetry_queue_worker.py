"""Telemetry Queue Worker and Jev Fraud Assessment Agent.

Listens to Redis stream (telemetry:stream) and pubsub channel (telemetry:events).
Upon receiving trip telemetry, invokes the Jev assessment agent (OpenRouter / ChatOpenAI
or rule-based kinematic extractor with realistic confidence scores, e.g. 0.92, 0.94),
classifying P0/P1/P2 and fraud code (ERR-01 to ERR-05).
Writes the trip, telemetry points, assessment, and fraud case to PostgreSQL
(app.trips, app.telemetry_points, app.fraud_cases, app.model_assessments)
and syncs CaseService in-memory state.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import math
import os
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import redis
from fastapi import HTTPException

from src.config import Settings, get_settings
from src.services.case_service import CaseService, get_case_service
from src.services.feature_engineering import compute_feature_window
from src.services.guardrails import (
    build_guardrail_assessment,
    cap_priority_for_guardrail,
    evaluate_telemetry_window,
    should_short_circuit,
)
from src.services.jev_assessment_service import JevAssessmentService
from src.services.model_input_projection import project_model_input
from src.services.route_analytics import (
    build_trip_timeline_milestones,
    corroborate_traffic_claim,
    detect_telemetry_missingness,
    format_maneuvers_for_llm,
    parse_trajectory_maneuvers,
)
from src.services.routing_service import fetch_osrm_route
from src.services.telemetry_queue import ReliableTelemetryQueue

logger = logging.getLogger(__name__)

DEFAULT_ORG_ID = "018f2f4e-0000-7000-8000-000000000001"
DEFAULT_PASSENGER_ID = "018f2f4e-2000-7000-8000-000000000001"
DEFAULT_VEHICLE_ID = "018f2f4e-4000-7000-8000-000000000001"
DEFAULT_POLICY_ID = "018f2f4e-6000-7000-8000-000000000001"

# S4-TENANT #294 P1b: DEFAULT_ORG_ID is a simulation-tenant fixture. Writes
# carrying it must never run unguarded in production, where they would
# commingle tenants. Allowed only on the /test/* stack
# (APP_ENV=test with test_auth_enabled) or with explicit opt-in
# SIMULATION_TENANT_ALLOW=1 for controlled simulation runs.
SIMULATION_TENANT_ALLOW_ENV = "SIMULATION_TENANT_ALLOW"


def _simulation_tenant_writes_allowed(settings: Settings | None = None) -> bool:
    app_env = (settings.app_env if settings else os.getenv("APP_ENV", "")).strip()
    test_auth = bool(getattr(settings, "test_auth_enabled", False)) if settings else False
    if app_env == "test" and (test_auth or os.getenv("TEST_AUTH_ENABLED", "").strip().lower() in ("1", "true")):
        return True
    return os.getenv(SIMULATION_TENANT_ALLOW_ENV, "").strip().lower() in ("1", "true", "yes", "on")


def _require_simulation_tenant_writes(settings: Settings | None = None) -> None:
    """Fail closed before any DEFAULT_ORG_ID write outside sim/test scope."""
    if _simulation_tenant_writes_allowed(settings):
        return
    raise HTTPException(
        status_code=403,
        detail="Default-org telemetry writes require sim/test tenant scope "
        "(APP_ENV=test with test_auth_enabled, or SIMULATION_TENANT_ALLOW=1)",
    )


def _coordinate_pair(value: Any) -> list[float] | None:
    if isinstance(value, dict):
        value = value.get("coordinates")
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        return None
    try:
        longitude, latitude = float(value[0]), float(value[1])
    except (TypeError, ValueError):
        return None
    if not math.isfinite(longitude) or not math.isfinite(latitude):
        return None
    if not -180 <= longitude <= 180 or not -90 <= latitude <= 90:
        return None
    return [longitude, latitude]


def _telemetry_coordinate(point: dict[str, Any]) -> list[float] | None:
    longitude, latitude = point.get("longitude"), point.get("latitude")
    if longitude is None or latitude is None:
        position = point.get("position")
        return _coordinate_pair(position) if isinstance(position, dict) else None
    return _coordinate_pair([longitude, latitude])


def _guardrail_enabled() -> bool:
    return os.getenv("TELEMETRY_GUARDRAIL_ENABLED", "true").strip().lower() not in ("0", "false", "no", "off")


def haversine_m(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    """Calculate great-circle distance in meters between two coordinates."""
    r = 6371000.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2.0) ** 2
    return 2.0 * r * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))


def _persist_nominal_event(
    conn: Any,
    *,
    trip_id: str,
    assignment_id: str,
    driver_id: str,
    points: list[dict[str, Any]],
    event_data: dict[str, Any],
    now: datetime,
    organization_id: str | None = None,
) -> None:
    """Persist operational telemetry for a nominal trip without creating a case."""
    if organization_id is None:
        _require_simulation_tenant_writes(get_settings())
    target_org_id = organization_id or DEFAULT_ORG_ID
    passenger_id = event_data["passenger_id"] if organization_id else DEFAULT_PASSENGER_ID
    vehicle_id = event_data["vehicle_id"] if organization_id else DEFAULT_VEHICLE_ID
    pickup = _coordinate_pair(event_data.get("pickup"))
    dropoff = _coordinate_pair(event_data.get("dropoff"))
    points = [point for point in points if _telemetry_coordinate(point)]
    if not pickup or not dropoff or not points:
        return
    pickup_address = event_data.get("pickup_address")
    dropoff_address = event_data.get("dropoff_address")
    with conn.cursor() as cur:
        cur.execute("SET search_path = app, extensions, public;")
        cur.execute(
            """INSERT INTO app.trips
            (id, organization_id, passenger_id, requested_at, pickup, dropoff,
             requested_service_class, status, completed_at, created_at,
             pickup_address, dropoff_address)
            VALUES (%s,%s,%s,%s,st_setsrid(st_makepoint(%s,%s),4326)::geography,
                    st_setsrid(st_makepoint(%s,%s),4326)::geography,
                    'car_standard','completed',%s,%s,%s,%s)
            ON CONFLICT (id) DO UPDATE SET
                pickup_address = COALESCE(EXCLUDED.pickup_address, app.trips.pickup_address),
                dropoff_address = COALESCE(EXCLUDED.dropoff_address, app.trips.dropoff_address);""",
            (
                trip_id,
                target_org_id,
                passenger_id,
                now,
                pickup[0],
                pickup[1],
                dropoff[0],
                dropoff[1],
                now,
                now,
                pickup_address,
                dropoff_address,
            ),
        )
        cur.execute(
            """INSERT INTO app.trip_assignments
            (id, trip_id, driver_id, vehicle_id, state, offered_at, accepted_at, started_at, ended_at, created_at)
            VALUES (%s,%s,%s,%s,'completed',%s,%s,%s,%s,%s) ON CONFLICT (id) DO NOTHING;""",
            (assignment_id, trip_id, driver_id, vehicle_id, now, now, now, now, now),
        )
        for idx, pt in enumerate(points):
            occurred = pt.get("occurred_at") or now
            event_id = str(uuid4() if organization_id else pt.get("event_id") or uuid4())
            coordinate = _telemetry_coordinate(pt)
            if coordinate is None:
                continue
            lon, lat = coordinate
            cur.execute(
                """INSERT INTO app.ingest_events
                (event_id, organization_id, schema_version, event_type, source, occurred_at,
                 correlation_id, trip_id, assignment_id, driver_id, producer_sequence, payload, payload_hash)
                VALUES (%s,%s,1,'telemetry.frame','driver_app',%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT DO NOTHING;""",
                (
                    event_id,
                    target_org_id,
                    occurred,
                    str(uuid4()),
                    trip_id,
                    assignment_id,
                    driver_id,
                    idx,
                    json.dumps(pt),
                    hashlib.sha256(json.dumps(pt).encode()).digest(),
                ),
            )
            cur.execute(
                """INSERT INTO app.telemetry_points
                (event_id, assignment_id, occurred_at, position, speed_mps, bearing_deg, accuracy_m,
                 app_state, network_state, gps_state, mock_location_reported)
                VALUES (%s,%s,%s,st_setsrid(st_makepoint(%s,%s),4326)::geography,
                        %s,%s,%s,%s,%s,%s,%s) ON CONFLICT (event_id) DO NOTHING;""",
                (
                    event_id,
                    assignment_id,
                    occurred,
                    lon,
                    lat,
                    float(pt.get("speed_mps", 0)),
                    float(pt.get("bearing_deg", 0)),
                    pt.get("accuracy_m"),
                    pt.get("app_state", "foreground"),
                    pt.get("network_state", "online"),
                    pt.get("gps_state", "valid"),
                    bool(pt.get("mock_location_reported", False)),
                ),
            )
        if not points or not pickup or not dropoff:
            return
        first_coordinate = _telemetry_coordinate(points[0])
        if first_coordinate is None:
            return
        pickup_route = fetch_osrm_route(first_coordinate, [float(pickup[0]), float(pickup[1])])
        destination_route = fetch_osrm_route(
            [float(pickup[0]), float(pickup[1])], [float(dropoff[0]), float(dropoff[1])]
        )
        if not pickup_route or not destination_route:
            return
        pickup_line = {
            "type": "LineString",
            "coordinates": pickup_route["geometry"]["coordinates"],
        }
        dest_line = {
            "type": "LineString",
            "coordinates": destination_route["geometry"]["coordinates"],
        }
        cur.execute(
            """INSERT INTO app.route_snapshots
            (id, assignment_id, calculated_at, provider, routing_profile, map_version, route, distance_m, duration_s, leg, provenance)
            VALUES (%s, %s, %s, 'osrm', 'car', 'v2026.09',
                    st_setsrid(st_geomfromgeojson(%s), 4326)::geography,
                    %s, %s, 'pickup', %s) ON CONFLICT (assignment_id, leg) DO NOTHING;""",
            (
                str(uuid4()),
                assignment_id,
                now,
                json.dumps(pickup_line),
                pickup_route["distance_m"],
                pickup_route["duration_s"],
                json.dumps(pickup_route["provenance"]),
            ),
        )
        cur.execute(
            """INSERT INTO app.route_snapshots
            (id, assignment_id, calculated_at, provider, routing_profile, map_version, route, distance_m, duration_s, leg, provenance)
            VALUES (%s, %s, %s, 'osrm', 'car', 'v2026.09',
                    st_setsrid(st_geomfromgeojson(%s), 4326)::geography,
                    %s, %s, 'destination', %s) ON CONFLICT (assignment_id, leg) DO NOTHING;""",
            (
                str(uuid4()),
                assignment_id,
                now,
                json.dumps(dest_line),
                destination_route["distance_m"],
                destination_route["duration_s"],
                json.dumps(destination_route["provenance"]),
            ),
        )


__all__ = [
    "DEFAULT_ORG_ID",
    "DEFAULT_PASSENGER_ID",
    "DEFAULT_POLICY_ID",
    "DEFAULT_VEHICLE_ID",
    "JevAssessmentAgent",
    "TelemetryQueueWorker",
    "build_trip_timeline_milestones",
    "corroborate_traffic_claim",
    "detect_telemetry_missingness",
    "format_maneuvers_for_llm",
    "haversine_m",
    "parse_trajectory_maneuvers",
    "process_telemetry_event",
]


class JevAssessmentAgent:
    """Jev / Fraud Assessment Agent with kinematic extraction and high-precision classification."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.jev_service = JevAssessmentService(self.settings)

    async def assess(self, event_data: dict[str, Any], use_llm: bool = True) -> dict[str, Any]:
        """Perform kinematic extraction and multi-layer Jev fraud classification.

        Classifies into P0/P1/P2 tier and fraud codes ERR-01 to ERR-05
        with real confidence scores (e.g. 0.92, 0.94, 0.98).

        Evaluation labels (scenario, expected_category, intent, simulation_id, …)
        are stripped by project_model_input before any model or classifier touch.
        Classification is driven exclusively by observable evidence.
        """
        # Strip all evaluation labels — only operational evidence enters classification.
        ev = project_model_input(event_data)

        # Shared mapper for production and benchmark parity
        from src.services.jev_state_builder import map_telemetry_event_to_jev_input

        jev_inp = map_telemetry_event_to_jev_input(ev)
        state_var = event_data.get("state_variant") or ev.get("state_variant")
        if state_var:
            jev_inp.state_variant = str(state_var)
        crit_var = event_data.get("criteria_variant") or ev.get("criteria_variant")
        if crit_var:
            jev_inp.criteria_variant = str(crit_var)
        maneuvers = jev_inp.telemetry.get("maneuvers") or []
        maneuver_narrative = format_maneuvers_for_llm(maneuvers, ev)
        max_speed = float(jev_inp.telemetry.get("max_speed_kmh", 0.0)) / 3.6
        stationary_duration = int(jev_inp.telemetry.get("stationary_duration_s", 0))
        has_mock_reported = bool(jev_inp.telemetry.get("mock_location_reported", False))

        # Try LLM-based evaluation if explicitly requested and OpenRouter key is present
        if (
            use_llm
            and getattr(self.settings, "openrouter_api_key", None)
            and self.settings.openrouter_api_key != "mock"
        ):
            try:
                llm_result = await self._assess_with_llm(
                    ev,
                    maneuver_narrative,
                    max_speed,
                    stationary_duration,
                    has_mock_reported,
                )
                if llm_result:
                    llm_result["maneuvers"] = maneuvers
                    llm_result["maneuver_narrative"] = maneuver_narrative
                    return llm_result
            except Exception as e:
                logger.debug("LLM assessment failed, falling back to jev_service assessment: %s", e)

        jev_res = await self.jev_service.assess(jev_inp)
        assessment_source = getattr(jev_res, "assessment_source", "model")
        if assessment_source == "heuristic_fallback" or jev_res.model_used == "jev_calibrated_heuristic":
            logger.warning(
                "TelemetryQueueWorker received heuristic fallback assessment: model_used=%s source=%s",
                jev_res.model_used,
                assessment_source,
            )
        res = {
            "category": jev_res.category,
            "priority_tier": jev_res.priority_tier,
            "priority_label": jev_res.priority,
            "priority_score": jev_res.priority_score,
            "confidence": jev_res.confidence,
            "reason_codes": jev_res.reason_codes,
            "forensic_brief": jev_res.forensic_brief,
            "model_requested": getattr(jev_res, "model_requested", ""),
            "model_used": jev_res.model_used,
            "fallback_model_used": getattr(jev_res, "fallback_model_used", False),
            "assessment_source": assessment_source,
            "probabilities": jev_res.probabilities,
            "priority_probabilities": jev_res.priority_probabilities,
            "evaluated_features": jev_res.evaluated_features,
            "maneuvers": maneuvers,
            "maneuver_narrative": maneuver_narrative,
        }
        return res

    async def _assess_with_llm(
        self,
        event_data: dict[str, Any],
        maneuver_narrative: str,
        max_speed: float,
        stationary_duration: int,
        has_mock_reported: bool,
    ) -> dict[str, Any] | None:
        """Call OpenRouter ChatOpenAI model with structured maneuver prompt.

        The prompt contains only kinematic facts derived from observable evidence.
        Evaluation labels (scenario, expected_category, intent, …) are never
        included — event_data is assumed to be already projected.
        """
        from src.agents.graph import get_chat_model

        model = get_chat_model(self.settings)
        prompt = (
            f"{maneuver_narrative}\n\n"
            "Dựa trên hồ sơ điều hướng và chuỗi động học chi tiết ở trên: "
            f"max_speed={max_speed:.1f} km/h, stationary_duration_s={stationary_duration}, "
            f"mock_reported={has_mock_reported}.\n"
            "Hãy đối chiếu với Quy chế GreenSM 2026 (Điều 14.1 ERR-01, Điều 14.2 ERR-02 dừng đỗ >= 180s, "
            "Điều 16.1 ERR-03 đi lệch tuyến > 35%, ERR-04 cuốc ảo, Điều 15.3 ERR-05 Fake GPS) "
            "và trả về JSON định dạng duy nhất:\n"
            '{"category": "ERR-01"|"ERR-02"|"ERR-03"|"ERR-04"|"ERR-05"|"no_violation", '
            '"priority_tier": 0|1|2, "priority_score": 1-100, "confidence": 0.0-1.0, '
            '"reason_codes": [...], "forensic_brief": "..."}'
        )
        msg = await model.ainvoke([("user", prompt)])
        from src.services.content_adapter import message_text

        content = message_text(msg)
        # Attempt to parse json from model response
        start_idx = content.find("{")
        end_idx = content.rfind("}")
        if start_idx != -1 and end_idx != -1:
            data = json.loads(content[start_idx : end_idx + 1])
            tier = int(data.get("priority_tier", 2))
            return {
                "category": data.get("category", "no_violation"),
                "priority_tier": tier,
                "priority_label": f"P{tier}",
                "priority_score": int(data.get("priority_score", 80)),
                "confidence": float(data.get("confidence", 0.92)),
                "reason_codes": list(data.get("reason_codes", [])),
                "forensic_brief": str(data.get("forensic_brief", "")),
            }
        return None


def _validate_tenant_telemetry(conn: Any, event: dict[str, Any], organization_id: str) -> None:
    """Lock and validate tenant actors before classifier calls or persistence.

    Policy versions are a shared catalog; only published versions are selectable.
    Actor ownership is validated independently of fixture/test environment switches.
    """
    with conn.cursor() as cur:
        for table, key in (("drivers", "driver_id"), ("passengers", "passenger_id"), ("vehicles", "vehicle_id")):
            # Table names are constants; values always remain bound parameters.
            columns = "id, organization_id, account_status" if table == "drivers" else "id, organization_id"
            cur.execute(f"SELECT {columns} FROM app.{table} WHERE id = %s FOR SHARE;", (event[key],))
            row = cur.fetchone()
            if not row or str(row["organization_id"]) != organization_id:
                raise HTTPException(status_code=403, detail="Telemetry actor is not owned by the active organization")
            if table == "drivers" and row["account_status"] != "active":
                raise HTTPException(status_code=403, detail="Telemetry driver is not active")
        cur.execute(
            "SELECT id, status FROM app.policy_versions WHERE id = %s FOR SHARE;", (event["policy_version_id"],)
        )
        policy = cur.fetchone()
        if not policy or policy["status"] != "published":
            raise HTTPException(status_code=422, detail="Telemetry requires a published policy version")
        cur.execute("SELECT organization_id, passenger_id FROM app.trips WHERE id = %s FOR SHARE;", (event["trip_id"],))
        trip = cur.fetchone()
        if trip and (
            str(trip["organization_id"]) != organization_id or str(trip["passenger_id"]) != event["passenger_id"]
        ):
            raise HTTPException(status_code=403, detail="Telemetry trip ownership or passenger does not match")
        cur.execute(
            """SELECT t.organization_id, a.trip_id, a.driver_id, a.vehicle_id
               FROM app.trip_assignments a JOIN app.trips t ON t.id = a.trip_id
               WHERE a.id = %s FOR SHARE OF a, t;""",
            (event["assignment_id"],),
        )
        assignment = cur.fetchone()
        if assignment and (
            str(assignment["organization_id"]) != organization_id
            or any(str(assignment[key]) != event[key] for key in ("trip_id", "driver_id", "vehicle_id"))
        ):
            raise HTTPException(status_code=403, detail="Telemetry assignment ownership or actors do not match")


async def process_telemetry_event(
    event_data: dict[str, Any],
    case_service: CaseService | None = None,
    *,
    organization_id: str | None = None,
    classifier: Any | None = None,
) -> dict[str, Any]:
    """Process telemetry using trusted caller tenancy, never payload authority.

    The authenticated caller supplies organization_id separately. Legacy queue
    fixtures without tenant authority retain the existing simulation write gate.
    """
    service = case_service or get_case_service()
    if organization_id is None:
        if event_data.get("organization_id"):
            raise HTTPException(status_code=403, detail="Telemetry organization requires trusted caller scope")
        return await _process_telemetry_event(event_data, service, classifier=classifier)
    organization_id = str(organization_id)
    if event_data.get("organization_id") and str(event_data["organization_id"]) != organization_id:
        raise HTTPException(status_code=403, detail="Telemetry organization does not match trusted caller scope")
    event = dict(event_data)
    for key in ("driver_id", "passenger_id", "vehicle_id", "policy_version_id"):
        if not event.get(key):
            raise HTTPException(status_code=422, detail=f"Telemetry requires {key}")
    for key in ("trip_id", "assignment_id"):
        event[key] = event.get(key) or str(uuid4())
    try:
        UUID(organization_id)
        for key in ("trip_id", "assignment_id", "driver_id", "passenger_id", "vehicle_id", "policy_version_id"):
            event[key] = str(UUID(str(event[key])))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Telemetry actor and organization IDs must be UUIDs") from exc
    if not _coordinate_pair(event.get("pickup")) or not _coordinate_pair(event.get("dropoff")):
        raise HTTPException(status_code=422, detail="Telemetry requires recorded pickup and dropoff coordinates")
    if not event.get("points") or any(_telemetry_coordinate(point) is None for point in event["points"]):
        raise HTTPException(status_code=422, detail="Telemetry requires valid recorded points")
    conn = service._get_db_connection()
    if conn is None:
        raise HTTPException(status_code=503, detail="Telemetry persistence is unavailable")
    try:
        _validate_tenant_telemetry(conn, event, organization_id)
        return await _process_telemetry_event(
            event, service, organization_id=organization_id, connection=conn, classifier=classifier
        )
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


async def _process_telemetry_event(
    event_data: dict[str, Any],
    case_service: CaseService | None = None,
    *,
    organization_id: str | None = None,
    connection: Any = None,
    classifier: Any | None = None,
) -> dict[str, Any]:
    """Process a single trip telemetry event from the queue:

    1. Check driver suspension (if suspended, reject!).
    2. Evaluate technical guardrails, then invoke Jev Assessment Agent unless a
       guardrail short-circuits classification.
    3. Write to PostgreSQL (app.trips, app.telemetry_points, app.fraud_cases, app.model_assessments).
    4. Sync CaseService in-memory state.
    """
    service = case_service or get_case_service()
    target_org_id = organization_id or DEFAULT_ORG_ID
    passenger_id = str(event_data["passenger_id"]) if organization_id else DEFAULT_PASSENGER_ID
    vehicle_id = str(event_data["vehicle_id"]) if organization_id else DEFAULT_VEHICLE_ID
    policy_id = str(event_data["policy_version_id"]) if organization_id else DEFAULT_POLICY_ID
    event_id = str(event_data.get("event_id") or "")
    payload_hash = hashlib.sha256(json.dumps(event_data, sort_keys=True, default=str).encode()).hexdigest()
    assignment_id_for_replay = event_data.get("assignment_id")
    sequence_for_replay = event_data.get("sequence")
    replay_key = (
        f"driver_app:{assignment_id_for_replay}:{sequence_for_replay}"
        if assignment_id_for_replay and sequence_for_replay is not None
        else event_id
    )
    if organization_id and replay_key:
        replay_key = f"{organization_id}:{replay_key}"
    seen = getattr(service, "_telemetry_event_hashes", None)
    if seen is None:
        seen = {}
        setattr(service, "_telemetry_event_hashes", seen)
    if replay_key and replay_key in seen:
        if seen[replay_key] != payload_hash:
            raise ValueError(f"telemetry identity {replay_key} has a different payload")
        prior = getattr(service, "_telemetry_event_results", {}).get(replay_key)
        if prior is not None:
            return prior
    # IDs and metadata
    trip_id = str(event_data.get("trip_id") or uuid4())
    driver_id = str(event_data.get("driver_id") or "018f2f4e-3000-7000-8000-000000000001")
    assignment_id = str(event_data.get("assignment_id") or uuid4())
    case_id = str(uuid4() if organization_id else event_data.get("case_id") or uuid4())
    lifecycle = str(event_data.get("lifecycle_state") or "complete")
    status = "cancelled" if lifecycle in ("cancelled", "canceled") else "completed"

    # 1. Check driver suspension invariant
    if organization_id is None and service.is_driver_suspended(driver_id):
        err_msg = f"Driver {driver_id} is currently suspended and cannot accept or make trips"
        logger.warning("Rejected trip: %s", err_msg)
        raise HTTPException(status_code=403, detail=err_msg)

    points = event_data.get("points") or []

    # 2. Technical guardrails run before fraud classification: a technical dropout is not fraud.
    guardrail = (
        evaluate_telemetry_window(points, event_data.get("platform_incidents") or event_data.get("incidents") or [])
        if _guardrail_enabled()
        else None
    )
    if guardrail is not None and should_short_circuit(guardrail):
        assessment = build_guardrail_assessment(guardrail)
        assessment["model_used"] = "guardrail_short_circuit"
        assessment["model_version"] = "guardrail"
        assessment["fallback_model_used"] = False
        assessment["assessment_source"] = "guardrail"
        assessment["inference_ms"] = 0.0
        assessment["advisory"] = None
    else:
        if getattr(service.settings, "fraud_classifier_enabled", False):
            active_classifier = classifier
            if active_classifier is None:
                try:
                    from src.api.classifier_routes import get_classifier_service

                    active_classifier = get_classifier_service()
                except Exception as exc:
                    logger.warning("Classifier unavailable in worker: %s", exc)
                    if bool(getattr(service.settings, "jev_allow_heuristic_fallback", False)):
                        agent = JevAssessmentAgent(service.settings)
                        assessment = await agent.assess(project_model_input(event_data))
                        active_classifier = None
                    else:
                        raise

            if active_classifier is not None:
                try:
                    import anyio

                    model_input = project_model_input(event_data)
                    clf_res = await anyio.to_thread.run_sync(active_classifier.predict, model_input)
                    primary_cat = getattr(clf_res, "category", "no_violation")
                    confidence = float(getattr(clf_res, "confidence", 0.0))
                    feat_ms = float(getattr(clf_res, "feature_ms", 0.0))
                    infer_ms = float(getattr(clf_res, "inference_ms", 0.0))
                    model_ver = str(
                        getattr(clf_res, "model_version", getattr(active_classifier, "model_version", "r3d"))
                    )
                    source = getattr(clf_res, "assessment_source", "r3d_classifier")
                    probs = getattr(clf_res, "probabilities", {})

                    # Advisory Mercury / Jev
                    advisory_payload = None
                    if bool(getattr(service.settings, "classifier_llm_advisory", False)):
                        from src.services.classifier_advisory import run_classifier_advisory

                        timeout_s = float(getattr(service.settings, "classifier_advisory_timeout_s", 8.0))
                        adv = await run_classifier_advisory(
                            bundle=model_input,
                            primary_category=primary_cat,
                            timeout_s=timeout_s,
                            settings=service.settings,
                        )
                        advisory_payload = adv.model_dump()

                    p_tier = 2 if primary_cat == "no_violation" else 1
                    p_label = "P2" if primary_cat == "no_violation" else "P1"
                    p_score = 10 if primary_cat == "no_violation" else int(min(100, max(1, round(confidence * 100))))

                    assessment = {
                        "category": primary_cat,
                        "priority_tier": p_tier,
                        "priority_label": p_label,
                        "priority_score": p_score,
                        "confidence": confidence,
                        "reason_codes": [primary_cat] if primary_cat != "no_violation" else [],
                        "forensic_brief": f"R3D fraud classifier output: {primary_cat} (confidence {confidence:.2f})",
                        "model_used": model_ver,
                        "model_version": model_ver,
                        "feature_ms": feat_ms,
                        "inference_ms": infer_ms,
                        "assessment_source": source,
                        "probabilities": probs,
                        "advisory": advisory_payload,
                    }
                except Exception as exc:
                    logger.error("Primary fraud classifier failed in worker: %s", exc)
                    if bool(getattr(service.settings, "jev_allow_heuristic_fallback", False)):
                        agent = JevAssessmentAgent(service.settings)
                        assessment = await agent.assess(project_model_input(event_data))
                    else:
                        raise
        else:
            agent = JevAssessmentAgent(service.settings)
            assessment = await agent.assess(project_model_input(event_data))

        if guardrail is not None:
            assessment = cap_priority_for_guardrail(assessment, guardrail)

    # Structured assessment audit log (no PII, trip_id hashed)
    trip_ref_hash = hashlib.sha256(str(trip_id).encode("utf-8")).hexdigest()[:16]
    log_data = {
        "trip_ref": trip_ref_hash,
        "category": assessment.get("category"),
        "confidence": assessment.get("confidence"),
        "inference_ms": assessment.get("inference_ms", 0.0),
        "model_version": assessment.get("model_version") or assessment.get("model_used"),
        "assessment_source": assessment.get("assessment_source"),
    }
    adv_info = assessment.get("advisory")
    if adv_info:
        log_data["advisory_status"] = adv_info.get("advisory_status")
        log_data["advisory_latency_ms"] = adv_info.get("llm_latency_ms")
        log_data["agreement"] = adv_info.get("agreement")
    logger.info("CLASSIFIER_ASSESSMENT %s", json.dumps(log_data))
    guardrail_payload = guardrail.model_dump(mode="json") if guardrail is not None else None
    assessment["guardrail"] = guardrail_payload

    # Features use only the booking's recorded pickup, never the fallbacks derived below.
    feature_window = compute_feature_window(points, pickup=_coordinate_pair(event_data.get("pickup")))
    feature_payload = {
        **feature_window.model_dump(mode="json"),
        "guardrail": guardrail_payload,
        # Producer-declared value kept for audit only; the column stores the computed SSD.
        "declared_stationary_duration_s": event_data.get("stationary_duration_s"),
    }
    feature_quality_flags = list(
        dict.fromkeys(
            [*(guardrail_payload["quality_flags"] if guardrail_payload else []), *feature_window.quality_flags]
        )
    )

    pickup_coords: list[float] | None = _coordinate_pair(event_data.get("pickup"))
    dropoff_coords: list[float] | None = _coordinate_pair(event_data.get("dropoff"))
    if not pickup_coords and points:
        pt0 = _telemetry_coordinate(points[0])
        if pt0:
            pickup_coords = list(pt0)
    if not dropoff_coords and points:
        ptn = _telemetry_coordinate(points[-1])
        if ptn:
            dropoff_coords = list(ptn)
    current_app_env = str(getattr(service.settings, "app_env", ""))
    if not pickup_coords and current_app_env == "test":
        pickup_coords = [105.8542, 21.0285]
    if not dropoff_coords and current_app_env == "test":
        dropoff_coords = [105.8600, 21.0350]
    now = (
        datetime.fromisoformat(str(points[0].get("occurred_at")).replace("Z", "+00:00"))
        if points and points[0].get("occurred_at")
        else datetime.now(UTC)
    )

    # 3. Write to PostgreSQL if DB connection available
    conn = connection if organization_id else service._get_db_connection()
    if conn is not None and organization_id is None:
        # S4-TENANT #294 P1b: every branch below writes DEFAULT_ORG_ID rows.
        _require_simulation_tenant_writes(service.settings)
    assigned_analyst_id: str | None = None
    if conn is not None and assessment["category"] != "no_violation" and (not pickup_coords or not dropoff_coords):
        conn.close()
        raise HTTPException(status_code=422, detail="Fraud case requires recorded pickup and dropoff coordinates")
    if conn is not None and assessment["category"] == "no_violation":
        try:
            _persist_nominal_event(
                conn,
                trip_id=trip_id,
                assignment_id=assignment_id,
                driver_id=driver_id,
                points=points,
                event_data=event_data,
                now=now,
                organization_id=organization_id,
            )
            conn.commit()
        except Exception:
            if organization_id is None:
                conn.rollback()
            raise
        finally:
            if organization_id is None:
                conn.close()
        conn = None
    if conn is not None:
        assert pickup_coords is not None and dropoff_coords is not None
        try:
            with conn.cursor() as cur:
                cur.execute("SET search_path = app, extensions, public;")

                # 3.1 Trip
                pickup_address = event_data.get("pickup_address")
                dropoff_address = event_data.get("dropoff_address")
                cur.execute(
                    """
                    INSERT INTO app.trips (
                        id, organization_id, passenger_id, requested_at, pickup, dropoff,
                        requested_service_class, status, cancelled_at, completed_at, created_at,
                        pickup_address, dropoff_address
                    ) VALUES (
                        %s, %s, %s, %s,
                        st_setsrid(st_makepoint(%s, %s), 4326)::geography,
                        st_setsrid(st_makepoint(%s, %s), 4326)::geography,
                        'car_standard', %s, %s, %s, %s,
                        %s, %s
                    ) ON CONFLICT (id) DO UPDATE SET
                        pickup_address = COALESCE(EXCLUDED.pickup_address, app.trips.pickup_address),
                        dropoff_address = COALESCE(EXCLUDED.dropoff_address, app.trips.dropoff_address);
                    """,
                    (
                        trip_id,
                        target_org_id,
                        passenger_id,
                        now,
                        pickup_coords[0],
                        pickup_coords[1],
                        dropoff_coords[0],
                        dropoff_coords[1],
                        status,
                        now if status == "cancelled" else None,
                        now if status == "completed" else None,
                        now,
                        pickup_address,
                        dropoff_address,
                    ),
                )

                # 3.2 Assignment
                cur.execute(
                    """
                    INSERT INTO app.trip_assignments (
                        id, trip_id, driver_id, vehicle_id, state, offered_at, accepted_at,
                        arrived_at, started_at, ended_at, cancellation_actor, cancellation_reason, created_at
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                    ) ON CONFLICT (id) DO NOTHING;
                    """,
                    (
                        assignment_id,
                        trip_id,
                        driver_id,
                        vehicle_id,
                        status,
                        now,
                        now,
                        now,
                        now,
                        now,
                        event_data.get("cancellation_actor"),
                        event_data.get("cancellation_reason"),
                        now,
                    ),
                )

                # 3.3 Fraud Case. Nominal telemetry is durable without opening a case.
                assigned_analyst_id = None
                if assessment["category"] != "no_violation":
                    cur.execute(
                        """
                        SELECT p.id
                        FROM app.principals p
                        WHERE p.id = (
                            SELECT candidate.id
                            FROM app.principals candidate
                            JOIN app.principal_roles role ON role.principal_id = candidate.id
                            LEFT JOIN app.fraud_cases open_case
                              ON open_case.assigned_analyst_id = candidate.id
                             AND open_case.status IN ('ready', 'in_review')
                            WHERE candidate.organization_id = %s
                              AND candidate.status = 'active'
                              AND role.role IN ('analyst', 'senior_analyst', 'fraud_analyst')
                            GROUP BY candidate.id
                            ORDER BY count(open_case.id), candidate.id
                            LIMIT 1
                        )
                        FOR UPDATE SKIP LOCKED;
                        """,
                        (target_org_id,),
                    )
                    analyst_row = cur.fetchone()
                    assigned_analyst_id = str(analyst_row["id"]) if analyst_row else None
                if assessment["category"] != "no_violation":
                    p_tier = assessment.get("priority_tier")
                    if p_tier is None:
                        p_tier = 2
                    p_score = assessment.get("priority_score")
                    if p_score is None:
                        p_score = 10
                    cur.execute(
                        """
                        INSERT INTO app.fraud_cases (
                            id, organization_id, assignment_id, status, suspected_category,
                            priority_tier, priority_score, priority_rule_version, version,
                            assigned_analyst_id, created_at, updated_at
                        ) VALUES (
                            %s, %s, %s, 'ready', %s, %s, %s, '2026.03', 1, %s, %s, %s
                        ) ON CONFLICT (assignment_id) DO UPDATE SET
                            suspected_category = EXCLUDED.suspected_category,
                            priority_tier = EXCLUDED.priority_tier,
                            priority_score = EXCLUDED.priority_score,
                            assigned_analyst_id = COALESCE(EXCLUDED.assigned_analyst_id, app.fraud_cases.assigned_analyst_id),
                            updated_at = EXCLUDED.updated_at
                        RETURNING id;
                        """,
                        (
                            case_id,
                            target_org_id,
                            assignment_id,
                            assessment.get("category", "no_violation"),
                            p_tier,
                            p_score,
                            assigned_analyst_id,
                            now,
                            now,
                        ),
                    )
                    case_row = cur.fetchone()
                    if case_row:
                        case_id = str(case_row["id"])

                # 3.4 Evidence Snapshot
                cur.execute(
                    "SELECT id FROM app.evidence_snapshots WHERE case_id = %s LIMIT 1;",
                    (case_id,),
                )
                existing_snap = cur.fetchone()
                if existing_snap:
                    snap_id = str(existing_snap["id"])
                else:
                    snap_id = str(uuid4())
                    dossier_data = json.dumps({"points_count": len(points)}).encode()
                    dossier_hash = hashlib.sha256(dossier_data).digest()
                    cur.execute(
                        """
                        INSERT INTO app.evidence_snapshots (
                            id, case_id, version, policy_version_id, event_cutoff_at, stage,
                            dossier, dossier_hash, created_at
                        ) VALUES (
                            %s, %s, 1, %s, %s, 'post_cancellation', %s, %s, %s
                        ) ON CONFLICT DO NOTHING;
                        """,
                        (
                            snap_id,
                            case_id,
                            policy_id,
                            now,
                            json.dumps({"points_count": len(points)}),
                            dossier_hash,
                            now,
                        ),
                    )

                # 3.5 Feature Set
                cur.execute(
                    "SELECT id FROM app.feature_sets WHERE evidence_snapshot_id = %s LIMIT 1;",
                    (snap_id,),
                )
                existing_feat = cur.fetchone()
                if existing_feat:
                    feature_id = str(existing_feat["id"])
                else:
                    feature_id = str(uuid4())
                    cur.execute(
                        """
                        INSERT INTO app.feature_sets (
                            id, evidence_snapshot_id, preprocessing_version, window_start, window_end,
                            telemetry_coverage, max_gap_s, davi, stationary_duration_s, quality_flags,
                            features, created_at
                        ) VALUES (
                            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                        ) ON CONFLICT DO NOTHING;
                        """,
                        (
                            feature_id,
                            snap_id,
                            feature_window.feature_version,
                            now,
                            now,
                            # Both columns are NOT NULL; the real None is recorded in
                            # features.missing_features plus the insufficient_samples flag.
                            # TODO(migration): make these nullable (DATA_MODEL: null is not zero).
                            feature_window.telemetry_coverage if feature_window.telemetry_coverage is not None else 0.0,
                            round(feature_window.max_gap_s) if feature_window.max_gap_s is not None else 0,
                            feature_window.davi,
                            (
                                round(feature_window.approach_stationary_duration_s)
                                if feature_window.approach_stationary_duration_s is not None
                                else None
                            ),
                            # CaseService derives CaseDetailResponse.guardrails and the
                            # adjudication block from this column, not from `features`.
                            json.dumps(feature_quality_flags),
                            json.dumps(feature_payload),
                            now,
                        ),
                    )

                # 3.6 Model Assessment
                cur.execute(
                    "SELECT id FROM app.model_assessments WHERE evidence_snapshot_id = %s LIMIT 1;",
                    (snap_id,),
                )
                if not cur.fetchone():
                    assessment_id = str(uuid4())
                    cur.execute(
                        """
                        INSERT INTO app.model_assessments (
                            id, evidence_snapshot_id, feature_set_id, provider, model_id,
                            prompt_version, output_schema_version, status, category,
                            confidence, score_semantics, reason_codes, forensic_brief, created_at
                        ) VALUES (
                            %s, %s, %s, 'JevSentinel', %s, 'v1.0', 1, 'completed',
                            %s, %s, 'probability_of_violation', %s, %s, %s
                        ) ON CONFLICT DO NOTHING;
                        """,
                        (
                            assessment_id,
                            snap_id,
                            feature_id,
                            assessment.get("model_used")
                            or (
                                "telemetry-guardrail"
                                if guardrail and should_short_circuit(guardrail)
                                else "jev-kinematic-v1"
                            ),
                            assessment["category"],
                            assessment["confidence"],
                            json.dumps(assessment["reason_codes"]),
                            assessment["forensic_brief"],
                            now,
                        ),
                    )

                # 3.7 Ingest Events & Telemetry Points
                for idx, pt in enumerate(points):
                    coordinate = _telemetry_coordinate(pt)
                    if coordinate is None:
                        continue
                    evt_id = str(uuid4())
                    point_payload = json.dumps(pt, sort_keys=True)
                    point_payload_hash = hashlib.sha256(point_payload.encode()).digest()
                    cur.execute(
                        """
                        INSERT INTO app.ingest_events (
                            event_id, organization_id, schema_version, event_type, source,
                            occurred_at, correlation_id, trip_id, assignment_id, driver_id,
                            producer_sequence, payload, payload_hash
                        ) VALUES (
                            %s, %s, 1, 'telemetry.frame', 'driver_app', %s, %s, %s, %s, %s, %s, %s, %s
                        ) ON CONFLICT (source, assignment_id, producer_sequence) DO NOTHING
                        RETURNING event_id;
                        """,
                        (
                            evt_id,
                            target_org_id,
                            now,
                            uuid4(),
                            trip_id,
                            assignment_id,
                            driver_id,
                            idx,
                            point_payload,
                            point_payload_hash,
                        ),
                    )
                    evt_row = cur.fetchone()
                    if not evt_row:
                        cur.execute(
                            """
                            SELECT event_id, payload_hash
                            FROM app.ingest_events
                            WHERE source = %s AND assignment_id = %s AND producer_sequence = %s;
                            """,
                            ("driver_app", assignment_id, idx),
                        )
                        existing_event = cur.fetchone()
                        if existing_event is None:
                            raise RuntimeError("Telemetry ingest conflict could not be resolved")
                        existing_hash = (
                            existing_event["payload_hash"] if isinstance(existing_event, dict) else existing_event[1]
                        )
                        if bytes(existing_hash) != point_payload_hash:
                            raise HTTPException(status_code=409, detail="Telemetry event has a different payload")
                        evt_id = str(
                            existing_event["event_id"] if isinstance(existing_event, dict) else existing_event[0]
                        )
                    else:
                        evt_id = str(evt_row["event_id"] if isinstance(evt_row, dict) else evt_row[0])

                    lon, lat = coordinate
                    cur.execute(
                        """
                        INSERT INTO app.telemetry_points (
                            event_id, assignment_id, occurred_at, position, speed_mps,
                            bearing_deg, accuracy_m, app_state, network_state, gps_state,
                            mock_location_reported
                        ) VALUES (
                            %s, %s, %s,
                            st_setsrid(st_makepoint(%s, %s), 4326)::geography,
                            %s, %s, %s, %s, %s, %s, %s
                        ) ON CONFLICT (event_id) DO NOTHING;
                        """,
                        (
                            evt_id,
                            assignment_id,
                            now,
                            lon,
                            lat,
                            float(pt.get("speed_mps", 0.0)),
                            float(pt.get("bearing_deg", 0.0)),
                            float(pt["accuracy_m"]) if pt.get("accuracy_m") is not None else None,
                            pt.get("app_state", "foreground"),
                            pt.get("network_state", "online"),
                            pt.get("gps_state", "valid"),
                            bool(pt.get("mock_location_reported")),
                        ),
                    )

                conn.commit()
        except Exception as e:
            logger.warning("Database write error in telemetry worker: %s", e)
            if conn and organization_id is None:
                conn.rollback()
            raise
        finally:
            if organization_id is None:
                conn.close()

    pickup_coords = _coordinate_pair(event_data.get("pickup"))
    dropoff_coords = _coordinate_pair(event_data.get("dropoff"))
    missingness_alerts = detect_telemetry_missingness(points)
    milestones = build_trip_timeline_milestones(
        points=points,
        pickup_pos=pickup_coords,
        dropoff_pos=dropoff_coords,
        stall_duration_s=int(event_data.get("stationary_duration_s") or 0),
        alerts=missingness_alerts,
    )

    # 4. Sync CaseService in-memory state
    if hasattr(service, "_candidate_routes"):
        service._candidate_routes.pop(case_id, None)
    if hasattr(service, "_traffic_corroborations"):
        service._traffic_corroborations.pop(case_id, None)
    if hasattr(service, "_timeline_milestones"):
        service._timeline_milestones[case_id] = milestones
    if hasattr(service, "_missingness_alerts"):
        service._missingness_alerts[case_id] = missingness_alerts
    if hasattr(service, "_destinations") and dropoff_coords:
        service._destinations[case_id] = {
            "latitude": dropoff_coords[1],
            "longitude": dropoff_coords[0],
            "label": str(event_data.get("dropoff_address") or "Destination"),
        }

    for pt in points:
        coordinate = _telemetry_coordinate(pt)
        if coordinate is None:
            continue
        service._telemetry_points.append(
            {
                "assignment_id": assignment_id,
                "position": {
                    "type": "Point",
                    "coordinates": coordinate,
                },
                "speed_mps": float(pt.get("speed_mps", 0.0)),
                "bearing_deg": float(pt.get("bearing_deg", 0.0)),
                "accuracy_m": (float(pt["accuracy_m"]) if pt.get("accuracy_m") is not None else None),
                "app_state": pt.get("app_state", "foreground"),
                "network_state": pt.get("network_state", "online"),
                "gps_state": pt.get("gps_state", "valid"),
                "occurred_at": pt.get("occurred_at") or now.isoformat(),
            }
        )

    service._trips[trip_id] = {
        "id": trip_id,
        "passenger_id": passenger_id,
        "organization_id": target_org_id,
        "_organization_id": target_org_id,
        "driver_id": driver_id,
        "status": status,
        "created_at": now.isoformat(),
        "pickup": {"type": "Point", "coordinates": pickup_coords} if pickup_coords else None,
        "dropoff": {"type": "Point", "coordinates": dropoff_coords} if dropoff_coords else None,
        "pickup_address": event_data.get("pickup_address"),
        "dropoff_address": event_data.get("dropoff_address"),
    }
    service._assignments[assignment_id] = {
        "id": assignment_id,
        "organization_id": target_org_id,
        "_organization_id": target_org_id,
        "trip_id": trip_id,
        "driver_id": driver_id,
        "state": status,
    }
    if assessment["category"] != "no_violation":
        in_memory_analyst_id = assigned_analyst_id
        if organization_id is None and not in_memory_analyst_id and hasattr(service, "_analysts") and service._analysts:
            analyst_counts = {a_id: 0 for a_id in service._analysts}
            for c in service._cases.values():
                aid = c.get("assigned_analyst_id")
                if aid in analyst_counts and c.get("status") in ("ready", "in_review"):
                    analyst_counts[aid] += 1
            in_memory_analyst_id = min(analyst_counts, key=lambda k: analyst_counts[k])
        elif organization_id is None and not in_memory_analyst_id:
            in_memory_analyst_id = "018f2f4e-3000-7000-8000-000000000001"

        p_tier_mem = assessment.get("priority_tier")
        if p_tier_mem is None:
            p_tier_mem = 2
        p_score_mem = assessment.get("priority_score")
        if p_score_mem is None:
            p_score_mem = 10

        service._cases[case_id] = {
            "id": case_id,
            "organization_id": target_org_id,
            "_organization_id": target_org_id,
            "assignment_id": assignment_id,
            "status": "ready",
            "priority_tier": p_tier_mem,
            "priority_score": p_score_mem,
            "suspected_category": assessment.get("category", "no_violation"),
            "confidence": assessment.get("confidence", 0.0),
            "assigned_analyst_id": in_memory_analyst_id,
            "version": 1,
            "created_at": now.isoformat(),
            "updated_at": now.isoformat(),
        }
    service._model_assessments[case_id] = {
        "case_id": case_id,
        "label": assessment["category"],
        "confidence": assessment["confidence"],
        "category": assessment["category"],
        "reason_codes": assessment["reason_codes"],
        "forensic_brief": assessment["forensic_brief"],
        "guardrail": guardrail_payload,
        "model_version": assessment.get("model_version") or assessment.get("model_used"),
        "inference_ms": assessment.get("inference_ms", 0.0),
        "advisory": assessment.get("advisory"),
    }
    if hasattr(service, "_guardrails"):
        service._guardrails[case_id] = guardrail_payload

    result = {
        "status": "processed",
        "trip_id": trip_id,
        "case_id": case_id if (assessment["category"] != "no_violation") else None,
        "assignment_id": assignment_id,
        "driver_id": driver_id,
        "category": assessment.get("category"),
        "confidence": assessment.get("confidence"),
        "priority_label": assessment.get("priority_label"),
        "priority_tier": assessment.get("priority_tier"),
        "forensic_brief": assessment.get("forensic_brief"),
        "assessment": assessment,
    }
    results = getattr(service, "_telemetry_event_results", None)
    if results is None:
        results = {}
        setattr(service, "_telemetry_event_results", results)
    if replay_key:
        seen[replay_key] = payload_hash
        results.setdefault(replay_key, result)
    return result


class TelemetryQueueWorker:
    """Redis Stream & PubSub worker for incoming vehicle telemetry."""

    def __init__(
        self,
        redis_host: str = "localhost",
        redis_port: int = 6379,
        stream_key: str = "telemetry:stream",
        channel: str = "telemetry:events",
        case_service: CaseService | None = None,
        queue: ReliableTelemetryQueue | None = None,
        processor: Any | None = None,
        classifier: Any | None = None,
    ) -> None:
        self.redis_host = redis_host
        self.redis_port = redis_port
        self.stream_key = stream_key
        self.channel = channel
        self.case_service = case_service or get_case_service()
        self._running = False
        self._client: redis.Redis | None = None
        self.queue = queue
        self.classifier = classifier
        self.processor = processor or (
            lambda payload, service: process_telemetry_event(payload, service, classifier=self.classifier)
        )

    def get_client(self) -> redis.Redis:
        if self._client is None:
            redis_url = os.getenv("REDIS_URL")
            if redis_url:
                self._client = redis.from_url(redis_url, decode_responses=True)
            else:
                self._client = redis.Redis(
                    host=self.redis_host,
                    port=self.redis_port,
                    decode_responses=True,
                )
        return self._client

    async def run_once(self) -> list[dict[str, Any]]:
        """Fetch and process available messages from the Redis stream."""
        if self.queue is not None:
            results: list[dict[str, Any]] = []
            item = await self.queue.claim()
            if not item:
                return results
            try:
                result = await self.processor(item["payload"], self.case_service)
            except Exception as exc:
                await self.queue.fail(item, exc)
                logger.warning("Telemetry event failed; returned to queue: %s", exc)
                return results
            await self.queue.ack(item)
            results.append(result)
            return results
        client = self.get_client()
        results = []
        try:
            # Read new entries from stream
            entries: Any = client.xread({self.stream_key: "0-0"}, count=10)
            if entries:
                for stream, messages in entries:
                    for msg_id, data in messages:
                        raw_payload = data.get("data") or data.get("payload") if isinstance(data, dict) else None
                        if raw_payload:
                            event_dict = json.loads(raw_payload) if isinstance(raw_payload, str) else raw_payload
                            res = await process_telemetry_event(
                                event_dict, self.case_service, classifier=self.classifier
                            )
                            results.append(res)
                        # Delete message from stream after processing
                        client.xdel(str(stream), str(msg_id))
        except Exception as e:
            logger.debug("Redis stream read error: %s", e)
        return results

    async def start(self) -> None:
        """Continuously listen and process telemetry events."""
        self._running = True
        logger.info("Telemetry queue worker started listening on %s", self.stream_key)
        while self._running:
            await self.run_once()
            await asyncio.sleep(0.1)

    def stop(self) -> None:
        self._running = False


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    worker = TelemetryQueueWorker()
    try:
        asyncio.run(worker.start())
    except KeyboardInterrupt:
        worker.stop()

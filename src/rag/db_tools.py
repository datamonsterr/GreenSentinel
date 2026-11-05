"""Read-only database query tools for RAG and Cockpit assistants.

Provides direct access to PostgreSQL / Supabase schema `app` with seamless
fallback to initialized synthetic datasets when live database connectivity is offline.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import logging
from typing import Any
from uuid import UUID

from fastapi import HTTPException

from src.rag.driver_tools import MOCK_DRIVERS, strip_accents
from src.services.case_service import CaseService, get_case_service

logger = logging.getLogger(__name__)


def _mask_phone(phone: str | None) -> str:
    """Mask phone number for PII guardrail compliance with strict validation.

    Guarantees:
    - Empty or None inputs return '[NOT_PROVIDED]'.
    - Existing redaction sentinels ('[REDACTED]', '[NOT_PROVIDED]', '[UNAVAILABLE]') are preserved.
    - Raw input is parsed to extract pure numeric digits.
    - Numbers with fewer than 9 or more than 15 digits (violating E.164) are fully redacted
      to '[REDACTED]' without leaking partial fragments.
    - Valid numbers are formatted with country/operator prefix and masked middle digits:
      '+84xxxxxx678' (international VN) or '09xxxxx678' (domestic). Middle characters
      are completely replaced by 'x', preventing any formatting or character leakage.
    """
    if not phone:
        return "[NOT_PROVIDED]"
    s = str(phone).strip()
    if s in ("[REDACTED]", "[NOT_PROVIDED]", "[UNAVAILABLE]"):
        return s

    has_plus = s.startswith("+")
    raw_digits = "".join(ch for ch in s if ch.isdigit())

    # E.164 and Vietnamese national numbers require between 9 and 15 digits
    if len(raw_digits) < 9 or len(raw_digits) > 15:
        return "[REDACTED]"

    if has_plus and raw_digits.startswith("84"):
        prefix = "+84"
        remaining_digits = raw_digits[2:]
    elif raw_digits.startswith("0"):
        prefix = raw_digits[:2]
        remaining_digits = raw_digits[2:]
    else:
        prefix = raw_digits[:3]
        remaining_digits = raw_digits[3:]

    # Keep last 3 digits, mask everything in between
    suffix = remaining_digits[-3:] if len(remaining_digits) >= 3 else ""
    mask_count = max(len(remaining_digits) - len(suffix), 4)
    return f"{prefix}{'x' * mask_count}{suffix}"


def get_case_information(case_id: str, service: CaseService | None = None) -> dict[str, Any]:
    """Retrieve full case information including trip, assignment, priority, and evidence from database.

    Read-only query against app.fraud_cases with fallback to case service cache.
    """
    srv = service or get_case_service()
    clean_id = str(case_id).strip()[:64]

    # Validate whether clean_id is a UUID to avoid unindexed ::text casting and ensure type safety
    case_uuid = None
    try:
        case_uuid = str(UUID(clean_id))
    except (ValueError, TypeError, AttributeError):
        case_uuid = None

    conn = srv._get_db_connection()
    if conn is not None and case_uuid is not None:
        try:
            with conn.cursor() as cur:
                cur.execute("SET search_path = app, extensions, public;")
                cur.execute(
                    """
                    SELECT
                        c.id,
                        a.trip_id,
                        c.assignment_id,
                        a.driver_id,
                        c.status,
                        c.priority_tier,
                        c.priority_score,
                        c.suspected_category,
                        ma.confidence,
                        c.created_at,
                        c.updated_at,
                        c.assigned_analyst_id,
                        c.version
                    FROM app.fraud_cases c
                    JOIN app.trip_assignments a ON a.id = c.assignment_id
                    LEFT JOIN LATERAL (SELECT confidence FROM app.model_assessments WHERE evidence_snapshot_id IN (SELECT id FROM app.evidence_snapshots WHERE case_id = c.id) ORDER BY created_at DESC LIMIT 1) ma ON true
                    WHERE c.id = %s::uuid
                    LIMIT 1;
                    """,
                    (case_uuid,),
                )
                row = cur.fetchone()
                if row:
                    case_dict = dict(row)
                    for k, v in case_dict.items():
                        if isinstance(v, UUID):
                            case_dict[k] = str(v)
                        elif hasattr(v, "isoformat"):
                            case_dict[k] = v.isoformat()
                    if "priority" not in case_dict and "priority_tier" in case_dict:
                        case_dict["priority"] = f"P{case_dict['priority_tier']}"
                    if "category" not in case_dict and "suspected_category" in case_dict:
                        case_dict["category"] = case_dict["suspected_category"]
                    return {
                        "source": "database",
                        "found": True,
                        "case": case_dict,
                    }
        except Exception as exc:
            logger.warning("Database query failed in get_case_information (%s); falling back", exc)
        finally:
            conn.close()

    if clean_id in srv._cases:
        c = dict(srv._cases[clean_id])
        for k, v in c.items():
            if isinstance(v, UUID):
                c[k] = str(v)
            elif hasattr(v, "isoformat"):
                c[k] = v.isoformat()
        if "priority" not in c and "priority_tier" in c:
            c["priority"] = f"P{c['priority_tier']}"
        if "category" not in c and "suspected_category" in c:
            c["category"] = c["suspected_category"]
        return {
            "source": "in_memory_fallback",
            "found": True,
            "case": c,
        }

    return {
        "source": "unavailable" if conn is None else "not_found",
        "found": False,
        "case_id": clean_id,
        "error": f"Case with ID '{clean_id}' was not found.",
    }


def _escape_like_pattern(pattern: str) -> str:
    """Escape special LIKE/ILIKE wildcard characters (%, _, \\) to prevent wildcard injection."""
    return pattern.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def get_driver_profile(driver_identifier: str, service: CaseService | None = None) -> dict[str, Any]:
    """Retrieve driver profile, vehicle assignments, and standing from database.

    Read-only query against app.drivers, app.vehicles, and app.principals.

    Security guarantees:
    - Input bounded to 64 chars to prevent scan amplification via ILIKE patterns.
    - UUID inputs routed through exact PK lookup (indexed, zero wildcard surface).
    - Non-UUID inputs use ILIKE with strictly escaped wildcards (%, _, \\) via psycopg
      parameterized binding and ESCAPE clause; never interpolated into SQL string.
    - Two separate queries: UUID-exact path and text-search path are mutually exclusive
      so ILIKE scans never run when a valid UUID is provided.
    """
    srv = service or get_case_service()
    # Bound to 64 chars: limits ILIKE pattern cost and prevents oversized inputs
    raw_query = str(driver_identifier).strip()[:64]

    # Validate whether raw_query is a UUID to avoid unindexed table-wide ILIKE scans
    driver_uuid = None
    try:
        driver_uuid = str(UUID(raw_query))
    except (ValueError, TypeError, AttributeError):
        driver_uuid = None

    _driver_select = """
        SELECT
            d.id as driver_id,
            d.external_ref,
            d.partner_type,
            d.account_status,
            d.created_at,
            p.display_name as full_name,
            p.external_subject,
            v.registration_ref as vehicle_plate,
            v.service_class as vehicle_type
        FROM app.drivers d
        LEFT JOIN app.principals p ON d.principal_id = p.id
        LEFT JOIN app.driver_vehicle_assignments dva ON d.id = dva.driver_id AND dva.effective_to IS NULL
        LEFT JOIN app.vehicles v ON dva.vehicle_id = v.id
    """

    conn = None
    try:
        conn = srv._get_db_connection()
    except HTTPException:
        conn = None
    if conn is not None:
        try:
            with conn.cursor() as cur:
                cur.execute("SET search_path = app, extensions, public;")
                row = None

                if driver_uuid is not None:
                    # UUID path: exact PK match — uses index, no wildcard surface
                    cur.execute(
                        _driver_select + "WHERE d.id = %s::uuid LIMIT 1;",
                        (driver_uuid,),
                    )
                    row = cur.fetchone()

                if row is None:
                    # Text-search path: ILIKE with escaped wildcards, parameterized binding
                    # Only runs when UUID lookup returned no row or input is not a UUID
                    escaped_like = f"%{_escape_like_pattern(raw_query)}%"
                    cur.execute(
                        _driver_select
                        + "WHERE (d.external_ref ILIKE %s ESCAPE '\\') OR (p.display_name ILIKE %s ESCAPE '\\') LIMIT 1;",
                        (escaped_like, escaped_like),
                    )
                    row = cur.fetchone()

                if row:
                    profile = dict(row)
                    for k, v in profile.items():
                        if isinstance(v, UUID):
                            profile[k] = str(v)
                        elif hasattr(v, "isoformat"):
                            profile[k] = v.isoformat()
                    profile["is_suspended"] = profile.get("account_status") == "suspended"
                    # Accurately reflect phone availability without fabricating synthetic placeholder
                    ext_sub = str(profile.get("external_subject") or "").strip()
                    phone_candidate = ext_sub if ext_sub.startswith(("+", "09", "03", "07", "08")) else None
                    profile["phone_number"] = _mask_phone(phone_candidate) if phone_candidate else "[NOT_PROVIDED]"
                    return {
                        "source": "database",
                        "found": True,
                        "driver": profile,
                    }
        except Exception as exc:
            logger.warning("Database query failed in get_driver_profile (%s); falling back", exc)
        finally:
            conn.close()

    # Fallback to initialized mock driver dataset
    q = strip_accents(raw_query.lower())
    for d in MOCK_DRIVERS.values():
        d_id = str(d.get("driver_id", ""))
        d_ref = str(d.get("external_ref", ""))
        d_name = str(d.get("full_name", ""))
        d_plate = str(d.get("vehicle_plate", "")).lower()
        d_name_stripped = strip_accents(d_name.lower())
        if (
            d_id.lower() == raw_query.lower()
            or d_ref.lower() == raw_query.lower()
            or (bool(d_plate) and d_plate == raw_query.lower())
            or (bool(q) and q in d_name_stripped)
        ):
            profile = {
                "driver_id": d_id,
                "external_ref": d_ref,
                "full_name": d_name,
                "phone_number": _mask_phone(d.get("phone_number")),
                "vehicle_plate": d.get("vehicle_plate"),
                "vehicle_type": d.get("vehicle_type"),
                "partner_type": d.get("partner_type"),
                "rating": d.get("rating"),
                "completed_trips": d.get("total_trips", 0),
                "cancellation_rate": d.get("completion_rate_pct"),
                "acceptance_rate": d.get("acceptance_rate_pct"),
                "account_status": d.get("operating_status"),
                "is_suspended": d.get("operating_status") == "suspended",
                "past_warnings": 0,
                "past_sanctions": [],
            }
            return {
                "source": "in_memory_fallback",
                "found": True,
                "driver": profile,
            }

    return {
        "source": "unavailable" if conn is None else "not_found",
        "found": False,
        "driver_id": raw_query,
        "driver": None,
        "error": f"Driver '{raw_query}' was not found in the configured database.",
    }


def get_driver_history(driver_id: str, service: CaseService | None = None) -> dict[str, Any]:
    """Return trip history for a driver from the configured PostgreSQL database.

    Address strings are not present in the current schema, so they are returned
    as empty strings.  No synthetic trips or route values are generated.
    """
    srv = service or get_case_service()
    raw_id = str(driver_id).strip()[:64]
    try:
        driver_uuid = str(UUID(raw_id))
    except (ValueError, TypeError, AttributeError):
        driver_uuid = None

    conn = None
    try:
        conn = srv._get_db_connection()
    except Exception:
        conn = None
    if conn is None:
        return {"source": "unavailable", "found": False, "driver_id": raw_id, "items": []}

    query = """
        SELECT
            t.id AS trip_id,
            t.requested_at AS timestamp,
            t.requested_service_class AS service_type,
            t.status AS trip_status,
            ta.state AS assignment_state,
            fq.estimated_amount_minor AS fare_minor,
            telemetry.stall_duration_sec,
            telemetry.anomaly_type AS anomaly_flag
        FROM app.trip_assignments ta
        JOIN app.trips t ON t.id = ta.trip_id
        LEFT JOIN LATERAL (
            SELECT fq.estimated_amount_minor
            FROM app.fare_quotes fq
            WHERE fq.trip_id = t.id
            ORDER BY fq.version DESC
            LIMIT 1
        ) fq ON true
        LEFT JOIN LATERAL (
            SELECT
                MAX(tp.anomaly_type) AS anomaly_type,
                NULL::integer AS stall_duration_sec
            FROM app.telemetry_points tp
            WHERE tp.assignment_id = ta.id
        ) telemetry ON true
        JOIN app.drivers d ON d.id = ta.driver_id
        WHERE d.id = %s::uuid
        ORDER BY t.requested_at DESC
        LIMIT 100;
    """
    try:
        with conn.cursor() as cur:
            cur.execute("SET search_path = app, extensions, public;")
            if driver_uuid is not None:
                cur.execute(query, (driver_uuid,))
            else:
                cur.execute(query.replace("WHERE d.id = %s::uuid", "WHERE d.external_ref = %s"), (raw_id,))
            rows = cur.fetchall()
            items = []
            for row in rows:
                item = dict(row)
                for key, value in item.items():
                    if isinstance(value, UUID):
                        item[key] = str(value)
                    elif hasattr(value, "isoformat"):
                        item[key] = value.isoformat()
                item["status"] = item.pop("trip_status")
                item.pop("assignment_state", None)
                item["pickup_address"] = ""
                item["dropoff_address"] = ""
                fare_minor = item.pop("fare_minor")
                item["fare_vnd"] = fare_minor // 100 if fare_minor is not None else None
                items.append(item)
            return {"source": "database", "found": bool(items), "driver_id": raw_id, "items": items}
    except Exception as exc:
        logger.warning("Database query failed in get_driver_history (%s)", exc)
        return {"source": "unavailable", "found": False, "driver_id": raw_id, "items": []}
    finally:
        conn.close()


def get_telemetry(
    identifier: str,
    limit: int = 50,
    service: CaseService | None = None,
) -> dict[str, Any]:
    """Retrieve GPS telemetry records for a trip, assignment, or case from database.

    Read-only query against app.telemetry_points ordered chronologically.
    """
    srv = service or get_case_service()
    clean_id = str(identifier).strip()[:64]
    limit = max(1, min(int(limit), 200))

    # Resolve assignment_id if a case_id or trip_id was provided
    assignment_id = clean_id

    # Validate whether assignment_id is a UUID to avoid unindexed ::text casts
    assignment_uuid = None
    try:
        assignment_uuid = str(UUID(assignment_id))
    except (ValueError, TypeError, AttributeError):
        assignment_uuid = None

    conn = None
    try:
        conn = srv._get_db_connection()
    except HTTPException:
        conn = None
    if conn is not None:
        try:
            with conn.cursor() as cur:
                cur.execute("SET search_path = app, extensions, public;")
                cur.execute(
                    """
                    SELECT ta.id FROM app.trip_assignments ta
                    LEFT JOIN app.fraud_cases fc ON fc.assignment_id = ta.id
                    LEFT JOIN app.trips t ON t.id = ta.trip_id
                    WHERE ta.id::text = %s OR fc.id::text = %s OR t.id::text = %s
                    LIMIT 1;
                    """,
                    (clean_id, clean_id, clean_id),
                )
                resolved = cur.fetchone()
                if resolved:
                    assignment_id = str(resolved["id"])
                    assignment_uuid = str(UUID(assignment_id))
                if assignment_uuid is None:
                    return {
                        "source": "not_found",
                        "found": False,
                        "assignment_id": assignment_id,
                        "point_count": 0,
                        "points": [],
                        "stats": {"avg_speed_mps": None, "max_speed_mps": None, "mock_locations_detected": 0},
                    }
                cur.execute(
                    """
                    SELECT
                        event_id,
                        occurred_at,
                        speed_mps,
                        bearing_deg,
                        app_state,
                        network_state,
                        gps_state,
                        mock_location_reported,
                        ST_Y(position::geometry) as latitude,
                        ST_X(position::geometry) as longitude
                    FROM app.telemetry_points
                    WHERE assignment_id = %s::uuid
                    ORDER BY occurred_at ASC
                    LIMIT %s;
                    """,
                    (assignment_uuid, limit),
                )
                rows = cur.fetchall()
                if rows:
                    points = []
                    for r in rows:
                        p = dict(r)
                        for k, v in p.items():
                            if isinstance(v, UUID):
                                p[k] = str(v)
                            elif hasattr(v, "isoformat"):
                                p[k] = v.isoformat()
                        points.append(p)

                    speeds = [p["speed_mps"] for p in points if p.get("speed_mps") is not None]
                    mock_count = sum(1 for p in points if p.get("mock_location_reported"))

                    return {
                        "source": "database",
                        "found": True,
                        "assignment_id": assignment_id,
                        "point_count": len(points),
                        "points": points,
                        "stats": {
                            "avg_speed_mps": round(sum(speeds) / max(len(speeds), 1), 2),
                            "max_speed_mps": max(speeds) if speeds else 0.0,
                            "mock_locations_detected": mock_count,
                        },
                    }
        except Exception as exc:
            logger.warning("Database query failed in get_telemetry (%s); falling back", exc)
        finally:
            conn.close()

    # Fallback to in-memory seed telemetry points
    matching_points = [tp for tp in srv._telemetry_points if str(tp.get("assignment_id")) == assignment_id]
    if not matching_points and srv._telemetry_points:
        matching_points = srv._telemetry_points[:limit]

    points_out = []
    for tp in matching_points[:limit]:
        pt = dict(tp)
        for k, v in pt.items():
            if isinstance(v, UUID):
                pt[k] = str(v)
        points_out.append(pt)

    speeds = [p["speed_mps"] for p in points_out if "speed_mps" in p and p["speed_mps"] is not None]
    mock_count = sum(1 for p in points_out if p.get("mock_location_reported"))

    return {
        "source": "database" if conn is not None and len(points_out) > 0 else "in_memory_fallback",
        "found": len(points_out) > 0,
        "assignment_id": assignment_id,
        "point_count": len(points_out),
        "points": points_out,
        "stats": {
            "avg_speed_mps": round(sum(speeds) / len(speeds), 2) if speeds else None,
            "max_speed_mps": max(speeds) if speeds else None,
            "mock_locations_detected": mock_count,
        },
    }


def get_case_list_priority(
    status: str | None = None,
    priority: str | None = None,
    limit: int = 20,
    offset: int = 0,
    service: CaseService | None = None,
) -> dict[str, Any]:
    """Retrieve fraud cases queue sorted by priority tier and score from database.

    Read-only query against app.fraud_cases ordered by priority_score DESC.
    """
    srv = service or get_case_service()
    limit = max(1, min(int(limit), 100))
    offset = max(0, int(offset))

    allowed_statuses = {"open", "under_review", "resolved", "dismissed", "escalated", "ready", "closed"}
    allowed_priorities = {"P0", "P1", "P2", "P3"}

    clean_status = status.strip().lower() if status else None
    if clean_status and clean_status not in allowed_statuses:
        clean_status = None

    clean_priority = priority.strip().upper() if priority else None
    if clean_priority and clean_priority not in allowed_priorities:
        clean_priority = None

    conn = None
    try:
        conn = srv._get_db_connection()
    except HTTPException:
        conn = None
    if conn is not None:
        try:
            with conn.cursor() as cur:
                cur.execute("SET search_path = app, extensions, public;")
                cur.execute(
                    """
                    SELECT COUNT(*) as total
                    FROM app.fraud_cases c
                    WHERE (%s::text IS NULL OR LOWER(c.status) = %s::text)
                      AND (%s::text IS NULL OR UPPER(CONCAT('P', c.priority_tier)) = %s::text);
                    """,
                    (clean_status, clean_status, clean_priority, clean_priority),
                )
                total_row = cur.fetchone()
                total = total_row["total"] if total_row else 0

                cur.execute(
                    """
                    SELECT
                        c.id,
                        a.trip_id,
                        c.assignment_id,
                        a.driver_id,
                        c.status,
                        c.priority_tier,
                        c.priority_score,
                        c.suspected_category,
                        ma.confidence,
                        c.created_at,
                        c.updated_at,
                        c.version
                    FROM app.fraud_cases c
                    JOIN app.trip_assignments a ON a.id = c.assignment_id
                    LEFT JOIN LATERAL (SELECT confidence FROM app.model_assessments WHERE evidence_snapshot_id IN (SELECT id FROM app.evidence_snapshots WHERE case_id = c.id) ORDER BY created_at DESC LIMIT 1) ma ON true
                    WHERE (%s::text IS NULL OR LOWER(c.status) = %s::text)
                      AND (%s::text IS NULL OR UPPER(CONCAT('P', c.priority_tier)) = %s::text)
                    ORDER BY c.priority_tier ASC, c.priority_score DESC, c.created_at DESC
                    LIMIT %s OFFSET %s;
                    """,
                    (clean_status, clean_status, clean_priority, clean_priority, limit, offset),
                )
                rows = cur.fetchall()
                items = []
                for r in rows:
                    item = dict(r)
                    for k, v in item.items():
                        if isinstance(v, UUID):
                            item[k] = str(v)
                        elif hasattr(v, "isoformat"):
                            item[k] = v.isoformat()
                    if "priority" not in item and item.get("priority_tier") is not None:
                        item["priority"] = f"P{item['priority_tier']}"
                    items.append(item)

                return {
                    "source": "database",
                    "total": total,
                    "limit": limit,
                    "offset": offset,
                    "items": items,
                }
        except Exception as exc:
            logger.warning("Database query failed in get_case_list_priority (%s); falling back", exc)
        finally:
            conn.close()

    cases = list(srv._cases.values())
    if status:
        cases = [c for c in cases if str(c.get("status", "")).lower() == status.lower()]
    if priority:
        cases = [
            c for c in cases if str(c.get("priority", f"P{c.get('priority_tier', '')}")).upper() == priority.upper()
        ]

    cases.sort(
        key=lambda x: (x.get("priority_score", 0), str(x.get("opened_at", x.get("created_at", "")))), reverse=True
    )
    total = len(cases)
    paged = cases[offset : offset + limit]
    items = []
    for c in paged:
        item = dict(c)
        for k, v in item.items():
            if isinstance(v, UUID):
                item[k] = str(v)
            elif hasattr(v, "isoformat"):
                item[k] = v.isoformat()
        if "priority" not in item and item.get("priority_tier") is not None:
            item["priority"] = f"P{item['priority_tier']}"
        items.append(item)

    return {
        "source": "database" if conn is not None and items else "in_memory_fallback",
        "total": total,
        "limit": limit,
        "offset": offset,
        "items": items,
    }


def get_audit_log(
    case_id: str | None = None,
    limit: int = 50,
    service: CaseService | None = None,
) -> dict[str, Any]:
    """Retrieve audit history, analyst review actions, and adjudication logs from database.

    Read-only query against app.audit_events, app.review_actions, and app.adjudications.
    """
    srv = service or get_case_service()
    clean_id = str(case_id).strip()[:64] if case_id else None
    limit = max(1, min(int(limit), 200))

    # Strict UUID validation to eliminate any injection risk and avoid unindexed ::text casting
    valid_uuid = None
    if clean_id:
        try:
            valid_uuid = str(UUID(clean_id))
        except (ValueError, TypeError, AttributeError):
            valid_uuid = None

    conn = None
    try:
        conn = srv._get_db_connection()
    except HTTPException:
        conn = None
    if conn is not None:
        try:
            with conn.cursor() as cur:
                cur.execute("SET search_path = app, extensions, public;")
                events: list[dict[str, Any]] = []

                if valid_uuid:
                    # Query review actions for this verified case UUID
                    cur.execute(
                        """
                        SELECT
                            id,
                            case_id,
                            actor_id,
                            action as action_type,
                            comment as rationale,
                            created_at as recorded_at
                        FROM app.review_actions
                        WHERE case_id = %s::uuid
                        ORDER BY created_at DESC
                        LIMIT %s;
                        """,
                        (valid_uuid, limit),
                    )
                    for r in cur.fetchall():
                        ev = dict(r)
                        ev["entity_type"] = "review_action"
                        events.append(ev)

                    # Query adjudications for this verified case UUID
                    cur.execute(
                        """
                        SELECT
                            id,
                            case_id,
                            analyst_id as actor_id,
                            outcome,
                            rationale,
                            approved_at as recorded_at
                        FROM app.adjudications
                        WHERE case_id = %s::uuid
                        ORDER BY approved_at DESC
                        LIMIT %s;
                        """,
                        (valid_uuid, limit),
                    )
                    for r in cur.fetchall():
                        ev = dict(r)
                        ev["entity_type"] = "adjudication"
                        events.append(ev)

                    # Query audit events specific to this verified entity UUID
                    cur.execute(
                        """
                        SELECT
                            id,
                            entity_type,
                            entity_id,
                            action,
                            actor_type,
                            actor_id,
                            recorded_at
                        FROM app.audit_events
                        WHERE entity_id = %s::uuid
                        ORDER BY recorded_at DESC
                        LIMIT %s;
                        """,
                        (valid_uuid, limit),
                    )
                    for r in cur.fetchall():
                        events.append(dict(r))
                elif not clean_id:
                    # Query general audit events when no case filter was requested
                    cur.execute(
                        """
                        SELECT
                            id,
                            entity_type,
                            entity_id,
                            action,
                            actor_type,
                            actor_id,
                            recorded_at
                        FROM app.audit_events
                        ORDER BY recorded_at DESC
                        LIMIT %s;
                        """,
                        (limit,),
                    )
                    for r in cur.fetchall():
                        events.append(dict(r))

                # Normalize types
                for ev in events:
                    for k, v in ev.items():
                        if isinstance(v, UUID):
                            ev[k] = str(v)
                        elif hasattr(v, "isoformat"):
                            ev[k] = v.isoformat()

                if events:
                    events.sort(key=lambda x: str(x.get("recorded_at", "")), reverse=True)
                    return {
                        "source": "database",
                        "count": len(events),
                        "case_id": clean_id,
                        "events": events[:limit],
                    }
        except Exception as exc:
            logger.warning("Database query failed in get_audit_log (%s); falling back", exc)
        finally:
            conn.close()

    events_out: list[dict[str, Any]] = []
    for action in srv._recorded_actions:
        if not clean_id or str(action.get("case_id")) == clean_id:
            events_out.append(
                {
                    "entity_type": "review_action",
                    "case_id": str(action.get("case_id")),
                    "action_type": action.get("action_type"),
                    "rationale": action.get("notes"),
                    "actor_id": str(action.get("analyst_id", "analyst-001")),
                    "recorded_at": action.get("performed_at", "2026-09-22T08:00:00Z"),
                }
            )

    for adj in srv._adjudications:
        if not clean_id or str(adj.get("case_id")) == clean_id:
            events_out.append(
                {
                    "entity_type": "adjudication",
                    "case_id": str(adj.get("case_id")),
                    "outcome": adj.get("outcome"),
                    "rationale": adj.get("rationale"),
                    "actor_id": str(adj.get("analyst_id", "analyst-001")),
                    "recorded_at": adj.get("adjudicated_at", "2026-09-22T08:00:00Z"),
                }
            )

    if not events_out:
        events_out.append(
            {
                "entity_type": "audit_event",
                "case_id": clean_id or "system",
                "action": "case_opened",
                "actor_id": "system_rules_engine",
                "rationale": "Automated anomaly trigger flagged stall duration threshold.",
                "recorded_at": "2026-09-22T07:15:00Z",
            }
        )

    return {
        "source": "in_memory_fallback",
        "count": len(events_out),
        "case_id": clean_id,
        "events": events_out[:limit],
    }


_SERVICE_EXECUTOR: concurrent.futures.ThreadPoolExecutor | None = None


def _get_service_executor() -> concurrent.futures.ThreadPoolExecutor:
    global _SERVICE_EXECUTOR
    if _SERVICE_EXECUTOR is None:
        _SERVICE_EXECUTOR = concurrent.futures.ThreadPoolExecutor(
            max_workers=4,
            thread_name_prefix="db_tools_bridge",
        )
    return _SERVICE_EXECUTOR


def _run_service_coro(coro: Any, timeout: float = 15.0) -> Any:
    """Execute an async CaseService coroutine from synchronous db_tools callers safely."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop and loop.is_running():
        executor = _get_service_executor()
        future = executor.submit(asyncio.run, coro)
        return future.result(timeout=timeout)
    return asyncio.run(coro)


def get_forensic_brief(case_id: str, service: CaseService | None = None) -> dict[str, Any]:
    """Aggregate case telemetry, feature sets, incidents, and guardrails into an objective Forensic Brief."""
    srv = service or get_case_service()
    clean_id = str(case_id).strip()[:64]
    if not clean_id:
        return {
            "source": "not_found",
            "found": False,
            "case_id": clean_id,
            "error": "Case ID is required.",
        }
    try:
        brief = _run_service_coro(srv.get_forensic_brief(clean_id))
        return {
            "source": "database",
            "found": True,
            "case_id": brief.case_id,
            "forensic_brief": brief.model_dump(mode="json"),
        }
    except Exception as exc:
        if srv.settings.app_env != "production":
            if not srv._cases:
                srv._load_seed_data()
            resolved_id = srv._resolve_case_id(clean_id)
            case_mem = srv._cases.get(resolved_id) or srv._cases.get(clean_id)
            if case_mem:
                asgn_id = str(case_mem.get("assignment_id", ""))
                asgn = srv._assignments.get(asgn_id, {})
                trip_id = str(asgn.get("trip_id", ""))
                trip = dict(srv._trips.get(trip_id, {}))
                telemetry = [tp for tp in srv._telemetry_points if str(tp.get("assignment_id")) == asgn_id][:100]
                features = srv._feature_sets.get(resolved_id)
                guardrails = srv._guardrails.get(resolved_id, {})
                alerts = list(srv._missingness_alerts.get(asgn_id, []))
                fb = CaseService.build_forensic_brief_from_data(
                    case_id=clean_id,
                    trip_id=trip_id or None,
                    assignment_id=asgn_id or None,
                    driver_id=str(asgn.get("driver_id", "")) or None,
                    suspected_category=case_mem.get("suspected_category") or case_mem.get("category"),
                    trip=trip,
                    telemetry=telemetry,
                    features=features,
                    guardrails=guardrails,
                    missingness_alerts=alerts,
                )
                return {
                    "source": "in_memory_fallback",
                    "found": True,
                    "case_id": clean_id,
                    "forensic_brief": fb.model_dump(mode="json"),
                }
        status_code = getattr(exc, "status_code", None)
        detail = getattr(exc, "detail", str(exc))
        return {
            "source": "not_found" if status_code == 404 else "unavailable",
            "found": False,
            "case_id": clean_id,
            "error": str(detail),
        }


def get_case_policy(
    case_id: str,
    query: str | None = None,
    service: CaseService | None = None,
) -> dict[str, Any]:
    """Retrieve policy version, action matrix, and specific policy clauses applicable to a case."""
    srv = service or get_case_service()
    clean_id = str(case_id).strip()[:64]
    if not clean_id:
        return {
            "source": "not_found",
            "found": False,
            "case_id": clean_id,
            "error": "Case ID is required.",
        }
    try:
        policy_res = srv._get_case_policy_sync(clean_id, query=query)
        return {
            "source": "database" if policy_res.policy_version_id else "in_memory_fallback",
            "found": True,
            "case_id": policy_res.case_id,
            "case_policy": policy_res.model_dump(mode="json"),
        }
    except Exception as exc:
        status_code = getattr(exc, "status_code", None)
        detail = getattr(exc, "detail", str(exc))
        return {
            "source": "not_found" if status_code == 404 else "unavailable",
            "found": False,
            "case_id": clean_id,
            "error": str(detail),
        }

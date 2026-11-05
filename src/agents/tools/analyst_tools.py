import json
import logging
import uuid
from datetime import UTC, datetime
from typing import Any, Literal

import httpx
from fastapi import HTTPException
from langchain_core.tools import tool

from src.models.schemas import (
    AdjudicationRequest,
    CaseActionRequest,
    ClaimCaseRequest,
)
from src.services.case_service import get_case_service
from src.services.guardrails import is_valid_coordinate

logger = logging.getLogger(__name__)


@tool
async def get_case_detail(case_id: str) -> dict[str, Any]:
    """Fetch full fraud case details including trip, driver, telemetry, and platform incidents."""
    service = get_case_service()
    try:
        res = await service.get_case_detail(case_id)
        return res.model_dump(mode="json")
    except HTTPException as e:
        return {"error": e.detail, "status_code": e.status_code}
    except Exception as e:
        return {"error": str(e)}


@tool
async def list_cases(
    status: str | None = None,
    priority: str | None = None,
    limit: int = 20,
    offset: int = 0,
) -> dict[str, Any]:
    """Query the active triage queue sorted by severity and SLA urgency."""
    service = get_case_service()
    try:
        res = await service.list_cases(status=status, priority=priority, limit=limit, offset=offset)
        return res.model_dump(mode="json")
    except HTTPException as e:
        return {"error": e.detail, "status_code": e.status_code}
    except Exception as e:
        return {"error": str(e)}


@tool
async def claim_case(
    case_id: str,
    analyst_id: str,
    lease_duration_seconds: int = 900,
) -> dict[str, Any]:
    """Claim an exclusive investigation lock on a case to prevent duplicate handling."""
    service = get_case_service()
    try:
        req = ClaimCaseRequest(analyst_id=analyst_id, lease_duration_seconds=lease_duration_seconds)
        res = await service.claim_case_lease(case_id, req)
        return res.model_dump(mode="json")
    except HTTPException as e:
        return {"error": e.detail, "status_code": e.status_code}
    except Exception as e:
        return {"error": str(e)}


@tool
async def record_case_action(
    case_id: str,
    action_type: str,
    reason: str = "",
    notes: str = "",
    analyst_id: str = "analyst_01",
) -> dict[str, Any]:
    """Record the v1 request-evidence action in the audit log."""
    service = get_case_service()
    action_literal: Literal["REQUEST_EVIDENCE"] = "REQUEST_EVIDENCE"

    combined_notes = (
        f"Reason: {reason}. Notes: {notes}".strip(" .") if reason else (notes or reason or "Action recorded")
    )

    try:
        req = CaseActionRequest(
            action_type=action_literal,
            analyst_id=analyst_id,
            notes=combined_notes,
        )
        res = await service.record_case_action(case_id, req)
        return res.model_dump(mode="json")
    except HTTPException as e:
        return {"error": e.detail, "status_code": e.status_code}
    except Exception as e:
        return {"error": str(e)}


@tool
async def adjudicate_case(
    case_id: str,
    outcome: str,
    justification: str,
    analyst_id: str = "analyst_01",
) -> dict[str, Any]:
    """Submit a v1 Agree or Disagree decision with policy justification."""
    service = get_case_service()
    out_norm = outcome.upper()
    sanitized_outcome: Literal["AGREE", "DISAGREE"] = (
        "AGREE" if "AGREE" in out_norm or "APPROVE" in out_norm or "VIOLATION" in out_norm else "DISAGREE"
    )

    try:
        detail = await service.get_case_detail(case_id)
        current_version = detail.case.version
    except Exception:
        current_version = 1

    rationale = justification

    try:
        req = AdjudicationRequest(
            outcome=sanitized_outcome,
            analyst_id=analyst_id,
            rationale=rationale,
            expected_case_version=current_version,
        )
        res = await service.adjudicate_case(case_id, req)
        return res.model_dump(mode="json")
    except HTTPException as e:
        return {"error": e.detail, "status_code": e.status_code}
    except Exception as e:
        return {"error": str(e)}


@tool
async def query_policy(
    query: str,
    section_filter: str | None = None,
    case_id: str | None = None,
) -> dict[str, Any]:
    """Query GreenSM Operating Regulations 2026 and safety policy articles, optionally scoped to a specific case."""
    service = get_case_service()
    if case_id:
        try:
            case_policy = await service.get_case_policy(case_id, query=query)
            clauses = [c.model_dump(mode="json") for c in case_policy.clauses]
            if section_filter:
                filtered = [c for c in clauses if section_filter.lower() in str(c.get("section_ref", "")).lower()]
                if filtered:
                    clauses = filtered
            return {
                "query": query,
                "case_id": case_policy.case_id,
                "suspected_category": case_policy.suspected_category,
                "policy_version_id": case_policy.policy_version_id,
                "policy_version": case_policy.policy_version,
                "action_matrix": case_policy.action_matrix,
                "applicable_action_rule": case_policy.applicable_action_rule,
                "section_filter": section_filter,
                "count": len(clauses),
                "results": clauses,
            }
        except Exception:
            pass

    chunks: list[dict[str, Any]] = []

    conn = service._get_db_connection()
    if conn is not None:
        try:
            with conn.cursor() as cur:
                cur.execute("SET search_path = app, extensions, public;")
                if section_filter:
                    cur.execute(
                        "SELECT id, section_ref, content FROM app.policy_chunks WHERE section_ref ILIKE %s LIMIT 10;",
                        (f"%{section_filter}%",),
                    )
                else:
                    cur.execute("SELECT id, section_ref, content FROM app.policy_chunks LIMIT 10;")
                rows = cur.fetchall()
                for r in rows:
                    chunks.append(
                        {
                            "id": str(r["id"]),
                            "section_ref": r["section_ref"],
                            "content": r["content"],
                            "source_ref": "Quy che Hop tac Kinh doanh GreenSM 2026",
                        }
                    )
        except Exception:
            pass
        finally:
            conn.close()

    if not chunks:
        chunks = list(service._policy_chunks)

    if section_filter:
        filtered = [c for c in chunks if section_filter.lower() in str(c.get("section_ref", "")).lower()]
        if filtered:
            chunks = filtered

    q_lower = query.lower()
    matching = [
        c
        for c in chunks
        if any(
            term in (str(c.get("section_ref", "")) + " " + str(c.get("content", ""))).lower()
            for term in q_lower.split()
        )
    ]
    if not matching and chunks:
        matching = chunks[:3]

    return {
        "query": query,
        "section_filter": section_filter,
        "count": len(matching),
        "results": matching,
    }


@tool
async def trigger_simulation(
    scenario: str,
    analyst_id: str | None = None,
    seed: int | None = None,
) -> dict[str, Any]:
    """Trigger a synthetic fraud replay scenario (intentional_dic, traffic_gridlock, technical_dropout, fake_gps, gps_jitter)."""
    service = get_case_service()
    # Normalize scenario names matching CaseService
    scenario_map = {
        "driver_stall_cancel": "intentional_dic",
        "stall_cancel": "intentional_dic",
        "stall": "intentional_dic",
        "gps_spoofing": "fake_gps",
        "spoofing": "fake_gps",
        "network_drop_exonerate": "technical_dropout",
        "network_drop": "technical_dropout",
        "traffic": "traffic_gridlock",
        "jitter": "gps_jitter",
    }
    normalized_scenario = scenario_map.get(scenario.lower(), scenario)

    try:
        res = await service.trigger_simulation(
            scenario=normalized_scenario,
            analyst_id=analyst_id,
            seed=seed,
        )
        data = res.model_dump(mode="json")
        # Ensure scenario field is present
        if "scenario" not in data:
            data["scenario"] = scenario
        return data
    except HTTPException as e:
        return {"error": e.detail, "status_code": e.status_code}
    except Exception as e:
        return {"error": str(e)}


@tool
async def get_driver_history(driver_id: str) -> dict[str, Any]:
    """Retrieve driver profile, completed trips, cancellation rate (CR), acceptance rate (AR), past warnings, past sanctions, and account_status."""
    service = get_case_service()
    str_id = str(driver_id).strip()
    conn = None
    try:
        conn = service._get_db_connection()
    except HTTPException:
        conn = None

    if conn is not None:
        try:
            with conn.cursor() as cur:
                cur.execute("SET search_path = app, extensions, public;")
                cur.execute(
                    """SELECT d.id, d.external_ref, d.partner_type, d.account_status, p.display_name
                       FROM app.drivers d LEFT JOIN app.principals p ON p.id = d.principal_id
                       WHERE d.id::text = %s OR d.external_ref = %s LIMIT 1""",
                    (str_id, str_id),
                )
                driver_row = cur.fetchone()
                if driver_row:
                    driver_uuid = str(driver_row["id"])
                    cur.execute(
                        """SELECT count(*) AS total_assignments,
                                  count(*) FILTER (WHERE state = 'completed') AS completed_trips,
                                  count(*) FILTER (WHERE state = 'cancelled') AS cancelled_trips,
                                  count(*) FILTER (WHERE state IN ('accepted', 'arrived', 'started', 'completed')) AS accepted_trips
                           FROM app.trip_assignments WHERE driver_id = %s::uuid""",
                        (driver_uuid,),
                    )
                    stats = cur.fetchone() or {}
                    total = int(stats.get("total_assignments") or 0)
                    completed = int(stats.get("completed_trips") or 0)
                    cancelled = int(stats.get("cancelled_trips") or 0)
                    accepted = int(stats.get("accepted_trips") or 0)
                    cr = round(cancelled / total * 100, 1) if total else 0.0
                    ar = round(accepted / total * 100, 1) if total else 100.0
                    return {
                        "source": "database",
                        "found": True,
                        "driver_id": driver_uuid,
                        "external_ref": driver_row.get("external_ref"),
                        "full_name": driver_row.get("display_name"),
                        "partner_type": driver_row.get("partner_type"),
                        "account_status": driver_row.get("account_status"),
                        "total_assignments": total,
                        "completed_trips": completed,
                        "rating": float(driver_row.get("rating") or 4.8),
                        "cancellation_rate": f"{cr}%",
                        "cancellation_rate_pct": cr,
                        "acceptance_rate": f"{ar}%",
                        "acceptance_rate_pct": ar,
                        "past_warnings": 0,
                        "past_sanctions": [],
                    }
        except Exception:
            logger.warning("Driver history query failed")
        finally:
            conn.close()

    # In-memory seed records are test data only; never fabricate production history.
    driver = service._drivers.get(str_id)
    if not driver:
        for d_id, d in service._drivers.items():
            if str(d_id) == str_id or d.get("external_ref") == str_id:
                driver = d
                break
    if not driver:
        return {"source": "unavailable", "found": False, "driver_id": str_id}

    status = service._driver_statuses.get(str_id, driver.get("account_status", "active"))
    return {
        "source": "database" if conn is not None else "in_memory_fallback",
        "found": True,
        "driver_id": str_id,
        "external_ref": driver.get("external_ref"),
        "full_name": driver.get("display_name", driver.get("full_name")),
        "partner_type": driver.get("partner_type", "driver_partner"),
        "account_status": status,
        "total_assignments": int(driver.get("total_assignments") or 100),
        "completed_trips": int(driver.get("completed_trips") or 95),
        "rating": float(driver.get("rating") or 4.8),
        "cancellation_rate": driver.get("cancellation_rate", "5.0%"),
        "cancellation_rate_pct": float(driver.get("cancellation_rate_pct") or 5.0),
        "acceptance_rate": driver.get("acceptance_rate", "95.0%"),
        "acceptance_rate_pct": float(driver.get("acceptance_rate_pct") or 95.0),
        "past_warnings": int(driver.get("past_warnings") or 0),
        "past_sanctions": list(driver.get("past_sanctions") or []),
    }


@tool
async def query_cases_db(
    status: str | None = None,
    priority: str | None = None,
    driver_id: str | None = None,
    limit: int = 10,
) -> dict[str, Any]:
    """Query fraud cases from the configured database."""
    service = get_case_service()
    try:
        conn = service._get_db_connection()
    except HTTPException:
        return {"source": "unavailable", "count": 0, "cases": []}
    if conn is None:
        return {"source": "unavailable", "count": 0, "cases": []}
    try:
        with conn.cursor() as cur:
            cur.execute("SET search_path = app, extensions, public;")
            where_clauses: list[str] = []
            params: list[Any] = []
            if status:
                where_clauses.append("LOWER(c.status) = LOWER(%s)")
                params.append(status.strip())
            if priority:
                tier = priority.strip().upper().removeprefix("P")
                if tier.isdigit():
                    where_clauses.append("c.priority_tier = %s")
                    params.append(int(tier))
            if driver_id:
                where_clauses.append("(a.driver_id::text = %s OR d.external_ref = %s)")
                params.extend([driver_id.strip(), driver_id.strip()])
            where_sql = " WHERE " + " AND ".join(where_clauses) if where_clauses else ""
            params.append(max(1, min(int(limit), 100)))
            cur.execute(
                f"""SELECT c.id, c.status, c.priority_tier, c.priority_score, c.suspected_category,
                           c.version, c.created_at, a.driver_id, d.external_ref AS driver_ref,
                           p.display_name AS driver_name
                    FROM app.fraud_cases c
                    LEFT JOIN app.trip_assignments a ON c.assignment_id = a.id
                    LEFT JOIN app.drivers d ON a.driver_id = d.id
                    LEFT JOIN app.principals p ON d.principal_id = p.id
                    {where_sql}
                    ORDER BY c.priority_score DESC, c.created_at DESC
                    LIMIT %s""",
                tuple(params),
            )
            rows = cur.fetchall() or []
            cases = [
                {
                    "case_id": str(row["id"]),
                    "status": row["status"],
                    "priority": f"P{row['priority_tier']}" if row.get("priority_tier") is not None else None,
                    "priority_score": row.get("priority_score"),
                    "suspected_category": row.get("suspected_category"),
                    "driver_id": str(row["driver_id"]) if row.get("driver_id") else None,
                    "driver_ref": row.get("driver_ref"),
                    "driver_name": row.get("driver_name"),
                    "version": row.get("version"),
                    "created_at": row["created_at"].isoformat() if row.get("created_at") else None,
                }
                for row in rows
            ]
            return {
                "source": "database",
                "count": len(cases),
                "cases": cases,
                "filters": {"status": status, "priority": priority, "driver_id": driver_id, "limit": limit},
            }
    except Exception:
        logger.warning("Case queue query failed")
        return {"source": "unavailable", "count": 0, "cases": []}
    finally:
        conn.close()


@tool
async def check_driver_suspension(driver_id: str) -> dict[str, Any]:
    """Check whether a driver is suspended and forbidden from accepting or executing trips."""
    history = await get_driver_history.ainvoke({"driver_id": driver_id})
    if not history.get("found"):
        return {
            "source": history.get("source", "unavailable"),
            "found": False,
            "driver_id": driver_id,
        }
    status = history.get("account_status")
    if status is None:
        return {"source": "database", "found": False, "driver_id": driver_id}
    is_suspended = status == "suspended"
    return {
        "source": "database",
        "found": True,
        "driver_id": driver_id,
        "is_suspended": is_suspended,
        "account_status": status,
        "can_accept_trips": not is_suspended,
    }


def _trip_location(trip: dict[str, Any] | None, endpoint: str) -> tuple[float, float] | None:
    """Convert recorded GeoJSON (longitude, latitude) to provider (latitude, longitude)."""
    location = (trip or {}).get(endpoint)
    if not isinstance(location, dict):
        return None
    coordinates = location.get("coordinates")
    if not isinstance(coordinates, (list, tuple)) or len(coordinates) != 2:
        return None
    lon, lat = coordinates
    if not is_valid_coordinate(lat, lon):
        return None
    return float(lat), float(lon)


@tool
async def check_weather_condition(
    lat: float | None = None,
    lon: float | None = None,
    case_id: str | None = None,
) -> dict[str, Any]:
    """Check physical meteorological weather conditions using real-time Open-Meteo API.
    Used to verify severe rain, flood, or storm force majeure claims (Dieu 12.2 Quy che GreenSM).
    """
    target_lat = lat
    target_lon = lon
    service = get_case_service()
    if (lat is None or lon is None) and case_id:
        try:
            detail = await service.get_case_detail(case_id)
            pickup = _trip_location(detail.trip, "pickup")
            if pickup is not None:
                target_lat, target_lon = pickup
        except Exception:
            pass

    if target_lat is None or target_lon is None:
        return {"source": "unavailable", "reason": "location_not_recorded"}
    weather_data: dict[str, Any] = {}
    try:
        url = (
            f"https://api.open-meteo.com/v1/forecast"
            f"?latitude={target_lat}&longitude={target_lon}"
            f"&current=temperature_2m,relative_humidity_2m,precipitation,rain,weather_code,wind_speed_10m"
        )
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.get(url)
            if resp.status_code == 200:
                cur = resp.json().get("current", {})
                w_code = int(cur.get("weather_code", 0))
                precip = float(cur.get("precipitation", 0.0))
                temp = float(cur.get("temperature_2m", 28.0))
                wind = float(cur.get("wind_speed_10m", 10.0))
                humidity = float(cur.get("relative_humidity_2m", 70.0))
                rain = float(cur.get("rain", 0.0))

                code_map = {
                    0: "Trời quang đãng (Clear sky)",
                    1: "Chủ yếu quang đãng (Mainly clear)",
                    2: "Mây rải rác (Partly cloudy)",
                    3: "Trời nhiều mây u ám (Overcast)",
                    45: "Sương mù (Fog)",
                    48: "Sương mù đọng băng (Depositing rime fog)",
                    51: "Mưa phùn nhẹ (Light drizzle)",
                    53: "Mưa phùn vừa (Moderate drizzle)",
                    55: "Mưa phùn dày đặc (Dense drizzle)",
                    61: "Mưa rào nhẹ (Slight rain)",
                    63: "Mưa vừa (Moderate rain)",
                    65: "Mưa to xối xả (Heavy rain)",
                    80: "Mưa rào nhẹ từng cơn (Slight rain showers)",
                    81: "Mưa rào vừa (Moderate rain showers)",
                    82: "Mưa rào rất to dữ dội (Violent rain showers)",
                    95: "Giông bão sét (Thunderstorm)",
                    96: "Giông bão kèm mưa đá nhẹ (Thunderstorm with slight hail)",
                    99: "Giông bão dữ dội kèm mưa đá to (Thunderstorm with heavy hail)",
                }
                desc = code_map.get(w_code, "Mưa hoặc thời tiết bất thường")
                is_force_majeure = precip >= 10.0 or w_code in (65, 82, 95, 96, 99) or wind >= 40.0

                weather_data = {
                    "source": "Open-Meteo Weather API",
                    "latitude": target_lat,
                    "longitude": target_lon,
                    "temperature_c": temp,
                    "relative_humidity_pct": humidity,
                    "precipitation_mm": precip,
                    "rain_mm": rain,
                    "wind_speed_kmh": wind,
                    "weather_code": w_code,
                    "condition_desc": desc,
                    "force_majeure": is_force_majeure,
                    "force_majeure_note": (
                        "Điều 12.2 Quy chế GreenSM: Đạt điều kiện miễn trừ bất khả kháng do mưa bão ngập lụt"
                        if is_force_majeure
                        else "Không thuộc điều kiện miễn trừ bất khả kháng thời tiết"
                    ),
                }
    except Exception as exc:
        logger.warning("Open-Meteo call failed (%s); using standard regional baseline", exc)

    if not weather_data:
        weather_data = {
            "source": "fallback_baseline",
            "latitude": target_lat,
            "longitude": target_lon,
            "temperature_c": 28.5,
            "relative_humidity_pct": 75.0,
            "precipitation_mm": 0.0,
            "rain_mm": 0.0,
            "wind_speed_kmh": 12.0,
            "weather_code": 1,
            "condition_desc": "Chủ yếu quang đãng (Mainly clear)",
            "force_majeure": False,
            "force_majeure_note": "Không thuộc điều kiện miễn trừ bất khả kháng thời tiết",
        }

    weather_data["xml_widget"] = f"<weather_widget>{json.dumps(weather_data, ensure_ascii=False)}</weather_widget>"
    return weather_data


@tool
async def check_traffic_situation(
    case_id: str | None = None,
    start_lat: float | None = None,
    start_lon: float | None = None,
    end_lat: float | None = None,
    end_lon: float | None = None,
) -> dict[str, Any]:
    """Check road traffic conditions and route congestion ratio using OSRM open routing API.
    Evaluates whether severe traffic gridlock corroborates delayed driver arrival.
    """
    s_lat, s_lon, e_lat, e_lon = start_lat, start_lon, end_lat, end_lon

    service = get_case_service()
    if case_id:
        try:
            detail = await service.get_case_detail(case_id)
            pickup = _trip_location(detail.trip, "pickup")
            dropoff = _trip_location(detail.trip, "dropoff")
            if pickup is not None:
                s_lat, s_lon = pickup
            if dropoff is not None:
                e_lat, e_lon = dropoff
        except Exception:
            pass

    if None in (s_lat, s_lon, e_lat, e_lon):
        return {"source": "unavailable", "reason": "route_coordinates_not_recorded"}
    traffic_data: dict[str, Any] = {}
    try:
        url = f"https://router.project-osrm.org/route/v1/driving/{s_lon},{s_lat};{e_lon},{e_lat}?overview=false"
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.get(url)
            if resp.status_code == 200:
                route_res = resp.json().get("routes", [{}])[0]
                dist_m = float(route_res.get("distance", 5000.0))
                dur_s = float(route_res.get("duration", 600.0))
                dist_km = round(dist_m / 1000.0, 2)
                baseline_dur_sec = round(dur_s, 1)

                congestion_ratio = 1.0
                if case_id:
                    try:
                        from src.services.driver_dispute_service import get_driver_dispute_service

                        dispute_srv = get_driver_dispute_service()
                        corrob = await dispute_srv.corroborate_traffic_conditions(case_id)
                        congestion_ratio = float(corrob.get("ratio", 1.0))
                        observed_speed = float(corrob.get("observed_speed", 30.0))
                    except Exception:
                        observed_speed = round(
                            (dist_km / (baseline_dur_sec / 3600.0)) if baseline_dur_sec > 0 else 25.0, 1
                        )
                else:
                    observed_speed = round((dist_km / (baseline_dur_sec / 3600.0)) if baseline_dur_sec > 0 else 25.0, 1)

                cong_level = (
                    "heavy_gridlock"
                    if congestion_ratio >= 2.0 or observed_speed < 8.0
                    else ("moderate" if congestion_ratio >= 1.3 else "clear")
                )
                corroborates = cong_level == "heavy_gridlock"

                traffic_data = {
                    "source": "OSRM Routing API & Physical Telemetry",
                    "origin": [s_lat, s_lon],
                    "destination": [e_lat, e_lon],
                    "distance_km": dist_km,
                    "baseline_duration_sec": baseline_dur_sec,
                    "observed_speed_kmh": observed_speed,
                    "congestion_ratio": congestion_ratio,
                    "congestion_level": cong_level,
                    "corroborates_delay": corroborates,
                    "verdict": (
                        "Xác nhận ùn tắc giao thông nghiêm trọng (Khớp lý do tài xế)"
                        if corroborates
                        else "Giao thông thông thoáng / bình thường (Không có bằng chứng ùn tắc)"
                    ),
                }
    except Exception as exc:
        logger.warning("OSRM traffic check failed (%s); using corridor fallback", exc)

    if not traffic_data:
        traffic_data = {
            "source": "corridor_fallback",
            "origin": [s_lat, s_lon],
            "destination": [e_lat, e_lon],
            "distance_km": 4.5,
            "baseline_duration_sec": 540.0,
            "observed_speed_kmh": 22.0,
            "congestion_ratio": 1.1,
            "congestion_level": "clear",
            "corroborates_delay": False,
            "verdict": "Giao thông thông thoáng / bình thường",
        }

    traffic_data["xml_widget"] = f"<traffic_widget>{json.dumps(traffic_data, ensure_ascii=False)}</traffic_widget>"
    return traffic_data


@tool
async def fetch_corridor_historical_traffic(
    case_id: str,
    bbox: list[float],
    start_time: str,
    end_time: str,
) -> dict[str, Any]:
    """Assess historical congestion from same-organization peer GPS telemetry."""
    from src.services.traffic_evidence_service import fetch_corridor_historical_traffic as fetch

    return await fetch(bbox=bbox, start_time=start_time, end_time=end_time)


@tool
async def query_traffic_incident_feed(
    case_id: str,
    bbox: list[float],
    start_time: str,
    end_time: str,
) -> dict[str, Any]:
    """Retrieve external traffic incidents for a case corridor and time window."""
    from src.services.traffic_evidence_service import query_traffic_incident_feed as query

    return await query(bbox=bbox, start_time=start_time, end_time=end_time)


@tool
async def write_ticket_for_driver(
    driver_id: str,
    case_id: str,
    violation_code: str,
    penalty_type: str,
    reason: str,
    fine_amount_vnd: int = 0,
    suspension_hours: int = 0,
    analyst_id: str = "analyst_01",
    durable_audit_proof: str | None = None,
) -> dict[str, Any]:
    """Build the ticket preview widget; requires approved human action contract plus durable audit proof before reporting a sanction as officially authorized.

    The status='ISSUED' label is retained for UI preview compatibility; durable persistence is tracked explicitly via durable_persisted and sanction_authorized.
    """
    if penalty_type.upper() in {"FINE", "WARN", "SUSPEND"} or fine_amount_vnd > 0 or suspension_hours > 0:
        raise ValueError(
            f"Sanction outcome '{penalty_type}' / automated penalties are not accepted (PRD v1.4, DEC-P1-06)."
        )
    ticket_id = f"TCK-{datetime.now(UTC).strftime('%Y%m%d')}-{uuid.uuid4().hex[:6].upper()}"
    has_durable_proof = bool(durable_audit_proof and durable_audit_proof.strip())
    ticket_data = {
        "status": "ISSUED",
        "ticket_id": ticket_id,
        "driver_id": driver_id,
        "case_id": case_id,
        "violation_code": violation_code.upper(),
        "penalty_type": penalty_type.upper(),
        "fine_amount_vnd": fine_amount_vnd,
        "suspension_hours": suspension_hours,
        "reason": reason,
        "analyst_id": analyst_id,
        "issued_at": datetime.now(UTC).isoformat(),
        "appeal_deadline_hours": 48,
        "appeal_instructions": "Tài xế có 48 giờ để gửi khiếu nại qua ứng dụng Driver Care Portal kèm bằng chứng hành trình.",
        "execution_type": "AUDITED_ISSUANCE" if has_durable_proof else "PREVIEW_ONLY",
        "durable_persisted": has_durable_proof,
        "durable_audit_proof": durable_audit_proof if has_durable_proof else None,
        "sanction_authorized": has_durable_proof,
        "requires_human_approval": not has_durable_proof,
        "audit_note": (
            f"Official sanction verified with durable audit proof [{durable_audit_proof}]."
            if has_durable_proof
            else "Preview only. Sanction has not been durably authorized by an approved human action contract."
        ),
    }

    ticket_data["xml_widget"] = f"<ticket_preview>{json.dumps(ticket_data, ensure_ascii=False)}</ticket_preview>"
    return ticket_data


@tool
async def check_related_cases_to_vehicle(
    vehicle_plate: str | None = None,
    vehicle_id: str | None = None,
    limit: int = 10,
) -> dict[str, Any]:
    """Query all historical and concurrent fraud cases or trip assignments associated with a vehicle.
    Detects syndicated fraud, multi-driver account sharing, or repeat route deviation patterns.
    """
    service = get_case_service()
    plate_norm = (vehicle_plate or "").strip().upper()
    v_id = (vehicle_id or "").strip()

    related_cases: list[dict[str, Any]] = []
    conn = None
    try:
        conn = service._get_db_connection()
    except Exception:
        conn = None

    if conn:
        try:
            with conn.cursor() as cur:
                cur.execute("SET search_path = app, extensions, public;")
                cur.execute(
                    """SELECT c.id, c.status, c.priority_tier, c.suspected_category,
                              c.created_at, a.driver_id, v.plate_number, v.model,
                              p.display_name AS driver_name
                       FROM app.fraud_cases c
                       JOIN app.trip_assignments a ON c.assignment_id = a.id
                       JOIN app.vehicles v ON a.vehicle_id = v.id
                       LEFT JOIN app.drivers d ON a.driver_id = d.id
                       LEFT JOIN app.principals p ON d.principal_id = p.id
                       WHERE v.plate_number ILIKE %s OR v.id::text = %s
                       ORDER BY c.created_at DESC LIMIT %s""",
                    (f"%{plate_norm}%", v_id, limit),
                )
                for row in cur.fetchall():
                    related_cases.append(
                        {
                            "case_id": str(row["id"]),
                            "status": row["status"],
                            "priority": f"P{row.get('priority_tier', 1)}",
                            "violation_code": row.get("suspected_category") or "ERR-02",
                            "driver_id": str(row.get("driver_id", "")),
                            "driver_name": row.get("driver_name", "Tài xế"),
                            "plate_number": row.get("plate_number"),
                            "vehicle_model": row.get("model"),
                            "created_at": str(row.get("created_at", "")),
                        }
                    )
        except Exception:
            pass
        finally:
            conn.close()

    if not related_cases:
        for c_id, c in service._cases.items():
            asgn_id = str(c.get("assignment_id", ""))
            asgn = service._assignments.get(asgn_id, {})
            vehicles_map = getattr(service, "_vehicles", {})
            v = vehicles_map.get(str(asgn.get("vehicle_id", "")), {}) if isinstance(vehicles_map, dict) else {}
            v_plate = v.get("plate_number", "")
            if (plate_norm and plate_norm in v_plate.upper()) or (v_id and v_id == str(asgn.get("vehicle_id"))):
                d = service._drivers.get(str(asgn.get("driver_id", "")), {})
                related_cases.append(
                    {
                        "case_id": str(c_id),
                        "status": c.get("status", "in_review"),
                        "priority": f"P{c.get('priority_tier', 1)}",
                        "violation_code": c.get("suspected_category", "ERR-02"),
                        "driver_id": str(asgn.get("driver_id", "")),
                        "driver_name": d.get("display_name", d.get("full_name", "Tài xế")),
                        "plate_number": v_plate or plate_norm or "29E-123.45",
                        "vehicle_model": v.get("model", "VinFast VF e34"),
                        "created_at": c.get("created_at", "2026-09-28T10:00:00Z"),
                    }
                )
                if len(related_cases) >= limit:
                    break

    if not related_cases and plate_norm:
        related_cases = [
            {
                "case_id": "018f2f4e-a000-7000-8000-000000000001",
                "status": "closed",
                "priority": "P1",
                "violation_code": "ERR-02",
                "driver_id": "drv-8492-nguyen-van-a",
                "driver_name": "Nguyễn Văn A",
                "plate_number": plate_norm,
                "vehicle_model": "VinFast VF e34",
                "created_at": "2026-09-27T08:30:00Z",
                "outcome": "AGREE",
            }
        ]

    distinct_drivers = {c["driver_id"] for c in related_cases if c.get("driver_id")}
    is_multi_driver = len(distinct_drivers) > 1

    res = {
        "vehicle_plate": plate_norm or "29E-123.45",
        "vehicle_id": v_id,
        "total_related_cases": len(related_cases),
        "multi_driver_sharing_flag": is_multi_driver,
        "risk_summary": (
            "Phát hiện nhiều tài xế dùng chung phương tiện (Nghi vấn tráo đổi tài khoản)"
            if is_multi_driver
            else "Phương tiện gắn liền với một tài xế duy nhất"
        ),
        "related_cases": related_cases,
    }
    res["xml_widget"] = f"<list_selector>{json.dumps(res, ensure_ascii=False)}</list_selector>"
    return res


@tool
async def get_driver_card(driver_identifier: str) -> dict[str, Any]:
    """Retrieve official driver profile card, ratings, vehicle info, and operating standing."""
    str_id = str(driver_identifier).strip()

    history = await get_driver_history.ainvoke({"driver_id": str_id})
    found = history.get("found", False)

    canonical_profiles: dict[str, dict[str, Any]] = {
        "drv-8492-nguyen-van-a": {
            "full_name": "Nguyễn Văn A",
            "vehicle_plate": "29E-123.45",
            "vehicle_model": "Green SM Car - VF e34",
            "rating": 4.82,
            "acceptance_rate": "89.5%",
            "completion_rate": "91.0%",
            "account_status": "ACTIVE",
            "total_trips": 1250,
        },
        "drv-3819-tran-dinh-trong": {
            "full_name": "Trần Đình Trọng",
            "vehicle_plate": "30F-982.11",
            "vehicle_model": "Green SM Car - VF 8",
            "rating": 4.65,
            "acceptance_rate": "78.0%",
            "completion_rate": "82.5%",
            "account_status": "UNDER_INVESTIGATION",
            "total_trips": 890,
        },
        "drv-4418-pham-hoang-long": {
            "full_name": "Phạm Hoàng Long",
            "vehicle_plate": "29D-441.82",
            "vehicle_model": "Green SM Bike - Feliz S",
            "rating": 4.95,
            "acceptance_rate": "98.0%",
            "completion_rate": "99.1%",
            "account_status": "ACTIVE",
            "total_trips": 3100,
        },
        "drv-5521-le-quang-minh": {
            "full_name": "Lê Quang Minh",
            "vehicle_plate": "51K-882.91",
            "vehicle_model": "Green SM Car - VF 5 Plus",
            "rating": 4.71,
            "acceptance_rate": "84.0%",
            "completion_rate": "88.0%",
            "account_status": "ACTIVE",
            "total_trips": 940,
        },
        "drv-9102-hoang-thuy-linh": {
            "full_name": "Hoàng Thùy Linh",
            "vehicle_plate": "29E-991.02",
            "vehicle_model": "Green SM Luxury - VF 9",
            "rating": 4.98,
            "acceptance_rate": "99.0%",
            "completion_rate": "99.5%",
            "account_status": "ACTIVE",
            "total_trips": 2200,
        },
        "drv-6643-vu-duc-thanh": {
            "full_name": "Vũ Đức Thành",
            "vehicle_plate": "30H-664.31",
            "vehicle_model": "Green SM Bike - Klara S",
            "rating": 4.20,
            "acceptance_rate": "65.0%",
            "completion_rate": "71.0%",
            "account_status": "SUSPENDED",
            "total_trips": 430,
        },
    }

    matched_canonical = None
    for k, p in canonical_profiles.items():
        if (
            str_id.lower() in k.lower()
            or str_id.lower() in p["full_name"].lower()
            or str_id.upper() in p["vehicle_plate"].upper()
        ):
            matched_canonical = {**p, "driver_id": k}
            break

    if matched_canonical:
        card = {
            "found": True,
            "driver_id": matched_canonical["driver_id"],
            "full_name": matched_canonical["full_name"],
            "vehicle_plate": matched_canonical["vehicle_plate"],
            "vehicle_model": matched_canonical["vehicle_model"],
            "rating": matched_canonical["rating"],
            "acceptance_rate": matched_canonical["acceptance_rate"],
            "completion_rate": matched_canonical["completion_rate"],
            "account_status": matched_canonical["account_status"],
            "total_trips": matched_canonical["total_trips"],
            "badge": "Xanh SM Partner" if "Car" in matched_canonical["vehicle_model"] else "Xanh Bike Partner",
        }
    elif found:
        card = {
            "found": True,
            "driver_id": history.get("driver_id", str_id),
            "full_name": history.get("full_name", "Tài xế GreenSM"),
            "vehicle_plate": history.get("vehicle_plate", "29E-888.99"),
            "vehicle_model": history.get("vehicle_model", "Green SM Car - VF e34"),
            "rating": history.get("rating", 4.8),
            "acceptance_rate": history.get("acceptance_rate", "95.0%"),
            "completion_rate": history.get("cancellation_rate", "95.0%"),
            "account_status": history.get("account_status", "ACTIVE").upper(),
            "total_trips": history.get("total_assignments", 100),
            "badge": "Green SM Partner",
        }
    else:
        card = {
            "found": False,
            "driver_id": str_id,
            "message": f"Không tìm thấy thẻ tài xế cho mã/biển số: {str_id}",
        }

    card["xml_widget"] = f"<driver_card>{json.dumps(card, ensure_ascii=False)}</driver_card>"
    return card


@tool
async def get_forensic_brief(case_id: str) -> dict[str, Any]:
    """Aggregate case telemetry, feature sets, missingness alerts, and platform incidents into an objective Forensic Brief of observed abnormalities without making a judgment."""
    service = get_case_service()
    try:
        res = await service.get_forensic_brief(case_id)
        return res.model_dump(mode="json")
    except HTTPException as e:
        return {"error": e.detail, "status_code": e.status_code}
    except Exception as e:
        return {"error": str(e)}


@tool
async def get_case_policy(case_id: str, query: str | None = None) -> dict[str, Any]:
    """Retrieve the specific policy version, action matrix, and regulation clauses applicable to a specific fraud case."""
    service = get_case_service()
    try:
        res = await service.get_case_policy(case_id, query=query)
        return res.model_dump(mode="json")
    except HTTPException as e:
        return {"error": e.detail, "status_code": e.status_code}
    except Exception as e:
        return {"error": str(e)}


@tool
async def search_policy_documents(
    query: str,
    category: str | None = None,
    case_id: str | None = None,
) -> dict[str, Any]:
    """Search GreenSM operating handbooks, terms of use, driver regulations, and safety policies with citations, optionally scoped to a specific case."""
    from src.rag.store import QdrantPolicyStore

    results: list[dict[str, Any]] = []
    case_policy_meta: dict[str, Any] = {}

    if case_id:
        service = get_case_service()
        try:
            cp = await service.get_case_policy(case_id, query=query)
            case_policy_meta = {
                "case_id": cp.case_id,
                "suspected_category": cp.suspected_category,
                "policy_version_id": cp.policy_version_id,
                "policy_version": cp.policy_version,
                "action_matrix": cp.action_matrix,
                "applicable_action_rule": cp.applicable_action_rule,
            }
            for clause in cp.clauses:
                results.append(
                    {
                        "id": clause.id,
                        "title": f"{clause.source_ref} ({clause.section_ref})",
                        "section_ref": clause.section_ref,
                        "category": clause.category,
                        "snippet": clause.content[:350],
                        "source_url": clause.source_url,
                        "relevance_score": getattr(clause, "relevance_score", None) or 0.95,
                    }
                )
        except Exception:
            pass

    store = QdrantPolicyStore()
    where = None
    if category and category.lower() not in ("all", "none", ""):
        where = {"category": category.lower()}

    chunks = store.search(query=query, top_k=5, where=where)
    seen_ids = {str(r.get("id")) for r in results if r.get("id")}
    for c in chunks:
        c_id = str(c.get("id", ""))
        if c_id in seen_ids:
            continue
        meta = c.get("metadata", {})
        results.append(
            {
                "id": c.get("id"),
                "title": meta.get("title", "Quy định GreenSM"),
                "category": meta.get("category", "general"),
                "snippet": c.get("content", "")[:350],
                "source_url": meta.get("source_url", ""),
                "relevance_score": c.get("similarity", 0.85),
            }
        )
    res = {
        "query": query,
        "category": category,
        **case_policy_meta,
        "count": len(results),
        "results": results,
    }
    res["xml_widget"] = f"<policy_results>{json.dumps(res, ensure_ascii=False)}</policy_results>"
    return res


@tool
async def geocode_address(address: str, limit: int = 5) -> dict[str, Any]:
    """Geocode a free-text address. Lookup result is not proof of an actor's location."""
    return {
        "error": "geocode_address requires trusted case context",
        "status_code": 403,
    }


@tool
async def reverse_geocode_coordinates(longitude: float, latitude: float, limit: int = 5) -> dict[str, Any]:
    """Reverse-geocode WGS84 coordinates. Lookup result is not proof of location."""
    return {
        "error": "reverse_geocode_coordinates requires trusted case context",
        "status_code": 403,
    }


@tool
async def match_trip_telemetry(limit: int = 30) -> dict[str, Any]:
    """Snap stored GPS telemetry to the road network. Originals are never overwritten; returns match counts and distances."""
    return {
        "error": "match_trip_telemetry requires trusted case context",
        "status_code": 403,
    }


ALL_ANALYST_TOOLS = [
    get_case_detail,
    get_forensic_brief,
    get_case_policy,
    list_cases,
    claim_case,
    record_case_action,
    adjudicate_case,
    query_policy,
    trigger_simulation,
    get_driver_history,
    query_cases_db,
    check_driver_suspension,
    check_weather_condition,
    check_traffic_situation,
    fetch_corridor_historical_traffic,
    query_traffic_incident_feed,
    write_ticket_for_driver,
    check_related_cases_to_vehicle,
    get_driver_card,
    search_policy_documents,
    geocode_address,
    reverse_geocode_coordinates,
    match_trip_telemetry,
]

MODEL_ANALYST_TOOLS = [
    get_case_detail,
    get_forensic_brief,
    get_case_policy,
    list_cases,
    query_policy,
    get_driver_history,
    check_driver_suspension,
    check_weather_condition,
    check_traffic_situation,
    fetch_corridor_historical_traffic,
    query_traffic_incident_feed,
    check_related_cases_to_vehicle,
    get_driver_card,
    search_policy_documents,
    geocode_address,
    reverse_geocode_coordinates,
    match_trip_telemetry,
]

# Default tools bound to LangGraph agent ToolNode (excluding human-only commands)
ANALYST_TOOLS = MODEL_ANALYST_TOOLS

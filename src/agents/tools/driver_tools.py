"""LangChain tools for GreenSM Driver operations and autonomous dispute management.

Exposes:
- get_driver_dispute_context: Get alleged violation info and context for a driver
- corroborate_traffic_conditions: Deterministic verification of physical road traffic conditions
- inspect_trip_telemetry: Inspect GPS breadcrumbs, speed, jitter, and mock-location flags from Supabase
- verify_exoneration_rules: Verify NFR-L06-02 deterministic conditions for autonomous dismissal
- submit_driver_statement: Submit driver explanation, triggering autonomous exoneration or escalation
- query_driver_policy: Policy retrieval on driver rights, dispute deadlines, and allowable force majeure
"""

import logging
import unicodedata
from typing import Annotated, Any

from fastapi import HTTPException
from langchain_core.tools import InjectedToolArg, tool

from src.models.schemas import DriverChatRequest
from src.services.driver_dispute_service import get_driver_dispute_service

logger = logging.getLogger(__name__)


@tool
async def get_driver_dispute_context(
    case_id: str,
    driver_id: Annotated[str, InjectedToolArg] = "",
    organization_id: Annotated[str, InjectedToolArg] = "",
) -> dict[str, Any]:
    """Retrieve full violation context and dispute parameters for a specific driver."""
    service = get_driver_dispute_service()
    try:
        res = await service.get_driver_dispute_context(
            case_id=case_id,
            driver_id=driver_id,
            organization_id=organization_id or None,
        )
        return res.model_dump(mode="json")
    except HTTPException as e:
        error_type = "FORBIDDEN" if e.status_code == 403 else "NOT_FOUND" if e.status_code == 404 else "ERROR"
        return {"error": e.detail, "error_type": error_type, "status_code": e.status_code}
    except Exception as e:
        logger.exception("Error in get_driver_dispute_context tool")
        return {"error": str(e), "error_type": "ERROR", "status_code": 500}


@tool
async def corroborate_traffic_conditions(
    case_id: str,
    driver_id: Annotated[str, InjectedToolArg] = "",
    start_time: str | None = None,
    end_time: str | None = None,
) -> dict[str, Any]:
    """Check deterministic traffic metrics (average speed, duration ratio, congestion level, valid GPS) for a case."""
    service = get_driver_dispute_service()
    try:
        return await service.corroborate_traffic_conditions(
            case_id=case_id,
            driver_id=driver_id or None,
            start_time=start_time,
            end_time=end_time,
        )
    except HTTPException as e:
        error_type = "FORBIDDEN" if e.status_code == 403 else "NOT_FOUND" if e.status_code == 404 else "ERROR"
        return {"error": e.detail, "error_type": error_type, "status_code": e.status_code}
    except Exception as e:
        logger.exception("Error in corroborate_traffic_conditions tool")
        return {"error": str(e), "error_type": "ERROR", "status_code": 500}


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
async def inspect_trip_telemetry(
    case_id: str,
    driver_id: Annotated[str, InjectedToolArg] = "",
) -> dict[str, Any]:
    """Inspect GPS breadcrumbs, observed speed, latency, jitter, and mock location signals for a trip."""
    service = get_driver_dispute_service()
    try:
        return await service.inspect_trip_telemetry(case_id=case_id, driver_id=driver_id or None)
    except HTTPException as e:
        error_type = "FORBIDDEN" if e.status_code == 403 else "NOT_FOUND" if e.status_code == 404 else "ERROR"
        return {"error": e.detail, "error_type": error_type, "status_code": e.status_code}
    except Exception as e:
        logger.exception("Error in inspect_trip_telemetry tool")
        return {"error": str(e), "error_type": "ERROR", "status_code": 500}


@tool
async def verify_exoneration_rules(
    case_id: str,
    driver_id: Annotated[str, InjectedToolArg] = "",
    claim_type: str = "traffic_gridlock",
) -> dict[str, Any]:
    """Evaluate deterministic NFR-L06-02 rules (speed < 5.0 km/h, duration ratio >= 2.0x, GPS valid, 0 past sanctions)."""
    service = get_driver_dispute_service()
    try:
        corrob = await service.corroborate_traffic_conditions(case_id=case_id, driver_id=driver_id or None)
        if corrob.get("status") == "unavailable" or corrob.get("error_type") == "UNAVAILABLE":
            return {
                "case_id": case_id,
                "claim_type": claim_type,
                "rule": "Điều 12.2 Quy chế GreenSM - Miễn trừ bất khả kháng",
                "qualifies_for_auto_exoneration": False,
                "status": "unavailable",
                "error_type": "UNAVAILABLE",
                "evidence_references": [],
                "metrics": {
                    "observed_speed_kmh": None,
                    "duration_ratio": None,
                    "gps_valid": None,
                    "prior_sanctions": 0,
                },
                "action": "ESCALATE_TO_ANALYST",
                "details": "Telemetry unavailable; cannot verify exoneration rules without physical GPS data.",
            }
        is_traffic = claim_type in ("traffic_gridlock", "traffic", "heavy_traffic")
        qualified = bool(is_traffic and corrob.get("corroborated"))
        return {
            "case_id": case_id,
            "claim_type": claim_type,
            "rule": "Điều 12.2 Quy chế GreenSM - Miễn trừ bất khả kháng",
            "qualifies_for_auto_exoneration": qualified,
            "status": "available",
            "evidence_references": corrob.get("evidence_references", []),
            "metrics": {
                "observed_speed_kmh": corrob.get("observed_speed"),
                "duration_ratio": corrob.get("ratio"),
                "gps_valid": corrob.get("gps_valid"),
                "prior_sanctions": corrob.get("prior_sanctions"),
            },
            "action": "AUTO_DISMISS" if qualified else "ESCALATE_TO_ANALYST",
            "details": corrob.get("details", ""),
        }
    except HTTPException as e:
        error_type = "FORBIDDEN" if e.status_code == 403 else "NOT_FOUND" if e.status_code == 404 else "ERROR"
        return {"error": e.detail, "error_type": error_type, "status_code": e.status_code}
    except Exception as e:
        logger.exception("Error in verify_exoneration_rules tool")
        return {"error": str(e), "error_type": "ERROR", "status_code": 500}


@tool
async def submit_driver_statement(
    case_id: str,
    driver_id: Annotated[str, InjectedToolArg] = "",
    reason: str = "",
    claim_type: str = "",
    confirmation_token: str = "",
    evidence: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Submit a driver dispute statement. Requires a valid single-use confirmation_token issued by the UI confirmation card."""
    service = get_driver_dispute_service()
    canonical_id = service.case_service._case_aliases.get(str(case_id).strip(), str(case_id).strip())
    case = service.case_service._cases.get(canonical_id)
    if case is not None and driver_id:
        actual_driver_id = service._get_case_driver_id(canonical_id, case)
        if not actual_driver_id or not service._is_driver_authorized(actual_driver_id, driver_id):
            return {
                "status": "failed",
                "error": f"Case {case_id} not found",
                "error_type": "NOT_FOUND",
                "status_code": 404,
                "message": "Thao tác gửi giải trình cần xác nhận trực tiếp từ tài xế qua thẻ xác nhận.",
            }
    if not confirmation_token or not str(confirmation_token).strip():
        return {
            "status": "failed",
            "message": "Thao tác gửi giải trình cần xác nhận trực tiếp từ tài xế qua thẻ xác nhận.",
        }
    ok, token_reason = await service._consume_token(confirmation_token, case_id, driver_id, "submit_statement")
    if not ok:
        return {
            "status": "failed",
            "reason": token_reason,
            "message": "Thao tác gửi giải trình cần xác nhận trực tiếp từ tài xế qua thẻ xác nhận.",
        }
    try:
        chat_req = DriverChatRequest(
            case_id=case_id,
            driver_id=driver_id,
            message=reason,
            claim_type=claim_type,
        )
        res = await service.process_driver_chat(chat_req)
        out = res.model_dump(mode="json")
        out["status"] = "submitted"
        return out
    except HTTPException as e:
        error_type = "FORBIDDEN" if e.status_code == 403 else "NOT_FOUND" if e.status_code == 404 else "ERROR"
        return {"status": "failed", "error": e.detail, "error_type": error_type, "status_code": e.status_code}
    except Exception as e:
        logger.exception("Error in submit_driver_statement tool")
        return {"status": "failed", "error": str(e), "error_type": "ERROR", "status_code": 500}


@tool
async def acknowledge_violation(
    case_id: str,
    driver_id: Annotated[str, InjectedToolArg] = "",
    confirmation_token: str = "",
) -> dict[str, Any]:
    """Acknowledge alleged violation for a case after explicit driver confirmation (never sanctions automatically)."""
    service = get_driver_dispute_service()
    if not confirmation_token or not str(confirmation_token).strip():
        return {
            "status": "failed",
            "message": "Thao tác chấp nhận thông tin sự việc cần xác nhận trực tiếp từ tài xế qua thẻ xác nhận.",
            "sanction_action": None,
        }
    try:
        return await service.acknowledge_with_token(
            case_id=case_id,
            driver_id=driver_id,
            confirmation_token=confirmation_token,
        )
    except HTTPException as e:
        error_type = "FORBIDDEN" if e.status_code == 403 else "NOT_FOUND" if e.status_code == 404 else "ERROR"
        return {
            "status": "failed",
            "error": e.detail,
            "error_type": error_type,
            "status_code": e.status_code,
            "sanction_action": None,
        }
    except Exception as e:
        logger.exception("Error in acknowledge_violation tool")
        return {"status": "failed", "error": str(e), "error_type": "ERROR", "status_code": 500, "sanction_action": None}


@tool
async def query_driver_policy(query: str) -> dict[str, Any]:
    """Query GreenSM driver regulations regarding dispute rights, deadlines (48h), force majeure, and fair review."""
    service = get_driver_dispute_service()
    try:
        return service.query_driver_policy(query)
    except Exception as e:
        logger.exception("Error in query_driver_policy tool")
        return {"error": str(e)}


@tool
async def geocode_address(address: str, limit: int = 5) -> dict[str, Any]:
    """Geocode a free-text address. Lookup result is not proof of an actor's location."""
    from src.agents.tools.analyst_tools import geocode_address as _wrapped

    return await _wrapped.ainvoke({"address": address, "limit": limit})


@tool
async def reverse_geocode_coordinates(longitude: float, latitude: float, limit: int = 5) -> dict[str, Any]:
    """Reverse-geocode WGS84 coordinates. Lookup result is not proof of location."""
    from src.agents.tools.analyst_tools import reverse_geocode_coordinates as _wrapped

    return await _wrapped.ainvoke({"longitude": longitude, "latitude": latitude, "limit": limit})


@tool
async def match_trip_telemetry(limit: int = 30) -> dict[str, Any]:
    """Snap stored GPS telemetry to the road network. Originals are never overwritten."""
    from src.agents.tools.analyst_tools import match_trip_telemetry as _wrapped

    return await _wrapped.ainvoke({"limit": limit})


STATUS_COPY_VI = {
    "not_disputed": ("Chưa khiếu nại", "Chưa có yêu cầu đối soát cho sự việc này."),
    "in_dispute": ("Đang đối soát", "Hệ thống đang tiếp nhận và đối soát giải trình của bạn."),
    "driver_disputed": ("Đang đối soát", "Hệ thống đang tiếp nhận và đối soát giải trình của bạn."),
    "auto_dismissed": ("Miễn trừ tự động", "Vi phạm được hệ thống tự động miễn trừ do điều kiện khách quan hợp lệ."),
    "escalated": ("Chuyển chuyên viên", "Hồ sơ đã được chuyển lên chuyên viên thẩm định để đối chiếu thủ công."),
    "pending_review": ("Chờ chuyên viên", "Đang chờ chuyên viên thẩm định kiểm tra dữ liệu."),
    "pending_analyst_review": ("Chờ chuyên viên", "Đang chờ chuyên viên thẩm định kiểm tra dữ liệu."),
    "pending_confirmation": ("Chờ xác nhận", "Vui lòng kiểm tra và xác nhận nội dung giải trình trước khi gửi."),
    "pending": ("Chờ xử lý", "Hồ sơ đang trong hàng đợi xử lý."),
    "resolved": ("Đã giải quyết", "Vụ việc đã được xử lý hoàn tất."),
    "dismissed": ("Đã miễn trừ", "Vi phạm đã được hủy bỏ và miễn trừ trách nhiệm."),
    "upheld": ("Đã xác nhận vi phạm", "Vi phạm được xác nhận theo quy chế hoạt động."),
    "closed": ("Đã đóng", "Hồ sơ vụ việc đã kết thúc."),
    "expired": ("Hết hạn", "Thời hạn 48 giờ để gửi khiếu nại đã kết thúc."),
    "open": ("Đang mở", "Vụ việc đang chờ xử lý."),
    "ready": ("Sẵn sàng", "Hồ sơ sẵn sàng đối soát."),
    "investigating": ("Đang thẩm tra", "Đang kiểm tra và xác minh các dữ liệu hành trình."),
    "in_review": ("Đang xem xét", "Hồ sơ đang được xem xét."),
}

STATUS_COPY_EN = {
    "not_disputed": ("Not disputed", "No dispute submitted for this case."),
    "in_dispute": ("In dispute", "Your explanation is currently being received and audited."),
    "driver_disputed": ("In dispute", "Your explanation is currently being received and audited."),
    "auto_dismissed": ("Auto dismissed", "Violation automatically dismissed due to verified objective conditions."),
    "escalated": ("Escalated", "Case has been escalated to a review specialist for manual verification."),
    "pending_review": ("Pending review", "Awaiting review from a specialist."),
    "pending_analyst_review": ("Pending review", "Awaiting review from a specialist."),
    "pending_confirmation": ("Pending confirmation", "Please review and confirm your statement before submitting."),
    "pending": ("Pending", "Case is in the processing queue."),
    "resolved": ("Resolved", "This case has been fully resolved."),
    "dismissed": ("Dismissed", "Violation was dismissed and penalties cleared."),
    "upheld": ("Upheld", "Violation was confirmed according to operating policies."),
    "closed": ("Closed", "This dispute case has concluded."),
    "expired": ("Expired", "The 48-hour dispute window has expired."),
    "open": ("Open", "The case is open and awaiting action."),
    "ready": ("Ready", "The case is ready for audit."),
    "investigating": ("Investigating", "Telemetry and journey details are currently being verified."),
    "in_review": ("In review", "The case is currently undergoing review."),
}

VIOLATION_COPY_VI = {
    "ERR-01": ("Chậm trễ đón khách", "Thời gian phương tiện tiếp cận điểm đón kéo dài bất thường so với dự kiến."),
    "ERR-02": (
        "Hủy chuyến bất thường",
        "Phát hiện hành vi hủy chuyến sau khi nhận khách hoặc hủy chuyến không hợp lệ.",
    ),
    "ERR-03": (
        "Bất thường định vị GPS",
        "Tín hiệu định vị GPS bị gián đoạn, giật đột ngột hoặc có dấu hiệu giả lập vị trí.",
    ),
    "ERR-04": ("Gián đoạn viễn thông", "Mất kết nối dữ liệu mạng hoặc thiết bị ngắt truyền phát tín hiệu telemetry."),
    "ERR-05": ("Sai lệch lộ trình", "Khoảng cách hoặc lộ trình di chuyển sai lệch đáng kể so với tuyến đường tối ưu."),
}

VIOLATION_COPY_EN = {
    "ERR-01": ("Pickup delay", "Vehicle arrival time at pickup point was unusually delayed compared to estimate."),
    "ERR-02": ("Abnormal cancellation", "Cancellation detected after accepting trip or invalid cancellation pattern."),
    "ERR-03": ("GPS anomaly", "GPS signal interrupted, sudden jitter, or mock location indicator observed."),
    "ERR-04": ("Telemetry disruption", "Loss of network connectivity or telemetry stream interruption."),
    "ERR-05": ("Route deviation", "Trip route or distance significantly deviated from optimal corridor."),
}


@tool
async def list_my_cases(
    driver_id: Annotated[str, InjectedToolArg] = "",
    organization_id: Annotated[str, InjectedToolArg] = "",
    status: str | None = None,
) -> dict[str, Any]:
    """List open and historical dispute cases for the authenticated driver."""
    if not organization_id or not str(organization_id).strip():
        return {"error": "Organization scope required", "error_type": "FORBIDDEN", "status_code": 403}
    if not driver_id or not str(driver_id).strip():
        return {"error": "driver_id is required", "error_type": "FORBIDDEN", "status_code": 403}

    service = get_driver_dispute_service()
    try:
        res = await service.list_driver_cases(
            driver_id=str(driver_id).strip(),
            organization_id=str(organization_id).strip(),
        )
        items = res.items
        if status:
            norm_status = status.strip().lower()
            items = [
                c
                for c in items
                if (c.status and c.status.lower() == norm_status)
                or (c.dispute_status and c.dispute_status.lower() == norm_status)
            ]
        return {
            "cases": [c.model_dump(mode="json") for c in items],
            "total": len(items),
        }
    except HTTPException as e:
        error_type = "FORBIDDEN" if e.status_code == 403 else "NOT_FOUND" if e.status_code == 404 else "ERROR"
        return {"error": e.detail, "error_type": error_type, "status_code": e.status_code}
    except Exception as e:
        logger.exception("Error in list_my_cases tool")
        return {"error": str(e), "error_type": "ERROR", "status_code": 500}


@tool
async def get_case_timeline(
    case_id: str,
    driver_id: Annotated[str, InjectedToolArg] = "",
    organization_id: Annotated[str, InjectedToolArg] = "",
) -> dict[str, Any]:
    """Retrieve dispute status history and response deadline for an owned case."""
    if not driver_id or not str(driver_id).strip():
        return {"error": "driver_id is required", "error_type": "FORBIDDEN", "status_code": 403}

    service = get_driver_dispute_service()
    try:
        ctx = await service.get_driver_dispute_context(
            case_id=case_id,
            driver_id=driver_id,
            organization_id=str(organization_id).strip() if organization_id else None,
        )
        entries = service.get_audit_entries(case_id=case_id)
        alleged_time = ctx.alleged_time
        if hasattr(alleged_time, "isoformat"):
            alleged_time = alleged_time.isoformat()

        timeline = [
            {
                "event": "case_opened",
                "status": "open",
                "occurred_at": str(alleged_time or ""),
                "title": "Sự việc được ghi nhận",
                "description": "Hệ thống ghi nhận sự việc và mở hồ sơ đối soát.",
            }
        ]
        for entry in entries:
            action = str(entry.get("action", ""))
            result = str(entry.get("result", ""))
            timeline.append(
                {
                    "event": action.lower(),
                    "status": result.lower(),
                    "occurred_at": str(entry.get("recorded_at", "")),
                    "title": f"Ghi nhận: {action}",
                    "description": (
                        entry.get("payload", {}).get("reason")
                        or entry.get("payload", {}).get("notes")
                        or f"Kết quả: {result}"
                    ),
                }
            )

        return {
            "case_id": ctx.case_id,
            "driver_id": ctx.driver_id,
            "dispute_status": ctx.dispute_status,
            "response_deadline": ctx.dispute_deadline,
            "timeline": timeline,
        }
    except HTTPException as e:
        error_type = "FORBIDDEN" if e.status_code == 403 else "NOT_FOUND" if e.status_code == 404 else "ERROR"
        return {"error": e.detail, "error_type": error_type, "status_code": e.status_code}
    except Exception as e:
        logger.exception("Error in get_case_timeline tool")
        return {"error": str(e), "error_type": "ERROR", "status_code": 500}


@tool
async def explain_case_status(
    case_id: str,
    driver_id: Annotated[str, InjectedToolArg] = "",
    organization_id: Annotated[str, InjectedToolArg] = "",
    locale: str = "vi",
) -> dict[str, Any]:
    """Provide plain-language explanation of case and dispute status without raw codes."""
    if not driver_id or not str(driver_id).strip():
        return {"error": "driver_id is required", "error_type": "FORBIDDEN", "status_code": 403}

    service = get_driver_dispute_service()
    try:
        ctx = await service.get_driver_dispute_context(
            case_id=case_id,
            driver_id=driver_id,
            organization_id=str(organization_id).strip() if organization_id else None,
        )
        d_status = str(ctx.dispute_status or "").lower()
        v_code = str(ctx.violation_code or "").upper()

        label_vi, exp_vi = STATUS_COPY_VI.get(d_status, ("Đang xử lý", "Hồ sơ đang trong quy trình đối soát."))
        label_en, exp_en = STATUS_COPY_EN.get(d_status, ("Processing", "Case is currently being processed."))
        v_label_vi, v_exp_vi = VIOLATION_COPY_VI.get(
            v_code, ("Nghi vấn vận hành", "Hệ thống ghi nhận sự việc cần xác minh thực tế.")
        )
        v_label_en, v_exp_en = VIOLATION_COPY_EN.get(
            v_code, ("Operational inquiry", "System flagged an event requiring verification.")
        )

        short_id = f"#{case_id[-4:].upper()}" if len(case_id) >= 4 else f"#{case_id}"

        return {
            "case_id": ctx.case_id,
            "short_case_id": short_id,
            "status_label_vi": label_vi,
            "status_explanation_vi": exp_vi,
            "status_label_en": label_en,
            "status_explanation_en": exp_en,
            "violation_label_vi": v_label_vi,
            "violation_explanation_vi": v_exp_vi,
            "violation_label_en": v_label_en,
            "violation_explanation_en": v_exp_en,
            "dispute_deadline": ctx.dispute_deadline,
        }
    except HTTPException as e:
        error_type = "FORBIDDEN" if e.status_code == 403 else "NOT_FOUND" if e.status_code == 404 else "ERROR"
        return {"error": e.detail, "error_type": error_type, "status_code": e.status_code}
    except Exception as e:
        logger.exception("Error in explain_case_status tool")
        return {"error": str(e), "error_type": "ERROR", "status_code": 500}


@tool
async def get_my_scorecard(
    driver_id: Annotated[str, InjectedToolArg] = "",
    organization_id: Annotated[str, InjectedToolArg] = "",
) -> dict[str, Any]:
    """Retrieve 90-day driver scorecard including rating, completion, repeat offense risk, and past incidents."""
    if not driver_id or not str(driver_id).strip():
        return {"error": "driver_id is required", "error_type": "FORBIDDEN", "status_code": 403}

    try:
        from src.services.driver_service import get_driver_scorecard

        res = await get_driver_scorecard(
            driver_id=str(driver_id).strip(),
            organization_id=str(organization_id).strip() if organization_id else None,
        )
        return res.model_dump(mode="json")
    except HTTPException as e:
        error_type = "FORBIDDEN" if e.status_code == 403 else "NOT_FOUND" if e.status_code == 404 else "ERROR"
        return {"error": e.detail, "error_type": error_type, "status_code": e.status_code}
    except Exception as e:
        logger.exception("Error in get_my_scorecard tool")
        return {"error": str(e), "error_type": "ERROR", "status_code": 500}


@tool
async def list_my_trips(
    driver_id: Annotated[str, InjectedToolArg] = "",
    cursor: str | None = None,
    limit: int = 20,
    status: str | None = None,
    organization_id: Annotated[str, InjectedToolArg] = "",
) -> dict[str, Any]:
    """Retrieve trip history with customer ratings for the authenticated driver."""
    if not driver_id or not str(driver_id).strip():
        return {"error": "driver_id is required", "error_type": "FORBIDDEN", "status_code": 403}

    clamped_limit = max(1, min(int(limit), 50))
    try:
        from src.services.driver_service import list_driver_trips as _svc_list_trips

        return await _svc_list_trips(
            driver_id=str(driver_id).strip(),
            cursor=cursor,
            limit=clamped_limit,
            status=status,
            organization_id=str(organization_id).strip() if organization_id else None,
        )
    except HTTPException as e:
        error_type = "FORBIDDEN" if e.status_code == 403 else "NOT_FOUND" if e.status_code == 404 else "ERROR"
        return {"error": e.detail, "error_type": error_type, "status_code": e.status_code}
    except Exception as e:
        logger.exception("Error in list_my_trips tool")
        return {"error": str(e), "error_type": "ERROR", "status_code": 500}


@tool
async def get_trip_summary(
    trip_id: str,
    driver_id: Annotated[str, InjectedToolArg] = "",
    organization_id: Annotated[str, InjectedToolArg] = "",
) -> dict[str, Any]:
    """Retrieve full details of a specific trip including customer rating, enforcing driver ownership."""
    if not trip_id or not str(trip_id).strip():
        return {"error": "trip_id is required", "error_type": "NOT_FOUND", "status_code": 404}
    if not driver_id or not str(driver_id).strip():
        return {"error": "driver_id is required", "error_type": "FORBIDDEN", "status_code": 403}

    try:
        from src.services.driver_service import get_driver_trip_summary as _svc_trip_summary

        return await _svc_trip_summary(
            trip_id=str(trip_id).strip(),
            driver_id=str(driver_id).strip(),
            organization_id=str(organization_id).strip() if organization_id else None,
        )
    except HTTPException as e:
        error_type = "FORBIDDEN" if e.status_code == 403 else "NOT_FOUND" if e.status_code == 404 else "ERROR"
        return {"error": e.detail, "error_type": error_type, "status_code": e.status_code}
    except Exception as e:
        logger.exception("Error in get_trip_summary tool")
        return {"error": str(e), "error_type": "ERROR", "status_code": 500}


@tool
async def check_weather_condition(
    case_id: str | None = None,
    trip_id: str | None = None,
    driver_id: Annotated[str, InjectedToolArg] = "",
    organization_id: Annotated[str, InjectedToolArg] = "",
    lat: float | None = None,
    lon: float | None = None,
) -> dict[str, Any]:
    """Check physical weather conditions for an owned case or trip, verifying driver ownership."""
    if not driver_id or not str(driver_id).strip():
        return {"error": "driver_id is required", "error_type": "FORBIDDEN", "status_code": 403}

    service = get_driver_dispute_service()
    try:
        from src.agents.tools.analyst_tools import check_weather_condition as _analyst_weather

        org_scoped = str(organization_id).strip() if organization_id else None
        if trip_id:
            from src.services.driver_service import get_driver_trip_summary

            summary = await get_driver_trip_summary(
                trip_id=trip_id,
                driver_id=driver_id,
                organization_id=org_scoped,
            )
            res = await _analyst_weather.ainvoke(
                {
                    "lat": summary.get("pickup_lat"),
                    "lon": summary.get("pickup_lng"),
                }
            )
        elif case_id:
            await service.get_driver_dispute_context(
                case_id=case_id,
                driver_id=driver_id,
                organization_id=org_scoped,
            )
            res = await _analyst_weather.ainvoke({"lat": lat, "lon": lon, "case_id": case_id})
        else:
            return {"error": "case_id or trip_id is required", "error_type": "FORBIDDEN", "status_code": 403}

        if "error" in res:
            return res
        redacted = dict(res)
        redacted["verdict"] = None
        return redacted
    except HTTPException as e:
        error_type = "FORBIDDEN" if e.status_code == 403 else "NOT_FOUND" if e.status_code == 404 else "ERROR"
        return {"error": e.detail, "error_type": error_type, "status_code": e.status_code}
    except Exception as e:
        logger.exception("Error in check_weather_condition tool")
        return {"error": str(e), "error_type": "ERROR", "status_code": 500}


@tool
async def check_traffic_situation(
    case_id: str | None = None,
    trip_id: str | None = None,
    driver_id: Annotated[str, InjectedToolArg] = "",
    organization_id: Annotated[str, InjectedToolArg] = "",
    start_lat: float | None = None,
    start_lon: float | None = None,
    end_lat: float | None = None,
    end_lon: float | None = None,
) -> dict[str, Any]:
    """Check road traffic conditions and route congestion for an owned case or trip."""
    if not driver_id or not str(driver_id).strip():
        return {"error": "driver_id is required", "error_type": "FORBIDDEN", "status_code": 403}

    service = get_driver_dispute_service()
    try:
        from src.agents.tools.analyst_tools import check_traffic_situation as _analyst_traffic

        org_scoped = str(organization_id).strip() if organization_id else None
        if trip_id:
            from src.services.driver_service import get_driver_trip_summary

            summary = await get_driver_trip_summary(
                trip_id=trip_id,
                driver_id=driver_id,
                organization_id=org_scoped,
            )
            res = await _analyst_traffic.ainvoke(
                {
                    "start_lat": summary.get("pickup_lat"),
                    "start_lon": summary.get("pickup_lng"),
                    "end_lat": summary.get("dropoff_lat"),
                    "end_lon": summary.get("dropoff_lng"),
                }
            )
        elif case_id:
            await service.get_driver_dispute_context(
                case_id=case_id,
                driver_id=driver_id,
                organization_id=org_scoped,
            )
            res = await _analyst_traffic.ainvoke(
                {
                    "case_id": case_id,
                    "start_lat": start_lat,
                    "start_lon": start_lon,
                    "end_lat": end_lat,
                    "end_lon": end_lon,
                }
            )
        else:
            return {"error": "case_id or trip_id is required", "error_type": "FORBIDDEN", "status_code": 403}

        if "error" in res:
            return res
        redacted = dict(res)
        redacted["verdict"] = None
        return redacted
    except HTTPException as e:
        error_type = "FORBIDDEN" if e.status_code == 403 else "NOT_FOUND" if e.status_code == 404 else "ERROR"
        return {"error": e.detail, "error_type": error_type, "status_code": e.status_code}
    except Exception as e:
        logger.exception("Error in check_traffic_situation tool")
        return {"error": str(e), "error_type": "ERROR", "status_code": 500}


@tool
async def get_forensic_brief(
    case_id: str,
    driver_id: Annotated[str, InjectedToolArg] = "",
    organization_id: Annotated[str, InjectedToolArg] = "",
) -> dict[str, Any]:
    """Retrieve observed abnormalities for an owned case with analyst-only fields redacted and no verdict."""
    if not driver_id or not str(driver_id).strip():
        return {"error": "driver_id is required", "error_type": "FORBIDDEN", "status_code": 403}

    service = get_driver_dispute_service()
    try:
        await service.get_driver_dispute_context(
            case_id=case_id,
            driver_id=driver_id,
            organization_id=str(organization_id).strip() if organization_id else None,
        )
        from src.agents.tools.analyst_tools import get_forensic_brief as _analyst_forensic

        raw_brief = await _analyst_forensic.ainvoke({"case_id": case_id})
        if "error" in raw_brief:
            return raw_brief

        # Redact analyst-only fields: motivation_assessment, active_guardrails, verdict
        redacted = dict(raw_brief)
        redacted.pop("motivation_assessment", None)
        redacted.pop("active_guardrails", None)
        redacted.pop("verdict", None)
        redacted["observed_only"] = True
        redacted["verdict"] = None
        return redacted
    except HTTPException as e:
        error_type = "FORBIDDEN" if e.status_code == 403 else "NOT_FOUND" if e.status_code == 404 else "ERROR"
        return {"error": e.detail, "error_type": error_type, "status_code": e.status_code}
    except Exception as e:
        logger.exception("Error in get_forensic_brief tool")
        return {"error": str(e), "error_type": "ERROR", "status_code": 500}


@tool
async def suggest_dispute_path(
    case_id: str,
    driver_id: Annotated[str, InjectedToolArg] = "",
    organization_id: Annotated[str, InjectedToolArg] = "",
) -> dict[str, Any]:
    """Provide advisory guidance on whether to dispute or accept based on evidence without issuing a verdict."""
    if not driver_id or not str(driver_id).strip():
        return {"error": "driver_id is required", "error_type": "FORBIDDEN", "status_code": 403}

    service = get_driver_dispute_service()
    try:
        ctx = await service.get_driver_dispute_context(
            case_id=case_id,
            driver_id=driver_id,
            organization_id=str(organization_id).strip() if organization_id else None,
        )
        corrob = await service.corroborate_traffic_conditions(case_id=case_id, driver_id=driver_id)

        is_traffic_corroborated = bool(corrob.get("corroborated"))
        speed = corrob.get("observed_speed")
        ratio = corrob.get("ratio")

        evidence_items = []
        if is_traffic_corroborated:
            evidence_items.append("Ùn tắc giao thông diện rộng đã được đối soát qua telemetry xe")
            suggestion = "dispute"
            metric_parts = []
            if speed is not None:
                metric_parts.append(f"{speed} km/h")
            if ratio is not None:
                metric_parts.append(f"hệ số thời gian {ratio}x")
            metric_str = f" ({', '.join(metric_parts)})" if metric_parts else ""
            reasoning = (
                f"Dữ liệu giao thông đối soát ghi nhận tốc độ phương tiện di chuyển chậm bất thường{metric_str} "
                "phù hợp với tình trạng ùn tắc giao thông. "
                "Bác tài có thể viện dẫn Điều 12.2 Quy chế GreenSM để Chuyên viên thẩm định xem xét đối soát."
            )
        else:
            suggestion = "review_details"
            reasoning = (
                "Hệ thống tự động chưa ghi nhận điều kiện ùn tắc giao thông rõ rệt từ cảm biến. "
                "Nếu có các yếu tố khách quan khác (sự cố bất khả kháng, thời tiết, yêu cầu từ khách), "
                "bác tài có thể gửi giải trình chi tiết kèm bằng chứng để Chuyên viên xem xét."
            )

        return {
            "case_id": ctx.case_id,
            "driver_id": ctx.driver_id,
            "suggestion": suggestion,
            "advisory": True,
            "reasoning": reasoning,
            "evidence_found": evidence_items,
            "traffic_corroborated": is_traffic_corroborated,
            "note": (
                "Khuyến nghị này mang tính chất tham khảo (advisory). "
                "Quyết định cuối cùng thuộc về Chuyên viên thẩm định độc lập; "
                "hệ thống không đưa ra phán quyết vi phạm tự động."
            ),
            "verdict": None,
        }
    except HTTPException as e:
        error_type = "FORBIDDEN" if e.status_code == 403 else "NOT_FOUND" if e.status_code == 404 else "ERROR"
        return {"error": e.detail, "error_type": error_type, "status_code": e.status_code}
    except Exception as e:
        logger.exception("Error in suggest_dispute_path tool")
        return {"error": str(e), "error_type": "ERROR", "status_code": 500}


_GENERIC_PATTERNS = frozenset(
    [
        "toi khong lam gi",
        "khong biet",
        "loi he thong",
        "don't know",
        "dont know",
        "i didn't do it",
        "i didnt do it",
        "no reason",
        "n/a",
        "none",
        "toi bi oan",
        "test test test",
        "khong co gi",
        "khong co ly do",
    ]
)


def _normalize_statement_text(text: str) -> str:
    s = str(text or "").strip().lower()
    s = s.replace("đ", "d").replace("Đ", "d")
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def _is_valid_corroboration(c: Any) -> bool:
    if isinstance(c, str):
        return bool(c.strip())
    if isinstance(c, dict):
        return bool(c)
    return False


@tool
async def assess_statement_completeness(
    incident_type: str,
    description: str,
    corroborations: list[Any] | None = None,
    no_evidence_declared: bool = False,
) -> dict[str, Any]:
    """Deterministic checklist assessing completeness of a driver's dispute statement."""
    missing_items: list[str] = []
    norm_type = str(incident_type or "").strip().lower()
    allowed_types = {"traffic", "gps", "weather", "passenger", "other"}
    type_valid = norm_type in allowed_types
    if not type_valid:
        missing_items.append("incident_type: must be one of traffic, gps, weather, passenger, other")

    desc_str = str(description or "").strip()
    desc_norm = _normalize_statement_text(desc_str)
    is_too_short = len(desc_str) < 20
    is_generic = any(pat in desc_norm for pat in _GENERIC_PATTERNS) and len(desc_str) < 60
    desc_valid = not is_too_short and not is_generic
    if is_too_short:
        missing_items.append("description: must be at least 20 characters and concrete")
    elif is_generic:
        missing_items.append("description: description is too generic; please provide specific details")

    valid_corrobs = [c for c in (corroborations or []) if _is_valid_corroboration(c)]
    has_corroboration = bool(valid_corrobs)
    evidence_valid = has_corroboration or bool(no_evidence_declared)
    if not evidence_valid:
        missing_items.append(
            "corroborations: provide at least one valid corroboration or declare no evidence available"
        )

    complete = len(missing_items) == 0
    return {
        "complete": complete,
        "missing_items": missing_items,
        "checklist": {
            "incident_type_valid": type_valid,
            "description_concrete": desc_valid,
            "evidence_provided_or_declared": evidence_valid,
        },
    }


@tool
async def get_appeal_options(
    case_id: str,
    driver_id: Annotated[str, InjectedToolArg] = "",
    organization_id: Annotated[str, InjectedToolArg] = "",
) -> dict[str, Any]:
    """Retrieve available appeal options, next steps, and deadlines for an owned case."""
    if not driver_id or not str(driver_id).strip():
        return {"error": "driver_id is required", "error_type": "FORBIDDEN", "status_code": 403}

    service = get_driver_dispute_service()
    try:
        ctx = await service.get_driver_dispute_context(
            case_id=case_id,
            driver_id=driver_id,
            organization_id=str(organization_id).strip() if organization_id else None,
        )
        return {
            "case_id": ctx.case_id,
            "driver_id": ctx.driver_id,
            "dispute_status": ctx.dispute_status,
            "deadline": ctx.dispute_deadline,
            "response_deadline": ctx.dispute_deadline,
            "options": [
                {
                    "action": "reject_and_explain",
                    "title": "Giải trình sự việc (Reject & Explain)",
                    "description": "Nêu rõ nguyên nhân khách quan và cung cấp đối soát (thời tiết, giao thông, lỗi thiết bị) theo Điều 12.2.",
                },
                {
                    "action": "request_assistance",
                    "title": "Hỗ trợ trực tiếp từ tổng đài",
                    "description": "Liên hệ kênh hỗ trợ đối tác nếu cần trợ giúp khẩn cấp.",
                },
            ],
            "next_steps": [
                "1. Chọn hình thức phản hồi trước hạn chót (48 giờ kể từ khi nhận thông báo).",
                "2. Nếu giải trình: hoàn thiện biểu mẫu với lý do cụ thể và đối soát.",
                "3. Chuyên viên độc lập sẽ thẩm định và phản hồi kết quả chính thức.",
            ],
        }
    except HTTPException as e:
        error_type = "FORBIDDEN" if e.status_code == 403 else "NOT_FOUND" if e.status_code == 404 else "ERROR"
        return {"error": e.detail, "error_type": error_type, "status_code": e.status_code}
    except Exception as e:
        logger.exception("Error in get_appeal_options tool")
        return {"error": str(e), "error_type": "ERROR", "status_code": 500}


ALL_DRIVER_TOOLS = [
    get_driver_dispute_context,
    corroborate_traffic_conditions,
    fetch_corridor_historical_traffic,
    query_traffic_incident_feed,
    inspect_trip_telemetry,
    verify_exoneration_rules,
    submit_driver_statement,
    acknowledge_violation,
    query_driver_policy,
    geocode_address,
    reverse_geocode_coordinates,
    match_trip_telemetry,
    list_my_cases,
    get_case_timeline,
    explain_case_status,
    get_my_scorecard,
    list_my_trips,
    get_trip_summary,
    check_weather_condition,
    check_traffic_situation,
    get_forensic_brief,
    suggest_dispute_path,
    assess_statement_completeness,
    get_appeal_options,
]

MODEL_DRIVER_TOOLS = [
    get_driver_dispute_context,
    corroborate_traffic_conditions,
    fetch_corridor_historical_traffic,
    query_traffic_incident_feed,
    inspect_trip_telemetry,
    verify_exoneration_rules,
    query_driver_policy,
    geocode_address,
    reverse_geocode_coordinates,
    match_trip_telemetry,
    list_my_cases,
    get_case_timeline,
    explain_case_status,
    get_my_scorecard,
    list_my_trips,
    get_trip_summary,
    check_weather_condition,
    check_traffic_situation,
    get_forensic_brief,
    suggest_dispute_path,
    assess_statement_completeness,
    get_appeal_options,
]

# Default tools bound to Driver LangGraph agent ToolNode (excluding human-only commands)
DRIVER_TOOLS = MODEL_DRIVER_TOOLS

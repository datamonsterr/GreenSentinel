"""Tenant-scoped solved-case retrieval and advisory similarity matching.

Provides:
- Authoritative immutable contexts from `app.solved_case_contexts`.
- Explicit read-only compatibility for tenant-linked legacy records.
- TypeSafe Jev Decision Model integration via OpenRouter `/api/alpha/decisions`.
- Deterministic heuristic fallback matching (claim type, violation code, telemetry proximity).
- Post-decision Workflow Trace synthesis (agent tools, human actions, policy citations, verdict).
- 1-Click Precedent Procedure application for Cockpit Fraud Analyst.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any

import httpx

try:
    import psycopg as _psycopg
    from psycopg.rows import dict_row as _dict_row
except ImportError:
    psycopg = None
    dict_row = None
else:
    psycopg = _psycopg
    dict_row = _dict_row

from src.config import Settings
from src.models.schemas import (
    PrecedentMatchResponse,
    PrecedentSimilarityMatch,
    PrecedentWorkflowItem,
    WorkflowDecision,
    WorkflowHumanAction,
    WorkflowTimelineEvent,
    WorkflowToolCall,
    WorkflowTrace,
)
from src.services.case_service import CaseService, get_case_service
from src.services.precedent_repository import (
    SCORE_SEMANTICS,
    PrecedentPersistenceError,
    get_finalized,
    get_finalized_by_case,
    get_legacy_read_only,
    list_finalized,
    publish_finalized,
    record_application_from_latest_view,
    record_reuse,
)

logger = logging.getLogger(__name__)

# Trip lifecycle milestones backing the workflow timeline ribbon (issue #100, §3.3).
TIMELINE_EVENT_TYPES = ("dispatched", "driver_arriving", "cancelled_by_passenger", "dispute_opened")
TIMELINE_LABELS = {
    "dispatched": "Điều phối",
    "driver_arriving": "Di chuyển đón",
    "cancelled_by_passenger": "Khách huỷ",
    "dispute_opened": "Khiếu nại",
}


def _load_case_timeline(conn: Any, case_id: str) -> list[WorkflowTimelineEvent]:
    """Exact trip-event timestamps for a case; empty when unavailable."""
    try:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT te.event_type, te.occurred_at FROM app.trip_events te
                   WHERE te.trip_id = (
                       SELECT ta.trip_id FROM app.trip_assignments ta
                       WHERE ta.id = (SELECT fc.assignment_id FROM app.fraud_cases fc WHERE fc.id = %s)
                   )
                   AND te.event_type IN ('dispatched', 'driver_arriving', 'cancelled_by_passenger', 'dispute_opened')
                   ORDER BY te.occurred_at ASC;""",
                (str(case_id),),
            )
            rows = cur.fetchall() or []
    except Exception:
        return []
    events = []
    for row in rows:
        occurred = row.get("occurred_at")
        events.append(
            WorkflowTimelineEvent(
                event_type=str(row.get("event_type")),
                occurred_at=occurred.isoformat() if hasattr(occurred, "isoformat") else str(occurred),
                label=TIMELINE_LABELS.get(str(row.get("event_type")), str(row.get("event_type"))),
            )
        )
    return events


OPENROUTER_DECISIONS_URL = "https://openrouter.ai/api/alpha/decisions"

# Canonical Historical Seed Precedents (Dual-loaded for offline/test reliability)
SEEDED_PRECEDENT_ITEMS: list[dict[str, Any]] = [
    {
        "id": "018f2f4e-9100-7000-8000-000000000001",
        "case_id": "018f2f4e-a000-7000-8000-000000000026",
        "violation_code": "ERR-02",
        "claim_type": "traffic_gridlock",
        "district": "Ba Dinh",
        "title": "Ùn tắc giao thông nghiêm trọng giờ cao điểm đường Kim Mã",
        "driver_statement_summary": "Đoạn đường Kim Mã - Liễu Giai bị kẹt xe kéo dài, xe điện di chuyển dưới 5km/h trong hơn 25 phút.",
        "verdict": "exonerated",
        "confidence_score": 0.98,
        "workflow_trace": {
            "agent_tools_called": [
                {
                    "tool_name": "corroborate_traffic_conditions",
                    "input_summary": "corridor=Kim Ma, start_time=17:30, end_time=18:15",
                    "output_summary": "speed=2.1 km/h, ratio=2.7x, congestion=heavy, gps_valid=true, prior_sanctions=0",
                    "executed_at": "2026-09-24T18:16:00Z",
                    "status": "success",
                },
                {
                    "tool_name": "query_driver_policy",
                    "input_summary": "query=traffic congestion stall leeway",
                    "output_summary": "GSM-POL-042 clause 3.2 allows 100% waiver when speed < 5km/h and duration ratio >= 2.0x",
                    "executed_at": "2026-09-24T18:16:05Z",
                    "status": "success",
                },
            ],
            "human_actions_performed": [
                {
                    "actor_role": "driver",
                    "action_type": "dispute_statement",
                    "summary": "Tài xế bấm nút báo kẹt xe Kim Mã trên ứng dụng Driver App",
                    "timestamp": "2026-09-24T18:15:30Z",
                }
            ],
            "driver_response_summary": "Đoạn đường Kim Mã - Liễu Giai bị kẹt xe kéo dài, xe điện di chuyển dưới 5km/h trong hơn 25 phút.",
            "related_policies": [
                {
                    "policy_code": "GSM-POL-042",
                    "clause": "3.2 (Bất khả kháng do giao thông đô thị)",
                    "rationale": "Miễn trừ chế tài trễ đón khách khi vận tốc dưới 5 km/h và tỷ lệ vượt trên 2.0x",
                    "relevance_score": 0.98,
                }
            ],
            "final_decision": {
                "verdict": "exonerated",
                "penalty_amount": 0,
                "rationale": "Xác thực kẹt xe Kim Mã tự động từ viễn thông thực tế (tốc độ TB 2.1 km/h, tỷ lệ 2.7x). Miễn trừ toàn bộ chế tài.",
                "decided_by": "system_autonomous_agent",
                "decided_at": "2026-09-24T18:16:10Z",
            },
        },
    },
    {
        "id": "018f2f4e-9100-7000-8000-000000000002",
        "case_id": "018f2f4e-a000-7000-8000-000000000001",
        "violation_code": "ERR-02",
        "claim_type": "traffic_gridlock",
        "district": "Dong Da",
        "title": "Xe buýt chết máy chắn lối rẽ Nguyễn Chí Thanh",
        "driver_statement_summary": "Sự cố xe buýt chết máy chắn ngang đường Nguyễn Chí Thanh khiến phương tiện không thể quay đầu đón khách đúng hẹn.",
        "verdict": "exonerated",
        "confidence_score": 0.95,
        "workflow_trace": {
            "agent_tools_called": [
                {
                    "tool_name": "corroborate_traffic_conditions",
                    "input_summary": "corridor=Nguyen Chi Thanh, start_time=08:10, end_time=08:40",
                    "output_summary": "speed=3.4 km/h, ratio=2.3x, congestion=heavy, gps_valid=true, prior_sanctions=0",
                    "executed_at": "2026-09-25T08:42:00Z",
                    "status": "success",
                },
                {
                    "tool_name": "query_driver_policy",
                    "input_summary": "query=road obstacle obstruction policy",
                    "output_summary": "GSM-POL-042 clause 3.4 permits waiver upon third-party incident verification",
                    "executed_at": "2026-09-25T08:42:15Z",
                    "status": "success",
                },
            ],
            "human_actions_performed": [
                {
                    "actor_role": "driver",
                    "action_type": "dispute_statement",
                    "summary": "Tài xế giải trình bị kẹt do xe buýt chết máy chắn ngang lối rẽ",
                    "timestamp": "2026-09-25T08:41:00Z",
                },
                {
                    "actor_role": "analyst",
                    "action_type": "delegate_inquiry",
                    "summary": "Chuyên viên yêu cầu cung cấp vị trí chính xác của xe buýt gặp sự cố",
                    "timestamp": "2026-09-25T08:45:00Z",
                },
                {
                    "actor_role": "driver",
                    "action_type": "driver_response",
                    "summary": "Tài xế phản hồi vị trí lối rẽ trước cổng Học viện Phụ nữ Việt Nam",
                    "timestamp": "2026-09-25T08:48:00Z",
                },
            ],
            "driver_response_summary": "Tôi bị kẹt ở lối rẽ Nguyễn Chí Thanh trước cổng Học viện Phụ nữ do có xe buýt chết máy chắn ngang.",
            "related_policies": [
                {
                    "policy_code": "GSM-POL-042",
                    "clause": "3.4 (Chướng ngại vật và sự cố giao thông đột xuất)",
                    "rationale": "Chấp thuận giải trình sự cố chắn đường khi telemetry xác nhận đứng yên trên tuyến",
                    "relevance_score": 0.95,
                }
            ],
            "final_decision": {
                "verdict": "exonerated",
                "penalty_amount": 0,
                "rationale": "Chấp thuận giải trình sự cố xe buýt chắn lối rẽ. Telemetry xác nhận đứng yên 18 phút. Miễn trừ chế tài.",
                "decided_by": "anl-001",
                "decided_at": "2026-09-25T08:50:00Z",
            },
        },
    },
    {
        "id": "018f2f4e-9100-7000-8000-000000000003",
        "case_id": "018f2f4e-a000-7000-8000-000000000003",
        "violation_code": "ERR-05",
        "claim_type": "gps_issue",
        "district": "Thanh Xuan",
        "title": "Mất tín hiệu định vị tầng hầm B3 Vincom Royal City",
        "driver_statement_summary": "Tài xế đón khách ở sảnh R3 Royal City, tầng hầm B3 mất sóng GPS và 4G khiến app ghi nhận đứt quãng hành trình.",
        "verdict": "exonerated",
        "confidence_score": 0.92,
        "workflow_trace": {
            "agent_tools_called": [
                {
                    "tool_name": "assess_fraud_risk",
                    "input_summary": "case_id=018f2f4e-a000-7000-8000-000000000003, check_underground_basement=true",
                    "output_summary": "underground_geofence_match=true, basement=B3 Royal City, mock_gps_detected=false",
                    "executed_at": "2026-09-23T14:10:00Z",
                    "status": "success",
                }
            ],
            "human_actions_performed": [
                {
                    "actor_role": "driver",
                    "action_type": "dispute_statement",
                    "summary": "Tài xế khiếu nại mất sóng GPS do vào tầng hầm B3 đón khách",
                    "timestamp": "2026-09-23T14:08:00Z",
                }
            ],
            "driver_response_summary": "Đón khách tại sảnh R3 Royal City tầng hầm B3, vào hầm mất sóng GPS hơn 10 phút.",
            "related_policies": [
                {
                    "policy_code": "GSM-POL-018",
                    "clause": "2.1 (Suy hao tín hiệu định vị tầng hầm đô thị)",
                    "rationale": "Không quy kết gian lận vị trí khi tọa độ vào/ra khớp geofence hầm trung tâm thương mại",
                    "relevance_score": 0.94,
                }
            ],
            "final_decision": {
                "verdict": "exonerated",
                "penalty_amount": 0,
                "rationale": "Geofence xác nhận điểm mất sóng trùng khớp lối vào hầm B3 Royal City. Không phát hiện mock GPS. Miễn trừ.",
                "decided_by": "anl-002",
                "decided_at": "2026-09-23T14:15:00Z",
            },
        },
    },
    {
        "id": "018f2f4e-9100-7000-8000-000000000004",
        "case_id": "018f2f4e-a000-7000-8000-000000000004",
        "violation_code": "ERR-05",
        "claim_type": "gps_issue",
        "district": "Tay Ho",
        "title": "Giả lập GPS nhảy cóc không có biến thiên gia tốc thực",
        "driver_statement_summary": "Tài xế báo lỗi app hiển thị sai vị trí ven Hồ Tây nhưng telemetry ghi nhận nhảy cóc 120km/h không có gia tốc vật lý.",
        "verdict": "penalty_applied",
        "confidence_score": 0.96,
        "workflow_trace": {
            "agent_tools_called": [
                {
                    "tool_name": "assess_fraud_risk",
                    "input_summary": "case_id=018f2f4e-a000-7000-8000-000000000004, inspect_accelerometer=true",
                    "output_summary": "speed_jump=124km/h, accelerometer_std=0.01g, mock_provider_detected=true",
                    "executed_at": "2026-09-22T20:00:00Z",
                    "status": "success",
                }
            ],
            "human_actions_performed": [
                {
                    "actor_role": "driver",
                    "action_type": "dispute_statement",
                    "summary": "Tài xế giải trình máy đơ làm nhảy vị trí",
                    "timestamp": "2026-09-22T19:50:00Z",
                },
                {
                    "actor_role": "analyst",
                    "action_type": "decision_submit",
                    "summary": "Chuyên viên đối chiếu vi phạm can thiệp hệ điều hành và áp dụng chế tài",
                    "timestamp": "2026-09-22T20:10:00Z",
                },
            ],
            "driver_response_summary": "Điện thoại tôi bị lag nên nhảy vị trí, không phải do tôi cố tình chỉnh GPS.",
            "related_policies": [
                {
                    "policy_code": "GSM-POL-003",
                    "clause": "1.4 (Sử dụng phần mềm can thiệp vị trí định vị)",
                    "rationale": "Nghiêm cấm hành vi giả lập tọa độ GPS nhằm trục lợi thưởng chuyến hoặc cước phí đón khách",
                    "relevance_score": 0.99,
                }
            ],
            "final_decision": {
                "verdict": "penalty_applied",
                "penalty_amount": 500000,
                "rationale": "Dữ liệu cảm biến gia tốc bất biến (0.01g) chứng minh phương tiện đứng yên trong khi GPS nhảy 120km/h. Áp dụng chế tài cấp 2.",
                "decided_by": "anl-001",
                "decided_at": "2026-09-22T20:12:00Z",
            },
        },
    },
    {
        "id": "018f2f4e-9100-7000-8000-000000000005",
        "case_id": "018f2f4e-a000-7000-8000-000000000005",
        "violation_code": "ERR-02",
        "claim_type": "passenger_wait",
        "district": "Cau Giay",
        "title": "Hành khách yêu cầu chờ quá 15 phút tại ngõ nhỏ phố Duy Tân",
        "driver_statement_summary": "Khách nhắn tin hẹn chờ thanh toán đồ đạc tại ngõ Duy Tân, tài xế không hủy chuyến chủ quan.",
        "verdict": "exonerated",
        "confidence_score": 0.93,
        "workflow_trace": {
            "agent_tools_called": [
                {
                    "tool_name": "query_driver_policy",
                    "input_summary": "query=passenger requested wait time grace period",
                    "output_summary": "GSM-POL-015 clause 4.1 permits waiting up to 20 minutes if confirmed by chat/call",
                    "executed_at": "2026-09-21T11:05:00Z",
                    "status": "success",
                }
            ],
            "human_actions_performed": [
                {
                    "actor_role": "driver",
                    "action_type": "dispute_statement",
                    "summary": "Tài xế gửi giải trình khách gọi điện xin chờ mang vali xuống sảnh",
                    "timestamp": "2026-09-21T11:00:00Z",
                },
                {
                    "actor_role": "analyst",
                    "action_type": "delegate_inquiry",
                    "summary": "Chuyên viên đối soát nhật ký cuộc gọi tổng đài nội bộ xác nhận liên lạc giữa khách và tài xế",
                    "timestamp": "2026-09-21T11:15:00Z",
                },
            ],
            "driver_response_summary": "Khách xin chờ mang đồ xuống, có gọi điện trên app lúc 10:45.",
            "related_policies": [
                {
                    "policy_code": "GSM-POL-015",
                    "clause": "4.1 (Thời gian chờ theo thỏa thuận với khách)",
                    "rationale": "Không tính lỗi cố tình kéo dài thời gian đón khi hành khách chủ động đề nghị chờ đợi",
                    "relevance_score": 0.95,
                }
            ],
            "final_decision": {
                "verdict": "exonerated",
                "penalty_amount": 0,
                "rationale": "Tổng đài xác nhận 2 cuộc gọi giữa khách và tài xế trong thời gian dừng chờ. Miễn trừ chế tài vi phạm ERR-02.",
                "decided_by": "anl-003",
                "decided_at": "2026-09-21T11:20:00Z",
            },
        },
    },
]


class JevPrecedentService:
    """Service providing Jev-powered Precedent Matching and Workflow Trace mining."""

    def __init__(self, case_service: CaseService | None = None, settings: Settings | None = None) -> None:
        self.case_service = case_service or get_case_service()
        self.settings = settings or self.case_service.settings
        self._precedents: dict[str, PrecedentWorkflowItem] = {}
        self._case_workflow_traces: dict[str, WorkflowTrace] = {}

        # Pre-seed in-memory store
        self._init_seeded_precedents()

    def _init_seeded_precedents(self) -> None:
        """Seed initial precedents into in-memory store."""
        for raw in SEEDED_PRECEDENT_ITEMS:
            item = PrecedentWorkflowItem.model_validate(raw)
            self._precedents[item.id] = item

    def _get_db_connection(self):
        """Retrieve db connection via case_service."""
        return self.case_service._get_db_connection()

    def list_precedents(
        self,
        violation_code: str | None = None,
        claim_type: str | None = None,
        limit: int = 50,
        organization_id: str | None = None,
    ) -> list[PrecedentWorkflowItem]:
        """List tenant-scoped finalized precedents, or test-only legacy fixtures offline."""
        conn = self._get_db_connection()
        if conn:
            try:
                if not organization_id:
                    return []
                return list_finalized(
                    conn,
                    organization_id=organization_id,
                    violation_code=violation_code,
                    claim_type=claim_type,
                    limit=limit,
                )
            finally:
                conn.close()
        items = list(self._precedents.values())
        if violation_code:
            items = [p for p in items if p.violation_code.upper() == violation_code.upper()]
        if claim_type:
            items = [p for p in items if p.claim_type.lower() == claim_type.lower()]
        return items[:limit]

    def get_precedent(self, precedent_id: str, organization_id: str | None = None) -> PrecedentWorkflowItem | None:
        """Get a finalized precedent without crossing tenant boundaries."""
        conn = self._get_db_connection()
        if conn:
            try:
                if not organization_id:
                    return None
                item = get_finalized(conn, precedent_id=precedent_id, organization_id=organization_id)
                return item or get_legacy_read_only(
                    conn,
                    precedent_id=precedent_id,
                    organization_id=organization_id,
                )
            finally:
                conn.close()
        return self._precedents.get(str(precedent_id).strip())

    async def match_precedent(
        self,
        case_id: str,
        claim_type: str | None = None,
        driver_statement: str | None = None,
        violation_code: str | None = None,
        telemetry_summary: dict[str, Any] | None = None,
        organization_id: str | None = None,
        actor_id: str | None = None,
    ) -> PrecedentMatchResponse:
        """Find matching historical precedent using TypeSafe Jev Decision model or heuristic fallback."""
        candidates = self.list_precedents(organization_id=organization_id)
        candidates_by_id = {candidate.id: candidate for candidate in candidates}

        if not candidates:
            return PrecedentMatchResponse(case_id=case_id, has_match=False, top_match=None, all_candidates=[])

        # Resolve case context if not provided
        if not violation_code:
            try:
                canonical_id = self.case_service._case_aliases.get(case_id, case_id)
                case_obj = self.case_service._cases.get(canonical_id, {})
                violation_code = case_obj.get("violation_code") or "ERR-02"
            except Exception:
                violation_code = "ERR-02"

        # Try Jev model on OpenRouter
        top_match: PrecedentSimilarityMatch | None = None
        openrouter_key = self.settings.openrouter_api_key

        if openrouter_key and openrouter_key.startswith("sk-or-"):
            try:
                top_match = await self._match_with_jev(
                    case_id=case_id,
                    claim_type=claim_type or "traffic_gridlock",
                    driver_statement=driver_statement or "Tài xế khiếu nại kẹt xe",
                    violation_code=violation_code,
                    telemetry_summary=telemetry_summary or {},
                    candidates=candidates,
                )
            except Exception as e:
                logger.warning("Jev decision model call failed (%s). Falling back to heuristic matcher.", e)

        # Fallback to deterministic heuristic matching if Jev was unavailable or failed
        if not top_match:
            top_match = self._match_with_heuristic(
                case_id=case_id,
                claim_type=claim_type,
                driver_statement=driver_statement,
                violation_code=violation_code,
                telemetry_summary=telemetry_summary,
                candidates=candidates,
            )

        # Build candidate matches for response
        all_candidates: list[PrecedentSimilarityMatch] = [top_match]
        # Append other scored candidates
        for c in candidates:
            if c.id != top_match.precedent_id:
                score = self._compute_heuristic_score(
                    c, violation_code, claim_type, driver_statement, telemetry_summary
                )
                all_candidates.append(
                    PrecedentSimilarityMatch(
                        precedent_id=c.id,
                        precedent_case_id=c.case_id,
                        title=c.title,
                        similarity_score=round(score, 2),
                        matching_factors=[f"Mã vi phạm: {c.violation_code}", f"Loại khiếu nại: {c.claim_type}"],
                        recommended_procedure=[t.tool_name for t in c.workflow_trace.agent_tools_called],
                        precedent_verdict=c.verdict,
                        confidence_rationale="Điểm tương đồng tính toán qua chỉ số heuristic đa chiều.",
                        model_used="heuristic_fallback",
                        score_semantics=SCORE_SEMANTICS,
                        provenance=c.provenance,
                        precedent_workflow=c.workflow_trace,
                    )
                )

        all_candidates.sort(key=lambda x: x.similarity_score, reverse=True)
        has_match = top_match.similarity_score >= 0.60

        response = PrecedentMatchResponse(
            case_id=case_id,
            has_match=has_match,
            top_match=top_match if has_match else None,
            all_candidates=all_candidates[:5],
        )
        if has_match and top_match and organization_id and actor_id:
            conn = self._get_db_connection()
            if conn:
                try:
                    record_reuse(
                        conn,
                        organization_id=organization_id,
                        current_case_id=case_id,
                        precedent=candidates_by_id[top_match.precedent_id],
                        actor_id=actor_id,
                        action="viewed",
                        similarity_score=top_match.similarity_score,
                        retrieval_model=top_match.model_used,
                        matching_factors=top_match.matching_factors,
                    )
                    conn.commit()
                except (PrecedentPersistenceError, ValueError):
                    conn.rollback()
                    raise
                finally:
                    conn.close()
        return response

    async def _match_with_jev(
        self,
        case_id: str,
        claim_type: str,
        driver_statement: str,
        violation_code: str,
        telemetry_summary: dict[str, Any],
        candidates: list[PrecedentWorkflowItem],
    ) -> PrecedentSimilarityMatch:
        """Call TypeSafe Jev Decision model on OpenRouter (/api/alpha/decisions)."""
        criteria: dict[str, str] = {}
        candidate_map: dict[str, PrecedentWorkflowItem] = {}

        for c in candidates[:6]:
            criteria[c.id] = (
                f"{c.title} (violation={c.violation_code}, claim={c.claim_type}, "
                f"verdict={c.verdict}): {c.driver_statement_summary}"
            )
            candidate_map[c.id] = c
        criteria["none"] = "None of the historical precedents match this dispute situation."

        state_payload = {
            "dispute_case_id": case_id,
            "violation_code": violation_code,
            "claim_type": claim_type,
            "driver_statement": driver_statement,
            "telemetry_corroboration": telemetry_summary,
        }

        request_body = {
            "model": self.settings.jev_model,
            "state": state_payload,
            "questions": {
                "matched_precedent": {
                    "type": "choice",
                    "instructions": (
                        "Select the historical precedent workflow that best matches the current driver dispute, "
                        "considering the alleged violation, driver rationale, and corridor telemetry."
                    ),
                    "criteria": criteria,
                }
            },
        }

        headers = {
            "Authorization": f"Bearer {self.settings.openrouter_api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/AI20K-Build-Phase-Cohort-4/P-063",
            "X-Title": "P-063 Precedent Workflow Jev Matcher",
        }

        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.post(OPENROUTER_DECISIONS_URL, headers=headers, json=request_body)
            if resp.status_code != 200:
                raise RuntimeError(f"OpenRouter Jev returned HTTP {resp.status_code}: {resp.text}")

            res_json = resp.json()
            answers = res_json.get("answers", {})
            match_answer = answers.get("matched_precedent", {})
            chosen_id = match_answer.get("choice")
            confidence = float(match_answer.get("confidence", 0.90))

            if not chosen_id or chosen_id == "none" or chosen_id not in candidate_map:
                # Fallback to heuristic
                return self._match_with_heuristic(
                    case_id, claim_type, driver_statement, violation_code, telemetry_summary, candidates
                )

            chosen = candidate_map[chosen_id]

            # Extract procedure recommendations
            recommended_tools = [t.tool_name for t in chosen.workflow_trace.agent_tools_called]
            factors = [
                f"Độ tin cậy Jev Decision AI: {int(confidence * 100)}%",
                f"Trùng khớp mã vi phạm: {chosen.violation_code}",
                f"Tương đồng tình huống khiếu nại: {chosen.claim_type}",
            ]
            if chosen.district:
                factors.append(f"Khu vực địa lý tương đồng: {chosen.district}")

            return PrecedentSimilarityMatch(
                precedent_id=chosen.id,
                precedent_case_id=chosen.case_id,
                title=chosen.title,
                similarity_score=round(confidence, 2),
                matching_factors=factors,
                recommended_procedure=recommended_tools,
                precedent_verdict=chosen.verdict,
                confidence_rationale=(
                    f"Mô hình TypeSafe Jev ({res_json.get('model', 'jev')}) nhận diện độ tương đồng cao "
                    f"với án lệ '{chosen.title}'. Đề xuất áp dụng quy trình xử lý tiền lệ."
                ),
                model_used="jev",
                score_semantics=SCORE_SEMANTICS,
                provenance=chosen.provenance,
                precedent_workflow=chosen.workflow_trace,
            )

    def _compute_heuristic_score(
        self,
        candidate: PrecedentWorkflowItem,
        violation_code: str | None,
        claim_type: str | None,
        driver_statement: str | None,
        telemetry: dict[str, Any] | None,
    ) -> float:
        """Calculate normalized [0.0, 1.0] similarity score using multi-attribute distance."""
        score = 0.0

        # 1. Violation code exact match (35%)
        if violation_code and candidate.violation_code.upper() == violation_code.upper():
            score += 0.35

        # 2. Claim type match (30%)
        if claim_type and candidate.claim_type.lower() == claim_type.lower():
            score += 0.30
        elif claim_type and ("traffic" in claim_type and "traffic" in candidate.claim_type):
            score += 0.25

        # 3. Statement keyword overlap (20%)
        if driver_statement and candidate.driver_statement_summary:
            statement_tokens = set(driver_statement.lower().replace(",", " ").replace(".", " ").split())
            candidate_tokens = set(
                candidate.driver_statement_summary.lower().replace(",", " ").replace(".", " ").split()
            )
            common = statement_tokens.intersection(candidate_tokens)
            if common:
                jaccard = len(common) / max(len(statement_tokens.union(candidate_tokens)), 1)
                score += min(0.20, jaccard * 1.5)

        # 4. Telemetry corroboration match (15%)
        if telemetry:
            is_corroborated = telemetry.get("corroborated", False)
            cand_verdict = candidate.verdict
            if (is_corroborated and cand_verdict == "exonerated") or (
                not is_corroborated and cand_verdict != "exonerated"
            ):
                score += 0.15

        return round(min(1.0, max(0.1, score)), 2)

    def _match_with_heuristic(
        self,
        case_id: str,
        claim_type: str | None,
        driver_statement: str | None,
        violation_code: str | None,
        telemetry_summary: dict[str, Any] | None,
        candidates: list[PrecedentWorkflowItem],
    ) -> PrecedentSimilarityMatch:
        """Deterministic heuristic similarity computation."""
        scored: list[tuple[float, PrecedentWorkflowItem]] = []
        for c in candidates:
            s = self._compute_heuristic_score(c, violation_code, claim_type, driver_statement, telemetry_summary)
            scored.append((s, c))

        scored.sort(key=lambda x: x[0], reverse=True)
        best_score, best_candidate = scored[0]

        factors = [
            f"Trùng khớp mã vi phạm {best_candidate.violation_code} (+35%)",
            f"Trùng khớp lý do khiếu nại {best_candidate.claim_type} (+30%)",
        ]
        if best_candidate.district:
            factors.append(f"Khu vực đối chiếu: {best_candidate.district}")

        recommended_tools = [t.tool_name for t in best_candidate.workflow_trace.agent_tools_called]

        return PrecedentSimilarityMatch(
            precedent_id=best_candidate.id,
            precedent_case_id=best_candidate.case_id,
            title=best_candidate.title,
            similarity_score=best_score,
            matching_factors=factors,
            recommended_procedure=recommended_tools,
            precedent_verdict=best_candidate.verdict,
            confidence_rationale=(
                f"Thuật toán đối soát tiền lệ xác định độ tương đồng {int(best_score * 100)}% "
                f"dựa trên vi phạm {best_candidate.violation_code} và phân loại {best_candidate.claim_type}."
            ),
            model_used="heuristic_fallback",
            score_semantics=SCORE_SEMANTICS,
            provenance=best_candidate.provenance,
            precedent_workflow=best_candidate.workflow_trace,
        )

    def synthesize_workflow_trace(
        self,
        case_id: str,
        decision_data: dict[str, Any] | None = None,
    ) -> WorkflowTrace:
        """Build a test fallback from recorded in-memory facts only."""
        cid = str(case_id).strip()
        canonical_id = self.case_service._case_aliases.get(cid, cid)
        tools_called: list[WorkflowToolCall] = []
        corrob = self.case_service._traffic_corroborations.get(canonical_id)
        if corrob:
            tools_called.append(
                WorkflowToolCall(
                    tool_name="corroborate_traffic_conditions",
                    input_summary=f"corridor_case={canonical_id}",
                    output_summary=json.dumps(corrob, ensure_ascii=False, sort_keys=True, default=str),
                    executed_at=corrob.get("created_at"),
                    status="success",
                    source_ref=f"in_memory_traffic_corroboration:{canonical_id}",
                )
            )
        human_actions: list[WorkflowHumanAction] = []
        if canonical_id in self.case_service._agent_sessions:
            sid = self.case_service._agent_sessions[canonical_id]["session_id"]
            msgs = self.case_service._agent_messages.get(sid, [])
            for m in msgs:
                role = m.get("role")
                content = str(m.get("content", ""))
                ts = m.get("timestamp")
                if role == "driver":
                    human_actions.append(
                        WorkflowHumanAction(
                            actor_id=str(m["actor_id"]) if m.get("actor_id") else None,
                            actor_role="driver",
                            action_type="dispute_statement",
                            summary=content,
                            timestamp=ts,
                            source_ref=f"in_memory_message:{m.get('id', len(human_actions))}",
                        )
                    )
                elif role in {"analyst", "user"}:
                    human_actions.append(
                        WorkflowHumanAction(
                            actor_id=str(m["actor_id"]) if m.get("actor_id") else None,
                            actor_role="analyst",
                            action_type="analyst_message",
                            summary=content,
                            timestamp=ts,
                            source_ref=f"in_memory_message:{m.get('id', len(human_actions))}",
                        )
                    )

        # 3. Driver statement summary
        driver_summary = ""
        for h in human_actions:
            if h.actor_role == "driver":
                driver_summary = h.summary
        final_decision: WorkflowDecision | None = None
        if decision_data:
            required = ("verdict", "rationale", "decided_by", "decided_at")
            if not all(decision_data.get(key) for key in required):
                raise ValueError("Recorded decision data is incomplete")
            final_decision = WorkflowDecision(
                verdict=str(decision_data["verdict"]),
                penalty_amount=int(decision_data.get("penalty_amount", 0)),
                rationale=str(decision_data["rationale"]),
                decided_by=str(decision_data["decided_by"]),
                decided_at=str(decision_data["decided_at"]),
                adjudication_id=decision_data.get("adjudication_id"),
                evidence_snapshot_id=decision_data.get("evidence_snapshot_id"),
                policy_version_id=decision_data.get("policy_version_id"),
                request_hash=decision_data.get("request_hash"),
                explicit_human_approval=bool(decision_data.get("explicit_human_approval", False)),
            )

        trace = WorkflowTrace(
            agent_tools_called=tools_called,
            human_actions_performed=human_actions,
            driver_response_summary=driver_summary,
            related_policies=[],
            final_decision=final_decision,
            trace_id=decision_data.get("trace_id") if decision_data else None,
            agent_run_id=decision_data.get("agent_run_id") if decision_data else None,
            source_refs=[f"in_memory_case:{canonical_id}"],
            timeline=[],
        )

        self._case_workflow_traces[canonical_id] = trace
        return trace

    def get_workflow_trace(self, case_id: str, organization_id: str | None = None) -> WorkflowTrace:
        """Retrieve an immutable finalized trace, with a test-only fallback."""
        cid = str(case_id).strip()
        canonical_id = self.case_service._case_aliases.get(cid, cid)
        conn = self._get_db_connection()
        if conn:
            try:
                if not organization_id:
                    return WorkflowTrace(source_refs=[f"case:{canonical_id}"])
                item = get_finalized_by_case(conn, case_id=canonical_id, organization_id=organization_id)
                if item:
                    base = item.workflow_trace
                else:
                    with conn.cursor() as cur:
                        cur.execute(
                            "SELECT workflow_trace FROM app.fraud_cases WHERE id = %s AND organization_id = %s",
                            (canonical_id, organization_id),
                        )
                        row = cur.fetchone()
                    base = WorkflowTrace.model_validate(row.get("workflow_trace") or {}) if row else WorkflowTrace()
                # A saved draft is a recorded workflow event even before adjudication.
                timeline = [*base.timeline, *_load_case_timeline(conn, canonical_id)]
                unique = {(event.event_type, event.occurred_at, event.label): event for event in timeline}
                return base.model_copy(
                    update={"timeline": sorted(unique.values(), key=lambda event: event.occurred_at)}
                )
            finally:
                conn.close()
        recorded = self.case_service._cases.get(canonical_id, {}).get("workflow_trace")
        if recorded:
            return WorkflowTrace.model_validate(recorded)
        if canonical_id in self._case_workflow_traces:
            cached = self._case_workflow_traces[canonical_id]
            return cached.model_copy(update={"timeline": list(cached.timeline or [])})
        return self.synthesize_workflow_trace(canonical_id).model_copy(update={"timeline": []})

    async def publish_precedent_workflow(
        self,
        case_id: str,
        title: str,
        workflow_trace: WorkflowTrace,
        verdict: str,
        district: str | None = None,
        confidence_score: float = 0.95,
        organization_id: str | None = None,
        published_by: str | None = None,
    ) -> PrecedentWorkflowItem:
        """Publish from authoritative linked records; never trust a supplied trace."""
        _ = (title, workflow_trace, verdict, district, confidence_score)
        if not organization_id or not published_by:
            raise PrecedentPersistenceError("Tenant and signing analyst are required")
        conn = self._get_db_connection()
        if not conn:
            raise PrecedentPersistenceError("Database is required for durable precedent publication")
        try:
            item = publish_finalized(
                conn,
                case_id=case_id,
                organization_id=organization_id,
                published_by=published_by,
            )
            conn.commit()
            return item
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def apply_precedent_procedure(
        self,
        case_id: str,
        precedent_id: str,
        *,
        organization_id: str | None = None,
        actor_id: str | None = None,
        request_id: str | None = None,
    ) -> dict[str, Any]:
        """Record advisory reuse without modifying either historical decision."""
        precedent = self.get_precedent(precedent_id, organization_id=organization_id)
        if not precedent:
            raise ValueError(f"Precedent with ID '{precedent_id}' not found.")

        reuse_history_id: str | None = None
        if organization_id and actor_id:
            conn = self._get_db_connection()
            if not conn:
                raise PrecedentPersistenceError("Database is required to record precedent reuse")
            try:
                reuse_history_id = record_application_from_latest_view(
                    conn,
                    organization_id=organization_id,
                    current_case_id=case_id,
                    precedent_id=precedent_id,
                    actor_id=actor_id,
                    request_id=request_id,
                )
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()

        rec_verdict = precedent.verdict
        rec_penalty = (
            precedent.workflow_trace.final_decision.penalty_amount if precedent.workflow_trace.final_decision else 0
        )
        rec_rationale = (
            f"[Áp dụng quy trình án lệ #{precedent.id[:8]} - '{precedent.title}'] "
            f"{precedent.workflow_trace.final_decision.rationale if precedent.workflow_trace.final_decision else ''}"
        )

        return {
            "case_id": case_id,
            "precedent_id": precedent.id,
            "precedent_title": precedent.title,
            "recommended_verdict": rec_verdict,
            "recommended_penalty_amount": rec_penalty,
            "recommended_rationale": rec_rationale,
            "policy_citations": [p.model_dump() for p in precedent.workflow_trace.related_policies],
            "recommended_tools": [t.tool_name for t in precedent.workflow_trace.agent_tools_called],
            "score_semantics": SCORE_SEMANTICS,
            "advisory_only": True,
            "decision_unchanged": True,
            "reuse_history_id": reuse_history_id,
            "applied_at": datetime.now(UTC).isoformat(),
        }


_jev_precedent_service_instance: JevPrecedentService | None = None


def get_jev_precedent_service() -> JevPrecedentService:
    """Singleton getter for JevPrecedentService."""
    global _jev_precedent_service_instance
    if _jev_precedent_service_instance is None:
        _jev_precedent_service_instance = JevPrecedentService()
    return _jev_precedent_service_instance

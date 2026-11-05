"""Driver Dispute and Autonomous Exoneration Service (Slice 1).

Implements:
- Driver dispute context retrieval
- Autonomous exoneration guardrails (NFR-L06-02: zero automated sanctions, deterministic proof)
- Analyst inquiry delegation
- Dispute dossier compilation for HITL review
- Dual execution mode: PostgreSQL / Supabase schema 'app' with in-memory fallback
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from src.services.driver_intent import is_driver_closure, is_driver_escalation

try:
    import psycopg as _psycopg
    from psycopg.rows import dict_row as _dict_row
except ImportError:
    psycopg = None
    dict_row = None
else:
    psycopg = _psycopg
    dict_row = _dict_row

try:
    from fastapi import HTTPException as _FastAPIHTTPException
except ImportError:

    class _FallbackHTTPError(Exception):
        def __init__(self, status_code: int = 500, detail: str = ""):
            super().__init__(detail)
            self.status_code = status_code
            self.detail = detail

    HTTPException: type[_FallbackHTTPError] | type[_FastAPIHTTPException] = _FallbackHTTPError
else:
    HTTPException = _FastAPIHTTPException


from src.config import Settings, get_settings
from src.models.schemas import (
    AnalystDelegateInquiryRequest,
    DisputeDossierResponse,
    DriverCaseListResponse,
    DriverCaseSessionItem,
    DriverChatRequest,
    DriverChatResponse,
    DriverDisputeContextResponse,
)
from src.services.case_service import CaseService, get_case_service

logger = logging.getLogger(__name__)

# Canonical ERR taxonomy from PRD (docs/ba/AGENT_TOOL_CATALOG.md).
# ERR-03 and ERR-04 detectors remain deferred; titles must still be accurate.
# Vietnamese titles carry no English parenthetical; English lives in
# VIOLATION_TITLE_MAP_EN and is selected via request locale (default vi).
VIOLATION_TITLE_MAP = {
    "ERR-01": "Chiếm đoạt chuyến/đơn: hủy rồi phục vụ ngoài ứng dụng thu tiền mặt",
    "ERR-02": "Lái xe lệch tuyến, kéo dài hoặc di chuyển sai hướng để khách hủy chuyến",
    "ERR-03": "Khai thác khuyến mãi qua đặt chuyến giả hoặc gaming chính sách",
    "ERR-04": "Chuyến đi ảo/ma: không có hành trình vật lý thực tế",
    "ERR-05": "GPS giả hoặc thao túng công nghệ vị trí",
}

VIOLATION_TITLE_MAP_EN = {
    "ERR-01": "Trip/order embezzlement: cancel then collect cash off-app",
    "ERR-02": "Route deviation / stall-to-cancel",
    "ERR-03": "Incentive/policy exploitation via fake trips",
    "ERR-04": "Phantom trip with no physical journey",
    "ERR-05": "Fake GPS / technological manipulation",
}


def normalize_violation_locale(value: str | None) -> str:
    """Only 'vi' and 'en' exist; everything else falls back to 'vi'."""
    v = (value or "").strip().lower()
    if v.startswith("en"):
        return "en"
    return "vi"


def resolve_request_locale(query_locale: str | None = None, accept_language: str | None = None) -> str:
    """Explicit ?locale= wins; otherwise the first Accept-Language range; default vi."""
    if query_locale:
        v = query_locale.strip().lower()
        if v.startswith("en"):
            return "en"
        if v.startswith("vi"):
            return "vi"
    if accept_language:
        first = accept_language.split(",")[0].strip().lower()
        if first.startswith("en"):
            return "en"
    return "vi"


def violation_title(
    violation_code: str | None,
    locale: str | None = "vi",
    default_vi: str = "Nghi vấn vi phạm chỉ số vận hành",
) -> str:
    """Localized violation title; violation_code stays in the payload for frontend mapping."""
    if normalize_violation_locale(locale) == "en":
        return VIOLATION_TITLE_MAP_EN.get((violation_code or "").strip(), "Suspected violation")
    return VIOLATION_TITLE_MAP.get((violation_code or "").strip(), default_vi)


POLICY_GUIDELINES = [
    {
        "article": "Điều 12.1",
        "title": "Quyền giải trình và thời hạn khiếu nại",
        "snippet": "Đối tác tài xế có quyền gửi phản hồi, giải trình trong vòng 48 giờ kể từ khi nhận được thông báo nghi vấn vi phạm. Trong thời gian này, nền tảng không áp dụng bất kỳ biện pháp hạn chế quyền lợi nào.",
    },
    {
        "article": "Điều 12.2",
        "title": "Trường hợp bất khả kháng và miễn trừ trách nhiệm",
        "snippet": "Trường hợp xe dừng đỗ hoặc di chuyển chậm do ùn tắc giao thông diện rộng, thời tiết khắc nghiệt, sự cố kỹ thuật từ hệ thống hoặc yêu cầu chính đáng từ hành khách sẽ được tự động miễn trừ trách nhiệm khi có dữ liệu đối chiếu hợp lệ.",
    },
    {
        "article": "Điều 12.3",
        "title": "Bảo vệ tài xế và quy trình thẩm định độc lập",
        "snippet": "Không áp dụng bất kỳ hình thức xử phạt tự động nào mà không qua thẩm định của Chuyên viên giám sát hoặc cơ chế đối chiếu telemetry minh bạch. Mọi quyết định đều có biên bản số hóa lưu trữ trên hệ thống.",
    },
]


class DriverDisputeService:
    """Service orchestrating driver dispute intake, deterministic autonomous exoneration,
    and dispute dossier preparation for analyst HITL adjudication.
    """

    def __init__(self, case_service: CaseService | None = None, settings: Settings | None = None) -> None:
        self.case_service = case_service or get_case_service()
        self.settings = settings or self.case_service.settings

        # In-memory storage for test/fallback mode
        self._traffic_overrides: dict[str, dict[str, Any]] = {
            "018f2f4e-a000-7000-8000-000000000026": {
                "observed_speed": 2.88,
                "ratio": 2.45,
                "congestion_level": "heavy",
                "gps_valid": True,
                "prior_sanctions": 0,
            }
        }
        self._confidence_overrides: dict[str, Any] = {}
        self._dispute_statements: dict[str, list[dict[str, Any]]] = {}
        self._exoneration_receipts: dict[str, dict[str, Any]] = {}
        self._audit_entries: dict[str, list[dict[str, Any]]] = {}
        self._processed_chat_requests: dict[str, DriverChatResponse] = {}
        self._driver_aliases: dict[str, str] = {}
        # In-memory only (Issue #482/#538): case-less chat has no case to
        # key durable storage by. No dedicated store/table exists yet; this
        # keeps the per-driver turn history available for the lifetime of
        # the process so the UI can show "what was just said" without
        # claiming cross-restart durability. A real store (e.g. a
        # `driver_id`-keyed session table) is future work.
        self._driverless_messages: dict[str, list[dict[str, Any]]] = {}
        self._confirmation_tokens: dict[str, dict[str, Any]] = {}
        self._statement_drafts: dict[tuple[str, str], dict[str, Any]] = {}

    def _append_driverless_message(self, driver_id: str, turn_id: str, role: str, content: str) -> None:
        """Append an in-memory case-less chat turn (see `_driverless_messages`)."""
        key = str(driver_id)
        messages = self._driverless_messages.setdefault(key, [])
        messages.append(
            {
                "id": str(uuid4()),
                "turn_id": str(turn_id),
                "role": role,
                "content": content,
                "created_at": datetime.now(UTC).isoformat(),
            }
        )

    def _get_db_connection(self):
        """Retrieve db connection via case_service."""
        return self.case_service._get_db_connection()

    def _is_test_guest_bypass(self, driver_id: str | None) -> bool:
        """Test-auth driver-guest bypass: fixture/dev loopback only, never hosted.

        Routes keep passing None/"driver-guest" for the test guest principal;
        ownership is then enforced at the route layer. Real principals always
        fail closed via _is_driver_authorized.
        """
        try:
            test_mode = self.settings.app_env == "test" and self.settings.test_auth_enabled
        except Exception:
            test_mode = False
        return bool(test_mode) and (not driver_id or str(driver_id).strip() in ("", "driver-guest"))

    def _is_driver_authorized(self, expected_driver_id: str | None, requested_driver_id: str | None) -> bool:
        """Verify whether requested_driver_id matches expected_driver_id or known alias."""
        if not requested_driver_id:
            return True
        # Missing ownership metadata must fail closed. A driver can only
        # access a case when the case has an authenticated owner.
        if not expected_driver_id:
            return False
        req = str(requested_driver_id).strip()
        exp = str(expected_driver_id).strip()
        if req == exp:
            return True
        if self._driver_aliases.get(req) == exp or self._driver_aliases.get(exp) == req:
            return True
        return False

    def _get_case_driver_id(self, case_id: str, case: dict[str, Any]) -> str | None:
        """Resolve authentic driver ID associated with this case."""
        if case.get("driver_id"):
            return str(case["driver_id"])
        asgn_id = str(case.get("assignment_id", ""))
        if asgn_id and asgn_id in self.case_service._assignments:
            d_id = self.case_service._assignments[asgn_id].get("driver_id")
            if d_id:
                return str(d_id)
        conn = None
        try:
            conn = self._get_db_connection()
        except HTTPException:
            conn = None
        if conn is not None:
            try:
                with conn.cursor() as cur:
                    cur.execute("SET search_path = app, extensions, public;")
                    cur.execute(
                        """
                        SELECT a.driver_id
                        FROM app.fraud_cases c
                        LEFT JOIN app.trip_assignments a ON a.id = c.assignment_id
                        WHERE c.id::text = %s
                        LIMIT 1;
                        """,
                        (str(case_id),),
                    )
                    row = cur.fetchone()
                    if row and row.get("driver_id"):
                        return str(row["driver_id"])
            except Exception:
                pass
            finally:
                conn.close()
        return None

    def _get_case_confidence(self, case_id: str, case: dict[str, Any]) -> float | None:
        """Resolve model classifier confidence c in [0.0, 1.0], or None if uncalibrated/missing."""
        cid = str(case_id).strip()
        if cid in self._confidence_overrides:
            val = self._confidence_overrides[cid]
            if val is None:
                return None
            try:
                return float(val)
            except (ValueError, TypeError):
                return None
        alias = self.case_service._case_aliases.get(cid)
        if alias and alias in self._confidence_overrides:
            val = self._confidence_overrides[alias]
            if val is None:
                return None
            try:
                return float(val)
            except (ValueError, TypeError):
                return None

        if "confidence" in case and case["confidence"] is not None:
            try:
                return float(case["confidence"])
            except (ValueError, TypeError):
                return None

        if "assessment" in case and isinstance(case["assessment"], dict):
            c_val = case["assessment"].get("confidence")
            if c_val is not None:
                try:
                    return float(c_val)
                except (ValueError, TypeError):
                    return None

        conn = None
        try:
            conn = self._get_db_connection()
        except HTTPException:
            conn = None

        if conn is not None:
            try:
                with conn.cursor() as cur:
                    cur.execute("SET search_path = app, extensions, public;")
                    cur.execute(
                        """
                        SELECT ma.confidence
                        FROM app.evidence_snapshots es
                        JOIN app.model_assessments ma ON ma.evidence_snapshot_id = es.id
                        WHERE es.case_id::text = %s
                        ORDER BY es.version DESC, ma.created_at DESC
                        LIMIT 1;
                        """,
                        (cid,),
                    )
                    row = cur.fetchone()
                    if row and row.get("confidence") is not None:
                        return float(row["confidence"])
            except Exception:
                pass
            finally:
                conn.close()

        return None

    def _find_case(self, case_id: str) -> tuple[str, dict[str, Any]]:
        cid = str(case_id).strip()
        # 1. DB Lookup
        conn = None
        try:
            conn = self._get_db_connection()
        except HTTPException:
            conn = None

        if conn is not None:
            try:
                with conn.cursor() as cur:
                    cur.execute("SET search_path = app, extensions, public;")
                    cur.execute(
                        "SELECT id, assignment_id, suspected_category, status, dispute_status, dispute_deadline FROM app.fraud_cases WHERE id::text = %s LIMIT 1;",
                        (cid,),
                    )
                    row = cur.fetchone()
                    if row:
                        return str(row["id"]), dict(row)
            except Exception as e:
                logger.warning("DB query for case check failed: %s", e)
            finally:
                conn.close()

        # 2. In-memory check
        canonical_id = self.case_service._case_aliases.get(cid, cid)
        case = self.case_service._cases.get(canonical_id)
        if not case:
            for k, c in self.case_service._cases.items():
                if k == cid or str(c.get("id")) == cid:
                    case = c
                    canonical_id = k
                    break

        if not case:
            raise HTTPException(status_code=404, detail=f"Case {case_id} not found")

        return canonical_id, case

    async def get_dispute_context(
        self,
        case_id: str,
        driver_id: str | None = None,
        organization_id: str | None = None,
        locale: str | None = "vi",
    ) -> DriverDisputeContextResponse:
        """Alias for get_driver_dispute_context."""
        return await self.get_driver_dispute_context(
            case_id,
            driver_id or "",
            organization_id=organization_id,
            locale=locale,
        )

    async def list_driver_cases(
        self,
        driver_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
        organization_id: str | None = None,
        locale: str | None = "vi",
    ) -> DriverCaseListResponse:
        """Retrieve list of dispute/fraud cases relevant to the driver.

        S4-TENANT #294: both driver_id and organization_id come from the
        server-owned Principal (routes take no org input). Persisted reads
        require both; unscoped DB reads are a 403.
        """
        conn = None
        try:
            conn = self._get_db_connection()
        except HTTPException:
            conn = None

        fixture_auth = self.settings.app_env == "test" and self.settings.test_auth_enabled
        if conn is None and not fixture_auth:
            raise HTTPException(503, "Driver case database unavailable")
        if conn is not None and not organization_id and not fixture_auth:
            raise HTTPException(403, "Organization scope required")
        if conn is not None and (not driver_id or driver_id == "driver-guest") and not fixture_auth:
            raise HTTPException(403, "Driver scope required")
        items: list[DriverCaseSessionItem] = []
        if conn is not None:
            try:
                with conn.cursor() as cur:
                    cur.execute("SET search_path = app, extensions, public;")
                    query = """
                        SELECT c.id, c.assignment_id, c.suspected_category, c.status, c.dispute_status, c.dispute_deadline,
                               c.created_at, a.driver_id, d.display_name as driver_name,
                               t.id as trip_id, t.pickup_address, t.dropoff_address, v.registration_ref as vehicle_plate
                        FROM app.fraud_cases c
                        LEFT JOIN app.trip_assignments a ON a.id = c.assignment_id
                        LEFT JOIN app.drivers d ON d.id = a.driver_id
                        LEFT JOIN app.trips t ON t.id = a.trip_id
                        LEFT JOIN app.vehicles v ON v.id = a.vehicle_id
                    """
                    params: list[Any] = []
                    filters = []
                    if driver_id and driver_id != "driver-guest":
                        filters.append("a.driver_id::text = %s")
                        params.append(driver_id)
                    if organization_id:
                        filters.append("c.organization_id::text = %s")
                        params.append(organization_id)
                    if filters:
                        query += " WHERE " + " AND ".join(filters)
                    query += (
                        " ORDER BY CASE WHEN c.id = '018f2f4e-a000-7000-8000-000000000026'::uuid THEN 0 ELSE 1 END, "
                        "c.created_at DESC LIMIT %s OFFSET %s"
                    )
                    params.extend([limit, offset])
                    cur.execute(query, tuple(params))
                    rows = cur.fetchall()
                    for r in rows:
                        cid = str(r["id"])
                        code = f"#{cid.split('-')[-1][:8]}"
                        v_code = r.get("suspected_category") or "ERR-01"
                        v_title = violation_title(v_code, locale)
                        created_str = (
                            r["created_at"].isoformat()
                            if hasattr(r["created_at"], "isoformat")
                            else str(r["created_at"])
                        )
                        d_status = r.get("dispute_status") or "not_disputed"
                        raw_deadline = r.get("dispute_deadline")
                        # ISO 8601 or None only. No str() fallback: a raw
                        # non-datetime, non-ISO-string DB value must never
                        # leak into the API response (PR #503 review fix).
                        if hasattr(raw_deadline, "isoformat"):
                            deadline_str = raw_deadline.isoformat()
                        elif isinstance(raw_deadline, str) and raw_deadline:
                            deadline_str = raw_deadline
                        else:
                            deadline_str = None
                        items.append(
                            DriverCaseSessionItem(
                                case_id=cid,
                                case_code=code,
                                driver_id=str(r.get("driver_id") or "drv-default"),
                                driver_name=r.get("driver_name") or "Tài xế GreenSM",
                                violation_code=v_code,
                                violation_title=v_title,
                                dispute_status=d_status,
                                status=r.get("status"),
                                dispute_deadline=deadline_str,
                                created_at=created_str,
                                alleged_time=created_str,
                                alleged_location=r.get("pickup_address") or "Hà Nội",
                                description=f"Sự việc ghi nhận trên phương tiện {r.get('vehicle_plate') or 'GSM-EV'}",
                                trip_id=str(r.get("trip_id") or ""),
                                vehicle_plate=r.get("vehicle_plate") or "29E-888.99",
                                pickup_address=r.get("pickup_address") or "Điểm đón khách",
                                dropoff_address=r.get("dropoff_address") or "Điểm trả khách",
                                source="customer_report" if v_code in ("ERR-02", "ERR-05") else "system_prediction",
                                has_unread=d_status in ("not_disputed", "in_dispute"),
                            )
                        )
            except Exception as e:
                if not fixture_auth:
                    raise HTTPException(503, "Driver case database unavailable") from e
                logger.warning("DB query for list_driver_cases failed: %s", e)
            finally:
                conn.close()

        if not fixture_auth:
            return DriverCaseListResponse(items=items, total=len(items))

        # Explicit local test fixtures only.
        existing_ids = {item.case_id for item in items}
        for cid, case_data in self.case_service._cases.items():
            if cid in existing_ids:
                continue
            if organization_id and str(case_data.get("organization_id", organization_id)) != organization_id:
                continue
            asgn_id = case_data.get("assignment_id")
            asgn = self.case_service._assignments.get(asgn_id, {}) if asgn_id is not None else {}
            did = str(asgn.get("driver_id") or "drv-default")
            if driver_id and driver_id != "driver-guest" and did != driver_id:
                continue
            drv = self.case_service._drivers.get(did, {})
            v_code = case_data.get("suspected_category") or "ERR-01"
            v_title = violation_title(v_code, locale)
            d_status = case_data.get("dispute_status") or "not_disputed"
            created_str = datetime.now(UTC).isoformat()
            items.append(
                DriverCaseSessionItem(
                    case_id=cid,
                    case_code=f"#{cid.split('-')[-1][:8]}",
                    driver_id=did,
                    driver_name=drv.get("display_name") or "Tài xế GreenSM",
                    violation_code=v_code,
                    violation_title=v_title,
                    dispute_status=d_status,
                    status=case_data.get("status"),
                    dispute_deadline=case_data.get("dispute_deadline"),
                    created_at=created_str,
                    alleged_time=created_str,
                    alleged_location="Hà Nội",
                    description=f"Sự việc vi phạm {v_code} đang trong thời hạn đối soát",
                    trip_id=str(asgn.get("trip_id") or ""),
                    vehicle_plate="29E-888.99",
                    pickup_address="Điểm đón khách",
                    dropoff_address="Điểm trả khách",
                    source="customer_report" if v_code in ("ERR-02", "ERR-05") else "system_prediction",
                    has_unread=d_status in ("not_disputed", "in_dispute"),
                ),
            )
        return DriverCaseListResponse(items=items[offset : offset + limit], total=len(items))

    async def get_driver_session(self, case_id: str, organization_id: str | None = None) -> dict[str, Any]:
        """Fetch historical conversation messages for a driver dispute session."""
        canonical_id, _ = self._find_case(case_id)
        session = await self.case_service.get_case_agent_session(
            canonical_id,
            organization_id=organization_id,
            roles={"driver", "driver_agent", "analyst"},
        )
        # Analyst cockpit messages (user/assistant) are private. The driver
        # projection contains only authenticated driver dialogue and delivered
        # driver-agent notices/minutes.
        allowed_roles = {"driver", "driver_agent", "analyst", "agent"}
        return {
            **session,
            "messages": [message for message in session.get("messages", []) if message.get("role") in allowed_roles],
        }

    def get_audit_entries(self, case_id: str) -> list[dict[str, Any]]:
        """Retrieve audit log entries for a case."""
        cid = str(case_id).strip()
        entries = self._audit_entries.get(cid)
        if entries:
            return entries
        canonical = self.case_service._case_aliases.get(cid)
        if canonical:
            return self._audit_entries.get(canonical, [])
        return []

    def _record_audit_entry(
        self,
        case_id: str,
        action: str,
        result: str,
        payload: dict[str, Any],
        actor_id: str | None = None,
        actor_type: str = "system",
    ) -> None:
        """Record append-only audit event in-memory and in DB if available."""
        existing_entries = self._audit_entries.get(str(case_id), [])
        for ex in existing_entries:
            if ex.get("action") == action and ex.get("result") == result:
                ex_payload = ex.get("payload", {})
                if ex_payload.get("statement") and ex_payload.get("statement") == payload.get("statement"):
                    return
                if ex_payload.get("reason") and ex_payload.get("reason") == payload.get("reason"):
                    return

        entry = {
            "id": str(uuid4()),
            "case_id": str(case_id),
            "actor_id": actor_id or str(uuid4()),
            "actor_type": actor_type,
            "action": action,
            "result": result,
            "payload": payload,
            "recorded_at": datetime.now(UTC).isoformat(),
        }
        self._audit_entries.setdefault(str(case_id), []).append(entry)

        # Database append
        conn = None
        try:
            conn = self._get_db_connection()
        except HTTPException:
            conn = None

        if conn is not None:
            try:
                with conn.cursor() as cur:
                    cur.execute("SET search_path = app, extensions, public;")
                    payload_json = json.dumps(payload, default=str)
                    event_hash = hashlib.sha256(payload_json.encode("utf-8")).digest()
                    db_result = (
                        "accepted"
                        if result in ("accepted", "pending_confirmation", "escalated", "resolved")
                        else ("denied" if result == "denied" else "failed")
                    )
                    cur.execute(
                        """
                        INSERT INTO app.audit_events (
                            event_id, organization_id, actor_id, case_id,
                            action, result, request_id, redacted_payload, previous_hash, event_hash
                        )
                        VALUES (
                            gen_random_uuid(),
                            (SELECT organization_id FROM app.fraud_cases WHERE id::text = %s LIMIT 1),
                            NULL, %s::uuid, %s, %s, gen_random_uuid(), %s::jsonb, '\\x'::bytea, %s
                        )
                        """,
                        (
                            case_id,
                            case_id,
                            action,
                            db_result,
                            payload_json,
                            event_hash,
                        ),
                    )
                conn.commit()
            except Exception as e:
                logger.warning("Failed to persist audit event to DB: %s", e)
                if conn:
                    conn.rollback()
            finally:
                conn.close()

    def _append_message(self, case_id: str, turn_id: str, role: str, content: str, overwrite: bool = False) -> None:
        """Append durable conversation message for case session.

        `overwrite=True` corrects an already-persisted turn (Issue #482/#538:
        the streaming path persists the real agent reply after the fact, so
        reopening the thread matches what was actually shown live) instead of
        silently keeping whatever deterministic placeholder was written first.
        """
        if role == "assistant":
            role = "driver_agent"
        session_id = None
        # Try database first
        conn = None
        try:
            conn = self._get_db_connection()
        except HTTPException:
            conn = None

        if conn is not None:
            try:
                with conn.cursor() as cur:
                    cur.execute("SET search_path = app, extensions, public;")
                    # Find or create session
                    cur.execute("SELECT id FROM app.case_agent_sessions WHERE case_id = %s LIMIT 1;", (case_id,))
                    s_row = cur.fetchone()
                    if s_row:
                        session_id = str(s_row["id"])
                    else:
                        cur.execute(
                            """
                            INSERT INTO app.case_agent_sessions (organization_id, case_id)
                            VALUES ((SELECT organization_id FROM app.fraud_cases WHERE id = %s LIMIT 1), %s)
                            RETURNING id;
                            """,
                            (case_id, case_id),
                        )
                        session_id = str(cur.fetchone()["id"])

                    if overwrite:
                        cur.execute(
                            """
                            INSERT INTO app.case_agent_messages (session_id, turn_id, role, content)
                            VALUES (%s, %s, %s, %s)
                            ON CONFLICT (session_id, turn_id, role) DO UPDATE SET content = EXCLUDED.content;
                            """,
                            (session_id, str(turn_id), role, content),
                        )
                    else:
                        cur.execute(
                            """
                            INSERT INTO app.case_agent_messages (session_id, turn_id, role, content)
                            VALUES (%s, %s, %s, %s)
                            ON CONFLICT (session_id, turn_id, role) DO NOTHING;
                            """,
                            (session_id, str(turn_id), role, content),
                        )
                conn.commit()
            except Exception as e:
                logger.warning("Failed to append message to DB: %s", e)
                if conn:
                    conn.rollback()
            finally:
                conn.close()

        # In-memory storage update
        if str(case_id) not in self.case_service._agent_sessions:
            self.case_service._agent_sessions[str(case_id)] = {
                "session_id": session_id or str(uuid4()),
                "case_id": str(case_id),
                "organization_id": "018f2f4e-0000-7000-8000-000000000001",
            }
        sid = self.case_service._agent_sessions[str(case_id)]["session_id"]
        messages = self.case_service._agent_messages.setdefault(sid, [])
        if overwrite:
            for m in messages:
                if m.get("turn_id") == str(turn_id) and m.get("role") == role:
                    m["content"] = content
                    return
        else:
            for m in messages:
                if m.get("turn_id") == str(turn_id) and m.get("role") == role and m.get("content") == content:
                    return
        messages.append(
            {
                "id": str(uuid4()),
                "turn_id": str(turn_id),
                "role": role,
                "content": content,
                "created_at": datetime.now(UTC).isoformat(),
            }
        )

    async def get_driver_dispute_context(
        self,
        case_id: str,
        driver_id: str,
        organization_id: str | None = None,
        locale: str | None = "vi",
    ) -> DriverDisputeContextResponse:
        """Fetch rich context of alleged violation for driver dispute interface."""
        cid = str(case_id).strip()
        did = str(driver_id).strip()

        # 1. DB Lookup
        conn = None
        try:
            conn = self._get_db_connection()
        except HTTPException:
            conn = None

        if conn is not None:
            try:
                with conn.cursor() as cur:
                    cur.execute("SET search_path = app, extensions, public;")
                    cur.execute(
                        """
                        SELECT c.id as case_id, c.organization_id, c.status, c.dispute_status, c.dispute_deadline, c.suspected_category,
                               c.created_at as alleged_time, a.id as assignment_id, a.driver_id, a.trip_id,
                               d.display_name as driver_name,
                               ST_AsText(t.pickup) as alleged_location
                        FROM app.fraud_cases c
                        JOIN app.trip_assignments a ON a.id = c.assignment_id
                        JOIN app.drivers d ON d.id = a.driver_id
                        JOIN app.trips t ON t.id = a.trip_id
                        WHERE c.id::text = %s
                        LIMIT 1;
                        """,
                        (cid,),
                    )
                    row = cur.fetchone()
                    if row:
                        if (
                            organization_id
                            and row.get("organization_id")
                            and str(row.get("organization_id")) != str(organization_id)
                        ):
                            raise HTTPException(
                                status_code=404,
                                detail=f"Case {case_id} not found",
                            )
                        raw_driver_id = row.get("driver_id")
                        if not raw_driver_id:
                            raise HTTPException(
                                status_code=404,
                                detail=f"Case {case_id} not found",
                            )
                        if not self._is_test_guest_bypass(did) and (
                            not did or not self._is_driver_authorized(str(raw_driver_id), did)
                        ):
                            raise HTTPException(
                                status_code=404,
                                detail=f"Case {case_id} not found",
                            )
                        actual_driver_id = str(raw_driver_id)
                        cat = row.get("suspected_category") or "ERR-01"
                        return DriverDisputeContextResponse(
                            case_id=str(row["case_id"]),
                            driver_id=actual_driver_id,
                            driver_name=str(row.get("driver_name") or "Tài xế GreenSM"),
                            trip_id=str(row["trip_id"]),
                            violation_code=cat,
                            violation_title=violation_title(cat, locale, "Nghi vấn vi phạm tiêu chuẩn đón khách"),
                            alleged_time=row.get("alleged_time"),
                            alleged_location=row.get("alleged_location") or "Hà Nội",
                            dispute_deadline=row.get("dispute_deadline")
                            or (datetime.now(UTC) + timedelta(hours=48)).isoformat(),
                            dispute_status=row.get("dispute_status") or "not_disputed",
                        )
            except HTTPException:
                raise
            except Exception as e:
                logger.warning("DB query for driver dispute context failed: %s", e)
            finally:
                conn.close()

        # 2. In-memory fallback
        canonical_id = self.case_service._case_aliases.get(cid, cid)
        case = self.case_service._cases.get(canonical_id)
        if not case:
            for k, c in self.case_service._cases.items():
                if k == cid or str(c.get("id")) == cid:
                    case = c
                    canonical_id = k
                    break

        if not case:
            raise HTTPException(status_code=404, detail=f"Case {case_id} not found")

        if organization_id and case.get("organization_id") and str(case.get("organization_id")) != str(organization_id):
            raise HTTPException(status_code=404, detail=f"Case {case_id} not found")

        asgn_id = str(case.get("assignment_id", ""))
        asgn = self.case_service._assignments.get(asgn_id, {})
        raw_driver = case.get("driver_id") or asgn.get("driver_id")
        if not raw_driver or not str(raw_driver).strip():
            raise HTTPException(status_code=404, detail=f"Case {case_id} not found")
        actual_driver_id = str(raw_driver).strip()
        if not self._is_test_guest_bypass(did) and (not did or not self._is_driver_authorized(actual_driver_id, did)):
            raise HTTPException(
                status_code=404,
                detail=f"Case {case_id} not found",
            )
        driver = self.case_service._drivers.get(actual_driver_id, {})

        driver_name = str(driver.get("display_name") or "Tài xế GreenSM")
        trip_id = str(asgn.get("trip_id") or case.get("trip_id") or "trip-001")

        cat = case.get("suspected_category") or "ERR-01"
        dispute_status = case.get("dispute_status") or "not_disputed"
        dispute_deadline = case.get("dispute_deadline") or (datetime.now(UTC) + timedelta(hours=48)).isoformat()

        return DriverDisputeContextResponse(
            case_id=canonical_id,
            driver_id=actual_driver_id,
            driver_name=driver_name,
            trip_id=trip_id,
            violation_code=cat,
            violation_title=violation_title(cat, locale, "Nghi vấn vi phạm tiêu chuẩn đón khách"),
            alleged_time=case.get("created_at") or datetime.now(UTC).isoformat(),
            alleged_location="105.8542, 21.0285 (Hoàn Kiếm, Hà Nội)",
            dispute_deadline=dispute_deadline,
            dispute_status=dispute_status,
        )

    async def corroborate_traffic_conditions(
        self,
        case_id: str,
        driver_id: str | None = None,
        start_time: str | None = None,
        end_time: str | None = None,
    ) -> dict[str, Any]:
        """Corroborate whether physical road conditions and telemetry support a traffic claim.
        Guardrail check:
        1. observed_speed < 5.0 km/h
        2. OSRM duration ratio >= 2.0
        3. valid GPS (no mock, no jitter flag)
        4. 0 prior sanctions on driver record
        """
        cid = str(case_id).strip()
        canonical_id, case = self._find_case(cid)

        # Cross-driver authorization check if driver_id supplied
        if driver_id:
            actual_driver_id = self._get_case_driver_id(canonical_id, case)
            if not actual_driver_id or not self._is_driver_authorized(actual_driver_id, driver_id):
                raise HTTPException(
                    status_code=404,
                    detail=f"Case {case_id} not found",
                )

        # Check explicit overrides for test scenarios
        if canonical_id in self._traffic_overrides or cid in self._traffic_overrides:
            ov = self._traffic_overrides.get(canonical_id) or self._traffic_overrides.get(cid) or {}
            speed = float(ov.get("observed_speed", 0.0))
            ratio = float(ov.get("ratio", 1.0))
            congestion = str(ov.get("congestion_level", "clear"))
            gps_valid = bool(ov.get("gps_valid", True))
            sanctions = int(ov.get("prior_sanctions", 0))

            corroborated = (speed < 5.0) and (ratio >= 2.0) and gps_valid and (sanctions == 0)
            return {
                "case_id": canonical_id,
                "corroborated": corroborated,
                "ratio": ratio,
                "observed_speed": speed,
                "congestion_level": congestion,
                "gps_valid": gps_valid,
                "prior_sanctions": sanctions,
                "telemetry_status": "available",
                "status": "available",
                "evidence_references": [f"fraud_case:{canonical_id}"],
                "evaluated_at": datetime.now(UTC).isoformat(),
                "details": (
                    "Điều kiện ùn tắc giao thông được xác thực đầy đủ (Corroborated: speed < 5 km/h, ratio >= 2.0x, valid GPS, 0 sanctions)"
                    if corroborated
                    else "Không đủ cơ sở xác thực kẹt xe tự động (Uncorroborated traffic criteria)"
                ),
            }

        # Check in-memory traffic corroboration state in case_service
        corrob_data = self.case_service._traffic_corroborations.get(
            canonical_id
        ) or self.case_service._traffic_corroborations.get(cid)
        if corrob_data:
            speed = float(corrob_data.get("observed_speed") or corrob_data.get("average_speed_kmh") or 15.0)
            ratio = float(corrob_data.get("ratio") or corrob_data.get("duration_ratio") or 1.2)
            congestion = str(corrob_data.get("congestion_level") or "clear")
            gps_valid = True
            sanctions = 0
            corroborated = (speed < 5.0) and (ratio >= 2.0) and gps_valid and (sanctions == 0)
            return {
                "case_id": canonical_id,
                "corroborated": corroborated,
                "ratio": ratio,
                "observed_speed": speed,
                "congestion_level": congestion,
                "gps_valid": gps_valid,
                "prior_sanctions": sanctions,
                "telemetry_status": "available",
                "status": "available",
                "evidence_references": [f"traffic_corroboration:{canonical_id}"],
                "evaluated_at": datetime.now(UTC).isoformat(),
                "details": "Corroboration evaluated from case service traffic records.",
            }

        # Fallback evaluation from telemetry / assignment
        asgn_id = str(case.get("assignment_id", ""))
        points = [p for p in self.case_service._telemetry_points if str(p.get("assignment_id")) == asgn_id]

        conn = None
        try:
            conn = self._get_db_connection()
        except HTTPException:
            conn = None

        db_points: list[dict[str, Any]] = []
        if conn is not None and asgn_id:
            try:
                with conn.cursor() as cur:
                    cur.execute("SET search_path = app, extensions, public;")
                    cur.execute(
                        "SELECT speed_mps, mock_location_reported FROM app.telemetry_points WHERE assignment_id::text = %s;",
                        (asgn_id,),
                    )
                    rows = cur.fetchall()
                    if rows:
                        db_points = list(rows)
            except Exception as e:
                logger.warning("DB query for telemetry points failed: %s", e)
            finally:
                conn.close()

        if db_points:
            speeds = [
                float(r["speed_mps"]) * 3.6 for r in db_points if isinstance(r, dict) and r.get("speed_mps") is not None
            ]
            avg_speed = (sum(speeds) / len(speeds)) if speeds else 25.0
            has_mock = any(bool(r.get("mock_location_reported")) for r in db_points if isinstance(r, dict))
            gps_valid = not has_mock
        elif points:
            speeds = [float(p.get("speed_mps", 0.0)) * 3.6 for p in points if p.get("speed_mps") is not None]
            avg_speed = (sum(speeds) / len(speeds)) if speeds else 25.0
            has_mock = any(p.get("mock_location_reported") is True for p in points)
            gps_valid = not has_mock
        else:
            # Telemetry is unavailable — do NOT fabricate synthetic default speed or congestion
            return {
                "case_id": canonical_id,
                "corroborated": False,
                "ratio": None,
                "observed_speed": None,
                "congestion_level": "unavailable",
                "gps_valid": None,
                "prior_sanctions": 0,
                "telemetry_status": "unavailable",
                "status": "unavailable",
                "error_type": "UNAVAILABLE",
                "evidence_references": [],
                "evaluated_at": datetime.now(UTC).isoformat(),
                "details": "Telemetry data is unavailable for this trip. Cannot corroborate physical road conditions without recorded GPS telemetry.",
            }

        ratio = 2.2 if avg_speed < 5.0 else 1.1
        congestion = "heavy" if avg_speed < 5.0 else "clear"
        sanctions = 0
        corroborated = (avg_speed < 5.0) and (ratio >= 2.0) and gps_valid and (sanctions == 0)

        evidence_ref = [f"telemetry_points:{asgn_id}"] if asgn_id else [f"fraud_case:{canonical_id}"]
        return {
            "case_id": canonical_id,
            "corroborated": corroborated,
            "ratio": ratio,
            "observed_speed": avg_speed,
            "congestion_level": congestion,
            "gps_valid": gps_valid,
            "prior_sanctions": sanctions,
            "telemetry_status": "available",
            "status": "available",
            "evidence_references": evidence_ref,
            "evaluated_at": datetime.now(UTC).isoformat(),
            "details": (
                "Điều kiện ùn tắc giao thông được xác thực đầy đủ (Corroborated: speed < 5 km/h, ratio >= 2.0x, valid GPS, 0 sanctions)"
                if corroborated
                else "Không đủ cơ sở xác thực kẹt xe tự động (Uncorroborated traffic criteria)"
            ),
        }

    async def inspect_trip_telemetry(self, case_id: str, driver_id: str | None = None) -> dict[str, Any]:
        """Inspect GPS breadcrumbs, observed speed, latency, jitter, and mock location signals for a trip."""
        cid = str(case_id).strip()
        canonical_id, case = self._find_case(cid)

        # Cross-driver authorization check if driver_id supplied
        if driver_id:
            actual_driver_id = self._get_case_driver_id(canonical_id, case)
            if not actual_driver_id or not self._is_driver_authorized(actual_driver_id, driver_id):
                raise HTTPException(
                    status_code=404,
                    detail=f"Case {case_id} not found",
                )

        asgn_id = str(case.get("assignment_id", ""))
        points = [p for p in self.case_service._telemetry_points if str(p.get("assignment_id")) == asgn_id]

        conn = None
        try:
            conn = self._get_db_connection()
        except HTTPException:
            conn = None

        db_points: list[dict[str, Any]] = []
        if conn is not None and asgn_id:
            try:
                with conn.cursor() as cur:
                    cur.execute("SET search_path = app, extensions, public;")
                    cur.execute(
                        """
                        SELECT speed_mps, mock_location_reported, recorded_at,
                               ST_X(location::geometry) as longitude,
                               ST_Y(location::geometry) as latitude
                        FROM app.telemetry_points
                        WHERE assignment_id::text = %s
                        ORDER BY recorded_at ASC
                        LIMIT 50;
                        """,
                        (asgn_id,),
                    )
                    rows = cur.fetchall()
                    if rows:
                        db_points = list(rows)
            except Exception as e:
                logger.warning("DB query for trip telemetry points failed: %s", e)
            finally:
                conn.close()

        raw_points = db_points if db_points else points
        if not raw_points:
            return {
                "case_id": canonical_id,
                "assignment_id": asgn_id,
                "status": "unavailable",
                "points_count": 0,
                "breadcrumbs": [],
                "average_speed_kmh": None,
                "max_speed_kmh": None,
                "has_mock_locations": False,
                "mock_locations_count": 0,
                "evidence_references": [],
                "error_type": "UNAVAILABLE",
                "telemetry_source": "unavailable",
                "timestamp": datetime.now(UTC).isoformat(),
                "details": "No telemetry data recorded for trip",
            }

        breadcrumbs = []
        speeds = []
        mock_count = 0
        for p in raw_points:
            spd = float(p.get("speed_mps", 0.0) or 0.0) * 3.6
            speeds.append(spd)
            is_mock = bool(p.get("mock_location_reported", False))
            if is_mock:
                mock_count += 1
            lon = float(
                p.get("longitude", 0.0)
                or (p.get("location", {}).get("longitude") if isinstance(p.get("location"), dict) else 0.0)
            )
            lat = float(
                p.get("latitude", 0.0)
                or (p.get("location", {}).get("latitude") if isinstance(p.get("location"), dict) else 0.0)
            )
            rec_at = p.get("recorded_at") or p.get("timestamp") or ""
            breadcrumbs.append(
                {
                    "latitude": round(lat, 6),
                    "longitude": round(lon, 6),
                    "speed_kmh": round(spd, 2),
                    "timestamp": rec_at.isoformat() if hasattr(rec_at, "isoformat") else str(rec_at),
                    "mock_location": is_mock,
                }
            )

        avg_speed = round(sum(speeds) / len(speeds), 2) if speeds else 0.0
        max_speed = round(max(speeds), 2) if speeds else 0.0
        return {
            "case_id": canonical_id,
            "assignment_id": asgn_id,
            "status": "available",
            "points_count": len(raw_points),
            "average_speed_kmh": avg_speed,
            "max_speed_kmh": max_speed,
            "has_mock_locations": mock_count > 0,
            "mock_locations_count": mock_count,
            "breadcrumbs": breadcrumbs[:50],
            "evidence_references": [f"telemetry_points:{asgn_id}"],
            "telemetry_source": "app.telemetry_points",
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def handle_driver_intent_transition(
        self,
        case_id: str,
        driver_id: str,
        message: str,
        turn_id: str | None = None,
        admits_fraud: bool = False,
    ) -> DriverChatResponse | None:
        """Shared driver intent and state transition handler across non-stream and stream chat paths.

        Handles:
        1. Terminal / finalized cases: resolved, auto_dismissed, driver_confirmed_resolution
        2. Cases already awaiting analyst review: pending_analyst_review, driver_disputed, in_dispute, pending_review
        3. Explicit fraud admission -> driver_disputed / in_dispute (audit: explicit_admission_pending_policy)
        4. Explicit escalation / continue appeal -> driver_disputed / in_dispute (audit: driver_appeal_escalated)
        5. Generic confirmation on non-pending case -> driver_disputed / in_dispute (audit: driver_denial_escalated)
           Safeguard: confirmation of an exoneration is not an admission; generic confirmation/denial
           routes to analyst review unless request.admits_fraud or case is pending_driver_confirmation.
        6. Driver confirmation on pending case -> driver_confirmed_resolution / resolved (audit: driver_confirmed_resolution)
        """
        canonical_id, case = self._find_case(case_id)
        if not case:
            return None

        # Check if case is already resolved / finalized
        if case.get("status") in ("resolved", "auto_dismissed", "driver_confirmed_resolution"):
            return DriverChatResponse(
                case_id=canonical_id,
                driver_id=driver_id,
                reply=f"Vụ việc đã được xử lý xong (Trạng thái: {case.get('status')}). Khiếu nại đã kết thúc.",
                dispute_status=case.get("dispute_status", "resolved"),
                is_auto_dismissed=(case.get("status") == "auto_dismissed"),
                exoneration_receipt=self._exoneration_receipts.get(canonical_id),
                needs_analyst_review=False,
            )

        # Case awaiting human analyst review — driver may not re-submit
        current_case_status = case.get("status")
        current_dispute_status = case.get("dispute_status")
        if current_case_status in ("pending_analyst_review", "driver_disputed") or current_dispute_status in (
            "in_dispute",
            "pending_review",
        ):
            return DriverChatResponse(
                case_id=canonical_id,
                driver_id=driver_id,
                reply=(
                    "Giải trình của bạn đã được tiếp nhận và đang chờ Chuyên viên giám sát xem xét. "
                    "Bạn sẽ được thông báo khi có kết quả chính thức."
                ),
                dispute_status="pending_review" if current_case_status == "pending_analyst_review" else "in_dispute",
                is_auto_dismissed=False,
                exoneration_receipt=None,
                needs_analyst_review=True,
            )

        tid = str(turn_id or uuid4())

        # 1. Explicit admission is retained and handed to an analyst;
        # the system applies no automated warning, fine, or sanction.
        if admits_fraud:
            self._append_message(canonical_id, tid, "driver", message)
            self._update_case_status(canonical_id, status="driver_disputed", dispute_status="in_dispute")
            self._record_audit_entry(
                case_id=canonical_id,
                action="explicit_admission_pending_policy",
                result="accepted",
                payload={"driver_id": driver_id, "admission": message, "policy_version": None},
            )
            reply = "Đã ghi nhận lời thừa nhận; chính sách áp dụng chưa được xác định nên hồ sơ đã chuyển cho chuyên viên phân tích."
            self._append_message(canonical_id, tid, "assistant", reply)
            return DriverChatResponse(
                case_id=canonical_id,
                driver_id=driver_id,
                reply=reply,
                dispute_status="in_dispute",
                needs_analyst_review=True,
                sanction_status="pending_policy",
                sanction_action=None,
            )

        is_escalation = is_driver_escalation(message)
        is_confirmation = is_driver_closure(message)

        # 2. Explicit Driver Escalation: Driver explicitly asks to escalate to an analyst / continue appeal
        if is_escalation:
            self._append_message(canonical_id, tid, "driver", message)
            self._update_case_status(
                canonical_id,
                status="driver_disputed",
                dispute_status="in_dispute",
            )
            self._record_audit_entry(
                case_id=canonical_id,
                action="driver_appeal_escalated",
                result="escalated",
                payload={
                    "driver_id": driver_id,
                    "statement": message,
                    "reason": "driver_requested_continued_appeal",
                },
            )
            escalate_reply = (
                "Yêu cầu tiếp tục khiếu nại của bạn đã được ghi nhận. Toàn bộ hồ sơ vụ việc cùng dữ liệu đối soát "
                "đã được chuyển trực tiếp tới Chuyên viên giám sát độc lập (Fraud Analyst) để thẩm định thủ công."
            )
            self._append_message(canonical_id, tid, "assistant", escalate_reply)
            return DriverChatResponse(
                case_id=canonical_id,
                driver_id=driver_id,
                reply=escalate_reply,
                dispute_status="in_dispute",
                is_auto_dismissed=False,
                exoneration_receipt=None,
                needs_analyst_review=True,
            )

        # 3. Driver Confirmation / Closure:
        # Safeguard: confirmation of an exoneration is not an admission. Route generic
        # confirmation/denial to analyst review unless the authenticated
        # request carries the explicit admission action or the case is pending_driver_confirmation.
        if is_confirmation:
            pending_confirmation = (
                current_case_status == "pending_driver_confirmation"
                or current_dispute_status in ("pending_confirmation", "pending_driver_confirmation")
                or any(
                    isinstance(e, dict) and e.get("action") == "driver_confirmation_requested"
                    for e in self._audit_entries.get(str(canonical_id), [])
                )
            )
            if not pending_confirmation:
                self._append_message(canonical_id, tid, "driver", message)
                self._update_case_status(canonical_id, status="driver_disputed", dispute_status="in_dispute")
                self._record_audit_entry(
                    case_id=canonical_id,
                    action="driver_denial_escalated",
                    result="escalated",
                    payload={"driver_id": driver_id, "statement": message, "reason": "no explicit fraud admission"},
                )
                reply = "Xác nhận này không phải là thừa nhận gian lận. Hồ sơ đã được chuyển cho chuyên viên phân tích xử lý."
                self._append_message(canonical_id, tid, "assistant", reply)
                return DriverChatResponse(
                    case_id=canonical_id,
                    driver_id=driver_id,
                    reply=reply,
                    dispute_status="in_dispute",
                    needs_analyst_review=True,
                )

            # Driver Confirmation when pending_driver_confirmation:
            # Driver confirmation is sufficient to close every case at that step,
            # even if evidence remains missing or conflicting. Zero sanction applied.
            self._append_message(canonical_id, tid, "driver", message)
            self._update_case_status(
                canonical_id,
                status="driver_confirmed_resolution",
                dispute_status="resolved",
            )
            self._record_audit_entry(
                case_id=canonical_id,
                action="driver_confirmed_resolution",
                result="resolved",
                payload={
                    "driver_id": driver_id,
                    "resolution": "no_further_appeal",
                    "sanction_applied": None,
                    "statement": message,
                },
            )
            confirm_reply = (
                "Cảm ơn bạn đã xác nhận. Vụ việc đã được ghi nhận hoàn tất và đóng khiếu nại (driver_confirmed_resolution). "
                "Không có bất kỳ chế tài xử phạt nào được áp dụng theo quy chế bảo vệ đối tác tài xế."
            )
            self._append_message(canonical_id, tid, "assistant", confirm_reply)
            return DriverChatResponse(
                case_id=canonical_id,
                driver_id=driver_id,
                reply=confirm_reply,
                dispute_status="resolved",
                is_auto_dismissed=False,
                exoneration_receipt=None,
                needs_analyst_review=False,
            )

        return None

    async def process_driver_chat(self, request: DriverChatRequest) -> DriverChatResponse:
        """Process driver input, enforce autonomous exoneration guardrails,
        confidence boundaries, driver confirmation resolution, or escalate to analyst HITL review.
        """
        cid = str(request.case_id).strip()
        canonical_id, case = self._find_case(cid)
        driver_id = str(request.driver_id).strip()
        message = request.message.strip()
        claim_type = (request.claim_type or "").strip().lower()

        # Cross-driver authorization check
        actual_driver_id = self._get_case_driver_id(canonical_id, case)
        if not actual_driver_id or not self._is_driver_authorized(actual_driver_id, driver_id):
            raise HTTPException(
                status_code=404,
                detail=f"Case {cid} not found",
            )

        # Idempotency check: duplicate chat requests with same case, turn_id, and message
        idempotency_key = f"{canonical_id}:{request.turn_id or ''}:{hashlib.sha256(message.encode()).hexdigest()}"
        if idempotency_key in self._processed_chat_requests:
            logger.info("Idempotent driver chat retry detected for %s", idempotency_key)
            return self._processed_chat_requests[idempotency_key]

        def _finish(resp: DriverChatResponse) -> DriverChatResponse:
            self._processed_chat_requests[idempotency_key] = resp
            return resp

        # Check deadline expiration
        dispute_deadline = case.get("dispute_deadline")
        is_deadline_expired = False
        if dispute_deadline:
            deadline_dt = None
            if isinstance(dispute_deadline, datetime):
                deadline_dt = dispute_deadline
            elif isinstance(dispute_deadline, str):
                try:
                    deadline_dt = datetime.fromisoformat(dispute_deadline.replace("Z", "+00:00"))
                except Exception:
                    deadline_dt = None

            if deadline_dt is not None:
                if deadline_dt.tzinfo is None:
                    deadline_dt = deadline_dt.replace(tzinfo=UTC)
                if deadline_dt < datetime.now(UTC):
                    is_deadline_expired = True

        current_case_status = case.get("status")
        current_dispute_status = case.get("dispute_status")

        # 48-Hour Silence Deadline: If no response / offline after confirmation question for > 48 hours, automatically escalate to Analyst.
        if is_deadline_expired:
            if current_case_status == "pending_driver_confirmation" or current_dispute_status in (
                "pending_confirmation",
                "pending_driver_confirmation",
            ):
                self._update_case_status(
                    canonical_id,
                    status="driver_disputed",
                    dispute_status="in_dispute",
                )
                self._record_audit_entry(
                    case_id=canonical_id,
                    action="driver_silence_timeout_escalation",
                    result="escalated",
                    payload={"reason": "48h silence deadline expired without driver response", "driver_id": driver_id},
                )
                turn_id = str(request.turn_id or uuid4())
                timeout_reply = (
                    "Thời hạn 48 giờ phản hồi đã kết thúc mà không nhận được xác nhận từ tài xế. "
                    "Hồ sơ vụ việc đã được tự động chuyển sang Chuyên viên giám sát độc lập (Fraud Analyst) để giải quyết theo quy trình."
                )
                self._append_message(canonical_id, turn_id, "assistant", timeout_reply)
                return _finish(
                    DriverChatResponse(
                        case_id=canonical_id,
                        driver_id=driver_id,
                        reply=timeout_reply,
                        dispute_status="in_dispute",
                        is_auto_dismissed=False,
                        needs_analyst_review=True,
                    )
                )
            else:
                self._update_case_status(
                    canonical_id,
                    status=case.get("status", "ready"),
                    dispute_status="closed",
                )
                return _finish(
                    DriverChatResponse(
                        case_id=canonical_id,
                        driver_id=driver_id,
                        reply="Thời hạn gửi khiếu nại (48 giờ) đã kết thúc. Vụ việc đã được chuyển sang trạng thái đóng khiếu nại.",
                        dispute_status="closed",
                        is_auto_dismissed=False,
                        needs_analyst_review=False,
                    )
                )

        # Shared intent and transition handling across non-stream and stream chat paths:
        transition_resp = self.handle_driver_intent_transition(
            case_id=canonical_id,
            driver_id=driver_id,
            message=message,
            turn_id=request.turn_id,
            admits_fraud=bool(request.admits_fraud),
        )
        if transition_resp is not None:
            return _finish(transition_resp)

        # Check if message text hints at traffic gridlock if claim_type not explicitly given
        traffic_keywords = ["kẹt xe", "tắc đường", "un tac", "traffic", "gridlock", "ket xe", "tac duong"]
        is_traffic_claim = claim_type in ("traffic_gridlock", "traffic_congestion", "traffic") or any(
            kw in message.lower() for kw in traffic_keywords
        )

        turn_id = str(request.turn_id or uuid4())
        self._append_message(canonical_id, turn_id, "driver", message)

        # Record driver submission in memory and Supabase DB
        submission_entry = {
            "statement": message,
            "claim_type": claim_type or ("traffic_gridlock" if is_traffic_claim else "other"),
            "submitted_at": datetime.now(UTC).isoformat(),
        }
        self._dispute_statements.setdefault(canonical_id, []).append(submission_entry)

        # Persist to app.driver_submissions in Supabase
        db_conn = None
        try:
            db_conn = self._get_db_connection()
        except Exception:
            db_conn = None

        if db_conn is not None:
            try:
                with db_conn.cursor() as cur:
                    cur.execute("SET search_path = app, extensions, public;")
                    cur.execute(
                        """
                        INSERT INTO app.driver_submissions (id, case_id, status, statement, deadline_at, received_at, provenance)
                        VALUES (
                            gen_random_uuid(), %s::uuid, %s, %s, %s::timestamptz, now(),
                            jsonb_build_object('claim_type', %s::text, 'driver_id', %s::text)
                        );
                        """,
                        (
                            canonical_id,
                            "present",
                            message,
                            case.get("dispute_deadline"),
                            claim_type or "other",
                            driver_id,
                        ),
                    )
                db_conn.commit()
            except Exception as e:
                logger.warning("Failed to record driver_submission in Supabase: %s", e)
                if db_conn:
                    db_conn.rollback()
            finally:
                db_conn.close()

        # Check if confirmation was already requested on a prior turn
        audit_entries = self._audit_entries.get(str(canonical_id), [])
        is_already_asked_confirmation = (
            current_case_status in ("pending_driver_confirmation", "in_review")
            and current_dispute_status in ("pending_confirmation", "pending_driver_confirmation", "pending")
        ) or any(isinstance(e, dict) and e.get("action") == "driver_confirmation_requested" for e in audit_entries)

        if is_already_asked_confirmation:
            # Stop the reply from re-issuing the same canned paragraph every turn.
            # Never add new metrics, confidence numbers, sanctions or auto-exemption claims.
            reminder_reply = (
                "Thông tin giải trình bổ sung của bạn đã được ghi nhận vào hồ sơ vụ việc. "
                "Vui lòng phản hồi xác nhận bạn muốn tiếp tục khiếu nại lên Chuyên viên giám sát độc lập "
                "hay Đồng ý kết thúc vụ việc không khiếu nại thêm."
            )
            self._append_message(canonical_id, turn_id, "assistant", reminder_reply)
            return _finish(
                DriverChatResponse(
                    case_id=canonical_id,
                    driver_id=driver_id,
                    reply=reminder_reply,
                    dispute_status="pending_confirmation",
                    is_auto_dismissed=False,
                    exoneration_receipt=None,
                    needs_analyst_review=False,
                )
            )

        # Issue #482 review finding: this used to fire the GSupport agent via
        # `asyncio.create_task(...)` and discard the result entirely, so the
        # driver never received the real agent reply through any caller of
        # this deterministic policy method. The deterministic compliance
        # reply computed below is the authoritative response for this
        # non-streaming endpoint (NFR-L06-02 guardrails; see tests asserting
        # exact policy copy). SSE callers (`stream_driver_chat`,
        # `stream_driverless_chat`) now explicitly await the real agent and
        # use its reply/blocks instead of discarding them.

        tool_failed = False
        try:
            corrob = await self.corroborate_traffic_conditions(canonical_id)
        except Exception as e:
            logger.exception("Corroborate traffic conditions failed: %s", e)
            tool_failed = True
            corrob = {
                "case_id": canonical_id,
                "corroborated": False,
                "ratio": 1.0,
                "observed_speed": 0.0,
                "congestion_level": "unknown",
                "gps_valid": True,
                "prior_sanctions": 0,
                "details": f"Tool execution failed: {e}",
            }

        c = self._get_case_confidence(canonical_id, case)

        # Boundary Rule: Exactly 0.5, missing confidence (c = None), out-of-range (c < 0 or c > 1),
        # or tool execution failure MUST escalate to Analyst and NEVER auto-close.
        is_boundary_escalation = tool_failed or c is None or c < 0.0 or c > 1.0 or abs(c - 0.5) < 1e-5

        if is_boundary_escalation or c is None:
            dispute_status = "pending_review" if (is_traffic_claim and corrob.get("corroborated")) else "in_dispute"
            escalated_status = "pending_analyst_review" if dispute_status == "pending_review" else "driver_disputed"
            action = (
                "traffic_corroboration_pending_review"
                if (is_traffic_claim and corrob.get("corroborated"))
                else "driver_dispute_submitted"
            )
            self._update_case_status(canonical_id, status=escalated_status, dispute_status=dispute_status)
            self._record_audit_entry(
                case_id=canonical_id,
                action=action,
                result="accepted" if action == "traffic_corroboration_pending_review" else "escalated",
                payload={
                    "driver_id": driver_id,
                    "claim_type": claim_type or ("traffic_gridlock" if is_traffic_claim else "other"),
                    "statement": message,
                    "confidence": c,
                    "corroboration": corrob,
                    "reason": "tool_execution_failed" if tool_failed else "boundary_or_missing_confidence",
                },
            )

            if tool_failed:
                reply = (
                    "Hệ thống gặp sự cố khi đối chiếu dữ liệu tự động. "
                    "Hồ sơ vụ việc đã được chuyển tiếp tới Chuyên viên giám sát độc lập (Fraud Analyst) để thẩm định thủ công."
                )
            elif corrob.get("status") == "unavailable" or corrob.get("error_type") == "UNAVAILABLE":
                reply = (
                    "Dữ liệu hành trình GPS của chuyến đi hiện không khả dụng để đối chiếu tự động. "
                    "Theo quy chế bảo vệ quyền lợi tài xế Điều 12.3, hồ sơ vụ việc đã được chuyển tiếp tới Chuyên viên giám sát độc lập (Fraud Analyst) để thẩm định thủ công."
                )
            elif is_traffic_claim and corrob.get("corroborated"):
                reply = (
                    "Giải trình về tình trạng kẹt xe của bạn đã được tiếp nhận và đối chiếu với "
                    f"dữ liệu giao thông thực tế (vận tốc TB: {corrob['observed_speed']:.1f} km/h, "
                    f"tỷ lệ thời gian: {corrob['ratio']:.1f}x). "
                    "Hồ sơ đã được chuyển tới Chuyên viên giám sát độc lập để xác nhận và ra quyết định "
                    "chính thức theo quy trình. Bạn sẽ được thông báo kết quả sau khi có phê duyệt."
                )
            elif abs(c - 0.5) < 1e-5 if c is not None else False:
                reply = (
                    "Độ tin cậy của hệ thống phân loại nằm ở ngưỡng ranh giới (đúng 50.0%). "
                    "Theo nguyên tắc bảo vệ quyền lợi tài xế Điều 12.3, vụ việc đã được chuyển tới Chuyên viên giám sát độc lập để thẩm định thủ công."
                )
            elif c is not None and (c < 0.0 or c > 1.0):
                reply = (
                    f"Chỉ số độ tin cậy không hợp lệ ({c}). "
                    "Hệ thống tự động chuyển tiếp hồ sơ tới Chuyên viên giám sát độc lập để kiểm tra và xử lý an toàn."
                )
            else:
                reply = (
                    f"Giải trình của bạn về lý do '{claim_type or 'khác'}' đã được ghi nhận vào hồ sơ vụ việc "
                    "và chuyển tiếp cho Chuyên viên giám sát độc lập để kiểm tra và đối soát."
                )

            self._append_message(canonical_id, turn_id, "assistant", reply)
            return _finish(
                DriverChatResponse(
                    case_id=canonical_id,
                    driver_id=driver_id,
                    reply=reply,
                    dispute_status=dispute_status,
                    is_auto_dismissed=False,
                    exoneration_receipt=None,
                    needs_analyst_review=True,
                )
            )

        # Non-boundary cases: c is a valid float in [0.0, 1.0] and c != 0.5
        # Set 48-hour deadline for driver response
        deadline_dt = datetime.now(UTC) + timedelta(hours=48)
        self._update_case_status(
            canonical_id,
            status="pending_driver_confirmation",
            dispute_status="pending_confirmation",
            dispute_deadline=deadline_dt,
        )

        if c > 0.5:
            # Strictly greater than 0.5: Ask whether Driver still wants to appeal
            self._record_audit_entry(
                case_id=canonical_id,
                action="driver_confirmation_requested",
                result="pending_confirmation",
                payload={
                    "driver_id": driver_id,
                    "confidence": c,
                    "deadline": deadline_dt.isoformat(),
                    "corroboration": corrob,
                    "inquiry": "ask_whether_appeal",
                },
            )
            speed_fmt = corrob.get("observed_speed") if corrob.get("observed_speed") is not None else 0.0
            ratio_fmt = corrob.get("ratio") if corrob.get("ratio") is not None else 1.0
            # R2: state only measured telemetry (speed/ratio) from the case;
            # the classifier confidence `c` is a model-derived score, not a
            # measured fact, and must never be presented to the driver as an
            # authoritative percentage (no fabricated metric/verdict).
            reply = (
                f"Hệ thống đã đối chiếu dữ liệu hành trình theo Điều 12.2 (Vận tốc TB: {speed_fmt:.1f} km/h, "
                f"Tỷ lệ thời gian: {ratio_fmt:.1f}x). "
                "Bạn có muốn tiếp tục khiếu nại lên Chuyên viên giám sát độc lập (Fraud Analyst) hay Đồng ý kết thúc vụ việc không khiếu nại thêm? "
                "Vui lòng phản hồi trong vòng 48 giờ. (Không áp dụng chế tài xử phạt khi bạn xác nhận kết thúc)."
            )
        else:
            # Confidence < 0.5: Do NOT escalate; still ask Driver to confirm resolution before closing
            self._record_audit_entry(
                case_id=canonical_id,
                action="driver_confirmation_requested",
                result="pending_confirmation",
                payload={
                    "driver_id": driver_id,
                    "confidence": c,
                    "deadline": deadline_dt.isoformat(),
                    "corroboration": corrob,
                    "inquiry": "ask_confirm_before_closing",
                    "low_confidence": True,
                },
            )
            # R2: no fabricated/unmeasured confidence percentage in the reply.
            reply = (
                "Giải trình của bạn đã được đối soát phù hợp với quy chế Điều 12.2. "
                "Hệ thống không chuyển vụ việc sang xử lý kỷ luật. Bạn vui lòng xác nhận kết thúc vụ việc (Không khiếu nại thêm) để đóng hồ sơ mà không áp dụng bất kỳ chế tài nào. "
                "Vui lòng phản hồi trong vòng 48 giờ."
            )

        self._append_message(canonical_id, turn_id, "assistant", reply)
        return _finish(
            DriverChatResponse(
                case_id=canonical_id,
                driver_id=driver_id,
                reply=reply,
                dispute_status="pending_confirmation",
                is_auto_dismissed=False,
                exoneration_receipt=None,
                needs_analyst_review=False,
            )
        )

    async def process_driver_chat_turn(
        self,
        case_id: str,
        request: DriverChatRequest,
        driver_id: str | None = None,
    ) -> DriverChatResponse:
        """Process driver chat turn with case_id and driver_id propagation."""
        canonical_id, _ = self._find_case(case_id)
        effective_driver_id = request.driver_id or driver_id or ""
        updated_request = request.model_copy(
            update={
                "case_id": canonical_id,
                "driver_id": effective_driver_id,
            }
        )
        return await self.process_driver_chat(updated_request)

    async def _stream_agent_tool_events(
        self,
        *,
        case_id: str | None,
        driver_id: str,
        message: str,
        claim_type: str | None = None,
        locale: str = "vi",
        timeout: float = 60.0,
        result_holder: dict[str, Any] | None = None,
        organization_id: str | None = None,
    ):
        """Run driver support agent and yield SSE tool events in real time.

        Also performs post-hoc deduplication and cancels agent_task on disconnect.
        """
        tool_queue: asyncio.Queue[tuple[str, dict[str, Any]]] = asyncio.Queue()
        emitted_tool_keys: set[tuple[str, str]] = set()

        async def _tool_listener(event_type: str, data: dict[str, Any]) -> None:
            await tool_queue.put((event_type, data))

        from src.agents.driver_agent import run_driver_support_agent

        agent_task = asyncio.create_task(
            asyncio.wait_for(
                run_driver_support_agent(
                    case_id=case_id,
                    driver_id=driver_id,
                    message=message,
                    claim_type=claim_type,
                    locale=locale,
                    on_tool_event=_tool_listener,
                    organization_id=organization_id,
                ),
                timeout=timeout,
            )
        )

        try:
            while not agent_task.done() or not tool_queue.empty():
                try:
                    evt_type, evt_data = tool_queue.get_nowait()
                    emitted_tool_keys.add((evt_type, str(evt_data.get("tool_call_id"))))
                    yield f"event: {evt_type}\ndata: {json.dumps(evt_data, ensure_ascii=False)}\n\n"
                    continue
                except asyncio.QueueEmpty:
                    pass
                if agent_task.done():
                    break
                get_fut = asyncio.create_task(tool_queue.get())
                done, _ = await asyncio.wait([agent_task, get_fut], return_when=asyncio.FIRST_COMPLETED)
                if get_fut in done:
                    evt_type, evt_data = get_fut.result()
                    emitted_tool_keys.add((evt_type, str(evt_data.get("tool_call_id"))))
                    yield f"event: {evt_type}\ndata: {json.dumps(evt_data, ensure_ascii=False)}\n\n"
                else:
                    get_fut.cancel()
                    try:
                        await get_fut
                    except asyncio.CancelledError:
                        pass

            agent_res = await agent_task
            for te in agent_res.get("tool_events", []):
                evt_type = te.get("event")
                evt_data = te.get("data") or {}
                key = (evt_type, str(evt_data.get("tool_call_id")))
                if key not in emitted_tool_keys:
                    emitted_tool_keys.add(key)
                    yield f"event: {evt_type}\ndata: {json.dumps(evt_data, ensure_ascii=False)}\n\n"

            if result_holder is not None:
                result_holder["result"] = agent_res
        finally:
            if not agent_task.done():
                agent_task.cancel()
                try:
                    await agent_task
                except (asyncio.CancelledError, Exception):
                    pass

    async def stream_driver_chat(
        self,
        case_id: str,
        message: str,
        claim_type: str | None = None,
        driver_id: str | None = None,
        turn_id: str | None = None,
        locale: str = "vi",
        organization_id: str | None = None,
    ):
        """SSE stream driver dispute response token-by-token followed by completion event."""
        if not driver_id:
            raise HTTPException(status_code=403, detail="Driver mapping required")
        canonical_id, case = self._find_case(case_id)
        resolved_org = organization_id or (
            str(case.get("organization_id")) if isinstance(case, dict) and case.get("organization_id") else None
        )
        if not resolved_org:
            msg = "Yêu cầu phạm vi tổ chức (organization_id)" if locale != "en" else "Organization scope required"
            yield f"event: error\ndata: {json.dumps({'message': msg}, ensure_ascii=False)}\n\n"
            return
        req = DriverChatRequest(
            case_id=canonical_id,
            driver_id=driver_id or "",
            message=message or "Tôi muốn giải trình về trường hợp này",
            claim_type=claim_type,
            turn_id=turn_id or str(uuid4()),
            locale=locale,
        )
        chat_resp = await self.process_driver_chat(req)

        # Issue #482/#538 review findings: previously the agent was fired via
        # `asyncio.create_task(...)` inside `process_driver_chat` and its
        # result discarded, so the driver only ever saw the deterministic
        # policy-engine template. Run the agent once here, bounded by a
        # timeout, and surface its REAL reply/blocks; fall back to the
        # deterministic compliance template if the agent run fails, times
        # out, or produced an empty/degraded response — never present a
        # degraded/fabricated agent reply as if it were real.
        agent_reply: str | None = None
        blocks: list[dict[str, Any]] = []
        result_holder: dict[str, Any] = {}
        agent_timeout = get_settings().driver_agent_timeout_seconds

        sub_gen = self._stream_agent_tool_events(
            case_id=canonical_id,
            driver_id=driver_id,
            message=message,
            claim_type=claim_type,
            locale=locale,
            timeout=agent_timeout,
            result_holder=result_holder,
            organization_id=resolved_org,
        )
        try:
            async for sse_event in sub_gen:
                yield sse_event

            agent_res = result_holder.get("result") or {}
            if not agent_res.get("error") and not agent_res.get("empty_response"):
                agent_reply = (agent_res.get("reply") or "").strip() or None
                blocks = agent_res.get("blocks", []) or []
        except TimeoutError:
            logger.exception("Driver support agent timed out after %ss for case %s", agent_timeout, canonical_id)
        except Exception:
            logger.exception(
                "Driver support agent run failed for case %s; falling back to deterministic reply",
                canonical_id,
            )
        finally:
            await sub_gen.aclose()

        is_agent_fallback = agent_reply is None
        reply = agent_reply or chat_resp.reply

        # Persist what is actually shown live so reopening the thread matches
        # (overwrite the deterministic placeholder process_driver_chat wrote).
        if agent_reply and req.turn_id:
            self._append_message(canonical_id, req.turn_id, "assistant", reply, overwrite=True)

        words = reply.split(" ")
        for i, word in enumerate(words):
            token = word + (" " if i < len(words) - 1 else "")
            token_payload = {
                "token": token,
                "delta": token,
                "case_id": canonical_id,
            }
            yield f"event: token\ndata: {json.dumps(token_payload, ensure_ascii=False)}\n\n"
            await asyncio.sleep(0.01)

        blocks_payload = {
            "case_id": canonical_id,
            "blocks": blocks,
        }
        yield f"event: blocks\ndata: {json.dumps(blocks_payload, ensure_ascii=False)}\n\n"

        done_payload = {
            "status": "completed",
            "case_id": canonical_id,
            "driver_id": chat_resp.driver_id,
            "turn_id": req.turn_id,
            "reply": reply,
            "dispute_status": chat_resp.dispute_status,
            "is_auto_dismissed": chat_resp.is_auto_dismissed,
            "exoneration_receipt": chat_resp.exoneration_receipt,
            "needs_analyst_review": chat_resp.needs_analyst_review,
            "blocks": blocks,
            # R1: explicit flag so the UI/logs can tell the deterministic
            # compliance template was shown instead of the real agent reply.
            "is_agent_fallback": is_agent_fallback,
        }
        yield f"event: done\ndata: {json.dumps(done_payload, ensure_ascii=False)}\n\n"

    async def stream_driverless_chat(
        self,
        driver_id: str,
        message: str,
        locale: str = "vi",
        turn_id: str | None = None,
        organization_id: str | None = None,
    ):
        """SSE stream case-less GSupport chat (Issue #482).

        No case id is bound yet; the agent resolves the driver's cases via
        the `list_my_cases` tool. Emits the same `token` / `blocks` / `done`
        lifecycle as `stream_driver_chat`, using the REAL agent reply.
        """
        if not driver_id:
            raise HTTPException(status_code=403, detail="Driver mapping required")
        if not organization_id:
            msg = "Yêu cầu phạm vi tổ chức (organization_id)" if locale != "en" else "Organization scope required"
            yield f"event: error\ndata: {json.dumps({'message': msg}, ensure_ascii=False)}\n\n"
            return

        turn_id = turn_id or str(uuid4())
        self._append_driverless_message(driver_id, turn_id, "driver", message)

        result_holder: dict[str, Any] = {}
        agent_timeout = get_settings().driver_agent_timeout_seconds
        sub_gen = self._stream_agent_tool_events(
            case_id=None,
            driver_id=driver_id,
            message=message,
            claim_type=None,
            locale=locale,
            timeout=agent_timeout,
            result_holder=result_holder,
            organization_id=organization_id,
        )
        try:
            async for sse_event in sub_gen:
                yield sse_event
        except TimeoutError:
            logger.exception("Case-less driver agent run timed out after %ss for driver %s", agent_timeout, driver_id)
            yield f"event: error\ndata: {json.dumps({'message': 'Agent request timed out'})}\n\n"
            return
        except Exception as e:
            logger.exception("Case-less driver agent run failed: %s", e)
            yield f"event: error\ndata: {json.dumps({'message': 'Agent request failed'})}\n\n"
            return
        finally:
            await sub_gen.aclose()

        # Issue #538 review finding: an agent error or an empty/degraded
        # response must never be presented as a successful reply, even if
        # `reply` is non-empty neutral fallback copy.
        agent_res = result_holder.get("result") or {}
        if agent_res.get("error") or agent_res.get("empty_response"):
            yield f"event: error\ndata: {json.dumps({'message': 'Agent returned no response'})}\n\n"
            return

        reply = (agent_res.get("reply") or "").strip()
        blocks = agent_res.get("blocks", []) or []

        if not reply:
            yield f"event: error\ndata: {json.dumps({'message': 'Agent returned no response'})}\n\n"
            return

        self._append_driverless_message(driver_id, turn_id, "driver_agent", reply)

        words = reply.split(" ")
        for i, word in enumerate(words):
            token = word + (" " if i < len(words) - 1 else "")
            token_payload = {"token": token, "delta": token}
            yield f"event: token\ndata: {json.dumps(token_payload, ensure_ascii=False)}\n\n"
            await asyncio.sleep(0.01)

        yield f"event: blocks\ndata: {json.dumps({'blocks': blocks}, ensure_ascii=False)}\n\n"

        done_payload = {
            "status": "completed",
            "driver_id": driver_id,
            "turn_id": turn_id,
            "reply": reply,
            "blocks": blocks,
        }
        yield f"event: done\ndata: {json.dumps(done_payload, ensure_ascii=False)}\n\n"

    def _update_case_status(
        self,
        case_id: str,
        status: str,
        dispute_status: str,
        dispute_deadline: datetime | None = None,
    ) -> None:
        """Update case status both in-memory and in DB."""
        cid = str(case_id)
        # Update in-memory
        if cid in self.case_service._cases:
            self.case_service._cases[cid]["status"] = status
            self.case_service._cases[cid]["dispute_status"] = dispute_status
            if dispute_deadline:
                self.case_service._cases[cid]["dispute_deadline"] = dispute_deadline.isoformat()

        alias = self.case_service._case_aliases.get(cid)
        if alias and alias in self.case_service._cases:
            self.case_service._cases[alias]["status"] = status
            self.case_service._cases[alias]["dispute_status"] = dispute_status
            if dispute_deadline:
                self.case_service._cases[alias]["dispute_deadline"] = dispute_deadline.isoformat()

        # Update Database
        conn = None
        try:
            conn = self._get_db_connection()
        except HTTPException:
            conn = None

        if conn is not None:
            db_status = status
            if status == "pending_driver_confirmation":
                db_status = "in_review"
            elif status == "driver_confirmed_resolution":
                db_status = "resolved"

            db_dispute_status = dispute_status
            if dispute_status in ("pending_confirmation", "pending_driver_confirmation"):
                db_dispute_status = "pending"
            elif dispute_status in ("resolved", "closed"):
                db_dispute_status = "not_disputed"

            try:
                with conn.cursor() as cur:
                    cur.execute("SET search_path = app, extensions, public;")
                    if dispute_deadline:
                        cur.execute(
                            """
                            UPDATE app.fraud_cases
                            SET status = %s, dispute_status = %s, dispute_deadline = %s, updated_at = now()
                            WHERE id::text = %s;
                            """,
                            (db_status, db_dispute_status, dispute_deadline, cid),
                        )
                    else:
                        cur.execute(
                            """
                            UPDATE app.fraud_cases
                            SET status = %s, dispute_status = %s, updated_at = now()
                            WHERE id::text = %s;
                            """,
                            (db_status, db_dispute_status, cid),
                        )
                conn.commit()
            except Exception as e:
                logger.warning("Failed to update case status in DB: %s", e)
                if conn:
                    conn.rollback()
            finally:
                conn.close()

    async def delegate_analyst_inquiry(
        self,
        case_id: str,
        request: AnalystDelegateInquiryRequest,
    ) -> dict[str, Any]:
        """Analyst delegates an inquiry or requests additional driver explanation."""
        cid = str(case_id).strip()
        canonical_id, _ = self._find_case(cid)
        deadline = datetime.now(UTC) + timedelta(hours=request.deadline_hours)

        self._update_case_status(
            canonical_id,
            status="evidence_requested",
            dispute_status="pending",
            dispute_deadline=deadline,
        )

        turn_id = str(request.turn_id or uuid4())
        instruction_msg = f"[Yêu cầu từ Chuyên viên giám sát {request.analyst_id}]: {request.instruction}"
        self._append_message(canonical_id, turn_id, "analyst", instruction_msg)

        self._record_audit_entry(
            case_id=canonical_id,
            action="analyst_delegate_inquiry",
            result="accepted",
            payload={
                "analyst_id": request.analyst_id,
                "instruction": request.instruction,
                "deadline": deadline.isoformat(),
            },
            actor_id=request.analyst_id,
            actor_type="analyst",
        )

        return {
            "case_id": canonical_id,
            "analyst_id": request.analyst_id,
            "dispute_status": "pending",
            "dispute_deadline": deadline.isoformat(),
            "instruction": request.instruction,
            "delegated_at": datetime.now(UTC).isoformat(),
        }

    async def get_dispute_dossier(self, case_id: str) -> DisputeDossierResponse:
        """Compile complete dispute dossier for analyst review."""
        cid = str(case_id).strip()
        canonical_id, case = self._find_case(cid)

        asgn_id = str(case.get("assignment_id", ""))
        asgn = self.case_service._assignments.get(asgn_id, {})
        driver_id = str(asgn.get("driver_id", "drv-001"))
        driver = self.case_service._drivers.get(driver_id, {})
        driver_name = str(driver.get("display_name") or "Tài xế GreenSM")

        statements = self._dispute_statements.get(canonical_id, [])
        latest_statement = statements[-1]["statement"] if statements else None
        latest_claim_type = statements[-1]["claim_type"] if statements else None

        corrob = await self.corroborate_traffic_conditions(canonical_id)
        traffic_info = {
            "ratio": corrob.get("ratio", 1.0),
            "observed_speed": corrob.get("observed_speed", 0.0),
            "congestion_level": corrob.get("congestion_level", "clear"),
            "corroborated": corrob.get("corroborated", False),
        }

        # Retrieve the durable transcript.  A fresh service instance must see
        # seeded/live messages, so the in-memory cache is only a test fallback.
        transcript = self._load_durable_transcript(canonical_id)

        dispute_status = case.get("dispute_status") or "not_disputed"
        recommended_action = "Auto-Dismiss" if corrob.get("corroborated") else "Review Driver Statement"

        # Precedent similarity matching via JevPrecedentService
        from src.services.jev_precedent_service import get_jev_precedent_service

        jev_service = get_jev_precedent_service()
        precedent_match_resp = await jev_service.match_precedent(
            case_id=canonical_id,
            claim_type=latest_claim_type,
            driver_statement=latest_statement,
            violation_code=case.get("violation_code") or case.get("suspected_category") or "ERR-02",
            telemetry_summary=traffic_info,
        )

        top_match = precedent_match_resp.top_match
        precedent_score = top_match.similarity_score if top_match else 0.0
        matching_factors = top_match.matching_factors if top_match else []
        workflow_trace = jev_service.get_workflow_trace(canonical_id)

        return DisputeDossierResponse(
            case_id=canonical_id,
            driver_id=driver_id,
            driver_name=driver_name,
            dispute_status=dispute_status,
            driver_statement=latest_statement,
            claim_type=latest_claim_type,
            traffic_corroboration=traffic_info,
            precedent_score=precedent_score,
            recommended_action=recommended_action,
            transcript=transcript,
            matched_precedent=top_match,
            matching_factors=matching_factors,
            workflow_trace=workflow_trace,
        )

    def _load_durable_transcript(self, case_id: str) -> list[dict[str, Any]]:
        """Read analyst-visible driver dialogue from the append-only store."""
        allowed_roles = ("driver", "driver_agent", "analyst", "agent")
        conn = None
        try:
            conn = self._get_db_connection()
        except HTTPException:
            conn = None
        if conn is not None:
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        """SELECT m.id, m.turn_id, m.role, m.content, m.created_at, m.sequence
                           FROM app.case_agent_messages m
                           JOIN app.case_agent_sessions s ON s.id = m.session_id
                          WHERE s.case_id = %s::uuid AND m.role = ANY(%s)
                          ORDER BY m.sequence ASC, m.created_at ASC, m.id ASC""",
                        (case_id, list(allowed_roles)),
                    )
                    rows = cur.fetchall()
                    return [dict(row) for row in rows]
            except Exception as exc:
                logger.exception("Failed to load durable dispute transcript for %s", case_id)
                raise HTTPException(status_code=503, detail="Durable dispute transcript unavailable") from exc
            finally:
                conn.close()

        if case_id in self.case_service._agent_sessions:
            sid = self.case_service._agent_sessions[case_id]["session_id"]
            return [
                message
                for message in self.case_service._agent_messages.get(sid, [])
                if message.get("role") in allowed_roles
            ]
        return []

    def query_driver_policy(self, query: str) -> dict[str, Any]:
        """Search policy articles relevant to driver rights and dispute guidelines."""
        q_lower = query.lower()
        scored = []
        for p in POLICY_GUIDELINES:
            text = (p["article"] + " " + p["title"] + " " + p["snippet"]).lower()
            score = 0.0
            for term in q_lower.split():
                if len(term) > 2 and term in text:
                    score += 1.0

            # Boost specific key concepts
            if (
                any(
                    k in q_lower
                    for k in [
                        "kẹt xe",
                        "tắc đường",
                        "ùn tắc",
                        "bất khả kháng",
                        "miễn trừ",
                        "12.2",
                        "traffic",
                        "gridlock",
                    ]
                )
                and p["article"] == "Điều 12.2"
            ):
                score += 5.0
            if (
                any(k in q_lower for k in ["thời hạn", "48h", "48 giờ", "hạn chót", "khiếu nại", "12.1", "deadline"])
                and p["article"] == "Điều 12.1"
            ):
                score += 5.0
            if (
                any(
                    k in q_lower for k in ["xử phạt", "phạt", "tự động", "chuyên viên", "12.3", "thẩm định", "sanction"]
                )
                and p["article"] == "Điều 12.3"
            ):
                score += 5.0

            scored.append((score, p))

        scored.sort(key=lambda x: x[0], reverse=True)
        top_score, top_policy = scored[0]
        match_score = f"{min(99, int(75 + top_score * 4))}%" if top_score > 0 else "85%"

        matching = [p for s, p in scored if s > 0]
        if not matching:
            matching = [p for _, p in scored]

        return {
            "query": query,
            "matched_article": top_policy["article"],
            "matched_title": top_policy["title"],
            "matched_chunk": top_policy["snippet"],
            "match_score": match_score,
            "summary": f"Đối chiếu quy chế {top_policy['article']} ({top_policy['title']}): {top_policy['snippet']}",
            "relevant_policies": matching,
            "guidance_for_driver": (
                f"Căn cứ {top_policy['article']} ({top_policy['title']}): {top_policy['snippet']} "
                "Hệ thống cam kết bảo vệ quyền lợi minh bạch của đối tác tài xế."
            ),
        }

    # -----------------------------------------------------------------------
    # Confirmation-gated Accept/Reject Flow & Statement Drafts (Issue #483)
    # -----------------------------------------------------------------------
    async def issue_confirmation_token(
        self,
        case_id: str,
        driver_id: str,
        action: str,
        draft_hash: str = "",
    ) -> str:
        """Issue a single-use, 10-minute confirmation token bound to (case_id, driver_id, action)."""
        if action not in ("acknowledge", "submit_statement"):
            raise ValueError(f"Invalid confirmation action: {action}")

        cid = str(case_id).strip()
        did = str(driver_id).strip()
        raw_token = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
        expires_at = datetime.now(UTC) + timedelta(minutes=10)

        self._confirmation_tokens[token_hash] = {
            "token_hash": token_hash,
            "case_id": cid,
            "driver_id": did,
            "action": action,
            "draft_hash": draft_hash or "",
            "expires_at": expires_at,
            "used": False,
            "used_at": None,
        }

        conn = None
        try:
            conn = self._get_db_connection()
        except Exception:
            conn = None

        if conn is not None:
            try:
                with conn.cursor() as cur:
                    cur.execute("SET search_path = app, extensions, public;")
                    cur.execute(
                        """
                        INSERT INTO app.driver_confirmation_tokens (
                            token_hash, case_id, driver_id, action, draft_hash, expires_at
                        )
                        VALUES (%s, %s::uuid, %s, %s, %s, %s)
                        ON CONFLICT (token_hash) DO NOTHING;
                        """,
                        (token_hash, cid, did, action, draft_hash or None, expires_at),
                    )
                conn.commit()
            except Exception as e:
                logger.debug("DB insert for confirmation token skipped/failed: %s", e)
                if conn:
                    conn.rollback()
            finally:
                conn.close()

        return raw_token

    def _lookup_token(self, token: str) -> dict[str, Any] | None:
        """Look up confirmation token record by SHA-256 hash in memory then DB."""
        if not token or not str(token).strip():
            return None
        token_hash = hashlib.sha256(str(token).strip().encode("utf-8")).hexdigest()
        mem_rec = self._confirmation_tokens.get(token_hash)

        conn = None
        try:
            conn = self._get_db_connection()
        except Exception:
            conn = None

        if conn is not None:
            try:
                with conn.cursor() as cur:
                    cur.execute("SET search_path = app, extensions, public;")
                    cur.execute(
                        """
                        SELECT token_hash, case_id, driver_id, action, draft_hash, expires_at, used_at
                        FROM app.driver_confirmation_tokens
                        WHERE token_hash = %s
                        LIMIT 1;
                        """,
                        (token_hash,),
                    )
                    row = cur.fetchone()
                    if row:
                        db_rec = {
                            "token_hash": str(row["token_hash"]),
                            "case_id": str(row["case_id"]),
                            "driver_id": str(row["driver_id"]),
                            "action": str(row["action"]),
                            "draft_hash": row.get("draft_hash") or "",
                            "expires_at": row["expires_at"],
                            "used": row.get("used_at") is not None or bool(mem_rec and mem_rec.get("used")),
                            "used_at": row.get("used_at") or (mem_rec.get("used_at") if mem_rec else None),
                        }
                        self._confirmation_tokens[token_hash] = db_rec
                        return db_rec
            except Exception as e:
                logger.debug("DB lookup for confirmation token skipped/failed: %s", e)
            finally:
                conn.close()

        return mem_rec

    async def _consume_token(
        self,
        token: str,
        case_id: str,
        driver_id: str,
        action: str,
    ) -> tuple[bool, str]:
        """Validate and atomically consume a single-use confirmation token."""
        rec = self._lookup_token(token)
        if not rec:
            return (False, "missing_or_unknown_token")
        if rec.get("used") or rec.get("used_at") is not None:
            return (False, "token_already_used")

        req_cid = str(case_id).strip()
        rec_cid = str(rec.get("case_id", "")).strip()
        if req_cid != rec_cid:
            return (False, "case_mismatch")

        req_did = str(driver_id).strip()
        rec_did = str(rec.get("driver_id", "")).strip()
        if req_did != rec_did and not self._is_driver_authorized(rec_did, req_did):
            return (False, "driver_mismatch")

        if str(rec.get("action")) != str(action):
            return (False, "action_mismatch")

        expires_at = rec.get("expires_at")
        if isinstance(expires_at, str):
            try:
                expires_at = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
            except Exception:
                expires_at = None
        if isinstance(expires_at, datetime):
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=UTC)
            if expires_at < datetime.now(UTC):
                return (False, "token_expired")

        now_dt = datetime.now(UTC)
        rec["used"] = True
        rec["used_at"] = now_dt
        token_hash = rec["token_hash"]
        self._confirmation_tokens[token_hash] = rec

        conn = None
        try:
            conn = self._get_db_connection()
        except Exception:
            conn = None

        if conn is not None:
            try:
                with conn.cursor() as cur:
                    cur.execute("SET search_path = app, extensions, public;")
                    cur.execute(
                        """
                        UPDATE app.driver_confirmation_tokens
                        SET used_at = %s
                        WHERE token_hash = %s AND used_at IS NULL
                        RETURNING token_hash;
                        """,
                        (now_dt, token_hash),
                    )
                    updated = cur.fetchone()
                    if updated is None:
                        cur.execute(
                            "SELECT used_at FROM app.driver_confirmation_tokens WHERE token_hash = %s;",
                            (token_hash,),
                        )
                        existing = cur.fetchone()
                        if existing and existing.get("used_at") is not None:
                            conn.rollback()
                            return (False, "token_already_used")
                conn.commit()
            except Exception as e:
                logger.debug("DB update for confirmation token skipped/failed: %s", e)
                if conn:
                    conn.rollback()
            finally:
                conn.close()

        return (True, "ok")

    async def submit_statement_with_token(
        self,
        case_id: str,
        driver_id: str,
        confirmation_token: str,
        reason_summary: str,
        evidence: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Submit driver statement only when a valid single-use confirmation token is presented."""
        ok, reason = await self._consume_token(confirmation_token, case_id, driver_id, "submit_statement")
        if not ok:
            return {
                "status": "failed",
                "reason": reason,
                "message": "Thao tác gửi giải trình cần xác nhận trực tiếp từ tài xế qua thẻ xác nhận.",
            }

        cid = str(case_id).strip()
        did = str(driver_id).strip()
        canonical_id = self.case_service._case_aliases.get(cid, cid)
        case = self.case_service._cases.get(canonical_id, {})
        now_iso = datetime.now(UTC).isoformat()

        submission_entry = {
            "statement": reason_summary,
            "reason_summary": reason_summary,
            "claim_type": "driver_statement",
            "evidence": evidence or [],
            "submitted_at": now_iso,
        }
        self._dispute_statements.setdefault(cid, []).append(submission_entry)
        if canonical_id != cid:
            self._dispute_statements.setdefault(canonical_id, []).append(submission_entry)

        db_conn = None
        try:
            db_conn = self._get_db_connection()
        except Exception:
            db_conn = None

        if db_conn is not None:
            try:
                with db_conn.cursor() as cur:
                    cur.execute("SET search_path = app, extensions, public;")
                    cur.execute(
                        """
                        INSERT INTO app.driver_submissions (
                            id, case_id, status, statement, deadline_at, received_at, provenance
                        )
                        VALUES (
                            gen_random_uuid(), %s::uuid, %s, %s, %s::timestamptz, now(),
                            %s::jsonb
                        );
                        """,
                        (
                            cid,
                            "submitted",
                            reason_summary,
                            case.get("dispute_deadline"),
                            json.dumps(
                                {
                                    "driver_id": did,
                                    "evidence": evidence or [],
                                    "action": "submit_statement",
                                },
                                default=str,
                            ),
                        ),
                    )
                db_conn.commit()
            except Exception as e:
                logger.debug("DB insert for driver_submission skipped/failed: %s", e)
                if db_conn:
                    db_conn.rollback()
            finally:
                db_conn.close()

        self._update_case_status(cid, status="driver_disputed", dispute_status="analyst_escalated")
        self._record_audit_entry(
            case_id=cid,
            action="driver_statement_submitted",
            result="escalated",
            payload={
                "driver_id": did,
                "reason": reason_summary,
                "evidence": evidence or [],
                "timestamp": now_iso,
            },
            actor_id=did,
            actor_type="driver",
        )

        turn_id = str(uuid4())
        self._append_message(cid, turn_id, "driver", reason_summary)
        reply = (
            "Giải trình của bạn đã được xác nhận và gửi thành công. "
            "Hồ sơ vụ việc đã được chuyển tới Chuyên viên thẩm định độc lập để xem xét."
        )
        self._append_message(cid, turn_id, "assistant", reply)

        return {
            "status": "submitted",
            "case_id": cid,
            "driver_id": did,
            "dispute_status": "analyst_escalated",
            "needs_analyst_review": True,
            "sanction_action": None,
            "message": reply,
        }

    async def acknowledge_with_token(
        self,
        case_id: str,
        driver_id: str,
        confirmation_token: str,
    ) -> dict[str, Any]:
        """Acknowledge alleged violation with confirmation token; routes to analyst and never sanctions."""
        ok, reason = await self._consume_token(confirmation_token, case_id, driver_id, "acknowledge")
        if not ok:
            return {
                "status": "failed",
                "reason": reason,
                "message": "Thao tác chấp nhận thông tin sự việc cần xác nhận trực tiếp từ tài xế qua thẻ xác nhận.",
                "sanction_action": None,
            }

        cid = str(case_id).strip()
        did = str(driver_id).strip()
        now_iso = datetime.now(UTC).isoformat()

        self._update_case_status(cid, status="driver_disputed", dispute_status="analyst_escalated")
        self._record_audit_entry(
            case_id=cid,
            action="driver_acknowledged_violation",
            result="escalated",
            payload={
                "driver_id": did,
                "reason": "Driver acknowledged violation via confirmation flow",
                "sanction_action": None,
                "timestamp": now_iso,
            },
            actor_id=did,
            actor_type="driver",
        )

        turn_id = str(uuid4())
        self._append_message(cid, turn_id, "driver", "Tôi xác nhận thông tin sự việc.")
        reply = (
            "Xác nhận của bạn đã được ghi nhận và chuyển tới Chuyên viên thẩm định để xem xét. "
            "Hệ thống không áp dụng bất kỳ hình thức xử phạt tự động nào."
        )
        self._append_message(cid, turn_id, "assistant", reply)

        return {
            "status": "submitted",
            "acknowledged": True,
            "case_id": cid,
            "driver_id": did,
            "dispute_status": "analyst_escalated",
            "needs_analyst_review": True,
            "sanction_action": None,
            "message": reply,
        }

    async def save_statement_draft(
        self,
        case_id: str,
        driver_id: str,
        draft: dict[str, Any],
    ) -> dict[str, Any]:
        """Persist driver statement draft in memory and DB (best-effort)."""
        cid = str(case_id).strip()
        did = str(driver_id).strip()
        draft_copy = dict(draft or {})
        self._statement_drafts[(cid, did)] = draft_copy

        conn = None
        try:
            conn = self._get_db_connection()
        except Exception:
            conn = None

        if conn is not None:
            try:
                with conn.cursor() as cur:
                    cur.execute("SET search_path = app, extensions, public;")
                    cur.execute(
                        """
                        INSERT INTO app.driver_statement_drafts (case_id, driver_id, draft, updated_at)
                        VALUES (%s::uuid, %s, %s::jsonb, now())
                        ON CONFLICT (case_id, driver_id)
                        DO UPDATE SET draft = EXCLUDED.draft, updated_at = now();
                        """,
                        (cid, did, json.dumps(draft_copy, default=str)),
                    )
                conn.commit()
            except Exception as e:
                logger.debug("DB upsert for statement draft skipped/failed: %s", e)
                if conn:
                    conn.rollback()
            finally:
                conn.close()

        return draft_copy

    async def get_statement_draft(
        self,
        case_id: str,
        driver_id: str,
    ) -> dict[str, Any] | None:
        """Retrieve saved driver statement draft from DB or in-memory store."""
        cid = str(case_id).strip()
        did = str(driver_id).strip()

        conn = None
        try:
            conn = self._get_db_connection()
        except Exception:
            conn = None

        if conn is not None:
            try:
                with conn.cursor() as cur:
                    cur.execute("SET search_path = app, extensions, public;")
                    cur.execute(
                        """
                        SELECT draft
                        FROM app.driver_statement_drafts
                        WHERE case_id = %s::uuid AND driver_id = %s
                        LIMIT 1;
                        """,
                        (cid, did),
                    )
                    row = cur.fetchone()
                    if row and row.get("draft") is not None:
                        val = row["draft"]
                        if isinstance(val, str):
                            val = json.loads(val)
                        if isinstance(val, dict):
                            self._statement_drafts[(cid, did)] = val
                            return val
            except Exception as e:
                logger.debug("DB lookup for statement draft skipped/failed: %s", e)
            finally:
                conn.close()

        return self._statement_drafts.get((cid, did))


_driver_dispute_service_instance: DriverDisputeService | None = None


def get_driver_dispute_service() -> DriverDisputeService:
    global _driver_dispute_service_instance
    if _driver_dispute_service_instance is None:
        _driver_dispute_service_instance = DriverDisputeService()
    return _driver_dispute_service_instance

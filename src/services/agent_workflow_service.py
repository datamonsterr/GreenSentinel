"""AgentWorkflowService — dispatch layer for #86 workflow tools.

This service implements the shared integration seam described in the Issue 60
execution contract:

    AgentWorkflowService.invoke(operation: str, arguments: dict, context: dict)

The runtime calls this after resolving canonical tool IDs; the service returns
ordinary typed-domain model_dump JSON. The runtime wraps ToolResult/provenance.

Owned files: this module, workflow_repository.py, workflow_models.py,
             the matching migration, and the API router.

Do NOT import API Principal here; the route layer builds and passes context.
Do NOT grant approvals from context fields alone.
"""

from __future__ import annotations

import json
import logging
import math
from datetime import datetime
from typing import Any

from src.config import Settings, get_settings
from src.models.workflow_models import (
    ActorTarget,
    AskInteractiveQuestionArguments,
    AskInteractiveQuestionResult,
    DraftCaseMinutesArguments,
    DraftCaseMinutesResult,
    DraftEvidenceRequestArguments,
    DraftEvidenceRequestResult,
    GetActionStatusArguments,
    GetActionStatusResult,
    MinutesSection,
    PreviewCaseMinutesArguments,
    PreviewCaseMinutesResult,
    QuestionPurpose,
    QuestionStatus,
    RequestActionApprovalArguments,
    RequestActionApprovalResult,
    WorkflowContext,
    WorkflowMinutesContent,
    compute_content_hash,
    utc_now_iso,
)
from src.services import workflow_repository as repo
from src.services.case_service import get_case_service
from src.services.workflow_repository import WorkflowPersistenceError

logger = logging.getLogger(__name__)

# Supported operations dispatched through this service
SUPPORTED_OPERATIONS = frozenset(
    {
        "ask_interactive_question",
        "draft_evidence_request",
        "draft_case_minutes",
        "preview_case_minutes",
        "request_action_approval",
        "get_action_status",
    }
)


class WorkflowServiceError(Exception):
    """Raised for validation or business rule violations."""

    def __init__(self, message: str, code: str = "VALIDATION_ERROR"):
        super().__init__(message)
        self.code = code


class AgentWorkflowService:
    """Dispatch layer for all workflow tool operations.

    The runtime calls invoke() with a canonical operation name, arguments parsed
    from the model call, and a trusted context dict. The service validates,
    persists, and returns a domain model_dump dict.
    """

    def __init__(
        self,
        settings: Settings | None = None,
        case_service: Any = None,
    ) -> None:
        self.settings = settings or get_settings()
        self._case_service = case_service

    def _get_case_service(self) -> Any:
        if self._case_service is not None:
            return self._case_service
        return get_case_service()

    def _get_db_connection(self) -> Any:
        return self._get_case_service()._get_db_connection()

    async def invoke(self, operation: str, arguments: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        """Dispatch a workflow tool operation.

        Parameters
        ----------
        operation:  Canonical tool name (e.g. "ask_interactive_question").
        arguments:  Model-supplied arguments; validated here against the typed schema.
        context:    Trusted runtime context; never parsed from model arguments.
                    Must contain: actor_id, organization_id, roles, case_id,
                    driver_id (nullable), request_id, run_id, tool_call_id, turn_id.

        Returns
        -------
        dict  model_dump() of the typed result; the runtime wraps the ToolResult envelope.
        """
        if operation not in SUPPORTED_OPERATIONS:
            raise WorkflowServiceError(
                f"Unknown workflow operation: {operation}. Supported: {sorted(SUPPORTED_OPERATIONS)}",
                code="VALIDATION_ERROR",
            )

        ctx = WorkflowContext.from_dict(context)

        dispatch = {
            "ask_interactive_question": self._ask_interactive_question,
            "draft_evidence_request": self._draft_evidence_request,
            "draft_case_minutes": self._draft_case_minutes,
            "preview_case_minutes": self._preview_case_minutes,
            "request_action_approval": self._request_action_approval,
            "get_action_status": self._get_action_status,
        }

        handler = dispatch[operation]
        return await handler(arguments, ctx)

    # ──────────────────────────────────────────────────────────────────────────
    # ask_interactive_question
    # ──────────────────────────────────────────────────────────────────────────

    async def _ask_interactive_question(self, arguments: dict[str, Any], ctx: WorkflowContext) -> dict[str, Any]:
        args = AskInteractiveQuestionArguments.model_validate(arguments)
        if args.purpose == QuestionPurpose.action_confirmation and (
            not ctx.is_analyst() or args.actor_target != ActorTarget.analyst
        ):
            raise WorkflowServiceError(
                "Action-confirmation questions are analyst-only and cannot approve actions",
                code="FORBIDDEN",
            )

        # Build payload for storage
        options_dicts = [o.model_dump() for o in args.options]
        payload = {
            "question_text": args.question_text,
            "options": options_dicts,
            "max_selections": args.max_selections,
            "hint": args.hint,
            "allows_explanation": args.allows_explanation,
        }

        conn = None
        try:
            conn = self._get_db_connection()
            row = repo.upsert_question(
                conn,
                case_id=ctx.case_id,
                organization_id=ctx.organization_id,
                question_id_stable=args.question_id_stable,
                question_kind=args.question_kind.value,
                purpose=args.purpose.value,
                actor_target=args.actor_target.value,
                payload=payload,
                created_by_actor_id=ctx.actor_id,
            )
            already_exists = row.get("status") == "pending" and row.get("revision", 1) >= 1
        except WorkflowPersistenceError as exc:
            raise WorkflowServiceError(str(exc), code="PERSISTENCE_UNAVAILABLE") from exc
        finally:
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass

        result = AskInteractiveQuestionResult(
            question_id=str(row["id"]),
            question_id_stable=row["question_id_stable"],
            revision=row["revision"],
            status=QuestionStatus(row["status"]),
            case_id=str(row["case_id"]),
            already_exists=already_exists,
        )
        return result.model_dump()

    # ──────────────────────────────────────────────────────────────────────────
    # draft_evidence_request
    # ──────────────────────────────────────────────────────────────────────────

    async def _draft_evidence_request(self, arguments: dict[str, Any], ctx: WorkflowContext) -> dict[str, Any]:
        if not ctx.is_analyst():
            raise WorkflowServiceError("draft_evidence_request requires analyst role", code="FORBIDDEN")

        args = DraftEvidenceRequestArguments.model_validate(arguments)

        # Draft is stored as a question with purpose=clarification, kind=text
        # The question_id_stable is deterministic from case+evidence_gap
        import hashlib

        stable_id = (
            "evreq_" + hashlib.sha256(f"{ctx.case_id}:{args.evidence_gap_description[:80]}".encode()).hexdigest()[:16]
        )

        payload = {
            "question_text": args.question_text,
            "options": [{"id": opt, "label": opt} for opt in args.allowed_submission_options],
            "max_selections": None,
            "hint": args.evidence_gap_description,
            "allows_explanation": True,
        }

        conn = None
        draft_id: str = ""
        try:
            conn = self._get_db_connection()
            policy_deadline_hours = repo.get_policy_deadline_hours(
                conn, case_id=ctx.case_id, organization_id=ctx.organization_id
            )
            row = repo.upsert_question(
                conn,
                case_id=ctx.case_id,
                organization_id=ctx.organization_id,
                question_id_stable=stable_id,
                question_kind="text",
                purpose="clarification",
                actor_target="driver",
                payload=payload,
                created_by_actor_id=ctx.actor_id,
            )
            draft_id = str(row["id"])
        except WorkflowPersistenceError as exc:
            raise WorkflowServiceError(str(exc), code="PERSISTENCE_UNAVAILABLE") from exc
        finally:
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass

        result = DraftEvidenceRequestResult(
            draft_id=draft_id,
            question_text=args.question_text,
            allowed_submission_options=args.allowed_submission_options,
            policy_deadline_hours=policy_deadline_hours,
            deadline_source=("published_policy" if policy_deadline_hours is not None else "manual_clarification"),
            note=(
                "Published case policy supplies the deadline; send still requires owner approval."
                if policy_deadline_hours is not None
                else "No published case policy deadline is available; manual clarification is required before sending."
            ),
        )
        return result.model_dump()

    # ──────────────────────────────────────────────────────────────────────────
    # draft_case_minutes
    # ──────────────────────────────────────────────────────────────────────────

    async def _draft_case_minutes(self, arguments: dict[str, Any], ctx: WorkflowContext) -> dict[str, Any]:
        if not ctx.is_analyst():
            raise WorkflowServiceError("draft_case_minutes requires analyst role", code="FORBIDDEN")

        args = DraftCaseMinutesArguments.model_validate({**arguments, "case_id": ctx.case_id})

        # Retrieve case/decision context from CaseService
        case_svc = self._get_case_service()
        case_detail = None
        adjudication = None
        missing_fields: list[str] = []
        source_row: dict[str, Any] | None = None

        try:
            case_detail = await case_svc.get_case_detail(args.case_id, organization_id=ctx.organization_id)
        except Exception as exc:
            logger.warning("Could not fetch case detail for minutes draft: %s", exc)
            missing_fields.append("case_detail_unavailable")

        # Require recorded decision before drafting final minutes
        if case_detail is not None:
            if not case_detail.adjudication:
                missing_fields.append("decision_not_recorded")
            else:
                adjudication = case_detail.adjudication

        if "decision_not_recorded" in missing_fields:
            # Return early with informative result; do not persist
            return DraftCaseMinutesResult(
                minutes_id="",
                revision=0,
                status="draft",  # type: ignore[arg-type]
                case_id=ctx.case_id,
                content_preview=("Chưa thể tạo biên bản: vụ việc chưa có quyết định chính thức được ghi nhận."),
                missing_fields=missing_fields,
            ).model_dump()

        conn = None
        try:
            conn = self._get_db_connection()
            source_row = repo.get_minutes_sources(conn, case_id=ctx.case_id, organization_id=ctx.organization_id)
        except WorkflowPersistenceError as exc:
            raise WorkflowServiceError(str(exc), code="PERSISTENCE_UNAVAILABLE") from exc
        finally:
            if conn:
                conn.close()

        if not source_row or not source_row.get("decision_id"):
            missing_fields.append("decision_not_recorded")
        if not source_row or not source_row.get("evidence_snapshot_id"):
            missing_fields.append("evidence_snapshot_id")
        traveled_path = source_row.get("traveled_path") if source_row else []
        map_svg = _render_traveled_path_svg(traveled_path)
        if map_svg is None:
            missing_fields.append("traveled_map_artifact")

        # Build structured Vietnamese minutes content
        now_iso = utc_now_iso()
        sections = _build_minutes_sections(case_detail, adjudication, args, source_row, map_svg)
        content = WorkflowMinutesContent(
            document_id=f"BB-{ctx.case_id[:8].upper()}",
            revision=1,
            issued_at=now_iso,
            status_label="Bản nháp",
            sections=sections,
            map_svg=map_svg,
            source_revision=(
                f"decision:{source_row['decision_id']};evidence:{source_row['evidence_snapshot_id']}"
                if source_row
                else None
            ),
        )

        conn = None
        try:
            conn = self._get_db_connection()
            row = repo.insert_minutes(
                conn,
                case_id=ctx.case_id,
                organization_id=ctx.organization_id,
                decision_id=str(source_row["decision_id"]),
                content=content.model_dump(),
                map_ref=f"route-snapshot:{source_row['route_snapshot_id']}"
                if source_row.get("route_snapshot_id")
                else None,
                evidence_snapshot_id=str(source_row["evidence_snapshot_id"]),
                drafted_by=ctx.actor_id,
            )
            minutes_id = str(row["id"])
            revision = row["revision"]
        except WorkflowPersistenceError as exc:
            raise WorkflowServiceError(str(exc), code="PERSISTENCE_UNAVAILABLE") from exc
        finally:
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass

        preview_text = sections[0].content[:500] if sections else "(Không có nội dung)"

        result = DraftCaseMinutesResult(
            minutes_id=minutes_id,
            revision=revision,
            status="draft",  # type: ignore[arg-type]
            case_id=ctx.case_id,
            content_preview=preview_text,
            missing_fields=missing_fields,
        )
        return result.model_dump()

    # ──────────────────────────────────────────────────────────────────────────
    # preview_case_minutes
    # ──────────────────────────────────────────────────────────────────────────

    async def _preview_case_minutes(self, arguments: dict[str, Any], ctx: WorkflowContext) -> dict[str, Any]:
        if not ctx.is_analyst():
            raise WorkflowServiceError("preview_case_minutes requires analyst role", code="FORBIDDEN")

        args = PreviewCaseMinutesArguments.model_validate(arguments)

        conn = None
        try:
            conn = self._get_db_connection()
            row = repo.get_minutes_by_id(conn, args.minutes_id)
        except WorkflowPersistenceError as exc:
            raise WorkflowServiceError(str(exc), code="NOT_FOUND") from exc
        finally:
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass

        # Verify case ownership
        if str(row.get("case_id")) != ctx.case_id:
            raise WorkflowServiceError("Minutes case_id does not match context case_id", code="FORBIDDEN")

        content = row.get("content") or {}
        if isinstance(content, str):
            content = json.loads(content)

        content_obj = WorkflowMinutesContent.model_validate(content)
        content_hash = compute_content_hash(content)

        # Determine missing required fields
        missing: list[str] = []
        if not row.get("decision_id"):
            missing.append("decision_id")
        # Driver recipient: inferred from case assignment
        driver_id = None
        driver_display = None
        case_svc = self._get_case_service()
        try:
            source_conn = self._get_db_connection()
            try:
                source_row = repo.get_minutes_sources(
                    source_conn, case_id=str(row["case_id"]), organization_id=ctx.organization_id
                )
            finally:
                source_conn.close()
            driver_id = str(source_row["driver_id"]) if source_row.get("driver_id") else None
            case_detail = await case_svc.get_case_detail(str(row["case_id"]), organization_id=ctx.organization_id)
            if not driver_id and hasattr(case_detail, "driver_id"):
                driver_id = str(case_detail.driver_id) if case_detail.driver_id else None
            if not driver_id:
                missing.append("recipient_driver_id")
        except Exception:
            missing.append("case_detail_unavailable")

        result = PreviewCaseMinutesResult(
            minutes_id=args.minutes_id,
            revision=row.get("revision", 1),
            status=row.get("status", "draft"),  # type: ignore[arg-type]
            case_id=str(row["case_id"]),
            recipient_driver_id=driver_id,
            recipient_display_name=driver_display,
            content=content_obj,
            map_ref=row.get("map_ref"),
            evidence_snapshot_id=str(row["evidence_snapshot_id"]) if row.get("evidence_snapshot_id") else None,
            decision_id=str(row["decision_id"]) if row.get("decision_id") else None,
            content_hash=content_hash,
            missing_required_fields=missing,
            ready_to_approve=len(missing) == 0,
        )
        return result.model_dump()

    # ──────────────────────────────────────────────────────────────────────────
    # request_action_approval
    # ──────────────────────────────────────────────────────────────────────────

    async def _request_action_approval(self, arguments: dict[str, Any], ctx: WorkflowContext) -> dict[str, Any]:
        if not ctx.is_analyst():
            raise WorkflowServiceError("request_action_approval requires analyst role", code="FORBIDDEN")

        args = RequestActionApprovalArguments.model_validate(arguments)
        payload_hash = compute_content_hash({"action_kind": args.action_kind, "payload": args.payload})

        conn = None
        try:
            conn = self._get_db_connection()
            row, already_exists = repo.upsert_action_request(
                conn,
                case_id=ctx.case_id,
                organization_id=ctx.organization_id,
                action_kind=args.action_kind,
                requested_by=ctx.actor_id,
                payload={
                    **args.payload,
                    "consequence_summary": args.consequence_summary,
                },
                payload_hash=payload_hash,
            )
        except WorkflowPersistenceError as exc:
            raise WorkflowServiceError(str(exc), code="PERSISTENCE_UNAVAILABLE") from exc
        finally:
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass

        result = RequestActionApprovalResult(
            action_request_id=str(row["id"]),
            action_kind=args.action_kind,
            status=row.get("status", "pending"),  # type: ignore[arg-type]
            payload_hash=payload_hash,
            already_exists=already_exists,
        )
        return result.model_dump()

    # ──────────────────────────────────────────────────────────────────────────
    # get_action_status
    # ──────────────────────────────────────────────────────────────────────────

    async def _get_action_status(self, arguments: dict[str, Any], ctx: WorkflowContext) -> dict[str, Any]:
        args = GetActionStatusArguments.model_validate(arguments)

        conn = None
        try:
            conn = self._get_db_connection()

            if args.action_request_id:
                row = repo.get_action_request_by_id(conn, args.action_request_id)
                # Verify case scope
                if str(row.get("case_id")) != ctx.case_id or str(row.get("organization_id")) != ctx.organization_id:
                    raise WorkflowServiceError("Action request case_id does not match context", code="FORBIDDEN")
                result = GetActionStatusResult(
                    kind="action_request",
                    record_id=args.action_request_id,
                    status=row.get("status", "unknown"),
                    safe_failure_reason=row.get("denial_reason"),
                    next_step=_next_step_for_action(row.get("status")),
                )

            elif args.question_id_stable:
                with conn.cursor() as cur:
                    cur.execute("SET search_path = app, extensions, public;")
                    cur.execute(
                        """
                        SELECT revision
                        FROM app.workflow_questions
                        WHERE case_id = %s::uuid AND question_id_stable = %s
                        ORDER BY revision DESC LIMIT 1
                        """,
                        (ctx.case_id, args.question_id_stable),
                    )
                    latest = cur.fetchone()
                    if latest is None:
                        raise WorkflowPersistenceError(
                            f"Question {args.question_id_stable} for case {ctx.case_id} not found",
                            retryable=False,
                        )
                    latest_revision = dict(latest)["revision"]
                    row = repo._fetch_question_row(cur, ctx.case_id, args.question_id_stable, latest_revision)
                if str(row.get("organization_id")) != ctx.organization_id:
                    raise WorkflowServiceError("Question organization mismatch", code="FORBIDDEN")
                if row.get("actor_target") == "analyst" and not ctx.is_analyst():
                    raise WorkflowServiceError("Question target is not authorized", code="FORBIDDEN")
                if row.get("actor_target") == "driver":
                    if not ctx.is_driver() or not ctx.driver_id:
                        raise WorkflowServiceError("Verified driver context required", code="FORBIDDEN")
                    with conn.cursor() as cur:
                        cur.execute(
                            """
                            SELECT 1 FROM app.drivers d
                            JOIN app.trip_assignments ta ON ta.driver_id = d.id
                            JOIN app.fraud_cases fc ON fc.assignment_id = ta.id
                            WHERE d.id = %s::uuid AND d.principal_id = %s::uuid
                              AND fc.id = %s::uuid AND fc.organization_id = %s::uuid
                            LIMIT 1
                            """,
                            (ctx.driver_id, ctx.actor_id, ctx.case_id, ctx.organization_id),
                        )
                        if cur.fetchone() is None:
                            raise WorkflowServiceError("Driver is not assigned to this case", code="FORBIDDEN")
                result = GetActionStatusResult(
                    kind="question",
                    record_id=str(row["id"]),
                    status=row.get("status", "unknown"),
                    next_step=_next_step_for_question(row.get("status")),
                )

            elif args.minutes_id:
                row = repo.get_minutes_by_id(conn, args.minutes_id)
                if str(row.get("case_id")) != ctx.case_id or str(row.get("organization_id")) != ctx.organization_id:
                    raise WorkflowServiceError("Minutes case_id does not match context", code="FORBIDDEN")
                result = GetActionStatusResult(
                    kind="minutes",
                    record_id=args.minutes_id,
                    status=row.get("status", "unknown"),
                    next_step=_next_step_for_minutes(row.get("status")),
                )

            else:
                raise WorkflowServiceError(
                    "Provide action_request_id, question_id_stable, or minutes_id",
                    code="VALIDATION_ERROR",
                )

        except WorkflowServiceError:
            raise
        except WorkflowPersistenceError as exc:
            raise WorkflowServiceError(str(exc), code="PERSISTENCE_UNAVAILABLE") from exc
        finally:
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass

        return result.model_dump()


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _build_minutes_sections(
    case_detail: Any,
    adjudication: Any,
    args: DraftCaseMinutesArguments,
    source_row: dict[str, Any] | None = None,
    map_svg: str | None = None,
) -> list[MinutesSection]:
    """Build structured Vietnamese sections from real case/adjudication data.

    No invented values. Missing data shown as 'Chưa có dữ liệu'.
    """
    sections: list[MinutesSection] = []

    def _val(v: Any, fallback: str = "Chưa có dữ liệu") -> str:
        if v is None or (isinstance(v, str) and not v.strip()):
            return fallback
        return str(v)

    case_id = _val(getattr(case_detail, "case_id", None) or getattr(case_detail, "id", None))
    trip_id = _val(getattr(case_detail, "trip_id", None))
    driver_id = _val(getattr(case_detail, "driver_id", None))

    sections.append(
        MinutesSection(
            section_key="Biên bản kết quả xử lý vụ việc",
            content=(
                f"Tài liệu: Biên bản kết quả xử lý vụ việc\n"
                f"Mã vụ: {case_id}\n"
                f"Trạng thái: Bản nháp\n"
                f"Lưu ý: Biên bản này chỉ có hiệu lực sau khi được chuyên viên phê duyệt và gửi."
            ),
        )
    )

    sections.append(
        MinutesSection(
            section_key="Thông tin định danh",
            content=(
                f"Mã vụ việc: {case_id}\n"
                f"Mã chuyến đi: {trip_id}\n"
                f"Tài xế: {driver_id}\n"
                f"Loại nghi vấn: {_val(getattr(case_detail, 'suspected_category', None))}"
            ),
        )
    )

    sections.append(
        MinutesSection(
            section_key="Diễn biến vụ việc",
            content=_val(
                getattr(case_detail, "summary", None),
                "Diễn biến vụ việc sẽ được cập nhật theo dữ liệu thực tế.",
            ),
        )
    )

    sections.append(
        MinutesSection(
            section_key="Lộ trình đã di chuyển",
            content=(
                f"Bản đồ nguồn: {_val(source_row.get('route_snapshot_id') if source_row else None, 'Không khả dụng')}\n"
                f"Điểm GPS thực tế: {len(source_row.get('traveled_path') or []) if source_row else 0}\n"
                f"Tài liệu bản đồ SVG: {'Có' if map_svg else 'Không khả dụng'}\n"
                "Lộ trình chỉ thể hiện các điểm GPS ghi nhận; khoảng trống được giữ nguyên."
            ),
        )
    )

    sections.append(
        MinutesSection(
            section_key="Nguồn thông tin và chứng cứ",
            content=(
                f"Snapshot chứng cứ: {_val(source_row.get('evidence_snapshot_id') if source_row else None, 'Không khả dụng')}\n"
                "Chỉ các chứng cứ được phép theo phân quyền mới được công bố."
            ),
        )
    )

    # Driver statement
    driver_statement = _val(
        getattr(case_detail, "driver_statement", None),
        "Không có giải trình nào được ghi nhận.",
    )
    sections.append(MinutesSection(section_key="Giải trình của tài xế", content=driver_statement))

    # Policy reference
    sections.append(
        MinutesSection(
            section_key="Căn cứ đối chiếu",
            content=(
                "Chính sách áp dụng: theo tài liệu chính sách đã được phê duyệt và truy xuất "
                "tại thời điểm quyết định. Không áp dụng điều khoản cứng không có trích dẫn."
            ),
        )
    )

    # Decision
    if adjudication:
        verdict = _val(getattr(adjudication, "verdict", None))
        rationale = _val(getattr(adjudication, "rationale", None))
        adj_id = _val(getattr(adjudication, "id", None))
        sections.append(
            MinutesSection(
                section_key="Kết luận và lý do",
                content=(f"Kết quả: {verdict}\nLý do: {rationale}\nMã quyết định: {adj_id}"),
            )
        )
    else:
        sections.append(
            MinutesSection(
                section_key="Kết luận và lý do",
                content="Quyết định chưa được ghi nhận.",
            )
        )

    sections.append(
        MinutesSection(
            section_key="Hướng dẫn tiếp theo",
            content=(
                "Hướng dẫn tiếp theo sẽ dựa trên chính sách được phê duyệt và nội dung quyết định. "
                "Không có thời hạn khiếu nại hoặc cổng nộp đơn nào được tạo ra ngoài nội dung đã được phê duyệt."
            ),
        )
    )

    return sections


def _render_traveled_path_svg(points: Any) -> str | None:
    """Render actual lon/lat observations to a safe deterministic SVG."""
    if not isinstance(points, list):
        return None
    valid: list[tuple[float, float, datetime | None]] = []
    for point in points:
        try:
            lon, lat = float(point["lon"]), float(point["lat"])
            occurred_at = datetime.fromisoformat(str(point["occurred_at"]).replace("Z", "+00:00"))
        except (KeyError, TypeError, ValueError):
            occurred_at = None
        if math.isfinite(lon) and math.isfinite(lat) and -180 <= lon <= 180 and -90 <= lat <= 90:
            valid.append((lon, lat, occurred_at))
    if len(valid) < 2:
        return None
    min_lon, max_lon = min(x[0] for x in valid), max(x[0] for x in valid)
    min_lat, max_lat = min(x[1] for x in valid), max(x[1] for x in valid)
    lon_span = max(max_lon - min_lon, 1e-9)
    lat_span = max(max_lat - min_lat, 1e-9)
    coords = []
    for lon, lat, _ in valid:
        x = 20 + 760 * (lon - min_lon) / lon_span
        y = 580 - 560 * (lat - min_lat) / lat_span
        coords.append(f"{x:.2f},{y:.2f}")
    segments: list[list[str]] = [[]]
    for index, coord in enumerate(coords):
        previous_at = valid[index - 1][2] if index else None
        current_at = valid[index][2]
        if previous_at and current_at and (current_at - previous_at).total_seconds() >= 30:
            segments.append([])
        segments[-1].append(coord)
    polylines = "".join(
        f'<polyline points="{" ".join(segment)}" fill="none" stroke="#2563eb" stroke-width="4"/>'
        for segment in segments
        if len(segment) >= 2
    )
    dots = "".join(
        f'<circle cx="{coord.split(",")[0]}" cy="{coord.split(",")[1]}" r="3" fill="#111827"/>' for coord in coords
    )
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 800 600" '
        'role="img" aria-label="Recorded GPS traveled path">' + polylines + dots + "</svg>"
    )


def _next_step_for_action(status: str | None) -> str | None:
    mapping = {
        "pending": "Awaiting case owner approval via POST /workflows/actions/{id}/approve",
        "approved": "Action approved; proceed with execution",
        "denied": "Action denied; request was rejected by the case owner",
        "cancelled": "Action request was cancelled",
        "expired": "Action request expired; submit a new one if still needed",
    }
    return mapping.get(status or "", None)


def _next_step_for_question(status: str | None) -> str | None:
    mapping = {
        "pending": "Awaiting human answer via POST /workflows/questions/{id}/answer",
        "answered": "Answer recorded; resume case generation with the new context",
        "declined": "Human declined to answer; proceed without this data",
        "cancelled": "Question was cancelled",
        "expired": "Question expired; issue a new question if still relevant",
        "superseded": "Question superseded by a newer revision",
    }
    return mapping.get(status or "", None)


def _next_step_for_minutes(status: str | None) -> str | None:
    mapping = {
        "draft": "Review and approve via POST /workflows/minutes/{id}/approve",
        "preview": "Analyst has viewed preview; approve via POST /workflows/minutes/{id}/approve",
        "approved": "Send via POST /workflows/minutes/{id}/send after verifying recipient",
        "sent": "Minutes sent; delivery state reflects outbox confirmation",
    }
    return mapping.get(status or "", None)


# ─── Dependency factory ───────────────────────────────────────────────────────


def get_agent_workflow_service() -> AgentWorkflowService:
    return AgentWorkflowService()

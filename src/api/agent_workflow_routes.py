"""Workflow API routes for #86 / #60.

Exports `router` at module level; root integrates it at existing API prefixes.
All public routes require a verified principal via the existing auth dependency.
Route context builds the WorkflowContext from the server-owned Principal;
the service never imports API Principal.

Ownership: this file, src/services/agent_workflow_service.py,
           src/services/workflow_repository.py, src/models/workflow_models.py.
Do NOT edit src/api/auth.py, routes.py, or main.py from this worker.

API schema summary (share with frontend/root early):
  POST /workflows/questions/ask             → AskInteractiveQuestionResult
  GET  /workflows/questions/{question_id}   → WorkflowQuestionResponse
  POST /workflows/questions/{question_id}/answer → AnswerSubmissionResponse
  POST /workflows/minutes/draft             → DraftCaseMinutesResult
  GET  /workflows/minutes/{minutes_id}/preview → PreviewCaseMinutesResult
  POST /workflows/minutes/{minutes_id}/approve → MinutesApprovalResponse
  POST /workflows/minutes/{minutes_id}/send    → MinutesSendResponse
  POST /workflows/actions/request           → RequestActionApprovalResult
  GET  /workflows/actions/{action_id}       → GetActionStatusResult
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from src.api.auth import (
    Principal,
    require_principal,
    require_role,
)
from src.models.workflow_models import (
    AnswerSubmissionResponse,
    AskInteractiveQuestionArguments,
    DraftCaseMinutesArguments,
    GetActionStatusResult,
    MinutesApprovalResponse,
    MinutesSendResponse,
    MinutesStatus,
    QuestionStatus,
    RequestActionApprovalArguments,
    SubmitAnswerRequest,
    WorkflowQuestionPayload,
    WorkflowQuestionResponse,
    compute_content_hash,
    utc_now_iso,
)
from src.services.agent_workflow_service import (
    AgentWorkflowService,
    WorkflowServiceError,
    get_agent_workflow_service,
)
from src.services.case_service import get_case_service
from src.services.workflow_repository import (
    WorkflowPersistenceError,
    approve_minutes,
    get_minutes_by_id,
    get_question_by_id,
    insert_answer,
    list_questions,
    mark_question_answered,
    post_minutes_to_outbox,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/workflows", tags=["workflows"])


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _require_principal_or_401(principal: Principal | None) -> Principal:
    if principal is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    return principal


def _workflow_error_to_http(exc: WorkflowServiceError) -> HTTPException:
    status_map = {
        "VALIDATION_ERROR": 422,
        "FORBIDDEN": 403,
        "NOT_FOUND": 404,
        "CONFLICT": 409,
        "PERSISTENCE_UNAVAILABLE": 503,
    }
    return HTTPException(
        status_code=status_map.get(exc.code, 500),
        detail=str(exc),
    )


def _build_context(
    principal: Principal,
    case_id: str,
    driver_id: str | None = None,
    request_id: str | None = None,
    run_id: str | None = None,
) -> dict[str, Any]:
    """Build a trusted WorkflowContext dict from server-owned data."""
    return {
        "actor_id": str(principal.id),
        "organization_id": str(principal.organization_id),
        "roles": list(principal.roles),
        "case_id": case_id,
        # Principal UUID and driver UUID are distinct. Auth supplies the latter
        # only for verified driver sessions; never infer it from principal.id.
        "driver_id": driver_id or getattr(principal, "driver_id", None),
        "request_id": request_id or str(uuid.uuid4()),
        "run_id": run_id or str(uuid.uuid4()),
        "tool_call_id": str(uuid.uuid4()),
        "turn_id": str(uuid.uuid4()),
    }


def _get_db_conn(service: AgentWorkflowService) -> Any:
    """Get DB connection through service; raise 503 on failure."""
    try:
        return service._get_db_connection()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Database unavailable: {exc}") from exc


def _driver_owns_case(conn: Any, principal: Principal, case_id: str) -> bool:
    """Require verified driver mapping and the case's current assignment."""
    driver_id = getattr(principal, "driver_id", None)
    if not driver_id or "driver" not in principal.roles:
        return False
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT 1
            FROM app.drivers d
            JOIN app.trip_assignments ta ON ta.driver_id = d.id
            JOIN app.fraud_cases fc ON fc.assignment_id = ta.id
            WHERE d.id = %s::uuid
              AND d.principal_id = %s::uuid
              AND fc.id = %s::uuid
            LIMIT 1
            """,
            (driver_id, principal.id, case_id),
        )
        return cur.fetchone() is not None


def _analyst_owns_case(conn: Any, principal: Principal, case_id: str) -> bool:
    """Only the DB-assigned analyst may approve or send case minutes."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT 1 FROM app.fraud_cases
            WHERE id = %s::uuid AND organization_id = %s::uuid
              AND assigned_analyst_id = %s::uuid
            LIMIT 1
            """,
            (case_id, principal.organization_id, principal.id),
        )
        return cur.fetchone() is not None


# ─── Interactive questions ────────────────────────────────────────────────────


@router.get("/questions", response_model=list[WorkflowQuestionResponse])
async def list_pending_questions(
    case_id: str,
    principal: Principal | None = Depends(require_principal),
    service: AgentWorkflowService = Depends(get_agent_workflow_service),
) -> list[WorkflowQuestionResponse]:
    """List pending questions scoped to one case and authenticated audience."""
    p = _require_principal_or_401(principal)
    conn = _get_db_conn(service)
    try:
        if "driver" in p.roles and not _driver_owns_case(conn, p, case_id):
            raise HTTPException(status_code=403, detail="Driver is not assigned to this case")
        rows = list_questions(conn, case_id=case_id, organization_id=str(p.organization_id))
    except WorkflowPersistenceError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    finally:
        conn.close()
    visible = [
        row for row in rows if row.get("actor_target") in ("both", "driver" if "driver" in p.roles else "analyst")
    ]
    return [
        WorkflowQuestionResponse(
            question_id=str(row["id"]),
            question_id_stable=row["question_id_stable"],
            revision=row["revision"],
            case_id=str(row["case_id"]),
            question_kind=row["question_kind"],
            purpose=row["purpose"],
            actor_target=row["actor_target"],
            status=row["status"],
            payload=WorkflowQuestionPayload.model_validate(row.get("payload") or {}),
            created_at=str(row.get("created_at") or ""),
            answered_at=str(row["answered_at"]) if row.get("answered_at") else None,
            expires_at=str(row["expires_at"]) if row.get("expires_at") else None,
        )
        for row in visible
    ]


@router.post("/questions/ask", summary="Ask an interactive workflow question")
async def ask_question(
    body: AskInteractiveQuestionArguments,
    case_id: str,
    principal: Principal | None = Depends(require_principal),
    service: AgentWorkflowService = Depends(get_agent_workflow_service),
) -> dict[str, Any]:
    """Persist a workflow question and return its ID and status.

    Only analyst or driver principals may ask questions. Analyst questions
    targeting 'driver' are evidence requests; the driver must answer via their
    authenticated session.
    """
    p = _require_principal_or_401(principal)
    # Analysts can ask any target; drivers can only ask clarification of themselves
    if "driver" in p.roles:
        conn = _get_db_conn(service)
        try:
            owns_case = _driver_owns_case(conn, p, case_id)
        finally:
            conn.close()
        if not owns_case:
            raise HTTPException(status_code=403, detail="Driver is not assigned to this case")
    if body.actor_target.value == "analyst" and "analyst" not in p.roles and "senior_analyst" not in p.roles:
        if "driver" not in p.roles:
            raise HTTPException(status_code=403, detail="Insufficient role for this question target")

    ctx = _build_context(p, case_id)
    try:
        result = await service.invoke("ask_interactive_question", body.model_dump(), ctx)
    except WorkflowServiceError as exc:
        raise _workflow_error_to_http(exc) from exc
    return result


@router.get(
    "/questions/{question_id}",
    response_model=WorkflowQuestionResponse,
    summary="Get question state",
)
async def get_question(
    question_id: str,
    principal: Principal | None = Depends(require_principal),
    service: AgentWorkflowService = Depends(get_agent_workflow_service),
) -> WorkflowQuestionResponse:
    """Retrieve a question by its DB UUID. Access requires authentication."""
    p = _require_principal_or_401(principal)
    conn = _get_db_conn(service)
    try:
        row = get_question_by_id(conn, question_id)
    except WorkflowPersistenceError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    finally:
        try:
            conn.close()
        except Exception:
            pass

    # Verify organization scope
    if str(row.get("organization_id")) != str(p.organization_id):
        raise HTTPException(status_code=403, detail="Access denied to this question")
    if "driver" in p.roles:
        conn = _get_db_conn(service)
        try:
            owns_case = _driver_owns_case(conn, p, str(row["case_id"]))
        finally:
            conn.close()
        if not owns_case:
            raise HTTPException(status_code=403, detail="Driver is not assigned to this case")

    payload = row.get("payload") or {}
    if isinstance(payload, str):
        payload = json.loads(payload)

    return WorkflowQuestionResponse(
        question_id=str(row["id"]),
        question_id_stable=row["question_id_stable"],
        revision=row["revision"],
        case_id=str(row["case_id"]),
        question_kind=row["question_kind"],
        purpose=row["purpose"],
        actor_target=row["actor_target"],
        status=row["status"],
        payload=WorkflowQuestionPayload.model_validate(payload),
        created_at=str(row.get("created_at") or ""),
        answered_at=str(row["answered_at"]) if row.get("answered_at") else None,
        expires_at=str(row["expires_at"]) if row.get("expires_at") else None,
    )


@router.post(
    "/questions/{question_id}/answer",
    response_model=AnswerSubmissionResponse,
    summary="Submit a human answer to a workflow question",
)
async def submit_answer(
    question_id: str,
    body: SubmitAnswerRequest,
    principal: Principal | None = Depends(require_principal),
    service: AgentWorkflowService = Depends(get_agent_workflow_service),
) -> AnswerSubmissionResponse:
    """Record a human answer for an interactive question.

    Validation rules:
    - Respondent must be authenticated via existing auth dependency.
    - The question must be in 'pending' status and belong to respondent's org.
    - Ordinary answers NEVER grant action approval.
    - Idempotent: same idempotency_key returns stored result.
    """
    p = _require_principal_or_401(principal)

    conn = _get_db_conn(service)
    try:
        # Fetch question to validate respondent scope
        q_row = get_question_by_id(conn, question_id)
    except WorkflowPersistenceError as exc:
        conn.close()
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    # Organization check
    if str(q_row.get("organization_id")) != str(p.organization_id):
        conn.close()
        raise HTTPException(status_code=403, detail="Access denied to this question")

    # Status check
    if q_row.get("status") != "pending":
        conn.close()
        raise HTTPException(
            status_code=409,
            detail=f"Question is not pending (current status: {q_row.get('status')})",
        )

    # Respondent role check: actor_target must match caller role
    actor_target = q_row.get("actor_target")
    is_driver = "driver" in p.roles
    is_analyst = not is_driver

    if is_driver and not _driver_owns_case(conn, p, str(q_row["case_id"])):
        conn.close()
        raise HTTPException(status_code=403, detail="Driver is not assigned to this case")

    if actor_target == "analyst" and is_driver:
        conn.close()
        raise HTTPException(status_code=403, detail="Driver cannot answer analyst-targeted question")
    if actor_target == "driver" and is_analyst:
        conn.close()
        raise HTTPException(status_code=403, detail="Analyst cannot answer driver-targeted question")

    # Validate submitted_value shape based on question kind
    kind = q_row.get("question_kind")
    _validate_answer_value(kind, body.submitted_value, q_row.get("payload") or {})

    try:
        answer_row, idempotent = insert_answer(
            conn,
            question_id=question_id,
            respondent_principal_id=str(p.id),
            submitted_value=body.submitted_value,
            explanation=body.explanation,
            idempotency_key=body.idempotency_key,
        )
        if idempotent and (
            str(answer_row.get("question_id")) != question_id
            or str(answer_row.get("respondent_principal_id")) != str(p.id)
        ):
            raise HTTPException(
                status_code=409,
                detail="Idempotency key is already bound to another answer",
            )
        if not idempotent:
            # Mark question answered
            mark_question_answered(conn, question_id)
    except WorkflowPersistenceError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    finally:
        try:
            conn.close()
        except Exception:
            pass

    return AnswerSubmissionResponse(
        answer_id=str(answer_row["id"]),
        question_id=question_id,
        status=QuestionStatus.answered,
        submitted_at=str(answer_row.get("submitted_at") or utc_now_iso()),
        idempotent=idempotent,
        note="Answer recorded. Ordinary answers do not grant action approval.",
    )


def _validate_answer_value(kind: str | None, value: Any, payload: dict[str, Any]) -> None:
    """Validate submitted_value type matches question kind."""
    if kind == "yes_no":
        if not isinstance(value, bool):
            raise HTTPException(status_code=422, detail="yes_no answer must be a boolean true/false")
    elif kind == "single_choice":
        if not isinstance(value, str):
            raise HTTPException(status_code=422, detail="single_choice answer must be a string option ID")
        _validate_option_ids([value], payload, exact_one=True)
    elif kind == "multiple_choice":
        if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
            raise HTTPException(
                status_code=422,
                detail="multiple_choice answer must be a list of string option IDs",
            )
        _validate_option_ids(value, payload)
    elif kind == "text":
        if not isinstance(value, str):
            raise HTTPException(status_code=422, detail="text answer must be a string")
        if len(value) > 8000:
            raise HTTPException(status_code=422, detail="text answer exceeds 8000 characters")


def _validate_option_ids(values: list[str], payload: dict[str, Any], *, exact_one: bool = False) -> None:
    option_ids = {str(option.get("id")) for option in payload.get("options", [])}
    if exact_one and len(values) != 1:
        raise HTTPException(status_code=422, detail="single_choice requires exactly one option")
    if len(values) != len(set(values)):
        raise HTTPException(status_code=422, detail="multiple_choice options must be unique")
    if not set(values).issubset(option_ids):
        raise HTTPException(status_code=422, detail="Answer contains an unknown option ID")
    max_selections = payload.get("max_selections")
    if max_selections is not None and len(values) > max_selections:
        raise HTTPException(status_code=422, detail="Answer exceeds the question selection limit")


# ─── Case minutes ─────────────────────────────────────────────────────────────


@router.post("/minutes/draft", summary="Draft Vietnamese case minutes")
async def draft_minutes(
    body: DraftCaseMinutesArguments,
    principal: Principal | None = Depends(require_principal),
    service: AgentWorkflowService = Depends(get_agent_workflow_service),
) -> dict[str, Any]:
    """Create a minutes draft grounded in the recorded adjudication.

    Requires analyst role. Returns missing_fields list if decision is absent.
    """
    p = _require_principal_or_401(principal)
    require_role(p, "analyst", "senior_analyst", "demo_operator", "admin")

    ctx = _build_context(p, body.case_id)
    try:
        result = await service.invoke("draft_case_minutes", body.model_dump(exclude={"case_id"}), ctx)
    except WorkflowServiceError as exc:
        raise _workflow_error_to_http(exc) from exc
    return result


@router.get("/minutes/{minutes_id}/preview", summary="Preview case minutes for analyst approval")
async def preview_minutes(
    minutes_id: str,
    case_id: str,
    principal: Principal | None = Depends(require_principal),
    service: AgentWorkflowService = Depends(get_agent_workflow_service),
) -> dict[str, Any]:
    """Return the full deterministic preview including content hash.

    The analyst must approve the exact hash returned here.
    """
    p = _require_principal_or_401(principal)
    require_role(p, "analyst", "senior_analyst", "demo_operator", "admin")

    ctx = _build_context(p, case_id)
    try:
        result = await service.invoke("preview_case_minutes", {"minutes_id": minutes_id}, ctx)
    except WorkflowServiceError as exc:
        raise _workflow_error_to_http(exc) from exc
    return result


@router.post(
    "/minutes/{minutes_id}/approve",
    response_model=MinutesApprovalResponse,
    summary="Approve minutes for sending",
)
async def approve_minutes_endpoint(
    minutes_id: str,
    case_id: str,
    content_hash: str,
    principal: Principal | None = Depends(require_principal),
    service: AgentWorkflowService = Depends(get_agent_workflow_service),
) -> MinutesApprovalResponse:
    """Case owner approves the exact previewed minutes by submitting its content hash.

    Only the analyst who owns the case may approve. The model cannot approve.
    Generic question answers never trigger this path.
    """
    p = _require_principal_or_401(principal)
    require_role(p, "analyst", "senior_analyst", "demo_operator", "admin")

    conn = _get_db_conn(service)
    try:
        # Verify case ownership by checking current lease or assignment
        row = get_minutes_by_id(conn, minutes_id)
        if str(row.get("case_id")) != case_id:
            raise HTTPException(status_code=403, detail="Minutes case_id mismatch")
        if str(row.get("organization_id")) != str(p.organization_id):
            raise HTTPException(status_code=403, detail="Organization mismatch")
        if not _analyst_owns_case(conn, p, case_id):
            raise HTTPException(status_code=403, detail="Only the assigned case owner may approve minutes")

        # Verify the hash matches current content
        content = row.get("content") or {}
        if isinstance(content, str):
            content = json.loads(content)
        actual_hash = compute_content_hash(content)
        if actual_hash != content_hash:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Content hash mismatch. You approved hash {content_hash!r} but "
                    f"current content hash is {actual_hash!r}. Fetch a fresh preview."
                ),
            )

        approved_row = approve_minutes(conn, minutes_id, approved_by=str(p.id), content_hash=content_hash)
    except (WorkflowPersistenceError, HTTPException):
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    finally:
        try:
            conn.close()
        except Exception:
            pass

    return MinutesApprovalResponse(
        minutes_id=minutes_id,
        revision=approved_row.get("revision", 1),
        status=MinutesStatus.approved,
        approved_by=str(p.id),
        approved_at=str(approved_row.get("approved_at") or utc_now_iso()),
        content_hash=content_hash,
    )


@router.post(
    "/minutes/{minutes_id}/send",
    response_model=MinutesSendResponse,
    summary="Post approved minutes to driver conversation via outbox",
)
async def send_minutes(
    minutes_id: str,
    case_id: str,
    recipient_driver_id: str,
    principal: Principal | None = Depends(require_principal),
    service: AgentWorkflowService = Depends(get_agent_workflow_service),
) -> MinutesSendResponse:
    """Post approved minutes to the driver's existing conversation via outbox.

    Delivery state starts as 'stored'. The outbox worker updates to 'sent'/'queued'.
    Idempotent: repeated calls return the stored sent state without re-inserting.
    Sending after final decision uses the durable case-owner principal, not a
    released investigation lease.
    """
    p = _require_principal_or_401(principal)
    require_role(p, "analyst", "senior_analyst", "demo_operator", "admin")

    conn = _get_db_conn(service)
    try:
        row = get_minutes_by_id(conn, minutes_id)
        if str(row.get("case_id")) != case_id:
            raise HTTPException(status_code=403, detail="Minutes case_id mismatch")
        if str(row.get("organization_id")) != str(p.organization_id):
            raise HTTPException(status_code=403, detail="Organization mismatch")
        if not _analyst_owns_case(conn, p, case_id):
            raise HTTPException(status_code=403, detail="Only the assigned case owner may send minutes")
        if row.get("status") not in ("approved", "sent"):
            raise HTTPException(
                status_code=409,
                detail=f"Minutes must be approved before sending (status: {row.get('status')})",
            )
        # Verify recipient belongs to same org
        case_svc = get_case_service()
        driver_ok = False
        try:
            # Quick org/driver validation via case service
            driver_info = case_svc._drivers.get(recipient_driver_id)
            if driver_info:
                driver_ok = str(driver_info.get("organization_id")) == str(p.organization_id)
        except Exception:
            pass

        if not driver_ok:
            # Try DB validation
            try:
                with conn.cursor() as cur:
                    cur.execute("SET search_path = app, extensions, public;")
                    cur.execute(
                        """
                        SELECT 1
                        FROM app.drivers d
                        JOIN app.trip_assignments ta ON ta.driver_id = d.id
                        JOIN app.fraud_cases fc ON fc.assignment_id = ta.id
                        WHERE d.id = %s::uuid
                          AND d.organization_id = %s::uuid
                          AND fc.id = %s::uuid
                        LIMIT 1
                        """,
                        (recipient_driver_id, p.organization_id, case_id),
                    )
                    dr = cur.fetchone()
                    if dr:
                        driver_ok = True
            except Exception:
                pass

        if not driver_ok:
            raise HTTPException(
                status_code=403,
                detail="Recipient driver not found or belongs to a different organization",
            )

        # Build outbox payload
        content = row.get("content") or {}
        if isinstance(content, str):
            content = json.loads(content)
        outbox_payload = {
            "minutes_id": minutes_id,
            "case_id": case_id,
            "recipient_driver_id": recipient_driver_id,
            "approved_by": str(p.id),
            "content_hash": row.get("approved_content_hash"),
            "content": content,
            "sent_by": str(p.id),
        }

        sent_row = post_minutes_to_outbox(
            conn,
            minutes_id,
            case_id=case_id,
            organization_id=str(p.organization_id),
            payload=outbox_payload,
        )
    except (WorkflowPersistenceError, HTTPException) as exc:
        if isinstance(exc, HTTPException):
            raise
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    finally:
        try:
            conn.close()
        except Exception:
            pass

    return MinutesSendResponse(
        minutes_id=minutes_id,
        outbox_event_id=str(sent_row.get("outbox_event_id") or ""),
        delivery_state=sent_row.get("delivery_state", "stored"),  # type: ignore[arg-type]
        sent_at=str(sent_row.get("sent_at") or utc_now_iso()),
    )


# ─── Action approval ──────────────────────────────────────────────────────────


@router.post("/actions/request", summary="Request action approval from the case owner")
async def request_action_approval(
    body: RequestActionApprovalArguments,
    case_id: str,
    principal: Principal | None = Depends(require_principal),
    service: AgentWorkflowService = Depends(get_agent_workflow_service),
) -> dict[str, Any]:
    """Persist an action approval request.

    The model cannot approve its own proposal. The case owner approves via
    POST /workflows/actions/{id}/approve. Generic question answers never trigger
    this approval path.
    """
    p = _require_principal_or_401(principal)
    require_role(p, "analyst", "senior_analyst", "demo_operator", "admin")

    ctx = _build_context(p, case_id)
    try:
        result = await service.invoke("request_action_approval", body.model_dump(), ctx)
    except WorkflowServiceError as exc:
        raise _workflow_error_to_http(exc) from exc
    return result


@router.get(
    "/actions/{action_id}",
    response_model=GetActionStatusResult,
    summary="Get action request / question / minutes status",
)
async def get_action_status(
    action_id: str,
    case_id: str,
    principal: Principal | None = Depends(require_principal),
    service: AgentWorkflowService = Depends(get_agent_workflow_service),
) -> GetActionStatusResult:
    """Read current status of an action request, question, or minutes record."""
    p = _require_principal_or_401(principal)

    ctx = _build_context(p, case_id)
    try:
        result = await service.invoke("get_action_status", {"action_request_id": action_id}, ctx)
    except WorkflowServiceError as exc:
        raise _workflow_error_to_http(exc) from exc
    return GetActionStatusResult(**result)

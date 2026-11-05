"""Behavioral RED→GREEN tests for AgentWorkflowService (#86 / #60).

Test strategy:
- One behavioral RED → minimal GREEN per public seam.
- Real isolated Postgres at 127.0.0.1:32794 (from runtime.env).
- No mock-only acceptance; no destructive shared resets.
- Tests use fixture data and are idempotent.

RED targets:
1. AgentWorkflowService.invoke() with unknown operation raises WorkflowServiceError
2. ask_interactive_question persists and returns question_id with pending status
3. Duplicate ask with same stable ID + pending → idempotent return (same id)
4. Single-choice question requires >= 2 options (validation)
5. yes_no question must not specify custom options (validation)
6. Driver role blocked from draft_case_minutes
7. request_action_approval creates pending record (analyst context)
8. Context with missing required field raises error
9. get_action_status returns action_request record details
10. Ordinary answer (not action_confirmation question) does NOT grant approval

GREEN: each test imports from the owned modules and asserts real DB persistence.
"""

from __future__ import annotations

import os
import uuid
from typing import Any

import pytest

pytestmark = pytest.mark.docker

# Force test env so DB_URL points to isolated postgres
if "APP_ENV" not in os.environ:
    os.environ["APP_ENV"] = "test"


# ─── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def db_conn():
    """Real isolated DB connection. Skip if DB not available."""
    try:
        import psycopg
        from psycopg.rows import dict_row

        url = os.getenv("DATABASE_URL", "postgresql://postgres:postgrespassword@127.0.0.1:32794/postgres")
        conn = psycopg.connect(url, row_factory=dict_row)
        yield conn
        conn.close()
    except Exception as exc:
        pytest.skip(f"Database not available: {exc}")


@pytest.fixture(scope="module")
def seed_ids(db_conn):
    """Fetch real case/org/principal IDs from the migrated DB for use in tests."""
    try:
        with db_conn.cursor() as cur:
            cur.execute("SET search_path = app, extensions, public;")
            cur.execute("SELECT id, organization_id FROM app.fraud_cases LIMIT 1")
            case_row = cur.fetchone()
            if not case_row:
                pytest.skip("No fraud cases seeded in isolated DB")

            cur.execute(
                "SELECT p.id FROM app.principals p "
                "JOIN app.principal_roles pr ON pr.principal_id = p.id "
                "WHERE pr.role = 'analyst' LIMIT 1"
            )
            analyst_row = cur.fetchone()
            if not analyst_row:
                pytest.skip("No analyst principal seeded in isolated DB")

            cur.execute(
                "SELECT p.id FROM app.principals p "
                "JOIN app.principal_roles pr ON pr.principal_id = p.id "
                "WHERE pr.role = 'driver' LIMIT 1"
            )
            driver_row = cur.fetchone()

        return {
            "case_id": str(case_row["id"]),
            "organization_id": str(case_row["organization_id"]),
            "analyst_id": str(analyst_row["id"]),
            "driver_id": str(driver_row["id"]) if driver_row else str(uuid.uuid4()),
        }
    except Exception as exc:
        pytest.skip(f"Seed data not available: {exc}")


def _analyst_ctx(seed: dict[str, Any]) -> dict[str, Any]:
    return {
        "actor_id": seed["analyst_id"],
        "organization_id": seed["organization_id"],
        "roles": ["analyst"],
        "case_id": seed["case_id"],
        "driver_id": None,
        "request_id": str(uuid.uuid4()),
        "run_id": str(uuid.uuid4()),
        "tool_call_id": str(uuid.uuid4()),
        "turn_id": str(uuid.uuid4()),
    }


def _driver_ctx(seed: dict[str, Any]) -> dict[str, Any]:
    return {
        "actor_id": seed["driver_id"],
        "organization_id": seed["organization_id"],
        "roles": ["driver"],
        "case_id": seed["case_id"],
        "driver_id": seed["driver_id"],
        "request_id": str(uuid.uuid4()),
        "run_id": str(uuid.uuid4()),
        "tool_call_id": str(uuid.uuid4()),
        "turn_id": str(uuid.uuid4()),
    }


# ─── Import smoke ────────────────────────────────────────────────────────────


def test_workflow_service_imports():
    """Imports succeed; owned module exists."""
    from src.models.workflow_models import (  # noqa: F401
        DeliveryState,
        MinutesStatus,
        QuestionKind,
        QuestionStatus,
        WorkflowContext,
    )
    from src.services.agent_workflow_service import (  # noqa: F401
        SUPPORTED_OPERATIONS,
        AgentWorkflowService,
        WorkflowServiceError,
        get_agent_workflow_service,
    )

    assert "ask_interactive_question" in SUPPORTED_OPERATIONS
    assert "draft_case_minutes" in SUPPORTED_OPERATIONS


def test_workflow_models_import():
    """Workflow models import and validate correctly."""
    from src.models.workflow_models import (
        ActorTarget,
        AskInteractiveQuestionArguments,
        QuestionKind,
        QuestionOption,
        QuestionPurpose,
    )

    args = AskInteractiveQuestionArguments(
        question_id_stable="test-q-001",
        question_kind=QuestionKind.single_choice,
        purpose=QuestionPurpose.clarification,
        actor_target=ActorTarget.driver,
        question_text="Bạn có gặp tình trạng kẹt xe không?",
        options=[
            QuestionOption(id="yes", label="Có"),
            QuestionOption(id="no", label="Không"),
        ],
    )
    assert args.question_id_stable == "test-q-001"


# ─── Validation RED tests ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_unknown_operation_raises_error():
    """RED: Unknown operation raises WorkflowServiceError (not an unhandled exception)."""
    from src.services.agent_workflow_service import AgentWorkflowService, WorkflowServiceError
    from src.services.case_service import get_case_service

    svc = AgentWorkflowService(case_service=get_case_service())
    ctx = {
        "actor_id": str(uuid.uuid4()),
        "organization_id": str(uuid.uuid4()),
        "roles": ["analyst"],
        "case_id": str(uuid.uuid4()),
        "driver_id": None,
        "request_id": str(uuid.uuid4()),
        "run_id": str(uuid.uuid4()),
        "tool_call_id": str(uuid.uuid4()),
        "turn_id": str(uuid.uuid4()),
    }
    with pytest.raises(WorkflowServiceError) as exc_info:
        await svc.invoke("nonexistent_operation", {}, ctx)
    assert exc_info.value.code == "VALIDATION_ERROR"


@pytest.mark.asyncio
async def test_single_choice_requires_two_options():
    """RED: single_choice with < 2 options raises validation error."""
    import pydantic

    from src.models.workflow_models import ActorTarget, AskInteractiveQuestionArguments, QuestionKind

    with pytest.raises((pydantic.ValidationError, ValueError)):
        AskInteractiveQuestionArguments(
            question_id_stable="bad-q",
            question_kind=QuestionKind.single_choice,
            actor_target=ActorTarget.driver,
            question_text="Question with no options?",
            options=[],  # Invalid: must have >= 2
        )


@pytest.mark.asyncio
async def test_yes_no_rejects_custom_options():
    """RED: yes_no with custom options raises validation error."""
    import pydantic

    from src.models.workflow_models import ActorTarget, AskInteractiveQuestionArguments, QuestionKind, QuestionOption

    with pytest.raises((pydantic.ValidationError, ValueError)):
        AskInteractiveQuestionArguments(
            question_id_stable="bad-yn",
            question_kind=QuestionKind.yes_no,
            actor_target=ActorTarget.driver,
            question_text="Có không?",
            options=[QuestionOption(id="maybe", label="Có thể")],  # Invalid
        )


@pytest.mark.asyncio
async def test_missing_context_field_raises_error():
    """RED: Context missing required actor_id raises KeyError/ValidationError."""
    from src.models.workflow_models import WorkflowContext

    with pytest.raises((KeyError, ValueError, Exception)):
        WorkflowContext.from_dict(
            {
                # Missing actor_id
                "organization_id": str(uuid.uuid4()),
                "roles": ["analyst"],
                "case_id": str(uuid.uuid4()),
                "request_id": str(uuid.uuid4()),
                "run_id": str(uuid.uuid4()),
                "tool_call_id": str(uuid.uuid4()),
                "turn_id": str(uuid.uuid4()),
            }
        )


@pytest.mark.asyncio
async def test_driver_cannot_draft_minutes():
    """RED: driver role blocked from draft_case_minutes."""
    from src.services.agent_workflow_service import AgentWorkflowService, WorkflowServiceError
    from src.services.case_service import get_case_service

    svc = AgentWorkflowService(case_service=get_case_service())
    ctx = {
        "actor_id": str(uuid.uuid4()),
        "organization_id": str(uuid.uuid4()),
        "roles": ["driver"],  # Driver role only
        "case_id": str(uuid.uuid4()),
        "driver_id": str(uuid.uuid4()),
        "request_id": str(uuid.uuid4()),
        "run_id": str(uuid.uuid4()),
        "tool_call_id": str(uuid.uuid4()),
        "turn_id": str(uuid.uuid4()),
    }
    with pytest.raises(WorkflowServiceError) as exc_info:
        await svc.invoke("draft_case_minutes", {"case_id": ctx["case_id"]}, ctx)
    assert exc_info.value.code == "FORBIDDEN"


@pytest.mark.asyncio
async def test_driver_cannot_request_action_approval():
    """RED: driver role blocked from request_action_approval."""
    from src.services.agent_workflow_service import AgentWorkflowService, WorkflowServiceError
    from src.services.case_service import get_case_service

    svc = AgentWorkflowService(case_service=get_case_service())
    ctx = {
        "actor_id": str(uuid.uuid4()),
        "organization_id": str(uuid.uuid4()),
        "roles": ["driver"],
        "case_id": str(uuid.uuid4()),
        "driver_id": str(uuid.uuid4()),
        "request_id": str(uuid.uuid4()),
        "run_id": str(uuid.uuid4()),
        "tool_call_id": str(uuid.uuid4()),
        "turn_id": str(uuid.uuid4()),
    }
    with pytest.raises(WorkflowServiceError) as exc_info:
        await svc.invoke(
            "request_action_approval",
            {"action_kind": "send_minutes", "payload": {}, "consequence_summary": "test"},
            ctx,
        )
    assert exc_info.value.code == "FORBIDDEN"


# ─── DB persistence tests ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_ask_question_persists_to_db(seed_ids):
    """GREEN: ask_interactive_question creates a real DB row with pending status."""
    from src.services.agent_workflow_service import AgentWorkflowService
    from src.services.case_service import get_case_service

    svc = AgentWorkflowService(case_service=get_case_service())
    ctx = _analyst_ctx(seed_ids)

    stable_id = f"test-q-{uuid.uuid4().hex[:8]}"
    result = await svc.invoke(
        "ask_interactive_question",
        {
            "question_id_stable": stable_id,
            "question_kind": "single_choice",
            "purpose": "clarification",
            "actor_target": "driver",
            "question_text": "Tình trạng giao thông tại thời điểm xảy ra sự cố?",
            "options": [
                {"id": "heavy", "label": "Ùn tắc nghiêm trọng"},
                {"id": "normal", "label": "Bình thường"},
                {"id": "unknown", "label": "Không nhớ rõ"},
            ],
        },
        ctx,
    )

    assert result["question_id_stable"] == stable_id
    assert result["status"] == "pending"
    assert result["case_id"] == seed_ids["case_id"]
    assert "question_id" in result
    assert len(result["question_id"]) == 36  # UUID


@pytest.mark.asyncio
async def test_ask_question_idempotent_same_stable_id(seed_ids):
    """GREEN: Calling ask with same pending stable ID returns the same question_id."""
    from src.services.agent_workflow_service import AgentWorkflowService
    from src.services.case_service import get_case_service

    svc = AgentWorkflowService(case_service=get_case_service())
    ctx = _analyst_ctx(seed_ids)
    stable_id = f"idem-q-{uuid.uuid4().hex[:8]}"

    args = {
        "question_id_stable": stable_id,
        "question_kind": "yes_no",
        "purpose": "clarification",
        "actor_target": "driver",
        "question_text": "Có phải bạn đang đợi khách không?",
        "options": [],
    }

    r1 = await svc.invoke("ask_interactive_question", args, ctx)
    r2 = await svc.invoke("ask_interactive_question", args, ctx)

    assert r1["question_id"] == r2["question_id"]
    assert r2["already_exists"] is True


@pytest.mark.asyncio
async def test_request_action_approval_creates_pending_record(seed_ids):
    """GREEN: request_action_approval persists a pending action request."""
    from src.services.agent_workflow_service import AgentWorkflowService
    from src.services.case_service import get_case_service

    svc = AgentWorkflowService(case_service=get_case_service())
    ctx = _analyst_ctx(seed_ids)

    result = await svc.invoke(
        "request_action_approval",
        {
            "action_kind": "send_case_minutes",
            "payload": {
                "minutes_id": str(uuid.uuid4()),
                "recipient_driver_id": seed_ids["driver_id"],
            },
            "consequence_summary": "Gửi biên bản kết quả xử lý đến tài xế",
        },
        ctx,
    )

    assert result["action_kind"] == "send_case_minutes"
    assert result["status"] == "pending"
    assert "action_request_id" in result
    assert "payload_hash" in result


@pytest.mark.asyncio
async def test_request_action_approval_idempotent(seed_ids):
    """GREEN: Same action payload → same action_request_id (already_exists=True)."""
    from src.services.agent_workflow_service import AgentWorkflowService
    from src.services.case_service import get_case_service

    svc = AgentWorkflowService(case_service=get_case_service())
    ctx = _analyst_ctx(seed_ids)

    fixed_payload = {
        "action_kind": "send_case_minutes",
        "payload": {"minutes_id": "fixed-idem-minutes-001", "recipient_driver_id": "drv-001"},
        "consequence_summary": "Idempotency test",
    }
    r1 = await svc.invoke("request_action_approval", fixed_payload, ctx)
    r2 = await svc.invoke("request_action_approval", fixed_payload, ctx)

    assert r1["action_request_id"] == r2["action_request_id"]
    assert r2["already_exists"] is True


@pytest.mark.asyncio
async def test_get_action_status_returns_result(seed_ids):
    """GREEN: get_action_status retrieves action request details."""
    from src.services.agent_workflow_service import AgentWorkflowService
    from src.services.case_service import get_case_service

    svc = AgentWorkflowService(case_service=get_case_service())
    ctx = _analyst_ctx(seed_ids)

    # First create an action request
    create_result = await svc.invoke(
        "request_action_approval",
        {
            "action_kind": "test_action",
            "payload": {"ref": str(uuid.uuid4())},
            "consequence_summary": "test status retrieval",
        },
        ctx,
    )
    action_id = create_result["action_request_id"]

    # Now retrieve it
    status_result = await svc.invoke(
        "get_action_status",
        {"action_request_id": action_id},
        ctx,
    )

    assert status_result["kind"] == "action_request"
    assert status_result["record_id"] == action_id
    assert status_result["status"] == "pending"
    assert status_result["next_step"] is not None


# ─── Ordinary answer never grants approval ────────────────────────────────────


@pytest.mark.asyncio
async def test_answer_does_not_grant_approval(seed_ids):
    """CRITICAL: Submitting an answer to a question does NOT change action_request to approved.

    This is a core security invariant. The answer endpoint returns a note
    explicitly stating this; the action_request stays pending.
    """
    from src.services.agent_workflow_service import AgentWorkflowService
    from src.services.case_service import get_case_service
    from src.services.workflow_repository import (
        get_action_request_by_id,
        insert_answer,
    )

    svc = AgentWorkflowService(case_service=get_case_service())
    ctx = _analyst_ctx(seed_ids)

    # Create an action approval request
    action_result = await svc.invoke(
        "request_action_approval",
        {
            "action_kind": "check_approval_invariant",
            "payload": {"test": str(uuid.uuid4())},
            "consequence_summary": "Must not be approved by answer",
        },
        ctx,
    )
    action_id = action_result["action_request_id"]

    # Create a clarification question
    q_result = await svc.invoke(
        "ask_interactive_question",
        {
            "question_id_stable": f"inv-q-{uuid.uuid4().hex[:8]}",
            "question_kind": "yes_no",
            "purpose": "clarification",  # NOT action_confirmation
            "actor_target": "analyst",
            "question_text": "Xác nhận?",
            "options": [],
        },
        ctx,
    )
    question_id = q_result["question_id"]

    # Submit an answer to the question
    conn = svc._get_db_connection()
    try:
        answer_row, _ = insert_answer(
            conn,
            question_id=question_id,
            respondent_principal_id=seed_ids["analyst_id"],
            submitted_value=True,
            explanation=None,
            idempotency_key=f"inv-answer-{uuid.uuid4().hex}",
        )
        # The action request must STILL be pending
        action_row = get_action_request_by_id(conn, action_id)
        assert action_row["status"] == "pending", (
            "INVARIANT VIOLATED: answer submission changed action_request status to "
            f"{action_row['status']!r}; must remain 'pending'"
        )
    finally:
        conn.close()


# ─── draft_evidence_request test ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_draft_evidence_request_requires_analyst(seed_ids):
    """RED: driver role blocked from draft_evidence_request."""
    from src.services.agent_workflow_service import AgentWorkflowService, WorkflowServiceError
    from src.services.case_service import get_case_service

    svc = AgentWorkflowService(case_service=get_case_service())
    ctx = _driver_ctx(seed_ids)

    with pytest.raises(WorkflowServiceError) as exc_info:
        await svc.invoke(
            "draft_evidence_request",
            {
                "evidence_gap_description": "Thiếu GPS 14:30-14:45",
                "question_text": "Bạn có giải thích gì cho khoảng thời gian mất GPS không?",
                "allowed_submission_options": [],
                "policy_deadline_hours": 48,
            },
            ctx,
        )
    assert exc_info.value.code == "FORBIDDEN"


@pytest.mark.asyncio
async def test_draft_evidence_request_analyst_ok(seed_ids):
    """GREEN: analyst can draft an evidence request."""
    from src.services.agent_workflow_service import AgentWorkflowService
    from src.services.case_service import get_case_service

    svc = AgentWorkflowService(case_service=get_case_service())
    ctx = _analyst_ctx(seed_ids)

    result = await svc.invoke(
        "draft_evidence_request",
        {
            "evidence_gap_description": "GPS gap 14:30-14:45 ngày 2026-09-15",
            "question_text": "Bạn có thể giải thích về khoảng thời gian mất tín hiệu GPS không?",
            "allowed_submission_options": ["gps_interference", "tunnel", "other"],
            "policy_deadline_hours": 48,
        },
        ctx,
    )

    assert result["status"] == "draft"
    assert "draft_id" in result
    assert "note" in result
    # Note must say send requires approval
    assert "approval" in result["note"].lower() or "send" in result["note"].lower()

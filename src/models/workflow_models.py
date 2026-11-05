"""Workflow domain models for Issue #86 / #60.

Pydantic V2 models for interactive questions, human answers, case minutes,
and action-approval requests. These are owned by this worker; root integrates
them through the API schema / event contract.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

# ─── Enums ───────────────────────────────────────────────────────────────────


class QuestionKind(StrEnum):
    single_choice = "single_choice"
    multiple_choice = "multiple_choice"
    yes_no = "yes_no"
    text = "text"


class QuestionPurpose(StrEnum):
    clarification = "clarification"
    action_confirmation = "action_confirmation"


class QuestionStatus(StrEnum):
    pending = "pending"
    answered = "answered"
    declined = "declined"
    cancelled = "cancelled"
    expired = "expired"
    superseded = "superseded"


class MinutesStatus(StrEnum):
    draft = "draft"
    preview = "preview"
    approved = "approved"
    sent = "sent"


class DeliveryState(StrEnum):
    stored = "stored"
    queued = "queued"
    sent = "sent"
    delivered = "delivered"
    read = "read"
    failed = "failed"


class ActionRequestStatus(StrEnum):
    pending = "pending"
    approved = "approved"
    denied = "denied"
    cancelled = "cancelled"
    expired = "expired"


class ActorTarget(StrEnum):
    analyst = "analyst"
    driver = "driver"
    both = "both"


# ─── Tool execution context ───────────────────────────────────────────────────


class WorkflowContext(BaseModel):
    """Trusted context injected by the runtime; never parsed from model arguments."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    actor_id: str
    organization_id: str
    roles: frozenset[str]
    case_id: str
    driver_id: str | None = None
    request_id: str
    run_id: str
    tool_call_id: str
    turn_id: str

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> WorkflowContext:
        roles = d.get("roles", [])
        if isinstance(roles, (list, tuple, set, frozenset)):
            roles = frozenset(roles)
        return cls(
            actor_id=d["actor_id"],
            organization_id=d["organization_id"],
            roles=roles,
            case_id=d["case_id"],
            driver_id=d.get("driver_id"),
            request_id=d["request_id"],
            run_id=d["run_id"],
            tool_call_id=d["tool_call_id"],
            turn_id=d["turn_id"],
        )

    def has_role(self, *roles: str) -> bool:
        return bool(self.roles & set(roles))

    def is_analyst(self) -> bool:
        return self.has_role("analyst", "senior_analyst", "demo_operator", "admin")

    def is_driver(self) -> bool:
        return self.has_role("driver")


# ─── Question models ──────────────────────────────────────────────────────────


class QuestionOption(BaseModel):
    """A single selectable option within a choice question."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(..., description="Stable option ID; must not change across revisions")
    label: str = Field(..., description="Vietnamese display text")
    hint: str | None = None


class WorkflowQuestionPayload(BaseModel):
    """Full question payload stored in the DB and returned to the UI."""

    model_config = ConfigDict(extra="forbid")

    question_text: str = Field(..., description="Vietnamese question text")
    options: list[QuestionOption] = Field(default_factory=list)
    max_selections: int | None = Field(None, ge=1)
    hint: str | None = None
    allows_explanation: bool = False


class WorkflowQuestion(BaseModel):
    """Domain model for a persisted workflow question."""

    model_config = ConfigDict(extra="forbid")

    id: str  # DB UUID
    question_id_stable: str
    revision: int
    case_id: str
    organization_id: str
    actor_target: ActorTarget
    question_kind: QuestionKind
    purpose: QuestionPurpose
    payload: WorkflowQuestionPayload
    status: QuestionStatus
    created_by_actor_id: str | None
    created_at: str  # ISO
    answered_at: str | None = None
    expires_at: str | None = None


class AskInteractiveQuestionArguments(BaseModel):
    """Arguments for the ask_interactive_question tool call."""

    model_config = ConfigDict(extra="forbid")

    question_id_stable: str = Field(..., description="Stable caller-assigned ID; reissuing same ID increments revision")
    question_kind: QuestionKind
    purpose: QuestionPurpose = QuestionPurpose.clarification
    actor_target: ActorTarget
    question_text: str
    options: list[QuestionOption] = Field(default_factory=list)
    max_selections: int | None = None
    hint: str | None = None
    allows_explanation: bool = False

    @model_validator(mode="after")
    def validate_options(self) -> AskInteractiveQuestionArguments:
        option_ids = [option.id for option in self.options]
        if len(option_ids) != len(set(option_ids)):
            raise ValueError("question option IDs must be unique")
        if self.question_kind in (QuestionKind.single_choice, QuestionKind.multiple_choice):
            if len(self.options) < 2:
                raise ValueError(f"{self.question_kind} requires at least 2 options")
            if self.question_kind == QuestionKind.single_choice and self.max_selections not in (None, 1):
                raise ValueError("single_choice allows at most one selection")
            if self.max_selections is not None and self.max_selections > len(self.options):
                raise ValueError("max_selections cannot exceed the number of options")
        elif self.question_kind == QuestionKind.yes_no:
            if self.options:
                raise ValueError("yes_no questions must not specify custom options")
            if self.max_selections is not None:
                raise ValueError("yes_no questions do not use max_selections")
        elif self.max_selections is not None:
            raise ValueError("text questions do not use max_selections")
        return self


class AskInteractiveQuestionResult(BaseModel):
    """Return value from ask_interactive_question (tool success payload)."""

    model_config = ConfigDict(extra="forbid")

    question_id: str  # DB UUID
    question_id_stable: str
    revision: int
    status: QuestionStatus
    case_id: str
    # Idempotent: True if question already existed at this revision
    already_exists: bool = False


# ─── Answer models ────────────────────────────────────────────────────────────


class SubmitAnswerRequest(BaseModel):
    """HTTP request body for submitting a human answer."""

    model_config = ConfigDict(extra="forbid")

    submitted_value: Any  # str | bool | list[str]
    explanation: str | None = None
    idempotency_key: str


class WorkflowAnswer(BaseModel):
    """Domain model for a recorded human answer."""

    model_config = ConfigDict(extra="forbid")

    id: str
    question_id: str
    respondent_principal_id: str
    submitted_value: Any
    explanation: str | None
    submitted_at: str
    idempotency_key: str


# ─── Minutes models ───────────────────────────────────────────────────────────


class MinutesSection(BaseModel):
    """A section of Vietnamese case minutes."""

    model_config = ConfigDict(extra="forbid")

    section_key: str  # e.g. "Thông tin định danh"
    content: str


class WorkflowMinutesContent(BaseModel):
    """Structured Vietnamese minutes content."""

    model_config = ConfigDict(extra="forbid")

    document_id: str
    revision: int
    issued_at: str  # ISO
    status_label: str  # "Bản nháp" | "Đã duyệt" | "Đã gửi"
    sections: list[MinutesSection]
    map_svg: str | None = None
    source_revision: str | None = None


class DraftCaseMinutesArguments(BaseModel):
    """Arguments for draft_case_minutes tool."""

    model_config = ConfigDict(extra="forbid")

    case_id: str
    decision_id: str | None = None
    map_ref: str | None = None
    evidence_snapshot_id: str | None = None


class DraftCaseMinutesResult(BaseModel):
    """Result from draft_case_minutes."""

    model_config = ConfigDict(extra="forbid")

    minutes_id: str
    revision: int
    status: MinutesStatus
    case_id: str
    content_preview: str  # First 500 chars of rendered Vietnamese
    missing_fields: list[str] = Field(default_factory=list)


class PreviewCaseMinutesArguments(BaseModel):
    """Arguments for preview_case_minutes tool."""

    model_config = ConfigDict(extra="forbid")

    minutes_id: str


class PreviewCaseMinutesResult(BaseModel):
    """Full deterministic preview returned to the assigned analyst."""

    model_config = ConfigDict(extra="forbid")

    minutes_id: str
    revision: int
    status: MinutesStatus
    case_id: str
    recipient_driver_id: str | None
    recipient_display_name: str | None
    content: WorkflowMinutesContent
    map_ref: str | None
    evidence_snapshot_id: str | None
    decision_id: str | None
    content_hash: str
    missing_required_fields: list[str]
    ready_to_approve: bool


class WorkflowMinutes(BaseModel):
    """Domain model for persisted case minutes."""

    model_config = ConfigDict(extra="forbid")

    id: str
    case_id: str
    organization_id: str
    revision: int
    decision_id: str | None
    content: WorkflowMinutesContent
    map_ref: str | None
    evidence_snapshot_id: str | None
    status: MinutesStatus
    approved_by: str | None
    approved_at: str | None
    approved_content_hash: str | None
    sent_at: str | None
    delivery_state: DeliveryState | None
    outbox_event_id: str | None
    drafted_by: str | None
    created_at: str


class ApproveMinutesRequest(BaseModel):
    """HTTP request body for approving minutes."""

    model_config = ConfigDict(extra="forbid")

    content_hash: str = Field(..., description="Must match the previewed content hash exactly")


class SendMinutesRequest(BaseModel):
    """HTTP request body for sending approved minutes."""

    model_config = ConfigDict(extra="forbid")

    minutes_id: str
    recipient_driver_id: str


# ─── Action approval models ───────────────────────────────────────────────────

SUPPORTED_ACTION_KINDS = (
    "send_approved_case_minutes",
    "send_approved_evidence_request",
    "submit_approved_adjudication",
    "submit_approved_escalation",
    "submit_driver_statement",
)


class RequestActionApprovalArguments(BaseModel):
    """Arguments for request_action_approval tool."""

    model_config = ConfigDict(extra="forbid")

    action_kind: str = Field(
        ...,
        description=(
            "Stable canonical action kind. Supported values: "
            + ", ".join(SUPPORTED_ACTION_KINDS)
            + ". Unknown values remain proposals and cannot execute."
        ),
    )
    payload: dict[str, Any] = Field(..., description="Full action payload for human review")
    consequence_summary: str = Field(..., description="What will happen if approved")


class RequestActionApprovalResult(BaseModel):
    """Result from request_action_approval."""

    model_config = ConfigDict(extra="forbid")

    action_request_id: str
    action_kind: str
    status: ActionRequestStatus
    payload_hash: str
    already_exists: bool = False


class GetActionStatusArguments(BaseModel):
    """Arguments for get_action_status tool."""

    model_config = ConfigDict(extra="forbid")

    action_request_id: str | None = None
    question_id_stable: str | None = None
    minutes_id: str | None = None


class GetActionStatusResult(BaseModel):
    """Polymorphic status result."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["action_request", "question", "minutes"]
    record_id: str
    status: str
    safe_failure_reason: str | None = None
    next_step: str | None = None


# ─── DraftEvidenceRequest ────────────────────────────────────────────────────


class DraftEvidenceRequestArguments(BaseModel):
    """Arguments for draft_evidence_request tool."""

    model_config = ConfigDict(extra="forbid")

    evidence_gap_description: str = Field(..., description="Specific evidence gap or timestamp the request targets")
    question_text: str = Field(..., description="Vietnamese question addressed to the driver")
    allowed_submission_options: list[str] = Field(default_factory=list)
    policy_deadline_hours: int | None = Field(None, ge=1, le=168)


class DraftEvidenceRequestResult(BaseModel):
    """Drafted evidence request; sending requires a separate approved step."""

    model_config = ConfigDict(extra="forbid")

    draft_id: str
    question_text: str
    allowed_submission_options: list[str]
    policy_deadline_hours: int | None
    deadline_source: Literal["published_policy", "manual_clarification"] = "manual_clarification"
    status: Literal["draft"] = "draft"
    note: str = "Send requires owner approval; deadline remains pending manual policy clarification."


# ─── API response schemas ─────────────────────────────────────────────────────


class WorkflowQuestionResponse(BaseModel):
    """Public API shape returned from GET /workflows/questions/{id}."""

    model_config = ConfigDict(extra="forbid")

    question_id: str
    question_id_stable: str
    revision: int
    case_id: str
    question_kind: QuestionKind
    purpose: QuestionPurpose
    actor_target: ActorTarget
    status: QuestionStatus
    payload: WorkflowQuestionPayload
    created_at: str
    answered_at: str | None = None
    expires_at: str | None = None


class AnswerSubmissionResponse(BaseModel):
    """Response from POST /workflows/questions/{id}/answer."""

    model_config = ConfigDict(extra="forbid")

    answer_id: str
    question_id: str
    status: QuestionStatus
    submitted_at: str
    idempotent: bool = False
    note: str = "Answer recorded. Ordinary answers do not grant action approval."


class MinutesApprovalResponse(BaseModel):
    """Response from POST /workflows/minutes/{id}/approve."""

    model_config = ConfigDict(extra="forbid")

    minutes_id: str
    revision: int
    status: MinutesStatus
    approved_by: str
    approved_at: str
    content_hash: str


class MinutesSendResponse(BaseModel):
    """Response from POST /workflows/minutes/{id}/send."""

    model_config = ConfigDict(extra="forbid")

    minutes_id: str
    outbox_event_id: str | None
    delivery_state: DeliveryState
    sent_at: str


# ─── Helpers ──────────────────────────────────────────────────────────────────


def compute_content_hash(content: Any) -> str:
    """Deterministic SHA-256 of JSON-serialized content."""
    raw = json.dumps(content, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode()).hexdigest()


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()

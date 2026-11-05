from __future__ import annotations

import base64
from datetime import datetime
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------------------
# Sentinel RAG Domain & Cockpit View Schemas
# ---------------------------------------------------------------------------
class DriverCardData(BaseModel):
    """Structured driver profile data for rich UI cockpit cards."""

    driver_id: str = Field(..., description="Unique driver ID, e.g. drv-8492-nguyen-van-a")
    full_name: str = Field(..., description="Driver full legal name")
    phone_number: str = Field(default="", description="Masked or full phone number")
    vehicle_plate: str = Field(..., description="License plate number")
    vehicle_type: str = Field(default="Green SM Car", description="Vehicle service type")
    rating: float = Field(default=4.9, ge=0.0, le=5.0, description="Average passenger rating")
    total_trips: int = Field(default=0, ge=0, description="Total completed trips")
    acceptance_rate_pct: float = Field(default=95.0, ge=0.0, le=100.0, description="Acceptance rate (AR)")
    completion_rate_pct: float = Field(default=98.0, ge=0.0, le=100.0, description="Completion rate (CR)")
    joined_date: str = Field(default="2024-01-01", description="Date joined the platform")
    operating_status: Literal["active", "suspended", "under_investigation", "offline"] = Field(
        default="active", description="Driver operational status"
    )


class DriverHistoryItem(BaseModel):
    """Single historical event / trip in driver record."""

    trip_id: str = Field(..., description="Trip or order ID")
    timestamp: str = Field(..., description="ISO 8601 timestamp of event")
    service_type: str = Field(default="Green SM Car", description="Car, Bike, Express, Delivery")
    pickup_address: str = Field(default="", description="Pickup point")
    dropoff_address: str = Field(default="", description="Dropoff point")
    status: Literal["completed", "passenger_cancelled", "driver_cancelled", "disputed"] = Field(
        ..., description="Outcome of the trip"
    )
    stall_duration_sec: int = Field(default=0, description="Observed stationary stall in seconds")
    anomaly_flag: str | None = Field(default=None, description="ERR-01 to ERR-05 code if flagged")
    fare_vnd: int = Field(default=0, description="Total fare in VND")


class PolicyCitation(BaseModel):
    """Verified policy chunk reference."""

    document_title: str = Field(..., description="Title of the policy document")
    doc_id: str = Field(..., description="Identifier of the policy chunk")
    category: str = Field(default="general", description="Policy category")
    snippet: str = Field(..., description="Relevant text excerpt")
    source_url: str = Field(default="", description="Official policy URL")


class ForensicAnalysis(BaseModel):
    """Structured AI forensic summary for fraud triage."""

    violation_code: str = Field(default="ERR-00", description="Primary violation code e.g. ERR-01, ERR-02 (DIC)")
    confidence_pct: float = Field(default=0.0, ge=0.0, le=100.0, description="Confidence score")
    recommended_action: Literal["Agree", "Disagree", "Request Evidence"] = Field(
        default="Disagree", description="Recommended action for Analyst HITL sign-off"
    )
    summary: str = Field(..., description="Concise forensic rationale")
    suggested_rationale: str = Field(default="", description="Pre-filled legal rationale text for one-click action")


class StructuredCockpitResponse(BaseModel):
    """Unified structured response contract for display in Cockpit views."""

    display_format: Literal["driver_card", "driver_history", "policy_answer", "forensic_brief", "composite"] = Field(
        ..., description="UI rendering mode for Cockpit frontend"
    )
    answer: str = Field(..., description="Direct markdown response text")
    driver_card: DriverCardData | None = Field(default=None, description="Driver profile card data")
    driver_history: list[DriverHistoryItem] = Field(default_factory=list, description="Driver trip / violation history")
    citations: list[PolicyCitation] = Field(default_factory=list, description="Verified policy citations")
    forensic: ForensicAnalysis | None = Field(
        default=None, description="Forensic recommendation and violation analysis"
    )
    tool_called: str | None = Field(default=None, description="Name of the tool executed by the agent")
    status: str = Field(default="success", description="Execution status: success, blocked, error")
    thinking_process: str | None = Field(default=None, description="Model reasoning and tool routing rationale")
    raw_tool_data: dict[str, Any] = Field(default_factory=dict, description="Raw data returned by tools")
    reasoning: str | None = Field(default=None, description="ReAct reasoning thought process")
    thought_process: list[str] = Field(default_factory=list, description="Step-by-step reasoning logs")


# ---------------------------------------------------------------------------
# Chat models (Legacy/Agent)
# ---------------------------------------------------------------------------
class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=5000, description="User message input")
    driver_id: str | None = Field(default=None, description="Optional driver context ID")
    trip_id: str | None = Field(default=None, description="Optional trip context ID")


class ChatResponse(BaseModel):
    response: str = Field(..., description="Agent response output")
    analysis: str = Field(default="", description="Internal reasoning analysis")
    data: StructuredCockpitResponse | None = Field(default=None, description="Structured UI data for Cockpit")


# ---------------------------------------------------------------------------
# System Health
# ---------------------------------------------------------------------------
class HealthResponse(BaseModel):
    status: str = "ok"
    env: str
    database: str = "connected"


# ---------------------------------------------------------------------------
# Ingest & Telemetry
# ---------------------------------------------------------------------------
class TelemetryPosition(BaseModel):
    latitude: float = Field(..., ge=-90.0, le=90.0)
    longitude: float = Field(..., ge=-180.0, le=180.0)
    accuracy_m: float | None = Field(..., ge=0.0)


class TelemetryPayload(BaseModel):
    position: TelemetryPosition | None = None
    speed_mps: float | None = Field(default=None, ge=0.0)
    bearing_deg: float | None = Field(default=None, ge=0.0, lt=360.0)
    app_state: Literal["foreground", "background", "crashed", "unknown"]
    network_state: Literal["online", "offline", "degraded", "unknown"]
    gps_state: Literal["valid", "jitter", "unavailable", "mock_reported", "unknown"]
    mock_location_reported: bool | None = None
    latency_ms: float | None = Field(default=None, ge=0.0)
    ping_latency_ms: float | None = Field(default=None, ge=0.0)
    battery_level_pct: float | None = Field(default=None, ge=0.0, le=100.0)
    distance_to_pickup_m: float | None = Field(default=None, ge=0.0)
    davi_score: float | None = Field(default=None, ge=-1.0, le=1.0)
    data_gap_s: float | None = Field(default=None, ge=0.0)


class TelemetryEventEnvelope(BaseModel):
    schema_version: Literal[1] = 1
    event_id: UUID
    event_type: Literal[
        "telemetry.observed",
        "driver.app_crashed",
        "driver.network_changed",
        "telemetry.missingness_alert",
    ]
    source: str = Field(..., min_length=1, max_length=100)
    occurred_at: datetime
    correlation_id: UUID
    causation_id: UUID | None = None
    simulation_run_id: UUID | None = None
    trip_id: UUID
    assignment_id: UUID
    driver_id: UUID
    sequence: int = Field(..., ge=0)
    payload: TelemetryPayload


class IngestResult(BaseModel):
    status: str
    event_id: UUID
    duplicate: bool = False
    detail: str | None = None


# ---------------------------------------------------------------------------
# Simulation Trigger
# ---------------------------------------------------------------------------
class SimulationTriggerRequest(BaseModel):
    analyst_id: str | None = None
    seed: int | None = None
    driver_id: str | None = None


class SimulationTriggerResponse(BaseModel):
    scenario: str
    case_id: str
    status: str


# ---------------------------------------------------------------------------
# Cases
# ---------------------------------------------------------------------------
PreliminaryJudgmentChoice = Literal["Nghi ngờ vi phạm", "Nghi oan-bất khả kháng", "Chưa đủ cơ sở"]


class PreliminaryAssessmentRequest(BaseModel):
    analyst_id: str
    judgment: PreliminaryJudgmentChoice
    note: str | None = None

    @field_validator("judgment", mode="before")
    @classmethod
    def normalize_judgment(cls, value: Any) -> Any:
        return "Nghi oan-bất khả kháng" if value == "Nghi oan/bất khả kháng" else value


class PreliminaryJudgment(PreliminaryAssessmentRequest):
    id: str
    case_id: str
    created_at: datetime


class AISuggestion(BaseModel):
    category: str | None = None
    confidence: float | None = None
    recommended_action: str | None = None


class StagedAdjudicationContext(BaseModel):
    preliminary_judgment_id: str | None = None
    preliminary_judgment: PreliminaryJudgment | None = None
    ai_suggestion: AISuggestion | None = None
    delta: Literal["match", "mismatch"] | None = None


class FraudCaseSummary(StagedAdjudicationContext):
    id: str
    trip_id: str | None = None
    assignment_id: str | None = None
    driver_id: str | None = None
    status: str
    priority: str
    priority_score: int
    category: str | None = None
    confidence: float | None = None
    opened_at: datetime | None = None
    updated_at: datetime | None = None
    assigned_analyst_id: str | None = None
    active_lease_analyst_id: str | None = None
    active_lease_expires_at: datetime | None = None
    version: int = 1
    # Rich UI and PostgreSQL fields
    driver_name: str | None = None
    vehicle_plate: str | None = None
    district: str | None = None
    stall_duration_s: int | None = None
    sla_countdown_s: int | None = None
    assigned_analyst_name: str | None = None
    dispute_status: str | None = "not_disputed"
    dispute_deadline: datetime | None = None
    active_lease_analyst_id: str | None = None


class CaseListResponse(BaseModel):
    items: list[FraudCaseSummary]
    total: int
    limit: int = 50
    offset: int = 0


class ConversationMessage(BaseModel):
    role: Literal["driver", "customer"]
    text: str
    occurred_at: datetime | None = None


class ForensicAbnormality(BaseModel):
    """Single factual abnormality observed in case telemetry, features, or incident records."""

    code: str = Field(..., description="Deterministic abnormality code e.g. stationary_stall, mock_location_reported")
    category: Literal["telemetry", "feature", "trip", "incident", "guardrail"] = Field(
        ..., description="Domain source of the observed abnormality"
    )
    metric: str = Field(..., description="Observed metric or field name")
    observed_value: Any = Field(..., description="Exact value recorded in database/telemetry")
    description: str = Field(..., description="Objective, non-judgmental description of the abnormality")


class DriverMotivationAssessment(BaseModel):
    """Evidence-bounded assessment of possible driver economic motivation."""

    economic_incentive_reward: float = Field(default=0.0, ge=0.0, allow_inf_nan=False)
    intent_profile: Literal["possible_accidental", "possible_intentional_exploit", "unclear_insufficient_data"] = (
        "unclear_insufficient_data"
    )
    natural_vietnamese_narrative: str = Field(default="Chưa đủ dữ liệu để đánh giá động cơ của tài xế.", min_length=1)


class ForensicBriefResponse(BaseModel):
    """Aggregated factual Forensic Brief summarizing exact abnormalities without judgment or fabricated data."""

    case_id: str
    trip_id: str | None = None
    assignment_id: str | None = None
    driver_id: str | None = None
    suspected_category: str | None = None
    abnormalities: list[ForensicAbnormality] = Field(default_factory=list)
    abnormality_count: int = 0
    has_abnormalities: bool = False
    summary_text: str = Field(
        ..., description="Objective summary of exact abnormalities observed in this case for Decision Rationale"
    )
    telemetry_point_count: int = 0
    stationary_duration_s: int | None = None
    davi: float | None = None
    max_gap_s: int | None = None
    telemetry_coverage: float | None = None
    mock_locations_detected: int = 0
    cancellation_actor: str | None = None
    cancellation_reason: str | None = None
    platform_incident_type: str | None = None
    active_guardrails: list[str] = Field(default_factory=list)
    motivation_assessment: DriverMotivationAssessment = Field(default_factory=DriverMotivationAssessment)


class CasePolicyClause(BaseModel):
    """Policy clause linked to a specific case's policy version or suspected category."""

    id: str
    source_ref: str = "Quy chế Hợp tác Kinh doanh GreenSM 2026"
    section_ref: str | None = None
    content: str
    category: str = "general"
    source_url: str = ""


class CasePolicyResponse(BaseModel):
    """Case-specific policy version, action matrix, and applicable policy clauses."""

    case_id: str
    suspected_category: str | None = None
    policy_version_id: str | None = None
    policy_version: str | None = None
    policy_status: str | None = None
    effective_from: str | None = None
    action_matrix: dict[str, Any] = Field(default_factory=dict)
    applicable_action_rule: dict[str, Any] | None = None
    clauses: list[CasePolicyClause] = Field(default_factory=list)
    related_policies: list[dict[str, Any]] = Field(default_factory=list)


class WorkflowDraftRequest(BaseModel):
    """Analyst-authored notes; saving does not adjudicate a case."""

    text: str = Field(max_length=20000)
    expected_version: int | None = Field(default=None, ge=0)


class WorkflowDraftResponse(BaseModel):
    text: str = ""
    version: int = Field(default=0, ge=0)
    updated_at: datetime | None = None
    updated_by: str | None = None


class CaseDetailResponse(BaseModel):
    cockpit_evidence: dict[str, Any] = Field(default_factory=dict)
    workflow_draft: WorkflowDraftResponse = Field(default_factory=WorkflowDraftResponse)
    conversation: list[ConversationMessage] = Field(default_factory=list)
    case: FraudCaseSummary
    trip: dict[str, Any] = Field(default_factory=dict)
    telemetry_samples: list[dict[str, Any]] = Field(default_factory=list)
    features: dict[str, Any] | None = None
    assessment: dict[str, Any] | None = None
    forensic_brief: ForensicBriefResponse | None = None
    case_policy: CasePolicyResponse | None = None
    route_geometry: dict[str, Any] | None = None
    candidate_routes: list[dict[str, Any]] = Field(default_factory=list)
    traffic_corroboration: dict[str, Any] | None = None
    timeline_milestones: list[dict[str, Any]] = Field(default_factory=list)
    missingness_alerts: list[dict[str, Any]] = Field(default_factory=list)
    destination: dict[str, Any] | None = None
    guardrails: dict[str, Any] | None = None
    active_lease: dict[str, Any] | None = None
    adjudication: dict[str, Any] | None = None
    preliminary_judgment: PreliminaryJudgment | None = None


# ---------------------------------------------------------------------------
# Driver Scorecard (issue #100; field-identical to webapp DriverScorecardResponse)
# ---------------------------------------------------------------------------
class DriverPastIncident(BaseModel):
    trip_id: str
    occurred_at: str
    violation_type: str
    investigation_finding: str
    action_taken: str
    status: Literal["exonerated", "penalized", "warned"]


class DriverScorecardResponse(BaseModel):
    driver_id: str
    violation_ratio_90d: float
    benchmark_violation_ratio: float
    fined_ratio: float
    repeat_offense_risk_score: int
    tenure_months: int
    total_trips: int | None = None
    total_cases: int | None = None
    past_incidents: list[DriverPastIncident] = Field(default_factory=list)


class DriverVehicleInfo(BaseModel):
    model: str | None = None
    plate: str | None = None


class WeeklyRatingTrend(BaseModel):
    week_label: str
    week_start: str
    average_rating: float | None = None
    rated_count: int = 0


class DriverProfileResponse(BaseModel):
    driver_id: str
    display_name: str | None = None
    vehicle: DriverVehicleInfo | None = None
    member_since: str | None = None
    scorecard: DriverScorecardResponse
    rating_average: float | None = None
    rated_count: int = 0
    distribution: dict[str, int] = Field(default_factory=lambda: {"5": 0, "4": 0, "3": 0, "2": 0, "1": 0})
    weekly_trend: list[WeeklyRatingTrend] = Field(default_factory=list)


class DriverFeedbackItem(BaseModel):
    id: str
    stars: int | None = None
    comment: str | None = None
    date: str | None = None
    created_at: str | None = None


class DriverFeedbackResponse(BaseModel):
    items: list[DriverFeedbackItem] = Field(default_factory=list)
    next_cursor: str | None = None
    total: int = 0


# ---------------------------------------------------------------------------
# Case Lease Claim
# ---------------------------------------------------------------------------
class ClaimCaseRequest(BaseModel):
    analyst_id: str
    lease_duration_seconds: int = Field(default=300, ge=10, le=3600)
    role: str | None = None
    force: bool = False


class ClaimCaseResponse(BaseModel):
    case_id: str
    analyst_id: str
    lease_expires_at: datetime
    status: str


class ReleaseCaseRequest(BaseModel):
    analyst_id: str
    role: str | None = None
    force: bool = False
    reason: str | None = None


class ReleaseCaseResponse(BaseModel):
    case_id: str
    analyst_id: str
    status: str
    released_at: datetime


# ---------------------------------------------------------------------------
# Case Actions
# ---------------------------------------------------------------------------
class CaseActionRequest(BaseModel):
    action_type: Literal["REQUEST_EVIDENCE"]
    analyst_id: str
    notes: str | None = None


class CaseActionResponse(BaseModel):
    case_id: str
    action_type: str
    status: str
    recorded_at: datetime
    new_case_status: str


# ---------------------------------------------------------------------------
# Case Adjudication
# ---------------------------------------------------------------------------
class AdjudicationRequest(BaseModel):
    outcome: Literal["AGREE", "DISAGREE"]
    analyst_id: str
    rationale: str = Field(
        ..., min_length=10, description="Mandatory analyst rationale (at least 10 characters per AC-P1-03)"
    )
    expected_case_version: int
    policy_version_id: str | None = None
    snapshot_hash: str | None = None
    agent_turn_id: UUID | None = None
    preliminary_judgment_id: str | None = None

    @field_validator("rationale")
    @classmethod
    def validate_rationale_length(cls, v: str) -> str:
        cleaned = v.strip()
        if len(cleaned) < 10:
            raise ValueError("Rationale requires at least 10 non-whitespace characters")
        return cleaned


class AdjudicationResponse(StagedAdjudicationContext):
    case_id: str
    outcome: str
    status: str
    sanction_applied: str | None = None
    adjudicated_at: datetime
    new_version: int


# ---------------------------------------------------------------------------
# Policy RAG Chat & Attachments
# ---------------------------------------------------------------------------
class ChatAttachment(BaseModel):
    name: str = Field(..., min_length=1)
    media_type: Literal["image/png", "image/jpeg", "image/webp"]
    data_base64: str = Field(..., min_length=1)

    @field_validator("data_base64")
    @classmethod
    def validate_data(cls, v: str) -> str:
        try:
            raw = base64.b64decode(v, validate=True)
        except Exception as e:
            raise ValueError("Invalid base64 encoding") from e
        if len(raw) > 4 * 1024 * 1024:
            raise ValueError("Attachment decoded size exceeds 4 MB limit")
        return v


class PolicyChatRequest(BaseModel):
    query: str = Field(..., min_length=1)
    case_id: UUID
    turn_id: UUID = Field(default_factory=uuid4)
    policy_version_id: str | None = None
    event_schema_version: Literal["1.0", "1.1"] | None = None
    reset_context: bool = Field(
        default=False,
        description="If true, execute turn without earlier conversational dialogue in model input while retaining case facts, evidence, and audit logs.",
    )
    attachments: list[ChatAttachment] | None = Field(
        default=None,
        max_length=3,
        description="Optional image attachments (max 3, each <= 4 MB decoded)",
    )


class AgentContextBreakdown(BaseModel):
    system: int = 0
    dossier: int = 0
    history: int = 0
    tool_results: int = 0
    query: int = 0


class AgentContextResponse(BaseModel):
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    context_window: int
    breakdown: AgentContextBreakdown
    turn_count: int


class AgentContextClearResponse(BaseModel):
    deleted_turns: int
    deleted_messages: int


# ---------------------------------------------------------------------------
# Driver Dispute & Autonomous Exoneration (POC v2)
# ---------------------------------------------------------------------------
class DriverDisputeContextResponse(BaseModel):
    case_id: str
    driver_id: str
    driver_name: str
    trip_id: str
    violation_code: str
    violation_title: str
    alleged_time: datetime | str | None = None
    alleged_location: str | dict[str, Any] | None = None
    dispute_deadline: datetime | str | None = None
    dispute_status: str = "not_disputed"
    allowed_claim_types: list[str] = Field(
        default_factory=lambda: ["traffic_gridlock", "gps_issue", "passenger_wait", "other"]
    )


class DriverCaseSessionItem(BaseModel):
    case_id: str
    case_code: str = ""
    driver_id: str = ""
    driver_name: str = ""
    violation_code: str
    violation_title: str
    dispute_status: str
    status: str | None = None
    dispute_deadline: datetime | str | None = None
    created_at: datetime | str
    alleged_time: datetime | str | None = None
    alleged_location: str | dict[str, Any] | None = None
    description: str | None = None
    trip_id: str | None = None
    vehicle_plate: str | None = None
    pickup_address: str | None = None
    dropoff_address: str | None = None
    source: str = "system_prediction"
    has_unread: bool = False


class DriverCaseListResponse(BaseModel):
    items: list[DriverCaseSessionItem]
    total: int


class DriverChatRequest(BaseModel):
    case_id: str = ""
    driver_id: str = ""
    message: str = Field(..., min_length=1)
    claim_type: str | None = None
    turn_id: str = Field(default_factory=lambda: str(uuid4()))
    event_schema_version: Literal["1.0", "1.1"] | None = None
    # Explicit, authenticated admission is the only autonomous disposition.
    admits_fraud: bool = False
    locale: Literal["vi", "en"] | str = "vi"

    @field_validator("message")
    @classmethod
    def validate_message_not_blank(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Message cannot be empty or whitespace only")
        return v


class DriverChatResponse(BaseModel):
    case_id: str
    driver_id: str
    reply: str
    dispute_status: str
    is_auto_dismissed: bool = False
    exoneration_receipt: dict[str, Any] | None = None
    needs_analyst_review: bool = False
    sanction_status: str = "pending_policy"
    sanction_action: str | None = None
    blocks: list[dict[str, Any]] = Field(default_factory=list)
    # R1: optional flag so callers can tell the deterministic compliance
    # template was shown instead of a real agent reply. Defaults to False to
    # stay backward compatible with existing callers/schema consumers.
    is_agent_fallback: bool = False


class DriverlessChatRequest(BaseModel):
    """Case-less GSupport chat turn (Issue #482): no case_id bound yet."""

    message: str = Field(..., min_length=1)
    turn_id: str = Field(default_factory=lambda: str(uuid4()))
    locale: Literal["vi", "en"] | str = "vi"

    @field_validator("message")
    @classmethod
    def validate_message_not_blank(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Message cannot be empty or whitespace only")
        return v


class ConfirmationRequest(BaseModel):
    action: Literal["acknowledge", "submit_statement"]
    draft_hash: str | None = ""


class AcknowledgeRequest(BaseModel):
    confirmation_token: str = ""


class StatementSubmitRequest(BaseModel):
    confirmation_token: str = ""
    reason_summary: str = Field(..., min_length=1)
    evidence: list[dict[str, Any]] | None = None

    @field_validator("reason_summary")
    @classmethod
    def validate_reason_not_blank(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("reason_summary cannot be empty or whitespace only")
        return v.strip()


class AnalystDelegateInquiryRequest(BaseModel):
    case_id: str = ""
    analyst_id: str = ""
    instruction: str = Field(..., min_length=1)
    deadline_hours: int = 48
    turn_id: str | None = None


class DisputeDossierResponse(BaseModel):
    case_id: str
    driver_id: str
    driver_name: str
    dispute_status: str
    driver_statement: str | None = None
    claim_type: str | None = None
    traffic_corroboration: dict[str, Any] = Field(default_factory=dict)
    precedent_score: float = 0.0
    recommended_action: str = "Request Evidence"
    transcript: list[dict[str, Any]] = Field(default_factory=list)
    matched_precedent: PrecedentSimilarityMatch | None = None
    matching_factors: list[str] = Field(default_factory=list)
    workflow_trace: WorkflowTrace | None = None


# ---------------------------------------------------------------------------
# Precedent Workflow Mining & Jev Similarity Engine (POC v2 Extension)
# ---------------------------------------------------------------------------
class WorkflowToolCall(BaseModel):
    tool_name: str
    input_summary: str | None = None
    output_summary: str | None = None
    executed_at: str | None = None
    status: str = "success"
    source_ref: str | None = None


class WorkflowHumanAction(BaseModel):
    actor_id: str | None = None
    actor_role: str  # 'driver', 'analyst', 'senior_analyst'
    action_type: str  # 'dispute_statement', 'delegate_inquiry', 'driver_response', 'decision_submit'
    summary: str
    timestamp: str | None = None
    source_ref: str | None = None


class WorkflowPolicyCitation(BaseModel):
    policy_version_id: str | None = None
    policy_code: str
    clause: str
    rationale: str
    relevance_score: float = 1.0


class WorkflowDecision(BaseModel):
    verdict: str  # 'exonerated', 'warning', 'penalty_applied', 'temporary_suspension'
    penalty_amount: int = 0
    rationale: str
    decided_by: str
    decided_at: str
    adjudication_id: str | None = None
    evidence_snapshot_id: str | None = None
    policy_version_id: str | None = None
    request_hash: str | None = None
    explicit_human_approval: bool = False


class WorkflowTimelineEvent(BaseModel):
    """Single trip lifecycle milestone backing the workflow ribbon (issue #100)."""

    event_type: str = Field(..., description="trip_events.event_type e.g. dispatched, driver_arriving")
    occurred_at: str = Field(..., description="ISO 8601 timestamp of the event")
    label: str = Field(default="", description="Short display label for the timeline ribbon")


class WorkflowTrace(BaseModel):
    ai_result: dict[str, Any] | None = None
    schema_version: str = "2.0"
    agent_tools_called: list[WorkflowToolCall] = Field(default_factory=list)
    human_actions_performed: list[WorkflowHumanAction] = Field(default_factory=list)
    driver_response_summary: str = ""
    related_policies: list[WorkflowPolicyCitation] = Field(default_factory=list)
    final_decision: WorkflowDecision | None = None
    trace_id: str | None = None
    agent_run_id: str | None = None
    source_refs: list[str] = Field(default_factory=list)
    timeline: list[WorkflowTimelineEvent] = Field(
        default_factory=list,
        description="Trip lifecycle milestones from app.trip_events; empty when unavailable",
    )


class PrecedentProvenance(BaseModel):
    organization_id: str | None = None
    assignment_id: str | None = None
    case_id: str | None = None
    conversation_session_id: str | None = None
    driver_submission_id: str | None = None
    conversation_state: Literal["linked", "not_available", "legacy_unknown"] = "legacy_unknown"
    evidence_snapshot_id: str | None = None
    policy_version_id: str | None = None
    adjudication_id: str | None = None
    published_by: str | None = None
    published_at: str | None = None
    trace_schema_version: str = "1.0"
    source_kind: Literal["finalized_case", "legacy_fixture", "legacy_appeal"] = "legacy_fixture"
    read_only: bool = True
    eligible_for_reuse: bool = False


class PrecedentWorkflowItem(BaseModel):
    id: str
    case_id: str | None = None
    violation_code: str
    claim_type: str
    district: str | None = None
    title: str
    driver_statement_summary: str
    workflow_trace: WorkflowTrace
    verdict: str
    confidence_score: float = 1.0
    created_at: str | None = None
    provenance: PrecedentProvenance = Field(default_factory=PrecedentProvenance)


class PrecedentSimilarityMatch(BaseModel):
    precedent_id: str
    precedent_case_id: str | None = None
    title: str = ""
    similarity_score: float  # [0.0, 1.0]
    matching_factors: list[str] = Field(default_factory=list)
    recommended_procedure: list[str] = Field(default_factory=list)
    precedent_verdict: str = ""
    confidence_rationale: str = ""
    model_used: str = "jev"  # 'jev' or 'heuristic_fallback'
    score_semantics: str = "uncalibrated_similarity"
    provenance: PrecedentProvenance = Field(default_factory=PrecedentProvenance)
    precedent_workflow: WorkflowTrace | None = None


class PrecedentMatchRequest(BaseModel):
    case_id: str
    claim_type: str | None = None
    driver_statement: str | None = None
    violation_code: str | None = None
    telemetry_summary: dict[str, Any] | None = None


class PrecedentMatchResponse(BaseModel):
    case_id: str
    has_match: bool
    top_match: PrecedentSimilarityMatch | None = None
    all_candidates: list[PrecedentSimilarityMatch] = Field(default_factory=list)


class UserAccountSettings(BaseModel):
    id: str
    display_name: str
    email: str | None = None
    roles: list[str] = Field(default_factory=list)
    primary_role: str = "fraud_analyst"
    organization_id: str
    driver_id: str | None = None


class UpdateAccountSettingsRequest(BaseModel):
    display_name: str = Field(..., min_length=1, max_length=100)


class AccountUserItem(BaseModel):
    id: str
    display_name: str
    external_subject: str | None = None
    roles: list[str] = Field(default_factory=list)
    status: str = "active"


class UpdateUserRoleRequest(BaseModel):
    role: Literal["fraud_analyst", "analyst", "driver", "admin"]


class AnalystDecisionMetrics(BaseModel):
    today_decisions_count: int = 0
    thirty_day_decisions_count: int = 0
    average_mttr_seconds: float | None = None
    model_agreement_pct: float | None = None
    quality_overturn_pct: float | None = None


class AnalystGovernanceLimits(BaseModel):
    dismiss_authority: str = "Unrestricted"
    warning_authority: str = "Authorized"
    direct_fine_limit_vnd: int = 2000000
    suspension_authority: str = "24h / 48h Lockout"
    role: str = "fraud_analyst"


class ActiveReviewLeaseSummary(BaseModel):
    case_id: str
    case_code: str
    severity: str
    driver_name: str | None = None
    vehicle_plate: str | None = None
    expires_at: datetime
    remaining_seconds: int


class AnalystAuditLedgerItem(StagedAdjudicationContext):
    id: str
    case_id: str
    case_code: str
    timestamp: datetime
    actor_id: str
    actor_name: str
    actor_type: Literal["analyst", "system", "driver"] = "analyst"
    action: str
    verdict: str
    subject_entity: str
    triggered_violation: str
    sanction: str | None = None
    rationale: str
    snapshot_version: int = 1
    request_hash: str | None = None


class AnalystAuditProfileResponse(BaseModel):
    analyst_id: str
    display_name: str
    roles: list[str] = Field(default_factory=list)
    organization_id: str
    metrics: AnalystDecisionMetrics
    governance_limits: AnalystGovernanceLimits
    active_lease: ActiveReviewLeaseSummary | None = None
    ledger: list[AnalystAuditLedgerItem] = Field(default_factory=list)
    total_ledger_count: int = 0


class AnalyticsQueueMetrics(BaseModel):
    total_cases: int = 0
    active_backlog: int = 0
    pending_driver_confirmation: int = 0
    claimed_cases: int = 0
    available_unclaimed: int = 0
    priority_distribution: dict[str, int] = Field(default_factory=dict)


class AnalyticsDispositionMetrics(BaseModel):
    driver_confirmed_resolutions: int = 0
    analyst_adjudications_total: int = 0
    analyst_decisions_breakdown: dict[str, int] = Field(default_factory=dict)
    auto_dismissed_count: int = 0


class AnalyticsPerformanceMetrics(BaseModel):
    average_mttr_seconds: float | None = None
    hitl_enforcement_ratio_pct: float | None = None
    reviewer_concordance_pct: float | None = None


class AnalyticsSystemHealth(BaseModel):
    database_healthy: bool = True
    worker_status: str = "active"
    environment: str = "production"


class AnalyticsMetricsResponse(BaseModel):
    scope: str = "organization"
    organization_id: str
    window_days: int | None = 30
    generated_at: datetime
    queue: AnalyticsQueueMetrics
    dispositions: AnalyticsDispositionMetrics
    categories: dict[str, int] = Field(default_factory=dict)
    performance: AnalyticsPerformanceMetrics
    health: AnalyticsSystemHealth


class DriverTripRatingItem(BaseModel):
    stars: int | None = Field(default=None, description="Rating stars (1-5) or null if unrated")
    comment: str | None = Field(default=None, description="Customer review comment")
    locale: str | None = Field(default=None, description="Review locale (e.g. vi)")
    created_at: str | None = Field(default=None, description="Rating timestamp")


class DriverTripItem(BaseModel):
    trip_id: str = Field(..., description="Unique trip identifier")
    driver_id: str | None = None
    organization_id: str | None = None
    pickup_label: str = Field(..., description="Pickup location label")
    pickup_lat: float | None = None
    pickup_lng: float | None = None
    dropoff_label: str = Field(..., description="Dropoff destination label")
    dropoff_lat: float | None = None
    dropoff_lng: float | None = None
    started_at: str = Field(..., description="Trip start timestamp")
    ended_at: str | None = Field(default=None, description="Trip end timestamp")
    distance_km: float = Field(default=0.0, description="Trip distance in kilometers")
    duration_min: float = Field(default=0.0, description="Trip duration in minutes")
    fare_vnd: int = Field(default=0, description="Fare amount in VND")
    payment_method: str = Field(default="wallet", description="Payment method: wallet, cash, credit_card")
    payment_method_synthetic: bool = Field(default=True, description="Flag indicating synthetic payment method")
    rating: DriverTripRatingItem | None = Field(default=None, description="Customer rating or null")
    status: str = Field(default="completed", description="Trip status")
    has_case: bool = Field(default=False, description="Whether trip is flagged and linked to a dispute case")
    case_id: str | None = Field(default=None, description="Linked case ID if flagged (navigation only)")


class DriverTripCounts(BaseModel):
    all: int = Field(default=0, description="Trips matching driver/org/month, any status")
    completed: int = Field(default=0, description="Completed trips with no linked case")
    flagged: int = Field(default=0, description="Trips with a linked case or status=flagged")


class DriverTripsResponse(BaseModel):
    trips: list[DriverTripItem] = Field(default_factory=list, description="Paginated list of trips")
    total: int = Field(
        default=0,
        description="Total trips matching driver/status/month filter, independent of cursor",
    )
    next_cursor: str | None = Field(default=None, description="Keyset pagination cursor for next page")
    counts: DriverTripCounts = Field(
        default_factory=DriverTripCounts,
        description="Per-status counts (all/completed/flagged) scoped by driver+month, ignoring `status`; source for tab badges",
    )


class DriverTripsSummaryResponse(BaseModel):
    month: str | None = Field(default=None, description="Month filter (YYYY-MM) or null for all-time")
    trip_count: int = Field(
        default=0,
        description="Total trips in the month, all statuses (not completed-only)",
    )
    total_fare_vnd: int = Field(default=0, description="Sum of fares in VND")
    total_distance_km: float = Field(default=0.0, description="Sum of distance in km")
    avg_rating: float | None = Field(default=None, description="Average rating score if rated")


DisputeDossierResponse.model_rebuild()

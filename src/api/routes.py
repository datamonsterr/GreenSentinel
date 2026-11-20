import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from src.agents.graph import agent
from src.api.auth import (
    Principal,
    require_analyst_identity,
    require_driver_identity,
    require_principal,
    require_role,
    test_auth_enabled,
)
from src.config import Settings, get_settings
from src.models.schemas import (
    AccountUserItem,
    AcknowledgeRequest,
    AdjudicationRequest,
    AdjudicationResponse,
    AgentContextClearResponse,
    AgentContextResponse,
    AnalystAuditProfileResponse,
    AnalystDelegateInquiryRequest,
    AnalyticsMetricsResponse,
    CaseActionRequest,
    CaseActionResponse,
    CaseDetailResponse,
    CaseListResponse,
    CasePolicyResponse,
    ChatRequest,
    ChatResponse,
    ClaimCaseRequest,
    ClaimCaseResponse,
    ConfirmationRequest,
    DisputeDossierResponse,
    DriverCaseListResponse,
    DriverChatRequest,
    DriverChatResponse,
    DriverDisputeContextResponse,
    DriverFeedbackResponse,
    DriverlessChatRequest,
    DriverProfileResponse,
    DriverScorecardResponse,
    DriverTripItem,
    DriverTripsResponse,
    DriverTripsSummaryResponse,
    ForensicBriefResponse,
    HealthResponse,
    IngestResult,
    PolicyChatRequest,
    PrecedentMatchRequest,
    PrecedentMatchResponse,
    PrecedentWorkflowItem,
    PreliminaryAssessmentRequest,
    PreliminaryJudgment,
    ReleaseCaseRequest,
    ReleaseCaseResponse,
    SimulationTriggerRequest,
    SimulationTriggerResponse,
    StatementSubmitRequest,
    TelemetryEventEnvelope,
    UpdateAccountSettingsRequest,
    UpdateUserRoleRequest,
    UserAccountSettings,
    WorkflowDraftRequest,
    WorkflowDraftResponse,
    WorkflowTrace,
)
from src.services import case_workflow
from src.services.access_control import require_case_scope
from src.services.case_service import CaseService, get_case_service
from src.services.driver_dispute_service import DriverDisputeService, get_driver_dispute_service
from src.services.jev_precedent_service import JevPrecedentService, get_jev_precedent_service
from src.services.observability_metrics import get_observability_summary
from src.services.org_bootstrap import (
    DEFAULT_SEED,
    DEFAULT_TEMPLATE_VERSION,
    BootstrapError,
    DatabaseUnavailableError,
    NotFoundError,
    OrgMismatchError,
    bootstrap_org_population,
    get_bootstrap_status,
    link_driver_principal,
)
from src.services.precedent_repository import PrecedentPersistenceError
from src.services.role_routing import primary_role_for, resolve_initial_route

router = APIRouter()

# Read-only case access (list/detail/evidence/workflow). Writes stay analyst-only (ADR-031).
CASE_READ_ROLES = ("analyst", "senior_analyst", "admin", *sorted(case_workflow.WORKFLOW_ROLES))


@router.get("/health", response_model=HealthResponse)
async def api_health(
    case_service: CaseService = Depends(get_case_service),
) -> HealthResponse:
    settings = get_settings()
    db_status = await case_service.check_database_health()
    return HealthResponse(status="ok", env=settings.app_env, database=db_status)


@router.get("/observability/summary")
async def observability_summary(
    principal: Principal | None = Depends(require_principal),
) -> dict[str, Any]:
    require_role(principal, "analyst", "senior_analyst", "admin")
    return get_observability_summary()


# Ingest
@router.post("/telemetry/ingest", response_model=IngestResult)
async def ingest_telemetry(
    envelope: TelemetryEventEnvelope,
    case_service: CaseService = Depends(get_case_service),
    principal: Principal | None = Depends(require_principal),
) -> IngestResult:
    require_role(principal, "demo_operator", "admin")
    return await case_service.ingest_telemetry(envelope)


# Simulations
@router.post("/simulations/{scenario}", response_model=SimulationTriggerResponse)
async def trigger_simulation(
    scenario: str,
    req: SimulationTriggerRequest | None = None,
    case_service: CaseService = Depends(get_case_service),
    principal: Principal | None = Depends(require_principal),
) -> SimulationTriggerResponse:
    require_role(principal, "demo_operator", "admin")
    if principal and req and req.analyst_id:
        require_analyst_identity(principal, req.analyst_id)
    analyst_id = principal.id if principal else (req.analyst_id if req else None)
    seed = req.seed if req else None
    driver_id = req.driver_id if req else None
    return await case_service.trigger_simulation(scenario, analyst_id=analyst_id, seed=seed, driver_id=driver_id)


@router.get("/me")
async def current_principal(
    principal: Principal | None = Depends(require_principal),
    case_service: CaseService = Depends(get_case_service),
) -> dict:
    if principal is None:
        settings = get_settings()
        if test_auth_enabled(settings):
            return {
                "id": "00000000-0000-0000-0000-000000000001",  # S4-RETIRE-allow: test-auth-only fixture
                "display_name": "Lê Minh Tuấn",  # S4-RETIRE-allow: test-auth-only fixture
                "roles": ["fraud_analyst", "analyst", "senior_analyst"],
                "primary_role": "fraud_analyst",
                "organization_id": "018f2f4e-0000-7000-8000-000000000001",
                "driver_id": None,
            }
        raise HTTPException(status_code=401, detail="Authentication required")
    return {
        "id": principal.id,
        "display_name": case_service.get_principal_display_name(principal.id),
        "roles": sorted(principal.roles),
        "organization_id": principal.organization_id,
        "driver_id": principal.driver_id,
    }


@router.get("/account/settings", response_model=UserAccountSettings)
async def get_account_settings(
    principal: Principal | None = Depends(require_principal),
    case_service: CaseService = Depends(get_case_service),
) -> UserAccountSettings:
    if principal is None:
        settings = get_settings()
        if test_auth_enabled(settings):
            return UserAccountSettings(
                id="00000000-0000-0000-0000-000000000001",  # S4-RETIRE-allow: test-auth-only fixture
                display_name="Lê Minh Tuấn",  # S4-RETIRE-allow: test-auth-only fixture
                roles=["fraud_analyst", "analyst", "senior_analyst"],
                primary_role="fraud_analyst",
                organization_id="018f2f4e-0000-7000-8000-000000000001",
            )
        raise HTTPException(status_code=401, detail="Authentication required")

    canonical_roles = {"admin", "analyst", "driver", *case_workflow.WORKFLOW_ROLES}
    normalized_roles = set()
    for r in principal.roles:
        if r in {"analyst", "fraud_analyst"}:
            normalized_roles.add("analyst")
        elif r in canonical_roles:
            normalized_roles.add(r)
    roles_list = sorted(normalized_roles)
    primary_role = "analyst"
    if "admin" in principal.roles:
        primary_role = "admin"
    elif "driver" in principal.roles and not (principal.roles & {"fraud_analyst", "analyst", "admin"}):
        primary_role = "driver"
    elif "fraud_analyst" in principal.roles or "analyst" in principal.roles:
        primary_role = "analyst"

    display_name = case_service.get_principal_display_name(principal.id) or f"User {principal.id[:8]}"
    return UserAccountSettings(
        id=principal.id,
        display_name=display_name,
        roles=roles_list,
        primary_role=primary_role,
        organization_id=principal.organization_id,
        driver_id=principal.driver_id,
    )


@router.patch("/account/settings", response_model=UserAccountSettings)
async def update_account_settings(
    req: UpdateAccountSettingsRequest,
    principal: Principal | None = Depends(require_principal),
    case_service: CaseService = Depends(get_case_service),
) -> UserAccountSettings:
    if principal is None:
        settings = get_settings()
        if test_auth_enabled(settings):
            return UserAccountSettings(
                id="00000000-0000-0000-0000-000000000001",  # S4-RETIRE-allow: test-auth-only fixture
                display_name=req.display_name,
                roles=["fraud_analyst", "analyst", "senior_analyst"],
                primary_role="fraud_analyst",
                organization_id="018f2f4e-0000-7000-8000-000000000001",
            )
        raise HTTPException(status_code=401, detail="Authentication required")

    case_service.set_principal_display_name(principal.id, req.display_name)
    return await get_account_settings(principal, case_service)


@router.get("/account/route")
async def get_account_route(
    principal: Principal | None = Depends(require_principal),
) -> dict[str, Any]:
    """Canonical initial route (S4-ENTRY #296, ADR-025). Server-verified."""
    if principal is None:
        settings = get_settings()
        if test_auth_enabled(settings):
            return {
                "route": "/workspace",
                "primary_role": "analyst",
                "organization_id": "018f2f4e-0000-7000-8000-000000000001",
            }
        raise HTTPException(status_code=401, detail="Authentication required")
    roles = set(principal.roles)
    route = resolve_initial_route(roles, has_org=bool(principal.organization_id))
    return {
        "route": route,
        "primary_role": primary_role_for(roles),
        "organization_id": principal.organization_id,
    }


@router.get("/account/users", response_model=list[AccountUserItem])
async def list_account_users(
    principal: Principal | None = Depends(require_principal),
    case_service: CaseService = Depends(get_case_service),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[AccountUserItem]:
    require_role(principal, "admin")
    principals = case_service.list_principals(organization_id=principal.organization_id if principal else None)
    page = principals[offset : offset + limit]
    return [
        AccountUserItem(
            id=p["id"],
            display_name=p["display_name"],
            external_subject=p.get("external_subject"),
            roles=p.get("roles", ["fraud_analyst"]),
            status=p.get("status", "active"),
        )
        for p in page
    ]


@router.patch("/account/users/{user_id}/role", response_model=AccountUserItem)
async def update_user_role(
    user_id: str,
    req: UpdateUserRoleRequest,
    principal: Principal | None = Depends(require_principal),
    case_service: CaseService = Depends(get_case_service),
) -> AccountUserItem:
    require_role(principal, "admin")
    if principal and (user_id == principal.id or req.role in {"admin"}):
        raise HTTPException(403, "Privileged grants require an independent administrator")
    # Last-Admin guard (S4-ENTRY #296): refuse demoting the final admin in org.
    if req.role != "admin":
        roster = case_service.list_principals(organization_id=principal.organization_id if principal else None)
        admins = [p for p in roster if "admin" in set(p.get("roles") or [])]
        target_is_admin = any(p["id"] == user_id and "admin" in set(p.get("roles") or []) for p in roster)
        if target_is_admin and len(admins) <= 1:
            raise HTTPException(403, "Cannot demote the last admin in the organization")
    case_service.update_principal_role(
        user_id, req.role, organization_id=principal.organization_id if principal else None
    )
    display_name = case_service.get_principal_display_name(user_id) or f"User {user_id[:8]}"
    return AccountUserItem(
        id=user_id,
        display_name=display_name,
        roles=[req.role],
        status="active",
    )


# Analyst Profile, Metrics & Audit
@router.get("/analyst/audit", response_model=AnalystAuditProfileResponse)
async def get_analyst_audit_profile(
    search: str | None = Query(default=None),
    verdict: str | None = Query(default=None),
    from_date: datetime | None = Query(default=None),
    to_date: datetime | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    principal: Principal | None = Depends(require_principal),
    case_service: CaseService = Depends(get_case_service),
) -> AnalystAuditProfileResponse:
    if not principal:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )
    require_role(principal, "analyst", "senior_analyst", "admin")
    return await case_service.get_analyst_audit_profile(
        analyst_id=principal.id,
        organization_id=principal.organization_id,
        search=search,
        verdict=verdict,
        from_date=from_date,
        to_date=to_date,
        limit=limit,
        offset=offset,
    )


# Analytics System & Operational Metrics
@router.get("/analytics/metrics", response_model=AnalyticsMetricsResponse)
async def get_analytics_metrics(
    window_days: int | None = Query(default=30, ge=1, le=365),
    principal: Principal | None = Depends(require_principal),
    case_service: CaseService = Depends(get_case_service),
) -> AnalyticsMetricsResponse:
    if not principal:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )
    require_role(principal, "analyst", "admin")
    return await case_service.get_analytics_metrics(
        organization_id=principal.organization_id,
        window_days=window_days,
    )


# Cases
@router.get("/cases", response_model=CaseListResponse)
async def list_cases(
    status: str | None = Query(default=None),
    priority: str | None = Query(default=None),
    search: str | None = Query(default=None, max_length=100),
    availability: str = Query(default="available", pattern="^(available|mine|all)$"),
    awaiting: str | None = Query(default=None, pattern="^me$"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    case_service: CaseService = Depends(get_case_service),
    principal: Principal | None = Depends(require_principal),
) -> CaseListResponse:
    require_role(principal, *CASE_READ_ROLES)
    wf_status = case_workflow.awaiting_status(principal.roles) if principal else None
    if awaiting == "me":
        if wf_status is None:
            raise HTTPException(status_code=400, detail="awaiting=me requires a workflow role")
        status = wf_status
    if wf_status is not None:
        availability = "all"  # workflow roles never claim; leases are irrelevant
    return await case_service.list_cases(
        status=status,
        priority=priority,
        search=search,
        availability=availability,
        analyst_id=principal.id if principal else None,
        limit=limit,
        offset=offset,
        organization_id=principal.organization_id if principal else None,
    )


@router.get("/cases/history", response_model=CaseListResponse)
async def list_case_history(
    status: str | None = Query(default=None),
    search: str | None = Query(default=None, max_length=100),
    decision: str | None = Query(default=None),
    analyst_id: str | None = Query(default=None),
    start_date: datetime | None = Query(default=None),
    end_date: datetime | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    case_service: CaseService = Depends(get_case_service),
    principal: Principal | None = Depends(require_principal),
) -> CaseListResponse:
    require_role(principal, *CASE_READ_ROLES, "driver")
    driver_id = (
        principal.driver_id if principal and "driver" in principal.roles and "analyst" not in principal.roles else None
    )
    return await case_service.list_case_history(
        status=status,
        search=search,
        decision=decision,
        analyst_id=analyst_id,
        start_date=start_date,
        end_date=end_date,
        limit=limit,
        offset=offset,
        organization_id=principal.organization_id if principal else None,
        driver_id=driver_id,
    )


@router.get("/cases/{id}", response_model=CaseDetailResponse)
async def get_case_detail(
    id: str,
    case_service: CaseService = Depends(get_case_service),
    principal: Principal | None = Depends(require_principal),
) -> CaseDetailResponse:
    require_role(principal, *CASE_READ_ROLES)
    return await case_service.get_case_detail(id, organization_id=principal.organization_id if principal else None)


@router.get("/cases/{id}/forensic-brief", response_model=ForensicBriefResponse)
async def get_case_forensic_brief(
    id: str,
    case_service: CaseService = Depends(get_case_service),
    principal: Principal | None = Depends(require_principal),
) -> ForensicBriefResponse:
    require_role(principal, *CASE_READ_ROLES)
    return await case_service.get_forensic_brief(id, organization_id=principal.organization_id if principal else None)


@router.get("/drivers/{driver_id}/scorecard", response_model=DriverScorecardResponse)
async def get_driver_scorecard_route(
    driver_id: str,
    case_service: CaseService = Depends(get_case_service),
    principal: Principal | None = Depends(require_principal),
) -> DriverScorecardResponse:
    """Live 90-day driver scorecard replacing the retired hash mock (issue #100)."""
    from src.services.driver_service import get_driver_scorecard

    require_role(principal, *CASE_READ_ROLES)
    return await get_driver_scorecard(
        driver_id,
        organization_id=principal.organization_id if principal else None,
        case_service=case_service,
    )


@router.get("/cases/{id}/driver-scorecard", response_model=DriverScorecardResponse)
async def get_case_driver_scorecard_route(
    id: str,
    case_service: CaseService = Depends(get_case_service),
    principal: Principal | None = Depends(require_principal),
) -> DriverScorecardResponse:
    """Case alias resolving the case driver before returning the live scorecard."""
    from src.services.driver_service import get_case_driver_scorecard

    require_role(principal, *CASE_READ_ROLES)
    if principal:
        require_case_scope(case_service, id, principal.organization_id)
    return await get_case_driver_scorecard(
        id,
        organization_id=principal.organization_id if principal else None,
        case_service=case_service,
    )


@router.get("/cases/{id}/policy", response_model=CasePolicyResponse)
async def get_case_policy(
    id: str,
    query: str | None = Query(default=None),
    case_service: CaseService = Depends(get_case_service),
    principal: Principal | None = Depends(require_principal),
) -> CasePolicyResponse:
    require_role(principal, *CASE_READ_ROLES)
    return await case_service.get_case_policy(
        id,
        query=query,
        organization_id=principal.organization_id if principal else None,
    )


@router.post("/cases/{id}/claim", response_model=ClaimCaseResponse)
async def claim_case(
    id: str,
    req: ClaimCaseRequest,
    case_service: CaseService = Depends(get_case_service),
    principal: Principal | None = Depends(require_principal),
) -> ClaimCaseResponse:
    require_role(principal, "analyst", "senior_analyst", "admin")
    require_analyst_identity(principal, req.analyst_id)
    if principal:
        require_case_scope(case_service, id, principal.organization_id)
        if req.role and req.role not in principal.roles:
            raise HTTPException(403, "Requested role is not assigned")
        req = req.model_copy(update={"role": "senior_analyst" if "senior_analyst" in principal.roles else "analyst"})
    return await case_service.claim_case_lease(
        id, req, organization_id=principal.organization_id if principal else None
    )


@router.post("/cases/{id}/release", response_model=ReleaseCaseResponse)
async def release_case(
    id: str,
    req: ReleaseCaseRequest,
    case_service: CaseService = Depends(get_case_service),
    principal: Principal | None = Depends(require_principal),
) -> ReleaseCaseResponse:
    require_role(principal, "analyst", "senior_analyst", "admin")
    require_analyst_identity(principal, req.analyst_id)
    if principal:
        require_case_scope(case_service, id, principal.organization_id)
        if req.role and req.role not in principal.roles:
            raise HTTPException(403, "Requested role is not assigned")
        req = req.model_copy(update={"role": "senior_analyst" if "senior_analyst" in principal.roles else "analyst"})
    return await case_service.release_case_lease(
        id, req, organization_id=principal.organization_id if principal else None
    )


@router.post("/cases/{id}/actions", response_model=CaseActionResponse)
async def record_case_action(
    id: str,
    req: CaseActionRequest,
    case_service: CaseService = Depends(get_case_service),
    principal: Principal | None = Depends(require_principal),
) -> CaseActionResponse:
    require_role(principal, "analyst", "senior_analyst", "admin")
    require_analyst_identity(principal, req.analyst_id)
    if principal:
        require_case_scope(case_service, id, principal.organization_id)
    return await case_service.record_case_action(
        id, req, organization_id=principal.organization_id if principal else None
    )


@router.post("/cases/{id}/preliminary-assessment", response_model=PreliminaryJudgment)
async def record_preliminary_assessment(
    id: str,
    req: PreliminaryAssessmentRequest,
    case_service: CaseService = Depends(get_case_service),
    principal: Principal | None = Depends(require_principal),
) -> PreliminaryJudgment:
    require_role(principal, "analyst", "senior_analyst", "admin")
    require_analyst_identity(principal, req.analyst_id)
    if principal:
        require_case_scope(case_service, id, principal.organization_id)
    return await case_service.record_preliminary_assessment(
        id, req, organization_id=principal.organization_id if principal else None
    )


@router.post("/cases/{id}/adjudicate", response_model=AdjudicationResponse)
async def adjudicate_case(
    id: str,
    req: AdjudicationRequest,
    background_tasks: BackgroundTasks,
    case_service: CaseService = Depends(get_case_service),
    principal: Principal | None = Depends(require_principal),
) -> AdjudicationResponse:
    require_role(principal, "analyst", "senior_analyst", "admin")
    require_analyst_identity(principal, req.analyst_id)
    if principal:
        require_case_scope(case_service, id, principal.organization_id)
    result = await case_service.adjudicate_case(
        id, req, organization_id=principal.organization_id if principal else None
    )

    from src.agents.graph import get_system_prompt_version
    from src.services.agent_tracing import make_trace_identity, record_decision_trace

    agent_run_id = str(req.agent_turn_id) if req.agent_turn_id else str(uuid4())
    background_tasks.add_task(
        record_decision_trace,
        make_trace_identity(
            case_id=id,
            run_id=agent_run_id,
            request_id=str(uuid4()),
            environment=get_settings().app_env,
            model=get_settings().gemini_model,
            prompt_version=get_system_prompt_version(),
            span_role="decision",
        ),
    )
    return result


@router.get("/cases/{id}/workflow")
async def get_case_workflow(
    id: str,
    case_service: CaseService = Depends(get_case_service),
    principal: Principal | None = Depends(require_principal),
) -> dict[str, Any]:
    require_role(principal, *CASE_READ_ROLES)
    if principal is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    require_case_scope(case_service, id, principal.organization_id)
    out = await asyncio.to_thread(
        case_workflow.load_stepper,
        case_service._get_db_connection,
        case_service._resolve_case_id(id),
        principal.organization_id,
    )
    out["actions"] = case_workflow.allowed_actions(out["status"], principal.roles)
    return out


@router.post("/cases/{id}/workflow/{action}")
async def advance_case_workflow(
    id: str,
    action: str,
    case_service: CaseService = Depends(get_case_service),
    principal: Principal | None = Depends(require_principal),
) -> dict[str, Any]:
    if principal is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    case_workflow.authorize(action, principal.roles)
    require_case_scope(case_service, id, principal.organization_id)
    out = await asyncio.to_thread(
        case_workflow.apply_transition,
        case_service._get_db_connection,
        case_service._resolve_case_id(id),
        principal.organization_id,
        principal.id,
        action,
        principal.roles,
    )
    out["actions"] = case_workflow.allowed_actions(out["status"], principal.roles)
    return out


@router.get("/cases/{id}/stream")
async def stream_case_progress(
    id: str,
    case_service: CaseService = Depends(get_case_service),
    principal: Principal | None = Depends(require_principal),
) -> StreamingResponse:
    require_role(principal, "analyst", "senior_analyst", "admin")
    if principal:
        require_case_scope(case_service, id, principal.organization_id)
    resolved_id = case_service._resolve_case_id(id)
    case_exists = False
    conn = case_service._get_db_connection()
    if conn is not None:
        try:
            with conn.cursor() as cur:
                cur.execute("SET search_path = app, extensions, public;")
                cur.execute("SELECT 1 FROM app.fraud_cases WHERE id = %s;", (resolved_id,))
                if cur.fetchone():
                    case_exists = True
        except Exception:
            pass
        finally:
            conn.close()
    if not case_exists and (resolved_id in case_service._cases or id in case_service._cases):
        case_exists = True
    if not case_exists:
        raise HTTPException(status_code=404, detail=f"Case {id} not found")
    return StreamingResponse(
        case_service.stream_case_progress(id, organization_id=principal.organization_id if principal else None),
        media_type="text/event-stream",
    )


@router.post("/policy/chat/stream")
async def stream_policy_chat(
    req: PolicyChatRequest,
    case_service: CaseService = Depends(get_case_service),
    principal: Principal | None = Depends(require_principal),
) -> StreamingResponse:
    require_role(principal, "analyst", "senior_analyst", "admin")
    if principal and req.case_id:
        require_case_scope(case_service, str(req.case_id), principal.organization_id)
    if req.event_schema_version == "1.1" and principal is not None:
        from src.services.agent_runtime import prepare_agent_turn, stream_agent_turn

        prepared = await prepare_agent_turn(principal, str(req.case_id), req.query, str(req.turn_id))
        frames = stream_agent_turn(
            principal,
            str(req.case_id),
            req.query,
            str(req.turn_id),
            prepared,
            reset_context=req.reset_context,
            attachments=req.attachments,
        )
        return StreamingResponse(frames, media_type="text/event-stream")
    return StreamingResponse(
        case_service.stream_policy_chat(
            req,
            organization_id=principal.organization_id if principal else None,
            actor_id=principal.id if principal else None,
        ),
        media_type="text/event-stream",
    )


@router.get("/cases/{id}/agent-context", response_model=AgentContextResponse)
async def get_case_agent_context(
    id: str,
    case_service: CaseService = Depends(get_case_service),
    principal: Principal | None = Depends(require_principal),
) -> dict[str, Any]:
    require_role(principal, *CASE_READ_ROLES)
    if principal:
        require_case_scope(case_service, id, principal.organization_id)
    from src.services.agent_runtime import get_agent_context

    return await get_agent_context(principal, id)


@router.delete("/cases/{id}/agent-context", response_model=AgentContextClearResponse)
async def delete_case_agent_context(
    id: str,
    case_service: CaseService = Depends(get_case_service),
    principal: Principal | None = Depends(require_principal),
) -> dict[str, Any]:
    require_role(principal, "analyst", "senior_analyst", "admin")
    if principal:
        require_case_scope(case_service, id, principal.organization_id)
    from src.services.agent_runtime import clear_agent_context

    return await clear_agent_context(principal, id)


@router.get("/cases/{id}/agent-session")
async def get_case_agent_session(
    id: str,
    case_service: CaseService = Depends(get_case_service),
    principal: Principal | None = Depends(require_principal),
) -> dict:
    require_role(principal, *CASE_READ_ROLES)
    return await case_service.get_case_agent_session(
        id,
        organization_id=principal.organization_id if principal else None,
    )


# Legacy chat & agent status
@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest, principal: Principal | None = Depends(require_principal)) -> ChatResponse:
    """Chat with the AI agent."""
    require_role(principal, "analyst", "senior_analyst", "admin")
    # S4-TENANT #294 P0: legacy unscoped agent use is denied outside the
    # /test/* stack. ChatRequest carries no case_id, so there is no case
    # scope to bind; fail closed when the server org is missing.
    if principal is None or not getattr(principal, "organization_id", None):
        if not test_auth_enabled():
            raise HTTPException(status_code=403, detail="Organization scope required")
    try:
        result = await agent.ainvoke({"query": request.message})
        return ChatResponse(
            response=result.get("response", ""),
            analysis=result.get("analysis", ""),
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/status")
async def agent_status():
    """Check agent operational status."""
    return {"status": "ready", "agent": "LangGraph Agent v1.0"}


# ---------------------------------------------------------------------------
# Driver Trips History & Summary Endpoints (Issue #479)
# ---------------------------------------------------------------------------
@router.get("/driver/trips", response_model=DriverTripsResponse)
async def get_driver_trips_route(
    cursor: str | None = Query(default=None),
    status: str | None = Query(default=None),
    month: str | None = Query(default=None),
    limit: int = Query(default=20),
    case_service: CaseService = Depends(get_case_service),
    principal: Principal | None = Depends(require_principal),
) -> DriverTripsResponse:
    """Retrieve authenticated driver's trip history with keyset cursor pagination."""
    require_role(principal, "driver")
    driver_id = principal.driver_id if principal else None
    if principal and not driver_id:
        raise HTTPException(403, "Driver mapping required")
    if driver_id:
        require_driver_identity(principal, driver_id)
    clamped_limit = max(1, min(limit, 50))

    from src.services.driver_service import list_driver_trips

    result = await list_driver_trips(
        driver_id=driver_id or "driver-guest",
        cursor=cursor,
        limit=clamped_limit,
        status=status,
        month=month,
        organization_id=principal.organization_id if principal else None,
        case_service=case_service,
    )
    return DriverTripsResponse(**result)


@router.get("/driver/trips/summary", response_model=DriverTripsSummaryResponse)
async def get_driver_trips_summary_route(
    month: str | None = Query(default=None),
    case_service: CaseService = Depends(get_case_service),
    principal: Principal | None = Depends(require_principal),
) -> DriverTripsSummaryResponse:
    """Retrieve monthly earnings and stats summary for authenticated driver."""
    require_role(principal, "driver")
    driver_id = principal.driver_id if principal else None
    if principal and not driver_id:
        raise HTTPException(403, "Driver mapping required")
    if driver_id:
        require_driver_identity(principal, driver_id)

    from src.services.driver_service import get_driver_trips_monthly_summary

    result = await get_driver_trips_monthly_summary(
        driver_id=driver_id or "driver-guest",
        month=month,
        organization_id=principal.organization_id if principal else None,
        case_service=case_service,
    )
    return DriverTripsSummaryResponse(**result)


@router.get("/driver/trips/{trip_id}", response_model=DriverTripItem)
async def get_driver_trip_route(
    trip_id: str,
    case_service: CaseService = Depends(get_case_service),
    principal: Principal | None = Depends(require_principal),
) -> DriverTripItem:
    """Retrieve single trip detail for authenticated driver, returning 404 for missing or foreign trips."""
    require_role(principal, "driver")
    driver_id = principal.driver_id if principal else None
    if principal and not driver_id:
        raise HTTPException(403, "Driver mapping required")
    if driver_id:
        require_driver_identity(principal, driver_id)

    from src.services.driver_service import get_driver_trip_summary

    result = await get_driver_trip_summary(
        trip_id=trip_id,
        driver_id=driver_id or "driver-guest",
        organization_id=principal.organization_id if principal else None,
        case_service=case_service,
    )
    return DriverTripItem(**result)


# ---------------------------------------------------------------------------
# Driver Profile & Customer Feedback Endpoints (Issue #480)
# ---------------------------------------------------------------------------
@router.get("/driver/profile", response_model=DriverProfileResponse)
async def get_driver_profile_route(
    principal: Principal | None = Depends(require_principal),
    case_service: CaseService = Depends(get_case_service),
) -> DriverProfileResponse:
    """Retrieve driver profile with identity, vehicle, 90-day scorecard, ratings, distribution, and weekly trend."""
    require_role(principal, "driver")
    driver_id = principal.driver_id if principal else None
    if not driver_id:
        raise HTTPException(404, "Driver not found")
    require_driver_identity(principal, driver_id)
    from src.services.driver_service import get_driver_profile

    return await get_driver_profile(
        driver_id=driver_id,
        organization_id=principal.organization_id if principal else None,
        case_service=case_service,
    )


@router.get("/driver/feedback", response_model=DriverFeedbackResponse)
async def get_driver_feedback_route(
    cursor: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=50),
    principal: Principal | None = Depends(require_principal),
    case_service: CaseService = Depends(get_case_service),
) -> DriverFeedbackResponse:
    """Retrieve cursor-paginated customer feedback for the authenticated driver."""
    require_role(principal, "driver")
    driver_id = principal.driver_id if principal else None
    if not driver_id:
        raise HTTPException(404, "Driver not found")
    require_driver_identity(principal, driver_id)
    from src.services.driver_service import list_driver_feedback

    return await list_driver_feedback(
        driver_id=driver_id,
        cursor=cursor,
        limit=limit,
        organization_id=principal.organization_id if principal else None,
        case_service=case_service,
    )


# ---------------------------------------------------------------------------
# Driver Dispute & A2A Delegation Endpoints (Slice 2)
# ---------------------------------------------------------------------------
@router.get("/driver/cases", response_model=DriverCaseListResponse)
async def list_driver_cases_route(
    request: Request,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    locale: str | None = Query(default=None),
    dispute_service: DriverDisputeService = Depends(get_driver_dispute_service),
    case_service: CaseService = Depends(get_case_service),
    principal: Principal | None = Depends(require_principal),
) -> DriverCaseListResponse:
    """Retrieve driver's assigned case dispute sessions."""
    require_role(principal, "driver")
    driver_id = principal.driver_id if principal else None
    if principal and not driver_id:
        raise HTTPException(403, "Driver mapping required")
    from src.services.driver_dispute_service import resolve_request_locale

    call_kwargs: dict[str, Any] = {
        "driver_id": driver_id,
        "organization_id": principal.organization_id if principal else None,
        "limit": limit,
        "offset": offset,
    }
    raw_header = request.headers.get("accept-language")
    if locale is not None or raw_header:
        call_kwargs["locale"] = resolve_request_locale(locale, raw_header)

    return await dispute_service.list_driver_cases(**call_kwargs)


@router.get("/driver/cases/{case_id}/session")
async def get_driver_case_session_route(
    case_id: str,
    dispute_service: DriverDisputeService = Depends(get_driver_dispute_service),
    case_service: CaseService = Depends(get_case_service),
    principal: Principal | None = Depends(require_principal),
) -> dict:
    """Retrieve persistent conversation history for a driver case session."""
    require_role(principal, "driver")
    if principal:
        require_driver_identity(principal, principal.driver_id or "")
        require_case_scope(
            case_service,
            case_id,
            principal.organization_id,
            principal.driver_id,
            anti_probing_driver_mismatch=True,
        )
    resolved_id = None if (not principal or principal.id == "driver-guest") else (principal.driver_id or principal.id)
    context = await dispute_service.get_dispute_context(case_id, driver_id=resolved_id)
    if principal and not (test_auth_enabled() and principal.id == "driver-guest"):
        require_driver_identity(principal, context.driver_id)
    return await dispute_service.get_driver_session(
        case_id,
        organization_id=principal.organization_id if principal else None,
    )


@router.get("/driver/cases/{case_id}/dispute", response_model=DriverDisputeContextResponse)
async def get_driver_dispute(
    case_id: str,
    request: Request,
    locale: str | None = Query(default=None),
    dispute_service: DriverDisputeService = Depends(get_driver_dispute_service),
    case_service: CaseService = Depends(get_case_service),
    principal: Principal | None = Depends(require_principal),
) -> DriverDisputeContextResponse:
    """Fetch rich context of alleged violation for driver dispute interface."""
    require_role(principal, "driver")
    if principal:
        require_driver_identity(principal, principal.driver_id or "")
        require_case_scope(case_service, case_id, principal.organization_id, principal.driver_id)
    from src.services.driver_dispute_service import resolve_request_locale

    resolved_id = None if (not principal or principal.id == "driver-guest") else (principal.driver_id or principal.id)
    context = await dispute_service.get_dispute_context(
        case_id,
        driver_id=resolved_id,
        locale=resolve_request_locale(locale, request.headers.get("accept-language")),
    )
    if principal and not (test_auth_enabled() and principal.id == "driver-guest"):
        require_driver_identity(principal, context.driver_id)
    return context


@router.post("/driver/chat/stream")
async def stream_driverless_chat_route(
    req: DriverlessChatRequest,
    dispute_service: DriverDisputeService = Depends(get_driver_dispute_service),
    principal: Principal | None = Depends(require_principal),
) -> StreamingResponse:
    """SSE stream case-less GSupport chat (Issue #482): no case_id, driver
    identity resolved from the authenticated principal, real agent reply.
    """
    require_role(principal, "driver")
    if not principal:
        raise HTTPException(status_code=401, detail="Authentication required")
    driver_id = principal.driver_id
    if not driver_id:
        raise HTTPException(status_code=403, detail="Driver mapping required")
    return StreamingResponse(
        dispute_service.stream_driverless_chat(
            driver_id=driver_id,
            message=req.message,
            locale=req.locale,
            turn_id=req.turn_id,
            organization_id=principal.organization_id if principal else None,
        ),
        media_type="text/event-stream",
    )


@router.post("/driver/cases/{case_id}/chat", response_model=DriverChatResponse)
async def post_driver_chat(
    case_id: str,
    req: DriverChatRequest,
    dispute_service: DriverDisputeService = Depends(get_driver_dispute_service),
    case_service: CaseService = Depends(get_case_service),
    principal: Principal | None = Depends(require_principal),
) -> DriverChatResponse:
    """Submit driver statement and evaluate autonomous exoneration or escalation."""
    require_role(principal, "driver")
    if principal:
        require_driver_identity(principal, principal.driver_id or "")
        require_case_scope(
            case_service,
            case_id,
            principal.organization_id,
            principal.driver_id,
            anti_probing_driver_mismatch=True,
        )
    resolved_id = None if (not principal or principal.id == "driver-guest") else (principal.driver_id or principal.id)
    context = await dispute_service.get_dispute_context(case_id, driver_id=resolved_id)
    if principal and not (test_auth_enabled() and principal.id == "driver-guest"):
        require_driver_identity(principal, context.driver_id)
    target_driver_id = (
        context.driver_id
        if (not principal or principal.id == "driver-guest")
        else (principal.driver_id or principal.id)
    )
    if principal and req.driver_id and req.driver_id != "driver-guest":
        if not (test_auth_enabled() and principal.id == "driver-guest"):
            require_driver_identity(principal, req.driver_id)
    if not req.case_id or req.case_id != case_id:
        req = req.model_copy(update={"case_id": case_id})
    if not req.driver_id or req.driver_id == "driver-guest":
        req = req.model_copy(update={"driver_id": target_driver_id})
    return await dispute_service.process_driver_chat_turn(
        case_id=case_id,
        request=req,
        driver_id=target_driver_id,
    )


@router.get("/driver/cases/{case_id}/chat/stream")
async def stream_driver_chat_get(
    case_id: str,
    message: str = Query(default=""),
    claim_type: str | None = Query(default=None),
    turn_id: str | None = Query(default=None),
    locale: str = Query(default="vi"),
    dispute_service: DriverDisputeService = Depends(get_driver_dispute_service),
    case_service: CaseService = Depends(get_case_service),
    principal: Principal | None = Depends(require_principal),
) -> StreamingResponse:
    """SSE stream driver dispute reply token-by-token followed by completion event."""
    require_role(principal, "driver")
    if principal:
        require_driver_identity(principal, principal.driver_id or "")
        require_case_scope(
            case_service,
            case_id,
            principal.organization_id,
            principal.driver_id,
            anti_probing_driver_mismatch=True,
        )
    resolved_id = None if (not principal or principal.id == "driver-guest") else (principal.driver_id or principal.id)
    context = await dispute_service.get_dispute_context(
        case_id,
        driver_id=resolved_id,
        organization_id=principal.organization_id if principal else None,
        locale=locale,
    )
    if principal and not (test_auth_enabled() and principal.id == "driver-guest"):
        require_driver_identity(principal, context.driver_id)
    driver_id = resolved_id or context.driver_id
    if not driver_id:
        raise HTTPException(status_code=403, detail="Driver mapping required")
    return StreamingResponse(
        dispute_service.stream_driver_chat(
            case_id=case_id,
            message=message or "Tôi muốn giải trình về trường hợp này",
            claim_type=claim_type,
            driver_id=driver_id,
            turn_id=turn_id,
            locale=locale,
            organization_id=principal.organization_id if principal else None,
        ),
        media_type="text/event-stream",
    )


@router.post("/driver/cases/{case_id}/chat/stream")
async def stream_driver_chat_post(
    case_id: str,
    req: DriverChatRequest,
    dispute_service: DriverDisputeService = Depends(get_driver_dispute_service),
    case_service: CaseService = Depends(get_case_service),
    principal: Principal | None = Depends(require_principal),
) -> StreamingResponse:
    """SSE stream driver dispute reply token-by-token (POST alternative)."""
    require_role(principal, "driver")
    if principal:
        require_driver_identity(principal, principal.driver_id or "")
        require_case_scope(
            case_service,
            case_id,
            principal.organization_id,
            principal.driver_id,
            anti_probing_driver_mismatch=True,
        )
    if principal and req.driver_id and req.driver_id != "driver-guest":
        if not (test_auth_enabled() and principal.id == "driver-guest"):
            require_driver_identity(principal, req.driver_id)
    if req.event_schema_version == "1.1":
        require_role(principal, "driver")
        from src.services.agent_runtime import prepare_agent_turn, stream_agent_turn

        prepared = await prepare_agent_turn(principal, case_id, req.message, req.turn_id)
        return StreamingResponse(
            stream_agent_turn(principal, case_id, req.message, req.turn_id, prepared), media_type="text/event-stream"
        )
    target_driver_id = (
        req.driver_id
        if (req.driver_id and req.driver_id != "driver-guest")
        else ((principal.driver_id or principal.id) if (principal and principal.id != "driver-guest") else None)
    )
    context = await dispute_service.get_dispute_context(
        case_id,
        driver_id=target_driver_id,
        organization_id=principal.organization_id if principal else None,
        locale=req.locale,
    )
    if principal and not (test_auth_enabled() and principal.id == "driver-guest"):
        require_driver_identity(principal, context.driver_id)
    driver_id = target_driver_id or context.driver_id
    if not driver_id:
        raise HTTPException(status_code=403, detail="Driver mapping required")
    return StreamingResponse(
        dispute_service.stream_driver_chat(
            case_id=case_id,
            message=req.message,
            claim_type=req.claim_type,
            driver_id=driver_id,
            turn_id=req.turn_id,
            locale=req.locale,
            organization_id=principal.organization_id if principal else None,
        ),
        media_type="text/event-stream",
    )


async def _require_owned_driver_case(
    case_id: str,
    principal: Principal | None,
    dispute_service: DriverDisputeService,
) -> tuple[str, DriverDisputeContextResponse]:
    """Verify caller has driver role and owns case_id; return 404 on missing or foreign case."""
    require_role(principal, "driver")
    driver_id = principal.driver_id if principal else None
    if not driver_id or driver_id == "driver-guest":
        raise HTTPException(status_code=403, detail="Driver mapping required")
    require_driver_identity(principal, driver_id)
    context = await dispute_service.get_driver_dispute_context(case_id, driver_id)
    require_driver_identity(principal, context.driver_id)
    return context.driver_id, context


@router.post("/driver/cases/{case_id}/confirmations")
async def create_driver_confirmation_route(
    case_id: str,
    req: ConfirmationRequest,
    dispute_service: DriverDisputeService = Depends(get_driver_dispute_service),
    principal: Principal | None = Depends(require_principal),
) -> dict[str, Any]:
    """Issue a single-use confirmation token for driver accept/reject flow (Issue #483)."""
    driver_id, context = await _require_owned_driver_case(case_id, principal, dispute_service)
    if req.action not in ("acknowledge", "submit_statement"):
        raise HTTPException(status_code=422, detail="Invalid confirmation action")
    token = await dispute_service.issue_confirmation_token(
        case_id=context.case_id,
        driver_id=driver_id,
        action=req.action,
        draft_hash=req.draft_hash or "",
    )
    rec = dispute_service._lookup_token(token)
    expires_at = (
        rec["expires_at"].isoformat()
        if rec and hasattr(rec.get("expires_at"), "isoformat")
        else (datetime.now(UTC) + timedelta(minutes=10)).isoformat()
    )
    return {"confirmation_token": token, "expires_at": expires_at}


@router.post("/driver/cases/{case_id}/acknowledge")
async def acknowledge_driver_violation_route(
    case_id: str,
    req: AcknowledgeRequest,
    dispute_service: DriverDisputeService = Depends(get_driver_dispute_service),
    principal: Principal | None = Depends(require_principal),
) -> dict[str, Any]:
    """Acknowledge violation with single-use confirmation token; routes to analyst and never sanctions."""
    driver_id, context = await _require_owned_driver_case(case_id, principal, dispute_service)
    return await dispute_service.acknowledge_with_token(
        case_id=context.case_id,
        driver_id=driver_id,
        confirmation_token=req.confirmation_token,
    )


@router.post("/driver/cases/{case_id}/statement")
async def submit_driver_statement_route(
    case_id: str,
    req: StatementSubmitRequest,
    dispute_service: DriverDisputeService = Depends(get_driver_dispute_service),
    principal: Principal | None = Depends(require_principal),
) -> dict[str, Any]:
    """Submit driver dispute statement with single-use confirmation token; escalates to analyst."""
    driver_id, context = await _require_owned_driver_case(case_id, principal, dispute_service)
    if not req.reason_summary or not req.reason_summary.strip():
        raise HTTPException(status_code=422, detail="reason_summary is required")
    return await dispute_service.submit_statement_with_token(
        case_id=context.case_id,
        driver_id=driver_id,
        confirmation_token=req.confirmation_token,
        reason_summary=req.reason_summary.strip(),
        evidence=req.evidence,
    )


@router.put("/driver/cases/{case_id}/statement-draft")
async def put_driver_statement_draft_route(
    case_id: str,
    body: dict[str, Any],
    dispute_service: DriverDisputeService = Depends(get_driver_dispute_service),
    principal: Principal | None = Depends(require_principal),
) -> dict[str, Any]:
    """Save or update a driver statement draft for an owned case."""
    driver_id, context = await _require_owned_driver_case(case_id, principal, dispute_service)
    draft_payload = body["draft"] if ("draft" in body and isinstance(body["draft"], dict) and len(body) == 1) else body
    saved = await dispute_service.save_statement_draft(
        case_id=context.case_id,
        driver_id=driver_id,
        draft=draft_payload,
    )
    return {"case_id": context.case_id, "driver_id": driver_id, "draft": saved, **saved}


@router.get("/driver/cases/{case_id}/statement-draft")
async def get_driver_statement_draft_route(
    case_id: str,
    dispute_service: DriverDisputeService = Depends(get_driver_dispute_service),
    principal: Principal | None = Depends(require_principal),
) -> dict[str, Any]:
    """Retrieve a saved driver statement draft for an owned case."""
    driver_id, context = await _require_owned_driver_case(case_id, principal, dispute_service)
    draft = await dispute_service.get_statement_draft(case_id=context.case_id, driver_id=driver_id)
    if draft is None:
        return {"case_id": context.case_id, "driver_id": driver_id, "draft": None}
    return {"case_id": context.case_id, "driver_id": driver_id, "draft": draft, **draft}


@router.post("/cases/{case_id}/delegate-inquiry")
async def delegate_inquiry_route(
    case_id: str,
    req: AnalystDelegateInquiryRequest,
    dispute_service: DriverDisputeService = Depends(get_driver_dispute_service),
    case_service: CaseService = Depends(get_case_service),
    principal: Principal | None = Depends(require_principal),
) -> dict:
    """Analyst requests additional explanation or evidence from driver."""
    require_role(principal, "analyst", "senior_analyst", "admin")
    if principal:
        require_case_scope(case_service, case_id, principal.organization_id)
    if principal and req.analyst_id:
        require_analyst_identity(principal, req.analyst_id)
    if not req.case_id or req.case_id != case_id:
        req = req.model_copy(update={"case_id": case_id})
    if not req.analyst_id and principal:
        req = req.model_copy(update={"analyst_id": principal.id})
    return await dispute_service.delegate_analyst_inquiry(case_id, req)


@router.get("/cases/{case_id}/dispute-dossier", response_model=DisputeDossierResponse)
async def get_dispute_dossier_route(
    case_id: str,
    dispute_service: DriverDisputeService = Depends(get_driver_dispute_service),
    case_service: CaseService = Depends(get_case_service),
    principal: Principal | None = Depends(require_principal),
) -> DisputeDossierResponse:
    """Retrieve compiled dispute dossier with corroboration, precedents, and transcript."""
    require_role(principal, *CASE_READ_ROLES)
    if principal:
        require_case_scope(case_service, case_id, principal.organization_id)
    return await dispute_service.get_dispute_dossier(case_id)


# ---------------------------------------------------------------------------
# Precedent Workflow Mining & Jev Similarity Endpoints (POC v2 Extension)
# ---------------------------------------------------------------------------
@router.get("/cases/{case_id}/workflow-draft", response_model=WorkflowDraftResponse)
async def get_workflow_draft_route(
    case_id: str,
    case_service: CaseService = Depends(get_case_service),
    principal: Principal | None = Depends(require_principal),
) -> WorkflowDraftResponse:
    require_role(principal, *CASE_READ_ROLES)
    return await case_service.get_workflow_draft(
        case_id, organization_id=principal.organization_id if principal else None
    )


@router.put("/cases/{case_id}/workflow-draft", response_model=WorkflowDraftResponse)
async def save_workflow_draft_route(
    case_id: str,
    request: WorkflowDraftRequest,
    case_service: CaseService = Depends(get_case_service),
    principal: Principal | None = Depends(require_principal),
) -> WorkflowDraftResponse:
    require_role(principal, "analyst", "senior_analyst", "admin")
    return await case_service.save_workflow_draft(
        case_id,
        request,
        analyst_id=principal.id if principal else "test-analyst",
        organization_id=principal.organization_id if principal else None,
    )


@router.get("/cases/{case_id}/workflow-trace", response_model=WorkflowTrace)
async def get_case_workflow_trace_route(
    case_id: str,
    jev_service: JevPrecedentService = Depends(get_jev_precedent_service),
    case_service: CaseService = Depends(get_case_service),
    principal: Principal | None = Depends(require_principal),
) -> WorkflowTrace:
    """Retrieve synthesized workflow trace for a case."""
    require_role(principal, *CASE_READ_ROLES)
    if principal:
        require_case_scope(case_service, case_id, principal.organization_id)
    return await asyncio.to_thread(
        jev_service.get_workflow_trace,
        case_id,
        organization_id=principal.organization_id if principal else None,
    )


@router.post("/cases/{case_id}/match-precedent", response_model=PrecedentMatchResponse)
async def match_case_precedent_route(
    case_id: str,
    req: PrecedentMatchRequest,
    jev_service: JevPrecedentService = Depends(get_jev_precedent_service),
    case_service: CaseService = Depends(get_case_service),
    principal: Principal | None = Depends(require_principal),
) -> PrecedentMatchResponse:
    """Evaluate precedent similarity using TypeSafe Jev Decision model or heuristic fallback."""
    require_role(principal, "analyst", "senior_analyst", "admin")
    if principal:
        require_case_scope(case_service, case_id, principal.organization_id)
    return await jev_service.match_precedent(
        case_id=case_id,
        claim_type=req.claim_type,
        driver_statement=req.driver_statement,
        violation_code=req.violation_code,
        telemetry_summary=req.telemetry_summary,
        organization_id=principal.organization_id if principal else None,
        actor_id=principal.id if principal else None,
    )


@router.get("/precedents", response_model=list[PrecedentWorkflowItem])
async def list_precedents_route(
    violation_code: str | None = Query(default=None),
    claim_type: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100),
    jev_service: JevPrecedentService = Depends(get_jev_precedent_service),
    principal: Principal | None = Depends(require_principal),
) -> list[PrecedentWorkflowItem]:
    """List historical precedent workflows from Precedent Bank."""
    require_role(principal, "analyst", "senior_analyst", "admin")
    return jev_service.list_precedents(
        violation_code=violation_code,
        claim_type=claim_type,
        limit=limit,
        organization_id=principal.organization_id if principal else None,
    )


@router.get("/precedents/{precedent_id}", response_model=PrecedentWorkflowItem)
async def get_precedent_route(
    precedent_id: str,
    jev_service: JevPrecedentService = Depends(get_jev_precedent_service),
    principal: Principal | None = Depends(require_principal),
) -> PrecedentWorkflowItem:
    """Retrieve single historical precedent workflow."""
    require_role(principal, "analyst", "senior_analyst", "admin")
    item = jev_service.get_precedent(
        precedent_id,
        organization_id=principal.organization_id if principal else None,
    )
    if not item:
        raise HTTPException(status_code=404, detail=f"Precedent '{precedent_id}' not found.")
    return item


@router.post("/cases/{case_id}/apply-precedent")
async def apply_precedent_route(
    case_id: str,
    payload: dict[str, Any],
    jev_service: JevPrecedentService = Depends(get_jev_precedent_service),
    case_service: CaseService = Depends(get_case_service),
    principal: Principal | None = Depends(require_principal),
) -> dict[str, Any]:
    """Apply precedent procedure parameters (verdict, rationale, policies) to current case."""
    require_role(principal, "analyst", "senior_analyst", "admin")
    if principal:
        require_case_scope(case_service, case_id, principal.organization_id)
    precedent_id = payload.get("precedent_id")
    if not precedent_id:
        raise HTTPException(status_code=422, detail="Field 'precedent_id' is required.")
    try:
        return jev_service.apply_precedent_procedure(
            case_id,
            str(precedent_id),
            organization_id=principal.organization_id if principal else None,
            actor_id=principal.id if principal else None,
            request_id=payload.get("request_id"),
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except PrecedentPersistenceError as e:
        raise HTTPException(status_code=409, detail=str(e))


# Org population bootstrap (S4-ACTORS #295, ADR-025 §4)
def _require_own_org(principal: Principal | None, org_id: str) -> None:
    if principal and str(principal.organization_id) != str(org_id):
        raise HTTPException(status_code=403, detail="Admin may only manage their own organization")


@router.post("/admin/organizations/{org_id}/bootstrap")
async def admin_bootstrap_org_population(
    org_id: str,
    template_version: str = Query(default=DEFAULT_TEMPLATE_VERSION),
    seed: str = Query(default=DEFAULT_SEED),
    principal: Principal | None = Depends(require_principal),
    case_service: CaseService = Depends(get_case_service),
) -> dict[str, Any]:
    """Idempotently bootstrap 100 drivers + 1000 customers for the admin's own org."""
    require_role(principal, "admin")
    _require_own_org(principal, org_id)
    try:
        return bootstrap_org_population(
            org_id,
            case_service._get_db_connection,
            template_version=template_version,
            seed=seed,
        )
    except DatabaseUnavailableError as e:
        raise HTTPException(status_code=503, detail=f"{e}; retry the same request") from e
    except BootstrapError as e:
        raise HTTPException(status_code=422 if str(e).startswith("Invalid") else 503, detail=str(e)) from e


@router.get("/admin/organizations/{org_id}/bootstrap")
async def admin_bootstrap_status(
    org_id: str,
    template_version: str = Query(default=DEFAULT_TEMPLATE_VERSION),
    seed: str = Query(default=DEFAULT_SEED),
    principal: Principal | None = Depends(require_principal),
    case_service: CaseService = Depends(get_case_service),
) -> dict[str, Any]:
    """Bootstrap progress; reports ready only after verified exact counts."""
    require_role(principal, "admin")
    _require_own_org(principal, org_id)
    try:
        return get_bootstrap_status(
            org_id,
            case_service._get_db_connection,
            template_version=template_version,
            seed=seed,
        )
    except DatabaseUnavailableError as e:
        raise HTTPException(status_code=503, detail=f"{e}; retry the same request") from e
    except BootstrapError as e:
        raise HTTPException(status_code=422 if str(e).startswith("Invalid") else 503, detail=str(e)) from e


@router.post("/admin/drivers/{driver_id}/link")
async def admin_link_driver(
    driver_id: str,
    payload: dict[str, Any],
    principal: Principal | None = Depends(require_principal),
    case_service: CaseService = Depends(get_case_service),
) -> dict[str, Any]:
    """Explicitly bind a Driver member to an owned driver entity (same-org only)."""
    require_role(principal, "admin")
    principal_id = payload.get("principal_id")
    if not principal_id:
        raise HTTPException(status_code=422, detail="Field 'principal_id' is required.")
    try:
        return link_driver_principal(
            driver_id,
            str(principal_id),
            principal.organization_id if principal else "",
            case_service._get_db_connection,
        )
    except OrgMismatchError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    except NotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except DatabaseUnavailableError as e:
        raise HTTPException(status_code=503, detail=f"{e}; retry the same request") from e
    except BootstrapError as e:
        raise HTTPException(status_code=422 if str(e).startswith("Invalid") else 503, detail=str(e)) from e


# Invitations (S4-ENTRY #296, ADR-025): Admin-only, own-org, stub Clerk proxy.
SUPPORTED_INVITE_ROLES = {"admin", "analyst", "driver"}
_INVITATIONS: dict[str, dict[str, Any]] = {}


class InvitationCreate(BaseModel):
    email: str = Field(..., min_length=3, max_length=320)
    role: str = Field(...)


def _clerk_secret_configured() -> bool:
    settings = get_settings()
    return bool(settings.clerk_secret_key)


@router.post("/admin/invitations", status_code=201)
async def create_invitation(
    payload: InvitationCreate,
    principal: Principal | None = Depends(require_principal),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    """Invite email+role to the Admin's own org. Fails safe on 403/422/501."""
    require_role(principal, "admin")
    role = payload.role.strip().lower()
    if role == "fraud_analyst":
        role = "analyst"
    if role not in SUPPORTED_INVITE_ROLES:
        raise HTTPException(status_code=422, detail=f"Unsupported role '{payload.role}'")
    email = payload.email.strip().lower()
    if "@" not in email or "." not in email.split("@")[-1]:
        raise HTTPException(status_code=422, detail="Invalid email address")
    if not settings.clerk_secret_key:
        raise HTTPException(
            status_code=501,
            detail="Clerk secret missing: set CLERK_SECRET_KEY to enable invitations",
        )
    invitation_id = str(uuid4())
    record = {
        "id": invitation_id,
        "email": email,
        "role": role,
        "organization_id": principal.organization_id if principal else None,
        "status": "pending",
        "created_at": datetime.now(UTC).isoformat(),
    }
    _INVITATIONS[invitation_id] = record
    return record


@router.get("/admin/invitations")
async def list_invitations(
    principal: Principal | None = Depends(require_principal),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    require_role(principal, "admin")
    org_id = principal.organization_id if principal else None
    items = [r for r in _INVITATIONS.values() if r.get("organization_id") == org_id]
    return {"items": items[offset : offset + limit], "total": len(items)}


@router.post("/admin/invitations/{invitation_id}/revoke")
async def revoke_invitation(
    invitation_id: str,
    principal: Principal | None = Depends(require_principal),
) -> dict[str, Any]:
    require_role(principal, "admin")
    record = _INVITATIONS.get(invitation_id)
    if not record or record.get("organization_id") != (principal.organization_id if principal else None):
        raise HTTPException(status_code=404, detail="Invitation not found")
    record["status"] = "revoked"
    return record


@router.post("/admin/invitations/{invitation_id}/resend")
async def resend_invitation(
    invitation_id: str,
    principal: Principal | None = Depends(require_principal),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    require_role(principal, "admin")
    record = _INVITATIONS.get(invitation_id)
    if not record or record.get("organization_id") != (principal.organization_id if principal else None):
        raise HTTPException(status_code=404, detail="Invitation not found")
    if record.get("status") == "revoked":
        raise HTTPException(status_code=422, detail="Revoked invitations cannot be resent")
    if not settings.clerk_secret_key:
        raise HTTPException(
            status_code=501,
            detail="Clerk secret missing: set CLERK_SECRET_KEY to enable invitations",
        )
    record["status"] = "pending"
    return record

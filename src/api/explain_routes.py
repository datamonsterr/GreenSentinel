"""Driver explanation agent v2 routes (PRD-A, ADR-034).

`/driver/cases/{id}/explain/*` is driver-only and scoped to the driver's own case (404 otherwise).
`/cases/{id}/explain*` and `/explain/help-requests*` are for analyst-family / VH roles; role checks
live in the service. The legacy driver chat and statement routes are untouched.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from src.api.auth import Principal, require_principal, require_role
from src.services.explain_service import FEEDBACK_ERROR_TYPES, ExplainService, get_explain_service

router = APIRouter(tags=["explain"])
svc = get_explain_service


def _actor(principal: Principal | None) -> Principal:
    if principal is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    return principal


def _driver(principal: Principal | None) -> Principal:
    p = _actor(principal)
    require_role(p, "driver")
    return p


class StartBody(BaseModel):
    reason: str


class AnswersBody(BaseModel):
    answers: dict[str, Any] = Field(default_factory=dict)


class AnswerBody(BaseModel):
    text: str = ""
    attachments: list[str] = Field(default_factory=list, max_length=10)
    ticket_code: str | None = Field(default=None, max_length=32)


class EditBody(BaseModel):
    text: str


class FeedbackBody(BaseModel):
    verdict: str
    error_types: list[str] = Field(default_factory=list)
    comment: str | None = Field(default=None, max_length=2000)


class HelpReplyBody(BaseModel):
    text: str
    facts: list[str] = Field(default_factory=list, max_length=10)


# ---- driver ---------------------------------------------------------------------------------------
@router.post("/driver/cases/{case_id}/explain/start")
async def driver_start(
    case_id: str,
    body: StartBody,
    principal: Principal | None = Depends(require_principal),
    s: ExplainService = Depends(svc),
):
    return await s.start(_driver(principal), case_id, body.reason)


@router.get("/driver/cases/{case_id}/explain")
async def driver_get(
    case_id: str, principal: Principal | None = Depends(require_principal), s: ExplainService = Depends(svc)
):
    return await s.get_for_driver(_driver(principal), case_id)


@router.put("/driver/cases/{case_id}/explain/draft")
async def driver_draft(
    case_id: str,
    body: AnswersBody,
    principal: Principal | None = Depends(require_principal),
    s: ExplainService = Depends(svc),
):
    return await s.save_draft(_driver(principal), case_id, body.answers)


@router.post("/driver/cases/{case_id}/explain/submit")
async def driver_submit(
    case_id: str,
    body: AnswersBody,
    principal: Principal | None = Depends(require_principal),
    s: ExplainService = Depends(svc),
):
    return await s.submit(_driver(principal), case_id, body.answers)


@router.post("/driver/cases/{case_id}/explain/answer")
async def driver_answer(
    case_id: str,
    body: AnswerBody,
    principal: Principal | None = Depends(require_principal),
    s: ExplainService = Depends(svc),
):
    return await s.answer(_driver(principal), case_id, body.text, body.attachments, body.ticket_code)


@router.post("/driver/cases/{case_id}/explain/end")
async def driver_end(
    case_id: str, principal: Principal | None = Depends(require_principal), s: ExplainService = Depends(svc)
):
    return await s.end(_driver(principal), case_id)


@router.post("/driver/cases/{case_id}/explain/summary/edit")
async def driver_summary_edit(
    case_id: str,
    body: EditBody,
    principal: Principal | None = Depends(require_principal),
    s: ExplainService = Depends(svc),
):
    return await s.edit_summary(_driver(principal), case_id, body.text)


@router.post("/driver/cases/{case_id}/explain/summary/confirm")
async def driver_summary_confirm(
    case_id: str, principal: Principal | None = Depends(require_principal), s: ExplainService = Depends(svc)
):
    return await s.confirm_summary(_driver(principal), case_id)


# ---- analyst / VH ---------------------------------------------------------------------------------
@router.get("/cases/{case_id}/explain")
async def analyst_get(
    case_id: str, principal: Principal | None = Depends(require_principal), s: ExplainService = Depends(svc)
):
    return s.analyst_view(_actor(principal), case_id)


@router.post("/cases/{case_id}/explain/feedback", status_code=201)
async def analyst_feedback(
    case_id: str,
    body: FeedbackBody,
    principal: Principal | None = Depends(require_principal),
    s: ExplainService = Depends(svc),
):
    return s.feedback(_actor(principal), case_id, body.verdict, body.error_types, body.comment)


@router.get("/explain/meta")
async def explain_meta(principal: Principal | None = Depends(require_principal)):
    _actor(principal)
    return {
        "feedback_error_types": list(FEEDBACK_ERROR_TYPES),
        "assessment_states": ["eligible", "not_eligible", "needs_driver", "missing_internal"],
        "flags": [
            "novel_scenario",
            "statement_changed",
            "ai_inconclusive",
            "session_interrupted",
            "asked_for_help",
            "asked_for_help_skipped",
        ],
    }


@router.get("/explain/help-requests")
async def help_list(
    status: str | None = None,
    principal: Principal | None = Depends(require_principal),
    s: ExplainService = Depends(svc),
):
    return await s.help_queue(_actor(principal), status)


@router.get("/explain/help-requests/count")
async def help_count(principal: Principal | None = Depends(require_principal), s: ExplainService = Depends(svc)):
    return await s.help_count(_actor(principal))


@router.get("/explain/help-requests/{help_id}")
async def help_detail(
    help_id: str, principal: Principal | None = Depends(require_principal), s: ExplainService = Depends(svc)
):
    return await s.help_detail(_actor(principal), help_id)


@router.post("/explain/help-requests/{help_id}/claim")
async def help_claim(
    help_id: str, principal: Principal | None = Depends(require_principal), s: ExplainService = Depends(svc)
):
    return await s.help_claim(_actor(principal), help_id)


@router.post("/explain/help-requests/{help_id}/reply")
async def help_reply(
    help_id: str,
    body: HelpReplyBody,
    principal: Principal | None = Depends(require_principal),
    s: ExplainService = Depends(svc),
):
    return await s.help_reply(_actor(principal), help_id, body.text, body.facts)

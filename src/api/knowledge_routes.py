"""Knowledge base + agent config routes (PRD-K, ADR-032).

`/knowledge/*` is for the KSGL family and admin (formulas and thresholds are real detection logic);
`/agent-config/*` and `/knowledge/registry` are also readable by VH roles. Role checks live in the services.
"""

from __future__ import annotations

import base64
import binascii
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from src.api.auth import Principal, require_principal
from src.services.agent_config_service import DEFINITIONS, AgentConfigService, get_agent_config_service
from src.services.kb_formula import PARAMETER_CATALOGUE, validate_formula
from src.services.kb_service import REJECT_REASONS, TOOL_CATALOGUE, TYPES, KbService, get_kb_service
from src.services.policy_analysis_service import PolicyAnalysisService, extract_text

router = APIRouter(tags=["knowledge"])


def _actor(principal: Principal | None) -> Principal:
    if principal is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    return principal


class ObjectCreate(BaseModel):
    type: str
    code: str
    name: str = ""
    scope: dict[str, Any] = Field(default_factory=dict)
    body: dict[str, Any] = Field(default_factory=dict)
    reason: str = ""


class ObjectUpdate(BaseModel):
    name: str | None = None
    scope: dict[str, Any] | None = None
    body: dict[str, Any] | None = None
    reason: str = ""


class FormulaValidate(BaseModel):
    formula: str
    params: dict[str, Any] | None = None


class PreviewBody(BaseModel):
    case_ids: list[str] | None = None
    params: dict[str, Any] | None = None


class PublishBody(BaseModel):
    override_reason: str | None = None


class ReasonBody(BaseModel):
    reason: str = ""


class SimilarBody(BaseModel):
    text: str
    type: str | None = None
    limit: int = 5


class DocumentCreate(BaseModel):
    name: str = ""
    code: str = ""
    text: str = ""
    filename: str | None = None
    content_type: str | None = None
    size_bytes: int = 0
    effective_from: str | None = None
    effective_to: str | None = None
    region: str | None = None
    service: str | None = None
    contract_type: str | None = None
    content_base64: str | None = Field(default=None, max_length=14_000_000)  # docx/pdf bytes; text is extracted server-side


class ProposalCreate(BaseModel):
    source: str = "manual"
    type: str
    title: str
    payload: dict[str, Any] = Field(default_factory=dict)
    source_excerpt: str | None = None
    source_ref: str | None = None
    mapping: str = "new"
    similarity: float | None = None
    matched_code: str | None = None


class ProposalEdit(BaseModel):
    payload: dict[str, Any]


class ProposalReject(BaseModel):
    reason_code: str
    note: str = ""


class ConfigSet(BaseModel):
    value: Any
    reason: str = ""
    scope: str = "global"


class KillSwitch(BaseModel):
    enabled: bool
    reason: str = ""


kb = get_kb_service
cfgsvc = get_agent_config_service


# ---- knowledge objects -------------------------------------------------------------------------
@router.get("/knowledge/meta")
def meta(principal: Principal | None = Depends(require_principal)) -> dict[str, Any]:
    _actor(principal)
    return {"types": list(TYPES), "tools": list(TOOL_CATALOGUE), "reject_reasons": list(REJECT_REASONS),
            "config_keys": list(DEFINITIONS)}


@router.get("/knowledge/parameters")
def parameters(principal: Principal | None = Depends(require_principal)) -> dict[str, Any]:
    _actor(principal)
    return {"items": [{"code": k, **{f: v for f, v in m.items()}} for k, m in PARAMETER_CATALOGUE.items()]}


@router.post("/knowledge/formula/validate")
def formula_validate(body: FormulaValidate, principal: Principal | None = Depends(require_principal)) -> dict[str, Any]:
    _actor(principal)
    return validate_formula(body.formula, body.params)


@router.get("/knowledge/objects")
def list_objects(type: str | None = None, status: str | None = None, q: str | None = None,
                 principal: Principal | None = Depends(require_principal), svc: KbService = Depends(kb)) -> dict[str, Any]:
    return {"items": svc.list_objects(_actor(principal), type=type, status=status, q=q)}


@router.post("/knowledge/objects", status_code=201)
def create_object(body: ObjectCreate, principal: Principal | None = Depends(require_principal), svc: KbService = Depends(kb)):
    return svc.create_object(_actor(principal), type=body.type, code=body.code, name=body.name, scope=body.scope,
                             body=body.body, reason=body.reason)


@router.get("/knowledge/objects/{object_id}")
def get_object(object_id: str, principal: Principal | None = Depends(require_principal), svc: KbService = Depends(kb)):
    return svc.get_object(_actor(principal), object_id)


@router.get("/knowledge/objects/{type_}/{code}/versions")
def versions(type_: str, code: str, principal: Principal | None = Depends(require_principal), svc: KbService = Depends(kb)):
    return {"items": svc.versions(_actor(principal), type_, code)}


@router.put("/knowledge/objects/{object_id}")
def update_object(object_id: str, body: ObjectUpdate, principal: Principal | None = Depends(require_principal),
                  svc: KbService = Depends(kb)):
    return svc.update_object(_actor(principal), object_id, name=body.name, scope=body.scope, body=body.body, reason=body.reason)


@router.post("/knowledge/objects/{object_id}/clone", status_code=201)
def clone_object(object_id: str, principal: Principal | None = Depends(require_principal), svc: KbService = Depends(kb)):
    return svc.clone_object(_actor(principal), object_id)


@router.post("/knowledge/objects/{object_id}/submit")
def submit(object_id: str, principal: Principal | None = Depends(require_principal), svc: KbService = Depends(kb)):
    return svc.submit(_actor(principal), object_id)


@router.post("/knowledge/objects/{object_id}/trial")
def trial(object_id: str, principal: Principal | None = Depends(require_principal), svc: KbService = Depends(kb)):
    return svc.start_trial(_actor(principal), object_id)


@router.post("/knowledge/objects/{object_id}/publish")
def publish(object_id: str, body: PublishBody | None = None, principal: Principal | None = Depends(require_principal),
            svc: KbService = Depends(kb)):
    return svc.publish(_actor(principal), object_id, override_reason=body.override_reason if body else None)


@router.post("/knowledge/objects/{object_id}/retire")
def retire(object_id: str, body: ReasonBody, principal: Principal | None = Depends(require_principal), svc: KbService = Depends(kb)):
    return svc.retire(_actor(principal), object_id, body.reason)


@router.post("/knowledge/objects/{object_id}/rollback")
def rollback(object_id: str, body: ReasonBody, principal: Principal | None = Depends(require_principal), svc: KbService = Depends(kb)):
    return svc.rollback(_actor(principal), object_id, body.reason)


@router.post("/knowledge/objects/{object_id}/preview")
def preview(object_id: str, body: PreviewBody | None = None, principal: Principal | None = Depends(require_principal),
            svc: KbService = Depends(kb)):
    b = body or PreviewBody()
    return svc.preview(_actor(principal), object_id, case_ids=b.case_ids, params=b.params)


@router.post("/knowledge/similar")
def similar(body: SimilarBody, principal: Principal | None = Depends(require_principal), svc: KbService = Depends(kb)):
    return {"items": svc.similar(_actor(principal), body.text, type=body.type, limit=min(body.limit, 20))}


@router.get("/knowledge/registry")
def registry(principal: Principal | None = Depends(require_principal), svc: KbService = Depends(kb)):
    return svc.registry(_actor(principal))


@router.post("/knowledge/seed")
def seed(principal: Principal | None = Depends(require_principal), svc: KbService = Depends(kb)):
    return svc.seed_demo(_actor(principal))


# ---- policy documents --------------------------------------------------------------------------
@router.get("/knowledge/documents")
def list_documents(principal: Principal | None = Depends(require_principal), svc: KbService = Depends(kb)):
    return {"items": svc.list_documents(_actor(principal))}


@router.post("/knowledge/documents", status_code=201)
def create_document(body: DocumentCreate, principal: Principal | None = Depends(require_principal), svc: KbService = Depends(kb)):
    data = body.model_dump()
    raw = data.pop("content_base64", None)
    if raw and not (data.get("text") or "").strip():
        try:
            data["text"] = extract_text(data.get("filename") or "", base64.b64decode(raw))
        except (ValueError, binascii.Error) as e:
            raise HTTPException(status_code=422, detail=f"Cannot extract text: {e}") from e
    return svc.create_document(_actor(principal), **data)


@router.post("/knowledge/documents/{document_id}/analyze")
def analyze_document(document_id: str, principal: Principal | None = Depends(require_principal),
                     svc: KbService = Depends(kb)):
    return PolicyAnalysisService(svc).analyze(_actor(principal), document_id)


# ---- proposals queue ---------------------------------------------------------------------------
@router.get("/knowledge/proposals")
def list_proposals(status: str | None = None, source: str | None = None, type: str | None = None,
                   principal: Principal | None = Depends(require_principal), svc: KbService = Depends(kb)):
    return {"items": svc.list_proposals(_actor(principal), status=status, source=source, type=type)}


@router.post("/knowledge/proposals", status_code=201)
def create_proposal(body: ProposalCreate, principal: Principal | None = Depends(require_principal), svc: KbService = Depends(kb)):
    actor = _actor(principal)
    svc._require(actor, frozenset({"analyst", "fraud_analyst", "senior_analyst", "admin"}))
    return svc.create_proposal(actor.organization_id, created_by=f"user:{actor.id}", **body.model_dump())


@router.post("/knowledge/proposals/{proposal_id}/accept")
def accept_proposal(proposal_id: str, principal: Principal | None = Depends(require_principal), svc: KbService = Depends(kb)):
    return svc.accept_proposal(_actor(principal), proposal_id)


@router.post("/knowledge/proposals/{proposal_id}/edit")
def edit_proposal(proposal_id: str, body: ProposalEdit, principal: Principal | None = Depends(require_principal),
                  svc: KbService = Depends(kb)):
    return svc.edit_proposal(_actor(principal), proposal_id, body.payload)


@router.post("/knowledge/proposals/{proposal_id}/reject")
def reject_proposal(proposal_id: str, body: ProposalReject, principal: Principal | None = Depends(require_principal),
                    svc: KbService = Depends(kb)):
    return svc.reject_proposal(_actor(principal), proposal_id, body.reason_code, body.note)


# ---- agent config ------------------------------------------------------------------------------
@router.get("/agent-config")
def get_config(scope: str = "global", principal: Principal | None = Depends(require_principal),
               svc: AgentConfigService = Depends(cfgsvc)):
    return svc.list_config(_actor(principal), scope=scope)


@router.put("/agent-config/{key}")
def set_config(key: str, body: ConfigSet, principal: Principal | None = Depends(require_principal),
               svc: AgentConfigService = Depends(cfgsvc)):
    return svc.set(_actor(principal), key, body.value, body.reason, scope=body.scope)


@router.get("/agent-config/history/list")
def config_history(key: str | None = None, principal: Principal | None = Depends(require_principal),
                   svc: AgentConfigService = Depends(cfgsvc)):
    return {"items": svc.history(_actor(principal), key=key)}


@router.post("/agent-config/history/{history_id}/revert")
def config_revert(history_id: str, body: ReasonBody, principal: Principal | None = Depends(require_principal),
                  svc: AgentConfigService = Depends(cfgsvc)):
    return svc.revert(_actor(principal), history_id, body.reason)


@router.post("/agent-config/kill-switch")
def kill_switch(body: KillSwitch, principal: Principal | None = Depends(require_principal),
                svc: AgentConfigService = Depends(cfgsvc)):
    return svc.set_kill_switch(_actor(principal), enabled=body.enabled, reason=body.reason)

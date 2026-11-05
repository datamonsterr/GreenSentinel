"""Verified case-scoped agent runtime and durable recovery transport."""

from uuid import uuid4

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from src.api.auth import Principal, require_principal
from src.models.schemas import ChatAttachment
from src.services.agent_runtime import prepare_agent_turn, read_turn_state, stream_agent_turn

router = APIRouter()


class AgentRuntimeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str = Field(min_length=1, max_length=12000)
    turn_id: str = Field(default_factory=lambda: str(uuid4()), min_length=1, max_length=200)
    event_schema_version: str = "1.1"
    attachments: list[ChatAttachment] | None = Field(default=None, max_length=3)
    reset_context: bool = False


@router.post("/cases/{case_id}/agent-runtime/stream")
async def stream(case_id: str, body: AgentRuntimeRequest, principal: Principal = Depends(require_principal)):

    from fastapi import HTTPException

    if body.event_schema_version != "1.1" or not body.query.strip():
        raise HTTPException(422, "Unsupported event schema or blank query")
    prepared = await prepare_agent_turn(principal, case_id, body.query, body.turn_id)
    return StreamingResponse(
        stream_agent_turn(
            principal,
            case_id,
            body.query,
            body.turn_id,
            prepared,
            reset_context=body.reset_context,
            attachments=body.attachments,
        ),
        media_type="text/event-stream",
    )


@router.get("/cases/{case_id}/agent-runtime/state")
async def state(case_id: str, turn_id: str | None = None, principal: Principal = Depends(require_principal)):
    import asyncio

    return await asyncio.to_thread(read_turn_state, principal, case_id, turn_id)

"""LangGraph tool boundary using trusted tool executor with actor allowlist enforcement."""

from __future__ import annotations

import inspect
import json
import logging
from uuid import uuid4

from langchain_core.messages import ToolMessage
from pydantic import ValidationError

from src.agents.tools.driver_tool_labels import get_driver_tool_label
from src.agents.tools.driver_tools import DRIVER_TOOLS
from src.models.tool_contracts import ToolExecutionContext
from src.services.tool_execution import execute_tool

logger = logging.getLogger(__name__)

# `runtime_context` on graph state carries fields the ToolNode boundary needs
# (e.g. `locale`, `on_tool_event`) that are *not* part of the trusted
# `ToolExecutionContext` contract (`extra="forbid"`). Build the context from
# only the model-declared fields so those boundary-local extras never trip
# `extra_forbidden` and silently FORBID every driver tool call before
# `execute_tool`/`_failed` ever runs (Railway preview bug, PR #603 follow-up:
# zero `tool_execution_failed` log lines for an always-FORBIDDEN call).
_TOOL_EXECUTION_CONTEXT_FIELDS = frozenset(ToolExecutionContext.model_fields)


async def execute_scoped_graph_call(request, handler):
    """LangGraph tool boundary using trusted tool executor with actor allowlist enforcement."""
    call = request.tool_call
    call_id = call.get("id") or str(uuid4())
    call_name = call.get("name", "")
    args = call.get("args", {})
    raw_ctx = dict(request.state.get("runtime_context") or {})

    roles = set(raw_ctx.get("roles") or [])
    is_analyst = bool(roles.intersection({"analyst", "senior_analyst", "admin"}))
    is_driver = ("driver" in roles) or not is_analyst
    locale = raw_ctx.get("locale", "vi")

    on_event = raw_ctx.get("on_tool_event") or request.state.get("on_tool_event")

    if is_driver:
        allowed_driver_names = {getattr(t, "name", getattr(t, "__name__", str(t))) for t in DRIVER_TOOLS}
        if call_name not in allowed_driver_names:
            error_msg = (
                f"Tool '{call_name}' is not permitted for driver accounts."
                if str(locale).lower().startswith("en")
                else f"Công cụ '{call_name}' không được phép thực thi đối với tài xế."
            )
            payload = {
                "status": "failed",
                "error": {
                    "code": "FORBIDDEN",
                    "message": error_msg,
                    "retryable": False,
                },
            }
            if callable(on_event):
                label = get_driver_tool_label(call_name, locale)
                out_start = on_event("tool.start", {"tool_call_id": call_id, "name": call_name, "label": label})
                if inspect.isawaitable(out_start):
                    await out_start
                out_end = on_event("tool.end", {"tool_call_id": call_id, "name": call_name, "status": "error"})
                if inspect.isawaitable(out_end):
                    await out_end
            return ToolMessage(
                content=json.dumps(payload, ensure_ascii=False),
                tool_call_id=call_id,
                name=call_name,
                status="error",
            )

    if callable(on_event):
        label = get_driver_tool_label(call_name, locale)
        out_start = on_event("tool.start", {"tool_call_id": call_id, "name": call_name, "label": label})
        if inspect.isawaitable(out_start):
            await out_start

    try:
        raw_ctx["tool_call_id"] = call_id
        if "roles" in raw_ctx and not isinstance(raw_ctx["roles"], frozenset):
            raw_ctx["roles"] = frozenset(raw_ctx["roles"])
        ctx_payload = {k: v for k, v in raw_ctx.items() if k in _TOOL_EXECUTION_CONTEXT_FIELDS}
        context = ToolExecutionContext.model_validate(ctx_payload)
        result = await execute_tool(call_name, args, context)
        payload = result.model_dump(mode="json")
        is_error = result.status != "succeeded"
    except ValidationError as e:
        logger.warning(
            "tool_execution_context_invalid tool=%s call_id=%s errors=%s",
            call_name,
            call_id,
            e.errors(),
        )
        payload = {
            "status": "failed",
            "error": {"code": "FORBIDDEN", "message": "Trusted case context is required", "retryable": False},
        }
        is_error = True

    if callable(on_event):
        out_end = on_event(
            "tool.end",
            {
                "tool_call_id": call_id,
                "name": call_name,
                "status": "error" if is_error else "ok",
            },
        )
        if inspect.isawaitable(out_end):
            await out_end

    return ToolMessage(
        content=json.dumps(payload, ensure_ascii=False),
        tool_call_id=call_id,
        name=call_name,
        status="error" if is_error else "success",
    )


__all__ = ["execute_scoped_graph_call"]

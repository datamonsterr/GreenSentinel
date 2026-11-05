"""Opt-in correlated tracing; never export raw case content, prompts or claims."""

import logging
import os
import sys
from contextlib import ExitStack, contextmanager
from typing import Any, Literal
from uuid import NAMESPACE_URL, uuid4, uuid5

logger = logging.getLogger(__name__)

_TRACE_METADATA_FIELDS = {
    "request_id",
    "run_id",
    "tool_call_id",
    "trace_id",
    "span_id",
    "parent_span_id",
    "service.name",
    "deployment.environment",
    "gen_ai.request.model",
    "gen_ai.prompt.version",
    "workflow.type",
}


def _enabled() -> bool:
    enabled = os.getenv("LANGSMITH_TRACING", os.getenv("LANGCHAIN_TRACING_V2", "false")).lower() == "true"
    return enabled and bool(os.getenv("LANGSMITH_API_KEY") or os.getenv("LANGCHAIN_API_KEY"))


def _trace_metadata(identity: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in identity.items() if key in _TRACE_METADATA_FIELDS and value is not None}


def make_trace_identity(
    *,
    case_id: str,
    run_id: str,
    request_id: str,
    environment: str,
    model: str,
    prompt_version: str,
    span_role: str = "agent",
) -> dict[str, str]:
    trace_id = uuid5(NAMESPACE_URL, f"greensentinel:{case_id}:{run_id}").hex
    root_span_id = uuid5(NAMESPACE_URL, f"greensentinel:{trace_id}:agent").hex[:16]
    span_id = root_span_id if span_role == "agent" else uuid5(NAMESPACE_URL, f"greensentinel:{trace_id}:{span_role}").hex[:16]
    identity = {
        "request_id": request_id,
        "run_id": run_id,
        "trace_id": trace_id,
        "span_id": span_id,
        "service.name": "greensentinel-backend",
        "deployment.environment": environment,
        "gen_ai.request.model": model,
        "gen_ai.prompt.version": prompt_version,
        "workflow.type": "analyst_cockpit",
    }
    if span_role != "agent":
        identity["parent_span_id"] = root_span_id
        identity["request_id"] = str(uuid4())
    return identity


@contextmanager
def _trace_scope(identity: dict[str, Any], *, name: str, run_type: Literal["chain", "tool"]):
    if not _enabled():
        yield None
        return

    stack = ExitStack()
    client = None
    try:
        from langsmith import Client, trace, tracing_context

        client = Client(
            api_key=os.getenv("LANGSMITH_API_KEY") or os.getenv("LANGCHAIN_API_KEY"),
            hide_inputs=True,
            hide_outputs=True,
        )
        stack.enter_context(
            tracing_context(
                enabled=True,
                client=client,
                project_name=os.getenv("LANGSMITH_PROJECT", os.getenv("LANGCHAIN_PROJECT", "greensentinel-agent-runtime")),
            )
        )
        run = stack.enter_context(
            trace(
                name=name,
                run_type=run_type,
                inputs={},
                metadata=_trace_metadata(identity),
                client=client,
            )
        )
    except Exception as exc:
        _close_trace_stack(stack)
        logger.warning("LangSmith trace could not start; continuing without tracing (%s)", type(exc).__name__)
        yield None
        return

    try:
        yield run
    except BaseException:
        try:
            stack.__exit__(*sys.exc_info())
        except Exception as exc:
            logger.warning("LangSmith trace could not close after application error (%s)", type(exc).__name__)
        raise
    else:
        _close_trace_stack(stack)
    finally:
        if client is not None:
            try:
                client.flush()
            except Exception as exc:
                logger.warning("LangSmith trace flush failed; application result is unchanged (%s)", type(exc).__name__)


def _close_trace_stack(stack: ExitStack) -> None:
    try:
        stack.close()
    except Exception as exc:
        logger.warning("LangSmith trace could not close (%s)", type(exc).__name__)


@contextmanager
def trace_turn(identity: dict[str, Any], *, name: str = "case-agent-runtime"):
    with _trace_scope(identity, name=name, run_type="chain") as run:
        yield run


@contextmanager
def trace_tool(identity: dict[str, Any], name: str):
    with _trace_scope(identity, name=f"agent.tool.{name}", run_type="tool") as run:
        yield run


@contextmanager
def trace_decision(identity: dict[str, Any]):
    with _trace_scope(identity, name="human.case-decision", run_type="chain") as run:
        yield run


def end_trace(run: Any, *, outputs: dict[str, Any] | None = None, error: str | None = None) -> None:
    if run is None:
        return
    try:
        run.end(outputs=outputs, error=error)
    except Exception as exc:
        logger.warning("LangSmith trace update failed; application result is unchanged (%s)", type(exc).__name__)


def record_decision_trace(identity: dict[str, Any]) -> None:
    with trace_decision(identity) as run:
        end_trace(run, outputs={"decision_recorded": True})

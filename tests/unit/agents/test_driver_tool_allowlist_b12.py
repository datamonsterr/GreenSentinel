"""TDD RED: B12 Security - Driver Tool Allowlist enforcement in execute_scoped_graph_call."""

import json
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage, ToolMessage
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode

from src.agents.state import AgentState
from src.agents.tools.driver_tools import DRIVER_TOOLS
from src.agents.tools.runtime_boundary import execute_scoped_graph_call
from src.models.tool_contracts import ToolExecutionContext


def _driver_context(driver_id: str = "drv-test-001") -> ToolExecutionContext:
    return ToolExecutionContext(
        actor_id=driver_id,
        organization_id="018f2f4e-0000-7000-8000-000000000001",
        roles=frozenset({"driver"}),
        case_id=None,
        driver_id=driver_id,
        request_id=str(uuid4()),
        run_id=str(uuid4()),
        tool_call_id=str(uuid4()),
        turn_id=str(uuid4()),
    )


def _driver_tool_graph():
    graph = StateGraph(AgentState)
    graph.add_node("tools", ToolNode(DRIVER_TOOLS, awrap_tool_call=execute_scoped_graph_call))
    graph.add_edge(START, "tools")
    graph.add_edge("tools", END)
    return graph.compile()


@pytest.mark.asyncio
async def test_analyst_only_tool_refused_for_driver_actor():
    """B12: execute_scoped_graph_call must reject any tool not in DRIVER_TOOLS when actor is a driver.

    Must return a ToolMessage error (status='error', JSON error envelope with natural-language message).
    """
    ctx = _driver_context()
    node = _driver_tool_graph()
    call_id = f"call_{uuid4()}"

    # 'list_cases' is an analyst-only tool, not in DRIVER_TOOLS
    result = await node.ainvoke(
        {
            "runtime_context": ctx.model_dump(mode="json"),
            "messages": [
                AIMessage(
                    content="",
                    tool_calls=[{"id": call_id, "name": "list_cases", "args": {}}],
                )
            ],
        }
    )

    tool_messages = [m for m in result["messages"] if isinstance(m, ToolMessage)]
    assert len(tool_messages) == 1
    msg = tool_messages[0]
    assert msg.tool_call_id == call_id
    assert msg.status == "error"
    payload = json.loads(msg.content)
    assert payload["status"] == "failed"
    assert payload["error"]["code"] == "FORBIDDEN"
    assert payload["error"]["retryable"] is False
    err_text = payload["error"]["message"].lower()
    assert "not" in err_text or "chưa" in err_text or "không" in err_text


@pytest.mark.asyncio
async def test_unregistered_analyst_tool_refused_without_executing():
    """B12: Any tool name not in DRIVER_TOOLS is refused."""
    ctx = _driver_context()
    node = _driver_tool_graph()
    call_id = f"call_{uuid4()}"

    result = await node.ainvoke(
        {
            "runtime_context": ctx.model_dump(mode="json"),
            "messages": [
                AIMessage(
                    content="",
                    tool_calls=[{"id": call_id, "name": "get_forensic_brief_unscoped", "args": {"case_id": "c1"}}],
                )
            ],
        }
    )

    tool_messages = [m for m in result["messages"] if isinstance(m, ToolMessage)]
    assert len(tool_messages) == 1
    msg = tool_messages[0]
    assert msg.status == "error"
    payload = json.loads(msg.content)
    assert payload["status"] == "failed"
    assert payload["error"]["code"] == "FORBIDDEN"


@pytest.mark.asyncio
async def test_allowed_driver_tool_still_runs():
    """B12: An allowed tool in DRIVER_TOOLS (e.g. list_my_cases) still runs successfully."""
    ctx = _driver_context()
    node = _driver_tool_graph()
    call_id = f"call_{uuid4()}"

    result = await node.ainvoke(
        {
            "runtime_context": ctx.model_dump(mode="json"),
            "messages": [
                AIMessage(
                    content="",
                    tool_calls=[{"id": call_id, "name": "list_my_cases", "args": {}}],
                )
            ],
        }
    )

    tool_messages = [m for m in result["messages"] if isinstance(m, ToolMessage)]
    assert len(tool_messages) == 1
    msg = tool_messages[0]
    # Allowed tool produces valid result payload and status is not error
    assert msg.status != "error"
    payload = json.loads(msg.content)
    assert payload["status"] == "succeeded"

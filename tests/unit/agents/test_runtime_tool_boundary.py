"""Real graph invocation honors trusted case scope rather than model identity."""

import json

import pytest
from dotenv import load_dotenv
from langchain_core.messages import AIMessage
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode

from src.agents.state import AgentState
from src.agents.tools.analyst_tools import ANALYST_TOOLS
from src.agents.tools.runtime_boundary import execute_scoped_graph_call
from tests.integration.services.test_canonical_tool_execution import context


def tool_graph():
    graph = StateGraph(AgentState)
    graph.add_node("tools", ToolNode(ANALYST_TOOLS, awrap_tool_call=execute_scoped_graph_call))
    graph.add_edge(START, "tools")
    graph.add_edge("tools", END)
    return graph.compile()


@pytest.mark.asyncio
async def test_graph_tool_cannot_run_without_runtime_authority():
    node = tool_graph()
    result = await node.ainvoke(
        {
            "messages": [
                AIMessage(
                    content="",
                    tool_calls=[{"id": "call1", "name": "get_case_detail", "args": {"case_id": context().case_id}}],
                )
            ]
        }
    )
    payload = json.loads(result["messages"][-1].content)
    assert payload["error"]["code"] == "FORBIDDEN"


@pytest.mark.asyncio
async def test_graph_actual_lookup_uses_canonical_scoped_executor():
    from tests.integration.services.test_canonical_tool_execution import _is_db_available

    if not _is_db_available():
        pytest.skip("PostgreSQL database with app.fraud_cases schema not available")
    load_dotenv(".env", override=False)
    ctx = context()
    node = tool_graph()
    result = await node.ainvoke(
        {
            "runtime_context": ctx.model_dump(mode="json"),
            "messages": [
                AIMessage(
                    content="",
                    tool_calls=[{"id": "call1", "name": "get_case_detail", "args": {"case_id": ctx.case_id}}],
                )
            ],
        }
    )
    payload = json.loads(result["messages"][-1].content)
    assert payload["status"] == "succeeded"
    assert payload["data"]["case_id"] == ctx.case_id
    assert payload["tool_call_id"] == "call1"

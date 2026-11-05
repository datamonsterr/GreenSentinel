"""TDD: case-less driver tool execution must not be rejected as FORBIDDEN.

Review finding (PR #538 on Issue #482): `ToolExecutionContext.case_id` was a
required `str`, so `runtime_context={"case_id": None, ...}` (case-less
GSupport chat) failed Pydantic validation in `execute_scoped_graph_call`
before `_scope`'s already-written driver-stub branch (no case bound) could
ever run, and every tool call silently became FORBIDDEN.
"""

import json
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode

from src.agents.state import AgentState
from src.agents.tools.driver_tools import DRIVER_TOOLS
from src.agents.tools.runtime_boundary import execute_scoped_graph_call
from src.models.tool_contracts import ToolExecutionContext
from src.services.tool_execution import execute_tool


def _caseless_context(driver_id: str = "drv-caseless-001") -> ToolExecutionContext:
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


def test_tool_execution_context_accepts_case_id_none():
    """Case-less chat has no case_id yet; the model must not require one."""
    ctx = _caseless_context()
    assert ctx.case_id is None


@pytest.mark.asyncio
async def test_list_my_cases_via_execute_tool_with_caseless_context():
    ctx = _caseless_context()
    result = await execute_tool("list_my_cases", {}, ctx)
    assert result.status == "succeeded", result.error
    assert result.error is None


@pytest.mark.asyncio
async def test_list_my_cases_tolerates_model_supplied_null_optional_arg():
    """Bug (PR #603 Railway preview): LLMs commonly fill unset optional JSON
    schema args with `null` rather than omitting them. `status` is optional
    and typed `string`; a model-supplied `null` must not VALIDATION_ERROR a
    caseless driver out of `list_my_cases`.
    """
    ctx = _caseless_context()
    result = await execute_tool("list_my_cases", {"status": None}, ctx)
    assert result.status == "succeeded", result.error
    assert result.error is None


@pytest.mark.asyncio
async def test_query_driver_policy_caseless_returns_policy_guidance_not_failure():
    """Bug (PR #603 Railway preview): a caseless driver asking a general
    policy FAQ ("Dieu 12.2 quy dinh gi ve ket xe?") must get policy guidance,
    not a tool failure. `query_driver_policy` is a surface alias of the
    catalog's `search_policy_documents` entry, but execute_tool's dispatch
    unconditionally routed every caller through the analyst case-scoped
    lookup (`build_case_context`), which requires a real case_id and raises
    for a caseless driver.
    """
    ctx = _caseless_context()
    result = await execute_tool("query_driver_policy", {"query": "Dieu 12.2 quy dinh gi ve ket xe?"}, ctx)
    assert result.status == "succeeded", result.error
    assert result.error is None
    assert result.data.get("results")


def _driver_tool_graph():
    graph = StateGraph(AgentState)
    graph.add_node("tools", ToolNode(DRIVER_TOOLS, awrap_tool_call=execute_scoped_graph_call))
    graph.add_edge(START, "tools")
    graph.add_edge("tools", END)
    return graph.compile()


@pytest.mark.asyncio
async def test_driver_graph_cannot_invoke_analyst_only_tool():
    """Risk #12 (PR #538): even if a model-selectable analyst-only tool name
    were requested through the driver graph's ToolNode, `execute_tool`'s
    actor check (not just ToolNode registration) must still reject it.
    """
    ctx = _caseless_context()
    node = _driver_tool_graph()
    result = await node.ainvoke(
        {
            "runtime_context": ctx.model_dump(mode="json"),
            "messages": [
                AIMessage(
                    content="",
                    tool_calls=[{"id": "call1", "name": "list_cases", "args": {}}],
                )
            ],
        }
    )
    last_msg = result["messages"][-1]
    assert getattr(last_msg, "status", None) == "error"
    assert "không" in last_msg.content.lower() or "not" in last_msg.content.lower()


@pytest.mark.asyncio
async def test_list_my_cases_via_execute_scoped_graph_call_with_caseless_context():
    ctx = _caseless_context()
    node = _driver_tool_graph()
    result = await node.ainvoke(
        {
            "runtime_context": ctx.model_dump(mode="json"),
            "messages": [
                AIMessage(
                    content="",
                    tool_calls=[{"id": "call1", "name": "list_my_cases", "args": {}}],
                )
            ],
        }
    )
    payload = json.loads(result["messages"][-1].content)
    assert payload["status"] == "succeeded", payload
    assert payload.get("error") is None


@pytest.mark.asyncio
async def test_list_my_cases_tolerates_boundary_local_runtime_context_extras():
    """Bug (Railway preview, PR #603 follow-up): `run_driver_support_agent`

    puts boundary-local keys (`locale`, `on_tool_event`) directly on the
    `runtime_context` dict for `execute_scoped_graph_call`'s own use. Those
    keys are not part of the trusted `ToolExecutionContext` contract
    (`extra="forbid"`) and must never be forwarded into
    `ToolExecutionContext.model_validate`, or every single driver tool call
    FORBIDs before `execute_tool` ever runs (no `tool_execution_failed` log).
    """
    ctx = _caseless_context()
    node = _driver_tool_graph()
    raw_runtime_context = {
        **ctx.model_dump(mode="json"),
        "locale": "vi",
        "on_tool_event": None,
    }
    result = await node.ainvoke(
        {
            "runtime_context": raw_runtime_context,
            "messages": [
                AIMessage(
                    content="",
                    tool_calls=[{"id": "call1", "name": "list_my_cases", "args": {}}],
                )
            ],
        }
    )
    payload = json.loads(result["messages"][-1].content)
    assert payload["status"] == "succeeded", payload
    assert payload.get("error") is None

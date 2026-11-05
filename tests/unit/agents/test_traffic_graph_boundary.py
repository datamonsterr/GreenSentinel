"""Real graph/tool boundary with only storage and HTTP replaced."""

import json
from types import SimpleNamespace

import httpx
import pytest
from langchain_core.messages import AIMessage
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode

from src.agents.state import AgentState
from src.agents.tools.analyst_tools import ANALYST_TOOLS
from src.agents.tools.driver_tools import DRIVER_TOOLS
from src.agents.tools.runtime_boundary import execute_scoped_graph_call
from src.models.tool_contracts import ToolExecutionContext
from src.services import tool_execution, traffic_evidence_service


@pytest.mark.parametrize("role,tools", [("analyst", ANALYST_TOOLS), ("driver", DRIVER_TOOLS)])
async def test_graph_traffic_calls_use_scoped_peer_telemetry_and_normalized_http(monkeypatch, role, tools):
    context = ToolExecutionContext(
        actor_id="actor",
        organization_id="org",
        roles=frozenset({role}),
        case_id="case",
        driver_id="driver",
        request_id="request",
        run_id="run",
        turn_id="turn",
        tool_call_id="placeholder",
    )

    def rows(query, params):
        if "FROM app.fraud_cases" in query:
            assert params == ("case", "org")
            return [
                {
                    "assignment_id": "00000000-0000-0000-0000-000000000001",
                    "assigned_analyst_id": "actor",
                    "principal_id": "actor",
                    "driver_id": "driver",
                }
            ]
        if "min(tp.occurred_at)" in query:
            assert params == ("00000000-0000-0000-0000-000000000001",)
            return [
                {
                    "window_start": "2026-10-11T10:00:00Z",
                    "window_end": "2026-10-11T10:30:00Z",
                    "west": 105.7,
                    "south": 21.0,
                    "east": 105.8,
                    "north": 21.1,
                }
            ]
        assert "t.organization_id=%s::uuid" in query
        assert params[0] == "org"
        return [
            {"assignment_id": "peer-1", "median_speed_kmh": 20},
            {"assignment_id": "peer-2", "median_speed_kmh": 20},
            {"assignment_id": "peer-3", "median_speed_kmh": 50},
        ]

    monkeypatch.setattr(tool_execution, "_rows", rows)
    monkeypatch.setattr(
        traffic_evidence_service,
        "get_settings",
        lambda: SimpleNamespace(
            traffic_incidents_url="https://traffic.test/incidents",
            traffic_api_key="",
            traffic_timeout_seconds=1,
        ),
    )
    requested = []

    def provider(request):
        requested.append(request.url.path)
        return httpx.Response(200, json={"incidents": []})

    original_client = httpx.AsyncClient
    monkeypatch.setattr(
        traffic_evidence_service.httpx,
        "AsyncClient",
        lambda **kwargs: original_client(transport=httpx.MockTransport(provider), **kwargs),
    )
    graph = StateGraph(AgentState)
    graph.add_node("tools", ToolNode(tools, awrap_tool_call=execute_scoped_graph_call))
    graph.add_edge(START, "tools")
    graph.add_edge("tools", END)
    arguments = {
        "case_id": "case",
        "bbox": [105.7, 21, 105.8, 21.1],
        "start_time": "2026-10-11T10:00:00Z",
        "end_time": "2026-10-11T10:30:00Z",
    }
    result = await graph.compile().ainvoke(
        {
            "runtime_context": context.model_dump(mode="json"),
            "messages": [
                AIMessage(
                    content="",
                    tool_calls=[
                        {"id": "history", "name": "fetch_corridor_historical_traffic", "args": arguments},
                        {"id": "incidents", "name": "query_traffic_incident_feed", "args": arguments},
                    ],
                )
            ],
        }
    )
    evidence = [json.loads(message.content) for message in result["messages"][-2:]]
    assert [item["status"] for item in evidence] == ["succeeded", "succeeded"]
    assert evidence[0]["data"]["source_type"] == "first_party_peer_telemetry"
    assert evidence[0]["data"]["peer_count"] == 3
    assert evidence[1]["data"]["incidents"] == []
    assert [item["tool_call_id"] for item in evidence] == ["history", "incidents"]
    assert requested == ["/incidents"]

"""Regression coverage for long-trip tool results and bounded Copilot context."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from google.genai import types
from openai import BadRequestError

from src.models.tool_contracts import ToolExecutionContext
from src.services import agent_runtime, tool_execution


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "tool,collection", [("inspect_trip_telemetry", "points"), ("get_trip_lifecycle_evidence", "events")]
)
async def test_long_trip_tool_is_bounded_and_reports_measured_counts(monkeypatch, tool, collection):
    async def inline_database_call(function, *args):
        return function(*args)

    monkeypatch.setattr(tool_execution.asyncio, "to_thread", inline_database_call)
    rows = [
        {
            "event_id": str(i),
            "id": str(i),
            "occurred_at": f"2026-01-01T00:{i // 60:02d}:{i % 60:02d}Z",
            "speed_mps": float(i % 20),
            "mock_location_reported": i == 17,
            "event_type": "location_recorded",
            "payload": {"raw": "x" * 2000},
            "_total_samples": 1200,
            "_min_speed_mps": 0.0,
            "_max_speed_mps": 19.0,
            "_mock_count": 1,
            "_window_start": "2026-01-01T00:00:00Z",
            "_window_end": "2026-01-01T00:19:59Z",
        }
        for i in range(1200)
    ]
    monkeypatch.setattr(tool_execution, "_scope", lambda _: {"assignment_id": "assignment"})
    monkeypatch.setattr(tool_execution, "_rows", lambda *_: rows)
    context = ToolExecutionContext(
        actor_id="actor",
        organization_id="org",
        roles={"analyst"},
        case_id="case",
        driver_id="driver",
        request_id="request",
        run_id="run",
        tool_call_id="call",
        turn_id="turn",
    )
    result = await tool_execution.execute_tool(tool, {}, context)
    repeated = await tool_execution.execute_tool(tool, {}, context)
    assert result.status == "succeeded"
    assert len(json.dumps(result.model_dump(mode="json"), ensure_ascii=False)) <= 20000
    assert result.data == repeated.data
    assert result.data["truncated"] is True
    assert result.data["total_samples"] == 1200
    assert result.data["returned_samples"] == len(result.data[collection])
    assert 0 < len(result.data[collection]) < 1200
    assert result.data[collection][0]["id"] == "0"
    assert result.data[collection][-1]["id"] == "1199"
    if collection == "points":
        assert result.data["summary"]["point_count"] == 1200
        assert result.data["summary"]["max_speed_mps"] == 19.0
        assert result.data["summary"]["mock_location_reported_count"] == 1
    else:
        assert result.data["summary"]["event_count"] == 1200


@pytest.mark.asyncio
async def test_provider_trims_old_history_and_bounds_tool_results_without_orphans(monkeypatch):
    monkeypatch.setattr(agent_runtime, "get_settings", lambda: SimpleNamespace(agent_context_window=128000))
    messages = []
    for i in range(30):
        messages.extend(
            [
                types.Content(role="user", parts=[types.Part.from_text(text=f"old {i}" + "界" * 6000)]),
                types.Content(role="model", parts=[types.Part.from_text(text="old answer" * 2000)]),
            ]
        )
    messages.extend(
        [
            types.Content(role="user", parts=[types.Part.from_text(text="current question")]),
            types.Content(role="model", parts=[types.Part.from_function_call(name="large_tool", args={})]),
            types.Content(
                role="user",
                parts=[types.Part.from_function_response(name="large_tool", response={"raw": "x" * 500000})],
            ),
        ]
    )
    received = []

    async def provider(contents, declarations, system):
        received.extend(contents)
        serialized = json.dumps([c.model_dump(mode="json", exclude_none=True) for c in contents], ensure_ascii=False)
        assert len(serialized.encode()) + len(system.encode()) + len(json.dumps(declarations).encode()) < 118000
        return "ok"

    monkeypatch.setattr(agent_runtime, "_provider_once", provider)
    assert await agent_runtime._provider(messages, [], "system") == "ok"
    assert any(p.text == "current question" for c in received for p in c.parts)
    assert not any(p.text and p.text.startswith("old 0") for c in received for p in c.parts)
    assert received[-2].parts[0].function_call.name == "large_tool"
    assert received[-1].parts[0].function_response.response["truncated"] is True


@pytest.mark.asyncio
async def test_oversize_current_query_is_rejected_before_provider_call(monkeypatch):
    monkeypatch.setattr(agent_runtime, "get_settings", lambda: SimpleNamespace(agent_context_window=128000))
    provider = AsyncMock()
    monkeypatch.setattr(agent_runtime, "_provider_once", provider)
    contents = [types.Content(role="user", parts=[types.Part.from_text(text="x" * 200000)])]
    with pytest.raises(Exception) as caught:
        await agent_runtime._provider(contents, [], "system")
    provider.assert_not_called()
    code, message, retryable = agent_runtime._diagnose_failure(caught.value)
    assert code == "CONTEXT_LENGTH_EXCEEDED"
    assert "ngữ cảnh" in message
    assert retryable is False


def test_openai_context_overflow_has_actionable_safe_error():
    error = BadRequestError(
        "private raw provider message",
        response=httpx.Response(400, request=httpx.Request("POST", "https://example.test")),
        body={"code": "context_length_exceeded"},
    )
    code, message, retryable = agent_runtime._diagnose_failure(error)
    assert code == "CONTEXT_LENGTH_EXCEEDED"
    assert "ngữ cảnh" in message
    assert "private" not in message
    assert retryable is False

from types import SimpleNamespace
from uuid import UUID

import pytest

from src.models.schemas import PolicyChatRequest, StructuredCockpitResponse
from src.services.case_service import CaseService

pytestmark = pytest.mark.docker


@pytest.mark.asyncio
async def test_policy_stream_persists_final_reply_and_emits_compact_statuses(monkeypatch):
    saved: list[tuple[str, str, str]] = []
    history = [{"role": "user", "content": "Earlier question"}, {"role": "assistant", "content": "Earlier answer"}]

    def begin_turn(_req, _organization_id, _actor_id):
        return {"session_id": "session-1", "driver_id": "driver-1", "history": history}

    def append_reply(session_id, turn_id, content):
        saved.append((session_id, turn_id, content))

    class Agent:
        def execute_turn(self, **kwargs):
            assert kwargs["conversation_history"][-1]["content"] == "Earlier answer"
            kwargs["on_tool_call"]("search_policy_documents")
            return SimpleNamespace(answer="Policy-backed reply", citations=[], status="success")

    monkeypatch.setattr(CaseService, "_begin_case_agent_turn", staticmethod(begin_turn))
    monkeypatch.setattr(CaseService, "_append_case_agent_reply", staticmethod(append_reply))
    monkeypatch.setattr("src.rag.cockpit_agent.CockpitRAGAgent", Agent)
    service = CaseService.__new__(CaseService)
    turn_id = UUID("018f2f4e-a000-7000-8000-000000000010")
    req = PolicyChatRequest(
        query="What rule applies?", case_id=UUID("018f2f4e-a000-7000-8000-000000000001"), turn_id=turn_id
    )

    events = [event async for event in service.stream_policy_chat(req, "org-1", "analyst-1")]
    event_names = [event.split("\n", 1)[0] for event in events]

    assert event_names[0] == "event: session"
    assert event_names.index("event: thinking") < event_names.index("event: tool_call")
    assert event_names.index("event: tool_call") < event_names.index("event: tool_done")
    assert (
        event_names.index("event: tool_done")
        < event_names.index("event: text_delta")
        < event_names.index("event: done")
    )
    assert "reasoning" not in "".join(events)
    assert "thought_process" not in "".join(events)
    assert saved == [("session-1", str(turn_id), "Policy-backed reply")]


@pytest.mark.asyncio
async def test_policy_stream_replays_saved_answer_without_reexecuting_agent(monkeypatch):
    class Agent:
        def execute_turn(self, **_kwargs):
            raise AssertionError("saved turn must not execute twice")

    monkeypatch.setattr(
        CaseService,
        "_begin_case_agent_turn",
        staticmethod(
            lambda *_: {
                "session_id": "session-1",
                "history": [],
                "existing_answer": "Saved answer",
            }
        ),
    )
    monkeypatch.setattr("src.rag.cockpit_agent.CockpitRAGAgent", Agent)
    service = CaseService.__new__(CaseService)
    req = PolicyChatRequest(query="Retry", case_id=UUID("018f2f4e-a000-7000-8000-000000000001"))

    events = [event async for event in service.stream_policy_chat(req)]

    assert any('"delta": "Saved answer"' in event for event in events)
    assert events[-1].startswith("event: done")
    assert not any(event.startswith("event: tool_call") for event in events)


@pytest.mark.asyncio
async def test_database_tool_result_is_observed_before_final_reply_is_persisted(monkeypatch):
    saved: list[str] = []
    recorded_metrics: list[dict] = []

    class Agent:
        def __init__(self):
            self.input_tokens = 5
            self.output_tokens = 2

        def execute_turn(self, **kwargs):
            kwargs["on_tool_call"]("get_telemetry")
            return StructuredCockpitResponse(
                display_format="composite",
                answer="Retrieved 4 GPS points.",
                tool_called="get_telemetry",
                status="success",
            )

        def continue_from_tool_result(self, *, question, tool_answer, conversation_history):
            assert question == "Summarize this trip"
            assert tool_answer == "Retrieved 4 GPS points."
            assert conversation_history[-1]["content"] == question
            self.input_tokens += 7
            self.output_tokens += 3
            return "The trip has 4 recorded GPS points."

    monkeypatch.setattr(
        CaseService,
        "_begin_case_agent_turn",
        staticmethod(
            lambda *_: {
                "session_id": "session-2",
                "driver_id": "driver-1",
                "history": [{"role": "user", "content": "Summarize this trip"}],
            }
        ),
    )
    monkeypatch.setattr(
        CaseService, "_append_case_agent_reply", staticmethod(lambda _sid, _tid, text: saved.append(text))
    )
    monkeypatch.setattr("src.rag.cockpit_agent.CockpitRAGAgent", Agent)
    monkeypatch.setattr(
        "src.services.observability_metrics.record_run",
        lambda **values: recorded_metrics.append(values),
    )
    service = CaseService.__new__(CaseService)
    req = PolicyChatRequest(
        query="Summarize this trip",
        case_id=UUID("018f2f4e-a000-7000-8000-000000000001"),
    )

    events = [event async for event in service.stream_policy_chat(req)]
    names = [event.split("\n", 1)[0] for event in events]

    final_thinking = len(names) - 1 - names[::-1].index("event: thinking")
    assert names.index("event: tool_done") < final_thinking
    assert final_thinking < names.index("event: text_delta")
    assert saved == ["The trip has 4 recorded GPS points."]
    assert len(recorded_metrics) == 1
    assert recorded_metrics[0]["input_tokens"] == 12
    assert recorded_metrics[0]["output_tokens"] == 5
    assert recorded_metrics[0]["status"] == "completed"

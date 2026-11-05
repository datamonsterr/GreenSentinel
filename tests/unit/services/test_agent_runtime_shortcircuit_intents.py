"""Short-circuit intents must complete without entering the tool loop.

Regression: CONVERSATIONAL, OUT_OF_SCOPE and ADVERSARIAL_ATTACK turns skip the
tool loop, but the final traffic guard read ``tool_result_cache`` which only the
tool loop assigned. Every greeting failed with ``UnboundLocalError`` and the
analyst saw "Không thể hoàn tất yêu cầu trợ lý".
"""

import json
from contextlib import nullcontext
from types import SimpleNamespace

import pytest

from src.services import agent_runtime
from src.services.copilot_decision_service import CopilotDecisionResult, CopilotIntent

CASE = "018f2f4e-a000-7000-8000-000000000068"


def _events(frames: list[str]) -> list[dict]:
    return [json.loads(line[6:]) for frame in frames for line in frame.splitlines() if line.startswith("data: ")]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "intent",
    [CopilotIntent.CONVERSATIONAL, CopilotIntent.OUT_OF_SCOPE, CopilotIntent.ADVERSARIAL_ATTACK],
)
async def test_short_circuit_intent_completes_turn(monkeypatch, intent):
    finished: list[tuple[str, str]] = []

    class Decision:
        async def decide_intent(self, query, **_):
            return CopilotDecisionResult(intent=intent, is_in_scope=True, needs_case_dossier=False)

    async def reply(query: str) -> str:
        return "Xin chào, tôi có thể hỗ trợ gì cho vụ việc này?"

    monkeypatch.setattr(agent_runtime, "authorize_case", lambda *_: {"driver_id": "driver-1"})
    monkeypatch.setattr(
        agent_runtime, "_finish", lambda run_id, writer, answer, status: finished.append((answer, status))
    )
    monkeypatch.setattr(agent_runtime, "_generate_conversational_reply", reply)
    monkeypatch.setattr(agent_runtime, "_generate_dynamic_refusal", reply)
    monkeypatch.setattr(agent_runtime, "get_settings", lambda: SimpleNamespace(agent_context_window=128000))
    monkeypatch.setattr("src.services.copilot_decision_service.get_copilot_decision_service", lambda: Decision())
    monkeypatch.setattr("src.services.agent_workflow_service.get_agent_workflow_service", lambda: object())
    monkeypatch.setattr("src.services.agent_tracing.trace_turn", lambda _identity: nullcontext())

    principal = SimpleNamespace(id="analyst-1", organization_id="org-1", roles=frozenset({"analyst"}))
    row = {"session_id": "session-1", "run_id": "run-1", "events": []}
    frames = [
        frame
        async for frame in agent_runtime.stream_agent_turn(principal, CASE, "xin chào", "turn-1", prepared=(row, True))
    ]

    types_seen = [event["type"] for event in _events(frames)]
    assert "run.error" not in types_seen
    assert types_seen[-1] == "run.completed"
    assert "text.delta" in types_seen
    assert finished and finished[0][1] == "completed"

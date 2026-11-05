"""Integration tests for agent runtime SSE events: suggestions, usage, stable citations, and formatted markdown."""

import json
from typing import Any
from uuid import uuid4

import pytest
from dotenv import load_dotenv
from google.genai import types
from httpx import ASGITransport, AsyncClient

from src.api.auth import Principal, require_principal
from src.config import get_settings
from src.main import app
from src.services.agent_runtime import _connection

CASE = "018f2f4e-a000-7000-8000-000000000001"
OWNER = "018f2f4e-1000-7000-8000-000000000001"
ORG = "018f2f4e-0000-7000-8000-000000000001"


def _is_db_available() -> bool:
    try:
        with _connection() as conn, conn.cursor() as cur:
            cur.execute("SELECT 1 FROM app.fraud_cases LIMIT 1;")
            return True
    except Exception:
        return False


@pytest.mark.asyncio
async def test_agent_runtime_emits_suggestions_usage_and_formatted_text(monkeypatch):
    if not _is_db_available():
        pytest.skip("PostgreSQL database not available")

    load_dotenv(".env", override=False)
    monkeypatch.setenv("GEMINI_API_KEY", "fixture-provider-key")
    get_settings.cache_clear()

    actor = Principal(OWNER, ORG, frozenset({"analyst"}))
    app.dependency_overrides[require_principal] = lambda: actor

    model_calls = 0

    async def model_boundary(*args: Any, **kwargs: Any) -> Any:
        nonlocal model_calls
        model_calls += 1
        # Call 1: Agent main turn producing raw answer
        # Call 2: Formatter producing JSON formatted answer + suggestions
        if model_calls == 1:
            raw_text = (
                "Đã đối chiếu thông tin vụ việc 018f2f4e-a000-7000-8000-000000000001. "
                "Tài xế có dấu hiệu vi phạm theo quy định Điều 14.1."
            )
            return types.GenerateContentResponse(
                candidates=[
                    types.Candidate(content=types.Content(role="model", parts=[types.Part.from_text(text=raw_text)]))
                ]
            )
        else:
            # Formatter response
            formatted_json = json.dumps(
                {
                    "markdown": "**Xác nhận dấu hiệu vi phạm theo Điều 14.1.**\n\nĐối chiếu [Vụ việc](case://018f2f4e-a000-7000-8000-000000000001) thành công.",
                    "suggestions": [
                        {"label": "Xem lịch sử tài xế", "prompt": "Xem lịch sử vi phạm"},
                        {"label": "Lập biên bản", "prompt": "Dự thảo biên bản xử lý"},
                    ],
                },
                ensure_ascii=False,
            )
            return types.GenerateContentResponse(
                candidates=[
                    types.Candidate(
                        content=types.Content(role="model", parts=[types.Part.from_text(text=formatted_json)])
                    )
                ]
            )

    monkeypatch.setattr("google.genai.models.AsyncModels.generate_content", model_boundary)

    tid = str(uuid4())
    payload = {"query": "Tóm tắt vụ việc", "turn_id": tid, "event_schema_version": "1.1"}

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            res = await c.post(f"/api/v1/cases/{CASE}/agent-runtime/stream", json=payload)
            assert res.status_code == 200
            raw_stream = res.text

            # Parse SSE events
            events = []
            for block in raw_stream.strip().split("\n\n"):
                for line in block.splitlines():
                    if line.startswith("data: "):
                        data = json.loads(line[6:])
                        events.append(data)

            types_seen = [e["type"] for e in events]
            assert "text.delta" in types_seen
            assert "suggestions" in types_seen
            assert "usage" in types_seen
            assert "run.completed" in types_seen

            # Verify suggestions order: emitted once before run.completed
            sugg_idx = types_seen.index("suggestions")
            usage_idx = types_seen.index("usage")
            comp_idx = types_seen.index("run.completed")
            assert sugg_idx < comp_idx
            assert usage_idx < comp_idx

            # Verify suggestions payload
            sugg_event = next(e for e in events if e["type"] == "suggestions")
            items = sugg_event["payload"]["items"]
            assert len(items) == 2
            assert items[0]["label"] == "Xem lịch sử tài xế"
            assert items[0]["prompt"] == "Xem lịch sử vi phạm"

            # Verify usage payload
            usage_event = next(e for e in events if e["type"] == "usage")
            usage_p = usage_event["payload"]
            assert "prompt_tokens" in usage_p
            assert "completion_tokens" in usage_p
            assert "total_tokens" in usage_p
            assert "context_window" in usage_p
            assert "breakdown" in usage_p
            bd = usage_p["breakdown"]
            assert "system" in bd
            assert "dossier" in bd
            assert "history" in bd
            assert "tool_results" in bd
            assert "query" in bd

            # Verify formatted markdown carried in text.delta
            deltas = [e["payload"]["delta"] for e in events if e["type"] == "text.delta"]
            reconstructed_text = "".join(deltas)
            assert "**Xác nhận dấu hiệu vi phạm theo Điều 14.1.**" in reconstructed_text
            assert "case://018f2f4e-a000-7000-8000-000000000001" in reconstructed_text

            # Verify persisted turn has formatted markdown as answer
            saved = await c.get(f"/api/v1/cases/{CASE}/agent-runtime/state", params={"turn_id": tid})
            assert saved.status_code == 200
            turn_row = saved.json()["turns"][0]
            assert "**Xác nhận dấu hiệu vi phạm theo Điều 14.1.**" in turn_row["answer"]

            # Verify replay re-emits suggestions and usage
            replay_res = await c.post(f"/api/v1/cases/{CASE}/agent-runtime/stream", json=payload)
            assert replay_res.status_code == 200
            replay_events = [
                json.loads(line[6:])
                for block in replay_res.text.strip().split("\n\n")
                for line in block.splitlines()
                if line.startswith("data: ")
            ]
            replay_types = [e["type"] for e in replay_events]
            assert "suggestions" in replay_types
            assert "usage" in replay_types
    finally:
        app.dependency_overrides.pop(require_principal, None)
        get_settings.cache_clear()


@pytest.mark.asyncio
async def test_agent_runtime_waiting_for_user_skips_formatter_and_emits_usage(monkeypatch):
    if not _is_db_available():
        pytest.skip("PostgreSQL database not available")

    load_dotenv(".env", override=False)
    monkeypatch.setenv("GEMINI_API_KEY", "fixture-provider-key")
    get_settings.cache_clear()

    actor = Principal(OWNER, ORG, frozenset({"analyst"}))
    app.dependency_overrides[require_principal] = lambda: actor

    async def mock_generate_content(*args: Any, **kwargs: Any) -> Any:
        call_part = types.Part.from_function_call(
            name="ask_interactive_question",
            args={
                "question_id_stable": f"test-q-{uuid4().hex[:8]}",
                "question_kind": "yes_no",
                "purpose": "clarification",
                "actor_target": "driver",
                "question_text": "Tài xế có xác nhận sự việc?",
            },
        )
        return types.GenerateContentResponse(
            candidates=[types.Candidate(content=types.Content(role="model", parts=[call_part]))]
        )

    monkeypatch.setattr("google.genai.models.AsyncModels.generate_content", mock_generate_content)

    formatter_called = False

    from src.services.answer_formatter import FormattedAnswer

    async def mock_format_answer(*args: Any, **kwargs: Any) -> Any:
        nonlocal formatter_called
        formatter_called = True
        return FormattedAnswer(markdown="FORMATTED SHOULD NOT BE CALLED")

    monkeypatch.setattr("src.services.agent_runtime.format_answer", mock_format_answer)

    tid = str(uuid4())
    payload = {"query": "Hỏi tài xế câu hỏi làm rõ", "turn_id": tid, "event_schema_version": "1.1"}

    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            res = await c.post(f"/api/v1/cases/{CASE}/agent-runtime/stream", json=payload)
            assert res.status_code == 200
            raw_stream = res.text

            events = []
            for block in raw_stream.strip().split("\n\n"):
                for line in block.splitlines():
                    if line.startswith("data: "):
                        events.append(json.loads(line[6:]))

            types_seen = [e["type"] for e in events]
            assert "interaction.request" in types_seen
            assert "usage" in types_seen
            assert "run.completed" in types_seen

            # 1. format_answer must be skipped
            assert formatter_called is False, "format_answer must not be called when waiting_for_user"

            # 2. Canned answer emitted
            deltas = [e["payload"]["delta"] for e in events if e["type"] == "text.delta"]
            reconstructed_text = "".join(deltas)
            assert "Vui lòng xem nội dung và gửi câu trả lời hoặc xác nhận trong ứng dụng." in reconstructed_text

            # 3. Status is waiting_for_user
            completed_event = next(e for e in events if e["type"] == "run.completed")
            assert completed_event["payload"]["status"] == "waiting_for_user"
    finally:
        app.dependency_overrides.pop(require_principal, None)
        get_settings.cache_clear()

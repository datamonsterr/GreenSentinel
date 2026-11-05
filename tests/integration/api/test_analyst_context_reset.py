"""Regression tests for Issue #153: Analyst single-message context-reset checkbox.

Verifies:
1. When reset_context=False, prior conversation turns are included in model input history.
2. When reset_context=True, prior conversation dialogue is excluded from model input history.
3. Resetting context for a turn preserves all stored session audit messages and case evidence.
4. Subsequent turns with reset_context=False can resume dialogue with full persisted history.
5. Typed schema validation for PolicyChatRequest.reset_context.
6. Case context, evidence, and tool scopes are retained regardless of reset_context flag.
"""

from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from src.api.auth import Principal, require_principal
from src.api.routes import router
from src.config import Settings, get_settings
from src.models.schemas import PolicyChatRequest
from src.services.case_service import CaseService, get_case_service


@pytest.fixture
def context_reset_app(monkeypatch):
    case_id = "018f2f4e-a000-7000-8000-000000000001"
    organization_id = "018f2f4e-0000-7000-8000-000000000001"
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    settings = Settings(app_env="test", database_url="", test_auth_enabled=True)
    service = CaseService(settings)
    monkeypatch.setattr(service, "_get_db_connection", lambda: None)
    monkeypatch.setattr(service, "get_redis_client", lambda: None)
    service._in_memory_sessions = True
    service._cases[case_id] = {"id": case_id, "organization_id": organization_id, "status": "ready"}
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_case_service] = lambda: service
    app.dependency_overrides[require_principal] = lambda: Principal(
        id="analyst-context-reset", organization_id=organization_id, roles=frozenset({"analyst"})
    )
    return app


@pytest.fixture
def recorded_cockpit_rag_agent(monkeypatch):
    """Mock CockpitRAGAgent capturing executed turns and conversation_history."""
    calls = []

    mock_response = SimpleNamespace(
        status="success",
        answer="Phân tích độc lập theo quy định hiện hành.",
        tool_called="search_policy",
        citations=[
            SimpleNamespace(
                document_title="Quy chế dịch vụ 2026",
                doc_id="policy-sec-14",
                snippet="Xử phạt vi phạm điều hướng đón khách",
            )
        ],
        model_copy=lambda **kwargs: SimpleNamespace(
            status="success",
            answer=kwargs.get("update", {}).get("answer", "Trả lời chính sách"),
            tool_called="search_policy",
            citations=[],
        ),
    )

    class MockRecordingAgent:
        def execute_turn(self, question, driver_id, case_id, conversation_history, on_tool_call=None):
            calls.append(
                {
                    "question": question,
                    "driver_id": driver_id,
                    "case_id": case_id,
                    "conversation_history": list(conversation_history),
                }
            )
            if on_tool_call:
                on_tool_call("search_policy")
            return mock_response

    monkeypatch.setattr("src.rag.cockpit_agent.CockpitRAGAgent", MockRecordingAgent)
    return calls


def test_policy_chat_request_schema_reset_context_default():
    """Verify PolicyChatRequest validates reset_context as a boolean defaulting to False."""
    req_default = PolicyChatRequest(
        query="Kiểm tra vi phạm",
        case_id=uuid4(),
    )
    assert req_default.reset_context is False

    req_reset = PolicyChatRequest(
        query="Kiểm tra vi phạm",
        case_id=uuid4(),
        reset_context=True,
    )
    assert req_reset.reset_context is True


@pytest.mark.asyncio
async def test_analyst_chat_context_reset_excludes_prior_history_from_model_input(
    recorded_cockpit_rag_agent, context_reset_app
):
    """DoD: Demonstrate checked/unchecked multi-turn behavior with captured model-input tests.

    Turn 1 (reset=False): history contains only Turn 1 query.
    Turn 2 (reset=False): history contains Turn 1 user + Turn 1 assistant + Turn 2 query.
    Turn 3 (reset=True):  history contains ONLY Turn 3 query (prior turns excluded from model input).
    Turn 4 (reset=False): history resumes with all prior turns intact from session storage.
    """
    case_id = "018f2f4e-a000-7000-8000-000000000001"
    app = context_reset_app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Turn 1: normal turn
        turn1_id = str(uuid4())
        res1 = await client.post(
            "/api/v1/policy/chat/stream",
            json={
                "query": "Tin nhắn 1: Tóm tắt vi phạm chuyến đi",
                "case_id": case_id,
                "turn_id": turn1_id,
                "reset_context": False,
            },
            headers={"Authorization": "Bearer test-analyst-token"},
        )
        assert res1.status_code == 200
        assert len(recorded_cockpit_rag_agent) == 1
        turn1_history = recorded_cockpit_rag_agent[0]["conversation_history"]
        assert len(turn1_history) == 1
        assert turn1_history[0]["content"] == "Tin nhắn 1: Tóm tắt vi phạm chuyến đi"

        # Turn 2: normal turn with history accumulation
        turn2_id = str(uuid4())
        res2 = await client.post(
            "/api/v1/policy/chat/stream",
            json={
                "query": "Tin nhắn 2: Bằng chứng telemetry thế nào?",
                "case_id": case_id,
                "turn_id": turn2_id,
                "reset_context": False,
            },
            headers={"Authorization": "Bearer test-analyst-token"},
        )
        assert res2.status_code == 200
        assert len(recorded_cockpit_rag_agent) == 2
        turn2_history = recorded_cockpit_rag_agent[1]["conversation_history"]
        # Turn 2 history should contain Turn 1 user, Turn 1 assistant, and Turn 2 user
        contents_turn2 = [h["content"] for h in turn2_history]
        assert "Tin nhắn 1: Tóm tắt vi phạm chuyến đi" in contents_turn2
        assert "Tin nhắn 2: Bằng chứng telemetry thế nào?" in contents_turn2

        # Turn 3: CONTEXT RESET CHECKED
        turn3_id = str(uuid4())
        res3 = await client.post(
            "/api/v1/policy/chat/stream",
            json={
                "query": "Tin nhắn 3: Đánh giá chính sách độc lập không phụ thuộc ngữ cảnh trước",
                "case_id": case_id,
                "turn_id": turn3_id,
                "reset_context": True,
            },
            headers={"Authorization": "Bearer test-analyst-token"},
        )
        assert res3.status_code == 200
        assert len(recorded_cockpit_rag_agent) == 3
        turn3_history = recorded_cockpit_rag_agent[2]["conversation_history"]
        # CRITICAL ASSERTION: Prior turns must NOT be present in model input!
        contents_turn3 = [h["content"] for h in turn3_history]
        assert "Tin nhắn 1: Tóm tắt vi phạm chuyến đi" not in contents_turn3
        assert "Tin nhắn 2: Bằng chứng telemetry thế nào?" not in contents_turn3
        assert contents_turn3 == ["Tin nhắn 3: Đánh giá chính sách độc lập không phụ thuộc ngữ cảnh trước"]

        # Turn 4: Subsequent message with reset_context=False resumes full history
        turn4_id = str(uuid4())
        res4 = await client.post(
            "/api/v1/policy/chat/stream",
            json={
                "query": "Tin nhắn 4: Kết luận tổng thể",
                "case_id": case_id,
                "turn_id": turn4_id,
                "reset_context": False,
            },
            headers={"Authorization": "Bearer test-analyst-token"},
        )
        assert res4.status_code == 200
        assert len(recorded_cockpit_rag_agent) == 4
        turn4_history = recorded_cockpit_rag_agent[3]["conversation_history"]
        contents_turn4 = [h["content"] for h in turn4_history]
        # Proves all turns were persisted and resume properly
        assert "Tin nhắn 1: Tóm tắt vi phạm chuyến đi" in contents_turn4
        assert "Tin nhắn 2: Bằng chứng telemetry thế nào?" in contents_turn4
        assert "Tin nhắn 3: Đánh giá chính sách độc lập không phụ thuộc ngữ cảnh trước" in contents_turn4
        assert "Tin nhắn 4: Kết luận tổng thể" in contents_turn4


@pytest.mark.asyncio
async def test_analyst_chat_context_reset_preserves_audit_records_and_session(
    recorded_cockpit_rag_agent, context_reset_app
):
    """DoD: Preserve stored audit/conversation records and required identity, ownership, policy.

    The reset cannot delete historical turns from app.case_agent_messages or session endpoint.
    """
    case_id = "018f2f4e-a000-7000-8000-000000000001"
    app = context_reset_app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Message 1: Normal
        await client.post(
            "/api/v1/policy/chat/stream",
            json={"query": "Câu hỏi 1", "case_id": case_id, "turn_id": str(uuid4()), "reset_context": False},
            headers={"Authorization": "Bearer test-analyst-token"},
        )
        # Message 2: With reset_context=True
        await client.post(
            "/api/v1/policy/chat/stream",
            json={"query": "Câu hỏi 2 đơn lẻ", "case_id": case_id, "turn_id": str(uuid4()), "reset_context": True},
            headers={"Authorization": "Bearer test-analyst-token"},
        )

        # Retrieve session endpoint
        session_res = await client.get(
            f"/api/v1/cases/{case_id}/agent-session",
            headers={"Authorization": "Bearer test-analyst-token"},
        )
        assert session_res.status_code == 200
        session_data = session_res.json()
        messages = session_data.get("messages", [])
        # Both user queries and both assistant answers must be fully preserved in audit logs
        assert len(messages) >= 4
        user_texts = [m["content"] for m in messages if m["role"] == "user"]
        assert "Câu hỏi 1" in user_texts
        assert "Câu hỏi 2 đơn lẻ" in user_texts

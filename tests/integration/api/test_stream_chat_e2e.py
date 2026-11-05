"""Fixture transport regressions; these do not prove real Clerk or hosted persistence."""

import json
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from src.api.routes import router
from src.config import Settings, get_settings
from src.services.case_service import CaseService, get_case_service


@pytest.fixture
def mock_cockpit_rag_agent(monkeypatch):
    """Mock CockpitRAGAgent to return deterministic responses without calling external LLM."""
    mock_response = SimpleNamespace(
        status="success",
        answer="Quy định xử lý dựa trên điều 14.2 quy chế vi phạm.",
        tool_called="search_policy",
        citations=[
            SimpleNamespace(
                document_title="Quy chế dịch vụ 2026",
                doc_id="policy-sec-14",
                snippet="Xử phạt hành vi dừng xe không đón khách",
            )
        ],
        model_copy=lambda **kwargs: SimpleNamespace(
            status="success",
            answer=kwargs.get("update", {}).get("answer", "Trả lời chính sách"),
            tool_called="search_policy",
            citations=[],
        ),
    )

    class MockAgent:
        def execute_turn(self, question, driver_id, case_id, conversation_history, on_tool_call=None):
            if on_tool_call:
                on_tool_call("search_policy")
            return mock_response

    monkeypatch.setattr("src.rag.cockpit_agent.CockpitRAGAgent", MockAgent)


async def _parse_sse_events(response_text: str) -> list[tuple[str, dict]]:
    events = []
    current_event = "message"
    for block in response_text.strip().split("\n\n"):
        if not block.strip():
            continue
        event_name = current_event
        data_str = ""
        for line in block.split("\n"):
            if line.startswith("event:"):
                event_name = line[6:].strip()
            elif line.startswith("data:"):
                data_str = line[5:].strip()
        if data_str:
            try:
                events.append((event_name, json.loads(data_str)))
            except json.JSONDecodeError:
                events.append((event_name, {"raw": data_str}))
    return events


@pytest.mark.asyncio
async def test_stream_chat_conversation_5_messages_test_env(mock_cockpit_rag_agent):
    """DoD verification: 5-message conversation pass in test environment."""
    case_id = "018f2f4e-a000-7000-8000-000000000001"
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    settings = Settings(app_env="test", database_url="")
    service = CaseService(settings)
    service._in_memory_sessions = True
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_case_service] = lambda: service

    conversation = [
        "Tin nhắn 1: Tóm tắt vi phạm",
        "Tin nhắn 2: Bằng chứng telemetry thế nào?",
        "Tin nhắn 3: Giải trình của tài xế",
        "Tin nhắn 4: Điều khoản quy định áp dụng",
        "Tin nhắn 5: Kết luận xử lý",
    ]

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        for idx, msg in enumerate(conversation):
            turn_id = str(uuid4())
            res = await client.post(
                "/api/v1/policy/chat/stream",
                json={"query": msg, "case_id": case_id, "turn_id": turn_id},
                headers={},
            )
            assert res.status_code == 200, f"Message {idx + 1} failed: {res.text}"
            assert "text/event-stream" in res.headers["content-type"]
            events = await _parse_sse_events(res.text)
            event_types = [e[0] for e in events]
            assert "text_delta" in event_types
            assert "done" in event_types

        # Verify session history contains all 5 turns
        session_res = await client.get(
            f"/api/v1/cases/{case_id}/agent-session",
            headers={},
        )
        assert session_res.status_code == 200
        session_data = session_res.json()
        assert len(session_data.get("messages", [])) >= 10  # 5 user + 5 assistant messages


@pytest.mark.asyncio
async def test_development_rejects_unverified_chat_tokens(mock_cockpit_rag_agent):
    """Development is protected; invented bearer tokens must never open chat."""
    case_id = "018f2f4e-a000-7000-8000-000000000001"
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    settings = Settings(app_env="development", database_url="")
    service = CaseService(settings)
    service._in_memory_sessions = True
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_case_service] = lambda: service

    conversation = [
        "Dev msg 1: Khởi động phiên",
        "Dev msg 2: Kiểm tra dữ liệu",
        "Dev msg 3: Đối chiếu quy định",
        "Dev msg 4: Đánh giá độ tin cậy",
        "Dev msg 5: Hoàn tất phiên",
    ]

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        for idx, msg in enumerate(conversation):
            turn_id = str(uuid4())
            res = await client.post(
                "/api/v1/policy/chat/stream",
                json={"query": msg, "case_id": case_id, "turn_id": turn_id},
                headers={"Authorization": "Bearer dev-analyst-session"},
            )
            assert res.status_code == 401
            assert "text/event-stream" not in res.headers.get("content-type", "")


@pytest.mark.asyncio
async def test_stream_chat_conversation_5_messages_production_with_clerk_auth(mock_cockpit_rag_agent, monkeypatch):
    """DoD verification: 5-message conversation in production with Clerk auth and token renewal on turn 2."""
    case_id = "018f2f4e-a000-7000-8000-000000000001"
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    settings = Settings(
        app_env="production",
        database_url="",
        clerk_secret_key="sk_test_mock",
        clerk_jwks_url="https://mock.clerk.accounts.dev/.well-known/jwks.json",
    )
    service = CaseService(settings)
    service._in_memory_sessions = True
    app.dependency_overrides[get_settings] = lambda: settings
    app.dependency_overrides[get_case_service] = lambda: service

    conversation = [
        "Prod msg 1: Bắt đầu soát xét",
        "Prod msg 2: Tra cứu chính sách phạt",
        "Prod msg 3: Kiểm tra hành trình GPS",
        "Prod msg 4: Xem xét lý do hủy cuốc",
        "Prod msg 5: Đề xuất phương án kỷ luật",
    ]

    # Authentication uses production settings; fixture storage replaces the persistence boundary.
    service.settings = Settings(app_env="test", database_url="", test_auth_enabled=True)
    monkeypatch.setattr(
        "src.api.auth.load_principal",
        lambda *args: {
            "id": "user_clerk_analyst",
            "organization_id": "018f2f4e-0000-7000-8000-000000000001",
            "roles": ["analyst"],
        },
    )

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        for idx, msg in enumerate(conversation):
            turn_id = str(uuid4())

            if idx == 1:
                # Turn 2: Client first sends an expired Clerk token -> gets 401 "Invalid Clerk session"
                with (
                    patch(
                        "src.api.auth.authenticate_request",
                        side_effect=ValueError("token expired"),
                    ),
                    patch(
                        "src.api.auth._verify_jwt_with_jwks",
                        side_effect=ValueError("token expired"),
                    ),
                ):
                    expired_res = await client.post(
                        "/api/v1/policy/chat/stream",
                        json={"query": msg, "case_id": case_id, "turn_id": turn_id},
                        headers={"Authorization": "Bearer expired-clerk-token"},
                    )
                    assert expired_res.status_code == 401
                    assert "Invalid Clerk session" in expired_res.json()["detail"]

                # Client refreshes token and retries turn 2 -> 200 OK
                with patch(
                    "src.api.auth.authenticate_request",
                    return_value=SimpleNamespace(
                        is_signed_in=True,
                        payload={"sub": "user_clerk_analyst", "email": "analyst@greensm.vn"},
                    ),
                ):
                    retry_res = await client.post(
                        "/api/v1/policy/chat/stream",
                        json={"query": msg, "case_id": case_id, "turn_id": turn_id},
                        headers={"Authorization": "Bearer fresh-clerk-token"},
                    )
                    assert retry_res.status_code == 200
                    events = await _parse_sse_events(retry_res.text)
                    event_types = [e[0] for e in events]
                    assert "text_delta" in event_types
                    assert "done" in event_types
            else:
                # Turns 1, 3, 4, 5 with valid Clerk session
                with patch(
                    "src.api.auth.authenticate_request",
                    return_value=SimpleNamespace(
                        is_signed_in=True,
                        payload={"sub": "user_clerk_analyst", "email": "analyst@greensm.vn"},
                    ),
                ):
                    res = await client.post(
                        "/api/v1/policy/chat/stream",
                        json={"query": msg, "case_id": case_id, "turn_id": turn_id},
                        headers={"Authorization": f"Bearer clerk-token-{idx + 1}"},
                    )
                    assert res.status_code == 200, f"Production turn {idx + 1} failed: {res.text}"
                    events = await _parse_sse_events(res.text)
                    event_types = [e[0] for e in events]
                    assert "text_delta" in event_types
                    assert "done" in event_types

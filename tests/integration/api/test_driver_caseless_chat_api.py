"""TDD RED: POST /api/v1/driver/chat/stream (Issue #482).

Case-less GSupport chat endpoint: driver identity from authenticated principal,
SSE token/blocks/done events, locale vi|en, no case_id required.
"""

import json
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient


def _parse_sse_blocks(text: str) -> list[tuple[str, dict]]:
    events = []
    for block in text.strip().split("\n\n"):
        if not block.strip():
            continue
        event_name = "message"
        data_str = ""
        for line in block.split("\n"):
            if line.startswith("event:"):
                event_name = line[6:].strip()
            elif line.startswith("data:"):
                data_str = line[5:].strip()
        if data_str:
            events.append((event_name, json.loads(data_str)))
    return events


@pytest.mark.asyncio
async def test_driverless_chat_stream_uses_authenticated_driver_identity(client: AsyncClient):
    """The driver identity on the done event must be the authenticated principal's
    driver_id (X-Driver-ID), never a client-supplied body field (none exists)."""
    agent_result = {"reply": "Xin chào, tôi có thể giúp gì cho bạn?", "blocks": [], "error": None}
    with patch(
        "src.agents.driver_agent.run_driver_support_agent",
        new=AsyncMock(return_value=agent_result),
    ) as mocked:
        res = await client.post(
            "/api/v1/driver/chat/stream",
            json={"message": "Xin chào", "locale": "vi"},
            headers={"X-Driver-ID": "drv-identity-007", "X-Role": "driver"},
        )
    assert res.status_code == 200, res.text
    events = _parse_sse_blocks(res.text)
    done_data = [data for evt, data in events if evt == "done"][0]
    assert done_data["driver_id"] == "drv-identity-007"
    _, kwargs = mocked.call_args
    assert kwargs.get("driver_id") == "drv-identity-007"


@pytest.mark.asyncio
async def test_driverless_chat_stream_emits_real_agent_reply(client: AsyncClient):
    agent_result = {
        "reply": "Chào bạn, bạn hiện có 1 vụ việc đang mở.",
        "blocks": [{"type": "case_card", "case_id": "018f2f4e-0000", "title": "Vụ việc #018F"}],
        "error": None,
    }
    with patch(
        "src.agents.driver_agent.run_driver_support_agent",
        new=AsyncMock(return_value=agent_result),
    ):
        res = await client.post(
            "/api/v1/driver/chat/stream",
            json={"message": "Tôi có vụ việc nào đang mở không?", "locale": "vi"},
            headers={"X-Driver-ID": "drv-api-caseless-001", "X-Role": "driver"},
        )

    assert res.status_code == 200, res.text
    assert "text/event-stream" in res.headers["content-type"]

    events = _parse_sse_blocks(res.text)
    event_names = [e for e, _ in events]
    assert "token" in event_names
    assert event_names[-2] == "blocks"
    assert event_names[-1] == "done"

    done_data = [data for evt, data in events if evt == "done"][0]
    assert done_data["reply"] == agent_result["reply"]
    assert done_data["driver_id"] == "drv-api-caseless-001"


@pytest.mark.asyncio
async def test_driverless_chat_stream_rejects_empty_message(client: AsyncClient):
    res = await client.post(
        "/api/v1/driver/chat/stream",
        json={"message": "   ", "locale": "vi"},
        headers={"X-Driver-ID": "drv-api-caseless-002", "X-Role": "driver"},
    )
    assert res.status_code == 422, res.text


@pytest.mark.asyncio
async def test_driverless_chat_stream_accepts_en_locale(client: AsyncClient):
    agent_result = {"reply": "You have 1 open case.", "blocks": [], "error": None}
    with patch(
        "src.agents.driver_agent.run_driver_support_agent",
        new=AsyncMock(return_value=agent_result),
    ) as mocked:
        res = await client.post(
            "/api/v1/driver/chat/stream",
            json={"message": "Do I have any open cases?", "locale": "en"},
            headers={"X-Driver-ID": "drv-api-caseless-003", "X-Role": "driver"},
        )

    assert res.status_code == 200, res.text
    mocked.assert_awaited_once()
    _, kwargs = mocked.call_args
    assert kwargs.get("locale") == "en"
    assert kwargs.get("case_id") is None
    assert kwargs.get("driver_id") == "drv-api-caseless-003"

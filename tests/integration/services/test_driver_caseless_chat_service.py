"""TDD RED: DriverDisputeService.stream_driverless_chat (Issue #482).

Case-less GSupport chat SSE: no case_id, driver identity from the authenticated
principal, real agent reply (not a discarded asyncio.create_task), locale vi|en.
"""

import json
from unittest.mock import AsyncMock, patch

import pytest

from src.services.driver_dispute_service import get_driver_dispute_service


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


@pytest.fixture
def dispute_service():
    return get_driver_dispute_service()


@pytest.mark.asyncio
async def test_stream_driverless_chat_emits_real_agent_reply(dispute_service):
    """The streamed text/done payload must be the real agent reply, not a template."""
    agent_result = {
        "reply": "Bạn hiện có 1 vụ việc đang mở (#018F).",
        "blocks": [{"type": "case_card", "case_id": "018f2f4e-0000", "title": "Vụ việc #018F"}],
        "error": None,
    }

    with patch(
        "src.agents.driver_agent.run_driver_support_agent",
        new=AsyncMock(return_value=agent_result),
    ):
        chunks = []
        async for chunk in dispute_service.stream_driverless_chat(
            driver_id="drv-caseless-001",
            message="Tôi có vụ việc nào đang mở không?",
            locale="vi",
            organization_id="018f2f4e-0000-7000-8000-000000000001",
        ):
            chunks.append(chunk)

    text = "".join(chunks)
    events = _parse_sse_blocks(text)
    event_names = [e for e, _ in events]

    assert "token" in event_names
    assert event_names[-2] == "blocks"
    assert event_names[-1] == "done"

    token_text = "".join(data.get("token", data.get("delta", "")) for evt, data in events if evt == "token")
    assert token_text.strip() == agent_result["reply"]

    done_data = [data for evt, data in events if evt == "done"][0]
    assert done_data["reply"] == agent_result["reply"]
    assert done_data["status"] == "completed"
    assert done_data["driver_id"] == "drv-caseless-001"

    blocks_data = [data for evt, data in events if evt == "blocks"][0]
    assert blocks_data["blocks"] == agent_result["blocks"]


@pytest.mark.asyncio
async def test_stream_driverless_chat_handles_agent_failure_gracefully(dispute_service):
    """Agent failure must not crash the stream; emit an error event instead."""
    with patch(
        "src.agents.driver_agent.run_driver_support_agent",
        new=AsyncMock(side_effect=RuntimeError("boom")),
    ):
        chunks = []
        async for chunk in dispute_service.stream_driverless_chat(
            driver_id="drv-caseless-002",
            message="Xin chào",
            locale="vi",
        ):
            chunks.append(chunk)

    text = "".join(chunks)
    events = _parse_sse_blocks(text)
    assert any(evt == "error" for evt, _ in events)

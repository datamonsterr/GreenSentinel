import asyncio
import json
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from src.config import get_settings
from src.services.driver_dispute_service import get_driver_dispute_service


def _parse_sse_events(text: str) -> list[tuple[str, dict]]:
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
async def test_driverless_chat_stream_emits_tool_start_and_end_events():
    """B16: stream_driverless_chat must emit 'event: tool.start' and 'event: tool.end' before tokens."""
    service = get_driver_dispute_service()

    agent_result = {
        "reply": "Tôi đã kiểm tra danh sách chuyến xe của bạn.",
        "blocks": [],
        "error": None,
        "tool_events": [
            {
                "event": "tool.start",
                "data": {
                    "tool_call_id": "call_1",
                    "name": "list_my_cases",
                    "label": "Đang kiểm tra danh sách vụ việc của bạn",
                },
            },
            {
                "event": "tool.end",
                "data": {
                    "tool_call_id": "call_1",
                    "name": "list_my_cases",
                    "status": "ok",
                },
            },
        ],
    }

    with patch(
        "src.agents.driver_agent.run_driver_support_agent",
        new=AsyncMock(return_value=agent_result),
    ):
        chunks = []
        async for chunk in service.stream_driverless_chat(
            driver_id="drv-001",
            message="Kiểm tra vụ việc",
            locale="vi",
            organization_id="018f2f4e-0000-7000-8000-000000000001",
        ):
            chunks.append(chunk)

    text = "".join(chunks)
    events = _parse_sse_events(text)
    event_names = [e for e, _ in events]

    # Verify event order: tool.start -> tool.end -> token -> blocks -> done
    assert "tool.start" in event_names
    assert "tool.end" in event_names
    assert "token" in event_names
    assert event_names[-2] == "blocks"
    assert event_names[-1] == "done"

    start_idx = event_names.index("tool.start")
    end_idx = event_names.index("tool.end")
    token_idx = event_names.index("token")
    assert start_idx < end_idx < token_idx

    # Check payloads
    tool_start_data = events[start_idx][1]
    assert tool_start_data["tool_call_id"] == "call_1"
    assert tool_start_data["name"] == "list_my_cases"
    assert tool_start_data["label"] == "Đang kiểm tra danh sách vụ việc của bạn"

    tool_end_data = events[end_idx][1]
    assert tool_end_data["tool_call_id"] == "call_1"
    assert tool_end_data["name"] == "list_my_cases"
    assert tool_end_data["status"] == "ok"


@pytest.mark.asyncio
async def test_scoped_chat_stream_emits_tool_start_and_end_events():
    """B16: stream_driver_chat must emit 'event: tool.start' and 'event: tool.end' before tokens."""
    service = get_driver_dispute_service()

    # Pre-populate a test case
    cid = "018f2f4e-case-tool-stream-001"
    service.case_service._cases[cid] = {
        "id": cid,
        "driver_id": "drv-001",
        "organization_id": "018f2f4e-0000-7000-8000-000000000001",
        "status": "open",
        "dispute_status": "in_dispute",
    }

    agent_result = {
        "reply": "Tôi đã kiểm tra dữ liệu giao thông.",
        "blocks": [],
        "error": None,
        "tool_events": [
            {
                "event": "tool.start",
                "data": {
                    "tool_call_id": "call_corrob",
                    "name": "corroborate_traffic_conditions",
                    "label": "Đang đối soát tình trạng giao thông",
                },
            },
            {
                "event": "tool.end",
                "data": {
                    "tool_call_id": "call_corrob",
                    "name": "corroborate_traffic_conditions",
                    "status": "ok",
                },
            },
        ],
    }

    with patch(
        "src.agents.driver_agent.run_driver_support_agent",
        new=AsyncMock(return_value=agent_result),
    ):
        chunks = []
        async for chunk in service.stream_driver_chat(
            case_id=cid,
            driver_id="drv-001",
            message="Kẹt xe đường vành đai 3",
            locale="vi",
        ):
            chunks.append(chunk)

    text = "".join(chunks)
    events = _parse_sse_events(text)
    event_names = [e for e, _ in events]

    assert "tool.start" in event_names
    assert "tool.end" in event_names
    assert "token" in event_names
    assert event_names[-2] == "blocks"
    assert event_names[-1] == "done"

    start_idx = event_names.index("tool.start")
    end_idx = event_names.index("tool.end")
    token_idx = event_names.index("token")
    assert start_idx < end_idx < token_idx


@pytest.mark.asyncio
async def test_stream_driver_chat_missing_driver_id_raises_403():
    """F3: stream_driver_chat must raise 403 when driver_id is None or empty, never falling back to drv-dev-001."""
    service = get_driver_dispute_service()
    cid = "018f2f4e-case-tool-stream-001"

    with pytest.raises(HTTPException) as exc_info:
        async for _ in service.stream_driver_chat(
            case_id=cid,
            driver_id=None,
            message="Test message",
        ):
            pass
    assert exc_info.value.status_code == 403
    assert "Driver mapping required" in str(exc_info.value.detail)

    with pytest.raises(HTTPException) as exc_info2:
        async for _ in service.stream_driver_chat(
            case_id=cid,
            driver_id="",
            message="Test message",
        ):
            pass
    assert exc_info2.value.status_code == 403
    assert "Driver mapping required" in str(exc_info2.value.detail)


@pytest.mark.asyncio
async def test_stream_driverless_chat_missing_driver_id_raises_403():
    """F3: stream_driverless_chat must raise 403 when driver_id is empty."""
    service = get_driver_dispute_service()

    with pytest.raises(HTTPException) as exc_info:
        async for _ in service.stream_driverless_chat(
            driver_id="",
            message="Test message",
        ):
            pass
    assert exc_info.value.status_code == 403
    assert "Driver mapping required" in str(exc_info.value.detail)


@pytest.mark.asyncio
async def test_stream_driver_chat_uses_configurable_agent_timeout(monkeypatch):
    """R1: the agent run deadline is read from Settings.driver_agent_timeout_seconds,
    not a hard-coded literal, so slower deployments (e.g. Railway dev) can raise it."""
    service = get_driver_dispute_service()
    cid = "018f2f4e-case-tool-stream-timeout"
    service.case_service._cases[cid] = {
        "id": cid,
        "driver_id": "drv-001",
        "organization_id": "018f2f4e-0000-7000-8000-000000000001",
        "status": "open",
        "dispute_status": "in_dispute",
    }
    get_settings.cache_clear()
    monkeypatch.setenv("DRIVER_AGENT_TIMEOUT_SECONDS", "7")
    get_settings.cache_clear()

    captured_timeout = {}
    original = service._stream_agent_tool_events

    def spy(*args, **kwargs):
        captured_timeout["timeout"] = kwargs.get("timeout")
        return original(*args, **kwargs)

    agent_result = {"reply": "ok", "blocks": [], "error": None, "tool_events": []}
    with (
        patch.object(service, "_stream_agent_tool_events", side_effect=spy),
        patch(
            "src.agents.driver_agent.run_driver_support_agent",
            new=AsyncMock(return_value=agent_result),
        ),
    ):
        async for _ in service.stream_driver_chat(case_id=cid, driver_id="drv-001", message="Test timeout"):
            pass

    get_settings.cache_clear()
    assert captured_timeout["timeout"] == 7.0


@pytest.mark.asyncio
async def test_stream_driver_chat_logs_swallowed_agent_error_with_case_id(caplog):
    """R1: a swallowed agent-run exception must be logged (with the case id),
    never silently discarded at debug level."""
    service = get_driver_dispute_service()
    cid = "018f2f4e-case-tool-stream-logerr"
    service.case_service._cases[cid] = {
        "id": cid,
        "driver_id": "drv-001",
        "organization_id": "018f2f4e-0000-7000-8000-000000000001",
        "status": "open",
        "dispute_status": "in_dispute",
    }

    async def boom(*_args, **_kwargs):
        raise RuntimeError("weather tool exploded")

    import logging

    with patch("src.agents.driver_agent.run_driver_support_agent", side_effect=boom):
        with caplog.at_level(logging.ERROR, logger="src.services.driver_dispute_service"):
            async for _ in service.stream_driver_chat(case_id=cid, driver_id="drv-001", message="Test log"):
                pass

    assert any(cid in rec.message and rec.levelno >= logging.ERROR for rec in caplog.records)


@pytest.mark.asyncio
async def test_stream_driver_chat_marks_fallback_in_done_event_when_agent_fails():
    """R1: when the real agent run errors/times out, the done event must carry
    an explicit fallback flag so the UI/logs can tell the template was shown."""
    service = get_driver_dispute_service()
    cid = "018f2f4e-case-tool-stream-fallback"
    service.case_service._cases[cid] = {
        "id": cid,
        "driver_id": "drv-001",
        "organization_id": "018f2f4e-0000-7000-8000-000000000001",
        "status": "open",
        "dispute_status": "in_dispute",
    }

    async def boom(*_args, **_kwargs):
        raise RuntimeError("agent exploded")

    with patch("src.agents.driver_agent.run_driver_support_agent", side_effect=boom):
        chunks = []
        async for chunk in service.stream_driver_chat(case_id=cid, driver_id="drv-001", message="Test fallback flag"):
            chunks.append(chunk)

    text = "".join(chunks)
    events = _parse_sse_events(text)
    done_payload = next(data for name, data in events if name == "done")
    assert done_payload["is_agent_fallback"] is True


@pytest.mark.asyncio
async def test_stream_driver_chat_cancels_agent_task_on_disconnect():
    """F4: stream_driver_chat must cancel agent_task if generator is closed early (client disconnect)."""
    service = get_driver_dispute_service()
    cid = "018f2f4e-case-tool-stream-001"
    service.case_service._cases[cid] = {
        "id": cid,
        "driver_id": "drv-001",
        "organization_id": "018f2f4e-0000-7000-8000-000000000001",
        "status": "open",
        "dispute_status": "in_dispute",
    }

    was_cancelled = False

    async def mock_agent(*args, **kwargs):
        nonlocal was_cancelled
        on_event = kwargs.get("on_tool_event")
        if on_event:
            await on_event("tool.start", {"tool_call_id": "call_1", "name": "list_my_cases", "label": "Checking cases"})
        try:
            await asyncio.sleep(5)
        except asyncio.CancelledError:
            was_cancelled = True
            raise

    with patch("src.agents.driver_agent.run_driver_support_agent", side_effect=mock_agent):
        gen = service.stream_driver_chat(
            case_id=cid,
            driver_id="drv-001",
            message="Test cancel",
        )
        first_chunk = await anext(gen)
        assert "tool.start" in first_chunk
        await gen.aclose()

    assert was_cancelled is True


@pytest.mark.asyncio
async def test_stream_driverless_chat_cancels_agent_task_on_disconnect():
    """F4: stream_driverless_chat must cancel agent_task if generator is closed early (client disconnect)."""
    service = get_driver_dispute_service()

    was_cancelled = False

    async def mock_agent(*args, **kwargs):
        nonlocal was_cancelled
        on_event = kwargs.get("on_tool_event")
        if on_event:
            await on_event("tool.start", {"tool_call_id": "call_1", "name": "list_my_cases", "label": "Checking cases"})
        try:
            await asyncio.sleep(5)
        except asyncio.CancelledError:
            was_cancelled = True
            raise

    with patch("src.agents.driver_agent.run_driver_support_agent", side_effect=mock_agent):
        gen = service.stream_driverless_chat(
            driver_id="drv-001",
            message="Test cancel driverless",
            organization_id="018f2f4e-0000-7000-8000-000000000001",
        )
        first_chunk = await anext(gen)
        assert "tool.start" in first_chunk
        await gen.aclose()

    assert was_cancelled is True

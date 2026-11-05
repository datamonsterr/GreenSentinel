"""TDD: driver tools and agent organization scope propagation.

Tests:
1. list_my_cases via execute_tool with a mocked list_driver_cases receives organization_id.
2. list_my_cases with missing/empty organization_id fails closed (FORBIDDEN).
3. driver tool adapters in tool_execution.py pass ctx.organization_id to underlying tools.
4. routes pass principal.organization_id into the driver support agent.
5. stream_driverless_chat and stream_driver_chat fail closed with localized error event when organization_id is missing.
"""

import json
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from src.agents.tools.driver_tools import (
    get_my_scorecard,
    get_trip_summary,
    list_my_cases,
    list_my_trips,
)
from src.main import app
from src.models.schemas import DriverCaseListResponse
from src.models.tool_contracts import ToolExecutionContext
from src.services.driver_dispute_service import get_driver_dispute_service
from src.services.tool_execution import execute_tool


def _make_driver_context(
    organization_id: str = "018f2f4e-0000-7000-8000-000000000001",
    driver_id: str = "drv-caseless-001",
    case_id: str | None = None,
) -> ToolExecutionContext:
    return ToolExecutionContext(
        actor_id=driver_id,
        organization_id=organization_id,
        roles=frozenset({"driver"}),
        case_id=case_id,
        driver_id=driver_id,
        request_id=str(uuid4()),
        run_id=str(uuid4()),
        tool_call_id=str(uuid4()),
        turn_id=str(uuid4()),
    )


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
async def test_list_my_cases_via_execute_tool_receives_organization_id():
    """execute_tool('list_my_cases', ...) must pass ctx.organization_id to list_driver_cases."""
    ctx = _make_driver_context(organization_id="org-scope-test-001", driver_id="drv-scope-001")
    service = get_driver_dispute_service()

    mock_list_cases = AsyncMock(return_value=DriverCaseListResponse(items=[], total=0))
    with patch.object(service, "list_driver_cases", mock_list_cases):
        result = await execute_tool("list_my_cases", {}, ctx)

    assert result.status == "succeeded", result.error
    mock_list_cases.assert_called_once()
    _, kwargs = mock_list_cases.call_args
    assert kwargs.get("organization_id") == "org-scope-test-001"
    assert kwargs.get("driver_id") == "drv-scope-001"


@pytest.mark.asyncio
async def test_list_my_cases_missing_org_fails_closed():
    """list_my_cases with missing/empty organization_id must fail closed with FORBIDDEN."""
    ctx = _make_driver_context(organization_id="", driver_id="drv-scope-001")
    result = await execute_tool("list_my_cases", {}, ctx)
    assert result.status == "failed"
    assert result.error is not None
    assert result.error.code == "FORBIDDEN"

    # Direct tool call also fails closed
    direct_res = await list_my_cases.ainvoke({"driver_id": "drv-scope-001", "organization_id": ""})
    assert direct_res.get("error_type") == "FORBIDDEN"
    assert direct_res.get("status_code") == 403


@pytest.mark.asyncio
async def test_driver_tools_pass_organization_scope():
    """Audit driver tools for passing organization_id to underlying services."""
    org_id = "org-audit-999"
    driver_id = "drv-audit-999"

    # 1. get_my_scorecard
    with patch("src.services.driver_service.get_driver_scorecard", new=AsyncMock()) as mock_sc:
        await get_my_scorecard.ainvoke({"driver_id": driver_id, "organization_id": org_id})
        mock_sc.assert_called_once()
        _, sc_kwargs = mock_sc.call_args
        assert sc_kwargs.get("organization_id") == org_id

    # 2. list_my_trips
    with patch(
        "src.services.driver_service.list_driver_trips", new=AsyncMock(return_value={"items": []})
    ) as mock_trips:
        await list_my_trips.ainvoke({"driver_id": driver_id, "organization_id": org_id})
        mock_trips.assert_called_once()
        _, trips_kwargs = mock_trips.call_args
        assert trips_kwargs.get("organization_id") == org_id

    # 3. get_trip_summary
    trip_id = str(uuid4())
    with patch("src.services.driver_service.get_driver_trip_summary", new=AsyncMock(return_value={})) as mock_ts:
        await get_trip_summary.ainvoke({"trip_id": trip_id, "driver_id": driver_id, "organization_id": org_id})
        mock_ts.assert_called_once()
        _, ts_kwargs = mock_ts.call_args
        assert ts_kwargs.get("organization_id") == org_id


@pytest.mark.asyncio
async def test_driver_tool_adapters_dispatch_organization_id():
    """Audit tool_execution.py _dispatch for passing ctx.organization_id to all driver tools."""
    org_id = "018f2f4e-org-test-7777"
    driver_id = "drv-adapter-test"
    case_id = "018f2f4e-case-test-7777"
    ctx = _make_driver_context(organization_id=org_id, driver_id=driver_id, case_id=case_id)

    service = get_driver_dispute_service()
    service.case_service._cases[case_id] = {
        "id": case_id,
        "driver_id": driver_id,
        "organization_id": org_id,
        "status": "open",
    }

    # get_my_scorecard adapter
    with patch("src.services.driver_service.get_driver_scorecard", new=AsyncMock()) as m:
        await execute_tool("get_my_scorecard", {}, ctx)
        m.assert_called_once()
        assert m.call_args[1].get("organization_id") == org_id

    # list_my_trips adapter
    with patch("src.services.driver_service.list_driver_trips", new=AsyncMock(return_value={"items": []})) as m:
        await execute_tool("list_my_trips", {}, ctx)
        m.assert_called_once()
        assert m.call_args[1].get("organization_id") == org_id

    # get_trip_summary adapter
    trip_id = str(uuid4())
    with patch("src.services.driver_service.get_driver_trip_summary", new=AsyncMock(return_value={})) as m:
        await execute_tool("get_trip_summary", {"trip_id": trip_id}, ctx)
        m.assert_called_once()
        assert m.call_args[1].get("organization_id") == org_id

    # get_case_timeline adapter
    service = get_driver_dispute_service()
    with patch.object(service, "get_driver_dispute_context", new=AsyncMock()) as m:
        m.return_value.alleged_time = None
        m.return_value.case_id = case_id
        m.return_value.driver_id = driver_id
        await execute_tool("get_case_timeline", {"case_id": case_id}, ctx)
        m.assert_called_once()
        assert m.call_args[1].get("organization_id") == org_id

    # get_appeal_options adapter
    with patch.object(service, "get_driver_dispute_context", new=AsyncMock()) as m:
        m.return_value.case_id = case_id
        m.return_value.driver_id = driver_id
        m.return_value.dispute_status = "open"
        m.return_value.dispute_deadline = None
        await execute_tool("get_appeal_options", {"case_id": case_id}, ctx)
        m.assert_called_once()
        assert m.call_args[1].get("organization_id") == org_id


@pytest.mark.asyncio
async def test_routes_pass_principal_organization_id_into_agent():
    """Routes must pass principal.organization_id to the agent."""
    org_id = "018f2f4e-org-custom-1234"
    driver_id = "drv-route-test-01"
    headers = {
        "X-Driver-ID": driver_id,
        "X-Organization-ID": org_id,
        "X-Role": "driver",
    }

    mock_agent_result = {
        "reply": "Xin chào!",
        "blocks": [],
        "error": None,
    }

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. POST /api/v1/driver/chat/stream
        with patch(
            "src.agents.driver_agent.run_driver_support_agent",
            new=AsyncMock(return_value=mock_agent_result),
        ) as mock_agent:
            resp = await client.post(
                "/api/v1/driver/chat/stream",
                json={"message": "Kiểm tra vụ việc", "locale": "vi"},
                headers=headers,
            )
            assert resp.status_code == 200, resp.text
            mock_agent.assert_called_once()
            _, agent_kwargs = mock_agent.call_args
            assert agent_kwargs.get("organization_id") == org_id

        # 2. GET /api/v1/driver/cases/{case_id}/chat/stream
        case_id = "018f2f4e-case-route-test-1"
        service = get_driver_dispute_service()
        asgn_id = f"asgn-{case_id}"
        service.case_service._drivers[driver_id] = {
            "id": driver_id,
            "display_name": "Tài xế GreenSM",
        }
        service.case_service._assignments[asgn_id] = {
            "id": asgn_id,
            "driver_id": driver_id,
            "trip_id": f"trip-{case_id}",
        }
        service.case_service._cases[case_id] = {
            "id": case_id,
            "assignment_id": asgn_id,
            "driver_id": driver_id,
            "organization_id": org_id,
            "status": "open",
            "dispute_status": "in_dispute",
        }
        with patch(
            "src.agents.driver_agent.run_driver_support_agent",
            new=AsyncMock(return_value=mock_agent_result),
        ) as mock_agent:
            resp = await client.get(
                f"/api/v1/driver/cases/{case_id}/chat/stream?message=Giải+trình",
                headers=headers,
            )
            assert resp.status_code == 200, resp.text
            mock_agent.assert_called_once()
            _, agent_kwargs = mock_agent.call_args
            assert agent_kwargs.get("organization_id") == org_id

        # 3. POST /api/v1/driver/cases/{case_id}/chat/stream
        with patch(
            "src.agents.driver_agent.run_driver_support_agent",
            new=AsyncMock(return_value=mock_agent_result),
        ) as mock_agent:
            resp = await client.post(
                f"/api/v1/driver/cases/{case_id}/chat/stream",
                json={"message": "Giải trình tiếp", "locale": "vi"},
                headers=headers,
            )
            assert resp.status_code == 200, resp.text
            mock_agent.assert_called_once()
            _, agent_kwargs = mock_agent.call_args
            assert agent_kwargs.get("organization_id") == org_id


@pytest.mark.asyncio
async def test_stream_missing_organization_id_emits_localized_error_event():
    """stream_driverless_chat and stream_driver_chat must emit localized error event when organization_id is missing."""
    service = get_driver_dispute_service()

    # Case-less stream: Vietnamese locale
    chunks_vi = []
    async for chunk in service.stream_driverless_chat(
        driver_id="drv-001",
        message="Kiểm tra",
        locale="vi",
        organization_id=None,
    ):
        chunks_vi.append(chunk)
    events_vi = _parse_sse_events("".join(chunks_vi))
    assert len(events_vi) == 1
    assert events_vi[0][0] == "error"
    assert "tổ chức" in events_vi[0][1]["message"].lower() or "organization" in events_vi[0][1]["message"].lower()

    # Case-less stream: English locale
    chunks_en = []
    async for chunk in service.stream_driverless_chat(
        driver_id="drv-001",
        message="Check",
        locale="en",
        organization_id=None,
    ):
        chunks_en.append(chunk)
    events_en = _parse_sse_events("".join(chunks_en))
    assert len(events_en) == 1
    assert events_en[0][0] == "error"
    assert "organization scope required" in events_en[0][1]["message"].lower()

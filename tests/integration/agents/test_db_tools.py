"""Tests for database tools and integration with the LangGraph fraud analyst agent."""

import pytest

from src.agents.graph import build_graph
from src.agents.tools.analyst_tools import (
    ANALYST_TOOLS,
    check_driver_suspension,
    get_driver_history,
    query_cases_db,
)
from src.services.case_service import get_case_service

pytestmark = pytest.mark.docker


@pytest.fixture
def case_service():
    return get_case_service()


@pytest.mark.asyncio
async def test_get_driver_history_tool(case_service):
    """Test get_driver_history returns required driver profile metrics."""
    driver_id = "018f2f4e-3000-7000-8000-000000000001"
    res = await get_driver_history.ainvoke({"driver_id": driver_id})

    assert "driver_id" in res
    assert "rating" in res
    assert isinstance(res["rating"], (int, float))
    assert "completed_trips" in res
    assert isinstance(res["completed_trips"], int)
    assert "cancellation_rate" in res
    assert "acceptance_rate" in res
    assert "past_warnings" in res
    assert "past_sanctions" in res
    assert isinstance(res["past_sanctions"], list)
    assert "account_status" in res


@pytest.mark.asyncio
async def test_query_cases_db_tool():
    """Test query_cases_db with filters on priority, status, and driver."""
    # 1. Basic query with limit
    res_all = await query_cases_db.ainvoke({"limit": 5})
    assert "count" in res_all
    assert len(res_all["cases"]) <= 5

    # 2. Filter by priority P0
    res_p0 = await query_cases_db.ainvoke({"priority": "P0", "limit": 10})
    for c in res_p0["cases"]:
        assert c["priority"] == "P0"

    # 3. Filter by status
    res_ready = await query_cases_db.ainvoke({"status": "ready", "limit": 5})
    for c in res_ready["cases"]:
        assert c["status"].lower() == "ready"


@pytest.mark.asyncio
async def test_check_driver_suspension_tool(case_service):
    """Test check_driver_suspension returns accurate suspension states."""
    test_driver = "018f2f4e-3000-7000-8000-000000000006"

    # Active driver
    case_service.set_driver_status(test_driver, "active")
    res_active = await check_driver_suspension.ainvoke({"driver_id": test_driver})
    assert res_active["driver_id"] == test_driver
    assert res_active["is_suspended"] is False
    assert res_active["can_accept_trips"] is True
    assert res_active["account_status"] == "active"

    # Suspended driver
    case_service.set_driver_status(test_driver, "suspended")
    res_susp = await check_driver_suspension.ainvoke({"driver_id": test_driver})
    assert res_susp["driver_id"] == test_driver
    assert res_susp["is_suspended"] is True
    assert res_susp["can_accept_trips"] is False
    assert res_susp["account_status"] == "suspended"

    # Restore
    case_service.set_driver_status(test_driver, "active")


@pytest.mark.asyncio
async def test_langgraph_tool_registration_and_workflow():
    """Verify that all database tools are registered in ALL_ANALYST_TOOLS and model tools bound into LangGraph."""
    from src.agents.tools.analyst_tools import ALL_ANALYST_TOOLS

    all_tool_names = [t.name for t in ALL_ANALYST_TOOLS]
    assert "get_driver_history" in all_tool_names
    assert "query_cases_db" in all_tool_names
    assert "check_driver_suspension" in all_tool_names
    assert "get_case_detail" in all_tool_names
    assert "list_cases" in all_tool_names
    assert "claim_case" in all_tool_names
    assert "record_case_action" in all_tool_names
    assert "adjudicate_case" in all_tool_names
    assert "query_policy" in all_tool_names
    assert "trigger_simulation" in all_tool_names
    assert "check_weather_condition" in all_tool_names
    assert "check_traffic_situation" in all_tool_names
    assert "write_ticket_for_driver" in all_tool_names
    assert "check_related_cases_to_vehicle" in all_tool_names
    assert "get_driver_card" in all_tool_names
    assert "search_policy_documents" in all_tool_names
    assert "get_forensic_brief" in all_tool_names
    assert "get_case_policy" in all_tool_names
    assert "fetch_corridor_historical_traffic" in all_tool_names
    assert "query_traffic_incident_feed" in all_tool_names
    assert len(all_tool_names) == len(set(all_tool_names))

    # Model-bound tools in ANALYST_TOOLS exclude human-only commands per #60/#85
    bound_tool_names = [t.name for t in ANALYST_TOOLS]
    assert "query_cases_db" not in bound_tool_names
    assert "write_ticket_for_driver" not in bound_tool_names
    assert "get_forensic_brief" in bound_tool_names
    assert "get_case_policy" in bound_tool_names
    assert "fetch_corridor_historical_traffic" in bound_tool_names
    assert "query_traffic_incident_feed" in bound_tool_names
    human_only = {
        "claim_case",
        "record_case_action",
        "adjudicate_case",
        "trigger_simulation",
        "query_cases_db",
        "write_ticket_for_driver",
    }
    assert set(bound_tool_names) == set(all_tool_names) - human_only
    assert len(bound_tool_names) == len(set(bound_tool_names))
    # Case-scoped Geoapify tools added for #230 are model-selectable.
    assert "geocode_address" in bound_tool_names
    assert "reverse_geocode_coordinates" in bound_tool_names
    assert "match_trip_telemetry" in bound_tool_names

    # Compile graph with all tools
    graph = build_graph()
    assert graph is not None

    # Query graph about driver status to test fallback & node execution
    state_input = {"query": "Kiểm tra tình trạng tài xế drv_gsm_0001 xem có bị đình chỉ không?"}
    out = await graph.ainvoke(state_input)
    assert (
        "drv_gsm_0001" in out["response"] or "driver" in out["response"].lower() or "tài xế" in out["response"].lower()
    )

"""TDD tests for extended GreenSM Fraud Analyst tools.

Tests 6 key automation tools:
1. check_weather_condition (Open-Meteo real API)
2. check_traffic_situation (OSRM / real routing corridor API)
3. write_ticket_for_driver (Disciplinary ticket issuance & audit persistence)
4. check_related_cases_to_vehicle (Vehicle-linked fraud case history)
5. get_driver_card (Driver credentials card)
6. search_policy_documents (Policy RAG search with citations)
"""

import pytest

from src.agents.tools.analyst_tools import (
    ALL_ANALYST_TOOLS,
    ANALYST_TOOLS,
    check_related_cases_to_vehicle,
    check_traffic_situation,
    check_weather_condition,
    get_driver_card,
    search_policy_documents,
    write_ticket_for_driver,
)


@pytest.mark.asyncio
async def test_extended_analyst_tools_export():
    """Verify that all new tools are exported in ANALYST_TOOLS."""
    tool_names = [t.name for t in ANALYST_TOOLS]
    assert "check_weather_condition" in tool_names
    assert "check_traffic_situation" in tool_names
    assert "check_related_cases_to_vehicle" in tool_names
    assert "get_driver_card" in tool_names
    assert "search_policy_documents" in tool_names
    assert "write_ticket_for_driver" not in tool_names
    assert "write_ticket_for_driver" in [t.name for t in ALL_ANALYST_TOOLS]


@pytest.mark.asyncio
async def test_check_weather_condition_tool():
    """Test check_weather_condition queries Open-Meteo real API or corridor coordinates."""
    # Test Hanoi coordinates
    res = await check_weather_condition.ainvoke({"lat": 21.0285, "lon": 105.8542})
    assert "temperature_c" in res
    assert "precipitation_mm" in res
    assert "condition_desc" in res
    assert "force_majeure" in res
    assert "xml_widget" in res
    assert "<weather_widget>" in res["xml_widget"]
    assert "</weather_widget>" in res["xml_widget"]


@pytest.mark.asyncio
async def test_check_traffic_situation_tool():
    """Test check_traffic_situation queries real routing API and evaluates congestion."""
    res = await check_traffic_situation.ainvoke(
        {
            "start_lat": 21.0285,
            "start_lon": 105.8542,
            "end_lat": 21.0031,
            "end_lon": 105.8048,
        }
    )
    assert "distance_km" in res
    assert "baseline_duration_sec" in res
    assert "congestion_level" in res
    assert "corroborates_delay" in res
    assert "xml_widget" in res
    assert "<traffic_widget>" in res["xml_widget"]
    assert "</traffic_widget>" in res["xml_widget"]


@pytest.mark.asyncio
async def test_write_ticket_for_driver_tool():
    """Test write_ticket_for_driver creates official disciplinary ticket."""
    res = await write_ticket_for_driver.ainvoke(
        {
            "driver_id": "drv-8492-nguyen-van-a",
            "case_id": "018f2f4e-a000-7000-8000-000000000001",
            "violation_code": "ERR-02",
            "penalty_type": "NOTICE",
            "reason": "Co tinh dung yen 210s khong di chuyen de ep khach huy chuyen (DIC)",
            "fine_amount_vnd": 0,
            "suspension_hours": 0,
            "analyst_id": "analyst_senior_01",
        }
    )
    assert res.get("status") == "ISSUED"
    assert res.get("ticket_id", "").startswith("TCK-")
    assert res.get("fine_amount_vnd") == 0
    assert res.get("penalty_type") == "NOTICE"
    assert res.get("violation_code") == "ERR-02"
    assert "xml_widget" in res
    assert "<ticket_preview>" in res["xml_widget"]
    assert "</ticket_preview>" in res["xml_widget"]

    # Verify no FINE is accepted
    with pytest.raises(ValueError):
        await write_ticket_for_driver.ainvoke(
            {
                "driver_id": "drv-8492-nguyen-van-a",
                "case_id": "018f2f4e-a000-7000-8000-000000000001",
                "violation_code": "ERR-02",
                "penalty_type": "FINE",
                "reason": "Co tinh dung yen 210s khong di chuyen de ep khach huy chuyen (DIC)",
                "fine_amount_vnd": 500000,
            }
        )


@pytest.mark.asyncio
async def test_check_related_cases_to_vehicle_tool():
    """Test check_related_cases_to_vehicle retrieves vehicle-associated cases."""
    res = await check_related_cases_to_vehicle.ainvoke(
        {
            "vehicle_plate": "29E-123.45",
            "limit": 5,
        }
    )
    assert "vehicle_plate" in res
    assert res["vehicle_plate"] == "29E-123.45"
    assert "related_cases" in res
    assert isinstance(res["related_cases"], list)
    assert "xml_widget" in res
    assert "<list_selector>" in res["xml_widget"] or "<choice_selector>" in res["xml_widget"]


@pytest.mark.asyncio
async def test_get_driver_card_tool():
    """Test get_driver_card retrieves comprehensive driver operating card."""
    res = await get_driver_card.ainvoke({"driver_identifier": "drv-8492-nguyen-van-a"})
    assert res.get("found") is True
    assert "full_name" in res
    assert "rating" in res
    assert "acceptance_rate" in res
    assert "completion_rate" in res
    assert "xml_widget" in res
    assert "<driver_card>" in res["xml_widget"]
    assert "</driver_card>" in res["xml_widget"]


@pytest.mark.asyncio
async def test_search_policy_documents_tool():
    """Test search_policy_documents returns GreenSM policy citations."""
    res = await search_policy_documents.ainvoke(
        {
            "query": "Quy dinh ve huy chuyen don va dieu kien bat kha khang",
            "category": "car",
        }
    )
    assert "count" in res
    assert res["count"] > 0
    assert "results" in res
    assert len(res["results"]) > 0
    first = res["results"][0]
    assert "title" in first or "section_ref" in first or "source" in first


def test_cockpit_agent_weather_routing():
    """Verify CockpitRAGAgent routes weather queries to check_weather_condition and returns weather widget."""
    from src.rag.cockpit_agent import CockpitRAGAgent

    agent = CockpitRAGAgent(api_key="test-key")
    resp = agent.execute_turn("Kiểm tra thời tiết xem có mưa bão bất khả kháng theo Điều 12.2 không?")
    assert resp.tool_called == "check_weather_condition"
    assert "<weather_widget>" in resp.answer
    assert "</weather_widget>" in resp.answer
    assert resp.status == "success"


def test_cockpit_agent_traffic_routing():
    """Verify CockpitRAGAgent routes traffic queries to check_traffic_situation and returns traffic widget."""
    from src.rag.cockpit_agent import CockpitRAGAgent

    agent = CockpitRAGAgent(api_key="test-key")
    resp = agent.execute_turn("Kiểm tra tình hình giao thông trên tuyến đường có bị ùn tắc kẹt xe không?")
    assert resp.tool_called == "check_traffic_situation"
    assert "<traffic_widget>" in resp.answer
    assert "</traffic_widget>" in resp.answer
    assert resp.status == "success"


def test_cockpit_agent_ticket_routing():
    """Verify CockpitRAGAgent never issues tickets; ticket requests fall back to sanction policy search."""
    from src.rag.cockpit_agent import CockpitRAGAgent

    agent = CockpitRAGAgent(api_key="test-key")
    resp = agent.execute_turn("Lập biên bản xử phạt tài xế drv-8492-nguyen-van-a mức phạt 200000")
    assert resp.tool_called != "write_ticket_for_driver"
    assert "<ticket_preview>" not in resp.answer


def test_cockpit_agent_vehicle_swap_routing():
    """Verify CockpitRAGAgent routes vehicle sharing check and returns list selector widget."""
    from src.rag.cockpit_agent import CockpitRAGAgent

    agent = CockpitRAGAgent(api_key="test-key")
    resp = agent.execute_turn("Kiểm tra các vụ việc liên quan đến xe 29E-123.45 xem có tráo xe không")
    assert resp.tool_called == "check_related_cases_to_vehicle"
    assert "<list_selector>" in resp.answer
    assert "</list_selector>" in resp.answer
    assert resp.status == "success"


@pytest.mark.asyncio
async def test_legacy_ticket_preview_does_not_persist_a_case_action(monkeypatch):
    """The inherited ISSUED preview is not evidence of an audited sanction."""
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    record = AsyncMock()
    monkeypatch.setattr(
        "src.agents.tools.analyst_tools.get_case_service",
        lambda: SimpleNamespace(record_case_action=record),
    )
    result = await write_ticket_for_driver.ainvoke(
        {
            "driver_id": "driver-1",
            "case_id": "case-1",
            "violation_code": "ERR-02",
            "penalty_type": "NOTICE",
            "reason": "Legacy preview characterization only",
        }
    )

    assert result["status"] == "ISSUED"
    record.assert_not_called()

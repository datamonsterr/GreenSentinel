"""Unit tests for driver-scoped LangChain tools (Issue #481).

Verifies:
- list_my_cases(driver_id, status=None)
- get_case_timeline(case_id, driver_id) (status history + response deadline)
- explain_case_status(case_id, driver_id) (plain-language vi/en explanation, never raw codes)
- get_my_scorecard(driver_id) (wrap src/services/driver_service.get_driver_scorecard)
- list_my_trips(driver_id, cursor=None, limit=20, status=None) with clamping 1..50
- get_trip_summary(trip_id, driver_id)
- check_weather_condition (driver-scoped, trip coordinates resolved, LLM coords ignored, ownership verified)
- check_traffic_situation (driver-scoped, trip coordinates resolved, LLM coords ignored, analyst verdict redacted)
- get_forensic_brief (driver-scoped, redacted analyst-only fields, observed abnormalities only, no verdict)
- suggest_dispute_path (advisory guidance with 'có thể viện dẫn Điều 12.2', omit missing metrics, never fraud verdict)
- assess_statement_completeness (NFD-folded diacritic stripping, non-blank strings/dicts corroborations)
- get_appeal_options (no accept_violation action, next steps + deadlines)
- Registration in DRIVER_TOOLS and per-tool input_schema in tool_catalog
- Real LangGraph integration with build_driver_support_agent and execute_scoped_graph_call
"""

from __future__ import annotations

import json
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from src.agents.tools.driver_tools import (
    DRIVER_TOOLS,
    assess_statement_completeness,
    check_traffic_situation,
    check_weather_condition,
    explain_case_status,
    get_appeal_options,
    get_case_timeline,
    get_forensic_brief,
    get_my_scorecard,
    get_trip_summary,
    list_my_cases,
    list_my_trips,
    suggest_dispute_path,
)
from src.services.scenario_seeder import ScenarioSeeder


@pytest.fixture(autouse=True)
def seed_test_scenarios():
    """Ensure clean scenario fixtures exist for each test with full fixture teardown."""
    from src.services.driver_service import _memory_driver_trips, _memory_trip_ratings

    seeder = ScenarioSeeder()
    seeder.seed_in_memory()
    _memory_driver_trips.clear()
    _memory_trip_ratings.clear()
    yield
    seeder.clean_in_memory()
    _memory_driver_trips.clear()
    _memory_trip_ratings.clear()


@pytest.mark.asyncio
async def test_list_my_cases_owned_and_forbidden():
    """Driver lists their own cases, status filter works, and unauthenticated/unscoped driver fails."""
    owned_driver_id = "018f2f4e-b300-7000-8000-000000000001"
    org_id = "018f2f4e-0000-7000-8000-000000000001"
    res = await list_my_cases.ainvoke({"driver_id": owned_driver_id, "organization_id": org_id})
    assert "error" not in res
    assert "cases" in res or "items" in res
    items = res.get("cases") or res.get("items", [])
    assert len(items) >= 1
    assert any(c.get("driver_id") == owned_driver_id for c in items)

    # Empty driver_id should return error dict with FORBIDDEN
    err_res = await list_my_cases.ainvoke({"driver_id": "", "organization_id": org_id})
    assert err_res.get("error_type") == "FORBIDDEN"
    assert err_res.get("status_code") == 403

    # Missing organization_id should return error dict with FORBIDDEN
    org_err = await list_my_cases.ainvoke({"driver_id": owned_driver_id, "organization_id": ""})
    assert org_err.get("error_type") == "FORBIDDEN"
    assert org_err.get("status_code") == 403


@pytest.mark.asyncio
async def test_get_case_timeline():
    """Returns status history and response deadline for owned case, 404 NOT_FOUND for foreign and missing."""
    owned_case_id = "018f2f4e-b000-7000-8000-000000000001"
    owned_driver_id = "018f2f4e-b300-7000-8000-000000000001"
    attacker_driver_id = "018f2f4e-b300-7000-8000-000000000002"

    res = await get_case_timeline.ainvoke({"case_id": owned_case_id, "driver_id": owned_driver_id})
    assert "error" not in res
    assert res.get("case_id") == owned_case_id
    assert "timeline" in res
    assert isinstance(res["timeline"], list)
    assert len(res["timeline"]) >= 1
    assert "response_deadline" in res
    assert res["response_deadline"] is not None

    # Foreign driver access must return NOT_FOUND (404) to prevent existence probing
    forbidden = await get_case_timeline.ainvoke({"case_id": owned_case_id, "driver_id": attacker_driver_id})
    assert forbidden.get("error_type") == "NOT_FOUND"
    assert forbidden.get("status_code") == 404

    # Non-existent case
    missing = await get_case_timeline.ainvoke(
        {"case_id": "018f2f4e-0000-0000-0000-000000000404", "driver_id": owned_driver_id}
    )
    assert missing.get("error_type") == "NOT_FOUND"
    assert missing.get("status_code") == 404


@pytest.mark.asyncio
async def test_explain_case_status_plain_language_no_raw_codes():
    """Returns plain language vi and en status explanations without raw internal codes."""
    owned_case_id = "018f2f4e-b000-7000-8000-000000000001"
    owned_driver_id = "018f2f4e-b300-7000-8000-000000000001"
    attacker_driver_id = "018f2f4e-b300-7000-8000-000000000002"

    res = await explain_case_status.ainvoke({"case_id": owned_case_id, "driver_id": owned_driver_id})
    assert "error" not in res
    assert res.get("case_id") == owned_case_id
    assert "status_explanation_vi" in res
    assert "status_explanation_en" in res

    # Invariant: No raw internal error codes in explanations
    for field in ("status_explanation_vi", "status_explanation_en", "status_label_vi", "status_label_en"):
        text = str(res.get(field, ""))
        for raw_code in ("ERR-01", "ERR-02", "ERR-03", "ERR-04", "ERR-05", "AUTO_DISMISSED", "not_disputed"):
            assert raw_code not in text, f"Raw internal code '{raw_code}' leaked into {field}: {text}"

    # Cross driver returns NOT_FOUND (404) to prevent existence probing
    forbidden = await explain_case_status.ainvoke({"case_id": owned_case_id, "driver_id": attacker_driver_id})
    assert forbidden.get("error_type") == "NOT_FOUND"
    assert forbidden.get("status_code") == 404

    # Missing case
    missing = await explain_case_status.ainvoke(
        {"case_id": "018f2f4e-0000-0000-0000-000000000404", "driver_id": owned_driver_id}
    )
    assert missing.get("error_type") == "NOT_FOUND"
    assert missing.get("status_code") == 404


@pytest.mark.asyncio
async def test_get_my_scorecard():
    """Wraps driver_service.get_driver_scorecard; returns scorecard or NOT_FOUND."""
    owned_driver_id = "018f2f4e-b300-7000-8000-000000000001"
    res = await get_my_scorecard.ainvoke({"driver_id": owned_driver_id})
    assert "error" not in res
    assert res.get("driver_id") == owned_driver_id
    assert "violation_ratio_90d" in res
    assert "repeat_offense_risk_score" in res

    # Unknown driver
    missing = await get_my_scorecard.ainvoke({"driver_id": "018f2f4e-0000-0000-0000-000000000404"})
    assert missing.get("error_type") == "NOT_FOUND"
    assert missing.get("status_code") == 404


@pytest.mark.asyncio
async def test_list_my_trips_clamping_and_get_trip_summary():
    """Tests trips list with limit clamping (1..50) and trip summary with driver ownership."""
    from src.services.driver_service import _memory_driver_trips, _memory_trip_ratings

    test_driver_id = "018f2f4e-b300-7000-8000-000000000001"
    foreign_driver_id = "018f2f4e-b300-7000-8000-000000000002"
    test_trip_id = "018f2f4e-b100-7000-8000-000000000001"

    # Seed in-memory trip and rating for unit test
    _memory_driver_trips[test_trip_id] = {
        "trip_id": test_trip_id,
        "driver_id": test_driver_id,
        "organization_id": "018f2f4e-0000-7000-8000-000000000001",
        "pickup_label": "Vincom Ocean Park, Gia Lâm",
        "pickup_lat": 20.995,
        "pickup_lng": 105.942,
        "dropoff_label": "Hồ Gươm, Hoàn Kiếm",
        "dropoff_lat": 21.028,
        "dropoff_lng": 105.854,
        "started_at": "2026-10-15T08:00:00Z",
        "ended_at": "2026-10-15T08:45:00Z",
        "distance_km": 14.5,
        "duration_min": 45.0,
        "fare_vnd": 185000,
        "payment_method": "wallet",
        "status": "completed",
        "case_id": "018f2f4e-b000-7000-8000-000000000001",
    }
    _memory_trip_ratings[test_trip_id] = {
        "trip_id": test_trip_id,
        "stars": 5,
        "comment": "Tài xế lái xe cẩn thận, xe sạch sẽ",
        "locale": "vi",
        "created_at": "2026-10-15T09:00:00Z",
    }

    # list_my_trips: clamp limit > 50 to 50, < 1 to 1
    trips_res = await list_my_trips.ainvoke({"driver_id": test_driver_id, "limit": 100})
    assert "error" not in trips_res
    trips = trips_res.get("trips", [])
    assert len(trips) >= 1
    assert any(t["trip_id"] == test_trip_id for t in trips)

    trips_res_clamped_low = await list_my_trips.ainvoke({"driver_id": test_driver_id, "limit": 0})
    assert "error" not in trips_res_clamped_low

    # get_trip_summary owned
    summary = await get_trip_summary.ainvoke({"trip_id": test_trip_id, "driver_id": test_driver_id})
    assert "error" not in summary
    assert summary.get("trip_id") == test_trip_id
    assert summary.get("driver_id") == test_driver_id
    assert summary.get("fare_vnd") == 185000
    assert summary.get("rating", {}).get("stars") == 5

    # Cross driver access to trip returns NOT_FOUND (404) to prevent existence probing
    forbidden_trip = await get_trip_summary.ainvoke({"trip_id": test_trip_id, "driver_id": foreign_driver_id})
    assert forbidden_trip.get("error_type") == "NOT_FOUND"
    assert forbidden_trip.get("status_code") == 404

    # Missing trip
    missing_trip = await get_trip_summary.ainvoke(
        {"trip_id": "018f2f4e-0000-0000-0000-000000000404", "driver_id": test_driver_id}
    )
    assert missing_trip.get("error_type") == "NOT_FOUND"
    assert missing_trip.get("status_code") == 404


@pytest.mark.asyncio
async def test_driver_scoped_weather_and_traffic():
    """Weather and traffic wrappers verify driver ownership before delegating and prevent existence probing."""
    owned_case_id = "018f2f4e-b000-7000-8000-000000000001"
    owned_driver_id = "018f2f4e-b300-7000-8000-000000000001"
    attacker_driver_id = "018f2f4e-b300-7000-8000-000000000002"

    # Weather: owned case succeeds
    weather = await check_weather_condition.ainvoke({"case_id": owned_case_id, "driver_id": owned_driver_id})
    assert "error" not in weather
    assert "condition_desc" in weather or "source" in weather

    # Weather: foreign case returns NOT_FOUND (404)
    w_forbidden = await check_weather_condition.ainvoke({"case_id": owned_case_id, "driver_id": attacker_driver_id})
    assert w_forbidden.get("error_type") == "NOT_FOUND"
    assert w_forbidden.get("status_code") == 404

    # Traffic: owned case succeeds
    traffic = await check_traffic_situation.ainvoke({"case_id": owned_case_id, "driver_id": owned_driver_id})
    assert "error" not in traffic
    assert "route_distance_km" in traffic or "source" in traffic
    # Traffic: analyst-only verdict redacted
    assert traffic.get("verdict") is None

    # Traffic: foreign case returns NOT_FOUND (404)
    t_forbidden = await check_traffic_situation.ainvoke({"case_id": owned_case_id, "driver_id": attacker_driver_id})
    assert t_forbidden.get("error_type") == "NOT_FOUND"
    assert t_forbidden.get("status_code") == 404


@pytest.mark.asyncio
async def test_trip_branch_weather_and_traffic_ignores_llm_coords():
    """Trip branch resolves coordinates from verified trip summary and ignores LLM coordinates."""
    from src.services.driver_service import _memory_driver_trips

    test_driver_id = "018f2f4e-b300-7000-8000-000000000001"
    test_trip_id = "018f2f4e-b100-7000-8000-000000000002"

    _memory_driver_trips[test_trip_id] = {
        "trip_id": test_trip_id,
        "driver_id": test_driver_id,
        "pickup_label": "Hà Nội",
        "pickup_lat": 21.028,
        "pickup_lng": 105.854,
        "dropoff_label": "Nội Bài",
        "dropoff_lat": 21.218,
        "dropoff_lng": 105.804,
        "started_at": "2026-10-15T10:00:00Z",
        "ended_at": "2026-10-15T11:00:00Z",
        "status": "completed",
    }

    # Pass fake coordinates (99.9, 99.9) - tool must resolve real coordinates from trip and succeed
    weather = await check_weather_condition.ainvoke(
        {"trip_id": test_trip_id, "driver_id": test_driver_id, "lat": 99.9, "lon": 99.9}
    )
    assert "error" not in weather
    assert weather.get("latitude") == 21.028
    assert weather.get("longitude") == 105.854

    traffic = await check_traffic_situation.ainvoke(
        {
            "trip_id": test_trip_id,
            "driver_id": test_driver_id,
            "start_lat": 99.9,
            "start_lon": 99.9,
            "end_lat": -99.9,
            "end_lon": -99.9,
        }
    )
    assert "error" not in traffic
    assert traffic.get("origin") == [21.028, 105.854]
    assert traffic.get("destination") == [21.218, 105.804]
    assert traffic.get("verdict") is None


@pytest.mark.asyncio
async def test_driver_scoped_forensic_brief_redaction():
    """Forensic brief redacts analyst-only fields, returns observed abnormalities only, no verdict."""
    owned_case_id = "018f2f4e-b000-7000-8000-000000000001"
    owned_driver_id = "018f2f4e-b300-7000-8000-000000000001"
    attacker_driver_id = "018f2f4e-b300-7000-8000-000000000002"

    brief = await get_forensic_brief.ainvoke({"case_id": owned_case_id, "driver_id": owned_driver_id})
    assert "error" not in brief
    assert brief.get("case_id") == owned_case_id
    assert "abnormalities" in brief or "observed_abnormalities" in brief

    # Redactions: analyst-only fields must NOT be present
    assert "motivation_assessment" not in brief, "motivation_assessment must be redacted from driver view"
    assert "active_guardrails" not in brief, "active_guardrails must be redacted from driver view"
    assert brief.get("observed_only") is True
    assert brief.get("verdict") is None

    # Cross driver returns NOT_FOUND (404)
    forbidden = await get_forensic_brief.ainvoke({"case_id": owned_case_id, "driver_id": attacker_driver_id})
    assert forbidden.get("error_type") == "NOT_FOUND"
    assert forbidden.get("status_code") == 404


@pytest.mark.asyncio
async def test_suggest_dispute_path_wording_and_omits_missing_metrics():
    """Suggests advisory guidance using 'có thể viện dẫn Điều 12.2', no promise of exemption, omits missing metrics."""
    owned_case_id = "018f2f4e-b000-7000-8000-000000000001"
    owned_driver_id = "018f2f4e-b300-7000-8000-000000000001"
    attacker_driver_id = "018f2f4e-b300-7000-8000-000000000002"

    res = await suggest_dispute_path.ainvoke({"case_id": owned_case_id, "driver_id": owned_driver_id})
    assert "error" not in res
    assert res.get("case_id") == owned_case_id
    assert res.get("advisory") is True
    assert "suggestion" in res
    assert "reasoning" in res
    reasoning = res["reasoning"]

    # Must contain 'có thể viện dẫn Điều 12.2' and NOT promise exemption
    assert "có thể viện dẫn điều 12.2" in reasoning.lower() or "có thể viện dẫn Điều 12.2" in reasoning
    assert "để được miễn trừ trách nhiệm" not in reasoning.lower()

    # Must not output "None km/h" or "Nonex"
    assert "none km/h" not in reasoning.lower()
    assert "nonex" not in reasoning.lower()

    # Cross driver returns NOT_FOUND (404)
    forbidden = await suggest_dispute_path.ainvoke({"case_id": owned_case_id, "driver_id": attacker_driver_id})
    assert forbidden.get("error_type") == "NOT_FOUND"
    assert forbidden.get("status_code") == 404


@pytest.mark.asyncio
async def test_assess_statement_completeness_vietnamese_diacritics_and_blank_corroborations():
    """NFD-folds and strips diacritics for generic pattern detection; enforces non-blank corroborations."""
    # 1. Vietnamese diacritics in generic phrase (e.g. 'Tôi không làm gì sai')
    res_generic_vi = await assess_statement_completeness.ainvoke(
        {
            "incident_type": "traffic",
            "description": "Tôi không làm gì sai cả",
            "corroborations": ["traffic_incident_feed"],
            "no_evidence_declared": False,
        }
    )
    assert res_generic_vi["complete"] is False
    assert any("description is too generic" in item for item in res_generic_vi["missing_items"])

    # 2. Another Vietnamese generic phrase
    res_generic_vi2 = await assess_statement_completeness.ainvoke(
        {
            "incident_type": "traffic",
            "description": "Tôi không biết gì hết trơn luôn",
            "corroborations": ["traffic_incident_feed"],
            "no_evidence_declared": False,
        }
    )
    assert res_generic_vi2["complete"] is False

    # 3. Blank strings or empty dicts in corroborations must be rejected
    res_blank_corrob = await assess_statement_completeness.ainvoke(
        {
            "incident_type": "traffic",
            "description": "Đoạn đường Giải Phóng bị tắc nghẽn kéo dài hơn 45 phút do va chạm",
            "corroborations": ["", "   ", {}],
            "no_evidence_declared": False,
        }
    )
    assert res_blank_corrob["complete"] is False
    assert any("corroborations" in item for item in res_blank_corrob["missing_items"])

    # 4. Valid string or non-empty dict corroboration accepted
    res_valid_corrob = await assess_statement_completeness.ainvoke(
        {
            "incident_type": "traffic",
            "description": "Đoạn đường Giải Phóng bị tắc nghẽn kéo dài hơn 45 phút do va chạm",
            "corroborations": [{"type": "image", "url": "https://example.com/proof.jpg"}],
            "no_evidence_declared": False,
        }
    )
    assert res_valid_corrob["complete"] is True


@pytest.mark.asyncio
async def test_get_appeal_options_no_accept_violation():
    """Returns appeal options without the accept_violation action (deferred to #483)."""
    owned_case_id = "018f2f4e-b000-7000-8000-000000000001"
    owned_driver_id = "018f2f4e-b300-7000-8000-000000000001"
    attacker_driver_id = "018f2f4e-b300-7000-8000-000000000002"

    res = await get_appeal_options.ainvoke({"case_id": owned_case_id, "driver_id": owned_driver_id})
    assert "error" not in res
    assert res.get("case_id") == owned_case_id
    assert "options" in res
    actions = [opt.get("action") for opt in res["options"]]
    assert "accept_violation" not in actions, "accept_violation must be removed (lands in #483)"
    assert "reject_and_explain" in actions
    assert "request_assistance" in actions

    # Cross driver returns NOT_FOUND (404)
    forbidden = await get_appeal_options.ainvoke({"case_id": owned_case_id, "driver_id": attacker_driver_id})
    assert forbidden.get("error_type") == "NOT_FOUND"
    assert forbidden.get("status_code") == 404


def test_driver_tools_driver_id_removed_from_llm_schema():
    """driver_id must be excluded from the LLM-visible schema for all driver tools."""
    for tool_obj in DRIVER_TOOLS:
        args_schema = tool_obj.args
        assert "driver_id" not in args_schema, f"driver_id leaked into LLM schema of tool {tool_obj.name}"


def test_tool_catalog_per_tool_input_schema():
    """Each driver tool must have a dedicated input_schema with correct required fields."""
    from src.services.tool_catalog import get_tool_catalog

    catalog = {e.canonical_id: e for e in get_tool_catalog()}

    expected_schemas = {
        "list_my_cases": ({"status"}, []),
        "get_case_timeline": ({"case_id"}, ["case_id"]),
        "explain_case_status": ({"case_id", "locale"}, ["case_id"]),
        "get_my_scorecard": (set(), []),
        "list_my_trips": ({"cursor", "limit", "status"}, []),
        "get_trip_summary": ({"trip_id"}, ["trip_id"]),
        "get_forensic_brief": ({"case_id"}, ["case_id"]),
        "suggest_dispute_path": ({"case_id"}, ["case_id"]),
        "assess_statement_completeness": (
            {"incident_type", "description", "corroborations", "no_evidence_declared"},
            ["incident_type", "description"],
        ),
        "get_appeal_options": ({"case_id"}, ["case_id"]),
    }

    for tid, (expected_props, expected_req) in expected_schemas.items():
        assert tid in catalog, f"Missing tool {tid} in catalog"
        entry = catalog[tid]
        props = set(entry.input_schema.get("properties", {}).keys())
        req = entry.input_schema.get("required", [])
        assert expected_props.issubset(props), f"Tool {tid} schema missing properties: {expected_props - props}"
        for r in expected_req:
            assert r in req, f"Tool {tid} schema missing required field {r}"


@pytest.mark.asyncio
async def test_driver_agent_graph_integration_with_fake_llm(monkeypatch):
    """Integration agent run using real build_driver_support_agent with execute_scoped_graph_call."""
    from src.agents.driver_agent import build_driver_support_agent
    from src.services.driver_service import _memory_driver_trips

    test_case_id = "018f2f4e-b000-7000-8000-000000000001"
    test_driver_id = "018f2f4e-b300-7000-8000-000000000001"
    test_trip_id = "018f2f4e-b100-7000-8000-000000000001"

    _memory_driver_trips[test_trip_id] = {
        "trip_id": test_trip_id,
        "driver_id": test_driver_id,
        "pickup_label": "Hà Nội",
        "dropoff_label": "Nội Bài",
        "started_at": "2026-10-15T08:00:00Z",
        "status": "completed",
    }

    # All 12 new tools to exercise
    tool_calls_to_run = [
        {"name": "list_my_cases", "args": {}},
        {"name": "get_case_timeline", "args": {"case_id": test_case_id}},
        {"name": "explain_case_status", "args": {"case_id": test_case_id}},
        {"name": "get_my_scorecard", "args": {}},
        {"name": "list_my_trips", "args": {"limit": 10}},
        {"name": "get_trip_summary", "args": {"trip_id": test_trip_id}},
        {"name": "check_weather_condition", "args": {"case_id": test_case_id}},
        {"name": "check_traffic_situation", "args": {"case_id": test_case_id}},
        {"name": "get_forensic_brief", "args": {"case_id": test_case_id}},
        {"name": "suggest_dispute_path", "args": {"case_id": test_case_id}},
        {
            "name": "assess_statement_completeness",
            "args": {
                "incident_type": "traffic",
                "description": "Ùn tắc giao thông cục bộ trên đường Giải Phóng kéo dài hơn 45 phút",
                "no_evidence_declared": True,
            },
        },
        {"name": "get_appeal_options", "args": {"case_id": test_case_id}},
    ]

    for tc in tool_calls_to_run:

        class FakeChatModel:
            def __init__(self, target_call):
                self.target_call = target_call

            def bind_tools(self, tools):
                return self

            async def ainvoke(self, messages, config=None):
                if any(getattr(m, "type", "") == "tool" or isinstance(m, ToolMessage) for m in messages):
                    return AIMessage(content="Đã xử lý công cụ thành công.")
                return AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": self.target_call["name"],
                            "args": self.target_call["args"],
                            "id": f"call_{self.target_call['name']}_01",
                        }
                    ],
                )

        import src.agents.driver_agent as da

        monkeypatch.setattr(da, "get_driver_chat_model", lambda settings=None, call=tc: FakeChatModel(call))

        # Real compiled graph with awrap_tool_call=execute_scoped_graph_call
        agent = build_driver_support_agent()

        runtime_context = {
            "actor_id": test_driver_id,
            "organization_id": "018f2f4e-0000-7000-8000-000000000001",
            "roles": ["driver"],
            "case_id": test_case_id,
            "driver_id": test_driver_id,
            "request_id": str(uuid4()),
            "run_id": str(uuid4()),
            "turn_id": str(uuid4()),
        }

        result = await agent.ainvoke(
            {
                "case_id": test_case_id,
                "runtime_context": runtime_context,
                "messages": [HumanMessage(content=f"Chạy công cụ {tc['name']}")],
                "system_prompt": "Test system prompt",
            }
        )

        tool_msgs = [m for m in result["messages"] if getattr(m, "type", "") == "tool" or isinstance(m, ToolMessage)]
        assert len(tool_msgs) >= 1, f"No tool message emitted for {tc['name']}"
        payload = json.loads(tool_msgs[0].content)

        # Assert tool body ran and succeeded (no SOURCE_UNAVAILABLE, no 503 No adapter)
        assert payload.get("status") == "succeeded", f"Tool {tc['name']} failed to execute: {payload}"
        assert payload.get("data") is not None, f"Tool {tc['name']} returned null data: {payload}"

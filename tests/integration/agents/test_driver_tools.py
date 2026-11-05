"""TDD Tests for Driver Tools (Slice 1).

Tests the 4 driver-facing LangChain tools:
1. get_driver_dispute_context
2. corroborate_traffic_conditions
3. submit_driver_statement
4. query_driver_policy
"""

import pytest

from src.agents.tools.driver_tools import (
    ALL_DRIVER_TOOLS,
    DRIVER_TOOLS,
    corroborate_traffic_conditions,
    get_driver_dispute_context,
    query_driver_policy,
    submit_driver_statement,
)
from src.services.case_service import get_case_service
from src.services.driver_dispute_service import get_driver_dispute_service

pytestmark = pytest.mark.docker


@pytest.fixture
def case_service():
    return get_case_service()


@pytest.fixture
def dispute_service():
    return get_driver_dispute_service()


@pytest.mark.asyncio
async def test_driver_tools_export():
    """Verify that all 4 driver tools are exported in DRIVER_TOOLS."""
    tool_names = [t.name for t in DRIVER_TOOLS]
    assert "get_driver_dispute_context" in tool_names
    assert "corroborate_traffic_conditions" in tool_names
    assert "inspect_trip_telemetry" in tool_names
    assert "verify_exoneration_rules" in tool_names
    assert "submit_driver_statement" in [t.name for t in ALL_DRIVER_TOOLS]
    assert "query_driver_policy" in tool_names
    assert len(DRIVER_TOOLS) >= 4
    assert "submit_driver_statement" not in tool_names


@pytest.mark.asyncio
async def test_get_driver_dispute_context_tool(case_service):
    """Test get_driver_dispute_context returns required context schema."""
    case_ids = list(case_service._cases.keys())
    assert len(case_ids) > 0
    case_id = case_ids[0]
    case = case_service._cases[case_id]
    asgn = case_service._assignments.get(str(case.get("assignment_id")), {})
    driver_id = str(asgn.get("driver_id", ""))

    res = await get_driver_dispute_context.ainvoke({"case_id": case_id, "driver_id": driver_id})

    assert "case_id" in res
    assert res["case_id"] == case_id
    assert "driver_id" in res
    assert "driver_name" in res
    assert "trip_id" in res
    assert "violation_code" in res
    assert "violation_title" in res
    assert "dispute_status" in res
    assert "allowed_claim_types" in res
    assert isinstance(res["allowed_claim_types"], list)
    assert "traffic_gridlock" in res["allowed_claim_types"]


@pytest.mark.asyncio
async def test_corroborate_traffic_conditions_tool(case_service, dispute_service):
    """Test corroborate_traffic_conditions returns metrics (speed, ratio, congestion)."""
    case_ids = list(case_service._cases.keys())
    case_id = case_ids[0]
    dispute_service._traffic_overrides[case_id] = {
        "observed_speed": 4.2,
        "ratio": 2.1,
        "congestion_level": "heavy",
        "gps_valid": True,
        "prior_sanctions": 0,
    }

    res = await corroborate_traffic_conditions.ainvoke({"case_id": case_id})

    assert "case_id" in res
    assert "corroborated" in res
    assert isinstance(res["corroborated"], bool)
    assert "ratio" in res
    assert isinstance(res["ratio"], (int, float))
    assert "observed_speed" in res
    assert isinstance(res["observed_speed"], (int, float))
    assert "congestion_level" in res


@pytest.mark.asyncio
async def test_submit_driver_statement_corroborated(case_service, dispute_service):
    """Test autonomous exoneration when traffic conditions are corroborated."""
    # Setup a case with corroborated traffic
    case_id = "test-corrob-case-001"
    driver_id = "drv-corrob-001"
    asgn_id = "asgn-corrob-001"

    case_service._drivers[driver_id] = {
        "id": driver_id,
        "display_name": "Nguyễn Văn Corrob",
        "account_status": "active",
    }
    case_service._assignments[asgn_id] = {
        "id": asgn_id,
        "driver_id": driver_id,
        "trip_id": "trip-corrob-001",
    }
    case_service._cases[case_id] = {
        "id": case_id,
        "assignment_id": asgn_id,
        "status": "ready",
        "dispute_status": "not_disputed",
        "suspected_category": "ERR-01",
        "priority_score": 50,
        "priority_tier": 1,
        "priority_rule_version": "v1",
        "version": 1,
    }

    # Corroborated conditions: speed 3.0 km/h, ratio 2.5, congestion heavy, valid GPS, 0 sanctions
    dispute_service._traffic_overrides[case_id] = {
        "observed_speed": 3.0,
        "ratio": 2.5,
        "congestion_level": "heavy",
        "gps_valid": True,
        "prior_sanctions": 0,
    }

    # Calling without a token fails and does nothing
    res_no_token = await submit_driver_statement.ainvoke(
        {
            "case_id": case_id,
            "driver_id": driver_id,
            "reason": "Kẹt xe nghiêm trọng tại ngã tư",
            "claim_type": "traffic_gridlock",
        }
    )
    assert res_no_token["status"] == "failed"
    assert case_service._cases[case_id]["status"] == "ready"
    assert case_service._cases[case_id]["dispute_status"] == "not_disputed"

    # Issue confirmation token through the service
    token = await dispute_service.issue_confirmation_token(
        case_id=case_id,
        driver_id=driver_id,
        action="submit_statement",
    )

    res = await submit_driver_statement.ainvoke(
        {
            "case_id": case_id,
            "driver_id": driver_id,
            "reason": "Kẹt xe nghiêm trọng tại ngã tư",
            "claim_type": "traffic_gridlock",
            "confirmation_token": token,
        }
    )

    assert res["case_id"] == case_id
    assert res["is_auto_dismissed"] is False
    assert res["dispute_status"] == "pending_review"
    assert res["exoneration_receipt"] is None
    assert res["needs_analyst_review"] is True
    assert case_service._cases[case_id]["status"] == "pending_analyst_review"
    assert case_service._cases[case_id]["dispute_status"] == "pending_review"


@pytest.mark.asyncio
async def test_submit_driver_statement_uncorroborated_escalates(case_service, dispute_service):
    """Test uncorroborated traffic claim escalates to analyst review without auto-sanction."""
    case_id = "test-uncorrob-case-002"
    driver_id = "drv-uncorrob-002"
    asgn_id = "asgn-uncorrob-002"

    case_service._drivers[driver_id] = {
        "id": driver_id,
        "display_name": "Trần Văn Fast",
        "account_status": "active",
    }
    case_service._assignments[asgn_id] = {
        "id": asgn_id,
        "driver_id": driver_id,
        "trip_id": "trip-uncorrob-002",
    }
    case_service._cases[case_id] = {
        "id": case_id,
        "assignment_id": asgn_id,
        "status": "ready",
        "dispute_status": "not_disputed",
        "suspected_category": "ERR-01",
        "priority_score": 50,
        "priority_tier": 1,
        "priority_rule_version": "v1",
        "version": 1,
    }

    # Normal traffic: speed 25.0 km/h, ratio 1.1 -> Uncorroborated
    dispute_service._traffic_overrides[case_id] = {
        "observed_speed": 25.0,
        "ratio": 1.1,
        "congestion_level": "clear",
        "gps_valid": True,
        "prior_sanctions": 0,
    }

    # Calling without a token fails and does nothing
    res_no_token = await submit_driver_statement.ainvoke(
        {
            "case_id": case_id,
            "driver_id": driver_id,
            "reason": "Tắc đường không đi nhanh được",
            "claim_type": "traffic_gridlock",
        }
    )
    assert res_no_token["status"] == "failed"
    assert case_service._cases[case_id]["status"] == "ready"
    assert case_service._cases[case_id]["dispute_status"] == "not_disputed"

    # Issue confirmation token through the service
    token = await dispute_service.issue_confirmation_token(
        case_id=case_id,
        driver_id=driver_id,
        action="submit_statement",
    )

    res = await submit_driver_statement.ainvoke(
        {
            "case_id": case_id,
            "driver_id": driver_id,
            "reason": "Tắc đường không đi nhanh được",
            "claim_type": "traffic_gridlock",
            "confirmation_token": token,
        }
    )

    assert res["case_id"] == case_id
    assert res["is_auto_dismissed"] is False
    assert res["dispute_status"] == "in_dispute"
    assert res["exoneration_receipt"] is None
    assert res["needs_analyst_review"] is True
    assert case_service._cases[case_id]["status"] == "driver_disputed"
    assert case_service._cases[case_id]["dispute_status"] == "in_dispute"


@pytest.mark.asyncio
async def test_query_driver_policy_tool():
    """Test query_driver_policy returns driver-friendly guidance and policy citations."""
    res = await query_driver_policy.ainvoke({"query": "khiếu nại kẹt xe tắc đường"})

    assert "query" in res
    assert "summary" in res
    assert "relevant_policies" in res
    assert isinstance(res["relevant_policies"], list)
    assert "guidance_for_driver" in res

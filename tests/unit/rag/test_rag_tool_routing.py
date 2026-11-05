"""Tests verifying that the RAG agent routes each user prompt to the correct corresponding tool."""

import pytest

from src.rag.cockpit_agent import CockpitRAGAgent


@pytest.fixture(scope="module")
def agent():
    """Create an isolated agent with an empty, non-seeded policy store."""

    class EmptyPolicyStore:
        last_search_error = None

        def search(self, **_kwargs):
            return []

    return CockpitRAGAgent(api_key="test-key", store=EmptyPolicyStore())


@pytest.mark.parametrize(
    ("prompt", "expected_tool"),
    [
        # 1. Case Information
        (
            "Show me the case information and dossier for 018f2f4e-a000-7000-8000-000000000001",
            "get_case_information",
        ),
        (
            "Retrieve case detail for 018f2f4e-a000-7000-8000-000000000010 from database",
            "get_case_information",
        ),
        # 2. Driver Profile
        (
            "Retrieve driver profile from db for Nguyen Van A (plate 29E-123.45)",
            "get_driver_profile",
        ),
        (
            "Show me the driver profile and credential standing for drv-8492-nguyen-van-a",
            "get_driver_profile",
        ),
        # 3. Telemetry
        (
            "Show telemetry and GPS points coordinates for trip 018f2f4e-8000-7000-8000-000000000001",
            "get_telemetry",
        ),
        (
            "Retrieve high-frequency GPS points and mock location flags for assignment 018f2f4e-9000-7000-8000-000000000010",
            "get_telemetry",
        ),
        # 4. Case List / Priority Queue
        (
            "Show me the priority queue of cases by priority",
            "get_case_list_priority",
        ),
        (
            "List cases in the triage queue for P0 cases",
            "get_case_list_priority",
        ),
        # 5. Audit Log
        (
            "Retrieve audit log and review actions for case 018f2f4e-a000-7000-8000-000000000001",
            "get_audit_log",
        ),
        (
            "Show the history log of analyst actions and adjudication audit for 018f2f4e-a000-7000-8000-000000000010",
            "get_audit_log",
        ),
        # 6. Policy Document Search
        (
            "What is the compensation policy for damaged luggage on GreenSM Car?",
            "search_policy_documents",
        ),
        (
            "What are the official terms of use and minimum age required to ride GreenSM?",
            "search_policy_documents",
        ),
        (
            "What is the history of GreenSM and when was it founded?",
            "search_policy_documents",
        ),
        # 7. Driver Trip History
        (
            "What is the past trip history and stall records for drv-8492-nguyen-van-a?",
            "get_driver_trip_history",
        ),
        # 8. Driver Suspension Check
        (
            "Check driver suspension status and standing for drv-6643-vu-duc-thanh",
            "check_driver_suspension",
        ),
    ],
)
def test_rag_agent_tool_routing_accuracy(agent, prompt, expected_tool):
    tool_name, _args = agent._offline_route(prompt)
    assert tool_name == expected_tool, f"Expected '{expected_tool}', received '{tool_name}' for: {prompt}"


def test_rag_agent_policy_search_category_extraction(agent):
    """Verify category parameter is accurately inferred during policy search."""
    res_bike = agent.execute_turn("What are the luggage weight limits for GreenSM Bike delivery?")
    assert res_bike.raw_tool_data.get("tool_called") == "search_policy_documents"
    tool_args = res_bike.raw_tool_data.get("tool_args", {})
    assert tool_args.get("category") == "general"


def test_agent_does_not_offer_decision_or_simulation_tools(agent):
    response = agent.execute_turn("Adjudicate this case and suspend the driver")
    assert response.tool_called not in {"adjudicate_case", "trigger_simulation"}

"""Unit and integration tests for Forensic Brief aggregation and Case Policy AI tool adapters."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from src.main import app
from src.rag.cockpit_agent import CockpitRAGAgent
from src.rag.db_tools import get_case_policy, get_forensic_brief
from src.services.case_service import CaseService


class EmptyPolicyStore:
    last_search_error = None

    def search(self, **_kwargs):
        return []


def test_forensic_brief_summarizes_exact_observed_abnormalities_without_judgment():
    service = CaseService()
    case_id = next(iter(service._cases.keys()))
    brief = CaseService.build_forensic_brief_from_data(
        case_id=case_id,
        trip_id="trip-test-1",
        assignment_id="asgn-test-1",
        driver_id="drv-test-1",
        suspected_category="cancel_abuse",
        trip={
            "status": "cancelled",
            "cancellation_actor": "passenger",
            "cancellation_reason": "driver_not_moving",
        },
        features={
            "stationary_duration_s": 265,
            "davi": -0.42,
            "max_gap_s": 78,
            "telemetry_coverage": 0.68,
            "features": {
                "distance_to_pickup_start_m": 620.0,
                "distance_to_pickup_end_m": 645.0,
            },
            "quality_flags": ["mock_provider_active"],
        },
        telemetry=[
            {
                "speed_mps": 0.0,
                "accuracy_m": 12.0,
                "app_state": "foreground",
                "network_state": "online",
                "gps_state": "valid",
                "mock_location_reported": False,
            },
            {
                "speed_mps": 35.0,
                "accuracy_m": 140.0,
                "app_state": "crashed",
                "network_state": "offline",
                "gps_state": "mock_reported",
                "mock_location_reported": True,
            },
        ],
        missingness_alerts=[
            {
                "alert_id": "gap-1",
                "start_time": "2026-09-25T08:00:00Z",
                "end_time": "2026-09-25T08:01:18Z",
                "gap_duration_s": 78,
                "reason": "Telemetry dropout",
                "severity": "warning",
            }
        ],
        guardrails={
            "blocking_guardrail": True,
            "active_guardrails": ["heavy_congestion_detected"],
            "platform_incident": {"incident_type": "gridlock", "severity": "high"},
        },
    )

    assert brief.case_id == case_id
    assert brief.abnormality_count > 0
    codes = {a.code for a in brief.abnormalities}
    assert "stationary_stall" in codes
    assert "negative_davi" in codes
    assert "telemetry_gap" in codes
    assert "low_telemetry_coverage" in codes
    assert "mock_location_reported" in codes
    assert "app_state_crashed" in codes
    assert "network_degradation" in codes
    assert "gps_jitter" in codes
    assert "speed_anomaly" in codes
    assert "platform_incident_gridlock" in codes
    assert "heavy_congestion_detected" in codes
    assert "trip_cancellation" in codes

    # Must not contain judgmental or sanction language
    lower_summary = brief.summary_text.lower()
    for forbidden in ("guilty", "innocent", "suspend", "đình chỉ", "phạt tiền", "approve", "dismiss"):
        assert forbidden not in lower_summary


def test_db_tools_get_forensic_brief_and_get_case_policy():
    service = CaseService()
    case_id = next(iter(service._cases.keys()))

    brief_res = get_forensic_brief(case_id, service=service)
    assert brief_res["found"] is True
    assert brief_res["case_id"] == case_id
    assert "summary_text" in brief_res["forensic_brief"]
    assert isinstance(brief_res["forensic_brief"]["abnormalities"], list)

    policy_res = get_case_policy(case_id, service=service)
    assert policy_res["found"] is True
    assert policy_res["case_id"] == case_id
    cp = policy_res["case_policy"]
    assert cp["policy_version"] is not None
    assert isinstance(cp["clauses"], list)
    assert len(cp["clauses"]) >= 1


def test_cockpit_agent_reads_policy_data_of_specific_case():
    agent = CockpitRAGAgent(api_key="test-key", store=EmptyPolicyStore())
    service = CaseService()
    case_id = next(iter(service._cases.keys()))

    # 1. Explicit case policy query routes to get_case_policy and returns case policy clauses
    resp_direct = agent.execute_turn(
        f"Cho xem case policy áp dụng cho hồ sơ {case_id}",
        case_id=case_id,
    )
    assert resp_direct.tool_called == "get_case_policy"
    assert resp_direct.status == "success"
    assert len(resp_direct.citations) >= 1
    assert case_id in resp_direct.answer

    # 2. General policy query in Cockpit with case_id context enriches from case policy data even when Qdrant store is empty
    resp_contextual = agent.execute_turn(
        "Quy định xử lý vi phạm hủy chuyến áp dụng thế nào?",
        case_id=case_id,
    )
    assert resp_contextual.tool_called == "search_policy_documents"
    assert resp_contextual.status == "success"
    assert len(resp_contextual.citations) >= 1
    assert "case_policy" in resp_contextual.raw_tool_data


def test_cockpit_agent_routes_forensic_brief_query():
    agent = CockpitRAGAgent(api_key="test-key", store=EmptyPolicyStore())
    service = CaseService()
    case_id = next(iter(service._cases.keys()))

    resp = agent.execute_turn(
        "Summarize forensic brief and observed abnormalities for this case",
        case_id=case_id,
    )
    assert resp.tool_called == "get_forensic_brief"
    assert resp.status == "success"
    assert "Forensic Brief" in resp.answer


@pytest.mark.asyncio
async def test_api_forensic_brief_and_case_policy_endpoints():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        cases_resp = await client.get("/api/v1/cases?availability=all")
        assert cases_resp.status_code == 200
        items = cases_resp.json()["items"]
        assert len(items) > 0
        case_id = items[0]["id"]

        # GET /api/v1/cases/{id}/forensic-brief
        fb_resp = await client.get(f"/api/v1/cases/{case_id}/forensic-brief")
        assert fb_resp.status_code == 200
        fb_data = fb_resp.json()
        assert fb_data["case_id"] == case_id
        assert "summary_text" in fb_data
        assert "abnormalities" in fb_data

        # GET /api/v1/cases/{id}/policy
        pol_resp = await client.get(f"/api/v1/cases/{case_id}/policy")
        assert pol_resp.status_code == 200
        pol_data = pol_resp.json()
        assert pol_data["case_id"] == case_id
        assert len(pol_data["clauses"]) >= 1

        # GET /api/v1/cases/{id} includes forensic_brief and case_policy
        detail_resp = await client.get(f"/api/v1/cases/{case_id}")
        assert detail_resp.status_code == 200
        detail_data = detail_resp.json()
        assert detail_data["forensic_brief"]["case_id"] == case_id
        assert detail_data["case_policy"]["case_id"] == case_id


def test_manual_scenarios_intent_routing_and_answers():
    agent = CockpitRAGAgent(api_key="mock", store=EmptyPolicyStore())
    service = CaseService()
    case_id = next(iter(service._cases.keys()))

    # Scenario 1
    resp1 = agent.execute_turn(
        "Cho tôi xem tóm tắt pháp y và quy chế áp dụng cho ca này",
        case_id=case_id,
    )
    assert resp1.status == "success"
    assert resp1.tool_called in ("get_forensic_brief", "get_case_policy")
    assert "Không tìm thấy nội dung chính sách" not in resp1.answer
    assert len(resp1.answer) > 20

    # Scenario 2
    resp2 = agent.execute_turn(
        "Tại sao tài xế dừng xe? Có bị phạt không?",
        case_id=case_id,
    )
    assert resp2.status == "success"
    assert resp2.tool_called == "get_case_policy"
    assert "Không tìm thấy nội dung chính sách" not in resp2.answer
    assert "Dieu 14.2" in resp2.answer or "Quy chế" in resp2.answer or "v2026" in resp2.answer

    # Scenario 3
    resp3 = agent.execute_turn(
        "Check policy on mock location for this case",
        case_id=case_id,
    )
    assert resp3.status == "success"
    assert resp3.tool_called == "get_case_policy"
    assert "Không tìm thấy nội dung chính sách" not in resp3.answer
    assert len(resp3.citations) >= 1


def test_forensic_dossier_prompts_route_to_get_forensic_brief():
    agent = CockpitRAGAgent(api_key="mock", store=EmptyPolicyStore())
    service = CaseService()
    case_id = next(iter(service._cases.keys()))

    # Test explicit "hồ sơ pháp y" prompt
    resp_dossier = agent.execute_turn(
        f"Cho tôi hồ sơ pháp y ca {case_id}",
        case_id=case_id,
    )
    assert resp_dossier.tool_called == "get_forensic_brief"
    assert resp_dossier.status == "success"
    assert "Forensic Brief" in resp_dossier.answer

    # Test alias with "hồ sơ pháp y" without passing explicit case_id
    resp_alias = agent.execute_turn(
        "Cho tôi hồ sơ pháp y ca-8921",
        case_id=None,
    )
    assert resp_alias.tool_called == "get_forensic_brief"
    assert resp_alias.status == "success"
    assert "Forensic Brief" in resp_alias.answer

    # Test safeguard: when tool called is get_case_information but question asks for forensic/pháp y
    resp_safeguard = agent.execute_turn(
        "Cho tôi hồ sơ pháp y và giám định bất thường ca này",
        case_id=case_id,
    )
    assert resp_safeguard.tool_called == "get_forensic_brief"
    assert resp_safeguard.status == "success"


def test_forensic_brief_gap_consistency_and_policy_deadlock_prevention():
    # 1. Gap consistency
    fb_none = CaseService.build_forensic_brief_from_data(
        case_id="case-gap-test-1",
        features={},
        missingness_alerts=[],
    )
    assert fb_none.max_gap_s is None
    assert not any(ab.code == "telemetry_gap" for ab in fb_none.abnormalities)

    fb_alert = CaseService.build_forensic_brief_from_data(
        case_id="case-gap-test-2",
        features={},
        missingness_alerts=[{"gap_duration_s": 42}],
    )
    assert fb_alert.max_gap_s == 42
    assert any(ab.code == "telemetry_gap" for ab in fb_alert.abnormalities)

    fb_zero = CaseService.build_forensic_brief_from_data(
        case_id="case-gap-test-3",
        features={},
        missingness_alerts=[{"gap_duration_s": 0}],
    )
    assert fb_zero.max_gap_s == 0
    assert not any(ab.code == "telemetry_gap" for ab in fb_zero.abnormalities)

    # 2. Deadlock prevention with allow_db_connect=False
    service = CaseService()
    case_id = next(iter(service._cases.keys()))
    policy = service._get_case_policy_sync(case_id, allow_db_connect=False)
    assert policy.case_id == case_id
    assert policy.policy_version is not None

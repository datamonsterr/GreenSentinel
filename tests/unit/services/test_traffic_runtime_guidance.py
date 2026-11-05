"""Hosted runtime must request independent evidence before adjudication."""

from src.services.agent_runtime import (
    SYSTEM,
    _ensure_traffic_policy_guidance,
    _ground_unavailable_incidents,
    _required_traffic_tools,
    _runtime_actor,
)


def test_hosted_prompt_requires_both_sources_and_preserves_human_decision():
    assert "fetch_corridor_historical_traffic" in SYSTEM
    assert "query_traffic_incident_feed" in SYSTEM
    assert "Điều 12.2" in SYSTEM
    assert "unavailable" in SYSTEM
    assert "free-flow" in SYSTEM
    assert "Không tự miễn trừ" in SYSTEM
    assert "get_case_context" in SYSTEM
    assert "inspect_trip_telemetry" in SYSTEM
    assert "không yêu cầu người dùng nhập lại dữ liệu đã có trong hồ sơ" in SYSTEM


def test_hosted_runtime_adds_policy_guard_after_both_traffic_tools():
    answer = _ensure_traffic_policy_guidance(
        "Dữ liệu cho thấy tốc độ hành trình giảm.",
        {"fetch_corridor_historical_traffic", "query_traffic_incident_feed"},
    )

    assert "Điều 12.2" in answer
    assert "không tự động kết luận gian lận" in answer


def test_hosted_runtime_does_not_add_policy_guard_without_both_traffic_tools():
    answer = "Chưa đủ dữ liệu."

    assert _ensure_traffic_policy_guidance(answer, {"fetch_corridor_historical_traffic"}) == answer


def test_explicit_analyst_traffic_request_requires_both_canonical_tools():
    expected = ("fetch_corridor_historical_traffic", "query_traffic_incident_feed")

    assert _required_traffic_tools("Kiểm tra tình trạng kẹt xe và sự cố giao thông", "analyst") == expected
    assert _required_traffic_tools("Check traffic incidents for this route deviation", "analyst") == expected
    assert _required_traffic_tools("Tóm tắt vụ việc", "analyst") == ()
    assert _required_traffic_tools("Kiểm tra kẹt xe", "driver") == ()


def test_canonical_fraud_analyst_role_uses_analyst_runtime():
    assert _runtime_actor(frozenset({"fraud_analyst"})) == "analyst"
    assert _runtime_actor(frozenset({"driver"})) == "driver"


def test_unavailable_incidents_cannot_be_reported_as_absent():
    answer = _ground_unavailable_incidents(
        "Không có sự cố giao thông nào được ghi nhận.",
        {
            "query_traffic_incident_feed": {
                "status": "unavailable",
                "reason": "provider_not_configured",
                "retention": "memory_only",
            },
            "fetch_corridor_historical_traffic": {
                "status": "available",
                "source_type": "first_party_peer_telemetry",
                "peer_count": 3,
                "observed_speed_kmh": 21.6,
                "free_flow_speed_kmh": 26.64,
                "congestion_ratio": 0.189189,
                "congested": False,
            },
        },
    )

    assert "chưa xác minh được sự cố giao thông" in answer
    assert "không có sự cố" not in answer.casefold()
    assert "3 chuyến" in answer
    assert "18,9%" in answer
    assert "Điều 12.2" in answer
    assert "không tự động kết luận gian lận hoặc miễn trừ" in answer


def test_available_incidents_preserve_model_answer():
    answer = "Có một sự cố đang được báo cáo."
    assert (
        _ground_unavailable_incidents(
            answer,
            {"query_traffic_incident_feed": {"status": "available", "incidents": [{}]}},
        )
        == answer
    )

"""Tests for Jev Advisory Anomaly Scoring and Multi-Layer Jev Assessment Service (Issue #71)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.config import Settings
from src.services.jev_assessment_service import (
    JevAssessmentInput,
    JevAssessmentResult,
    JevAssessmentService,
)


@pytest.fixture
def mock_jev_settings():
    return Settings(
        app_env="test",
        project_jev_api_key="sk-or-v1-testkey123456",
        project_jev_model="~typesafe/jev-latest",
        database_url="",
    )


@pytest.fixture
def sample_assessment_input() -> JevAssessmentInput:
    return JevAssessmentInput(
        driver={
            "driver_id": "018f2f4e-3000-7000-8000-000000000001",
            "name": "Nguyễn Văn Tài",
            "rating": 4.88,
            "total_trips": 1240,
            "acceptance_rate": 94.0,
            "cancellation_rate": 2.5,
            "status": "active",
        },
        driver_analytics={
            "dispute_history_count": 1,
            "prior_sanctions_count": 0,
            "historical_cancellation_ratio": 0.02,
        },
        trip_conversation=[
            {"sender": "passenger", "message": "Em đang đứng trước sảnh rồi ạ", "time": "08:15"},
            {"sender": "driver", "message": "Tôi đang tới", "time": "08:16"},
        ],
        driver_reason_and_agent_conversation={
            "driver_reason": "Xe chết máy trên đường Nguyễn Chí Thanh",
            "agent_chat": [
                {"role": "agent", "text": "Hệ thống ghi nhận xe dừng 180s tại phố Kim Mã"},
                {"role": "driver", "text": "Đúng vậy, xe phía trước bị sự cố"},
            ],
        },
        customer_reports=[
            {"actor": "passenger", "complaint": "Tài xế dừng quá lâu không di chuyển đón khách", "rating": 1}
        ],
        telemetry={
            "stationary_duration_s": 240,
            "max_speed_kmh": 0.0,
            "mock_location_reported": False,
            "points_count": 25,
            "maneuvers": [
                {"action": "stop", "duration_s": 240, "location": "Kim Mã"},
            ],
        },
        trip_data={
            "trip_id": "018f2f4e-4000-7000-8000-000000000001",
            "assignment_id": "018f2f4e-5000-7000-8000-000000000001",
            "pickup_address": "54 Liễu Giai, Ba Đình",
            "dropoff_address": "Vincom Bà Triệu, Hai Bà Trưng",
            "lifecycle_state": "cancelled",
            "cancellation_actor": "passenger",
            "cancellation_reason": "Tài xế không di chuyển",
            "fare_amount_vnd": 65000,
        },
    )


def test_jev_assessment_service_structure_and_defaults():
    service = JevAssessmentService()
    assert service.settings is not None
    assert "ERR-01" in service.system_prompt
    assert "ERR-02" in service.system_prompt
    assert "ERR-05" in service.system_prompt
    assert "no_violation" in service.system_prompt


@pytest.mark.asyncio
async def test_jev_assessment_layer1_and_layer2_mock_api(mock_jev_settings, sample_assessment_input):
    """Test Jev two-layer decision via OpenRouter alpha decisions API."""
    service = JevAssessmentService(settings=mock_jev_settings)

    mock_response_payload = {
        "model": "~typesafe/jev-latest",
        "answers": {
            "error_type": {
                "type": "choice",
                "choice": "ERR-02",
                "confidence": 0.98,
                "probabilities": {"ERR-02": 0.98, "ERR-01": 0.01, "no_violation": 0.01},
            },
            "priority_tier": {
                "type": "choice",
                "choice": "P1",
                "confidence": 0.92,
                "probabilities": {"P1": 0.92, "P0": 0.05, "P2": 0.03},
            },
        },
    }

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = mock_response_payload

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_resp) as mock_post:
        result: JevAssessmentResult = await service.assess(sample_assessment_input)

        assert mock_post.called
        assert result.category == "ERR-02"
        assert result.confidence >= 0.90
        assert result.priority == "P1"
        assert result.priority_score >= 80
        assert result.model_used == "~typesafe/jev-latest"
        assert "ERR-02" in result.forensic_brief
        assert result.probabilities["ERR-02"] == 0.98


@pytest.mark.asyncio
async def test_jev_assessment_fallback_on_api_error(mock_jev_settings, sample_assessment_input):
    """Test graceful fallback to calibrated heuristic when OpenRouter returns error."""
    service = JevAssessmentService(settings=mock_jev_settings)

    mock_resp = AsyncMock()
    mock_resp.status_code = 503
    mock_resp.text = "Service Unavailable"

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_resp):
        result = await service.assess(sample_assessment_input)

        # Fallback should accurately detect ERR-02 because stationary_duration_s = 240s
        assert result.category == "ERR-02"
        assert result.confidence >= 0.90
        assert result.priority == "P1"
        assert result.model_used in ("jev_calibrated_heuristic", "jev_fallback")


@pytest.mark.asyncio
async def test_jev_priority_layer_auto_assessment(mock_jev_settings):
    """Test that Layer 2 automatically assigns P0 to Fake GPS and P1 to Prolonged Stall."""
    service = JevAssessmentService(settings=mock_jev_settings)

    # Fake GPS input
    gps_input = JevAssessmentInput(
        telemetry={"mock_location_reported": True, "max_speed_kmh": 140.0, "stationary_duration_s": 0},
        trip_data={"lifecycle_state": "completed"},
    )

    mock_gps_response = {
        "model": "~typesafe/jev-latest",
        "answers": {
            "error_type": {"choice": "ERR-05", "confidence": 0.99, "probabilities": {"ERR-05": 0.99}},
            "priority_tier": {"choice": "P0", "confidence": 0.95, "probabilities": {"P0": 0.95}},
        },
    }

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = mock_gps_response

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_resp):
        result = await service.assess(gps_input)
        assert result.category == "ERR-05"
        assert result.priority == "P0"
        assert result.priority_score >= 95


@pytest.mark.asyncio
async def test_jev_handles_sparse_and_optional_inputs(mock_jev_settings):
    """Verify service handles minimal payload where optional conversation/reports are None."""
    service = JevAssessmentService(settings=mock_jev_settings)
    sparse_input = JevAssessmentInput(
        trip_data={"trip_id": "sparse-001", "lifecycle_state": "completed"},
        telemetry={"stationary_duration_s": 0, "max_speed_kmh": 35.0, "mock_location_reported": False},
    )

    mock_nominal_response = {
        "model": "~typesafe/jev-latest",
        "answers": {
            "error_type": {"choice": "no_violation", "confidence": 0.95, "probabilities": {"no_violation": 0.95}},
            "priority_tier": {"choice": "P2", "confidence": 0.90, "probabilities": {"P2": 0.90}},
        },
    }

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = mock_nominal_response

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_resp):
        result = await service.assess(sparse_input)
        assert result.category == "no_violation"
        assert result.priority == "P2"
        assert result.confidence >= 0.90


@pytest.mark.asyncio
async def test_default_telemetry_assessment_stays_offline():
    """Default test settings must not spend ambient provider credentials."""
    from src.services.telemetry_queue_worker import JevAssessmentAgent

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as post:
        result = await JevAssessmentAgent().assess(
            {"scenario": "driver_stall_cancel", "stationary_duration_s": 210, "points": []}
        )
    post.assert_not_called()
    assert result["category"] == "ERR-02"
    assert result["confidence"] == 0.92

"""Unit tests for Jev model fallback chain, retry backoff, and heuristic fallback gating (Issue #545).

TDD test suite verifying:
1. Primary success (inception/mercury-decide:free).
2. Primary 429 then success on retry.
3. Primary 400 then fallback success (perplexity/pplx-decider-flash-v1.2, fallback_model_used=True).
4. All fail raises JevUnavailableError and no heuristic call when flag is False.
5. Flag True gives heuristic with assessment_source="heuristic_fallback" and WARNING log.
6. TelemetryQueueWorker logs WARNING and tags heuristic result.
"""

from __future__ import annotations

import logging
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from src.config import Settings
from src.services.jev_assessment_service import (
    JevAssessmentInput,
    JevAssessmentService,
    JevUnavailableError,
)
from src.services.telemetry_queue_worker import JevAssessmentAgent


def _make_sample_input() -> JevAssessmentInput:
    return JevAssessmentInput(
        driver={"driver_id": "drv-001", "name": "Test Driver"},
        driver_analytics={"dispute_history_count": 0},
        telemetry={"points": [{"latitude": 21.0, "longitude": 105.8, "speed_mps": 5.0}], "max_speed_kmh": 18.0},
        trip_data={"lifecycle_state": "completed", "trip_id": "trip-001"},
    )


def _make_200_response(
    model_name: str = "inception/mercury-decide:free", category: str = "no_violation"
) -> httpx.Response:
    content = {
        "model": model_name,
        "provider": "Inception",
        "usage": {"input_tokens": 120, "cost": 0.0},
        "answers": {
            "error_type": {"choice": category, "confidence": 0.95, "probabilities": {category: 0.95}},
            "priority_tier": {"choice": "P2", "probabilities": {"P2": 0.95}},
        },
    }
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = 200
    resp.json.return_value = content
    resp.text = '{"status": "ok"}'
    return resp


@pytest.mark.asyncio
async def test_primary_success():
    """Primary model succeeds on first attempt."""
    settings = Settings(
        project_jev_api_key="test-key-real",
        project_jev_model="inception/mercury-decide:free",
        jev_fallback_models=["perplexity/pplx-decider-flash-v1.2"],
        jev_allow_heuristic_fallback=False,
    )
    service = JevAssessmentService(settings=settings)
    inp = _make_sample_input()

    resp_200 = _make_200_response(model_name="inception/mercury-decide:free")

    with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=resp_200) as mock_post:
        result = await service.assess(inp)

        assert mock_post.call_count == 1
        assert result.model_requested == "inception/mercury-decide:free"
        assert result.model_used == "inception/mercury-decide:free"
        assert result.fallback_model_used is False
        assert result.assessment_source == "model"
        assert result.category == "no_violation"
        assert result.input_tokens == 120
        assert len(result.attempts) == 1
        assert result.attempts[0]["model"] == "inception/mercury-decide:free"
        assert result.attempts[0]["status"] == 200


@pytest.mark.asyncio
async def test_primary_429_then_success_on_retry():
    """Primary model returns 429 then succeeds on retry."""
    settings = Settings(
        project_jev_api_key="test-key-real",
        project_jev_model="inception/mercury-decide:free",
        jev_fallback_models=["perplexity/pplx-decider-flash-v1.2"],
        jev_allow_heuristic_fallback=False,
    )
    service = JevAssessmentService(settings=settings)
    inp = _make_sample_input()

    resp_429 = MagicMock(spec=httpx.Response)
    resp_429.status_code = 429
    resp_429.text = "rate limit exceeded"

    resp_200 = _make_200_response(model_name="inception/mercury-decide:free")

    with (
        patch("httpx.AsyncClient.post", new_callable=AsyncMock, side_effect=[resp_429, resp_200]) as mock_post,
        patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep,
    ):
        result = await service.assess(inp)

        assert mock_post.call_count == 2
        assert mock_sleep.call_count == 1
        assert result.model_requested == "inception/mercury-decide:free"
        assert result.model_used == "inception/mercury-decide:free"
        assert result.fallback_model_used is False
        assert result.assessment_source == "model"
        assert len(result.attempts) == 2
        assert result.attempts[0]["status"] == 429
        assert result.attempts[1]["status"] == 200


@pytest.mark.asyncio
async def test_primary_400_then_fallback_success():
    """Primary model returns 400 (context length / max tokens): no retry, fallback model succeeds."""
    settings = Settings(
        project_jev_api_key="test-key-real",
        project_jev_model="inception/mercury-decide:free",
        jev_fallback_models=["perplexity/pplx-decider-flash-v1.2"],
        jev_allow_heuristic_fallback=False,
    )
    service = JevAssessmentService(settings=settings)
    inp = _make_sample_input()

    resp_400 = MagicMock(spec=httpx.Response)
    resp_400.status_code = 400
    resp_400.text = "max_tokens exceeded"

    resp_200 = _make_200_response(model_name="perplexity/pplx-decider-flash-v1.2", category="no_violation")

    with (
        patch("httpx.AsyncClient.post", new_callable=AsyncMock, side_effect=[resp_400, resp_200]) as mock_post,
        patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep,
    ):
        result = await service.assess(inp)

        # Primary 400 had NO retry -> immediately tried fallback model
        assert mock_post.call_count == 2
        assert mock_sleep.call_count == 0
        assert result.model_requested == "inception/mercury-decide:free"
        assert result.model_used == "perplexity/pplx-decider-flash-v1.2"
        assert result.fallback_model_used is True
        assert result.assessment_source == "model"
        assert len(result.attempts) == 2
        assert result.attempts[0]["model"] == "inception/mercury-decide:free"
        assert result.attempts[0]["status"] == 400
        assert result.attempts[1]["model"] == "perplexity/pplx-decider-flash-v1.2"
        assert result.attempts[1]["status"] == 200


@pytest.mark.asyncio
async def test_all_fail_raises_jev_unavailable_error_and_no_heuristic_call():
    """When all models in the chain fail and jev_allow_heuristic_fallback is False, raise JevUnavailableError."""
    settings = Settings(
        project_jev_api_key="test-key-real",
        project_jev_model="inception/mercury-decide:free",
        jev_fallback_models=["perplexity/pplx-decider-flash-v1.2"],
        jev_allow_heuristic_fallback=False,
    )
    service = JevAssessmentService(settings=settings)
    inp = _make_sample_input()

    resp_500 = MagicMock(spec=httpx.Response)
    resp_500.status_code = 500
    resp_500.text = "Internal Server Error"

    with (
        patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=resp_500),
        patch("asyncio.sleep", new_callable=AsyncMock),
        patch.object(service, "_calibrated_heuristic") as mock_heuristic,
    ):
        with pytest.raises(JevUnavailableError) as exc_info:
            await service.assess(inp)

        mock_heuristic.assert_not_called()
        assert len(exc_info.value.attempts) > 0
        # 1 initial + 2 retries = 3 calls per model, 2 models in chain = 6 attempts
        assert len(exc_info.value.attempts) == 6


@pytest.mark.asyncio
async def test_flag_true_gives_heuristic_with_assessment_source_tag_and_warning(caplog):
    """When models fail but jev_allow_heuristic_fallback is True, return heuristic with WARNING and tag."""
    settings = Settings(
        project_jev_api_key="test-key-real",
        project_jev_model="inception/mercury-decide:free",
        jev_fallback_models=["perplexity/pplx-decider-flash-v1.2"],
        jev_allow_heuristic_fallback=True,
    )
    service = JevAssessmentService(settings=settings)
    inp = _make_sample_input()

    resp_503 = MagicMock(spec=httpx.Response)
    resp_503.status_code = 503
    resp_503.text = "Service Unavailable"

    with (
        patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=resp_503),
        patch("asyncio.sleep", new_callable=AsyncMock),
        caplog.at_level(logging.WARNING),
    ):
        result = await service.assess(inp)

        assert result.assessment_source == "heuristic_fallback"
        assert result.model_used == "jev_calibrated_heuristic"
        assert any("calibrated heuristic" in rec.message for rec in caplog.records if rec.levelno == logging.WARNING)


@pytest.mark.asyncio
async def test_telemetry_queue_worker_heuristic_logged_warning_and_tagged(caplog):
    """JevAssessmentAgent logs WARNING and tags assessment_source when heuristic fallback is used."""
    settings = Settings(
        project_jev_api_key="test-key-real",
        project_jev_model="inception/mercury-decide:free",
        jev_fallback_models=["perplexity/pplx-decider-flash-v1.2"],
        jev_allow_heuristic_fallback=True,
    )
    agent = JevAssessmentAgent(settings=settings)
    event_data = {
        "trip_id": "018f2f4e-1000-7000-8000-000000000001",
        "driver_id": "018f2f4e-3000-7000-8000-000000000001",
        "passenger_id": "018f2f4e-2000-7000-8000-000000000001",
        "vehicle_id": "018f2f4e-4000-7000-8000-000000000001",
        "policy_version_id": "018f2f4e-6000-7000-8000-000000000001",
        "points": [],
        "lifecycle_state": "completed",
    }

    resp_503 = MagicMock(spec=httpx.Response)
    resp_503.status_code = 503
    resp_503.text = "Service Unavailable"

    with (
        patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=resp_503),
        patch("asyncio.sleep", new_callable=AsyncMock),
        caplog.at_level(logging.WARNING),
    ):
        res = await agent.assess(event_data, use_llm=False)

        assert res.get("assessment_source") == "heuristic_fallback"
        assert any("heuristic" in rec.message.lower() for rec in caplog.records if rec.levelno == logging.WARNING)


def test_settings_defaults_and_env_parsing(monkeypatch):
    """Verify Settings defaults and env var parsing for Jev models."""
    monkeypatch.delenv("PROJECT_JEV_MODEL", raising=False)
    monkeypatch.delenv("JEV_MODEL", raising=False)
    monkeypatch.delenv("MODEL", raising=False)
    monkeypatch.delenv("JEV_FALLBACK_MODELS", raising=False)
    monkeypatch.delenv("JEV_ALLOW_HEURISTIC_FALLBACK", raising=False)
    monkeypatch.delenv("jev_allow_heuristic_fallback", raising=False)

    s = Settings()
    assert s.project_jev_model == "inception/mercury-decide:free"
    assert s.jev_fallback_models == ["perplexity/pplx-decider-flash-v1.2"]
    assert s.jev_allow_heuristic_fallback is False

    # Comma-separated parsing
    monkeypatch.setenv("JEV_FALLBACK_MODELS", "model-a, model-b,model-c")
    s2 = Settings()
    assert s2.jev_fallback_models == ["model-a", "model-b", "model-c"]

    # Empty string -> empty list
    monkeypatch.setenv("JEV_FALLBACK_MODELS", "")
    s3 = Settings()
    assert s3.jev_fallback_models == []

    # Custom model selection (~typesafe/jev-latest stays selectable)
    monkeypatch.setenv("PROJECT_JEV_MODEL", "~typesafe/jev-latest")
    s4 = Settings()
    assert s4.project_jev_model == "~typesafe/jev-latest"

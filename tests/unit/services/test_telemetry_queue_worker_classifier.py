"""Unit tests for telemetry queue worker classifier integration (Slice W2)."""

from __future__ import annotations

import logging
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from pydantic import BaseModel

from src.config import Settings
from src.services.case_service import CaseService
from src.services.telemetry_queue_worker import (
    process_telemetry_event,
)


class LocalClassifierResult(BaseModel):
    category: str = "ERR-02"
    probabilities: dict[str, float] = {
        "no_violation": 0.05,
        "ERR-01": 0.01,
        "ERR-02": 0.92,
        "ERR-03": 0.01,
        "ERR-04": 0.01,
        "ERR-05": 0.0,
        "insufficient_evidence": 0.0,
    }
    confidence: float = 0.92
    guardrail_blocked: bool = False
    guardrail_reason: str | None = None
    model_version: str = "r3d_v2.1_20261019"
    artifact_sha: str = "d52e52ff"
    feature_ms: float = 12.0
    inference_ms: float = 24.5
    assessment_source: str = "r3d_classifier"


class FakeClassifier:
    def __init__(self, category: str = "ERR-02") -> None:
        self.category = category
        self.model_version = "r3d_v2.1_20261019"

    def predict(self, bundle: dict[str, Any]) -> LocalClassifierResult:
        return LocalClassifierResult(
            category=self.category,
            model_version=self.model_version,
            inference_ms=24.5,
        )


@pytest.fixture
def base_event():
    return {
        "trip_id": "018f2f4e-1000-7000-8000-000000000001",
        "assignment_id": "018f2f4e-2000-7000-8000-000000000001",
        "driver_id": "018f2f4e-3000-7000-8000-000000000001",
        "passenger_id": "018f2f4e-4000-7000-8000-000000000001",
        "vehicle_id": "018f2f4e-5000-7000-8000-000000000001",
        "policy_version_id": "018f2f4e-6000-7000-8000-000000000001",
        "pickup": [105.8542, 21.0285],
        "dropoff": [105.8600, 21.0350],
        "points": [
            {
                "latitude": 21.0285,
                "longitude": 105.8542,
                "speed_mps": 0.0,
                "bearing_deg": 0.0,
                "accuracy_m": 5.0,
                "app_state": "foreground",
                "network_state": "online",
                "gps_state": "valid",
                "mock_location_reported": False,
                "occurred_at": "2026-10-19T10:00:00Z",
            },
            {
                "latitude": 21.0286,
                "longitude": 105.8543,
                "speed_mps": 2.0,
                "bearing_deg": 10.0,
                "accuracy_m": 5.0,
                "app_state": "foreground",
                "network_state": "online",
                "gps_state": "valid",
                "mock_location_reported": False,
                "occurred_at": "2026-10-19T10:00:15Z",
            },
        ],
    }


@pytest.mark.asyncio
async def test_worker_primary_classifier_when_enabled(base_event, caplog):
    caplog.set_level(logging.INFO)
    settings = Settings(
        app_env="test",
        test_auth_enabled=True,
        fraud_classifier_enabled=True,
        classifier_llm_advisory=True,
    )
    fake_classifier = FakeClassifier(category="ERR-02")
    service = CaseService(settings=settings)

    with patch("src.services.classifier_advisory.run_classifier_advisory") as mock_adv:
        from src.models.classifier_api import ClassifierAdvisoryResult

        mock_adv.return_value = ClassifierAdvisoryResult(
            llm_category="ERR-02",
            llm_probabilities={"ERR-02": 0.9},
            llm_model_used="inception/mercury-decide:free",
            llm_latency_ms=400.0,
            advisory_status="ok",
            agreement=True,
        )

        result = await process_telemetry_event(
            base_event,
            case_service=service,
            classifier=fake_classifier,
        )

        assert result["status"] == "processed"
        assert result["category"] == "ERR-02"
        assessment = result["assessment"]
        assert assessment["model_version"] == "r3d_v2.1_20261019"
        assert assessment["inference_ms"] == 24.5
        assert assessment["assessment_source"] == "r3d_classifier"
        assert assessment["advisory"]["llm_category"] == "ERR-02"
        assert assessment["advisory"]["agreement"] is True

        # Check structured log line: trip_ref hashed, no raw trip_id or PII
        log_records = [r.message for r in caplog.records if "CLASSIFIER_ASSESSMENT" in r.message]
        assert len(log_records) == 1
        log_msg = log_records[0]
        assert "ERR-02" in log_msg
        assert "trip_ref" in log_msg
        assert base_event["trip_id"] not in log_msg


@pytest.mark.asyncio
async def test_worker_rollback_path_when_disabled(base_event):
    settings = Settings(
        app_env="test",
        test_auth_enabled=True,
        fraud_classifier_enabled=False,  # Rollback path
    )
    fake_classifier = MagicMock()
    service = CaseService(settings=settings)

    with patch("src.services.telemetry_queue_worker.JevAssessmentAgent.assess") as mock_agent_assess:
        mock_agent_assess.return_value = {
            "category": "ERR-01",
            "confidence": 0.9,
            "priority_tier": 1,
            "priority_label": "P1",
            "priority_score": 85,
            "reason_codes": [],
            "forensic_brief": "Legacy brief",
            "model_used": "legacy-jev",
            "assessment_source": "model",
        }

        result = await process_telemetry_event(
            base_event,
            case_service=service,
            classifier=fake_classifier,
        )

        assert result["category"] == "ERR-01"
        assert fake_classifier.predict.call_count == 0  # Primary classifier was NOT touched


@pytest.mark.asyncio
async def test_worker_classifier_unavailable_no_heuristic_fails_closed(base_event):
    settings = Settings(
        app_env="test",
        test_auth_enabled=True,
        fraud_classifier_enabled=True,
        jev_allow_heuristic_fallback=False,  # Semantics: never fallback unless enabled
    )
    service = CaseService(settings=settings)

    fake_classifier = MagicMock()
    fake_classifier.predict.side_effect = RuntimeError("Artifacts missing")

    with pytest.raises(Exception) as exc_info:
        await process_telemetry_event(
            base_event,
            case_service=service,
            classifier=fake_classifier,
        )
    assert "Artifacts missing" in str(exc_info.value) or "503" in str(exc_info.value)


@pytest.mark.asyncio
async def test_worker_classifier_unavailable_heuristic_fallback(base_event):
    settings = Settings(
        app_env="test",
        test_auth_enabled=True,
        fraud_classifier_enabled=True,
        jev_allow_heuristic_fallback=True,  # Allowed fallback
    )
    service = CaseService(settings=settings)

    fake_classifier = MagicMock()
    fake_classifier.predict.side_effect = RuntimeError("Artifacts missing")

    with patch("src.services.jev_assessment_service.JevAssessmentService._calibrated_heuristic") as mock_heur:
        from src.services.jev_assessment_service import JevAssessmentResult

        mock_heur.return_value = JevAssessmentResult(
            category="no_violation",
            confidence=0.85,
            priority="P2",
            priority_tier=2,
            priority_score=15,
            model_used="jev_calibrated_heuristic",
            assessment_source="heuristic_fallback",
        )

        result = await process_telemetry_event(
            base_event,
            case_service=service,
            classifier=fake_classifier,
        )

        assert result["category"] == "no_violation"
        assert result["assessment"]["assessment_source"] == "heuristic_fallback"

"""Unit tests for Classifier Advisory Service (Slice W2)."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from src.services.classifier_advisory import run_classifier_advisory
from src.services.jev_assessment_service import JevAssessmentResult


@pytest.mark.asyncio
async def test_advisory_success_agreement_true():
    mock_jev_res = JevAssessmentResult(
        category="ERR-02",
        confidence=0.92,
        priority="P1",
        priority_tier=1,
        priority_score=85,
        model_used="inception/mercury-decide:free",
        probabilities={"ERR-02": 0.92, "no_violation": 0.08},
    )

    with patch(
        "src.services.jev_assessment_service.JevAssessmentService.assess", new_callable=AsyncMock
    ) as mock_assess:
        mock_assess.return_value = mock_jev_res
        bundle = {"trip_id": "t1", "points": []}
        result = await run_classifier_advisory(
            bundle=bundle,
            primary_category="ERR-02",
            timeout_s=5.0,
        )

        assert result.advisory_status == "ok"
        assert result.llm_category == "ERR-02"
        assert result.agreement is True
        assert result.llm_model_used == "inception/mercury-decide:free"
        assert result.llm_probabilities == {"ERR-02": 0.92, "no_violation": 0.08}
        assert result.llm_latency_ms >= 0.0
        # Check that state_variant was evidence_classref
        inp_arg = mock_assess.call_args[0][0]
        assert inp_arg.state_variant == "evidence_classref"


@pytest.mark.asyncio
async def test_advisory_success_agreement_false():
    mock_jev_res = JevAssessmentResult(
        category="no_violation",
        confidence=0.85,
        priority="P2",
        priority_tier=2,
        priority_score=15,
        model_used="inception/mercury-decide:free",
        probabilities={"no_violation": 0.85, "ERR-02": 0.15},
    )

    with patch(
        "src.services.jev_assessment_service.JevAssessmentService.assess", new_callable=AsyncMock
    ) as mock_assess:
        mock_assess.return_value = mock_jev_res
        bundle = {"trip_id": "t2", "points": []}
        result = await run_classifier_advisory(
            bundle=bundle,
            primary_category="ERR-02",
            timeout_s=5.0,
        )

        assert result.advisory_status == "ok"
        assert result.llm_category == "no_violation"
        assert result.agreement is False


@pytest.mark.asyncio
async def test_advisory_timeout():
    async def _slow_assess(*args, **kwargs):
        await asyncio.sleep(2.0)
        return JevAssessmentResult(
            category="ERR-02",
            confidence=0.9,
            priority="P1",
            priority_tier=1,
            priority_score=80,
        )

    with patch("src.services.jev_assessment_service.JevAssessmentService.assess", side_effect=_slow_assess):
        bundle = {"trip_id": "t3"}
        result = await run_classifier_advisory(
            bundle=bundle,
            primary_category="ERR-02",
            timeout_s=0.05,
        )

        assert result.advisory_status == "timeout"
        assert result.llm_category is None
        assert result.agreement is False
        assert result.llm_latency_ms >= 50.0


@pytest.mark.asyncio
async def test_advisory_error_handling():
    with patch(
        "src.services.jev_assessment_service.JevAssessmentService.assess", side_effect=RuntimeError("API error")
    ):
        bundle = {"trip_id": "t4"}
        result = await run_classifier_advisory(
            bundle=bundle,
            primary_category="ERR-02",
            timeout_s=5.0,
        )

        assert result.advisory_status == "error"
        assert result.llm_category is None
        assert result.agreement is False

"""Async Mercury advisory opinion wrapper around JevAssessmentService (Slice W2)."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from src.config import Settings, get_settings
from src.models.classifier_api import ClassifierAdvisoryResult
from src.services.jev_assessment_service import (
    DEFAULT_JEV_MODEL,
    JevAssessmentService,
)
from src.services.jev_state_builder import map_telemetry_event_to_jev_input
from src.services.model_input_projection import project_model_input

logger = logging.getLogger(__name__)


class ClassifierAdvisoryService:
    """Orchestrates async LLM advisory opinions using JevAssessmentService."""

    def __init__(
        self,
        settings: Settings | None = None,
        jev_service: JevAssessmentService | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.jev_service = jev_service or JevAssessmentService(self.settings)

    async def get_advisory(
        self,
        bundle: dict[str, Any],
        primary_category: str | None = None,
        timeout_s: float | None = None,
    ) -> ClassifierAdvisoryResult:
        """Call JevAssessmentService asynchronously bounded by timeout_s."""
        timeout = timeout_s if timeout_s is not None else getattr(self.settings, "classifier_advisory_timeout_s", 8.0)
        model_name = (
            getattr(self.settings, "project_jev_model", None)
            or getattr(self.settings, "jev_model", None)
            or DEFAULT_JEV_MODEL
        )

        # Strip evaluation labels; state variant pinned to evidence_classref per PROD_DESIGN.md §3, §4
        clean_bundle = project_model_input(bundle)
        jev_inp = map_telemetry_event_to_jev_input(clean_bundle)
        jev_inp.state_variant = "evidence_classref"

        t0 = time.perf_counter()
        try:
            jev_res = await asyncio.wait_for(
                self.jev_service.assess(jev_inp),
                timeout=timeout,
            )
            t1 = time.perf_counter()
            duration_ms = round((t1 - t0) * 1000.0, 2)

            llm_cat = getattr(jev_res, "category", None)
            agreement = (
                (primary_category == llm_cat) if (primary_category is not None and llm_cat is not None) else None
            )

            return ClassifierAdvisoryResult(
                llm_category=llm_cat,
                llm_probabilities=getattr(jev_res, "probabilities", {}),
                llm_model_used=getattr(jev_res, "model_used", model_name),
                llm_latency_ms=duration_ms,
                advisory_status="ok",
                agreement=agreement,
            )
        except TimeoutError:
            t1 = time.perf_counter()
            duration_ms = round((t1 - t0) * 1000.0, 2)
            logger.warning("Classifier advisory timed out after %.2f ms", duration_ms)
            return ClassifierAdvisoryResult(
                llm_category=None,
                llm_probabilities={},
                llm_model_used=model_name,
                llm_latency_ms=duration_ms,
                advisory_status="timeout",
                agreement=False,
            )
        except Exception as exc:
            t1 = time.perf_counter()
            duration_ms = round((t1 - t0) * 1000.0, 2)
            logger.warning("Classifier advisory execution error: %s", exc)
            return ClassifierAdvisoryResult(
                llm_category=None,
                llm_probabilities={},
                llm_model_used=model_name,
                llm_latency_ms=duration_ms,
                advisory_status="error",
                agreement=False,
            )


async def run_classifier_advisory(
    bundle: dict[str, Any],
    primary_category: str | None = None,
    timeout_s: float | None = None,
    settings: Settings | None = None,
    jev_service: JevAssessmentService | None = None,
) -> ClassifierAdvisoryResult:
    """Convenience helper to run advisory opinion on a single trip bundle."""
    svc = ClassifierAdvisoryService(settings=settings, jev_service=jev_service)
    return await svc.get_advisory(
        bundle=bundle,
        primary_category=primary_category,
        timeout_s=timeout_s,
    )

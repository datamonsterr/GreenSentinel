"""FastAPI API routes for serving the R3D Fraud Classifier (Slice W2)."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Protocol, runtime_checkable

import anyio
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse

from src.api.auth import Principal, require_principal, require_role
from src.config import Settings, get_settings
from src.models.classifier_api import (
    ClassifierAdvisoryResult,
    ClassifierAssessRequest,
    ClassifierAssessResponse,
    ClassifierInfoResponse,
)
from src.services import classifier_advisory

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/classifier", tags=["classifier"])


@runtime_checkable
class FraudClassifierProtocol(Protocol):
    """Interface contract for the fraud classifier service (W1 contract)."""

    model_version: str

    def predict(self, bundle: dict[str, Any]) -> Any: ...

    def predict_many(self, bundles: list[dict[str, Any]]) -> list[Any]: ...

    def get_info(self) -> dict[str, Any]: ...


class ClassifierUnavailableException(HTTPException):
    """Exception raised when classifier service or artifacts are unavailable."""

    def __init__(self, detail: str = "Classifier unavailable") -> None:
        super().__init__(status_code=503, detail=detail)


def get_classifier_service() -> FraudClassifierProtocol:
    """Dependency injection provider for the FraudClassifier singleton.

    Guarded with lazy import so the application starts cleanly even if W1
    package has not yet been merged or installed.
    """
    try:
        from src.services.fraud_classifier import get_fraud_classifier

        return get_fraud_classifier()
    except ImportError as exc:
        raise ClassifierUnavailableException(f"Fraud classifier package not installed: {exc}") from exc
    except Exception as exc:
        raise ClassifierUnavailableException(f"Fraud classifier unavailable: {exc}") from exc


def _format_server_timing(
    feat_ms: float,
    infer_ms: float,
    total_ms: float,
    advisory_ms: float | None = None,
) -> str:
    parts = [
        f"feat;dur={feat_ms:.1f}",
        f"infer;dur={infer_ms:.1f}",
    ]
    if advisory_ms is not None:
        parts.append(f"advisory;dur={advisory_ms:.1f}")
        parts.append(f"adv;dur={advisory_ms:.1f}")
    parts.append(f"total;dur={total_ms:.1f}")
    return ", ".join(parts)


async def _run_heuristic_fallback(
    bundle: dict[str, Any],
    settings: Settings,
    total_start: float,
    response: Response,
) -> ClassifierAssessResponse:
    """Fallback to Jev calibrated heuristic when JEV_ALLOW_HEURISTIC_FALLBACK=True."""
    from src.services.jev_assessment_service import JevAssessmentService
    from src.services.jev_state_builder import map_telemetry_event_to_jev_input
    from src.services.model_input_projection import project_model_input

    t0 = time.perf_counter()
    jev_svc = JevAssessmentService(settings=settings)
    clean_bundle = project_model_input(bundle)
    jev_inp = map_telemetry_event_to_jev_input(clean_bundle)
    jev_res = await jev_svc.assess(jev_inp)
    total_ms = (time.perf_counter() - total_start) * 1000.0
    infer_ms = (time.perf_counter() - t0) * 1000.0

    response.headers["Server-Timing"] = _format_server_timing(
        feat_ms=0.0,
        infer_ms=infer_ms,
        total_ms=total_ms,
    )

    return ClassifierAssessResponse(
        category=jev_res.category,
        probabilities=jev_res.probabilities,
        confidence=jev_res.confidence,
        guardrail_blocked=False,
        guardrail_reason=None,
        model_version="jev_calibrated_heuristic",
        artifact_sha="",
        feature_ms=0.0,
        inference_ms=round(infer_ms, 2),
        assessment_source="heuristic_fallback",
        advisory=None,
    )


def _extract_bundle_from_raw(body: Any) -> dict[str, Any]:
    if isinstance(body, dict):
        if "bundle" in body and isinstance(body["bundle"], dict):
            return body["bundle"]
        if "telemetry_event" in body and isinstance(body["telemetry_event"], dict):
            return body["telemetry_event"]
        return body
    if hasattr(body, "extract_bundle"):
        return body.extract_bundle()
    return {}


@router.post("/assess", response_model=ClassifierAssessResponse)
async def assess_single(
    request: Request,
    response: Response,
    body: dict[str, Any] | ClassifierAssessRequest,
    advisory: bool = Query(default=False),
    principal: Principal | None = Depends(require_principal),
    settings: Settings = Depends(get_settings),
    classifier: FraudClassifierProtocol = Depends(get_classifier_service),
) -> Any:
    """Assess single trip bundle using R3D fraud classifier and optional advisory."""
    require_role(principal, "analyst", "senior_analyst", "demo_operator", "admin")

    t_total_start = time.perf_counter()
    bundle = _extract_bundle_from_raw(body)

    # Run CPU inference in threadpool to preserve event loop concurrency
    # If advisory requested, start advisory task concurrently
    advisory_task = None
    if advisory and settings.classifier_llm_advisory:
        advisory_task = asyncio.create_task(
            classifier_advisory.run_classifier_advisory(
                bundle=bundle,
                primary_category=None,
                timeout_s=settings.classifier_advisory_timeout_s,
                settings=settings,
            )
        )

    try:
        res = await anyio.to_thread.run_sync(classifier.predict, bundle)
    except Exception as exc:
        if advisory_task:
            advisory_task.cancel()
        logger.error("Classifier inference failed: %s", exc)
        if settings.jev_allow_heuristic_fallback:
            return await _run_heuristic_fallback(bundle, settings, t_total_start, response)
        return JSONResponse(
            status_code=503,
            content={
                "detail": f"Classifier inference error: {exc}",
                "assessment_source": "classifier_unavailable",
                "category": "insufficient_evidence",
            },
        )

    # 3. Await advisory if running
    adv_res: ClassifierAdvisoryResult | None = None
    if advisory_task is not None:
        try:
            adv_res = await advisory_task
            if adv_res is not None and adv_res.llm_category is not None:
                adv_res.agreement = getattr(res, "category", None) == adv_res.llm_category
        except Exception as exc:
            logger.debug("Advisory task error: %s", exc)

    t_total_end = time.perf_counter()
    total_ms = (t_total_end - t_total_start) * 1000.0
    feat_ms = float(getattr(res, "feature_ms", 0.0))
    infer_ms = float(getattr(res, "inference_ms", 0.0))
    adv_ms = adv_res.llm_latency_ms if adv_res else None

    response.headers["Server-Timing"] = _format_server_timing(
        feat_ms=feat_ms,
        infer_ms=infer_ms,
        total_ms=total_ms,
        advisory_ms=adv_ms,
    )

    return ClassifierAssessResponse(
        category=getattr(res, "category", "no_violation"),
        probabilities=getattr(res, "probabilities", {}),
        confidence=float(getattr(res, "confidence", 0.0)),
        guardrail_blocked=bool(getattr(res, "guardrail_blocked", False)),
        guardrail_reason=getattr(res, "guardrail_reason", None),
        model_version=str(getattr(res, "model_version", getattr(classifier, "model_version", "r3d"))),
        artifact_sha=str(getattr(res, "artifact_sha", "")),
        feature_ms=round(feat_ms, 2),
        inference_ms=round(infer_ms, 2),
        assessment_source=getattr(res, "assessment_source", "r3d_classifier"),
        advisory=adv_res,
    )


@router.post("/assess/batch", response_model=list[ClassifierAssessResponse])
async def assess_batch(
    request: Request,
    response: Response,
    body: list[dict[str, Any]] | dict[str, Any],
    advisory: bool = Query(default=False),
    principal: Principal | None = Depends(require_principal),
    settings: Settings = Depends(get_settings),
    classifier: FraudClassifierProtocol = Depends(get_classifier_service),
) -> Any:
    """Assess batch of trip bundles (up to CLASSIFIER_BATCH_MAX items)."""
    require_role(principal, "analyst", "senior_analyst", "demo_operator", "admin")

    t_total_start = time.perf_counter()

    # Extract bundles from list or {"items": [...]}
    if isinstance(body, list):
        items = body
    elif isinstance(body, dict) and "items" in body and isinstance(body["items"], list):
        items = body["items"]
    else:
        items = [body] if isinstance(body, dict) else []

    if len(items) > settings.classifier_batch_max:
        raise HTTPException(
            status_code=400,
            detail=f"Batch size exceeds maximum limit of {settings.classifier_batch_max} (received {len(items)})",
        )

    if not items:
        response.headers["Server-Timing"] = _format_server_timing(0.0, 0.0, 0.0)
        return []

    bundles = [_extract_bundle_from_raw(item) for item in items]

    # Launch advisory tasks concurrently if requested
    advisory_tasks = []
    if advisory and settings.classifier_llm_advisory:
        for b in bundles:
            advisory_tasks.append(
                asyncio.create_task(
                    classifier_advisory.run_classifier_advisory(
                        bundle=b,
                        primary_category=None,
                        timeout_s=settings.classifier_advisory_timeout_s,
                        settings=settings,
                    )
                )
            )

    try:
        if hasattr(classifier, "predict_many"):
            results = await anyio.to_thread.run_sync(classifier.predict_many, bundles)
        else:
            results = await anyio.to_thread.run_sync(lambda: [classifier.predict(b) for b in bundles])
    except Exception as exc:
        if advisory_tasks:
            for task in advisory_tasks:
                task.cancel()
        logger.error("Classifier batch inference failed: %s", exc)
        return JSONResponse(
            status_code=503,
            content={
                "detail": f"Classifier batch inference error: {exc}",
                "assessment_source": "classifier_unavailable",
            },
        )

    advisory_results: list[ClassifierAdvisoryResult | None] = []
    if advisory_tasks:
        adv_gathered = await asyncio.gather(*advisory_tasks, return_exceptions=True)
        for r, adv in zip(results, adv_gathered, strict=False):
            if isinstance(adv, ClassifierAdvisoryResult):
                if adv.llm_category is not None:
                    adv.agreement = getattr(r, "category", None) == adv.llm_category
                advisory_results.append(adv)
            else:
                advisory_results.append(None)
    else:
        advisory_results = [None] * len(results)

    t_total_end = time.perf_counter()
    total_ms = (t_total_end - t_total_start) * 1000.0
    sum_feat_ms = sum(float(getattr(r, "feature_ms", 0.0)) for r in results)
    sum_infer_ms = sum(float(getattr(r, "inference_ms", 0.0)) for r in results)

    response.headers["Server-Timing"] = _format_server_timing(
        feat_ms=sum_feat_ms,
        infer_ms=sum_infer_ms,
        total_ms=total_ms,
    )

    resp_items = []
    for r, adv in zip(results, advisory_results, strict=False):
        feat_ms = float(getattr(r, "feature_ms", 0.0))
        infer_ms = float(getattr(r, "inference_ms", 0.0))
        resp_items.append(
            ClassifierAssessResponse(
                category=getattr(r, "category", "no_violation"),
                probabilities=getattr(r, "probabilities", {}),
                confidence=float(getattr(r, "confidence", 0.0)),
                guardrail_blocked=bool(getattr(r, "guardrail_blocked", False)),
                guardrail_reason=getattr(r, "guardrail_reason", None),
                model_version=str(getattr(r, "model_version", getattr(classifier, "model_version", "r3d"))),
                artifact_sha=str(getattr(r, "artifact_sha", "")),
                feature_ms=round(feat_ms, 2),
                inference_ms=round(infer_ms, 2),
                assessment_source=getattr(r, "assessment_source", "r3d_classifier"),
                advisory=adv,
            )
        )
    return resp_items


@router.get("/info", response_model=ClassifierInfoResponse)
async def get_classifier_info(
    principal: Principal | None = Depends(require_principal),
    classifier: FraudClassifierProtocol = Depends(get_classifier_service),
) -> Any:
    """Get metadata, artifact shas, loaded time, and benchmark metrics."""
    require_role(principal, "analyst", "senior_analyst", "demo_operator", "admin")

    info: dict[str, Any] = {}
    if hasattr(classifier, "get_info"):
        try:
            info = classifier.get_info()
        except Exception:
            pass

    model_version = info.get("model_version") or getattr(classifier, "model_version", "r3d_unknown")
    artifact_shas = info.get("artifact_shas") or getattr(classifier, "artifact_shas", {})
    loaded_at = info.get("loaded_at") or getattr(classifier, "loaded_at", None)
    load_ms = info.get("load_ms") or getattr(classifier, "load_ms", None)
    metrics = info.get("metrics") or getattr(classifier, "metrics", {})

    return ClassifierInfoResponse(
        model_version=str(model_version),
        artifact_shas=dict(artifact_shas) if isinstance(artifact_shas, dict) else {},
        loaded_at=str(loaded_at) if loaded_at else None,
        load_ms=float(load_ms) if load_ms is not None else None,
        metrics=dict(metrics) if isinstance(metrics, dict) else {},
        status="ok",
    )

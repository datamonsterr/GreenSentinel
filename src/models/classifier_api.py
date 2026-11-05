"""Pydantic V2 schemas for the Fraud Classifier API (Slice W2)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ClassifierAssessRequest(BaseModel):
    """Single trip assessment request.

    Accepts {bundle: object}, {telemetry_event: object}, or raw trip bundle fields.
    """

    model_config = ConfigDict(extra="allow")

    bundle: dict[str, Any] | None = None
    telemetry_event: dict[str, Any] | None = None

    def extract_bundle(self) -> dict[str, Any]:
        """Resolve trip bundle from nested wrapper or root fields."""
        if self.bundle is not None:
            return self.bundle
        if self.telemetry_event is not None:
            return self.telemetry_event
        # Raw trip bundle passed at root level
        data = self.model_dump(exclude_unset=True)
        data.pop("bundle", None)
        data.pop("telemetry_event", None)
        return data


class ClassifierBatchAssessRequest(BaseModel):
    """Batch assessment request container."""

    items: list[dict[str, Any] | ClassifierAssessRequest] = Field(
        ..., description="List of trip bundles or assess requests"
    )


class ClassifierAdvisoryResult(BaseModel):
    """Secondary advisory opinion from Mercury / Jev decision model."""

    model_config = ConfigDict(extra="ignore")

    llm_category: str | None = None
    llm_probabilities: dict[str, float] = Field(default_factory=dict)
    llm_model_used: str = ""
    llm_latency_ms: float = 0.0
    advisory_status: Literal["ok", "timeout", "error", "disabled"] = "disabled"
    agreement: bool | None = None


class ClassifierAssessResponse(BaseModel):
    """Response returned by classifier assessment endpoints."""

    model_config = ConfigDict(extra="allow")

    category: str
    probabilities: dict[str, float] = Field(default_factory=dict)
    confidence: float
    guardrail_blocked: bool = False
    guardrail_reason: str | None = None
    model_version: str
    artifact_sha: str = ""
    feature_ms: float = 0.0
    inference_ms: float = 0.0
    assessment_source: Literal[
        "r3d_classifier",
        "guardrail_short_circuit",
        "classifier_unavailable",
        "heuristic_fallback",
    ]
    advisory: ClassifierAdvisoryResult | None = None


class ClassifierInfoResponse(BaseModel):
    """Metadata and loaded artifact manifest for the served classifier."""

    model_config = ConfigDict(extra="allow")

    model_version: str
    artifact_shas: dict[str, str] = Field(default_factory=dict)
    loaded_at: str | None = None
    load_ms: float | None = None
    metrics: dict[str, Any] = Field(default_factory=dict)
    status: str = "ok"

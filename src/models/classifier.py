"""Classifier result schema and type definitions for production fraud detection.

Defined according to PROD_DESIGN.md interface contract (§1, §Interface contract).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ClassifierResult(BaseModel):
    """Normalized response payload emitted by FraudClassifier."""

    category: str = Field(
        ...,
        description="Predicted fraud class from 7-class benchmark taxonomy.",
    )
    probabilities: dict[str, float] = Field(
        ...,
        description="Calibrated probability distribution across all 7 benchmark classes.",
    )
    confidence: float = Field(
        ...,
        description="Confidence score in [0.0, 1.0] corresponding to the predicted category.",
    )
    guardrail_blocked: bool = Field(
        ...,
        description="True if technical guardrail conditions blocked ML inference.",
    )
    guardrail_reason: str | None = Field(
        default=None,
        description="Primary guardrail failure reason code if blocked.",
    )
    model_version: str = Field(
        ...,
        description="Version string identifying model package and release lineage.",
    )
    artifact_sha: str = Field(
        ...,
        description="Short SHA256 identifier of the active artifact bundle.",
    )
    feature_ms: float = Field(
        ...,
        description="Time in milliseconds spent extracting tabular and sequence features.",
    )
    inference_ms: float = Field(
        ...,
        description="Time in milliseconds spent in model forward passes and meta-learning.",
    )
    assessment_source: Literal["r3d_classifier", "guardrail_short_circuit", "classifier_unavailable"] = Field(
        ...,
        description="Execution provenance for auditing and metrics attribution.",
    )

"""Strict, standalone contract for the synthetic reasoning baseline."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from src.models.policy import PolicyCitation

ForensicCategory = Literal["ERR-02", "ERR-05", "no_violation", "insufficient_evidence"]


class ScoreSemantics(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)

    scale: Literal["0.0_to_1.0_ordinal_support"] = "0.0_to_1.0_ordinal_support"
    calibrated: Literal[False] = False
    is_violation_probability: Literal[False] = False
    description: str = Field(
        default="Advisory rule/model support score only. Not a calibrated violation probability, vector similarity score, or punitive sanction basis."
    )


class ForensicInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)

    case_id: str = Field(min_length=1)
    telemetry_points: int = Field(ge=0)
    stationary_duration_s: float = Field(ge=0)
    lifecycle_state: Literal["completed", "cancelled", "active"]
    cancellation_actor: Literal["passenger", "driver", "none"]
    mock_location_reported: bool
    platform_outage: bool
    gps_degraded: bool
    policy_version_id: str | None = None
    driver_claimed_outage: bool = False
    contradictory_evidence: bool = False


class Evidence(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)

    source: str = Field(min_length=1)
    value: str | bool | int | float | None
    description: str = Field(min_length=1)


class ForensicOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)

    case_id: str = Field(min_length=1)
    category: ForensicCategory
    confidence: float = Field(ge=0, le=1)
    score_semantics: ScoreSemantics = Field(default_factory=ScoreSemantics)
    evidence: list[Evidence] = Field(min_length=1)
    summary: str = Field(min_length=1)
    policy_version: str | None = None
    retrieved_policy_clauses: list[str] = Field(default_factory=list)
    policy_citations: list[PolicyCitation] = Field(default_factory=list)
    uncertainty_score: float = Field(ge=0, le=1, default=0.0)
    abstention: bool = False
    abstention_rationale: str | None = None
    human_confirmation_required: Literal[True] = True
    sanctions_prohibited: Literal[True] = True

"""Strict contracts for agent tool execution, authorization, results, and catalog entries.

Refs #60, #85.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ToolExecutionContext(BaseModel):
    """Server-injected trusted context for tool execution."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    actor_id: str
    organization_id: str
    roles: frozenset[str]
    case_id: str | None = None
    driver_id: str | None = None
    request_id: str
    run_id: str
    tool_call_id: str
    turn_id: str


class ToolError(BaseModel):
    """Structured tool error with canonical code and retryability flag."""

    model_config = ConfigDict(extra="forbid")

    code: Literal[
        "VALIDATION_ERROR",
        "UNAUTHENTICATED",
        "FORBIDDEN",
        "NOT_FOUND",
        "CONFLICT",
        "SOURCE_UNAVAILABLE",
        "PROVIDER_TIMEOUT",
        "PROVIDER_UNAVAILABLE",
        "PERSISTENCE_UNAVAILABLE",
        "RUN_LIMIT",
        "INTERRUPTED",
        "INTERNAL_ERROR",
    ]
    message: str
    retryable: bool


class EvidenceProvenance(BaseModel):
    """Source-backed evidence provenance metadata."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["database", "provider", "dataset", "unavailable"]
    source: str
    record_ids: list[str] = Field(default_factory=list)
    observed_at: str | None = None
    retrieved_at: str
    dataset_version: str | None = None
    citation_ids: list[str] = Field(default_factory=list)
    provider_request_id: str | None = None


class ToolResult(BaseModel):
    """Strict typed result envelope for all agent tool executions."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["succeeded", "failed"]
    tool_id: str
    tool_call_id: str
    data: dict[str, Any] | None = None
    error: ToolError | None = None
    provenance: list[EvidenceProvenance] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_result_state(self) -> ToolResult:
        if self.status == "succeeded":
            if self.data is None:
                raise ValueError("succeeded ToolResult must have data")
            if self.error is not None:
                raise ValueError("succeeded ToolResult cannot have error")
        elif self.status == "failed":
            if self.error is None:
                raise ValueError("failed ToolResult must have error")
            if self.data is not None:
                raise ValueError("failed ToolResult cannot have data")
        return self


class ToolCatalogEntry(BaseModel):
    """Catalog metadata describing an agent or human tool/command."""

    model_config = ConfigDict(extra="forbid")

    canonical_id: str
    surface_names: list[str]
    actor: Literal["analyst", "driver", "operations", "both"]
    purpose: str
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    error_codes: list[str]
    provenance_kind: Literal["database", "provider", "dataset", "unavailable", "composite"]
    side_effects: bool
    model_selectable: bool
    timeout_seconds: float = 10.0
    max_retries: int = 2

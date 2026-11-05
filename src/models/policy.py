"""Source-backed policy records shared by retrieval and advisory outputs."""

from pydantic import BaseModel, ConfigDict, Field


class PolicySource(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    id: str = Field(min_length=1)
    version: str = Field(min_length=1)
    source: str = Field(min_length=1)
    section: str = Field(min_length=1)
    text: str = Field(min_length=1)
    is_demo_policy: bool = False


class PolicyCitation(PolicySource):
    """Exact retrieved record, including version and provenance."""

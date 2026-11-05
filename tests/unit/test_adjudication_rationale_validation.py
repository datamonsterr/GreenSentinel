import pytest
from pydantic import ValidationError

from src.models.schemas import AdjudicationRequest


def test_adjudication_rationale_enforces_minimum_ten_characters():
    # 1. Rationale shorter than 10 characters must be rejected
    short_rationales = ["", "Valid", "Short 123", "   short  "]
    for r in short_rationales:
        with pytest.raises(ValidationError) as exc_info:
            AdjudicationRequest(
                outcome="AGREE",
                analyst_id="018f2f4e-1000-7000-8000-000000000001",
                rationale=r,
                expected_case_version=1,
            )
        assert "min_length" in str(exc_info.value) or "at least 10" in str(exc_info.value)

    # 2. Rationale >= 10 characters must be valid
    valid = AdjudicationRequest(
        outcome="AGREE",
        analyst_id="018f2f4e-1000-7000-8000-000000000001",
        rationale="1234567890",
        expected_case_version=1,
    )
    assert len(valid.rationale) >= 10

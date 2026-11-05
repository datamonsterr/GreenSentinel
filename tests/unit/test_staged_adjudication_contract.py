"""Issue #236: public schema round-trips and existing HITL validation."""

import pytest
from pydantic import ValidationError

from src.models.schemas import AdjudicationRequest, CaseDetailResponse

JUDGMENT_ID = "23600000-0000-4000-8000-000000000001"
ANALYST_ID = "23600000-0000-4000-8000-000000000002"
CASE_ID = "23600000-0000-4000-8000-000000000003"
JUDGMENTS = ("Nghi ngờ vi phạm", "Nghi oan-bất khả kháng", "Chưa đủ cơ sở")
CASE = {"id": CASE_ID, "status": "ready", "priority": "P1", "priority_score": 80}


def decision_payload(**overrides):
    return {
        "outcome": "AGREE",
        "analyst_id": ANALYST_ID,
        "rationale": "Independent evidence supports this signed decision",
        "expected_case_version": 1,
        "preliminary_judgment_id": JUDGMENT_ID,
        **overrides,
    }


def test_final_request_retains_reference_to_the_committed_independent_judgment():
    request = AdjudicationRequest.model_validate(decision_payload())
    assert request.model_dump(mode="json").get("preliminary_judgment_id") == JUDGMENT_ID


def test_uncommitted_case_detail_explicitly_reports_null_judgment_for_reload():
    detail = CaseDetailResponse.model_validate({"case": CASE})
    payload = detail.model_dump(mode="json")
    assert "preliminary_judgment" in payload, "Reload needs an explicit uncommitted gate state"
    assert payload["preliminary_judgment"] is None


@pytest.mark.parametrize("judgment", JUDGMENTS)
@pytest.mark.parametrize("note", [None, "Đã kiểm tra dữ kiện; cần xác minh kẹt xe."])
def test_case_detail_round_trips_committed_judgment_and_optional_note(judgment, note):
    record = {
        "id": JUDGMENT_ID,
        "case_id": CASE_ID,
        "analyst_id": ANALYST_ID,
        "judgment": judgment,
        "note": note,
        "created_at": "2026-10-14T01:00:00Z",
    }
    detail = CaseDetailResponse.model_validate(
        {"case": {**CASE, "status": "in_review"}, "preliminary_judgment": record}
    )
    restored = detail.model_dump(mode="json").get("preliminary_judgment")
    assert restored is not None, "CaseDetailResponse discards the persisted preliminary judgment"
    assert {key: restored[key] for key in ("id", "analyst_id", "judgment", "note")} == {
        key: record[key] for key in ("id", "analyst_id", "judgment", "note")
    }


@pytest.mark.parametrize("outcome", ["AGREE", "DISAGREE"])
@pytest.mark.parametrize("rationale", ["123456789", "     short     "])
def test_reveal_never_replaces_minimum_signed_decision_rationale(outcome, rationale):
    with pytest.raises(ValidationError):
        AdjudicationRequest.model_validate(decision_payload(outcome=outcome, rationale=rationale))


@pytest.mark.parametrize("outcome", ["AGREE", "DISAGREE"])
def test_reveal_never_replaces_the_analyst_signature(outcome):
    payload = decision_payload(outcome=outcome)
    del payload["analyst_id"]
    with pytest.raises(ValidationError):
        AdjudicationRequest.model_validate(payload)


def test_exactly_ten_rationale_characters_remain_a_valid_final_request():
    request = AdjudicationRequest.model_validate(decision_payload(rationale="1234567890"))
    assert request.rationale == "1234567890"


@pytest.mark.parametrize("legacy_outcome", ["DISMISS", "APPROVE", "REJECT", "WARN", "FINE", "SUSPEND"])
def test_adjudication_request_rejects_legacy_outcomes(legacy_outcome):
    with pytest.raises(ValidationError):
        AdjudicationRequest.model_validate(decision_payload(outcome=legacy_outcome))

import pytest
from pydantic import ValidationError

from src.agents.forensic_baseline import assess_case, assess_case_grounded
from src.models.forensic import ForensicInput
from src.services.grounded_policy import PolicyRepository, PolicySource, ask_policy


def case(**changes):
    data = dict(
        case_id="c1",
        telemetry_points=3,
        stationary_duration_s=0.0,
        lifecycle_state="completed",
        cancellation_actor="none",
        mock_location_reported=False,
        platform_outage=False,
        gps_degraded=False,
        policy_version_id="v1",
    )
    data.update(changes)
    return ForensicInput.model_validate(data)


def source(identifier="ERR-05-clause", text="mock location evidence requires review", version="v1", **changes):
    return PolicySource(id=identifier, version=version, source="policy.pdf", section="4.2", text=text, **changes)


def test_missing_or_unknown_version_abstains():
    assert assess_case_grounded(case(policy_version_id=None)).abstention
    assert assess_case_grounded(case(mock_location_reported=True), PolicyRepository([source(version="v2")])).abstention


def test_grounded_classification_cites_exact_text():
    item = source()
    result = assess_case_grounded(case(mock_location_reported=True), PolicyRepository([item]))
    assert result.abstention is False
    assert result.retrieved_policy_clauses == [item.text]


def test_conflicting_same_identity_abstains_but_duplicate_equivalent_is_safe():
    same = source()
    repo = PolicyRepository([same, same])
    assert assess_case_grounded(case(mock_location_reported=True), repo).abstention is False
    conflict = PolicyRepository([same, source(text="mock location is permitted")])
    assert assess_case_grounded(case(mock_location_reported=True), conflict).abstention


def test_policy_question_abstains_when_irrelevant_and_preserves_citations():
    repo = PolicyRepository([source()])
    assert ask_policy("weather forecast", "v1", repo)["abstained"]
    answer = ask_policy("mock location evidence", "v1", repo)
    assert answer["abstained"] is False
    assert answer["answer"] == "mock location evidence requires review"


def test_policy_source_rejects_extra_metadata():
    with pytest.raises(ValidationError):
        PolicySource(id="x", version="v1", source="s", section="1", text="t", invented=True)


def test_completed_trip_with_unknown_policy_abstains():
    result = assess_case_grounded(case(), PolicyRepository([source(version="v2")]))
    assert result.abstention
    assert result.policy_version is None
    assert result.policy_citations == []


def test_exact_null_evidence_and_explicit_conflict_abstain():
    missing = assess_case_grounded(case(policy_version_id=None))
    assert next(item.value for item in missing.evidence if item.source == "policy_version_id") is None
    result = assess_case_grounded(case(contradictory_evidence=True), PolicyRepository([source()]))
    assert result.abstention
    assert result.confidence == 0
    assert ask_policy("mock location", "v1", PolicyRepository([source()]), contradictory_evidence=True)["abstained"]


def test_candidate_preserves_scores_and_structured_citation():
    input_case = case(mock_location_reported=True)
    result = assess_case_grounded(input_case, PolicyRepository([source(is_demo_policy=True)]))
    assert result.confidence == assess_case(input_case).confidence
    assert result.policy_citations[0].text == result.retrieved_policy_clauses[0]
    assert result.policy_citations[0].is_demo_policy
    assert result.score_semantics.calibrated is False
    assert result.human_confirmation_required
    assert result.sanctions_prohibited


def test_complementary_sections_deduplicate_and_are_order_independent():
    first = source()
    second = source(identifier="ERR-05-review", text="Review mock location evidence carefully.").model_copy(
        update={"section": "4.3"}
    )
    a = assess_case_grounded(case(mock_location_reported=True), PolicyRepository([second, first, first]))
    b = assess_case_grounded(case(mock_location_reported=True), PolicyRepository([first, second]))
    assert not a.abstention
    assert a.model_dump() == b.model_dump()


def test_conflicting_section_cannot_be_hidden_by_query():
    first = source()
    second = source(text="Contradictory clause on unrelated words.")
    repository = PolicyRepository([first, second])
    assert ask_policy("mock location", "v1", repository)["abstained"]
    assert assess_case_grounded(case(mock_location_reported=True), repository).abstention

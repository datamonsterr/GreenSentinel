"""Offline evidence-first rules and grounded advisory classifier; scores are uncalibrated, not guilt probabilities."""

from src.models.forensic import Evidence, ForensicCategory, ForensicInput, ForensicOutput, ScoreSemantics
from src.services.grounded_policy import PolicyRepository

BASELINE_VERSION = "forensic-rules-v1"
CANDIDATE_VERSION = "forensic-grounded-v2"


def assess_case(case: ForensicInput) -> ForensicOutput:
    """Classify observed features without access to benchmark labels (Baseline: rules-v1)."""
    facts = case.model_dump()
    sources = ["telemetry_points", "platform_outage", "gps_degraded"]
    category: ForensicCategory = "insufficient_evidence"
    confidence = 0.0
    uncertainty_score = 1.0
    abstention = True
    abstention_rationale = None
    summary = "Available evidence does not support a baseline classification; analyst review required."
    if case.platform_outage or case.gps_degraded or case.telemetry_points < 2:
        summary = "Telemetry is missing or unreliable; hold for analyst review."
        abstention_rationale = "Technical failure or degraded telemetry."
    elif case.mock_location_reported:
        category, confidence = "ERR-05", 0.9
        uncertainty_score = 0.1
        abstention = False
        sources += ["mock_location_reported"]
        summary = "Mock location is reported; suspected GPS manipulation requires analyst review."
    elif (
        case.stationary_duration_s >= 180
        and case.lifecycle_state == "cancelled"
        and case.cancellation_actor == "passenger"
    ):
        category, confidence = "ERR-02", 0.8
        uncertainty_score = 0.2
        abstention = False
        sources += ["stationary_duration_s", "lifecycle_state", "cancellation_actor"]
        summary = "At least 180 seconds stationary precedes passenger cancellation; intent remains unproven."
    elif case.lifecycle_state == "completed":
        category, confidence = "no_violation", 0.7
        uncertainty_score = 0.3
        abstention = False
        sources += ["lifecycle_state", "mock_location_reported"]
        summary = "Completed trip triggers none of the supported rules; this does not establish absence of fraud."
    else:
        sources += ["stationary_duration_s", "lifecycle_state", "cancellation_actor", "mock_location_reported"]
        abstention_rationale = "Inconclusive feature combination."

    return ForensicOutput(
        case_id=case.case_id,
        category=category,
        confidence=confidence,
        score_semantics=ScoreSemantics(
            scale="0.0_to_1.0_ordinal_support",
            calibrated=False,
            is_violation_probability=False,
            description="Rule-based heuristic support score only; never a violation probability or sanction basis.",
        ),
        evidence=[
            Evidence(source=key, value=facts[key], description=f"Observed input field: {key}.") for key in sources
        ],
        summary=summary,
        policy_version=None,
        retrieved_policy_clauses=[],
        uncertainty_score=uncertainty_score,
        abstention=abstention,
        abstention_rationale=abstention_rationale,
    )


def assess_case_grounded(case: ForensicInput, policy_repository: PolicyRepository | None = None) -> ForensicOutput:
    """Extend unchanged baseline rules with versioned retrieval and safe abstention."""
    baseline = assess_case(case)
    repository = policy_repository or PolicyRepository()
    facts = case.model_dump()
    version = case.policy_version_id

    def abstain(reason: str, keys: list[str]) -> ForensicOutput:
        evidence = list(baseline.evidence)
        seen = {item.source for item in evidence}
        evidence.extend(
            Evidence(source=key, value=facts[key], description=f"Observed input field: {key}.")
            for key in keys
            if key not in seen
        )
        return baseline.model_copy(
            update={
                "category": "insufficient_evidence",
                "confidence": 0.0,
                "uncertainty_score": 1.0,
                "abstention": True,
                "abstention_rationale": reason,
                "policy_version": None,
                "retrieved_policy_clauses": [],
                "policy_citations": [],
                "evidence": evidence,
                "summary": "Advisory assessment abstained; human analyst review required.",
            }
        )

    if not version:
        return abstain("Missing policy version.", ["policy_version_id"])
    if case.contradictory_evidence:
        return abstain("Contradictory evidence requires analyst review.", ["contradictory_evidence"])
    if case.driver_claimed_outage and not (case.platform_outage or case.gps_degraded):
        return abstain(
            "Driver statement conflicts with supplied technical evidence; review required.", ["driver_claimed_outage"]
        )
    if baseline.abstention:
        return abstain(baseline.abstention_rationale or "Insufficient evidence.", [])
    topic = baseline.category if baseline.category in {"ERR-02", "ERR-05"} else None
    citations, error = repository.resolve(version, topic)
    if error:
        return abstain(error, ["policy_version_id"])
    return baseline.model_copy(
        update={
            "policy_version": version,
            "policy_citations": citations,
            "retrieved_policy_clauses": [item.text for item in citations],
            "summary": baseline.summary + " Policy citations provide context, not proof of intent.",
        }
    )

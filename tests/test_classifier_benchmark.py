import json

import pytest

from eval.benchmark_classifier import (
    calibration_diagnostics,
    evaluate_model,
    load_cases,
    project_held_out,
    requirement_policy,
    run_benchmark,
)
from src.agents.forensic_baseline import assess_case
from src.models.forensic import Evidence
from src.models.policy import PolicyCitation


def test_paired_run_is_reproducible_and_never_claims_unexecuted_holdout():
    first = run_benchmark(None)
    second = run_benchmark(None)
    assert first == second
    assert first["release_acceptance"] is False
    assert first["metadata"]["independent_held_out"] is False
    assert first["held_out"]["executed"] == 0
    assert len(first["held_out"]["not_run"]) == first["held_out"]["total"] == 37
    baseline_ids = [row["case_id"] for row in first["baseline"]["cases"]]
    candidate_ids = [row["case_id"] for row in first["candidate"]["cases"]]
    assert baseline_ids == candidate_ids == first["metadata"]["paired_case_ids"]
    assert all(gate["passed"] for gate in first["acceptance_thresholds"].values())


def test_models_receive_only_runtime_input_even_when_labels_change():
    rows = load_cases()[:1]
    original = rows[0]["expected"]
    rows[0]["expected"] = "no_violation"
    rows[0]["label_metadata"] = {"scenario": "force_new_category"}
    observed = []

    def model(input_case):
        observed.append(input_case.model_dump())
        return assess_case(input_case)

    result = evaluate_model(rows, model, requirement_policy())
    assert result["cases"][0]["predicted"] == original
    assert "label_metadata" not in observed[0]
    assert "expected" not in observed[0]


def test_grounding_checks_exact_type_and_external_citation():
    rows = load_cases()[:1]

    def corrupted(input_case):
        output = assess_case(input_case)
        output.evidence = [Evidence(source="platform_outage", value=0, description="Incorrect type.")]
        output.policy_version = "unknown"
        output.policy_citations = [
            PolicyCitation(id="fake", version="unknown", source="unknown", section="1", text="Unsupported text.")
        ]
        output.retrieved_policy_clauses = ["Other fabricated text."]
        return output

    result = evaluate_model(rows, corrupted, requirement_policy())
    assert result["grounding_error_count"] == 3
    assert result["grounding_error_rate"] == 1


def test_binned_ece_does_not_cancel_opposite_bin_errors():
    rows = [
        {"expected": "ERR-02", "predicted": "ERR-02", "support": 0.1},
        {"expected": "ERR-02", "predicted": "ERR-05", "support": 0.9},
    ]
    diagnostics = calibration_diagnostics(rows)
    assert diagnostics["ece_diagnostic"] == pytest.approx(0.9)
    assert diagnostics["brier_diagnostic"] == pytest.approx(0.81)
    assert diagnostics["calibrated"] is False


def test_duplicate_ids_and_empty_dataset_fail(tmp_path):
    path = tmp_path / "cases.json"
    rows = load_cases()[:1]
    path.write_text(json.dumps(rows + rows), encoding="utf-8")
    with pytest.raises(ValueError, match="unique IDs"):
        load_cases(path)
    with pytest.raises(ValueError, match="empty split"):
        evaluate_model([], assess_case, requirement_policy())


def test_demo_requirement_policy_is_exact_source_text():
    repository = requirement_policy()
    for citation in repository.retrieve("PRD-v1.1"):
        assert citation.is_demo_policy
        assert citation.source == "docs/ba/PRD.md"
        assert citation.text.startswith("| **ERR-")


def test_explicit_heldout_adapter_uses_only_observations():
    fixture = load_cases()[0]
    case = {
        "case_id": "heldout-explicit",
        "split": "held_out",
        "execution": {"adapter": "forensic_input", "input": fixture["input"]},
        "expected": {"facts": [{"key": "category", "value": fixture["expected"]}]},
    }
    rows, not_run = project_held_out({"cases": [case]})
    assert not not_run
    assert len(rows) == 1
    assert rows[0]["input"]["case_id"] == fixture["input"]["case_id"]
    assert "expected" not in rows[0]["input"]
    case["execution"]["input"] = fixture["input"] | {"scenario": "intentional_dic"}
    with pytest.raises(ValueError):
        project_held_out({"cases": [case]})

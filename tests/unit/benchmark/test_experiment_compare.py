"""Unit tests for experiment comparator and registry update (Issue #497 / Epic #494)."""

import json
from pathlib import Path

import pytest

from scripts.benchmark.experiments import compare


def _make_metrics(
    macro_f1: float = 0.80,
    fpr: float = 0.02,
    adverse_recall: float = 0.70,
    pr_auc: dict | None = None,
    ece: float = 0.05,
    ci_half_width: float = 0.01,
) -> dict:
    if pr_auc is None:
        pr_auc = {f"ERR-0{i}": 0.75 for i in range(1, 6)}
        pr_auc["no_violation"] = 0.90
        pr_auc["insufficient_evidence"] = 0.70
    return {
        "macro_f1": macro_f1,
        "ci_half_width": ci_half_width,
        "ci": [macro_f1 - ci_half_width, macro_f1 + ci_half_width],
        "no_violation_fpr": fpr,
        "adverse_recall_at_budget": adverse_recall,
        "per_class_pr_auc": pr_auc,
        "calibration": {"ece_10bin": ece, "brier": 0.10},
    }


def test_baseline_attempt_keep():
    cand = _make_metrics(macro_f1=0.75)
    decision, guards, best_so_far = compare.evaluate_decision(candidate=cand, best=None)
    assert decision == "keep"
    assert guards["all_passed"] is True
    assert best_so_far == 0.75


def test_keep_when_primary_improves_and_guards_pass():
    best = _make_metrics(macro_f1=0.70, ci_half_width=0.02)
    # diff = 0.75 - 0.70 = 0.05 > 0.02 (half-width)
    cand = _make_metrics(macro_f1=0.75, ci_half_width=0.02)
    decision, guards, best_so_far = compare.evaluate_decision(candidate=cand, best=best, paired_ci_half_width=0.02)
    assert decision == "keep"
    assert guards["all_passed"] is True
    assert best_so_far == 0.75


def test_revert_when_primary_gain_not_exceeding_ci_half_width():
    best = _make_metrics(macro_f1=0.70)
    # diff = 0.71 - 0.70 = 0.01 <= 0.02 (half-width)
    cand = _make_metrics(macro_f1=0.71)
    decision, guards, best_so_far = compare.evaluate_decision(candidate=cand, best=best, paired_ci_half_width=0.02)
    assert decision == "revert"
    assert best_so_far == 0.70


def test_revert_when_fpr_guard_fails():
    best = _make_metrics(macro_f1=0.70, fpr=0.020)
    # Candidate FPR = 0.026 > 0.020 + 0.005 -> fails FPR guard
    cand = _make_metrics(macro_f1=0.80, fpr=0.026)
    decision, guards, best_so_far = compare.evaluate_decision(candidate=cand, best=best, paired_ci_half_width=0.01)
    assert decision == "revert"
    assert guards["fpr_ok"] is False
    assert guards["all_passed"] is False
    assert best_so_far == 0.70


def test_revert_when_adverse_recall_guard_fails():
    best = _make_metrics(macro_f1=0.70, adverse_recall=0.75)
    # Candidate recall = 0.739 < 0.75 - 0.01 = 0.74 -> fails recall guard
    cand = _make_metrics(macro_f1=0.80, adverse_recall=0.739)
    decision, guards, best_so_far = compare.evaluate_decision(candidate=cand, best=best, paired_ci_half_width=0.01)
    assert decision == "revert"
    assert guards["recall_at_budget_ok"] is False
    assert best_so_far == 0.70


def test_revert_when_pr_auc_drops_more_than_tolerance():
    best_pr = {f"ERR-0{i}": 0.80 for i in range(1, 6)}
    cand_pr = dict(best_pr)
    # ERR-03 drops by 0.035 > 0.03
    cand_pr["ERR-03"] = 0.764
    best = _make_metrics(macro_f1=0.70, pr_auc=best_pr)
    cand = _make_metrics(macro_f1=0.80, pr_auc=cand_pr)
    decision, guards, best_so_far = compare.evaluate_decision(candidate=cand, best=best, paired_ci_half_width=0.01)
    assert decision == "revert"
    assert guards["pr_auc_ok"] is False
    assert best_so_far == 0.70


def test_revert_when_ece_guard_fails():
    best = _make_metrics(macro_f1=0.70, ece=0.04)
    # Candidate ECE = 0.061 > 0.04 + 0.02 -> fails ECE guard
    cand = _make_metrics(macro_f1=0.80, ece=0.061)
    decision, guards, best_so_far = compare.evaluate_decision(candidate=cand, best=best, paired_ci_half_width=0.01)
    assert decision == "revert"
    assert guards["ece_ok"] is False
    assert best_so_far == 0.70


def test_append_registry_row(tmp_path: Path):
    reg_path = tmp_path / "registry.jsonl"
    cand = _make_metrics(macro_f1=0.72)

    row = compare.record_experiment_attempt(
        registry_path=reg_path,
        candidate_metrics=cand,
        best_metrics=None,
        exp_id="E0",
        variant="baseline",
        issue="#497",
        pr="",
        paired_ci_half_width=0.01,
    )
    assert row["attempt"] == 0
    assert row["exp_id"] == "E0"
    assert row["variant"] == "baseline"
    assert row["decision"] == "keep"
    assert row["best_so_far"] == 0.72
    assert reg_path.exists()

    # Second row with revert
    cand2 = _make_metrics(macro_f1=0.725)
    row2 = compare.record_experiment_attempt(
        registry_path=reg_path,
        candidate_metrics=cand2,
        best_metrics=cand,
        exp_id="E1",
        variant="noisy_variant",
        issue="#497",
        pr="#498",
        paired_ci_half_width=0.02,  # gain 0.005 < 0.02
    )
    assert row2["attempt"] == 1
    assert row2["decision"] == "revert"
    assert row2["best_so_far"] == 0.72

    # Check file lines
    lines = [json.loads(line) for line in reg_path.read_text().strip().splitlines()]
    assert len(lines) == 2
    assert lines[0]["decision"] == "keep"
    assert lines[1]["decision"] == "revert"


def test_compare_rejects_mismatched_trip_refs(tmp_path: Path):
    cand_preds = tmp_path / "cand_preds.jsonl"
    best_preds = tmp_path / "best_preds.jsonl"
    cand_preds.write_text(
        '{"trip_ref": "t1", "label": "no_violation", "predicted_category": "no_violation"}\n'
        '{"trip_ref": "t2", "label": "ERR-01", "predicted_category": "ERR-01"}\n',
        encoding="utf-8",
    )
    best_preds.write_text(
        '{"trip_ref": "t1", "label": "no_violation", "predicted_category": "no_violation"}\n'
        '{"trip_ref": "t3", "label": "ERR-01", "predicted_category": "ERR-01"}\n',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="[Mm]ismatched trip_ref"):
        compare.compute_paired_ci_from_predictions(cand_preds, best_preds)


def test_compare_rejects_mismatched_sha():
    cand = _make_metrics(macro_f1=0.75)
    cand["corpus_trips_sha256"] = "sha_alpha"
    best = _make_metrics(macro_f1=0.70)
    best["corpus_trips_sha256"] = "sha_beta"
    with pytest.raises(ValueError, match="[Mm]ismatched corpus_trips_sha256"):
        compare.evaluate_decision(candidate=cand, best=best, paired_ci_half_width=0.01)


def test_compare_rejects_mismatched_enum_blind():
    cand = _make_metrics(macro_f1=0.75)
    cand["enum_blind"] = True
    best = _make_metrics(macro_f1=0.70)
    best["enum_blind"] = False
    with pytest.raises(ValueError, match="[Mm]ismatched enum_blind"):
        compare.evaluate_decision(candidate=cand, best=best, paired_ci_half_width=0.01)


def test_attempts_folder_to_registry(tmp_path: Path):
    attempts_dir = tmp_path / "attempts"
    attempts_dir.mkdir()
    registry_file = tmp_path / "registry.jsonl"

    cand_e0 = _make_metrics(macro_f1=0.70)
    cand_e0["corpus_trips_sha256"] = "sha_same"
    cand_e0["enum_blind"] = True

    cand_e1 = _make_metrics(macro_f1=0.75)
    cand_e1["corpus_trips_sha256"] = "sha_same"
    cand_e1["enum_blind"] = True

    compare.record_attempt_file(
        attempts_dir=attempts_dir,
        exp_id="E0",
        variant="baseline",
        candidate_metrics=cand_e0,
        best_metrics=None,
        issue="#494",
        paired_ci_half_width=0.01,
    )
    compare.record_attempt_file(
        attempts_dir=attempts_dir,
        exp_id="E1",
        variant="v1",
        candidate_metrics=cand_e1,
        best_metrics=cand_e0,
        issue="#495",
        paired_ci_half_width=0.01,
    )

    # Assign attempts and build registry
    assigned = compare.assign_attempts(attempts_dir)
    assert len(assigned) == 2
    assert assigned[0]["attempt"] == 0
    assert assigned[1]["attempt"] == 1

    compare.build_registry_from_attempts(attempts_dir, registry_file)
    assert registry_file.exists()
    lines = [json.loads(line) for line in registry_file.read_text().strip().splitlines()]
    assert len(lines) == 2
    assert lines[0]["exp_id"] == "E0"
    assert lines[1]["exp_id"] == "E1"


def test_compare_refuses_when_candidate_valid_false():
    cand = _make_metrics(macro_f1=0.80)
    cand["valid"] = False
    best = _make_metrics(macro_f1=0.70)
    best["valid"] = True
    with pytest.raises(ValueError, match="valid=false"):
        compare.evaluate_decision(candidate=cand, best=best, paired_ci_half_width=0.01)


def test_compare_refuses_when_best_valid_false():
    cand = _make_metrics(macro_f1=0.80)
    cand["valid"] = True
    best = _make_metrics(macro_f1=0.70)
    best["valid"] = False
    with pytest.raises(ValueError, match="valid=false"):
        compare.evaluate_decision(candidate=cand, best=best, paired_ci_half_width=0.01)


def test_compare_refuses_when_candidate_live_failure_rate_above_limit():
    cand = _make_metrics(macro_f1=0.80)
    cand["valid"] = True
    cand["live_failure_rate"] = 0.05
    best = _make_metrics(macro_f1=0.70)
    best["valid"] = True
    best["live_failure_rate"] = 0.01
    with pytest.raises(ValueError, match="live_failure_rate.*exceeds"):
        compare.evaluate_decision(candidate=cand, best=best, paired_ci_half_width=0.01)


def test_compare_refuses_when_best_live_failure_rate_above_limit():
    cand = _make_metrics(macro_f1=0.80)
    cand["valid"] = True
    cand["live_failure_rate"] = 0.01
    best = _make_metrics(macro_f1=0.70)
    best["valid"] = True
    best["live_failure_rate"] = 0.03
    with pytest.raises(ValueError, match="live_failure_rate.*exceeds"):
        compare.evaluate_decision(candidate=cand, best=best, paired_ci_half_width=0.01)


def test_compare_cli_refuses_on_invalid_candidate(tmp_path: Path):
    cand_file = tmp_path / "cand_metrics.json"
    cand_data = _make_metrics(macro_f1=0.80)
    cand_data["valid"] = False
    cand_data["exp_id"] = "E1"
    cand_data["variant"] = "test_var"
    cand_file.write_text(json.dumps(cand_data), encoding="utf-8")

    attempts_dir = tmp_path / "attempts"

    # Running compare main with invalid candidate exits non-zero
    with pytest.raises(SystemExit) as excinfo:
        # sys.argv simulation
        import sys

        orig_argv = sys.argv
        try:
            sys.argv = [
                "compare.py",
                "--candidate",
                str(cand_file),
                "--attempts-dir",
                str(attempts_dir),
            ]
            compare.main()
        finally:
            sys.argv = orig_argv

    assert excinfo.value.code != 0

"""Synthetic records test scorer contracts only; these are not operator evidence."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta

import pytest

from eval.phase1_benchmark import COHORTS, compare, reviewer_order, score, validate_manifest


def records(tmp_path):
    manifest = {
        "dataset_version": "test-only-v1",
        "split": "held_out",
        "gold_fixed_at": "2026-10-01T00:00:00Z",
        "cases": [
            {
                "case_id": f"c{i}",
                "cohort": COHORTS[i // 10],
                "gold_decision": "hold",
                "provenance": "synthetic contract test only",
                "source_refs": [f"fixture:{i}"],
                "inputs": {"case_id": f"c{i}"},
            }
            for i in range(30)
        ],
    }
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    reviewers = [{"id": f"person-{i}", "seed": i, "case_order": reviewer_order(manifest["cases"], i)} for i in range(3)]
    start = datetime(2026, 10, 2, tzinfo=UTC)
    rows = []
    for reviewer in reviewers:
        for seq, cid in enumerate(reviewer["case_order"]):
            rendered = start + timedelta(seconds=seq * 60)
            rows.append(
                {
                    "reviewer": reviewer["id"],
                    "case_id": cid,
                    "decision": "hold",
                    "artifact_ref": "fixture:observation",
                    "rationale": "Fixture reviewer rationale",
                    "task_completed": True,
                    "evidence_grounded": True,
                    "workflow_correct": True,
                    "sanction_applied": False,
                    "authorized_human": True,
                    "tool_failures": 0,
                    "evidence_refs": [f"fixture:{cid[1:]}"],
                    "dossier_rendered_at": rendered.isoformat(),
                    "submitted_at": (rendered + timedelta(seconds=10)).isoformat(),
                    "mttr_seconds": 10,
                    "agent_latency_seconds": 1,
                    "cost_usd": 0.001,
                }
            )
    observation = {
        "model": "fixture-model",
        "prompt_version": "fixture-prompt",
        "commit": "fixture-commit",
        "dataset_version": manifest["dataset_version"],
        "manifest_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "run_id": "fixture-run",
        "environment": {"kind": "synthetic-test"},
        "mode": "human_observation",
        "started_at": start.isoformat(),
        "ended_at": (start + timedelta(hours=1)).isoformat(),
        "reviewers": reviewers,
        "observations": rows,
    }
    return manifest, observation, path


def write(tmp_path, value, name="observations.json"):
    path = tmp_path / name
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def test_complete_contract_reports_separate_reviewers_and_measured_metrics(tmp_path):
    _, observation, manifest = records(tmp_path)
    result = score(manifest, write(tmp_path, observation))
    assert result["status"] == "pass"
    assert [r["matching_decisions"] for r in result["reviewers"]] == [30, 30, 30]
    assert result["cost_usd"]["samples"] == 90
    assert result["metrics"]["human_integrity"] == 1
    assert result["cohort_mean_mttr_seconds"] == 10


@pytest.mark.parametrize("matches,passes", [(27, False), (28, True)])
def test_strict_concordance_cannot_pool_a_failing_reviewer(tmp_path, matches, passes):
    _, observation, manifest = records(tmp_path)
    for row in observation["observations"][: 30 - matches]:
        row["decision"] = "dismiss"
    result = score(manifest, write(tmp_path, observation))
    assert result["gates"]["per_reviewer_concordance"] is passes
    assert result["reviewers"][1]["matching_decisions"] == 30


@pytest.mark.parametrize("duration,passes", [(45, False), (44.9, True)])
def test_mttr_boundary_uses_render_and_submission(tmp_path, duration, passes):
    _, observation, manifest = records(tmp_path)
    for row in observation["observations"]:
        stamp = datetime.fromisoformat(row["dossier_rendered_at"])
        row["submitted_at"] = (stamp + timedelta(seconds=duration)).isoformat()
        row["mttr_seconds"] = duration
    assert score(manifest, write(tmp_path, observation))["gates"]["mean_mttr"] is passes


def test_mttr_is_cohort_mean_not_individual_reviewer_gate(tmp_path):
    _, observation, manifest = records(tmp_path)
    for row in observation["observations"][:30]:
        stamp = datetime.fromisoformat(row["dossier_rendered_at"])
        row.update(mttr_seconds=50, submitted_at=(stamp + timedelta(seconds=50)).isoformat())
    result = score(manifest, write(tmp_path, observation))
    assert result["reviewers"][0]["mean_mttr_seconds"] == 50
    assert result["gates"]["mean_mttr"]


@pytest.mark.parametrize("value", [True, float("nan"), float("inf"), -1])
def test_invalid_numeric_measurements_rejected(tmp_path, value):
    _, observation, manifest = records(tmp_path)
    observation["observations"][0]["cost_usd"] = value
    with pytest.raises(ValueError, match="finite non-negative"):
        score(manifest, write(tmp_path, observation))


@pytest.mark.parametrize(
    "field", ["authorized_human", "sanction_applied", "evidence_grounded", "workflow_correct", "task_completed"]
)
def test_missing_safety_or_quality_fields_never_default_to_pass(tmp_path, field):
    _, observation, manifest = records(tmp_path)
    del observation["observations"][0][field]
    with pytest.raises(ValueError, match="explicit boolean"):
        score(manifest, write(tmp_path, observation))


def test_automatic_dismissal_fails_human_integrity(tmp_path):
    _, observation, manifest = records(tmp_path)
    observation["observations"][0].update(decision="dismiss", authorized_human=False)
    result = score(manifest, write(tmp_path, observation))
    assert result["status"] == "fail_or_unverified"
    assert len(result["safety_violations"]) == 1


def test_outage_warning_fails_guardrail_even_with_authorized_human(tmp_path):
    _, observation, manifest = records(tmp_path)
    row = next(r for r in observation["observations"] if r["case_id"] == "c20")
    row.update(decision="warning", sanction_applied=True)
    assert not score(manifest, write(tmp_path, observation))["gates"]["guardrail"]


def test_missing_cost_or_fixture_mode_keeps_acceptance_unverified(tmp_path):
    _, observation, manifest = records(tmp_path)
    observation["mode"] = "local_fixture"
    observation["observations"][0]["cost_usd"] = None
    result = score(manifest, write(tmp_path, observation))
    assert not result["gates"]["human_evidence"]
    assert not result["gates"]["cost_latency_measured"]
    assert result["cost_usd"]["total"] is None


@pytest.mark.parametrize("change", ["missing", "duplicate", "wrong_hash", "wrong_order", "gold_leak", "wrong_cohort"])
def test_protocol_input_integrity(tmp_path, change):
    manifest_data, observation, manifest = records(tmp_path)
    if change == "missing":
        observation["observations"].pop()
    elif change == "duplicate":
        observation["observations"][-1] = observation["observations"][0]
    elif change == "wrong_hash":
        observation["manifest_sha256"] = "wrong"
    elif change == "wrong_order":
        observation["reviewers"][0]["case_order"].reverse()
    elif change == "gold_leak":
        manifest_data["cases"][0]["inputs"]["gold_decision"] = "hold"
        manifest = write(tmp_path, manifest_data, "manifest.json")
    else:
        manifest_data["cases"][0]["cohort"] = "ERR-05"
        manifest = write(tmp_path, manifest_data, "manifest.json")
    with pytest.raises(ValueError):
        score(manifest, write(tmp_path, observation))


def test_candidate_reports_safety_regression_and_paired_uncertainty(tmp_path):
    _, observation, manifest = records(tmp_path)
    baseline = write(tmp_path, observation, "baseline.json")
    observation["run_id"] = "fixture-candidate"
    observation["observations"][0]["authorized_human"] = False
    result = score(manifest, baseline, candidate_path=write(tmp_path, observation, "candidate.json"))
    comparison = result["comparison"]
    assert "human_integrity" in comparison["regressions"][0]["fields"]
    assert comparison["paired_case_bootstrap95_seconds"] == [0, 0]
    other = score(manifest, baseline)
    other["provenance"]["manifest_sha256"] = "changed"
    with pytest.raises(ValueError, match="same fixed"):
        compare(result, other)


def test_manifest_cannot_repeat_cases(tmp_path):
    manifest, _, _ = records(tmp_path)
    manifest["cases"][-1]["case_id"] = "c0"
    with pytest.raises(ValueError, match="unique"):
        validate_manifest(manifest)


def test_unknown_decision_cannot_bypass_adverse_integrity(tmp_path):
    _, observation, manifest = records(tmp_path)
    observation["observations"][0]["decision"] = "Suspend 24h"
    with pytest.raises(ValueError, match="normalized"):
        score(manifest, write(tmp_path, observation))


def test_cli_export_excludes_fixed_gold_and_fixture_acceptance_exits_nonzero(tmp_path, monkeypatch, capsys):
    from eval.phase1_benchmark import main

    _, observation, manifest = records(tmp_path)
    monkeypatch.setattr("sys.argv", ["benchmark", "--manifest", str(manifest), "--export-inputs"])
    assert main() == 0
    exported = json.loads(capsys.readouterr().out)
    assert all(set(row) == {"case_id", "inputs"} for row in exported["cases"])
    observation["mode"] = "local_fixture"
    monkeypatch.setattr(
        "sys.argv", ["benchmark", "--manifest", str(manifest), "--observations", str(write(tmp_path, observation))]
    )
    assert main() == 1
    assert json.loads(capsys.readouterr().out)["status"] == "fail_or_unverified"


def test_cli_candidate_safety_failure_exits_nonzero(tmp_path, monkeypatch, capsys):
    from eval.phase1_benchmark import main

    _, observation, manifest = records(tmp_path)
    baseline = write(tmp_path, observation, "baseline.json")
    observation["observations"][0]["authorized_human"] = False
    candidate = write(tmp_path, observation, "candidate.json")
    monkeypatch.setattr(
        "sys.argv",
        ["benchmark", "--manifest", str(manifest), "--observations", str(baseline), "--candidate", str(candidate)],
    )
    assert main() == 1
    assert not json.loads(capsys.readouterr().out)["comparison"]["candidate_gates"]["human_integrity"]


def test_nested_gold_cannot_be_exported_as_runtime_evidence(tmp_path):
    manifest, _, _ = records(tmp_path)
    manifest["cases"][0]["inputs"]["nested"] = [{"gold_decision": "hold"}]
    with pytest.raises(ValueError, match="evaluation labels"):
        validate_manifest(manifest)

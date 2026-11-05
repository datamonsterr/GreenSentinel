"""Paired fixture benchmark and honest inventory of the unexecutable held-out corpus."""

from __future__ import annotations

import hashlib
import json
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from src.agents.forensic_baseline import BASELINE_VERSION, CANDIDATE_VERSION, assess_case, assess_case_grounded
from src.models.forensic import ForensicInput, ForensicOutput
from src.models.policy import PolicySource
from src.services.grounded_policy import PolicyRepository

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_PATH = ROOT / "eval/fixtures/issue62_development_v1.json"
CORPUS_PATH = ROOT / "eval/corpus/v1/corpus.json"
RESULTS_DIR = ROOT / "eval/results"
CATEGORIES = ["ERR-02", "ERR-05", "no_violation", "insufficient_evidence"]
THRESHOLDS = {
    "overall_accuracy": 0.85,
    "ERR-02_f1": 0.85,
    "ERR-05_f1": 0.80,
    "no_violation_f1": 0.80,
    "insufficient_evidence_f1": 0.85,
    "grounding_error_count": 0,
    "schema_validity": 1.0,
    "automated_sanctions": 0,
}


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def load_cases(path: Path = FIXTURE_PATH) -> list[dict[str, Any]]:
    rows = json.loads(path.read_text(encoding="utf-8"))
    ids = [row["id"] for row in rows]
    if not rows or len(ids) != len(set(ids)):
        raise ValueError("Fixture must be non-empty with unique IDs.")
    for row in rows:
        ForensicInput.model_validate(row["input"])
        if row["expected"] not in CATEGORIES:
            raise ValueError("Unknown expected category.")
    return rows


def requirement_policy(root: Path = ROOT) -> PolicyRepository:
    """Extract actual PRD text as explicitly demo requirement policy, not a handbook."""
    text = (root / "docs/ba/PRD.md").read_text(encoding="utf-8")
    sources = [
        PolicySource(
            id="requirement-" + category,
            version="PRD-v1.1",
            source="docs/ba/PRD.md",
            section="§3/" + category,
            text=line,
            is_demo_policy=True,
        )
        for category in ("ERR-02", "ERR-05")
        for line in text.splitlines()
        if line.startswith("| **" + category + "**")
    ]
    return PolicyRepository(sources)


def calibration_diagnostics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Binned score/correctness diagnostics; ordinal support remains uncalibrated."""
    bins = []
    ece = 0.0
    for index in range(5):
        low, high = index / 5, (index + 1) / 5
        selected = [r for r in rows if low <= r["support"] < high or (index == 4 and r["support"] == 1.0)]
        if not selected:
            continue
        accuracy = sum(r["expected"] == r["predicted"] for r in selected) / len(selected)
        support = sum(r["support"] for r in selected) / len(selected)
        ece += len(selected) / len(rows) * abs(accuracy - support)
        bins.append(
            {"lower": low, "upper": high, "count": len(selected), "accuracy": accuracy, "mean_support": support}
        )
    return {
        "ece_diagnostic": ece,
        "brier_diagnostic": sum((r["support"] - float(r["expected"] == r["predicted"])) ** 2 for r in rows) / len(rows),
        "bins": bins,
        "calibrated": False,
        "semantics": "Ordinal support vs category correctness; not violation probability. Abstention is a category.",
    }


def evaluate_model(
    rows: list[dict[str, Any]], model: Callable[[ForensicInput], ForensicOutput], repository: PolicyRepository
) -> dict[str, Any]:
    if not rows:
        raise ValueError("Cannot evaluate an empty split.")
    validator = Draft202012Validator(ForensicOutput.model_json_schema())
    measured = []
    invalid = sanctions = errors_total = claims = 0
    matrix = {a: {p: 0 for p in CATEGORIES} for a in CATEGORIES}
    for row in rows:
        # The model sees only strict runtime facts, never labels or corpus metadata.
        inp = ForensicInput.model_validate(row["input"])
        out = model(inp)
        dumped = out.model_dump(mode="json")
        valid = validator.is_valid(dumped)
        invalid += int(not valid)
        facts = inp.model_dump()
        errors = []
        for ev in out.evidence:
            claims += 1
            if ev.source not in facts or type(ev.value) is not type(facts[ev.source]) or ev.value != facts[ev.source]:
                errors.append("ungrounded_evidence:" + ev.source)
        allowed = [r.model_dump() for r in repository.retrieve(inp.policy_version_id or "")]
        citations = [c.model_dump() for c in out.policy_citations]
        for citation in citations:
            claims += 1
            if citation not in allowed or citation["version"] != out.policy_version:
                errors.append("ungrounded_policy_citation")
        for clause in out.retrieved_policy_clauses:
            claims += 1
            if clause not in [c["text"] for c in citations]:
                errors.append("uncited_policy_text")
        if out.policy_version and not citations:
            claims += 1
            errors.append("unretrieved_policy_version")
        errors_total += len(errors)
        sanctions += int(
            dumped.get("sanctions_prohibited") is not True
            or dumped.get("human_confirmation_required") is not True
            or dumped.get("punitive", False)
        )
        matrix[row["expected"]][out.category] += 1
        measured.append(
            {
                "case_id": row["id"],
                "expected": row["expected"],
                "predicted": out.category,
                "support": out.confidence,
                "schema_valid": valid,
                "grounding_errors": errors,
                "output": dumped,
            }
        )
    n = len(rows)
    per_class = {}
    for category in CATEGORIES:
        tp = matrix[category][category]
        fp = sum(matrix[a][category] for a in CATEGORIES if a != category)
        fn = sum(matrix[category][p] for p in CATEGORIES if p != category)
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        per_class[category] = {
            "support": sum(matrix[category].values()),
            "precision": precision,
            "recall": recall,
            "f1": 2 * precision * recall / (precision + recall) if precision + recall else 0.0,
        }
    return {
        "sample_count": n,
        "overall_accuracy": sum(r["expected"] == r["predicted"] for r in measured) / n,
        "per_class": per_class,
        "confusion_matrix": matrix,
        "schema_validity": 1 - invalid / n,
        "grounding_error_count": errors_total,
        "grounding_claim_count": claims,
        "grounding_error_rate": errors_total / claims if claims else 0.0,
        "automated_sanctions": sanctions,
        "calibration": calibration_diagnostics(measured),
        "cases": measured,
    }


def acceptance_gates(candidate: dict[str, Any]) -> dict[str, Any]:
    results = {}
    for name, threshold in THRESHOLDS.items():
        value = candidate["per_class"][name[:-3]]["f1"] if name.endswith("_f1") else candidate[name]
        maximum = name in {"grounding_error_count", "automated_sanctions"}
        results[name] = {
            "value": value,
            "threshold": threshold,
            "passed": value <= threshold if maximum else value >= threshold,
        }
    return results


def project_held_out(corpus: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Run only explicit measured input adapters; references alone are not observations."""
    executable, not_run = [], []
    for case in corpus["cases"]:
        if case["split"] != "held_out":
            continue
        execution = case["execution"]
        if execution["adapter"] == "forensic_input":
            facts = ForensicInput.model_validate(execution["input"])
            labels = [fact["value"] for fact in case["expected"]["facts"] if fact["key"] == "category"]
            if len(labels) != 1 or labels[0] not in CATEGORIES:
                raise ValueError("Explicit forensic adapter needs exactly one supported evaluation label.")
            executable.append({"id": case["case_id"], "input": facts.model_dump(), "expected": labels[0]})
        else:
            not_run.append(
                {
                    "case_id": case["case_id"],
                    "adapter": execution["adapter"],
                    "fixture_ref": execution["fixture_ref"],
                    "reason": "No verified mapping from referenced evidence to ForensicInput; labels never create observations.",
                }
            )
    return executable, not_run


def run_benchmark(destination: Path | None = RESULTS_DIR) -> dict[str, Any]:
    fixture = load_cases()
    repository = requirement_policy()
    baseline = evaluate_model(fixture, assess_case, repository)
    candidate = evaluate_model(fixture, lambda inp: assess_case_grounded(inp, repository), repository)
    corpus = json.loads(CORPUS_PATH.read_text(encoding="utf-8"))
    held_out = [c for c in corpus["cases"] if c["split"] == "held_out"]
    executable, not_run = project_held_out(corpus)
    revision = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.strip()
    report = {
        "metadata": {
            "benchmark_version": "issue62-paired-v1",
            "dataset_version": "issue62-development-v1",
            "dataset_sha256": _sha(FIXTURE_PATH),
            "corpus_version": corpus["corpus_version"],
            "corpus_sha256": _sha(CORPUS_PATH),
            "revision": revision,
            "baseline_version": BASELINE_VERSION,
            "candidate_version": CANDIDATE_VERSION,
            "model_code_sha256": _sha(ROOT / "src/agents/forensic_baseline.py"),
            "retrieval_sha256": _sha(ROOT / "src/services/grounded_policy.py"),
            "schema_sha256": _sha(ROOT / "src/models/forensic.py"),
            "policy_schema_sha256": _sha(ROOT / "src/models/policy.py"),
            "policy_source_sha256": _sha(ROOT / "docs/ba/PRD.md"),
            "prompt_version": "none-deterministic-rules",
            "harness_sha256": _sha(Path(__file__)),
            "paired_case_ids": [r["id"] for r in fixture],
            "independent_held_out": False,
            "scope": "Existing exposed synthetic development fixtures; no unseen or production accuracy claim.",
            "approval": "User approved thresholds 2026-10-03 before session tuning; fixture/local only.",
        },
        "baseline": baseline,
        "candidate": candidate,
        "held_out": {
            "total": len(held_out),
            "executed": len(executable),
            "not_run": not_run,
            "paired_case_ids": [row["id"] for row in executable],
            "baseline": evaluate_model(executable, assess_case, repository) if executable else None,
            "candidate": evaluate_model(executable, lambda inp: assess_case_grounded(inp, repository), repository)
            if executable
            else None,
        },
        "acceptance_thresholds": acceptance_gates(candidate),
        "release_acceptance": False,
    }
    if destination is not None:
        destination.mkdir(parents=True, exist_ok=True)
        (destination / "issue62_benchmark.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        summary = f"# Issue #62 paired fixture benchmark\n\nFixture cases: {len(fixture)}. Baseline accuracy: {baseline['overall_accuracy']:.2f}. Candidate accuracy: {candidate['overall_accuracy']:.2f}.\n\nAll {len(held_out)} referenced held-out cases are not run: no verified input adapter. The source fixtures were previously exposed; this is development evidence. Calibration diagnostics do not certify ordinal scores as probabilities. Policy citations extract actual PRD requirement text, labeled demo policy, not approved partner handbooks. See [JSON](issue62_benchmark.json) for per-class metrics, case IDs, exact outputs, hashes, grounding and acceptance gates.\n"
        (destination / "issue62_benchmark_report.md").write_text(summary, encoding="utf-8")
    return report


if __name__ == "__main__":
    report = run_benchmark()
    print(
        json.dumps(
            {
                "fixture_cases": report["candidate"]["sample_count"],
                "candidate_accuracy": report["candidate"]["overall_accuracy"],
                "held_out_executed": report["held_out"]["executed"],
                "release_acceptance": report["release_acceptance"],
            },
            indent=2,
        )
    )

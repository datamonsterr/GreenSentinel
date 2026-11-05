"""Score imported Phase 1 observations; never manufacture corpus or reviewer results."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import platform
import random
import statistics
from datetime import datetime
from pathlib import Path
from typing import Any

CASE_COUNT = 30
COHORTS = ("dic", "traffic_false_alarm", "technical_outage")
ADVERSE = {"warning", "fine", "suspension", "sanction"}
DECISIONS = ADVERSE | {"hold", "dismiss", "request_evidence", "escalate"}


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError("input must be a JSON object")
    return value


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _text(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value


def _number(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        raise ValueError(f"{name} must be a finite non-negative number")
    return float(value)


def _timestamp(value: Any, name: str) -> datetime:
    stamp = datetime.fromisoformat(_text(value, name).replace("Z", "+00:00"))
    if stamp.tzinfo is None:
        raise ValueError(f"{name} must have a timezone")
    return stamp


def _labels_in_inputs(value: Any) -> bool:
    if isinstance(value, dict):
        return any(
            key in {"gold_decision", "gold", "expected_decision", "cohort", "expected_category"}
            or _labels_in_inputs(child)
            for key, child in value.items()
        )
    return isinstance(value, list) and any(_labels_in_inputs(child) for child in value)


def validate_manifest(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    _text(manifest.get("dataset_version"), "dataset_version")
    _timestamp(manifest.get("gold_fixed_at"), "gold_fixed_at")
    if manifest.get("split") != "held_out":
        raise ValueError("manifest split must be held_out")
    cases = manifest.get("cases")
    if not isinstance(cases, list) or len(cases) != CASE_COUNT or not all(isinstance(c, dict) for c in cases):
        raise ValueError("manifest must contain exactly 30 cases")
    ids = [_text(c.get("case_id"), "case_id") for c in cases]
    if len(set(ids)) != CASE_COUNT:
        raise ValueError("manifest case_id values must be unique")
    cohorts = [c.get("cohort") for c in cases]
    if any(cohorts.count(cohort) != 10 for cohort in COHORTS):
        raise ValueError("manifest must contain exactly 10 cases in each fixed cohort")
    for case in cases:
        _text(case.get("gold_decision"), "gold_decision")
        if case["gold_decision"] not in DECISIONS:
            raise ValueError("gold_decision must use the normalized decision vocabulary")
        _text(case.get("provenance"), "case provenance")
        refs = case.get("source_refs")
        if not isinstance(refs, list) or not refs:
            raise ValueError("source_refs must identify each case's source evidence")
        for ref in refs:
            _text(ref, "source_ref")
        if not isinstance(case.get("inputs"), dict):
            raise ValueError("case inputs must be an object separate from gold")
        if _labels_in_inputs(case["inputs"]):
            raise ValueError("evaluation labels must not appear in runtime inputs")
    return cases


def reviewer_order(cases: list[dict[str, Any]], seed: int) -> list[str]:
    ids = [c["case_id"] for c in cases]
    random.Random(seed).shuffle(ids)
    return ids


def wilson(matches: int, total: int) -> list[float]:
    """Descriptive 95% Wilson interval; not independent reviewer population inference."""
    z = 1.959963984540054
    p = matches / total
    denominator = 1 + z * z / total
    centre = (p + z * z / (2 * total)) / denominator
    width = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / denominator
    return [max(0.0, centre - width), min(1.0, centre + width)]


def _evaluate(manifest: dict[str, Any], observation: dict[str, Any], manifest_hash: str) -> dict[str, Any]:
    cases = validate_manifest(manifest)
    for name in ("model", "prompt_version", "commit", "dataset_version", "run_id"):
        _text(observation.get(name), name)
    if (
        observation["dataset_version"] != manifest["dataset_version"]
        or observation.get("manifest_sha256") != manifest_hash
    ):
        raise ValueError("observation dataset/version/hash must match the fixed manifest")
    environment = observation.get("environment")
    if not isinstance(environment, dict) or not environment:
        raise ValueError("observation environment is required")
    mode = observation.get("mode")
    if mode not in {"local_fixture", "isolated_database", "hosted", "human_observation"}:
        raise ValueError("mode must distinguish fixture, isolated_database, hosted or human_observation")
    started = _timestamp(observation.get("started_at"), "started_at")
    ended = _timestamp(observation.get("ended_at"), "ended_at")
    if ended < started or _timestamp(manifest["gold_fixed_at"], "gold_fixed_at") >= started:
        raise ValueError("gold must be fixed before a chronologically valid observation run")
    reviewers = observation.get("reviewers")
    if not isinstance(reviewers, list) or len(reviewers) != 3 or not all(isinstance(r, dict) for r in reviewers):
        raise ValueError("exactly three independent reviewers are required")
    reviewer_ids = [_text(r.get("id"), "reviewer id") for r in reviewers]
    if len(set(reviewer_ids)) != 3:
        raise ValueError("reviewer identities must be independent and unique")
    for reviewer in reviewers:
        seed = reviewer.get("seed")
        if isinstance(seed, bool) or not isinstance(seed, int):
            raise ValueError("reviewer randomization seed must be an integer")
        if reviewer.get("case_order") != reviewer_order(cases, seed):
            raise ValueError("reviewer case_order must match its reproducible randomization seed")
    if len({tuple(r["case_order"]) for r in reviewers}) != 3:
        raise ValueError("reviewers must use separate randomized case orders")
    rows = observation.get("observations")
    expected = {(r, c["case_id"]) for r in reviewer_ids for c in cases}
    if not isinstance(rows, list) or not all(isinstance(r, dict) for r in rows):
        raise ValueError("observations must be a list of records")
    if len(rows) != 90 or {(r.get("reviewer"), r.get("case_id")) for r in rows} != expected:
        raise ValueError("exactly 90 unique reviewer/case observations are required")
    gold = {c["case_id"]: c for c in cases}
    measured = []
    for row in rows:
        case = gold[row["case_id"]]
        _text(row.get("decision"), "decision")
        if row["decision"] not in DECISIONS:
            raise ValueError("decision must use the normalized decision vocabulary")
        _text(row.get("artifact_ref"), "observation artifact_ref")
        _text(row.get("rationale"), "human rationale")
        for name in ("task_completed", "evidence_grounded", "workflow_correct", "sanction_applied", "authorized_human"):
            if type(row.get(name)) is not bool:
                raise ValueError(f"{name} must be an explicit boolean")
        failures = row.get("tool_failures")
        if type(failures) is not int or failures < 0:
            raise ValueError("tool_failures must be a non-negative integer")
        refs = row.get("evidence_refs")
        if (
            not isinstance(refs, list)
            or not refs
            or not all(isinstance(r, str) and r in case["source_refs"] for r in refs)
        ):
            raise ValueError("evidence_refs must link observed claims to manifest sources")
        rendered = _timestamp(row.get("dossier_rendered_at"), "dossier_rendered_at")
        submitted = _timestamp(row.get("submitted_at"), "submitted_at")
        if not started <= rendered <= submitted <= ended:
            raise ValueError("dossier/submission timestamps must be ordered within the run")
        mttr = (submitted - rendered).total_seconds()
        if "mttr_seconds" in row and not math.isclose(
            _number(row["mttr_seconds"], "mttr_seconds"), mttr, abs_tol=0.001
        ):
            raise ValueError("mttr_seconds must match dossier render to successful submission")
        latency = (
            None
            if row.get("agent_latency_seconds") is None
            else _number(row["agent_latency_seconds"], "agent_latency_seconds")
        )
        cost = None if row.get("cost_usd") is None else _number(row["cost_usd"], "cost_usd")
        integrity = row["authorized_human"] and bool(row["rationale"].strip())
        integrity = integrity and (row["sanction_applied"] == (row["decision"] in ADVERSE))
        guardrail = not (
            case["cohort"] == "technical_outage" and (row["sanction_applied"] or row["decision"] in ADVERSE)
        )
        measured.append(
            {
                **row,
                "mttr_seconds": mttr,
                "agent_latency_seconds": latency,
                "cost_usd": cost,
                "matching": row["decision"] == case["gold_decision"],
                "human_integrity": integrity,
                "guardrail_ok": guardrail,
            }
        )
    summary = []
    for reviewer in reviewers:
        selected = [row for row in measured if row["reviewer"] == reviewer["id"]]
        if [row["case_id"] for row in selected] != reviewer["case_order"]:
            raise ValueError("observations must preserve each reviewer's actual randomized sequence")
        if any(
            _timestamp(first["submitted_at"], "submitted_at")
            > _timestamp(second["dossier_rendered_at"], "dossier_rendered_at")
            for first, second in zip(selected, selected[1:])
        ):
            raise ValueError("reviewer measurements must not overlap in time")
        matching = sum(row["matching"] for row in selected)
        summary.append(
            {
                "reviewer": reviewer["id"],
                "matching_decisions": matching,
                "cases": 30,
                "concordance": matching / 30,
                "concordance_wilson95": wilson(matching, 30),
                "mean_mttr_seconds": statistics.mean(row["mttr_seconds"] for row in selected),
            }
        )
    mean = statistics.mean(row["mttr_seconds"] for row in measured)
    violations = [
        {
            "reviewer": r["reviewer"],
            "case_id": r["case_id"],
            "guardrail_ok": r["guardrail_ok"],
            "human_integrity": r["human_integrity"],
        }
        for r in measured
        if not r["guardrail_ok"] or not r["human_integrity"]
    ]
    metrics = {
        name: sum(row[name] for row in measured) / 90
        for name in ("task_completed", "evidence_grounded", "workflow_correct", "guardrail_ok", "human_integrity")
    }
    complete = all(row["cost_usd"] is not None and row["agent_latency_seconds"] is not None for row in measured)
    gates = {
        "mean_mttr": mean < 45,
        "per_reviewer_concordance": all(r["matching_decisions"] >= 28 for r in summary),
        "guardrail": all(row["guardrail_ok"] for row in measured),
        "human_integrity": all(row["human_integrity"] for row in measured),
        "workflow": all(row["workflow_correct"] and row["task_completed"] for row in measured),
        "grounding": metrics["evidence_grounded"] > 0.90,
        "cost_latency_measured": complete,
        "human_evidence": mode == "human_observation",
    }
    costs = [row["cost_usd"] for row in measured if row["cost_usd"] is not None]
    latencies = [row["agent_latency_seconds"] for row in measured if row["agent_latency_seconds"] is not None]
    return {
        "protocol": "phase1-analyst-v1",
        "status": "pass" if all(gates.values()) else "fail_or_unverified",
        "gates": gates,
        "reviewers": summary,
        "cohort_mean_mttr_seconds": mean,
        "metrics": metrics,
        "tool_failures": sum(row["tool_failures"] for row in measured),
        "cost_usd": {"samples": len(costs), "total": sum(costs) if len(costs) == 90 else None},
        "agent_latency_seconds": {"samples": len(latencies), "mean": statistics.mean(latencies) if latencies else None},
        "safety_violations": violations,
        "cases": measured,
        "provenance": {
            key: observation[key]
            for key in (
                "model",
                "prompt_version",
                "commit",
                "dataset_version",
                "run_id",
                "environment",
                "mode",
                "started_at",
                "ended_at",
                "reviewers",
            )
        },
    }


def compare(baseline: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    if baseline["provenance"]["manifest_sha256"] != candidate["provenance"]["manifest_sha256"]:
        raise ValueError("comparison requires the same fixed held-out manifest")
    base = {(r["reviewer"], r["case_id"]): r for r in baseline["cases"]}
    other = {(r["reviewer"], r["case_id"]): r for r in candidate["cases"]}
    if base.keys() != other.keys():
        raise ValueError("comparison requires identical reviewer/case pairs")
    regressions = []
    deltas: dict[str, list[float]] = {}
    for key, first in base.items():
        second = other[key]
        worse = [
            field
            for field in (
                "matching",
                "task_completed",
                "evidence_grounded",
                "workflow_correct",
                "guardrail_ok",
                "human_integrity",
            )
            if first[field] and not second[field]
        ]
        worse += [
            field
            for field in ("mttr_seconds", "tool_failures", "cost_usd", "agent_latency_seconds")
            if first[field] is not None and second[field] is not None and second[field] > first[field]
        ]
        worse += [
            field
            for field in ("cost_usd", "agent_latency_seconds")
            if first[field] is not None and second[field] is None
        ]
        if worse:
            regressions.append({"reviewer": key[0], "case_id": key[1], "fields": worse})
        deltas.setdefault(key[1], []).append(second["mttr_seconds"] - first["mttr_seconds"])
    case_means = [statistics.mean(values) for values in deltas.values()]
    rng = random.Random(69)
    bootstrap = sorted(statistics.mean(rng.choices(case_means, k=30)) for _ in range(2000))
    return {
        "same_held_out_manifest": True,
        "candidate_status": candidate["status"],
        "candidate_gates": candidate["gates"],
        "candidate_reviewers": candidate["reviewers"],
        "candidate_metrics": candidate["metrics"],
        "candidate_cost_usd": candidate["cost_usd"],
        "candidate_agent_latency_seconds": candidate["agent_latency_seconds"],
        "candidate_tool_failures": candidate["tool_failures"],
        "regressions": regressions,
        "mean_mttr_delta_seconds": statistics.mean(case_means),
        "paired_case_bootstrap95_seconds": [bootstrap[49], bootstrap[1949]],
        "uncertainty": "2000 seeded case-cluster resamples, conditional on these three reviewers; repeated exposure/order effects and population generalization remain unmeasured.",
        "candidate_provenance": candidate["provenance"],
    }


def score(manifest_path: Path, observations_path: Path, *, candidate_path: Path | None = None) -> dict[str, Any]:
    manifest = _load(manifest_path)
    result = _evaluate(manifest, _load(observations_path), _sha(manifest_path))
    result["provenance"].update(manifest_sha256=_sha(manifest_path), observations_sha256=_sha(observations_path))
    result["scorer_environment"] = {"python": platform.python_version(), "platform": platform.platform()}
    if candidate_path:
        result["comparison"] = compare(result, score(manifest_path, candidate_path))
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--observations", type=Path)
    parser.add_argument("--candidate", type=Path)
    parser.add_argument(
        "--export-inputs",
        action="store_true",
        help="Export only manifest runtime inputs, excluding gold and cohort labels",
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result: dict[str, Any]
    if args.export_inputs:
        if args.observations or args.candidate:
            parser.error("--export-inputs cannot be combined with observations")
        result = {
            "cases": [{"case_id": c["case_id"], "inputs": c["inputs"]} for c in validate_manifest(_load(args.manifest))]
        }
    else:
        if not args.observations:
            parser.error("--observations is required for scoring")
        result = score(args.manifest, args.observations, candidate_path=args.candidate)
    rendered = json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    accepted = args.export_inputs or (
        result["status"] == "pass" and result.get("comparison", {}).get("candidate_status", "pass") == "pass"
    )
    return 0 if accepted else 1


if __name__ == "__main__":
    raise SystemExit(main())

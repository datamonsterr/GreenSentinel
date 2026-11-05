"""Validate and analyze the versioned evaluation corpus for issue #64."""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CORPUS = ROOT / "eval/corpus/v1/corpus.json"
DEFAULT_SCHEMA = ROOT / "eval/corpus/v1/corpus.schema.json"
FORMATS = FormatChecker()

FORBIDDEN_INPUT_KEYS = {
    "allowed_uncertainty",
    "expected",
    "expected_action",
    "expected_category",
    "expected_facts",
    "expected_guardrail",
    "gold_answer",
    "ground_truth",
    "label",
    "scenario",
    "sme_review",
}
PROTOCOL_SUITES = {
    "operational_dic": 10,
    "operational_traffic_false_alarm": 10,
    "operational_technical_outage": 10,
}
TAXONOMY = {f"ERR-0{index}" for index in range(1, 6)}


@FORMATS.checks("date-time")
def valid_timestamp(value: Any) -> bool:
    """Require a calendar-valid, timezone-aware timestamp when present."""
    if not isinstance(value, str):
        return True
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).tzinfo is not None
    except ValueError:
        return False


def load_json(path: Path) -> dict[str, Any]:
    """Load one JSON object."""
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain one JSON object")
    return value


def _walk_keys(value: Any, path: str = "input") -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            found.append((key, child_path))
            found.extend(_walk_keys(child, child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            found.extend(_walk_keys(child, f"{path}[{index}]"))
    return found


def validate_corpus(corpus: dict[str, Any], schema: dict[str, Any]) -> dict[str, Any]:
    """Validate JSON Schema plus cross-record safety and coverage invariants."""
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema, format_checker=FORMATS)
    schema_errors = sorted(validator.iter_errors(corpus), key=lambda error: list(error.path))
    if schema_errors:
        details = "; ".join(f"{'/'.join(map(str, error.path)) or '<root>'}: {error.message}" for error in schema_errors)
        raise ValueError(f"schema validation failed: {details}")

    cases = corpus["cases"]
    ids = [case["case_id"] for case in cases]
    if len(ids) != len(set(ids)):
        duplicates = sorted(case_id for case_id, count in Counter(ids).items() if count > 1)
        raise ValueError(f"duplicate case IDs: {duplicates}")

    groups: dict[str, set[str]] = defaultdict(set)
    suite_counts = Counter(case["suite"] for case in cases)
    split_counts = Counter(case["split"] for case in cases)
    taxonomy: set[str] = set()
    review_counts = Counter(case["sme_review"]["status"] for case in cases)

    for case in cases:
        case_id = case["case_id"]
        groups[case["leakage_group"]].add(case["split"])
        leaked = sorted(
            path for key, path in _walk_keys(case["execution"].get("input", {})) if key.lower() in FORBIDDEN_INPUT_KEYS
        )
        if leaked:
            raise ValueError(f"{case_id} leaks evaluation labels into runtime input: {leaked}")

        action = case["expected"]["action"]
        if action["punitive"] and not action["human_confirmation_required"]:
            raise ValueError(f"{case_id} permits an automated punitive action")

        if case["suite"] == "taxonomy_classifier":
            category = next((fact["value"] for fact in case["expected"]["facts"] if fact["key"] == "category"), None)
            if category:
                taxonomy.add(str(category))

    leaked_groups = sorted(group for group, splits in groups.items() if len(splits) > 1)
    if leaked_groups:
        raise ValueError(f"leakage groups cross splits: {leaked_groups}")
    for suite, expected_count in PROTOCOL_SUITES.items():
        if suite_counts[suite] != expected_count:
            raise ValueError(f"{suite} must contain {expected_count} cases, found {suite_counts[suite]}")
        if any(case["split"] != "held_out" for case in cases if case["suite"] == suite):
            raise ValueError(f"{suite} must remain held_out")
    if taxonomy != TAXONOMY:
        raise ValueError(f"taxonomy coverage must equal {sorted(TAXONOMY)}, found {sorted(taxonomy)}")
    if set(split_counts) != {"train", "tuning", "held_out"}:
        raise ValueError("train, tuning and held_out splits must all be represented")

    return {
        "corpus_version": corpus["corpus_version"],
        "case_count": len(cases),
        "suite_counts": dict(sorted(suite_counts.items())),
        "split_counts": dict(sorted(split_counts.items())),
        "sme_review_counts": dict(sorted(review_counts.items())),
    }


def analyze_results(corpus: dict[str, Any], run: dict[str, Any]) -> dict[str, Any]:
    """Map failed and missing observations to stable cases and follow-up work."""
    if run.get("corpus_version") != corpus["corpus_version"]:
        raise ValueError("result corpus_version does not match corpus")
    known = {case["case_id"]: case for case in corpus["cases"]}
    rows = run.get("results")
    if not isinstance(rows, list):
        raise ValueError("results must be a list")
    observed: dict[str, dict[str, Any]] = {}
    for row in rows:
        case_id = row.get("case_id")
        if case_id not in known:
            raise ValueError(f"unknown result case_id: {case_id}")
        if case_id in observed:
            raise ValueError(f"duplicate result case_id: {case_id}")
        if row.get("status") not in {"pass", "fail", "blocked", "not_run"}:
            raise ValueError(f"invalid status for {case_id}")
        observed[case_id] = row

    status_counts: Counter[str] = Counter()
    findings: list[dict[str, Any]] = []
    coverage_gaps: list[str] = []
    follow_ups: dict[tuple[str, str], list[str]] = defaultdict(list)
    for case_id, case in known.items():
        row = observed.get(case_id, {"case_id": case_id, "status": "not_run", "failures": ["No result supplied"]})
        status = row["status"]
        status_counts[status] += 1
        if status == "pass":
            continue
        if status == "not_run":
            coverage_gaps.append(case_id)
            continue
        failures = row.get("failures") or ["Unspecified failure"]
        finding = {
            "case_id": case_id,
            "suite": case["suite"],
            "split": case["split"],
            "status": status,
            "failures": failures,
            "owner_layer": case["follow_up"]["owner_layer"],
            "suggested_issue_title": case["follow_up"]["suggested_issue_title"],
        }
        findings.append(finding)
        key = (finding["owner_layer"], finding["suggested_issue_title"])
        follow_ups[key].append(case_id)

    return {
        "corpus_version": corpus["corpus_version"],
        "run_id": run.get("run_id", "unspecified"),
        "environment": run.get("environment", "unspecified"),
        "source_revision": run.get("source_revision", "unspecified"),
        "status_counts": dict(sorted(status_counts.items())),
        "findings": findings,
        "coverage_gaps": sorted(coverage_gaps),
        "follow_ups": [
            {"owner_layer": owner, "suggested_issue_title": title, "case_ids": sorted(case_ids)}
            for (owner, title), case_ids in sorted(follow_ups.items())
        ],
    }


def render_markdown(analysis: dict[str, Any]) -> str:
    """Render a deterministic, case-addressable error-analysis report."""
    lines = [
        "# Evaluation Corpus Error Analysis",
        "",
        f"- Corpus: `{analysis['corpus_version']}`",
        f"- Run: `{analysis['run_id']}`",
        f"- Environment: `{analysis['environment']}`",
        f"- Source revision: `{analysis['source_revision']}`",
        f"- Status counts: `{json.dumps(analysis['status_counts'], sort_keys=True)}`",
        "",
        "## Findings",
        "",
        "| Case ID | Suite | Split | Status | Failure | Owner |",
        "|---|---|---|---|---|---|",
    ]
    for finding in analysis["findings"]:
        failure = "; ".join(str(item).replace("|", "\\|") for item in finding["failures"])
        lines.append(
            f"| `{finding['case_id']}` | `{finding['suite']}` | `{finding['split']}` | "
            f"`{finding['status']}` | {failure} | `{finding['owner_layer']}` |"
        )
    if not analysis["findings"]:
        lines.append("| — | — | — | `pass` | No failures | — |")
    lines.extend(["", "## Coverage gaps", ""])
    if analysis["coverage_gaps"]:
        lines.append(
            f"`not_run` ({len(analysis['coverage_gaps'])}): "
            + ", ".join(f"`{case_id}`" for case_id in analysis["coverage_gaps"])
        )
    else:
        lines.append("None.")
    lines.extend(["", "## Actionable follow-ups", ""])
    for follow_up in analysis["follow_ups"]:
        case_ids = ", ".join(f"`{case_id}`" for case_id in follow_up["case_ids"])
        lines.append(f"- **{follow_up['suggested_issue_title']}** (`{follow_up['owner_layer']}`): {case_ids}")
    if not analysis["follow_ups"]:
        lines.append("- None.")
    lines.append("")
    return "\n".join(lines)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    parser.add_argument("--schema", type=Path, default=DEFAULT_SCHEMA)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("validate")
    analyze = subparsers.add_parser("analyze")
    analyze.add_argument("--results", type=Path, required=True)
    analyze.add_argument("--json-output", type=Path)
    analyze.add_argument("--markdown-output", type=Path)
    return parser


def main() -> None:
    args = _parser().parse_args()
    corpus = load_json(args.corpus)
    schema = load_json(args.schema)
    summary = validate_corpus(corpus, schema)
    if args.command == "validate":
        print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
        return
    analysis = analyze_results(corpus, load_json(args.results))
    markdown = render_markdown(analysis)
    if args.json_output:
        args.json_output.parent.mkdir(parents=True, exist_ok=True)
        args.json_output.write_text(json.dumps(analysis, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.markdown_output:
        args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
        args.markdown_output.write_text(markdown, encoding="utf-8")
    if not args.json_output and not args.markdown_output:
        print(markdown)


if __name__ == "__main__":
    main()

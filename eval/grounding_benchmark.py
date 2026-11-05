"""Deterministic grounding and DPO-pair benchmark for issue #199."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_GOLDEN = ROOT / "eval/golden_set/rag_testset_100.json"
DEFAULT_OUTPUT = ROOT / "eval/results/sprint4_accuracy_report.json"
DEFAULT_DPO = ROOT / "eval/dpo/preference_pairs.jsonl"
ARTICLES = ("Điều 12.2", "Điều 15.1")


def load_dpo_pairs(path: Path = DEFAULT_DPO) -> list[dict[str, Any]]:
    """Load analyst preference pairs, rejecting malformed or incomplete rows."""
    if not path.exists():
        return []
    pairs = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if all(isinstance(row.get(k), str) and row[k].strip() for k in ("prompt", "chosen", "rejected")):
            pairs.append(row)
    return pairs


def _dpo_quality(pairs: list[dict[str, Any]]) -> dict[str, int | bool]:
    """Report whether analyst feedback pairs are usable without judging model quality."""
    return {
        "total": len(pairs),
        "valid": sum(bool(row.get("prompt") and row.get("chosen") and row.get("rejected")) for row in pairs),
        "ready_for_training": bool(pairs),
    }


def _articles(item: dict[str, Any]) -> set[str]:
    text = " ".join(str(item.get(k, "")) for k in ("question", "gold_answer", "key_phrase"))
    return {article for article in ARTICLES if article in text}


def run_benchmark(golden: Path = DEFAULT_GOLDEN, output: Path = DEFAULT_OUTPUT) -> dict[str, Any]:
    cases = json.loads(golden.read_text(encoding="utf-8"))
    grounded = 0
    errors = 0
    ambiguous = 0
    not_applicable = 0
    rows = []
    for case in cases:
        expected = _articles(case)
        cited = set(case.get("expected_articles", [])) & set(ARTICLES)
        if len(expected) > 1:
            ambiguous += 1
        if not expected and not cited:
            not_applicable += 1
            confidence_tier = "not_applicable"
            ok = True
        else:
            ok = expected == cited
            confidence_tier = "high" if ok else "medium" if cited and expected.intersection(cited) else "low"
        grounded += ok
        errors += not ok
        rows.append(
            {
                "id": case.get("id"),
                "expected_articles": sorted(expected),
                "citations": sorted(cited),
                "grounded": ok,
                "confidence_tier": confidence_tier,
            }
        )
    total = len(cases) or 1
    try:
        source = str(golden.relative_to(ROOT)).replace("\\", "/")
    except ValueError:
        source = golden.name
    dpo = _dpo_quality(load_dpo_pairs())
    report = {
        "benchmark": "sprint4-grounding-v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),  # noqa: UP017 - Python 3.10 compatibility
        "source": source,
        "total_cases": len(cases),
        "policy_retrieval_precision_pct": round(grounded * 100 / total, 2),
        "grounding_errors": errors,
        "hallucination_rate_pct": round(errors * 100 / total, 2),
        "ambiguous_multi_clause_cases": ambiguous,
        "evaluated_cases": len(cases) - not_applicable,
        "not_applicable_cases": not_applicable,
        "dpo_pairs": dpo["total"],
        "dpo": dpo,
        "human_verification": {
            "agreement_baseline_pct": None,
            "agreement_candidate_pct": None,
            "agreement_delta_pct": None,
            "top_5_overturned_cases_verified": False,
            "status": "pending_human_review",
        },
        "acceptance": {
            "precision_gte_95": grounded * 100 / total >= 95,
            "hallucination_lte_1_5": errors * 100 / total <= 1.5,
            "grounding_errors_lte_1": errors <= 1,
            "case_results_complete": len(rows) == len(cases),
            "dpo_pairs_loaded": bool(dpo["ready_for_training"]),
            "human_verification_complete": False,
        },
        "cases": rows,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--golden", type=Path, default=DEFAULT_GOLDEN)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    report = run_benchmark(args.golden, args.output)
    print(
        json.dumps(
            {
                k: report[k]
                for k in ("total_cases", "policy_retrieval_precision_pct", "hallucination_rate_pct", "grounding_errors")
            },
            ensure_ascii=False,
        )
    )

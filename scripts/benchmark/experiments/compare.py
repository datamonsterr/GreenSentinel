"""Comparator and registry updater for benchmark experiments (Issue #497 / Epic #494).

Evaluates keep-or-revert decision rule:
- Primary metric (macro-F1) improves by more than paired-bootstrap CI half-width
- All guards hold:
  - FPR <= best + 0.005
  - recall@budget >= best - 0.01
  - no class PR-AUC drop > 0.03
  - ECE <= best + 0.02
Appends the result to docs/data/experiments/registry.jsonl.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.benchmark.experiments.metrics import paired_bootstrap_difference  # noqa: E402


def validate_paired_comparison(
    candidate: dict[str, Any],
    best: dict[str, Any] | None,
    cand_preds: dict[str, Any] | list[dict[str, Any]] | None = None,
    best_preds: dict[str, Any] | list[dict[str, Any]] | None = None,
    max_live_failure_rate: float = 0.02,
) -> None:
    """Validate that candidate and best runs are strictly comparable."""
    # 0. Validity and live failure rate checks
    if candidate.get("valid") is False:
        raise ValueError("Candidate metrics has valid=false; refusing comparison.")
    if best is not None and best.get("valid") is False:
        raise ValueError("Best metrics has valid=false; refusing comparison.")

    cand_lfr = float(candidate.get("live_failure_rate") or 0.0)
    if cand_lfr > max_live_failure_rate:
        raise ValueError(
            f"Candidate live_failure_rate {cand_lfr} exceeds limit {max_live_failure_rate}; refusing comparison."
        )
    if best is not None:
        best_lfr = float(best.get("live_failure_rate") or 0.0)
        if best_lfr > max_live_failure_rate:
            raise ValueError(
                f"Best live_failure_rate {best_lfr} exceeds limit {max_live_failure_rate}; refusing comparison."
            )

    if best is None:
        return

    # 1. Corpus trips sha256 check
    cand_sha = candidate.get("corpus_trips_sha256")
    best_sha = best.get("corpus_trips_sha256")
    if cand_sha and best_sha and cand_sha != best_sha:
        raise ValueError(
            f"Mismatched corpus_trips_sha256: candidate={cand_sha} vs best={best_sha}. "
            "Paired comparison requires identical corpus trips."
        )

    # 2. Enum-blind flag check
    if "enum_blind" in candidate and "enum_blind" in best:
        cand_blind = bool(candidate.get("enum_blind", False))
        best_blind = bool(best.get("enum_blind", False))
        if cand_blind != best_blind:
            raise ValueError(
                f"Mismatched enum_blind flag: candidate={cand_blind} vs best={best_blind}. "
                "Paired comparison requires matching enum_blind setting."
            )

    # 3. Dataset split check
    if "split" in candidate and "split" in best:
        cand_split = str(candidate.get("split") or "")
        best_split = str(best.get("split") or "")
        if cand_split and best_split and cand_split != best_split:
            raise ValueError(
                f"Mismatched split: candidate='{cand_split}' vs best='{best_split}'. "
                "Paired comparison requires matching dataset split."
            )

    # 4. Sample size check
    if "sample" in candidate and "sample" in best:
        cand_sample = candidate.get("sample")
        best_sample = best.get("sample")
        if cand_sample is not None and best_sample is not None and cand_sample != best_sample:
            raise ValueError(
                f"Mismatched sample size: candidate={cand_sample} vs best={best_sample}. "
                "Paired comparison requires identical sample sizes."
            )

    # 5. Trip_ref sets check
    if cand_preds is not None and best_preds is not None:
        cand_refs = set(cand_preds.keys()) if isinstance(cand_preds, dict) else {r["trip_ref"] for r in cand_preds}
        best_refs = set(best_preds.keys()) if isinstance(best_preds, dict) else {r["trip_ref"] for r in best_preds}
        if cand_refs != best_refs:
            diff = cand_refs ^ best_refs
            raise ValueError(
                f"Mismatched trip_ref sets: candidate has {len(cand_refs)}, best has {len(best_refs)} "
                f"({len(diff)} trips differ). Paired comparison requires identical trips."
            )


def evaluate_decision(
    candidate: dict[str, Any],
    best: dict[str, Any] | None,
    paired_ci_half_width: float | None = None,
    max_live_failure_rate: float = 0.02,
) -> tuple[str, dict[str, Any], float]:
    """Evaluate candidate against best using Epic #494 rules.

    Returns:
        (decision ['keep'|'revert'], guards_dict, best_so_far)
    """
    validate_paired_comparison(candidate=candidate, best=best, max_live_failure_rate=max_live_failure_rate)

    cand_primary = float(candidate.get("macro_f1") or 0.0)

    if best is None:
        # Initial baseline attempt
        guards = {
            "fpr_ok": True,
            "recall_at_budget_ok": True,
            "pr_auc_ok": True,
            "ece_ok": True,
            "all_passed": True,
        }
        return "keep", guards, cand_primary

    if paired_ci_half_width is None:
        raise ValueError(
            "Paired comparison requires paired_ci_half_width computed on identical trips; unpaired fallback prohibited."
        )

    best_primary = float(best.get("macro_f1") or 0.0)
    diff = cand_primary - best_primary

    # 1. FPR guard: not above baseline + 0.005
    cand_fpr = float(candidate.get("no_violation_fpr") or 0.0)
    best_fpr = float(best.get("no_violation_fpr") or 0.0)
    fpr_ok = cand_fpr <= best_fpr + 0.005

    # 2. Recall at alert budget: not below baseline - 0.01
    cand_rec = float(candidate.get("adverse_recall_at_budget") or 0.0)
    best_rec = float(best.get("adverse_recall_at_budget") or 0.0)
    rec_ok = cand_rec >= best_rec - 0.01

    # 3. Per-class PR-AUC: no class drop > 0.03
    cand_pr_auc = candidate.get("per_class_pr_auc") or {}
    best_pr_auc = best.get("per_class_pr_auc") or {}
    pr_auc_ok = True
    pr_auc_drops: dict[str, float] = {}
    for cls, best_score in best_pr_auc.items():
        cand_score = float(cand_pr_auc.get(cls) or 0.0)
        drop = float(best_score) - cand_score
        pr_auc_drops[cls] = round(drop, 4)
        if drop > 0.03:
            pr_auc_ok = False

    # 4. ECE guard: not above baseline + 0.02
    cand_ece = float(
        candidate.get("calibration", {}).get("ece_10bin")
        if isinstance(candidate.get("calibration"), dict)
        else candidate.get("ece_10bin", 0.0)
    )
    best_ece = float(
        best.get("calibration", {}).get("ece_10bin")
        if isinstance(best.get("calibration"), dict)
        else best.get("ece_10bin", 0.0)
    )
    ece_ok = cand_ece <= best_ece + 0.02

    all_guards_passed = fpr_ok and rec_ok and pr_auc_ok and ece_ok

    guards = {
        "fpr_ok": fpr_ok,
        "cand_fpr": round(cand_fpr, 4),
        "best_fpr": round(best_fpr, 4),
        "recall_at_budget_ok": rec_ok,
        "cand_recall_at_budget": round(cand_rec, 4),
        "best_recall_at_budget": round(best_rec, 4),
        "pr_auc_ok": pr_auc_ok,
        "pr_auc_drops": pr_auc_drops,
        "ece_ok": ece_ok,
        "cand_ece": round(cand_ece, 4),
        "best_ece": round(best_ece, 4),
        "all_passed": all_guards_passed,
    }

    # Primary rule: improves by more than paired CI half-width
    primary_gain_ok = diff > paired_ci_half_width

    if primary_gain_ok and all_guards_passed:
        decision = "keep"
        best_so_far = cand_primary
    else:
        decision = "revert"
        best_so_far = best_primary

    return decision, guards, best_so_far


def record_attempt_file(
    attempts_dir: Path,
    exp_id: str,
    variant: str,
    candidate_metrics: dict[str, Any],
    best_metrics: dict[str, Any] | None = None,
    issue: str = "#494",
    pr: str = "",
    paired_ci_half_width: float | None = None,
    attempt: int | None = None,
    max_live_failure_rate: float = 0.02,
) -> dict[str, Any]:
    """Evaluate decision and save single attempt to attempts/<exp_id>.json."""
    attempts_dir.mkdir(parents=True, exist_ok=True)
    out_file = attempts_dir / f"{exp_id}.json"

    if out_file.exists() and attempt is None:
        try:
            prev = json.loads(out_file.read_text(encoding="utf-8"))
            if prev.get("attempt") is not None:
                attempt = prev["attempt"]
        except Exception:
            pass

    decision, guards, best_so_far = evaluate_decision(
        candidate=candidate_metrics,
        best=best_metrics,
        paired_ci_half_width=paired_ci_half_width,
        max_live_failure_rate=max_live_failure_rate,
    )

    primary_val = float(candidate_metrics.get("macro_f1") or 0.0)
    ci_val = candidate_metrics.get("ci") or [
        primary_val - float(candidate_metrics.get("ci_half_width") or 0.0),
        primary_val + float(candidate_metrics.get("ci_half_width") or 0.0),
    ]

    record = {
        "attempt": attempt,
        "exp_id": exp_id,
        "variant": variant,
        "issue": issue,
        "pr": pr,
        "primary": round(primary_val, 4),
        "ci": [round(ci_val[0], 4), round(ci_val[1], 4)],
        "guards": guards,
        "decision": decision,
        "best_so_far": round(best_so_far, 4),
        "date": datetime.now(UTC).strftime("%Y-%m-%d"),
        "corpus_trips_sha256": candidate_metrics.get("corpus_trips_sha256"),
        "split": candidate_metrics.get("split"),
        "sample": candidate_metrics.get("sample"),
        "enum_blind": candidate_metrics.get("enum_blind"),
        "git_sha": candidate_metrics.get("git_sha"),
    }

    out_file.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    return record


def assign_attempts(attempts_dir: Path, target_exp_id: str | None = None) -> list[dict[str, Any]]:
    """Assign attempt numbers to attempt files in attempts_dir."""
    if not attempts_dir.exists():
        return []

    files = sorted(attempts_dir.glob("*.json"))
    records: list[tuple[Path, dict[str, Any]]] = []
    for f in files:
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            records.append((f, data))
        except Exception:
            continue

    assigned_nums = [r["attempt"] for _, r in records if r.get("attempt") is not None]
    next_attempt = max(assigned_nums) + 1 if assigned_nums else 0

    assigned_records: list[dict[str, Any]] = []

    for path, rec in records:
        exp_id = rec.get("exp_id")
        if target_exp_id is not None and target_exp_id != "all":
            if exp_id == target_exp_id and rec.get("attempt") is None:
                rec["attempt"] = next_attempt
                next_attempt += 1
                path.write_text(json.dumps(rec, indent=2) + "\n", encoding="utf-8")
        else:
            if rec.get("attempt") is None:
                rec["attempt"] = next_attempt
                next_attempt += 1
                path.write_text(json.dumps(rec, indent=2) + "\n", encoding="utf-8")
        assigned_records.append(rec)

    return sorted(assigned_records, key=lambda x: (x.get("attempt") is None, x.get("attempt") or 0))


def build_registry_from_attempts(attempts_dir: Path, registry_path: Path) -> list[dict[str, Any]]:
    """Build registry.jsonl from all assigned attempt files in attempts_dir."""
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    if not attempts_dir.exists():
        registry_path.write_text("", encoding="utf-8")
        return []

    files = sorted(attempts_dir.glob("*.json"))
    rows: list[dict[str, Any]] = []
    for f in files:
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            if data.get("attempt") is not None:
                rows.append(data)
        except Exception:
            continue

    rows.sort(key=lambda r: int(r["attempt"]))

    with registry_path.open("w", encoding="utf-8") as f:
        for r in rows:
            line_obj = {
                "attempt": r["attempt"],
                "exp_id": r["exp_id"],
                "variant": r["variant"],
                "issue": r.get("issue", ""),
                "pr": r.get("pr", ""),
                "primary": r["primary"],
                "ci": r["ci"],
                "guards": r["guards"],
                "decision": r["decision"],
                "best_so_far": r["best_so_far"],
                "date": r["date"],
            }
            f.write(json.dumps(line_obj) + "\n")

    return rows


def record_experiment_attempt(
    registry_path: Path,
    candidate_metrics: dict[str, Any],
    best_metrics: dict[str, Any] | None,
    exp_id: str,
    variant: str,
    issue: str = "#494",
    pr: str = "",
    paired_ci_half_width: float | None = None,
    attempts_dir: Path | None = None,
    max_live_failure_rate: float = 0.02,
) -> dict[str, Any]:
    """Evaluate decision, build schema row, write attempt file and append to registry.jsonl."""
    existing_rows: list[dict[str, Any]] = []
    if registry_path.exists():
        with registry_path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    existing_rows.append(json.loads(line))

    attempt = len(existing_rows)

    decision, guards, best_so_far = evaluate_decision(
        candidate=candidate_metrics,
        best=best_metrics,
        paired_ci_half_width=paired_ci_half_width,
        max_live_failure_rate=max_live_failure_rate,
    )

    primary_val = float(candidate_metrics.get("macro_f1") or 0.0)
    ci_val = candidate_metrics.get("ci") or [
        primary_val - float(candidate_metrics.get("ci_half_width") or 0.0),
        primary_val + float(candidate_metrics.get("ci_half_width") or 0.0),
    ]

    row = {
        "attempt": attempt,
        "exp_id": exp_id,
        "variant": variant,
        "issue": issue,
        "pr": pr,
        "primary": round(primary_val, 4),
        "ci": [round(ci_val[0], 4), round(ci_val[1], 4)],
        "guards": guards,
        "decision": decision,
        "best_so_far": round(best_so_far, 4),
        "date": datetime.now(UTC).strftime("%Y-%m-%d"),
    }

    if attempts_dir is None:
        attempts_dir = registry_path.parent / "attempts"
    record_attempt_file(
        attempts_dir=attempts_dir,
        exp_id=exp_id,
        variant=variant,
        candidate_metrics=candidate_metrics,
        best_metrics=best_metrics,
        issue=issue,
        pr=pr,
        paired_ci_half_width=paired_ci_half_width,
        attempt=attempt,
        max_live_failure_rate=max_live_failure_rate,
    )

    registry_path.parent.mkdir(parents=True, exist_ok=True)
    with registry_path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row) + "\n")

    return row


def compute_paired_ci_from_predictions(
    cand_pred_path: Path,
    best_pred_path: Path,
) -> float:
    """Compute paired bootstrap half-width from two predictions.jsonl files."""
    cand_preds: dict[str, str] = {}
    y_true: dict[str, str] = {}
    with cand_pred_path.open("r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                item = json.loads(line)
                ref = item["trip_ref"]
                cand_preds[ref] = item["predicted_category"]
                y_true[ref] = item["label"]

    best_preds: dict[str, str] = {}
    with best_pred_path.open("r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                item = json.loads(line)
                best_preds[item["trip_ref"]] = item["predicted_category"]

    cand_refs = set(cand_preds.keys())
    best_refs = set(best_preds.keys())
    if cand_refs != best_refs:
        diff = cand_refs ^ best_refs
        raise ValueError(
            f"Mismatched trip_ref sets: candidate has {len(cand_refs)}, best has {len(best_refs)} "
            f"({len(diff)} trips differ). Paired comparison requires identical trips."
        )

    common_refs = sorted(cand_refs)
    if not common_refs:
        return 0.0

    aligned_yt = [y_true[r] for r in common_refs]
    aligned_cand = [cand_preds[r] for r in common_refs]
    aligned_best = [best_preds[r] for r in common_refs]

    res = paired_bootstrap_difference(aligned_yt, aligned_cand, aligned_best, n_bootstraps=500)
    return float(res["ci_half_width"])


def main():
    parser = argparse.ArgumentParser(description="GreenSentinel Experiment Comparator")
    parser.add_argument("--candidate", type=Path, default=None, help="Candidate metrics.json")
    parser.add_argument("--best", type=Path, default=None, help="Best-so-far metrics.json")
    parser.add_argument(
        "--attempts-dir",
        type=Path,
        default=Path("docs/data/experiments/attempts"),
        help="Path to attempts directory",
    )
    parser.add_argument(
        "--registry",
        type=Path,
        default=Path("docs/data/experiments/registry.jsonl"),
        help="Path to registry.jsonl",
    )
    parser.add_argument(
        "--assign-attempt",
        nargs="?",
        const="all",
        default=None,
        help="Assign attempt number at merge time (optional: specific exp_id)",
    )
    parser.add_argument(
        "--build-registry",
        action="store_true",
        help="Rebuild registry.jsonl from attempts folder",
    )
    parser.add_argument("--issue", default="#494", help="Issue reference")
    parser.add_argument("--pr", default="", help="PR reference")
    parser.add_argument(
        "--max-live-failure-rate",
        type=float,
        default=0.02,
        help="Maximum allowed live failure rate (default: 0.02)",
    )

    args = parser.parse_args()

    if args.assign_attempt is not None:
        target = None if args.assign_attempt == "all" else args.assign_attempt
        assign_attempts(args.attempts_dir, target_exp_id=target)
        rows = build_registry_from_attempts(args.attempts_dir, args.registry)
        print(f"Assigned attempts and rebuilt registry: {len(rows)} entries in {args.registry}")
        return

    if args.build_registry:
        rows = build_registry_from_attempts(args.attempts_dir, args.registry)
        print(f"Rebuilt registry from attempts: {len(rows)} entries in {args.registry}")
        return

    if args.candidate is None:
        parser.error("--candidate is required unless --assign-attempt or --build-registry is used")

    with args.candidate.open("r", encoding="utf-8") as f:
        cand_metrics = json.load(f)

    best_metrics = None
    if args.best and args.best.exists():
        with args.best.open("r", encoding="utf-8") as f:
            best_metrics = json.load(f)

    paired_ci_half_width = None
    if args.best:
        cand_preds_file = args.candidate.parent / "predictions.jsonl"
        best_preds_file = args.best.parent / "predictions.jsonl"
        if cand_preds_file.exists() and best_preds_file.exists():
            paired_ci_half_width = compute_paired_ci_from_predictions(cand_preds_file, best_preds_file)

    try:
        row = record_attempt_file(
            attempts_dir=args.attempts_dir,
            exp_id=cand_metrics.get("exp_id", "unknown"),
            variant=cand_metrics.get("variant", "unknown"),
            candidate_metrics=cand_metrics,
            best_metrics=best_metrics,
            issue=args.issue,
            pr=args.pr,
            paired_ci_half_width=paired_ci_half_width,
            max_live_failure_rate=args.max_live_failure_rate,
        )
    except ValueError as exc:
        sys.exit(f"Comparison refused: {exc}")

    print(
        f"Recorded attempt {row.get('attempt', 'unassigned')} ({row['exp_id']}): Decision = {row['decision'].upper()} "
        f"(Primary: {row['primary']}, Best so far: {row['best_so_far']}) in {args.attempts_dir}"
    )


if __name__ == "__main__":
    main()

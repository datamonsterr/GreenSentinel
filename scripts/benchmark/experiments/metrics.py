"""Pure evaluation metrics for the GreenSentinel trip-fraud classifier benchmark suite.

Covers all metrics from Epic #494 / Issue #497:
- Primary: Macro-F1 over 7 classes with 95% bootstrap CI
- Paired bootstrap of the difference between two prediction sets
- No-violation false-alarm rate (FPR)
- Adverse recall at alert budget
- Per-class PR-AUC (one-vs-rest)
- ECE 10-bin and Brier score on top-class confidence
- AURC (Area Under Risk-Coverage curve)
- Strict minus enum-blind gap
- Cost: mean input tokens, p95 latency, live calls
- Prevalence-reweighted metrics with optional per-row prevalence_weight
"""

from __future__ import annotations

import json
from collections import defaultdict
from typing import Any

import numpy as np

CLASSES: list[str] = [
    "no_violation",
    "ERR-01",
    "ERR-02",
    "ERR-03",
    "ERR-04",
    "ERR-05",
    "insufficient_evidence",
]

ADVERSE_CLASSES: frozenset[str] = frozenset({"ERR-01", "ERR-02", "ERR-03", "ERR-04", "ERR-05"})


def compute_per_class_f1(
    y_true: list[str],
    y_pred: list[str],
    weights: list[float] | None = None,
) -> dict[str, dict[str, float]]:
    """Compute per-class TP, FP, FN, precision, recall, and F1 across CLASSES."""
    if len(y_true) != len(y_pred):
        raise ValueError(f"Length mismatch: {len(y_true)} vs {len(y_pred)}")
    if weights is not None and len(weights) != len(y_true):
        raise ValueError(f"Weights length mismatch: {len(weights)} vs {len(y_true)}")

    out: dict[str, dict[str, float]] = {}
    for cls in CLASSES:
        tp = 0.0
        fp = 0.0
        fn = 0.0
        for i in range(len(y_true)):
            w = 1.0 if weights is None else float(weights[i])
            yt = y_true[i]
            yp = y_pred[i]
            if yt == cls and yp == cls:
                tp += w
            elif yt != cls and yp == cls:
                fp += w
            elif yt == cls and yp != cls:
                fn += w

        prec = tp / (tp + fp) if (tp + fp) > 0.0 else 0.0
        rec = tp / (tp + fn) if (tp + fn) > 0.0 else 0.0
        f1 = (2.0 * prec * rec) / (prec + rec) if (prec + rec) > 0.0 else 0.0
        out[cls] = {
            "tp": round(tp, 4),
            "fp": round(fp, 4),
            "fn": round(fn, 4),
            "precision": round(prec, 6),
            "recall": round(rec, 6),
            "f1": round(f1, 6),
        }
    return out


def compute_macro_f1(
    y_true: list[str],
    y_pred: list[str],
    weights: list[float] | None = None,
) -> float:
    """Unweighted average of F1 over the 7 classes."""
    per_class = compute_per_class_f1(y_true, y_pred, weights=weights)
    return float(np.mean([v["f1"] for v in per_class.values()]))


def bootstrap_macro_f1_ci(
    y_true: list[str],
    y_pred: list[str],
    n_bootstraps: int = 1000,
    ci: float = 0.95,
    seed: int | None = 42,
    weights: list[float] | None = None,
) -> dict[str, float]:
    """Bootstrap confidence interval for macro-F1."""
    point = compute_macro_f1(y_true, y_pred, weights=weights)
    n = len(y_true)
    if n == 0:
        return {"point": 0.0, "ci_lower": 0.0, "ci_upper": 0.0, "ci_half_width": 0.0}

    rng = np.random.default_rng(seed)
    y_true_arr = np.array(y_true)
    y_pred_arr = np.array(y_pred)
    weights_arr = np.array(weights) if weights is not None else None

    boot_f1s = []
    for _ in range(n_bootstraps):
        indices = rng.integers(0, n, size=n)
        sample_yt = y_true_arr[indices].tolist()
        sample_yp = y_pred_arr[indices].tolist()
        sample_w = weights_arr[indices].tolist() if weights_arr is not None else None
        boot_f1s.append(compute_macro_f1(sample_yt, sample_yp, weights=sample_w))

    alpha = (1.0 - ci) / 2.0
    lower = round(float(np.percentile(boot_f1s, alpha * 100.0)), 6)
    upper = round(float(np.percentile(boot_f1s, (1.0 - alpha) * 100.0)), 6)
    half_width = round(float((upper - lower) / 2.0), 6)

    return {
        "point": round(point, 6),
        "ci_lower": lower,
        "ci_upper": upper,
        "ci_half_width": half_width,
    }


def paired_bootstrap_difference(
    y_true: list[str],
    y_pred_candidate: list[str],
    y_pred_best: list[str],
    n_bootstraps: int = 1000,
    ci: float = 0.95,
    seed: int | None = 42,
    weights: list[float] | None = None,
) -> dict[str, float]:
    """Paired bootstrap of the difference (candidate - best) on the same trips."""
    n = len(y_true)
    if n != len(y_pred_candidate) or n != len(y_pred_best):
        raise ValueError("Candidate and best prediction sets must align with y_true")
    if n == 0:
        return {"diff": 0.0, "ci_lower": 0.0, "ci_upper": 0.0, "ci_half_width": 0.0}

    cand_point = compute_macro_f1(y_true, y_pred_candidate, weights=weights)
    best_point = compute_macro_f1(y_true, y_pred_best, weights=weights)
    diff = cand_point - best_point

    rng = np.random.default_rng(seed)
    y_true_arr = np.array(y_true)
    cand_arr = np.array(y_pred_candidate)
    best_arr = np.array(y_pred_best)
    weights_arr = np.array(weights) if weights is not None else None

    diffs = []
    for _ in range(n_bootstraps):
        indices = rng.integers(0, n, size=n)
        sample_yt = y_true_arr[indices].tolist()
        sample_cand = cand_arr[indices].tolist()
        sample_best = best_arr[indices].tolist()
        sample_w = weights_arr[indices].tolist() if weights_arr is not None else None

        f1_cand = compute_macro_f1(sample_yt, sample_cand, weights=sample_w)
        f1_best = compute_macro_f1(sample_yt, sample_best, weights=sample_w)
        diffs.append(f1_cand - f1_best)

    alpha = (1.0 - ci) / 2.0
    lower = round(float(np.percentile(diffs, alpha * 100.0)), 6)
    upper = round(float(np.percentile(diffs, (1.0 - alpha) * 100.0)), 6)
    half_width = round(float((upper - lower) / 2.0), 6)

    return {
        "diff": round(diff, 6),
        "ci_lower": lower,
        "ci_upper": upper,
        "ci_half_width": half_width,
    }


def no_violation_false_alarm_rate(
    y_true: list[str],
    y_pred: list[str],
    weights: list[float] | None = None,
) -> float:
    """Share of true no_violation trips predicted as any ERR-0x."""
    if len(y_true) != len(y_pred):
        raise ValueError("Length mismatch between y_true and y_pred")

    num = 0.0
    denom = 0.0
    for i in range(len(y_true)):
        w = 1.0 if weights is None else float(weights[i])
        yt = y_true[i]
        yp = y_pred[i]
        if yt == "no_violation":
            denom += w
            if yp in ADVERSE_CLASSES:
                num += w

    if denom <= 0.0:
        return 0.0
    return float(num / denom)


def adverse_recall_at_alert_budget(
    records: list[dict[str, Any]],
    alert_budget_pct: float = 5.0,
    weights: list[float] | None = None,
) -> float:
    """Rank trips by risk score, take top k%, compute recall of true adverse classes.

    Risk score calculation:
    - 1 - P(no_violation) if probabilities present
    - confidence of predicted category if adverse
    - 1 - confidence if predicted no_violation
    - 0.0 otherwise.
    """
    n = len(records)
    if n == 0:
        return 0.0

    scored: list[tuple[float, int, dict[str, Any], float]] = []
    for i, r in enumerate(records):
        w = 1.0 if weights is None else float(weights[i])
        probs = r.get("probabilities")
        cat = r.get("predicted_category")
        conf = float(r.get("confidence") or 0.0)

        if isinstance(probs, dict) and "no_violation" in probs:
            risk = 1.0 - float(probs["no_violation"])
        elif cat in ADVERSE_CLASSES:
            risk = conf
        elif cat == "no_violation":
            risk = 1.0 - conf
        else:
            risk = 0.0

        scored.append((risk, i, r, w))

    # Stable sort by risk descending, then original index ascending
    scored.sort(key=lambda item: (-item[0], item[1]))

    total_adverse_weight = sum(w for _, _, r, w in scored if r.get("label") in ADVERSE_CLASSES)
    if total_adverse_weight <= 0.0:
        return 0.0

    top_count = max(1, int(round(n * (alert_budget_pct / 100.0))))
    top_adverse_weight = sum(w for _, _, r, w in scored[:top_count] if r.get("label") in ADVERSE_CLASSES)

    return float(top_adverse_weight / total_adverse_weight)


def compute_per_class_pr_auc(
    records: list[dict[str, Any]],
    weights: list[float] | None = None,
) -> dict[str, float]:
    """Compute one-vs-rest PR-AUC for each class using available probabilities."""
    n = len(records)
    if n == 0:
        return {cls: 0.0 for cls in CLASSES}

    out: dict[str, float] = {}
    for cls in CLASSES:
        items: list[tuple[float, int, float]] = []
        for i, r in enumerate(records):
            w = 1.0 if weights is None else float(weights[i])
            is_pos = 1 if r.get("label") == cls else 0
            probs = r.get("probabilities")
            if isinstance(probs, dict) and cls in probs:
                score = float(probs[cls])
            elif r.get("predicted_category") == cls:
                score = float(r.get("confidence") or 0.0)
            else:
                score = 0.0
            items.append((score, is_pos, w))

        total_pos_weight = sum(w for _, is_pos, w in items if is_pos == 1)
        if total_pos_weight <= 0.0:
            out[cls] = 0.0
            continue

        # Sort descending by score
        items.sort(key=lambda x: -x[0])

        # Group by unique score thresholds
        tp = 0.0
        fp = 0.0
        prev_recall = 0.0
        ap = 0.0

        threshold_groups: dict[float, list[tuple[int, float]]] = defaultdict(list)
        for score, is_pos, w in items:
            threshold_groups[score].append((is_pos, w))

        # Ordered distinct thresholds
        sorted_thresholds = sorted(threshold_groups.keys(), reverse=True)
        for t in sorted_thresholds:
            for is_pos, w in threshold_groups[t]:
                if is_pos == 1:
                    tp += w
                else:
                    fp += w
            curr_recall = tp / total_pos_weight
            curr_prec = tp / (tp + fp) if (tp + fp) > 0.0 else 0.0
            delta_recall = curr_recall - prev_recall
            ap += delta_recall * curr_prec
            prev_recall = curr_recall

        out[cls] = round(float(ap), 6)

    return out


def compute_calibration(
    y_true: list[str],
    y_pred: list[str],
    confidences: list[float],
    n_bins: int = 10,
    weights: list[float] | None = None,
) -> dict[str, Any]:
    """10-bin Expected Calibration Error (ECE) and Brier score."""
    n = len(y_true)
    if n == 0:
        return {"ece_10bin": 0.0, "brier": 0.0, "bins": []}

    bins = [{"n": 0.0, "acc": 0.0, "conf": 0.0} for _ in range(n_bins)]
    brier_sum = 0.0
    total_w = 0.0

    for i in range(n):
        w = 1.0 if weights is None else float(weights[i])
        correct = 1.0 if y_true[i] == y_pred[i] else 0.0
        conf = float(confidences[i])
        brier_sum += w * ((conf - correct) ** 2)
        total_w += w

        idx = min(int(conf * n_bins), n_bins - 1)
        bins[idx]["n"] += w
        bins[idx]["acc"] += w * correct
        bins[idx]["conf"] += w * conf

    ece = 0.0
    bin_rows = []
    for i, b in enumerate(bins):
        if b["n"] > 0:
            acc = b["acc"] / b["n"]
            conf = b["conf"] / b["n"]
            ece += abs(acc - conf) * (b["n"] / total_w)
            bin_rows.append(
                {
                    "bin": f"[{i / n_bins:.1f},{(i + 1) / n_bins:.1f})",
                    "n": round(b["n"], 2),
                    "acc": round(acc, 4),
                    "conf": round(conf, 4),
                }
            )

    brier = brier_sum / total_w if total_w > 0.0 else 0.0
    return {
        "ece_10bin": round(float(ece), 6),
        "brier": round(float(brier), 6),
        "bins": bin_rows,
    }


def compute_aurc(
    y_true: list[str],
    y_pred: list[str],
    confidences: list[float],
    weights: list[float] | None = None,
) -> float:
    """Area Under Risk-Coverage curve for selective prediction by confidence.

    Samples are ranked by confidence descending. At coverage m/N, risk is the
    weighted error rate of the top m samples. AURC is the mean risk across coverages.
    """
    n = len(y_true)
    if n == 0:
        return 0.0

    indexed: list[tuple[float, int, int, float]] = []
    for i in range(n):
        w = 1.0 if weights is None else float(weights[i])
        error = 1 if y_true[i] != y_pred[i] else 0
        conf = float(confidences[i])
        indexed.append((conf, i, error, w))

    # Sort descending by confidence
    indexed.sort(key=lambda x: -x[0])

    cum_error_weight = 0.0
    cum_total_weight = 0.0
    risk_sum = 0.0

    for _, _, err, w in indexed:
        cum_total_weight += w
        if err == 1:
            cum_error_weight += w
        risk = cum_error_weight / cum_total_weight if cum_total_weight > 0.0 else 0.0
        risk_sum += risk

    return float(risk_sum / n)


def compute_strict_enum_blind_gap(strict_macro_f1: float, enum_blind_macro_f1: float) -> float:
    """Difference between strict and enum-blind macro-F1 (measures enum leakage)."""
    return round(float(strict_macro_f1 - enum_blind_macro_f1), 4)


def compute_cost_metrics(records: list[dict[str, Any]], live_calls: int = 0) -> dict[str, Any]:
    """Cost: mean input tokens per trip (len(json)/3 fallback), latency percentiles, live calls."""
    n = len(records)
    if n == 0:
        return {
            "mean_input_tokens": 0.0,
            "mean_latency_ms": 0.0,
            "p50_latency_ms": 0.0,
            "p95_latency_ms": 0.0,
            "live_calls": live_calls,
        }

    token_counts: list[float] = []
    latencies: list[float] = []

    for r in records:
        tokens = r.get("input_tokens")
        if tokens is not None and tokens > 0:
            token_counts.append(float(tokens))
        else:
            bundle_rep = r.get("bundle") or {k: v for k, v in r.items() if k != "bundle"}
            try:
                dumped = json.dumps(bundle_rep)
                token_counts.append(len(dumped) / 3.0)
            except Exception:
                token_counts.append(0.0)

        lat = float(r.get("latency_ms") or 0.0)
        latencies.append(lat)

    lat_sorted = sorted(latencies)

    def _pct(p: float) -> float:
        if not lat_sorted:
            return 0.0
        idx = min(int(round(p / 100.0 * (len(lat_sorted) - 1))), len(lat_sorted) - 1)
        return lat_sorted[idx]

    return {
        "mean_input_tokens": round(float(np.mean(token_counts)), 2) if token_counts else 0.0,
        "mean_latency_ms": round(float(np.mean(latencies)), 3) if latencies else 0.0,
        "p50_latency_ms": round(float(_pct(50.0)), 3),
        "p95_latency_ms": round(float(_pct(95.0)), 3),
        "live_calls": live_calls,
    }


def normalize_model_used(value: Any) -> str:
    """Return valid model attribution; malformed values remain untracked."""
    return value.strip() if isinstance(value, str) else ""


def classify_live_failure_cause(r: dict[str, Any]) -> str:
    """Classify the failure cause for a live fallback prediction."""
    reason = r.get("fallback_reason")
    if reason in ("max_tokens_exceeded", "insufficient_credits", "rate_limit", "timeout", "untracked_variant_failure"):
        return reason
    status = r.get("http_status")
    if status == 400:
        return "max_tokens_exceeded"
    if status == 402:
        return "insufficient_credits"
    if status == 429:
        return "rate_limit"
    if reason == "timeout":
        return "timeout"
    model = normalize_model_used(r.get("model_used")).lower()
    if not model or model in ("none", "unknown"):
        return "untracked_variant_failure"
    return "other"


def compute_live_failure_metrics(
    records: list[dict[str, Any]],
    live_calls: int = 0,
    live: bool = False,
) -> dict[str, Any]:
    """Derive live calls and failures from records; caller counts cannot dilute failures."""
    default_causes = {
        "max_tokens_exceeded": 0,
        "insufficient_credits": 0,
        "rate_limit": 0,
        "timeout": 0,
        "other": 0,
    }
    if not live:
        return {
            "live_calls": live_calls,
            "live_failures": 0,
            "live_failure_rate": 0.0,
            "live_failures_by_cause": default_causes,
        }

    failures = 0
    causes = dict(default_causes)

    inferred_live_calls = 0
    for r in records:
        model = normalize_model_used(r.get("model_used"))
        # Soft guardrails may cap a provider response or fallback after a live call.
        is_guardrail = model == "guardrail_short_circuit"
        if not is_guardrail:
            inferred_live_calls += 1

        is_heuristic = (
            model == "jev_calibrated_heuristic" or "heuristic" in model.lower() or r.get("fallback_reason") is not None
        )
        is_untracked = not model or model.lower() in ("none", "unknown")

        if (is_heuristic or is_untracked) and not is_guardrail:
            failures += 1
            cause = classify_live_failure_cause(r)
            causes[cause] = causes.get(cause, 0) + 1

    actual_live_calls = inferred_live_calls
    failure_rate = float(failures / actual_live_calls) if actual_live_calls > 0 else (0.0 if failures == 0 else 1.0)

    return {
        "live_calls": actual_live_calls,
        "live_failures": failures,
        "live_failure_rate": round(failure_rate, 6),
        "live_failures_by_cause": causes,
    }


def compute_provenance_metrics(
    records: list[dict[str, Any]],
    live: bool = False,
) -> dict[str, Any]:
    """Compute provenance metrics across prediction records.

    Tracks:
    - calls: total calls excluding explicit sentinel model_used == "guardrail_short_circuit"
    - by_model_used: count of calls by resolved model id / sentinel
    - fallback_model_count: count of predictions where fallback model was used
    - heuristic_fallback_count: count of predictions that fell back to heuristic
    - failed_count: count of failed calls
    - total_cost: sum of cost across all predictions
    - mean_input_tokens: average input tokens per prediction
    """
    by_model: dict[str, int] = defaultdict(int)
    calls = 0
    fallback_model_count = 0
    heuristic_fallback_count = 0
    total_cost = 0.0
    token_counts: list[float] = []

    live_fail_metrics = compute_live_failure_metrics(records, live=live)
    failed_count = live_fail_metrics["live_failures"]

    for r in records:
        model = normalize_model_used(r.get("model_used")) or "unknown"
        by_model[model] += 1

        is_guardrail = model == "guardrail_short_circuit"
        if not is_guardrail:
            calls += 1

        if bool(r.get("fallback_model_used")):
            fallback_model_count += 1

        source = str(r.get("assessment_source") or "")
        is_heuristic = (
            source == "heuristic_fallback" or model == "jev_calibrated_heuristic" or "heuristic" in model.lower()
        )
        if is_heuristic and not is_guardrail:
            heuristic_fallback_count += 1

        cost = float(r.get("cost") or 0.0)
        total_cost += cost

        toks = r.get("input_tokens")
        if toks is not None and toks > 0:
            token_counts.append(float(toks))

    mean_input_tokens = round(float(np.mean(token_counts)), 2) if token_counts else 0.0

    return {
        "calls": calls,
        "by_model_used": dict(by_model),
        "fallback_model_count": fallback_model_count,
        "heuristic_fallback_count": heuristic_fallback_count,
        "failed_count": failed_count,
        "total_cost": round(total_cost, 6),
        "mean_input_tokens": mean_input_tokens,
    }


def evaluate_suite(
    records: list[dict[str, Any]],
    live_calls: int = 0,
    live: bool = False,
    n_bootstraps: int = 500,
    ci: float = 0.95,
    seed: int = 42,
    use_prevalence_weights: bool = False,
) -> dict[str, Any]:
    """Run full evaluation suite over prediction records and return metrics dictionary."""
    y_true = [str(r.get("label") or "") for r in records]
    y_pred = [str(r.get("predicted_category") or "") for r in records]
    confs = [float(r.get("confidence") or 0.0) for r in records]

    weights = None
    if use_prevalence_weights:
        weights = [float(r.get("prevalence_weight", 1.0)) for r in records]

    boot_res = bootstrap_macro_f1_ci(y_true, y_pred, n_bootstraps=n_bootstraps, ci=ci, seed=seed, weights=weights)
    fpr = no_violation_false_alarm_rate(y_true, y_pred, weights=weights)
    rec_at_budget = adverse_recall_at_alert_budget(records, alert_budget_pct=5.0, weights=weights)
    pr_aucs = compute_per_class_pr_auc(records, weights=weights)
    calib = compute_calibration(y_true, y_pred, confs, n_bins=10, weights=weights)
    aurc = compute_aurc(y_true, y_pred, confs, weights=weights)
    live_failure_metrics = compute_live_failure_metrics(records, live_calls=live_calls, live=live)
    cost = compute_cost_metrics(records, live_calls=live_failure_metrics["live_calls"])
    provenance = compute_provenance_metrics(records, live=live)

    per_class = compute_per_class_f1(y_true, y_pred, weights=weights)

    return {
        "n": len(records),
        "macro_f1": boot_res["point"],
        "ci": [boot_res["ci_lower"], boot_res["ci_upper"]],
        "ci_half_width": boot_res["ci_half_width"],
        "no_violation_fpr": round(fpr, 6),
        "adverse_recall_at_budget": round(rec_at_budget, 6),
        "per_class_pr_auc": pr_aucs,
        "calibration": calib,
        "aurc": round(aurc, 6),
        "cost": cost,
        "provenance": provenance,
        "live_calls": live_failure_metrics["live_calls"],
        "live_failures": live_failure_metrics["live_failures"],
        "live_failure_rate": live_failure_metrics["live_failure_rate"],
        "live_failures_by_cause": live_failure_metrics["live_failures_by_cause"],
        "per_class": per_class,
    }

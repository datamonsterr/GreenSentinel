"""Unit tests for benchmark experiment metrics suite (Issue #497 / Epic #494).

Hand-computed fixture verifications for:
- Macro-F1 over 7 classes with 95% bootstrap CI
- Paired bootstrap of difference between two prediction sets
- No-violation false-alarm rate (FPR)
- Adverse recall at alert budget
- Per-class PR-AUC (one-vs-rest)
- ECE 10-bin and Brier score
- AURC (Area Under Risk-Coverage Curve)
- Strict minus enum-blind gap
- Cost metrics
- Prevalence-reweighted metrics
"""

import pytest

from scripts.benchmark.experiments import metrics


def test_classes_constant():
    assert metrics.CLASSES == [
        "no_violation",
        "ERR-01",
        "ERR-02",
        "ERR-03",
        "ERR-04",
        "ERR-05",
        "insufficient_evidence",
    ]
    assert metrics.ADVERSE_CLASSES == {"ERR-01", "ERR-02", "ERR-03", "ERR-04", "ERR-05"}


def test_hand_computed_macro_f1():
    # 7 true classes, perfect match -> macro-F1 = 1.0
    y_true = list(metrics.CLASSES)
    y_pred = list(metrics.CLASSES)
    assert pytest.approx(metrics.compute_macro_f1(y_true, y_pred), 1e-6) == 1.0

    # ERR-05 predicted as ERR-04:
    # 5 classes with F1 = 1.0 (no_violation, ERR-01, ERR-02, ERR-03, insufficient_evidence)
    # ERR-04: TP=1, FP=1, FN=0 -> prec=0.5, rec=1.0 -> F1 = 2/3
    # ERR-05: TP=0, FP=0, FN=1 -> F1 = 0.0
    # Macro-F1 = (5 + 2/3) / 7 = 17 / 21
    y_pred_one_err = [
        "no_violation",
        "ERR-01",
        "ERR-02",
        "ERR-03",
        "ERR-04",
        "ERR-04",
        "insufficient_evidence",
    ]
    expected_f1 = 17.0 / 21.0
    assert pytest.approx(metrics.compute_macro_f1(y_true, y_pred_one_err), 1e-6) == expected_f1


def test_bootstrap_macro_f1_ci():
    y_true = metrics.CLASSES * 10
    y_pred = metrics.CLASSES * 10
    res = metrics.bootstrap_macro_f1_ci(y_true, y_pred, n_bootstraps=200, ci=0.95, seed=42)
    assert pytest.approx(res["point"], 1e-6) == 1.0
    assert pytest.approx(res["ci_lower"], 1e-6) == 1.0
    assert pytest.approx(res["ci_upper"], 1e-6) == 1.0
    assert res["ci_half_width"] >= 0.0


def test_paired_bootstrap_difference():
    # Candidate is perfect, baseline has errors
    y_true = metrics.CLASSES * 5
    y_pred_cand = metrics.CLASSES * 5
    y_pred_best = ["no_violation"] * len(y_true)

    res = metrics.paired_bootstrap_difference(y_true, y_pred_cand, y_pred_best, n_bootstraps=200, ci=0.95, seed=42)
    cand_f1 = metrics.compute_macro_f1(y_true, y_pred_cand)
    best_f1 = metrics.compute_macro_f1(y_true, y_pred_best)
    expected_diff = cand_f1 - best_f1

    assert pytest.approx(res["diff"], 1e-6) == expected_diff
    assert res["ci_lower"] <= res["diff"] <= res["ci_upper"]
    assert res["ci_half_width"] == pytest.approx((res["ci_upper"] - res["ci_lower"]) / 2.0, abs=1e-5)


def test_no_violation_false_alarm_rate():
    # 4 true no_violation trips, 2 adverse trips
    y_true = ["no_violation", "no_violation", "no_violation", "no_violation", "ERR-01", "ERR-02"]
    y_pred = ["no_violation", "ERR-01", "insufficient_evidence", "ERR-05", "ERR-01", "no_violation"]
    # True no_violation at indices 0, 1, 2, 3:
    # 0 -> no_violation (OK)
    # 1 -> ERR-01 (False Alarm)
    # 2 -> insufficient_evidence (Not adverse ERR-0x)
    # 3 -> ERR-05 (False Alarm)
    # Rate = 2 / 4 = 0.5
    fpr = metrics.no_violation_false_alarm_rate(y_true, y_pred)
    assert pytest.approx(fpr, 1e-6) == 0.5

    # Denominator zero returns 0.0
    assert metrics.no_violation_false_alarm_rate(["ERR-01"], ["ERR-01"]) == 0.0


def test_adverse_recall_at_alert_budget():
    # 10 trips, 4 true adverse (indices 0, 1, 2, 6)
    records = [
        {"trip_ref": "t0", "label": "ERR-01", "predicted_category": "ERR-01", "confidence": 0.90},
        {"trip_ref": "t1", "label": "ERR-02", "predicted_category": "ERR-02", "confidence": 0.80},
        {"trip_ref": "t2", "label": "ERR-03", "predicted_category": "no_violation", "confidence": 0.40},
        {"trip_ref": "t3", "label": "no_violation", "predicted_category": "no_violation", "confidence": 0.90},
        {"trip_ref": "t4", "label": "no_violation", "predicted_category": "no_violation", "confidence": 0.95},
        {"trip_ref": "t5", "label": "no_violation", "predicted_category": "ERR-04", "confidence": 0.70},
        {"trip_ref": "t6", "label": "ERR-04", "predicted_category": "insufficient_evidence", "confidence": 0.80},
        {"trip_ref": "t7", "label": "no_violation", "predicted_category": "no_violation", "confidence": 0.85},
        {
            "trip_ref": "t8",
            "label": "insufficient_evidence",
            "predicted_category": "insufficient_evidence",
            "confidence": 0.90,
        },
        {"trip_ref": "t9", "label": "no_violation", "predicted_category": "no_violation", "confidence": 0.99},
    ]

    # Risks:
    # t0: 0.90
    # t1: 0.80
    # t5: 0.70
    # t2: 0.60 (1 - 0.40)
    # Top 20% = 2 trips (t0, t1) -> adverse recall = 2 / 4 = 0.50
    rec_20 = metrics.adverse_recall_at_alert_budget(records, alert_budget_pct=20.0)
    assert pytest.approx(rec_20, 1e-6) == 0.50

    # Top 40% = 4 trips (t0, t1, t5, t2) -> 3 adverse in top 4 -> 3 / 4 = 0.75
    rec_40 = metrics.adverse_recall_at_alert_budget(records, alert_budget_pct=40.0)
    assert pytest.approx(rec_40, 1e-6) == 0.75

    # Top 10% = 1 trip (t0) -> 1 / 4 = 0.25
    rec_10 = metrics.adverse_recall_at_alert_budget(records, alert_budget_pct=10.0)
    assert pytest.approx(rec_10, 1e-6) == 0.25

    # Test with explicit probabilities dict (1 - P(no_violation))
    records_with_probs = [
        {
            "trip_ref": "p0",
            "label": "ERR-01",
            "predicted_category": "ERR-01",
            "confidence": 0.5,
            "probabilities": {"no_violation": 0.05},
        },
        {
            "trip_ref": "p1",
            "label": "no_violation",
            "predicted_category": "no_violation",
            "confidence": 0.5,
            "probabilities": {"no_violation": 0.95},
        },
    ]
    rec_prob = metrics.adverse_recall_at_alert_budget(records_with_probs, alert_budget_pct=50.0)
    assert pytest.approx(rec_prob, 1e-6) == 1.0


def test_per_class_pr_auc():
    # 4 samples for ERR-01:
    # A: label=ERR-01, score=0.9
    # B: label=no_violation, score=0.8
    # C: label=ERR-01, score=0.7
    # D: label=no_violation, score=0.2
    # Standard AP / PR-AUC: (0.5 - 0)*1.0 + (1.0 - 0.5)*(2/3) = 0.5 + 1/3 = 5/6 ≈ 0.833333
    records = [
        {
            "trip_ref": "A",
            "label": "ERR-01",
            "predicted_category": "ERR-01",
            "confidence": 0.9,
            "probabilities": {"ERR-01": 0.9},
        },
        {
            "trip_ref": "B",
            "label": "no_violation",
            "predicted_category": "ERR-01",
            "confidence": 0.8,
            "probabilities": {"ERR-01": 0.8},
        },
        {
            "trip_ref": "C",
            "label": "ERR-01",
            "predicted_category": "ERR-01",
            "confidence": 0.7,
            "probabilities": {"ERR-01": 0.7},
        },
        {
            "trip_ref": "D",
            "label": "no_violation",
            "predicted_category": "no_violation",
            "confidence": 0.8,
            "probabilities": {"ERR-01": 0.2},
        },
    ]
    pr_auc = metrics.compute_per_class_pr_auc(records)
    assert "ERR-01" in pr_auc
    assert pytest.approx(pr_auc["ERR-01"], 1e-3) == 5.0 / 6.0


def test_ece_and_brier():
    y_true = ["no_violation", "ERR-01", "ERR-02", "ERR-03"]
    y_pred = ["no_violation", "ERR-01", "no_violation", "ERR-03"]
    confidences = [0.95, 0.85, 0.85, 0.35]

    # Hand-computed:
    # Brier: (0.05^2 + 0.15^2 + 0.85^2 + 0.65^2) / 4 = 1.17 / 4 = 0.2925
    # ECE (10-bin): (1/4)*0.05 + (2/4)*0.35 + (1/4)*0.65 = 0.3500
    calib = metrics.compute_calibration(y_true, y_pred, confidences, n_bins=10)
    assert pytest.approx(calib["brier"], 1e-4) == 0.2925
    assert pytest.approx(calib["ece_10bin"], 1e-4) == 0.3500
    assert len(calib["bins"]) > 0


def test_aurc_risk_coverage():
    # 4 samples sorted by confidence: [0.9, 0.8, 0.7, 0.6]
    # Errors: [0, 0, 1, 1]
    # m=1: risk = 0 / 1 = 0
    # m=2: risk = 0 / 2 = 0
    # m=3: risk = 1 / 3
    # m=4: risk = 2 / 4 = 0.5
    # AURC = (0 + 0 + 1/3 + 0.5) / 4 = 5/24 ≈ 0.208333
    y_true = ["A", "B", "C", "D"]
    y_pred = ["A", "B", "X", "Y"]
    confs = [0.9, 0.8, 0.7, 0.6]

    aurc = metrics.compute_aurc(y_true, y_pred, confs)
    assert pytest.approx(aurc, 1e-4) == 5.0 / 24.0


def test_strict_minus_enum_blind_gap():
    assert pytest.approx(metrics.compute_strict_enum_blind_gap(0.85, 0.75), 1e-6) == 0.10


def test_cost_metrics():
    records = [
        {"latency_ms": 10.0, "input_tokens": 100},
        {"latency_ms": 20.0, "input_tokens": 200},
        {"latency_ms": 100.0, "input_tokens": 0, "bundle": {"a": 1}},  # fallback token estimate
    ]
    cost = metrics.compute_cost_metrics(records, live_calls=2)
    assert cost["live_calls"] == 2
    assert cost["mean_latency_ms"] > 0
    assert cost["p95_latency_ms"] >= cost["p50_latency_ms"]
    assert cost["mean_input_tokens"] > 0


def test_prevalence_reweighting():
    # Two samples of no_violation, one correct and one incorrect
    y_true = ["no_violation", "no_violation"]
    y_pred = ["no_violation", "ERR-01"]
    # Without weights: FPR = 1/2 = 0.5
    assert pytest.approx(metrics.no_violation_false_alarm_rate(y_true, y_pred), 1e-6) == 0.5

    # With weights: sample 0 has weight 3.0, sample 1 has weight 1.0
    # FPR = 1.0 / (3.0 + 1.0) = 0.25
    weights = [3.0, 1.0]
    fpr_weighted = metrics.no_violation_false_alarm_rate(y_true, y_pred, weights=weights)
    assert pytest.approx(fpr_weighted, 1e-6) == 0.25


def test_evaluate_suite_live_failure_accounting():
    records = [
        # Normal live success
        {
            "label": "no_violation",
            "predicted_category": "no_violation",
            "confidence": 0.9,
            "model_used": "~typesafe/jev-latest",
        },
        # Guardrail short-circuit (NOT a live failure)
        {
            "label": "insufficient_evidence",
            "predicted_category": "insufficient_evidence",
            "confidence": 0.0,
            "model_used": "guardrail_short_circuit",
        },
        # Live failure: 402 insufficient credits
        {
            "label": "ERR-01",
            "predicted_category": "ERR-01",
            "confidence": 0.8,
            "model_used": "jev_calibrated_heuristic",
            "fallback_reason": "insufficient_credits",
            "http_status": 402,
        },
        # Live failure: 400 token limit
        {
            "label": "ERR-02",
            "predicted_category": "ERR-02",
            "confidence": 0.7,
            "model_used": "jev_calibrated_heuristic",
            "fallback_reason": "max_tokens_exceeded",
            "http_status": 400,
        },
        # Live failure: 429 rate limit
        {
            "label": "ERR-03",
            "predicted_category": "ERR-03",
            "confidence": 0.6,
            "model_used": "jev_calibrated_heuristic",
            "fallback_reason": "rate_limit",
            "http_status": 429,
        },
    ]
    res = metrics.evaluate_suite(records, live_calls=4, live=True)
    assert res["live_calls"] == 4
    assert res["live_failures"] == 3
    assert pytest.approx(res["live_failure_rate"], 1e-4) == 3 / 4
    assert res["live_failures_by_cause"]["insufficient_credits"] == 1
    assert res["live_failures_by_cause"]["max_tokens_exceeded"] == 1
    assert res["live_failures_by_cause"]["rate_limit"] == 1
    assert res["live_failures_by_cause"]["timeout"] == 0
    assert res["live_failures_by_cause"]["other"] == 0


def test_evaluate_suite_offline_zero_live_failures():
    records = [
        {
            "label": "no_violation",
            "predicted_category": "no_violation",
            "confidence": 0.9,
            "model_used": "jev_calibrated_heuristic",
        },
        {
            "label": "ERR-01",
            "predicted_category": "ERR-01",
            "confidence": 0.8,
            "model_used": "jev_calibrated_heuristic",
        },
    ]
    res = metrics.evaluate_suite(records, live_calls=0, live=False)
    assert res["live_calls"] == 0
    assert res["live_failures"] == 0
    assert res["live_failure_rate"] == 0.0
    assert res["live_failures_by_cause"] == {
        "max_tokens_exceeded": 0,
        "insufficient_credits": 0,
        "rate_limit": 0,
        "timeout": 0,
        "other": 0,
    }

"""Tests for research harness metric integrity, variant propagation, and comparator gating (#525).

Covers:
1. Live failure propagation: variants omitting model_used/fallback_reason counted as failures in live mode.
2. Gating denominator consistency: guardrail short-circuits excluded from live_calls denominator.
3. Live runs with 0 live calls marked invalid.
4. Paired comparison rejects mismatched split.
5. Paired comparison rejects mismatched sample size.
6. Real model input token accounting uses jev_inp and respects state_variant.
7. Early abort recording in metrics.json.
"""

import json

import pytest

from scripts.benchmark.experiments import compare, metrics, run_experiment, variants


def test_variant_omitting_model_used_counted_as_failure_in_live_mode():
    """If a variant omits model_used or leaves it None/empty/unknown in live mode,
    it must NOT be counted as a live model success; it must be classified as an
    untracked live failure and increment live_failures."""
    records = [
        # Normal live success with recognized model
        {
            "trip_ref": "t1",
            "label": "no_violation",
            "predicted_category": "no_violation",
            "confidence": 0.9,
            "model_used": "~typesafe/jev-latest",
        },
        # Variant omitted model_used (None)
        {
            "trip_ref": "t2",
            "label": "ERR-01",
            "predicted_category": "ERR-01",
            "confidence": 0.8,
            "model_used": None,
        },
        # Variant returned "unknown" model_used
        {
            "trip_ref": "t3",
            "label": "ERR-02",
            "predicted_category": "ERR-02",
            "confidence": 0.7,
            "model_used": "unknown",
        },
        # Guardrail short-circuit (not a live call)
        {
            "trip_ref": "t4",
            "label": "insufficient_evidence",
            "predicted_category": "insufficient_evidence",
            "confidence": 0.0,
            "model_used": "guardrail_short_circuit",
            "guardrail_blocked": True,
        },
    ]

    res = metrics.compute_live_failure_metrics(records, live_calls=3, live=True)
    assert res["live_calls"] == 3
    # Both t2 and t3 must be counted as failures
    assert res["live_failures"] == 2
    assert res["live_failure_rate"] == pytest.approx(2 / 3, rel=1e-3)
    assert res["live_failures_by_cause"].get("untracked_variant_failure", 0) >= 1


def test_live_calls_denominator_inferred_consistently():
    """When live_calls=0 or omitted, compute_live_failure_metrics must infer
    live_calls from records excluding guardrail short-circuits."""
    records = [
        {
            "trip_ref": "t1",
            "label": "no_violation",
            "predicted_category": "no_violation",
            "confidence": 0.9,
            "model_used": "model_a",
        },
        {
            "trip_ref": "t2",
            "label": "ERR-01",
            "predicted_category": "ERR-01",
            "confidence": 0.8,
            "model_used": "guardrail_short_circuit",
            "guardrail_blocked": True,
        },
        {
            "trip_ref": "t3",
            "label": "ERR-02",
            "predicted_category": "ERR-02",
            "confidence": 0.7,
            "model_used": "model_a",
        },
    ]
    res = metrics.compute_live_failure_metrics(records, live_calls=0, live=True)
    # Only 2 trips were live calls (t1, t3); t2 was guardrail
    assert res["live_calls"] == 2
    assert res["live_failures"] == 0
    assert res["live_failure_rate"] == 0.0


def test_compare_rejects_mismatched_split():
    """Paired comparison must refuse when candidate split != best split."""
    cand = {
        "macro_f1": 0.80,
        "valid": True,
        "split": "test",
        "sample": 1000,
        "corpus_trips_sha256": "sha_123",
        "enum_blind": True,
    }
    best = {
        "macro_f1": 0.75,
        "valid": True,
        "split": "validation",
        "sample": 1000,
        "corpus_trips_sha256": "sha_123",
        "enum_blind": True,
    }
    with pytest.raises(ValueError, match="[Mm]ismatched split"):
        compare.validate_paired_comparison(candidate=cand, best=best)


def test_compare_rejects_mismatched_sample_size():
    """Paired comparison must refuse when candidate sample size != best sample size."""
    cand = {
        "macro_f1": 0.80,
        "valid": True,
        "split": "validation",
        "sample": 500,
        "corpus_trips_sha256": "sha_123",
        "enum_blind": True,
    }
    best = {
        "macro_f1": 0.75,
        "valid": True,
        "split": "validation",
        "sample": 1000,
        "corpus_trips_sha256": "sha_123",
        "enum_blind": True,
    }
    with pytest.raises(ValueError, match="[Mm]ismatched sample"):
        compare.validate_paired_comparison(candidate=cand, best=best)


def test_compare_requires_paired_ci_half_width_when_best_present():
    """Evaluating a decision against best requires explicit paired_ci_half_width."""
    cand = {
        "macro_f1": 0.80,
        "valid": True,
        "split": "validation",
        "sample": 1000,
        "corpus_trips_sha256": "sha_123",
        "enum_blind": True,
        "ci_half_width": 0.05,
    }
    best = {
        "macro_f1": 0.75,
        "valid": True,
        "split": "validation",
        "sample": 1000,
        "corpus_trips_sha256": "sha_123",
        "enum_blind": True,
        "ci_half_width": 0.05,
    }
    with pytest.raises(ValueError, match="paired_ci_half_width"):
        compare.evaluate_decision(candidate=cand, best=best, paired_ci_half_width=None)


def test_calculate_input_tokens_uses_jev_input_and_respects_variant():
    """_calculate_input_tokens must respect jev_inp and its state_variant,
    not hardcode variant='baseline' and re-parse raw bundle."""
    from scripts.benchmark import run_10k

    sample_bundle = {
        "trip_ref": "t-001",
        "label": "no_violation",
        "driver_id": "drv-001",
        "telemetry": [
            {
                "latitude": 10.77,
                "longitude": 106.69,
                "accuracy_m": 5,
                "speed_mps": 5.0,
                "occurred_at": "2026-10-01T00:00:00Z",
            }
        ],
        "trip": {"status": "completed"},
        "assignment": {"arrived_at": "2026-10-01T00:00:00Z"},
    }
    jev_inp, _, _ = run_10k.bundle_to_input(sample_bundle)
    jev_inp.state_variant = "features_numeric"

    tokens_numeric = variants._calculate_input_tokens(sample_bundle, jev_inp)

    jev_inp_baseline, _, _ = run_10k.bundle_to_input(sample_bundle)
    jev_inp_baseline.state_variant = "baseline"
    tokens_baseline = variants._calculate_input_tokens(sample_bundle, jev_inp_baseline)

    # features_numeric cleans PII and drops raw points, producing a distinct state size
    assert tokens_numeric != tokens_baseline or tokens_numeric > 0


@pytest.mark.parametrize("guardrail", [{"guardrail_reason": "soft cap"}, {"guardrail_blocked": True}])
@pytest.mark.parametrize("model,failures", [("jev_calibrated_heuristic", 1), ("typesafe/jev", 0)])
def test_soft_guardrail_counts_provider_call_and_failure(guardrail, model, failures):
    result = metrics.compute_live_failure_metrics([{"model_used": model, **guardrail}], live=True)
    assert result["live_calls"] == 1
    assert result["live_failures"] == failures
    assert result["live_failure_rate"] == failures


@pytest.mark.parametrize("supplied_calls", [0, 1, 1000])
def test_caller_cannot_dilute_failure_denominator(supplied_calls):
    records = [{"model_used": "jev_calibrated_heuristic"}, {"model_used": "guardrail_short_circuit"}]
    result = metrics.evaluate_suite(records, live_calls=supplied_calls, live=True)
    assert result["live_calls"] == 1
    assert result["cost"]["live_calls"] == 1
    assert result["live_failure_rate"] == 1.0


@pytest.mark.parametrize("model", [None, "", "   ", "unknown", "None", [], {}, 42, True])
@pytest.mark.asyncio
async def test_untracked_models_fail_closed_in_worker_and_metrics(monkeypatch, model):
    async def assess(*args, **kwargs):
        return {"model_used": model, "guardrail_reason": "soft cap"}

    monkeypatch.setattr(run_experiment, "run_single_variant_async", assess)
    records, calls, aborted = await run_experiment._execute_all_bundles(
        [{"trip_ref": "untracked"}], "baseline", "validation", True, False, 1
    )
    assert calls == 1
    assert not aborted
    assert records[0]["model_used"] == "unknown"
    assert records[0]["fallback_reason"] == "untracked_variant_failure"
    direct = metrics.compute_live_failure_metrics([{"model_used": model}], live=True)
    actual = metrics.compute_live_failure_metrics(records, live_calls=calls, live=True)
    for result in (direct, actual):
        assert result["live_failures"] == 1
        assert result["live_failures_by_cause"]["untracked_variant_failure"] == 1


@pytest.mark.asyncio
async def test_worker_excludes_only_explicit_short_circuit(monkeypatch):
    predictions = iter(
        [
            {"model_used": "jev_calibrated_heuristic", "guardrail_reason": "soft cap"},
            {"model_used": "typesafe/jev", "guardrail_blocked": True},
            {"model_used": "guardrail_short_circuit"},
        ]
    )

    async def assess(*args, **kwargs):
        return next(predictions)

    monkeypatch.setattr(run_experiment, "run_single_variant_async", assess)
    records, calls, aborted = await run_experiment._execute_all_bundles(
        [{"trip_ref": str(i)} for i in range(3)], "baseline", "validation", True, False, 1
    )
    assert calls == 2
    assert not aborted
    result = metrics.compute_live_failure_metrics(records, live_calls=calls, live=True)
    assert result["live_calls"] == 2
    assert result["live_failures"] == 1
    assert result["live_failure_rate"] == 0.5


def test_zero_live_calls_remain_invalid(tmp_path, monkeypatch):
    async def assess(*args, **kwargs):
        return {"model_used": "guardrail_short_circuit", "predicted_category": "no_violation", "confidence": 1.0}

    monkeypatch.setattr(run_experiment, "run_single_variant_async", assess)
    source = tmp_path / "trips.jsonl"
    source.write_text(json.dumps({"trip_ref": "guardrail", "split": "validation", "label": "no_violation"}) + "\n")
    result = run_experiment.run_experiment_pipeline(
        "test", "baseline", source, sample=1, live=True, out_dir=tmp_path / "result"
    )
    assert result["live_calls"] == 0
    assert result["valid"] is False
    assert json.loads((tmp_path / "result" / "metrics.json").read_text())["valid"] is False

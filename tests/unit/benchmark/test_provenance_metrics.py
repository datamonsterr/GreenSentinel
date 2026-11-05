"""Unit tests for benchmark provenance metrics and live heuristic fallback gating (Issue #545).

TDD test suite verifying:
1. evaluate_suite returns a provenance block {calls, by_model_used, fallback_model_count, heuristic_fallback_count, failed_count, total_cost, mean_input_tokens}.
2. Provenance counts correctly track primary, fallback, and heuristic executions.
3. In live mode, heuristic_fallback_count > 0 marks run invalid and triggers failure stdout / abort.
4. run_experiment and run_10k write per-prediction model_used, fallback_model_used, and assessment_source.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from scripts.benchmark.experiments.metrics import compute_provenance_metrics, evaluate_suite


def _make_dummy_prediction(
    idx: int,
    model_used: str = "inception/mercury-decide:free",
    fallback_model_used: bool = False,
    assessment_source: str = "model",
    cost: float = 0.0,
    input_tokens: int = 150,
    label: str = "no_violation",
    predicted: str = "no_violation",
) -> dict:
    return {
        "trip_ref": f"trip-{idx}",
        "label": label,
        "predicted_category": predicted,
        "confidence": 0.95,
        "probabilities": {predicted: 0.95},
        "priority_tier": 2,
        "latency_ms": 45.0,
        "input_tokens": input_tokens,
        "model_used": model_used,
        "fallback_model_used": fallback_model_used,
        "assessment_source": assessment_source,
        "cost": cost,
    }


def test_compute_provenance_metrics_counts():
    """Verify provenance block fields and aggregation across models."""
    records = [
        # 3 primary calls
        _make_dummy_prediction(
            1,
            model_used="inception/mercury-decide:free",
            fallback_model_used=False,
            assessment_source="model",
            cost=0.0,
            input_tokens=100,
        ),
        _make_dummy_prediction(
            2,
            model_used="inception/mercury-decide:free",
            fallback_model_used=False,
            assessment_source="model",
            cost=0.0,
            input_tokens=120,
        ),
        _make_dummy_prediction(
            3,
            model_used="inception/mercury-decide:free",
            fallback_model_used=False,
            assessment_source="model",
            cost=0.0,
            input_tokens=140,
        ),
        # 1 fallback call
        _make_dummy_prediction(
            4,
            model_used="perplexity/pplx-decider-flash-v1.2",
            fallback_model_used=True,
            assessment_source="model",
            cost=0.0005,
            input_tokens=110,
        ),
        # 1 heuristic fallback
        _make_dummy_prediction(
            5,
            model_used="jev_calibrated_heuristic",
            fallback_model_used=False,
            assessment_source="heuristic_fallback",
            cost=0.0,
            input_tokens=0,
        ),
        # 1 guardrail short-circuit (not an LLM call)
        _make_dummy_prediction(
            6,
            model_used="guardrail_short_circuit",
            fallback_model_used=False,
            assessment_source="guardrail",
            cost=0.0,
            input_tokens=0,
            label="insufficient_evidence",
            predicted="insufficient_evidence",
        ),
    ]

    prov = compute_provenance_metrics(records, live=True)

    # 5 non-guardrail calls
    assert prov["calls"] == 5
    assert prov["by_model_used"]["inception/mercury-decide:free"] == 3
    assert prov["by_model_used"]["perplexity/pplx-decider-flash-v1.2"] == 1
    assert prov["by_model_used"]["jev_calibrated_heuristic"] == 1
    assert prov["by_model_used"]["guardrail_short_circuit"] == 1
    assert prov["fallback_model_count"] == 1
    assert prov["heuristic_fallback_count"] == 1
    assert prov["failed_count"] >= 1
    assert prov["total_cost"] == 0.0005
    assert prov["mean_input_tokens"] > 0


def test_evaluate_suite_includes_provenance():
    """evaluate_suite includes provenance block in returned metrics."""
    records = [
        _make_dummy_prediction(1, model_used="inception/mercury-decide:free", cost=0.0, input_tokens=100),
        _make_dummy_prediction(2, model_used="inception/mercury-decide:free", cost=0.0, input_tokens=100),
    ]

    suite = evaluate_suite(records, live=True)
    assert "provenance" in suite
    assert suite["provenance"]["calls"] == 2
    assert suite["provenance"]["fallback_model_count"] == 0
    assert suite["provenance"]["heuristic_fallback_count"] == 0


def test_live_heuristic_fallback_invalidates_run(tmp_path: Path):
    """In --live mode, heuristic_fallback_count > 0 marks run invalid and prints detection stdout."""
    from scripts.benchmark.experiments.run_experiment import run_experiment_pipeline

    # Create dummy in_path
    in_file = tmp_path / "trips.jsonl"
    dummy_bundle = {
        "trip_ref": "trip-001",
        "driver_id": "drv-001",
        "split": "validation",
        "label": "no_violation",
        "trip": {"lifecycle_state": "completed"},
        "assignment": {},
        "telemetry": {"points": []},
    }
    in_file.write_text(json.dumps(dummy_bundle) + "\n", encoding="utf-8")

    out_dir = tmp_path / "out"

    # Mock _execute_all_bundles to return a prediction with heuristic_fallback
    dummy_result = [
        _make_dummy_prediction(
            1,
            model_used="jev_calibrated_heuristic",
            fallback_model_used=False,
            assessment_source="heuristic_fallback",
        )
    ]

    with (
        patch(
            "scripts.benchmark.experiments.run_experiment._execute_all_bundles", return_value=(dummy_result, 1, False)
        ),
        patch("sys.exit") as mock_exit,
        patch("builtins.print") as mock_print,
    ):
        metrics = run_experiment_pipeline(
            exp_id="TEST",
            variant="baseline",
            in_path=in_file,
            split="validation",
            sample=1,
            live=True,
            out_dir=out_dir,
        )

        assert metrics["valid"] is False
        assert metrics["provenance"]["heuristic_fallback_count"] == 1
        mock_exit.assert_called()
        # Verify print statement was called with HEURISTIC FALLBACK DETECTED line
        print_calls = [call.args[0] for call in mock_print.call_args_list if call.args]
        assert any("HEURISTIC FALLBACK DETECTED: 1" in str(line) for line in print_calls)

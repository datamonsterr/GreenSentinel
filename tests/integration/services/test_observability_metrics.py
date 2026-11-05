import hashlib

from src.services import observability_metrics


def test_benchmark_summary_uses_recorded_artifact_provenance(tmp_path, monkeypatch):
    dataset = tmp_path / "dataset.json"
    result = tmp_path / "benchmark.json"
    dataset_bytes = b'{"case": 1}'
    dataset.write_bytes(dataset_bytes)
    result.write_text(
        '{"timestamp":"2026-10-02T00:00:00","total_test_cases":1,'
        '"dataset_version":"dataset-v1","model_version":"gemini-test",'
        '"prompt_version":"prompt-v1","retrieval_top3_accuracy_pct":100}',
        encoding="utf-8",
    )
    monkeypatch.setattr(observability_metrics, "_BENCHMARK_DATASET", dataset)
    monkeypatch.setattr(observability_metrics, "_BENCHMARK_RESULT", result)

    summary = observability_metrics._benchmark_summary()

    assert summary["dataset_version"] == "dataset-v1"
    assert summary["current_dataset_version"] == hashlib.sha256(dataset_bytes).hexdigest()[:12]
    assert summary["benchmark_model_version"] == "gemini-test"
    assert summary["benchmark_prompt_version"] == "prompt-v1"
    assert summary["metrics"] == {"retrieval_top3_accuracy_pct": 100}
    assert summary["artifact_version"] == hashlib.sha256(result.read_bytes()).hexdigest()[:12]


def test_estimated_cost_requires_finite_non_negative_pricing(monkeypatch):
    monkeypatch.setenv("GEMINI_INPUT_COST_USD_PER_MILLION", "NaN")
    monkeypatch.setenv("GEMINI_OUTPUT_COST_USD_PER_MILLION", "0.5")
    assert observability_metrics._estimated_cost(10, 20) is None

    monkeypatch.setenv("GEMINI_INPUT_COST_USD_PER_MILLION", "0.25")
    monkeypatch.setenv("GEMINI_OUTPUT_COST_USD_PER_MILLION", "0.5")
    assert str(observability_metrics._estimated_cost(1_000_000, 2_000_000)) == "1.25"


def test_summary_aggregates_only_bounded_run_observations(monkeypatch):
    monkeypatch.setenv("GEMINI_INPUT_COST_USD_PER_MILLION", "1")
    monkeypatch.setenv("GEMINI_OUTPUT_COST_USD_PER_MILLION", "2")
    with observability_metrics._observations_lock:
        observability_metrics._observations.clear()
    try:
        observability_metrics.record_run(
            trace_id="trace-safe",
            run_id="run-safe",
            latency_ms=250,
            status="completed",
            timed_out=False,
            tool_count=2,
            tool_success_count=1,
            tool_failure_count=1,
            input_tokens=100,
            output_tokens=50,
            model="gemini-test",
            grounding_errors=0,
            grounding_sample_count=1,
            guardrail_violations=0,
            guardrail_sample_count=1,
        )
        summary = observability_metrics.get_observability_summary()
        assert summary["run_count"] == 1
        assert summary["latency_ms"] == {"sample_count": 1, "p50": 250, "p95": 250}
        assert summary["tools"]["success_rate_pct"] == 50.0
        assert summary["model"]["estimated_cost_usd"] == "0.0002"
        assert summary["quality"]["grounding_sample_count"] == 1
        assert "trace-safe" not in str(summary)
        assert "run-safe" not in str(summary)
    finally:
        with observability_metrics._observations_lock:
            observability_metrics._observations.clear()

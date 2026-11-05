"""Unit tests for experiment harness and variant registry (Issue #497 / Epic #494)."""

import json
from pathlib import Path

import pytest

from scripts.benchmark.experiments import run_experiment, variants


def test_variant_registry():
    @variants.register_variant("mock_test_variant")
    def mock_var(bundle: dict, live: bool = False) -> dict:
        return {
            "predicted_category": "no_violation",
            "confidence": 0.9,
            "probabilities": {"no_violation": 0.9},
            "priority_tier": 2,
            "latency_ms": 1.0,
            "input_tokens": 10,
        }

    assert "mock_test_variant" in variants.list_variants()
    var_fn = variants.get_variant("mock_test_variant")
    res = var_fn({}, live=False)
    assert res["predicted_category"] == "no_violation"


def test_baseline_variant_registered():
    assert "baseline" in variants.list_variants()
    baseline_fn = variants.get_variant("baseline")
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
    pred = baseline_fn(sample_bundle, live=False)
    assert "predicted_category" in pred
    assert "confidence" in pred
    assert "probabilities" in pred
    assert "priority_tier" in pred
    assert "latency_ms" in pred
    assert "input_tokens" in pred


def test_split_filtering_deterministic():
    bundles = [
        {"trip_ref": "t1", "driver_id": "driver_alpha", "split": "train"},
        {"trip_ref": "t2", "driver_id": "driver_beta", "split": "validation"},
        {"trip_ref": "t3", "driver_id": "driver_gamma"},  # no split -> hash partition
    ]
    train_trips = run_experiment.filter_by_split(bundles, "train")
    val_trips = run_experiment.filter_by_split(bundles, "validation")
    test_trips = run_experiment.filter_by_split(bundles, "test")

    # All bundles deterministically assigned
    assert len(train_trips) + len(val_trips) + len(test_trips) == len(bundles)
    assert any(b["trip_ref"] == "t1" for b in train_trips)
    assert any(b["trip_ref"] == "t2" for b in val_trips)


def test_stratified_sampling_deterministic():
    # 100 bundles with 4 labels
    bundles = [
        {"trip_ref": f"t_{i}", "label": "no_violation" if i < 70 else "ERR-01" if i < 85 else "ERR-02"}
        for i in range(100)
    ]
    sample1 = run_experiment.stratified_sample(bundles, sample_size=20, seed=20261017)
    sample2 = run_experiment.stratified_sample(bundles, sample_size=20, seed=20261017)
    assert len(sample1) == 20
    assert [b["trip_ref"] for b in sample1] == [b["trip_ref"] for b in sample2]


def test_offline_network_guard_rejection():
    import httpx

    @variants.register_variant("network_leaker")
    def leaky_var(bundle: dict, live: bool = False) -> dict:
        httpx.get("https://example.com")
        return {"predicted_category": "no_violation", "confidence": 0.5, "priority_tier": 2}

    with pytest.raises(RuntimeError, match="offline"):
        run_experiment.run_single_variant("network_leaker", {}, live=False)


def test_experiment_harness_smoke_30_rows(tmp_path: Path):
    in_file = tmp_path / "trips.jsonl"
    out_dir = tmp_path / "exp_out"

    labels = ["no_violation", "ERR-01", "ERR-02", "ERR-03", "ERR-04", "ERR-05", "insufficient_evidence"]
    rows = []
    for i in range(30):
        rows.append(
            {
                "trip_ref": f"trip-{i:03d}",
                "driver_id": f"driver-{i % 5}",
                "label": labels[i % len(labels)],
                "split": "validation",
                "telemetry": [
                    {
                        "latitude": 10.77 + (i * 0.001),
                        "longitude": 106.69,
                        "accuracy_m": 5,
                        "speed_mps": 8.0,
                        "occurred_at": "2026-10-01T00:00:00Z",
                    }
                ],
                "trip": {"status": "completed"},
                "assignment": {"arrived_at": "2026-10-01T00:00:00Z"},
            }
        )
    with in_file.open("w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")

    res = run_experiment.run_experiment_pipeline(
        exp_id="E0",
        variant="baseline",
        in_path=in_file,
        split="validation",
        sample=20,
        seed=20261017,
        live=False,
        enum_blind=False,
        out_dir=out_dir,
    )
    assert res["exp_id"] == "E0"

    pred_file = out_dir / "predictions.jsonl"
    metrics_file = out_dir / "metrics.json"

    assert pred_file.exists()
    assert metrics_file.exists()

    pred_lines = [json.loads(line) for line in pred_file.read_text().strip().splitlines()]
    assert len(pred_lines) == 20

    metrics_data = json.loads(metrics_file.read_text())
    assert metrics_data["exp_id"] == "E0"
    assert metrics_data["variant"] == "baseline"
    assert metrics_data["n"] == 20
    assert "macro_f1" in metrics_data
    assert "ci" in metrics_data
    assert "corpus_trips_sha256" in metrics_data
    assert "git_sha" in metrics_data
    assert "wall_time_s" in metrics_data


def test_baseline_returns_multi_class_probabilities_dict():
    baseline_fn = variants.get_variant("baseline")
    sample_bundle = {
        "trip_ref": "t-002",
        "label": "no_violation",
        "driver_id": "drv-002",
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
    pred = baseline_fn(sample_bundle, live=False)
    probs = pred.get("probabilities")
    assert isinstance(probs, dict)
    assert len(probs) > 1, f"Expected multi-class probabilities dict, got {probs}"
    assert pred.get("input_tokens", 0) > 0, f"Expected input_tokens > 0, got {pred.get('input_tokens')}"


def test_variant_auto_discovery_from_variants_folder(tmp_path: Path):
    variants_dir = tmp_path / "variants"
    variants_dir.mkdir()
    plugin_file = variants_dir / "e1_dummy.py"
    plugin_file.write_text(
        "from scripts.benchmark.experiments.variants import register_variant\n"
        "@register_variant('e1_dummy_variant')\n"
        "def e1_fn(bundle, live=False):\n"
        "    return {'predicted_category': 'no_violation', 'confidence': 0.99}\n",
        encoding="utf-8",
    )
    variants.discover_variants(variants_dir)
    assert "e1_dummy_variant" in variants.list_variants()
    fn = variants.get_variant("e1_dummy_variant")
    res = fn({}, live=False)
    assert res["confidence"] == 0.99


def test_concurrency_gives_identical_predictions_to_sequential_on_fixture_offline(tmp_path: Path):
    in_file = tmp_path / "trips.jsonl"
    out_dir_seq = tmp_path / "out_seq"
    out_dir_conc = tmp_path / "out_conc"

    labels = ["no_violation", "ERR-01", "ERR-02", "ERR-03", "ERR-04", "ERR-05", "insufficient_evidence"]
    rows = []
    for i in range(20):
        rows.append(
            {
                "trip_ref": f"trip-{i:03d}",
                "driver_id": f"driver-{i % 4}",
                "label": labels[i % len(labels)],
                "split": "validation",
                "telemetry": [
                    {
                        "latitude": 10.77 + (i * 0.001),
                        "longitude": 106.69,
                        "accuracy_m": 5,
                        "speed_mps": 6.0,
                        "occurred_at": "2026-10-01T00:00:00Z",
                    }
                ],
                "trip": {"status": "completed"},
                "assignment": {"arrived_at": "2026-10-01T00:00:00Z"},
            }
        )
    with in_file.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")

    res_seq = run_experiment.run_experiment_pipeline(
        exp_id="E_SEQ",
        variant="baseline",
        in_path=in_file,
        split="validation",
        sample=20,
        seed=20261017,
        live=False,
        concurrency=1,
        out_dir=out_dir_seq,
    )

    res_conc = run_experiment.run_experiment_pipeline(
        exp_id="E_CONC",
        variant="baseline",
        in_path=in_file,
        split="validation",
        sample=20,
        seed=20261017,
        live=False,
        concurrency=4,
        out_dir=out_dir_conc,
    )

    preds_seq = [json.loads(line) for line in (out_dir_seq / "predictions.jsonl").read_text().splitlines()]
    preds_conc = [json.loads(line) for line in (out_dir_conc / "predictions.jsonl").read_text().splitlines()]

    assert len(preds_seq) == len(preds_conc)
    for ps, pc in zip(preds_seq, preds_conc):
        assert ps["trip_ref"] == pc["trip_ref"]
        assert ps["predicted_category"] == pc["predicted_category"]
        assert ps["confidence"] == pc["confidence"]
        assert ps["probabilities"] == pc["probabilities"]
        assert ps["priority_tier"] == pc["priority_tier"]

    assert res_seq["macro_f1"] == res_conc["macro_f1"]


@pytest.mark.asyncio
async def test_fake_service_returning_heuristic_with_fallback_reason():
    from src.models.schemas import DriverMotivationAssessment
    from src.services.jev_assessment_service import JevAssessmentResult

    class FakeJevService:
        async def assess(self, inp):
            return JevAssessmentResult(
                category="ERR-01",
                confidence=0.85,
                priority="P1",
                priority_tier=1,
                priority_score=75,
                reason_codes=["fallback_test"],
                forensic_brief="Fallback brief",
                motivation_assessment=DriverMotivationAssessment(),
                model_used="jev_calibrated_heuristic",
                fallback_reason="insufficient_credits",
                http_status=402,
            )

    bundle = {
        "trip_ref": "t-fallback-01",
        "label": "ERR-01",
        "driver_id": "drv-01",
        "telemetry": [
            {
                "latitude": 10.77,
                "longitude": 106.69,
                "accuracy_m": 5,
                "speed_mps": 6.0,
                "occurred_at": "2026-10-01T00:00:00Z",
            }
        ],
        "trip": {"status": "completed"},
        "assignment": {"arrived_at": "2026-10-01T00:00:00Z"},
    }

    pred = await variants.baseline_assess_async(bundle, live=True, service=FakeJevService())
    assert pred["model_used"] == "jev_calibrated_heuristic"
    assert pred["fallback_reason"] == "insufficient_credits"
    assert pred["http_status"] == 402


def test_consecutive_402_early_abort_stops_sending_calls(tmp_path: Path, monkeypatch):
    from src.models.schemas import DriverMotivationAssessment
    from src.services.jev_assessment_service import JevAssessmentResult

    call_count = 0

    class FakeAbortingService:
        async def assess(self, inp):
            nonlocal call_count
            call_count += 1
            return JevAssessmentResult(
                category="ERR-01",
                confidence=0.50,
                priority="P2",
                priority_tier=2,
                priority_score=10,
                reason_codes=["test_402"],
                forensic_brief="402 failure",
                motivation_assessment=DriverMotivationAssessment(),
                model_used="jev_calibrated_heuristic",
                fallback_reason="insufficient_credits",
                http_status=402,
            )

    monkeypatch.setattr(variants, "_cached_live_service", FakeAbortingService())

    # Create 40 bundles
    in_file = tmp_path / "trips.jsonl"
    out_dir = tmp_path / "exp_out_abort"
    rows = [
        {
            "trip_ref": f"trip-{i:03d}",
            "driver_id": f"driver-{i}",
            "label": "no_violation",
            "split": "validation",
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
        for i in range(40)
    ]
    in_file.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")

    with pytest.raises(SystemExit) as excinfo:
        run_experiment.run_experiment_pipeline(
            exp_id="E_ABORT",
            variant="baseline",
            in_path=in_file,
            split="validation",
            sample=40,
            live=True,
            concurrency=1,
            out_dir=out_dir,
        )

    assert excinfo.value.code != 0
    # Exactly 20 calls sent before stopping early!
    assert call_count == 20

    # predictions.jsonl and metrics.json must be written with valid=False
    pred_file = out_dir / "predictions.jsonl"
    metrics_file = out_dir / "metrics.json"
    assert pred_file.exists()
    assert metrics_file.exists()

    metrics_data = json.loads(metrics_file.read_text())
    assert metrics_data["valid"] is False
    assert metrics_data["live_calls"] == 20
    assert metrics_data["live_failures"] == 20
    assert metrics_data["live_failure_rate"] == 1.0
    assert metrics_data["live_failures_by_cause"]["insufficient_credits"] == 20


def test_failure_rate_exceeding_threshold_aborts_with_invalid_metrics(tmp_path: Path, monkeypatch):
    from src.models.schemas import DriverMotivationAssessment
    from src.services.jev_assessment_service import JevAssessmentResult

    call_index = 0

    class AlternatingService:
        async def assess(self, inp):
            nonlocal call_index
            call_index += 1
            if call_index <= 5:
                # 5 failures (HTTP 400 max_tokens_exceeded)
                return JevAssessmentResult(
                    category="ERR-01",
                    confidence=0.50,
                    priority="P2",
                    priority_tier=2,
                    priority_score=10,
                    reason_codes=["token_limit"],
                    forensic_brief="Token limit",
                    motivation_assessment=DriverMotivationAssessment(),
                    model_used="jev_calibrated_heuristic",
                    fallback_reason="max_tokens_exceeded",
                    http_status=400,
                )
            # Remaining 15 succeed
            return JevAssessmentResult(
                category="no_violation",
                confidence=0.95,
                priority="P2",
                priority_tier=2,
                priority_score=15,
                reason_codes=[],
                forensic_brief="Clean trip",
                motivation_assessment=DriverMotivationAssessment(),
                model_used="~typesafe/jev-latest",
                http_status=200,
            )

    monkeypatch.setattr(variants, "_cached_live_service", AlternatingService())

    in_file = tmp_path / "trips.jsonl"
    out_dir = tmp_path / "exp_out_threshold"
    rows = [
        {
            "trip_ref": f"trip-{i:03d}",
            "driver_id": f"driver-{i}",
            "label": "no_violation",
            "split": "validation",
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
        for i in range(20)
    ]
    in_file.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")

    # max_live_failure_rate is 0.02, but failure rate here is 5/20 = 0.25
    with pytest.raises(SystemExit) as excinfo:
        run_experiment.run_experiment_pipeline(
            exp_id="E_THRESHOLD",
            variant="baseline",
            in_path=in_file,
            split="validation",
            sample=20,
            live=True,
            concurrency=1,
            max_live_failure_rate=0.02,
            out_dir=out_dir,
        )

    assert excinfo.value.code != 0
    metrics_file = out_dir / "metrics.json"
    pred_file = out_dir / "predictions.jsonl"
    assert metrics_file.exists()
    assert pred_file.exists()

    metrics_data = json.loads(metrics_file.read_text())
    assert metrics_data["valid"] is False
    assert metrics_data["live_calls"] == 20
    assert metrics_data["live_failures"] == 5
    assert metrics_data["live_failure_rate"] == 0.25
    assert metrics_data["live_failures_by_cause"]["max_tokens_exceeded"] == 5


@pytest.mark.asyncio
async def test_jev_assessment_service_fallback_reason_classification(monkeypatch):
    import httpx

    from src.config import Settings
    from src.services.jev_assessment_service import JevAssessmentInput, JevAssessmentService

    settings = Settings(openrouter_api_key="sk-live-test-key")
    service = JevAssessmentService(settings=settings)
    inp = JevAssessmentInput(trip_data={"status": "completed"})

    # Test 400 -> max_tokens_exceeded
    async def mock_post_400(*args, **kwargs):
        return httpx.Response(400, text="Token limit exceeded", request=httpx.Request("POST", "http://test"))

    monkeypatch.setattr(httpx.AsyncClient, "post", mock_post_400)
    res_400 = await service.assess(inp)
    assert res_400.model_used == "jev_calibrated_heuristic"
    assert res_400.fallback_reason == "max_tokens_exceeded"
    assert res_400.http_status == 400

    # Test 402 -> insufficient_credits
    async def mock_post_402(*args, **kwargs):
        return httpx.Response(402, text="Insufficient credits", request=httpx.Request("POST", "http://test"))

    monkeypatch.setattr(httpx.AsyncClient, "post", mock_post_402)
    res_402 = await service.assess(inp)
    assert res_402.model_used == "jev_calibrated_heuristic"
    assert res_402.fallback_reason == "insufficient_credits"
    assert res_402.http_status == 402

    # Test 429 -> rate_limit
    async def mock_post_429(*args, **kwargs):
        return httpx.Response(429, text="Rate limit exceeded", request=httpx.Request("POST", "http://test"))

    monkeypatch.setattr(httpx.AsyncClient, "post", mock_post_429)
    res_429 = await service.assess(inp)
    assert res_429.model_used == "jev_calibrated_heuristic"
    assert res_429.fallback_reason == "rate_limit"
    assert res_429.http_status == 429

    # Test timeout -> timeout
    async def mock_post_timeout(*args, **kwargs):
        raise httpx.TimeoutException("Connection timed out")

    monkeypatch.setattr(httpx.AsyncClient, "post", mock_post_timeout)
    res_timeout = await service.assess(inp)
    assert res_timeout.model_used == "jev_calibrated_heuristic"
    assert res_timeout.fallback_reason == "timeout"
    assert res_timeout.http_status is None

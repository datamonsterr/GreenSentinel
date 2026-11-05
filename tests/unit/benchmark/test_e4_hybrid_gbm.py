"""Unit tests for E4 hybrid GBM + Jev classifier (Issue #513 / Epic #494)."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import pytest

from scripts.benchmark.experiments import variants
from scripts.benchmark.experiments.e4.features import FEATURE_NAMES, extract_features
from scripts.benchmark.experiments.e4.fusion import blend_log_linear, predict_with_abstention


@pytest.fixture
def sample_bundle() -> dict[str, Any]:
    return {
        "trip_ref": "trip-e4-test-01",
        "driver_id": "drv-001",
        "telemetry": [
            {
                "latitude": 10.770,
                "longitude": 106.690,
                "accuracy_m": 5,
                "speed_mps": 5.0,
                "occurred_at": "2026-10-01T00:00:00Z",
            },
            {
                "latitude": 10.772,
                "longitude": 106.692,
                "accuracy_m": 5,
                "speed_mps": 6.0,
                "occurred_at": "2026-10-01T00:01:00Z",
            },
        ],
        "pickup": [106.695, 10.775],
        "dropoff": [106.700, 10.780],
        "trip": {"fare_amount_vnd": 50000},
        "assignment": {},
        "driver_profile": {"rating": 4.8, "cancellation_rate": 0.02, "total_trips": 500},
        "driver_analytics": {"window_7d": {"trips": 20, "cancellations": 1}, "historical_cancellation_ratio": 0.02},
        "conversation": [{"sender": "passenger", "text": "Tôi đang đợi ở cổng A"}],
        "customer_report": {"complaint_text": "Tài xế đi đúng giờ"},
    }


def test_feature_extraction_structure(sample_bundle: dict[str, Any]):
    feat_dict, feat_vec = extract_features(sample_bundle)
    assert len(feat_vec) == len(FEATURE_NAMES)
    assert len(feat_dict) == len(FEATURE_NAMES)

    # Check key features present
    assert "teleport_jump_count" in feat_dict
    assert "speed_p95_kmh" in feat_dict
    assert "stationary_duration_s" in feat_dict
    assert "approach_ssd" in feat_dict
    assert "detour_ratio" in feat_dict

    # Check that no label proxy fields leaked into features
    for name in FEATURE_NAMES:
        assert "cancellation_actor" not in name
        assert "cancellation_reason" not in name
        assert "fare_amount" not in name
        assert "status" not in name
        assert "label" not in name


def test_feature_extraction_handles_empty_telemetry():
    empty_bundle = {"trip_ref": "trip-empty", "driver_id": "drv-002", "telemetry": []}
    feat_dict, feat_vec = extract_features(empty_bundle)
    assert len(feat_vec) == len(FEATURE_NAMES)
    assert not math.isnan(feat_dict["teleport_jump_count"])
    assert feat_dict["teleport_jump_count"] == 0.0


def test_blend_log_linear_probabilities():
    classes = ["no_violation", "ERR-01", "ERR-02", "ERR-03", "ERR-04", "ERR-05", "insufficient_evidence"]
    p_gbm = {c: 0.1 for c in classes}
    p_gbm["ERR-02"] = 0.4
    p_llm = {c: 0.1 for c in classes}
    p_llm["ERR-01"] = 0.4

    # w = 1.0 -> purely GBM
    fused_gbm = blend_log_linear(p_gbm, p_llm, weight_gbm=1.0, classes=classes)
    assert fused_gbm["ERR-02"] > fused_gbm["ERR-01"]
    assert pytest.approx(sum(fused_gbm.values()), abs=1e-5) == 1.0

    # w = 0.0 -> purely LLM
    fused_llm = blend_log_linear(p_gbm, p_llm, weight_gbm=0.0, classes=classes)
    assert fused_llm["ERR-01"] > fused_llm["ERR-02"]
    assert pytest.approx(sum(fused_llm.values()), abs=1e-5) == 1.0

    # w = 0.5 -> balanced
    fused_mid = blend_log_linear(p_gbm, p_llm, weight_gbm=0.5, classes=classes)
    assert pytest.approx(sum(fused_mid.values()), abs=1e-5) == 1.0
    assert fused_mid["ERR-02"] == pytest.approx(fused_mid["ERR-01"], abs=1e-3)


def test_predict_with_abstention():
    classes = ["no_violation", "ERR-01", "ERR-02", "ERR-03", "ERR-04", "ERR-05", "insufficient_evidence"]

    # Confident prediction
    probs_high = {c: 0.05 for c in classes}
    probs_high["ERR-02"] = 0.70
    cat, conf = predict_with_abstention(probs_high, threshold=0.40)
    assert cat == "ERR-02"
    assert conf == 0.70

    # Diffuse prediction -> abstain to insufficient_evidence
    probs_low = {c: 1.0 / 7.0 for c in classes}  # max prob is ~0.143
    cat_abs, conf_abs = predict_with_abstention(probs_low, threshold=0.35)
    assert cat_abs == "insufficient_evidence"
    assert conf_abs < 0.35


def test_variant_registered():
    from scripts.benchmark.experiments.variants import discover_variants

    discover_variants()
    assert "e4_hybrid_gbm" in variants.list_variants()
    var_fn = variants.get_variant("e4_hybrid_gbm")
    assert callable(var_fn)


def test_variant_execution_offline(sample_bundle: dict[str, Any]):
    from scripts.benchmark.experiments.variants import get_variant

    var_fn = get_variant("e4_hybrid_gbm")
    pred = var_fn(sample_bundle, live=False)

    assert "predicted_category" in pred
    assert "confidence" in pred
    assert "probabilities" in pred
    assert len(pred["probabilities"]) == 7
    assert "priority_tier" in pred
    assert "latency_ms" in pred
    assert "input_tokens" in pred
    assert pred["input_tokens"] > 0


def test_train_pipeline_smoke(tmp_path: Path, sample_bundle: dict[str, Any]):
    from scripts.benchmark.experiments.e4.train import train_e4_hybrid_model

    corpus_file = tmp_path / "trips.jsonl"
    classes = ["no_violation", "ERR-01", "ERR-02", "ERR-03", "ERR-04", "ERR-05", "insufficient_evidence"]
    lines = []
    # 28 trips with all 7 classes represented in both train and holdout, with varying speeds and metrics
    for i in range(28):
        b = json.loads(json.dumps(sample_bundle))
        b["trip_ref"] = f"trip-train-{i}"
        b["split"] = "train"
        b["label"] = classes[i % len(classes)]
        b["telemetry"][0]["speed_mps"] = float(i + 1)
        b["driver_profile"]["rating"] = 3.5 + (i % 15) * 0.1
        b["driver_profile"]["cancellation_rate"] = 0.01 * (i % 10)
        lines.append(json.dumps(b))
    corpus_file.write_text("\n".join(lines) + "\n", encoding="utf-8")

    out_model = tmp_path / "model.pkl"
    artifact = train_e4_hybrid_model(
        corpus_path=corpus_file,
        out_model_path=out_model,
        holdout_ratio=0.25,
        seed=20261017,
        max_workers=2,
    )

    assert out_model.exists()
    assert "model" in artifact
    assert "weight_gbm" in artifact
    assert "abstain_threshold" in artifact
    assert 0.0 <= artifact["weight_gbm"] <= 1.0
    assert 0.1 <= artifact["abstain_threshold"] <= 0.6
    assert len(artifact["feature_importances"]) > 0


@pytest.mark.asyncio
async def test_e4_live_heuristic_fallback_counts_as_live_failure(sample_bundle: dict[str, Any]):
    from scripts.benchmark.experiments import metrics
    from scripts.benchmark.experiments.variants import e4_hybrid_gbm
    from src.models.schemas import DriverMotivationAssessment
    from src.services.jev_assessment_service import JevAssessmentResult

    class FakeHeuristicFallbackService:
        async def assess(self, inp):
            return JevAssessmentResult(
                category="ERR-01",
                confidence=0.6,
                priority="P1",
                priority_tier=1,
                priority_score=75,
                reason_codes=["fallback_test"],
                forensic_brief="Heuristic fallback occurred",
                motivation_assessment=DriverMotivationAssessment(),
                model_used="jev_calibrated_heuristic",
                fallback_reason="max_tokens_exceeded",
                http_status=400,
                probabilities={"ERR-01": 0.6, "no_violation": 0.4},
            )

    e4_hybrid_gbm.reset_live_failures_count()

    # 1. Live mode with fallback service must report model_used, fallback_reason, and live_failed=True
    pred_live = await e4_hybrid_gbm.e4_assess_async(
        sample_bundle,
        live=True,
        service=FakeHeuristicFallbackService(),
    )
    assert pred_live["model_used"] == "jev_calibrated_heuristic"
    assert pred_live["fallback_reason"] == "max_tokens_exceeded"
    assert pred_live["http_status"] == 400
    assert pred_live["live_failed"] is True
    assert e4_hybrid_gbm.get_live_failures_count() == 1

    # 2. compute_live_failure_metrics must count this as a live failure
    suite_metrics = metrics.compute_live_failure_metrics([pred_live], live=True)
    assert suite_metrics["live_failures"] == 1
    assert suite_metrics["live_failure_rate"] == 1.0
    assert suite_metrics["live_failures_by_cause"]["max_tokens_exceeded"] == 1

    # 3. Synchronous runner e4_hybrid_gbm_variant with service must also report live failure
    e4_hybrid_gbm.reset_live_failures_count()
    pred_sync = e4_hybrid_gbm.e4_hybrid_gbm_variant(
        sample_bundle,
        live=True,
        service=FakeHeuristicFallbackService(),
    )
    assert pred_sync["model_used"] == "jev_calibrated_heuristic"
    assert pred_sync["live_failed"] is True
    assert e4_hybrid_gbm.get_live_failures_count() == 1

    # 4. Offline mode with the same service is not considered a live failure
    e4_hybrid_gbm.reset_live_failures_count()
    pred_offline = await e4_hybrid_gbm.e4_assess_async(
        sample_bundle,
        live=False,
        service=FakeHeuristicFallbackService(),
    )
    assert pred_offline["live_failed"] is False
    assert e4_hybrid_gbm.get_live_failures_count() == 0
    offline_metrics = metrics.compute_live_failure_metrics([pred_offline], live=False)
    assert offline_metrics["live_failures"] == 0

    # 5. Live mode with real model succeeds without failure
    class FakeSuccessService:
        async def assess(self, inp):
            return JevAssessmentResult(
                category="no_violation",
                confidence=0.90,
                priority="P2",
                priority_tier=2,
                priority_score=15,
                reason_codes=[],
                forensic_brief="Model decision",
                motivation_assessment=DriverMotivationAssessment(),
                model_used="~typesafe/jev-latest",
                http_status=200,
                probabilities={"no_violation": 0.90, "ERR-01": 0.10},
            )

    e4_hybrid_gbm.reset_live_failures_count()
    pred_ok = await e4_hybrid_gbm.e4_assess_async(
        sample_bundle,
        live=True,
        service=FakeSuccessService(),
    )
    assert pred_ok["model_used"] == "~typesafe/jev-latest"
    assert pred_ok["live_failed"] is False
    assert e4_hybrid_gbm.get_live_failures_count() == 0
    ok_metrics = metrics.compute_live_failure_metrics([pred_ok], live=True)
    assert ok_metrics["live_failures"] == 0

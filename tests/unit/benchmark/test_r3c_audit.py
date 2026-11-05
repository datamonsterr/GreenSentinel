"""Unit tests for R3C leakage audit (Issue #546 / Epic #494)."""

from __future__ import annotations

from typing import Any

import pytest

from scripts.benchmark.experiments.r3c.audit import (
    audit_features,
    evaluate_presence_model,
    format_audit_markdown,
)


@pytest.fixture
def mock_audit_data() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    train = [
        {
            "label": "no_violation",
            "telemetry": [
                {"latitude": 10.0, "longitude": 106.0, "occurred_at": "2026-10-01T00:00:00Z", "speed_mps": 5.0},
                {"latitude": 10.001, "longitude": 106.001, "occurred_at": "2026-10-01T00:00:30Z", "speed_mps": 5.0},
            ],
            "customer_report": None,
        },
        {
            "label": "ERR-01",
            "telemetry": [
                {"latitude": 10.0, "longitude": 106.0, "occurred_at": "2026-10-01T00:00:00Z", "speed_mps": 2.0},
                {"latitude": 10.005, "longitude": 106.005, "occurred_at": "2026-10-01T00:00:30Z", "speed_mps": 2.0},
            ],
            "customer_report": {"text": "Tài xế đi đường vòng"},
        },
        {
            "label": "no_violation",
            "telemetry": [
                {"latitude": 10.0, "longitude": 106.0, "occurred_at": "2026-10-01T00:00:00Z", "speed_mps": 4.0},
                {"latitude": 10.001, "longitude": 106.001, "occurred_at": "2026-10-01T00:00:30Z", "speed_mps": 4.0},
            ],
            "customer_report": None,
        },
        {
            "label": "ERR-01",
            "telemetry": [
                {"latitude": 10.0, "longitude": 106.0, "occurred_at": "2026-10-01T00:00:00Z", "speed_mps": 1.0},
                {"latitude": 10.004, "longitude": 106.004, "occurred_at": "2026-10-01T00:00:30Z", "speed_mps": 1.0},
            ],
            "customer_report": {"text": "Đi lung tung"},
        },
    ]
    val = [
        {
            "label": "no_violation",
            "telemetry": [
                {"latitude": 10.0, "longitude": 106.0, "occurred_at": "2026-10-01T00:00:00Z", "speed_mps": 5.0},
                {"latitude": 10.001, "longitude": 106.001, "occurred_at": "2026-10-01T00:00:30Z", "speed_mps": 5.0},
            ],
            "customer_report": None,
        },
        {
            "label": "ERR-01",
            "telemetry": [
                {"latitude": 10.0, "longitude": 106.0, "occurred_at": "2026-10-01T00:00:00Z", "speed_mps": 1.5},
                {"latitude": 10.006, "longitude": 106.006, "occurred_at": "2026-10-01T00:00:30Z", "speed_mps": 1.5},
            ],
            "customer_report": {"text": "Đi sai"},
        },
    ]
    return train, val


def test_audit_features_runs(mock_audit_data):
    train, val = mock_audit_data
    results = audit_features(train, val, max_depth=3, threshold=0.30)
    assert "features" in results
    assert len(results["features"]) > 0
    top_feat = results["features"][0]
    assert "feature" in top_feat
    assert "macro_f1" in top_feat
    assert "auc_ovr" in top_feat
    assert "flagged" in top_feat


def test_evaluate_presence_model(mock_audit_data):
    train, val = mock_audit_data
    pres_result = evaluate_presence_model(train, val)
    assert "macro_f1" in pres_result
    assert "fields" in pres_result
    assert isinstance(pres_result["fields"], list)


def test_format_audit_markdown(mock_audit_data):
    train, val = mock_audit_data
    audit_res = audit_features(train, val)
    pres_res = evaluate_presence_model(train, val)
    md = format_audit_markdown(audit_res, pres_res, e4_audit=None)
    assert "# Leak Audit and Baseline Comparison (R3C vs E4)" in md
    assert "Top 30 Features by Univariate Macro-F1" in md
    assert "Presence-Only Model Audit" in md

"""Unit tests for scripts/benchmark/realism_report.py."""

import json
import tempfile
from pathlib import Path

from scripts.benchmark.realism_report import (
    compute_ks_statistic,
    compute_metric_summary,
    compute_wasserstein_distance,
    generate_markdown_report,
    profile_trips_file,
)


def test_wasserstein_and_ks_metrics():
    u = [1.0, 2.0, 3.0, 4.0, 5.0]
    v = [2.0, 3.0, 4.0, 5.0, 6.0]
    w1 = compute_wasserstein_distance(u, v)
    assert abs(w1 - 1.0) < 1e-4

    ks = compute_ks_statistic(u, v)
    assert abs(ks - 0.2) < 1e-4


def test_metric_summary():
    data = [10.0, 20.0, 30.0, 40.0, 50.0]
    summary = compute_metric_summary(data)
    assert summary["count"] == 5
    assert summary["mean"] == 30.0
    assert summary["p50"] == 30.0
    assert summary["min"] == 10.0
    assert summary["max"] == 50.0


def test_realism_report_generation():
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        v1_file = tmp_path / "v1.jsonl"
        v2_file = tmp_path / "v2.jsonl"
        out_md = tmp_path / "REALISM_V2.md"

        # Create dummy v1 and v2 trip files
        dummy_v1 = {
            "trip_ref": "v1_001",
            "telemetry": [
                {
                    "occurred_at": "2026-10-15T08:00:00Z",
                    "latitude": 21.0,
                    "longitude": 105.8,
                    "speed_mps": 10.0,
                    "accuracy_m": 5.0,
                },
                {
                    "occurred_at": "2026-10-15T08:00:15Z",
                    "latitude": 21.001,
                    "longitude": 105.801,
                    "speed_mps": 10.0,
                    "accuracy_m": 5.0,
                },
            ],
            "route": {"distance_m": 150},
            "conversation": [{"text": "cuốc ảo quá", "role": "customer"}],
            "customer_report": "cuốc ảo này",
            "driver_objection": {"status": "present", "text": "Xe bị sự cố kỹ thuật"},
            "label": "no_violation",
            "split": "train",
        }
        dummy_v2 = {
            "trip_ref": "v2_001",
            "telemetry": [
                {
                    "occurred_at": "2026-10-15T08:00:00Z",
                    "latitude": 21.0285,
                    "longitude": 105.8542,
                    "speed_mps": 8.0,
                    "accuracy_m": 10.0,
                },
                {
                    "occurred_at": "2026-10-15T08:00:05Z",
                    "latitude": 21.0288,
                    "longitude": 105.8545,
                    "speed_mps": 8.2,
                    "accuracy_m": 9.5,
                },
            ],
            "route": {"distance_m": 140},
            "conversation": [{"text": "Chào anh em đang đến", "role": "driver"}],
            "customer_report": "Tôi đang đợi ở sảnh",
            "driver_objection": {"status": "present", "text": "Đường đông nghẽn xe"},
            "label": "no_violation",
            "split": "validation",
        }

        with v1_file.open("w", encoding="utf-8") as f:
            f.write(json.dumps(dummy_v1) + "\n")
        with v2_file.open("w", encoding="utf-8") as f:
            f.write(json.dumps(dummy_v2) + "\n")

        p_v1 = profile_trips_file(v1_file)
        p_v2 = profile_trips_file(v2_file)

        report_md = generate_markdown_report(p_v1, p_v2, out_md)
        assert out_md.exists()
        assert "Realism Report: releases_v1 vs releases_v2" in report_md
        assert "Ping Interval" in report_md
        assert "Speed Consistency" in report_md
        assert "Wasserstein" in report_md
        assert "Driver Objection Presence" in report_md


def test_shortcut_audit_depth3_decision_tree():
    from scripts.benchmark.realism_report import run_shortcut_audit

    dummy_trips = [
        {
            "trip_ref": f"tr_{i:03d}",
            "label": "no_violation" if i % 2 == 0 else "ERR-01",
            "split": "train" if i < 14 else "validation",
            "telemetry": [
                {"occurred_at": "2026-10-15T08:00:00Z", "latitude": 21.0, "longitude": 105.8, "speed_mps": 8.0},
                {"occurred_at": "2026-10-15T08:00:15Z", "latitude": 21.001, "longitude": 105.801, "speed_mps": 8.0},
            ],
            "customer_report": "report" if i % 3 == 0 else None,
            "driver_objection": {"status": "present", "text": "dispute"} if i % 4 == 0 else None,
            "conversation": [{"role": "driver", "text": "hello"}],
        }
        for i in range(20)
    ]

    audit = run_shortcut_audit(dummy_trips)
    assert "passed" in audit
    assert "top_15_features" in audit
    assert len(audit["top_15_features"]) == 15
    for feat in audit["top_15_features"]:
        assert "feature" in feat
        assert "macro_f1" in feat
        assert "status" in feat

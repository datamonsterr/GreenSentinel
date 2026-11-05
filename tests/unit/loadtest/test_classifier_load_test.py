"""Unit tests for the classifier load-test CLI tool (Slice W3).

Tests exercise:
- Server-Timing parsing
- Percentile math and aggregations
- Error accounting and status codes
- Batching logic (/assess/batch with batch_size > 1)
- Report rendering (JSON & Markdown)
- SHA256 verification and mismatch handling
- Mock HTTP transport execution across concurrency levels
- Auth resolution and credential masking (never log tokens)
- Macro-F1 accuracy verification
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from scripts.loadtest.classifier_load_test import (
    Sha256MismatchError,
    compute_macro_f1_score,
    compute_stats,
    format_markdown_report,
    load_or_fetch_trips,
    mask_token,
    parse_server_timing,
    resolve_auth_headers,
    run_load_test,
    verify_sha256,
)


def test_parse_server_timing_standard():
    header = "feat;dur=12.4, infer;dur=31.8, total;dur=44.2"
    timings = parse_server_timing(header)
    assert timings == {"feat": 12.4, "infer": 31.8, "total": 44.2}


def test_parse_server_timing_with_descriptions_and_whitespace():
    header = 'feat;dur=15.5;desc="Feature Ext",  infer;dur=28.1;desc="ONNX Stacker" , total;dur=43.6'
    timings = parse_server_timing(header)
    assert timings["feat"] == 15.5
    assert timings["infer"] == 28.1
    assert timings["total"] == 43.6


def test_parse_server_timing_missing_or_malformed():
    assert parse_server_timing(None) == {}
    assert parse_server_timing("") == {}
    assert parse_server_timing("feat;no_dur, infer;dur=not_a_float") == {}


def test_compute_stats_percentiles():
    # 100 values from 1 to 100
    values = [float(i) for i in range(1, 101)]
    stats = compute_stats(values)

    assert stats["count"] == 100.0
    assert stats["mean"] == pytest.approx(50.5, rel=1e-3)
    assert stats["p50"] == pytest.approx(50.5, rel=1e-2)
    assert stats["p90"] == pytest.approx(90.1, rel=1e-2)
    assert stats["p95"] == pytest.approx(95.05, rel=1e-2)
    assert stats["p99"] == pytest.approx(99.01, rel=1e-2)
    assert stats["max"] == 100.0


def test_compute_stats_empty():
    stats = compute_stats([])
    assert stats["count"] == 0.0
    assert stats["mean"] == 0.0
    assert stats["p50"] == 0.0
    assert stats["p95"] == 0.0
    assert stats["max"] == 0.0


def test_compute_macro_f1_score_accuracy():
    y_true = ["no_violation", "ERR-01", "ERR-02", "ERR-03"]
    y_pred = ["no_violation", "ERR-01", "ERR-02", "ERR-03"]
    f1 = compute_macro_f1_score(y_true, y_pred)
    assert f1 > 0.0

    # With mismatches
    y_pred_mismatch = ["ERR-01", "ERR-02", "ERR-03", "no_violation"]
    f1_mismatch = compute_macro_f1_score(y_true, y_pred_mismatch)
    assert f1_mismatch == 0.0


def test_auth_resolution_and_masking():
    # Test env var priority
    env_token = {"AUTH_TOKEN": "secret-preview-token"}
    headers, has_token = resolve_auth_headers(env_token)
    assert has_token is True
    assert headers["Authorization"] == "Bearer secret-preview-token"

    # Masking
    masked = mask_token(headers["Authorization"])
    assert "secret-preview-token" not in masked
    assert "Bearer ***" in masked

    # Missing auth
    empty_headers, empty_has_token = resolve_auth_headers({})
    assert empty_has_token is False
    assert "Authorization" not in empty_headers
    assert mask_token(None) == "[NONE]"


def test_sha256_verification_and_mismatch(tmp_path: Path):
    sample_file = tmp_path / "sample.txt"
    sample_file.write_text("hello world\n", encoding="utf-8")
    correct_sha = "a948904f2f0f479b8f8197694b30184b0d2ed1c1cd2a1ec0fb85d299a192a447"
    assert verify_sha256(sample_file, correct_sha) is True

    # Bad sha
    assert verify_sha256(sample_file, "wrong_hash") is False

    # Check sha verification failure in load_or_fetch_trips
    corrupt_file = tmp_path / "corrupt.jsonl"
    corrupt_file.write_text('{"bad": true}\n', encoding="utf-8")
    with pytest.raises(Sha256MismatchError):
        load_or_fetch_trips(trips_path=corrupt_file, expected_sha=correct_sha)


def test_load_or_fetch_trips_custom_file(tmp_path: Path):
    trips_file = tmp_path / "trips.jsonl"
    rows = [
        {"trip_id": "t1", "label": "ERR-01"},
        {"trip_id": "t2", "label": "no_violation"},
    ]
    with open(trips_file, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")

    loaded = load_or_fetch_trips(trips_path=trips_file)
    assert len(loaded) == 2
    assert loaded[0]["trip_id"] == "t1"


@pytest.mark.asyncio
async def test_run_load_test_with_mock_transport_single():
    # Setup mock transport for health, info, and assess
    def handler(request: httpx.Request) -> httpx.Response:
        url_path = request.url.path
        if url_path == "/health":
            return httpx.Response(200, json={"status": "ok"})
        if url_path == "/api/v1/classifier/info":
            return httpx.Response(
                200,
                json={
                    "model_version": "r3d-v2.1",
                    "artifact_shas": {"r3c": "abc", "r3f": "def"},
                    "load_time_ms": 120.0,
                },
            )
        if url_path == "/api/v1/classifier/assess":
            body = json.loads(request.content.decode("utf-8"))
            pred = "ERR-01" if body.get("label") == "ERR-01" else "no_violation"
            headers = {"Server-Timing": "feat;dur=10.0, infer;dur=25.0, total;dur=35.0"}
            return httpx.Response(
                200,
                headers=headers,
                json={
                    "category": pred,
                    "confidence": 0.95,
                    "model_version": "r3d-v2.1",
                    "artifact_sha": "d52e52f",
                    "inference_ms": 25.0,
                    "feature_ms": 10.0,
                    "assessment_source": "r3d_classifier",
                },
            )
        return httpx.Response(404, json={"detail": "Not found"})

    transport = httpx.MockTransport(handler)

    sample_trips = [{"trip_id": f"t_{i}", "label": "ERR-01" if i % 2 == 0 else "no_violation"} for i in range(10)]

    result = await run_load_test(
        base_url="https://mock.railway.app",
        trips=sample_trips,
        concurrency_levels=[1, 2],
        requests_per_level=6,
        warmup=2,
        batch_size=1,
        endpoint="/api/v1/classifier/assess",
        advisory=False,
        headers={"Authorization": "Bearer test-mock-token"},
        transport=transport,
    )

    assert result["health_baseline_ms"] >= 0.0
    assert result["cold_start"]["status_code"] == 200
    assert result["cold_start"]["server_timing"]["infer"] == 25.0
    assert "1" in result["levels"]
    assert "2" in result["levels"]

    level_1 = result["levels"]["1"]
    assert level_1["requests"] == 6
    assert level_1["error_rate"] == 0.0
    assert level_1["latency_client"]["p50"] > 0.0
    assert level_1["latency_infer"]["p95"] == 25.0
    assert level_1["throughput_req_sec"] > 0.0

    # Macro-F1 accuracy check
    assert result["accuracy"]["macro_f1"] is not None
    assert result["accuracy"]["macro_f1"] > 0.0


@pytest.mark.asyncio
async def test_run_load_test_error_accounting():
    request_counter = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal request_counter
        url_path = request.url.path
        if url_path == "/health":
            return httpx.Response(200, json={"status": "ok"})
        if url_path == "/api/v1/classifier/info":
            return httpx.Response(200, json={"status": "ok"})
        if url_path == "/api/v1/classifier/assess":
            request_counter += 1
            if request_counter % 3 == 0:
                return httpx.Response(503, json={"detail": "Service unavailable"})
            return httpx.Response(
                200,
                headers={"Server-Timing": "feat;dur=5.0, infer;dur=15.0, total;dur=20.0"},
                json={
                    "category": "no_violation",
                    "inference_ms": 15.0,
                    "feature_ms": 5.0,
                    "model_version": "r3d-v2.1",
                    "assessment_source": "r3d_classifier",
                },
            )
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    sample_trips = [{"trip_id": f"t_{i}"} for i in range(6)]

    result = await run_load_test(
        base_url="https://mock.railway.app",
        trips=sample_trips,
        concurrency_levels=[1],
        requests_per_level=6,
        warmup=0,
        batch_size=1,
        transport=transport,
    )

    level_1 = result["levels"]["1"]
    assert level_1["requests"] == 6
    assert level_1["errors"] > 0
    assert level_1["error_rate"] > 0.0
    assert 503 in level_1["status_counts"]


@pytest.mark.asyncio
async def test_run_load_test_batching():
    received_batch_sizes = []

    def handler(request: httpx.Request) -> httpx.Response:
        url_path = request.url.path
        if url_path == "/health" or url_path == "/api/v1/classifier/info":
            return httpx.Response(200, json={"status": "ok"})
        if url_path == "/api/v1/classifier/assess/batch":
            payload = json.loads(request.content.decode("utf-8"))
            items = payload if isinstance(payload, list) else payload.get("trips", [])
            received_batch_sizes.append(len(items))
            headers = {"Server-Timing": "feat;dur=20.0, infer;dur=40.0, total;dur=60.0"}
            results = [
                {
                    "category": "no_violation",
                    "inference_ms": 40.0,
                    "feature_ms": 20.0,
                    "model_version": "r3d-v2.1",
                    "assessment_source": "r3d_classifier",
                }
                for _ in items
            ]
            return httpx.Response(200, headers=headers, json=results)
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    sample_trips = [{"trip_id": f"t_{i}"} for i in range(12)]

    result = await run_load_test(
        base_url="https://mock.railway.app",
        trips=sample_trips,
        concurrency_levels=[1],
        requests_per_level=4,
        warmup=0,
        batch_size=3,
        transport=transport,
    )

    assert result["config"]["batch_size"] == 3
    assert all(size == 3 for size in received_batch_sizes)
    level_1 = result["levels"]["1"]
    assert level_1["requests"] == 4
    assert level_1["error_rate"] == 0.0


@pytest.mark.asyncio
async def test_run_load_test_advisory_measurement():
    def handler(request: httpx.Request) -> httpx.Response:
        url_path = request.url.path
        if url_path in ("/health", "/api/v1/classifier/info"):
            return httpx.Response(200, json={"status": "ok"})
        if url_path == "/api/v1/classifier/assess":
            assert "advisory=true" in str(request.url)
            headers = {"Server-Timing": "feat;dur=10.0, infer;dur=25.0, adv;dur=450.0, total;dur=485.0"}
            return httpx.Response(
                200,
                headers=headers,
                json={
                    "category": "ERR-01",
                    "confidence": 0.9,
                    "inference_ms": 25.0,
                    "feature_ms": 10.0,
                    "model_version": "r3d-v2.1",
                    "assessment_source": "r3d_classifier",
                    "llm_latency_ms": 450.0,
                    "advisory": {
                        "llm_category": "ERR-01",
                        "llm_latency_ms": 450.0,
                    },
                },
            )
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    sample_trips = [{"trip_id": "t1"}]

    result = await run_load_test(
        base_url="https://mock.railway.app",
        trips=sample_trips,
        concurrency_levels=[1],
        requests_per_level=2,
        warmup=0,
        batch_size=1,
        advisory=True,
        transport=transport,
    )

    level_1 = result["levels"]["1"]
    assert "latency_advisory" in level_1
    assert level_1["latency_advisory"]["p50"] == 450.0


def test_format_markdown_report_rendering():
    dummy_result = {
        "config": {
            "base_url": "https://p063-preview.up.railway.app",
            "endpoint": "/api/v1/classifier/assess",
            "concurrency_levels": [1, 4, 8, 16],
            "requests_per_level": 300,
            "warmup": 20,
            "batch_size": 1,
            "advisory_enabled": False,
            "token_configured": True,
        },
        "health_baseline_ms": 45.2,
        "info": {"model_version": "r3d-v2.1"},
        "cold_start": {
            "client_latency_ms": 210.5,
            "inference_ms": 38.2,
            "feature_ms": 14.1,
            "status_code": 200,
        },
        "levels": {
            "8": {
                "concurrency": 8,
                "requests": 300,
                "errors": 0,
                "error_rate": 0.0,
                "wall_time_sec": 4.5,
                "throughput_req_sec": 66.7,
                "status_counts": {200: 300},
                "latency_client": {"mean": 115.0, "p50": 110.0, "p90": 140.0, "p95": 160.0, "p99": 220.0, "max": 280.0},
                "latency_infer": {"mean": 32.0, "p50": 30.0, "p90": 42.0, "p95": 45.0, "p99": 49.0, "max": 52.0},
                "latency_feat": {"mean": 12.0, "p50": 11.0, "p90": 15.0, "p95": 16.0, "p99": 18.0, "max": 20.0},
            }
        },
        "accuracy": {
            "macro_f1": 0.8688,
            "expected_baseline": 0.8688,
            "labels_available": True,
            "match": True,
        },
        "acceptance": {
            "infer_p95_pass": True,
            "api_p95_pass": True,
            "error_rate_pass": True,
            "overall_pass": True,
        },
    }

    report_md = format_markdown_report(dummy_result)
    assert "# Classifier Load Test Report" in report_md
    assert "https://p063-preview.up.railway.app" in report_md
    assert "Health baseline" in report_md
    assert "45.2 ms" in report_md
    assert "Cold-start" in report_md
    assert "Concurrency 8" in report_md
    assert "PASS" in report_md
    assert "0.8688" in report_md
    assert "Bearer" not in report_md  # Secret hygiene


def test_parse_args_defaults_and_custom():
    from scripts.loadtest.classifier_load_test import parse_args

    # Defaults
    args_default = parse_args([])
    assert args_default.base_url == "http://localhost:8000"
    assert args_default.concurrency == "1,4,8,16"
    assert args_default.requests == 300
    assert args_default.warmup == 20
    assert args_default.endpoint == "/api/v1/classifier/assess"
    assert args_default.batch_size == 1
    assert args_default.advisory is False
    assert args_default.out is None
    assert args_default.report is None

    # Custom
    args_custom = parse_args(
        [
            "--base-url",
            "https://preview.railway.app",
            "--concurrency",
            "2,4",
            "--requests",
            "50",
            "--warmup",
            "5",
            "--endpoint",
            "/api/v1/custom/assess",
            "--batch-size",
            "8",
            "--advisory",
            "--out",
            "results.json",
            "--report",
            "report.md",
        ]
    )
    assert args_custom.base_url == "https://preview.railway.app"
    assert args_custom.concurrency == "2,4"
    assert args_custom.requests == 50
    assert args_custom.warmup == 5
    assert args_custom.endpoint == "/api/v1/custom/assess"
    assert args_custom.batch_size == 8
    assert args_custom.advisory is True
    assert args_custom.out == "results.json"
    assert args_custom.report == "report.md"


def test_verify_sha256_nonexistent(tmp_path: Path):
    nonexistent = tmp_path / "does_not_exist.txt"
    assert verify_sha256(nonexistent, "any_sha") is False
    with pytest.raises(FileNotFoundError):
        load_or_fetch_trips(trips_path=nonexistent)


@pytest.mark.asyncio
async def test_main_async_with_out_and_report_mock(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from scripts.loadtest.classifier_load_test import main_async, parse_args

    trips_file = tmp_path / "trips.jsonl"
    trips_file.write_text('{"trip_id": "t1", "label": "ERR-01"}\n{"trip_id": "t2", "label": "no_violation"}\n')

    out_file = tmp_path / "out.json"
    report_file = tmp_path / "report.md"

    def handler(request: httpx.Request) -> httpx.Response:
        url_path = request.url.path
        if url_path == "/health" or url_path == "/api/v1/classifier/info":
            return httpx.Response(200, json={"status": "ok"})
        if url_path == "/api/v1/classifier/assess":
            return httpx.Response(
                200,
                headers={"Server-Timing": "feat;dur=5.0, infer;dur=15.0, total;dur=20.0"},
                json={
                    "category": "ERR-01",
                    "inference_ms": 15.0,
                    "feature_ms": 5.0,
                    "model_version": "r3d-v2.1",
                    "assessment_source": "r3d_classifier",
                },
            )
        return httpx.Response(404)

    # Mock AsyncClient inside classifier_load_test to use our MockTransport
    orig_client = httpx.AsyncClient

    def mock_async_client(**kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return orig_client(**kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", mock_async_client)
    monkeypatch.setenv("AUTH_TOKEN", "mock-token-123")

    args = parse_args(
        [
            "--base-url",
            "https://mock.railway.app",
            "--trips",
            str(trips_file),
            "--concurrency",
            "1",
            "--requests",
            "2",
            "--warmup",
            "1",
            "--out",
            str(out_file),
            "--report",
            str(report_file),
        ]
    )

    exit_code = await main_async(args)
    assert exit_code == 0
    assert out_file.exists()
    assert report_file.exists()

    out_data = json.loads(out_file.read_text())
    assert out_data["acceptance"]["overall_pass"] is True
    assert "mock-token-123" not in report_file.read_text()
    assert "mock-token-123" not in json.dumps(out_data)

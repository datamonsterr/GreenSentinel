"""Latency and inference-time load-test CLI for the classifier API.

Measures client end-to-end latency, Server-Timing headers, response fields,
throughput, error rates, cold-start, network baseline, and macro-F1 accuracy
across configurable concurrency levels.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sys
import time
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import httpx
import numpy as np

try:
    from scripts.benchmark.experiments.metrics import compute_macro_f1
except ImportError:
    # Fallback if executed from outside project root
    compute_macro_f1 = None  # type: ignore[assignment]

DEV300_SHA256 = "cd008ee10b22520fbd71598d1718d06cf9ba9a9f3af38ca8736a11019a9a9ed9"
DEFAULT_HF_DATASET_URL = (
    "https://huggingface.co/datasets/datamonsterr/green-sentinel-synthesized-trips/resolve/main/releases_v2.1/dev300.jsonl"
)


class Sha256MismatchError(ValueError):
    """Raised when SHA256 checksum verification fails."""


def parse_server_timing(header_value: str | None) -> dict[str, float]:
    """Parse Server-Timing header into a dictionary of metric_name -> duration in ms.

    Example: 'feat;dur=12.4, infer;dur=31.8, total;dur=44.2' ->
             {'feat': 12.4, 'infer': 31.8, 'total': 44.2}
    """
    if not header_value:
        return {}
    results: dict[str, float] = {}
    for entry in header_value.split(","):
        entry = entry.strip()
        if not entry:
            continue
        parts = entry.split(";")
        metric_name = parts[0].strip()
        for param in parts[1:]:
            param = param.strip()
            if param.startswith("dur="):
                val_str = param[4:].strip().strip("\"'")
                try:
                    results[metric_name] = float(val_str)
                except ValueError:
                    pass
    return results


def compute_stats(values: list[float]) -> dict[str, float]:
    """Compute summary statistics (count, mean, p50, p90, p95, p99, max)."""
    if not values:
        return {
            "count": 0.0,
            "mean": 0.0,
            "p50": 0.0,
            "p90": 0.0,
            "p95": 0.0,
            "p99": 0.0,
            "max": 0.0,
        }
    arr = np.array(values, dtype=float)
    return {
        "count": float(len(arr)),
        "mean": round(float(np.mean(arr)), 2),
        "p50": round(float(np.percentile(arr, 50)), 2),
        "p90": round(float(np.percentile(arr, 90)), 2),
        "p95": round(float(np.percentile(arr, 95)), 2),
        "p99": round(float(np.percentile(arr, 99)), 2),
        "max": round(float(np.max(arr)), 2),
    }


def compute_macro_f1_score(y_true: list[str], y_pred: list[str]) -> float:
    """Compute macro-F1 score over standard 7 classes."""
    if compute_macro_f1 is not None:
        return float(compute_macro_f1(y_true, y_pred))

    # In-memory fallback if benchmark metrics module unavailable
    classes = [
        "no_violation",
        "ERR-01",
        "ERR-02",
        "ERR-03",
        "ERR-04",
        "ERR-05",
        "insufficient_evidence",
    ]
    f1s = []
    for cls in classes:
        tp = sum(1 for yt, yp in zip(y_true, y_pred, strict=False) if yt == cls and yp == cls)
        fp = sum(1 for yt, yp in zip(y_true, y_pred, strict=False) if yt != cls and yp == cls)
        fn = sum(1 for yt, yp in zip(y_true, y_pred, strict=False) if yt == cls and yp != cls)
        prec = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        rec = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = (2 * prec * rec) / (prec + rec) if (prec + rec) > 0 else 0.0
        f1s.append(f1)
    return float(np.mean(f1s))


def verify_sha256(path: Path | str, expected_sha: str) -> bool:
    """Verify SHA256 checksum of a file."""
    p = Path(path)
    if not p.exists() or not p.is_file():
        return False
    h = hashlib.sha256()
    with open(p, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest().lower() == expected_sha.lower()


def mask_token(token: str | None) -> str:
    """Mask credential strings for logging and reporting."""
    if not token:
        return "[NONE]"
    if token.startswith("Bearer "):
        return "Bearer ***"
    return "***"


def resolve_auth_headers(env: dict[str, str] | None = None) -> tuple[dict[str, str], bool]:
    """Discover and resolve authentication headers from environment variables.

    Never logs or exposes the underlying secret token.
    """
    e = env if env is not None else os.environ
    token_keys = [
        "CLASSIFIER_LOAD_TEST_TOKEN",
        "AUTH_TOKEN",
        "CLERK_SESSION_TOKEN",
        "E2E_ANALYST_TOKEN",
        "BEARER_TOKEN",
    ]
    headers: dict[str, str] = {}
    found_token = False

    for k in token_keys:
        val = e.get(k)
        if val and val.strip():
            token = val.strip()
            if not token.startswith("Bearer "):
                token = f"Bearer {token}"
            headers["Authorization"] = token
            found_token = True
            break

    # Optional local dev / test role headers if APP_ENV=test
    if e.get("APP_ENV") == "test" or e.get("TEST_AUTH_ENABLED") == "true":
        if "X_ROLE" in e:
            headers["x-role"] = e["X_ROLE"]
        if "X_PRINCIPAL_ID" in e:
            headers["x-principal-id"] = e["X_PRINCIPAL_ID"]

    return headers, found_token


def load_or_fetch_trips(
    trips_path: str | Path | None = None,
    expected_sha: str | None = None,
    cache_dir: str | Path | None = None,
    download_if_missing: bool = True,
) -> list[dict[str, Any]]:
    """Load trips JSONL file, verifying SHA256 checksum and caching if fetched."""
    target_path: Path | None = None

    if trips_path:
        target_path = Path(trips_path)
        if not target_path.exists():
            raise FileNotFoundError(f"Specified trips file not found: {trips_path}")
        if expected_sha and not verify_sha256(target_path, expected_sha):
            raise Sha256MismatchError(f"Checksum mismatch for {trips_path}: expected SHA256 {expected_sha}")
    else:
        sha_to_check = expected_sha or DEV300_SHA256
        # Check standard cache directory
        c_dir = Path(cache_dir) if cache_dir else Path.home() / ".cache" / "greensentinel" / "releases_v2.1"
        c_dir.mkdir(parents=True, exist_ok=True)
        cached_file = c_dir / "dev300.jsonl"

        # Also check local path on host if available
        host_local = Path("/home/dat/releases_v2_1/dev300.jsonl")
        if not cached_file.exists() and host_local.exists():
            if verify_sha256(host_local, sha_to_check):
                cached_file.write_bytes(host_local.read_bytes())

        if cached_file.exists():
            if not verify_sha256(cached_file, sha_to_check):
                raise Sha256MismatchError(f"Cached file {cached_file} SHA256 mismatch. Remove or re-download.")
            target_path = cached_file
        elif download_if_missing:
            # Download from Hugging Face
            with httpx.Client(timeout=60.0, follow_redirects=True) as client:
                resp = client.get(DEFAULT_HF_DATASET_URL)
                resp.raise_for_status()
                cached_file.write_bytes(resp.content)

            if not verify_sha256(cached_file, sha_to_check):
                cached_file.unlink(missing_ok=True)
                raise Sha256MismatchError(f"Downloaded file from {DEFAULT_HF_DATASET_URL} failed SHA256 verification.")
            target_path = cached_file
        else:
            raise FileNotFoundError("Default dev300.jsonl not found in cache and download disabled.")

    trips: list[dict[str, Any]] = []
    with open(target_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                trips.append(json.loads(line))
    return trips


async def _execute_single_request(
    client: httpx.AsyncClient,
    url: str,
    payload: Any,
    params: dict[str, Any] | None,
    headers: dict[str, str],
) -> dict[str, Any]:
    t0 = time.perf_counter()
    status_code = 0
    server_timing: dict[str, float] = {}
    inference_ms: float | None = None
    feature_ms: float | None = None
    advisory_ms: float | None = None
    category: str | None = None
    model_version: str | None = None
    assessment_source: str | None = None

    try:
        resp = await client.post(url, json=payload, params=params, headers=headers)
        status_code = resp.status_code
        server_timing = parse_server_timing(resp.headers.get("server-timing"))

        if resp.status_code == 200:
            try:
                body = resp.json()
                if isinstance(body, dict):
                    category = body.get("category")
                    inference_ms = body.get("inference_ms")
                    feature_ms = body.get("feature_ms")
                    model_version = body.get("model_version")
                    assessment_source = body.get("assessment_source")

                    # Check advisory timing
                    adv = body.get("advisory")
                    if isinstance(adv, dict) and "llm_latency_ms" in adv:
                        advisory_ms = float(adv["llm_latency_ms"])
                    elif "llm_latency_ms" in body:
                        advisory_ms = float(body["llm_latency_ms"])
                    elif "advisory_latency_ms" in body:
                        advisory_ms = float(body["advisory_latency_ms"])
                    elif "adv" in server_timing:
                        advisory_ms = server_timing["adv"]

                elif isinstance(body, list) and body:
                    # Batch response format: list of results
                    first = body[0]
                    category = first.get("category")
                    inference_ms = first.get("inference_ms")
                    feature_ms = first.get("feature_ms")
                    model_version = first.get("model_version")
                    assessment_source = first.get("assessment_source")
            except Exception:
                pass
    except Exception:
        status_code = 599  # Client-side / connection failure
    finally:
        t1 = time.perf_counter()

    client_latency_ms = (t1 - t0) * 1000.0

    return {
        "client_latency_ms": client_latency_ms,
        "status_code": status_code,
        "server_timing": server_timing,
        "inference_ms": inference_ms,
        "feature_ms": feature_ms,
        "advisory_ms": advisory_ms,
        "category": category,
        "model_version": model_version,
        "assessment_source": assessment_source,
    }


async def run_load_test(
    base_url: str,
    trips: list[dict[str, Any]],
    concurrency_levels: list[int] | None = None,
    requests_per_level: int = 300,
    warmup: int = 20,
    batch_size: int = 1,
    endpoint: str = "/api/v1/classifier/assess",
    advisory: bool = False,
    headers: dict[str, str] | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> dict[str, Any]:
    """Execute load test against classifier service across concurrency levels."""
    levels = concurrency_levels or [1, 4, 8, 16]
    req_headers = dict(headers or {})
    params = {"advisory": "true"} if advisory else None

    # Resolve assess endpoint (single vs batch)
    if batch_size > 1:
        if endpoint.endswith("/assess"):
            assess_url = urljoin(base_url.rstrip("/") + "/", endpoint.lstrip("/") + "/batch")
        else:
            assess_url = urljoin(base_url.rstrip("/") + "/", "api/v1/classifier/assess/batch")
    else:
        assess_url = urljoin(base_url.rstrip("/") + "/", endpoint.lstrip("/"))

    health_url = urljoin(base_url.rstrip("/") + "/", "health")
    info_url = urljoin(base_url.rstrip("/") + "/", "api/v1/classifier/info")

    async with httpx.AsyncClient(transport=transport, timeout=120.0, follow_redirects=True) as client:
        # 1. Health baseline
        t0_health = time.perf_counter()
        await client.get(health_url)
        t1_health = time.perf_counter()
        health_baseline_ms = (t1_health - t0_health) * 1000.0

        # 2. Classifier info probe
        info_data: dict[str, Any] = {}
        try:
            info_resp = await client.get(info_url, headers=req_headers)
            if info_resp.status_code == 200:
                info_data = info_resp.json()
        except Exception:
            pass

        # 3. Cold-start measurement (first request after info)
        if batch_size > 1:
            first_payload = [trips[k % len(trips)] for k in range(batch_size)] if trips else [{"trip_id": "cold_start"}]
        else:
            first_payload = trips[0] if trips else {"trip_id": "cold_start"}
        cold_start = await _execute_single_request(client, assess_url, first_payload, params, req_headers)

        # 4. Warmup
        if warmup > 0:
            for i in range(warmup):
                trip = trips[i % len(trips)] if trips else {}
                payload = [trip] if batch_size > 1 else trip
                await _execute_single_request(client, assess_url, payload, params, req_headers)

        # 5. Concurrency levels
        level_results: dict[str, Any] = {}
        all_predictions: list[str] = []
        all_ground_truths: list[str] = []

        for c in levels:
            sem = asyncio.Semaphore(c)
            level_requests: list[dict[str, Any]] = []

            async def worker(idx: int) -> None:
                async with sem:
                    if batch_size > 1:
                        start_idx = (idx * batch_size) % len(trips)
                        chunk = [trips[(start_idx + k) % len(trips)] for k in range(batch_size)]
                        req_payload = chunk
                        first_item = chunk[0]
                    else:
                        req_payload = trips[idx % len(trips)]
                        first_item = req_payload

                    res = await _execute_single_request(client, assess_url, req_payload, params, req_headers)
                    level_requests.append(res)

                    # Accumulate for accuracy sanity if label exists
                    gt_label = first_item.get("label") or first_item.get("ground_truth")
                    if res["category"] and gt_label:
                        all_predictions.append(res["category"])
                        all_ground_truths.append(gt_label)

            t_start = time.perf_counter()
            tasks = [worker(i) for i in range(requests_per_level)]
            await asyncio.gather(*tasks)
            t_end = time.perf_counter()

            wall_time = max(t_end - t_start, 0.0001)
            total_reqs = len(level_requests)
            successful_reqs = sum(1 for r in level_requests if 200 <= r["status_code"] < 300)
            errors = total_reqs - successful_reqs
            error_rate = errors / total_reqs if total_reqs > 0 else 0.0

            status_counts: dict[int, int] = {}
            for r in level_requests:
                status_counts[r["status_code"]] = status_counts.get(r["status_code"], 0) + 1

            client_latencies = [r["client_latency_ms"] for r in level_requests]
            infer_latencies = [
                r["server_timing"].get("infer") or (r["inference_ms"] if r["inference_ms"] is not None else 0.0)
                for r in level_requests
                if 200 <= r["status_code"] < 300
            ]
            feat_latencies = [
                r["server_timing"].get("feat") or (r["feature_ms"] if r["feature_ms"] is not None else 0.0)
                for r in level_requests
                if 200 <= r["status_code"] < 300
            ]
            total_server_latencies = [
                r["server_timing"].get("total", 0.0) for r in level_requests if 200 <= r["status_code"] < 300
            ]

            level_stat: dict[str, Any] = {
                "concurrency": c,
                "requests": total_reqs,
                "successful": successful_reqs,
                "errors": errors,
                "error_rate": round(error_rate, 4),
                "wall_time_sec": round(wall_time, 2),
                "throughput_req_sec": round(total_reqs / wall_time, 2),
                "status_counts": status_counts,
                "latency_client": compute_stats(client_latencies),
                "latency_infer": compute_stats(infer_latencies),
                "latency_feat": compute_stats(feat_latencies),
                "latency_server_total": compute_stats(total_server_latencies),
            }

            if advisory:
                adv_latencies = [
                    r["advisory_ms"]
                    for r in level_requests
                    if r["advisory_ms"] is not None and 200 <= r["status_code"] < 300
                ]
                level_stat["latency_advisory"] = compute_stats(adv_latencies)

            level_results[str(c)] = level_stat

    # Accuracy sanity check
    macro_f1: float | None = None
    labels_available = bool(all_ground_truths and all_predictions)
    if labels_available:
        macro_f1 = round(compute_macro_f1_score(all_ground_truths, all_predictions), 4)

    # Acceptance evaluation (§8 PROD_DESIGN.md: infer p95 <= 50ms, API p95 <= 300ms at C=8, error rate 0)
    c8_stats = level_results.get("8") or (level_results[str(levels[0])] if levels else {})
    api_p95 = c8_stats.get("latency_client", {}).get("p95", 0.0)
    infer_p95 = c8_stats.get("latency_infer", {}).get("p95", 0.0)
    err_rate = c8_stats.get("error_rate", 0.0)

    infer_p95_pass = infer_p95 <= 50.0
    api_p95_pass = api_p95 <= 300.0
    error_rate_pass = err_rate == 0.0
    overall_pass = infer_p95_pass and api_p95_pass and error_rate_pass

    return {
        "config": {
            "base_url": base_url,
            "endpoint": endpoint,
            "concurrency_levels": levels,
            "requests_per_level": requests_per_level,
            "warmup": warmup,
            "batch_size": batch_size,
            "advisory_enabled": advisory,
            "token_configured": bool(req_headers.get("Authorization")),
        },
        "health_baseline_ms": round(health_baseline_ms, 2),
        "info": info_data,
        "cold_start": cold_start,
        "levels": level_results,
        "accuracy": {
            "macro_f1": macro_f1,
            "expected_baseline": 0.8688,
            "labels_available": labels_available,
            "match": (abs(macro_f1 - 0.8688) <= 0.005) if macro_f1 is not None else None,
        },
        "acceptance": {
            "infer_p95_pass": infer_p95_pass,
            "api_p95_pass": api_p95_pass,
            "error_rate_pass": error_rate_pass,
            "overall_pass": overall_pass,
        },
    }


def format_markdown_report(result: dict[str, Any]) -> str:
    """Render comprehensive Markdown summary of load-test findings."""
    cfg = result["config"]
    acc = result.get("acceptance", {})
    accuracy = result.get("accuracy", {})
    levels = result.get("levels", {})

    status_tag = "PASS" if acc.get("overall_pass") else "FAIL"

    lines: list[str] = [
        "# Classifier Load Test Report",
        "",
        f"**Status:** `{status_tag}`",
        f"- **Base URL:** `{cfg.get('base_url')}`",
        f"- **Endpoint:** `{cfg.get('endpoint')}`",
        f"- **Batch Size:** `{cfg.get('batch_size')}`",
        f"- **Advisory Enabled:** `{cfg.get('advisory_enabled')}`",
        f"- **Auth Token Configured:** `{'Yes' if cfg.get('token_configured') else 'No'}`",
        "",
        "## Baseline Measurements",
        f"- **Health baseline (GET /health):** {result.get('health_baseline_ms', 0.0)} ms",
    ]

    cs = result.get("cold_start", {})
    lines.extend(
        [
            f"- **Cold-start client latency:** {round(cs.get('client_latency_ms', 0.0), 2)} ms",
            f"- **Cold-start inference time:** {round(cs.get('inference_ms') or 0.0, 2)} ms",
            f"- **Cold-start feature time:** {round(cs.get('feature_ms') or 0.0, 2)} ms",
            f"- **Cold-start HTTP status:** {cs.get('status_code')}",
            "",
            "## Concurrency Levels Summary",
            "",
            "| Concurrency | Requests | Req/s | Client p50 (ms) | Client p90 (ms) | Client p95 (ms) | Client p99 (ms) | Client Max (ms) | Infer p95 (ms) | Feat p95 (ms) | Errors |",
            "|---|---|---|---|---|---|---|---|---|---|---|",
        ]
    )

    for c_key, stat in levels.items():
        lc = stat.get("latency_client", {})
        li = stat.get("latency_infer", {})
        lf = stat.get("latency_feat", {})
        lines.append(
            f"| Concurrency {c_key} | {stat.get('requests')} | {stat.get('throughput_req_sec')} | "
            f"{lc.get('p50')} | {lc.get('p90')} | {lc.get('p95')} | {lc.get('p99')} | {lc.get('max')} | "
            f"{li.get('p95')} | {lf.get('p95')} | {stat.get('errors')} ({stat.get('error_rate', 0) * 100:.1f}%) |"
        )

    lines.extend(["", "## Accuracy Sanity Check"])
    if accuracy.get("labels_available"):
        lines.extend(
            [
                f"- **Served Macro-F1:** `{accuracy.get('macro_f1')}`",
                f"- **Expected Offline R3D Baseline:** `{accuracy.get('expected_baseline')}`",
                f"- **Parity Status:** `{'MATCH' if accuracy.get('match') else 'MISMATCH'}`",
            ]
        )
    else:
        lines.append("- *No ground-truth labels provided in request trips; accuracy check skipped.*")

    lines.extend(
        [
            "",
            "## Acceptance Criteria (§8 PROD_DESIGN.md)",
            f"- **Classifier inference p95 <= 50 ms:** `{'PASS' if acc.get('infer_p95_pass') else 'FAIL'}`",
            f"- **Single-trip API p95 <= 300 ms at Concurrency 8:** `{'PASS' if acc.get('api_p95_pass') else 'FAIL'}`",
            f"- **Zero error rate (status 200 OK):** `{'PASS' if acc.get('error_rate_pass') else 'FAIL'}`",
            f"- **Overall Acceptance:** `{'PASS' if acc.get('overall_pass') else 'FAIL'}`",
            "",
        ]
    )

    return "\n".join(lines)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run latency and inference-time load tests on the classifier service.")
    parser.add_argument(
        "--base-url",
        default="http://localhost:8000",
        help="Base service URL (e.g. https://greensentinel-preview.up.railway.app)",
    )
    parser.add_argument(
        "--trips",
        default=None,
        help="Path to trips JSONL file (default caches/downloads dev300.jsonl from Hugging Face)",
    )
    parser.add_argument(
        "--concurrency",
        default="1,4,8,16",
        help="Comma-separated concurrency levels to test (default: 1,4,8,16)",
    )
    parser.add_argument(
        "--requests",
        type=int,
        default=300,
        help="Number of requests per concurrency level (default: 300)",
    )
    parser.add_argument(
        "--warmup",
        type=int,
        default=20,
        help="Number of warmup requests prior to benchmark (default: 20)",
    )
    parser.add_argument(
        "--endpoint",
        default="/api/v1/classifier/assess",
        help="Classifier assessment endpoint (default: /api/v1/classifier/assess)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=1,
        help="Batch size per request; uses /assess/batch when > 1 (default: 1)",
    )
    parser.add_argument(
        "--advisory",
        action="store_true",
        help="Include and measure optional advisory LLM latency separately",
    )
    parser.add_argument(
        "--out",
        help="Path to save output JSON metrics file",
    )
    parser.add_argument(
        "--report",
        help="Path to save output Markdown report file",
    )
    return parser.parse_args(argv)


async def main_async(args: argparse.Namespace) -> int:
    # Resolve auth headers from env
    headers, has_token = resolve_auth_headers()
    auth_header_repr = mask_token(headers.get("Authorization"))
    print(f"[load-test] Base URL: {args.base_url}")
    print(f"[load-test] Auth Header: {auth_header_repr}")
    print(f"[load-test] Endpoint: {args.endpoint} (batch-size: {args.batch_size})")

    # Parse concurrency levels
    concurrency_levels = [int(c.strip()) for c in args.concurrency.split(",") if c.strip()]

    # Load or fetch dev300 trips
    print("[load-test] Loading trips...")
    trips = load_or_fetch_trips(trips_path=args.trips)
    print(f"[load-test] Loaded {len(trips)} trips.")

    # Execute load test
    results = await run_load_test(
        base_url=args.base_url,
        trips=trips,
        concurrency_levels=concurrency_levels,
        requests_per_level=args.requests,
        warmup=args.warmup,
        batch_size=args.batch_size,
        endpoint=args.endpoint,
        advisory=args.advisory,
        headers=headers,
    )

    # Save JSON if requested
    if args.out:
        out_p = Path(args.out)
        out_p.parent.mkdir(parents=True, exist_ok=True)
        out_p.write_text(json.dumps(results, indent=2), encoding="utf-8")
        print(f"[load-test] JSON results saved to {args.out}")

    # Generate and save Markdown report
    report_md = format_markdown_report(results)
    if args.report:
        report_p = Path(args.report)
        report_p.parent.mkdir(parents=True, exist_ok=True)
        report_p.write_text(report_md, encoding="utf-8")
        print(f"[load-test] Markdown report saved to {args.report}")

    print("\n" + report_md + "\n")
    return 0 if results["acceptance"]["overall_pass"] else 1


def main() -> None:
    args = parse_args()
    exit_code = asyncio.run(main_async(args))
    sys.exit(exit_code)


if __name__ == "__main__":
    main()

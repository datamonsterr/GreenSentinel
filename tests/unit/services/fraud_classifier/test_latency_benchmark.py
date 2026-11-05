from __future__ import annotations

import json
import os
import time
from pathlib import Path

import numpy as np
import pytest

from src.services.fraud_classifier.model import (
    ClassifierUnavailableError,
    get_fraud_classifier,
    reset_fraud_classifier,
)

DEV300_PATH = Path("/home/dat/releases_v2_1/dev300.jsonl")


@pytest.mark.slow
def test_latency_micro_benchmark():
    if os.environ.get("CI") == "true":
        pytest.skip("Latency benchmark skipped in CI")

    if not DEV300_PATH.exists():
        pytest.skip("dev300 dataset not found locally")

    reset_fraud_classifier()
    try:
        classifier = get_fraud_classifier()
    except ClassifierUnavailableError:
        pytest.skip("Classifier artifacts not yet available")

    with DEV300_PATH.open() as f:
        trips = [json.loads(line) for line in f]

    # Warmup with 1 trip
    classifier.predict(trips[0])

    # 1. Single-trip latency measurements
    single_infer_ms = []
    single_feat_ms = []
    single_total_ms = []

    for trip in trips:
        t0 = time.perf_counter()
        res = classifier.predict(trip)
        t_tot = (time.perf_counter() - t0) * 1000.0
        single_infer_ms.append(res.inference_ms)
        single_feat_ms.append(res.feature_ms)
        single_total_ms.append(t_tot)

    p50_infer = float(np.percentile(single_infer_ms, 50))
    p95_infer = float(np.percentile(single_infer_ms, 95))
    p99_infer = float(np.percentile(single_infer_ms, 99))

    p50_total = float(np.percentile(single_total_ms, 50))
    p95_total = float(np.percentile(single_total_ms, 95))
    p99_total = float(np.percentile(single_total_ms, 99))

    print("\n" + "=" * 50)
    print("IN-PROCESS LATENCY MICRO-BENCHMARK (Single Trip, N=300):")
    print(f"  Inference p50: {p50_infer:.2f} ms | p95: {p95_infer:.2f} ms | p99: {p99_infer:.2f} ms")
    print(f"  Total     p50: {p50_total:.2f} ms | p95: {p95_total:.2f} ms | p99: {p99_total:.2f} ms")
    print("=" * 50)

    # 2. Batch of 64 latency measurements
    batch_64 = trips[:64]
    # Warmup
    classifier.predict_many(batch_64[:2])

    batch_times = []
    for _ in range(10):
        t0 = time.perf_counter()
        _ = classifier.predict_many(batch_64)
        t_batch = (time.perf_counter() - t0) * 1000.0
        batch_times.append(t_batch)

    batch_p50 = float(np.percentile(batch_times, 50))
    batch_p95 = float(np.percentile(batch_times, 95))
    batch_p99 = float(np.percentile(batch_times, 99))

    print("IN-PROCESS LATENCY MICRO-BENCHMARK (Batch of 64, 10 runs):")
    print(f"  Batch 64  p50: {batch_p50:.2f} ms | p95: {batch_p95:.2f} ms | p99: {batch_p99:.2f} ms")
    print(f"  Per-item  p50: {batch_p50 / 64:.2f} ms | p95: {batch_p95 / 64:.2f} ms | p99: {batch_p99 / 64:.2f} ms")
    print("=" * 50 + "\n")

    # Target assertion from PROD_DESIGN §Non-functional targets: p95 <= 50 ms
    assert p95_infer <= 50.0, f"p95 inference latency {p95_infer:.2f} ms exceeded 50 ms limit"

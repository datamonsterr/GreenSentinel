# Benchmark Data Index — Ride-Hailing Fraud Benchmark (Epics #247 & #494)

Index for the single-trip ride-hailing fraud benchmark datasets, generator pipelines, evaluation metrics, and research experiment archives (`no_violation`, `ERR-01`…`ERR-05`, `insufficient_evidence`).

---

## Authoritative Documentation

| Document | Description |
|---|---|
| **[DATASET.md](DATASET.md)** | **Authoritative Dataset Card** for current corpus `releases_v2.1` (40k trips, SHA-256 `d52e52ff...`, 70/15/15 driver split, generator config, scrubbed boundary, known leaks, release history). |
| **[DATASET_CARDS.md](DATASET_CARDS.md)** | Reference dataset cards ([[REF-PORTO]], [[REF-NYC-TLC]], [[REF-MULTIWOZ]], [[REF-SGD]], [[REF-PAYSIM]], [[REF-MIPO]], [[REF-NAYFEH]], [[REF-OSM-VN]]) distinguishing v1-era anchors from `build_v2` parametric priors. |
| **[BENCHMARK.md](BENCHMARK.md)** | **Consolidated Benchmark Index** ordered chronologically from 2026-10-12 heuristic runs to the final out-of-sample test split evaluation. |
| **[AUTORESEARCH.md](AUTORESEARCH.md)** | Research methodology, keep/revert decision protocol, table of attempts E0–E6, E7/E8, D1, R3A–R3H, R3C, R3F, R3D, validity caveats, and staircase progression. |
| **[REALISM_V2.md](REALISM_V2.md)** | Realism audit and distributional comparison of `build_v2` realistic generation against v1 synthetic artifacts. |
| **[HARNESS_INTEGRITY_REVIEW.md](HARNESS_INTEGRITY_REVIEW.md)** | Harness failure gating, zero silent heuristic fallback enforcement, and provider access accounting ([ADR-029](../architecture/adr-029-harness-live-call-accounting.md)). |
| **[experiments/](experiments/)** | Experiment registry ([registry.jsonl](experiments/registry.jsonl)), staircase chart ([staircase.png](experiments/staircase.png)), attempt summaries ([attempts/](experiments/attempts/)), and leak audit ([R3C_LEAK_AUDIT.md](experiments/R3C_LEAK_AUDIT.md)). |
| **[benchmark/history/](benchmark/history/)** | Archived historical benchmark reports ([2026-10-12-heuristic-30k.md](benchmark/history/2026-10-12-heuristic-30k.md), [2026-10-12-heuristic-validation-259.md](benchmark/history/2026-10-12-heuristic-validation-259.md), [2026-10-12-dataset-eda-10k.md](benchmark/history/2026-10-12-dataset-eda-10k.md), [2026-10-12-validation-guide.md](benchmark/history/2026-10-12-validation-guide.md)). |

---

## Datasets and Storage

- **Current Corpus (`releases_v2.1`)**: 40,000 trips, generated via `scripts/benchmark/build_v2/` ([PR #544](https://github.com/AI20K-Build-Phase-Cohort-4/GreenSentinel/pull/544)) and published on Hugging Face Hub: <https://huggingface.co/datasets/datamonsterr/green-sentinel-synthesized-trips> (`trips_sha256` `d52e52ff...`, revision `abb8cc8b...`). Bulk data is git-ignored.
- **Historical Realistic Corpus (`releases_v2`)**: 40,000 trips, published on Hugging Face Hub (`trips_sha256` `9986acd1...`, revision `cc8023b7...`).
- **Historical Merged Corpus (`releases_v1`)**: 40,000 trips (v1 + feedback-v2 + g1g2-v3 + evidence-v4) hosted on Hugging Face Hub (`trips_sha256` `1a0f05b3...`, revision `914a3656...`).
- **Vietnam Corridor Pilot (`synthesized_vietnam_trip`)**: 1,000 trips grounded in OSM/OSRM road networks ([SYNTHESIZED_VIETNAM_TRIP_394.md](SYNTHESIZED_VIETNAM_TRIP_394.md)), hosted on Hugging Face Hub (`trips_sha256` `c4c80903...`, revision `a914d500...`).
- **Committed Artifacts**:
  - Conversation bank: [`data/conversation_bank/`](../../data/conversation_bank/) (11 YAML dialogue banks).
  - Notebook profiles: [`notebooks/benchmark10k/`](../../notebooks/benchmark10k/) (metrics and profile json).
  - Tracked profiles: [`data/benchmark-10k/profiles/evidence-v4/`](../../data/benchmark-10k/profiles/evidence-v4/) and [`data/benchmark-10k/profiles/synthesized_vietnam_trip/`](../../data/benchmark-10k/profiles/synthesized_vietnam_trip/).

---

## Reproduction Commands

```bash
# 1. Build current releases_v2.1 corpus (40k trips, realistic generator)
python3 scripts/benchmark/build_v2/builder.py --out data/benchmark-10k/releases_v2.1 --n 40000 --seed 20261017

# 2. Or fetch historical releases_v1 from Hugging Face Hub (checksum-verified)
python scripts/benchmark/fetch_dataset.py --profile releases_v1 --out data/benchmark-10k

# 3. Run benchmark evaluation in enum-blind mode
python3 scripts/benchmark/run_10k.py --in data/benchmark-10k/releases_v2.1/trips.jsonl --out /tmp/predictions.jsonl --metrics-out /tmp/metrics.json --enum-blind

# 4. Run historical generator hardening (evidence-v4)
python3 scripts/benchmark/build_10k_v2.py --n 10000 --seed 20261011 --profile evidence-v4
```

Verification setup: [benchmark evidence runbook](../testing/manual/BENCHMARK_EVIDENCE.md).

---

## Class Balance vs Production Prevalence

The benchmark class mix contains **70% no violation, 24% fraud violations (`ERR-01`..`ERR-05`), and 6% insufficient evidence**. This distribution represents deliberate **enrichment** to ensure sufficient sample sizes per violation category. Financial mobile-money benchmarks (e.g. PaySim [[REF-PAYSIM]](DATASET_CARDS.md#ref-paysim)) exhibit natural fraud rates of ~0.13%, which should not be conflated with ride-hailing dispute prevalence. The benchmark's 70/24/6 mix is a deliberate synthetic enrichment to score detectors, not an estimate of production alert volume.

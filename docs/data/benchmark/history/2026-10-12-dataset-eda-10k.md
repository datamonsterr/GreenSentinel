# Benchmark 10k Analysis (Issue #255)

> [!NOTE]
> **Superseded by [DATASET.md](../../DATASET.md) and [BENCHMARK.md](../../BENCHMARK.md)**.
> This document is retained for historical audit provenance (2026-10-12 EDA of v1 10k corpus).

Source: `data/benchmark-10k/v1/trips.jsonl` (10,000 bundles) + `manifest.json`.
Method: `scripts/analyze_10k.py` (stdlib + numpy, ~3.3 s) →
`notebooks/benchmark10k/profile.json` (counts, quantiles, AUROCs, timings,
leakage verdicts). No matplotlib in env — tables only, no plots.
Bundle schema per `scripts/benchmark/build_10k.py`: `label`,
`measured_features{approach_ssd_s,davi,coverage,max_gap_s,mock_ratio,arrived_at_pickup}`,
`route{tortuosity,...}`, `conversation[]`, `driver_profile/analytics`,
`label_provenance`. Null means insufficient evidence, never zero
([DATA_MODEL.md](../../../architecture/DATA_MODEL.md)); ERR-05 has 100% null SSD/DAVI (300/300),
all other classes ≤0.8% nulls per feature.

## 1. Per-class distributions

p05 / p25 / p50 / p75 / p95 + mean. `turns` = conversation length; `utt_w` =
per-bundle mean customer utterance words.

### approach_ssd_s

| class | n/null | p05 | p25 | p50 | p75 | p95 | mean |
|---|---:|---:|---:|---:|---:|---:|---:|
| no_violation | 7000/0 | 0.0 | 0.0 | 0.0 | 0.0 | 15.0 | 3.96 |
| ERR-02 | 800/2 | 210.0 | 255.0 | 300.0 | 360.0 | 390.0 | 301.71 |
| insufficient_evidence | 600/4 | 0.0 | 0.0 | 0.0 | 0.0 | 15.0 | 2.27 |
| ERR-01 | 500/2 | 45.0 | 60.0 | 75.0 | 90.0 | 105.0 | 74.49 |
| ERR-03 | 500/2 | 0.0 | 0.0 | 0.0 | 0.0 | 15.0 | 3.58 |
| ERR-04 | 300/0 | 0.0 | 0.0 | 0.0 | 15.0 | 15.0 | 4.00 |
| ERR-05 | 300/300 | — | — | — | — | — | — |

### davi

| class | n/null | p05 | p25 | p50 | p75 | p95 | mean |
|---|---:|---:|---:|---:|---:|---:|---:|
| no_violation | 7000/2 | 0.6715 | 0.7430 | 0.7893 | 0.8391 | 0.8962 | 0.7860 |
| ERR-02 | 800/4 | -0.9990 | -0.9794 | 0.6988 | 0.9923 | 0.9990 | 0.0312 |
| insufficient_evidence | 600/25 | 0.4818 | 0.5827 | 0.6694 | 0.7653 | 0.8403 | 0.6686 |
| ERR-01 | 500/5 | -0.9991 | -0.9855 | -0.0557 | 0.9905 | 0.9989 | 0.0093 |
| ERR-03 | 500/2 | -0.9365 | -0.7292 | -0.6106 | -0.4433 | -0.1980 | -0.5722 |
| ERR-04 | 300/0 | 0.6539 | 0.7333 | 0.7809 | 0.8339 | 0.8906 | 0.7789 |
| ERR-05 | 300/300 | — | — | — | — | — | — |

### coverage

| class | p05 | p50 | p95 | mean |
|---|---:|---:|---:|---:|
| no_violation | 0.9211 | 1.0 | 1.0 | 0.9909 |
| ERR-02 | 0.9000 | 1.0 | 1.0 | 0.9900 |
| insufficient_evidence | 0.1431 | 0.4440 | 0.7564 | 0.4526 |
| ERR-01 | 1.0000 | 1.0 | 1.0 | 0.9869 |
| ERR-03 | 1.0000 | 1.0 | 1.0 | 0.9883 |
| ERR-04 | 0.9205 | 1.0 | 1.0 | 0.9901 |
| ERR-05 | 0.8929 | 1.0 | 1.0 | 0.9890 |

Only dropout separates on coverage (p50 0.44 vs 1.0 elsewhere).

### max_gap_s

| class | p05 | p25 | p50 | p75 | p95 | mean |
|---|---:|---:|---:|---:|---:|---:|
| no_violation | 15.0 | 30.0 | 30.0 | 30.0 | 45.0 | 29.38 |
| ERR-02 | 15.0 | 15.0 | 30.0 | 30.0 | 45.0 | 27.47 |
| insufficient_evidence | 80.3 | 135.2 | 193.7 | 246.7 | 296.9 | 190.56 |
| ERR-01 | 15.0 | 15.0 | 15.0 | 30.0 | 30.0 | 21.63 |
| ERR-03 | 15.0 | 15.0 | 15.0 | 30.0 | 30.0 | 20.24 |
| ERR-04 | 15.0 | 30.0 | 30.0 | 30.0 | 45.0 | 29.55 |
| ERR-05 | 15.0 | 15.0 | 30.0 | 30.0 | 45.0 | 26.85 |

### mock_ratio

0.0 everywhere (all quantiles, all classes) except ERR-05 = 1.0 constant
(p05–p95 all 1.0, mean 1.0). Perfect construction separation.

### tortuosity

| class | p05 | p25 | p50 | p75 | p95 | mean |
|---|---:|---:|---:|---:|---:|---:|
| no_violation | 1.1410 | 1.2214 | 1.3013 | 1.3642 | 1.4334 | 1.2931 |
| ERR-02 | 1.1466 | 1.2180 | 1.3039 | 1.3637 | 1.4334 | 1.2935 |
| insufficient_evidence | 1.1351 | 1.2113 | 1.2853 | 1.3565 | 1.4351 | 1.2834 |
| ERR-01 | 1.1382 | 1.2184 | 1.2968 | 1.3625 | 1.4324 | 1.2898 |
| ERR-03 | 1.3867 | 1.4887 | 1.5698 | 1.6663 | 1.7656 | 1.5738 |
| ERR-04 | 1.1434 | 1.2116 | 1.3001 | 1.3739 | 1.4388 | 1.2928 |
| ERR-05 | 1.1419 | 1.2067 | 1.2968 | 1.3664 | 1.4274 | 1.2877 |

### turns / utterance length

Turns uniform 4–12 in every class (p50 8, mean ~8.0, no class signal by
design). Mean customer utterance words: no_violation 8.5, ERR-02 9.4,
dropout 8.5, ERR-01 8.4, ERR-03 9.0, ERR-04 9.8, ERR-05 9.2 (p05–p95 ≈ 7–11).

## 2. Separability vs no_violation

Transductive single-feature ranking, labels eval-only — same pairwise
protocol as `docs/data/MIPO_EDA.md` (AUROC half-credit ties, AP groups
ties). Higher score = more anomalous; davi/coverage negated.

| pos class | feature (dir) | AUROC | AP | baseline AP | verdict |
|---|---|---:|---:|---:|---|
| ERR-02 | SSD (+) | 1.0000 | 1.0000 | 0.1026 | trivially separable |
| ERR-05 | mock_ratio (+) | 1.0000 | 1.0000 | 0.0411 | trivially separable |
| insufficient_evidence | max_gap (+) | 0.9992 | 0.9903 | 0.0789 | trivially separable |
| ERR-03 | davi (−) | 0.9944 | 0.9917 | 0.0667 | near-trivially separable |
| ERR-01 | SSD (+) | 0.9981 | 0.9916 | 0.0667 | separable pairwise, hardest operationally (see below) |
| ERR-03 | tortuosity (+) | 0.9775 | 0.8958 | 0.0667 | separable |
| ERR-04 | coverage (−) | 0.5051 | 0.0420 | 0.0411 | overlapping — no kinematic signal by design |

**ERR-01 is the hardest class.** Pairwise SSD AUROC vs no_violation is
0.9981, but its stalls (p05–p95 45–105 s) sit entirely below the 180 s
ERR-02 rule threshold, so any 180 s-threshold detector misses 100% of
ERR-01. It shares scenario `driver_stall_cancel` with ERR-02 (inter-stall
SSD AUROC 0.9992, adjacent ranges 60–119 vs 210–390). Correct ERR-01
labels require admissible lifecycle facts (`cancellation_actor=driver`,
`cancellation_reason=driver_cancelled_unjustified`) plus dialogue — never
kinematics alone. ERR-04 is second-hardest on kinematics (ghost trips reuse
normal geometry; signal lives in lifecycle `ghost_no_pickup` /
null `arrived_at`, not in measured features).

Disclosed admissible shortcut: `cancellation_actor` is near-deterministic
per class (driver→ERR-01, passenger→ERR-02/ERR-03, platform→dropout,
None→normal/ERR-04/ERR-05) and `arrived_at_pickup` is False for
ERR-01/02/03/05. These are operational lifecycle facts the projection
allowlist retains (`cancellation_reason`, `cancellation_actor`), not
leakage — but kinematic-only evaluation is the meaningful benchmark.

## 3. Leakage audit

(a) Builder (`scripts/benchmark/build_10k.py`) scan — 10,000/10,000 bundles:

| checked field | label-derived content | verdict |
|---|---|---|
| `telemetry[]` point keys | none of label/scenario/expected_*/intent/simulation_id/anomaly_*/simulation_labels (0 hits) | PASS |
| `conversation[]` entry keys | only role/text/sent_at_offset_s/lang (0 hits) | PASS |
| `measured_features` keys | exactly the 6 FW keys, no extras (0 hits) | PASS |
| `driver_profile` keys | no label/scenario keys (0 hits) | PASS |
| class-conditioned generation (scenario, CONTEXT_FOR_LABEL dialogue bank, lifecycle actor/reason, 70% fraud-driver routing, `profile_provenance.fraud_propensity`) | present by design, documented in builder | PASS with disclosure — see below |

Disclosure: telemetry/conversation/lifecycle differ by class because the
scenario generator conditions on the label — that is the intended
synthetic signal, not leakage. `driver_profile.profile_provenance.fraud_propensity`
and the 70% fraud-driver routing are detector-invisible: `driver_profile`
is not in the projection allowlist. No raw label string reaches any
detector-consumed field.

(b) `src/services/model_input_projection.py` probe — feed all eval keys plus
`anomaly_type`/`anomaly_score`/`simulation_labels`: all 11 dropped from top
level and from `points[]` (the three anomaly/simulation keys fall out via
the allowlist, which lacks them); operational `trip_id`/`points`/
`cancellation_reason`/`cancellation_actor` retained. **PASS.**

(c) `label_provenance` present with `synthetic=True` on 10,000/10,000
bundles (share 1.0). **PASS.**

## 4. Class-geometry sanity (gridlock FP)

no_violation AND (gridlock_subset OR heavy traffic): n=704, SSD≥180 count=0,
share **0.0000**. Small as required — heavy-traffic honest trips do not
trip the stall rule. Honest FP preserved.

## 5. Prior-conformance verdicts

| prior (source) | benchmark | verdict |
|---|---|---|
| Trip speed mean 7.55 m/s (Porto; NYC 5.4 ref) | `duration_s = distance/7.0` constant (builder line 272) | NOTED DIVERGENCE — 7% below Porto mean, inside Porto–NYC band; constant has no variance by design |
| Tortuosity normal (Porto WGS84 p50 1.445; config sample p50 1.2769) | normal p50 1.3013 | CONFORMS to config sampling prior; raw Porto tail (p95 3.85) absent by design (degenerate endpoints excluded) |
| Tortuosity detour p50 1.5622 (MiPo AiSq) | ERR-03 p50 1.5698 | CONFORMS |
| Dialogue 4–12 turn cap, passenger p50 11 words (MultiWOZ) | turns uniform 4–12, p50 8; utterance mean ~8.5 | DIVERGES below prior — cap truncates MultiWOZ total-turn p50 16 (p25–75 12–20); word means slightly short of 11 but same order |
| Scheduler NYC hour anchors h04/h05/h17/h18 + weekday vector | weights adopted verbatim in config | CONFORMS (shape prior, not Vietnam calibration) |
| Honest jump 0.15% segments >50 m/s, threshold 50 kept | ERR-05 mock-based, no speed jumps | CONFORMS (threshold kept as physics ceiling) |
| PaySim fraud 0.13% | 30% enriched mix, enrichment noted in manifest | CONFORMS (documented enrichment, not prevalence claim) |
| Population/driver fraud distributions | assumption, fraud-prone routing 70% | CONFORMS as assumption (no public honest-vs-fraud driver data) |
| Geography Hanoi landmarks 1–8 km | chord×tortuosity construction | CONFORMS as assumption |

## Files

- `scripts/analyze_10k.py` — analysis (new)
- `notebooks/benchmark10k/profile.json` — counts, quantiles, AUROCs, timings, leakage (new)
- This doc (new). No commits. No plots (matplotlib absent; tables only).

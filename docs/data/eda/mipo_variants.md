# MiPo Variants EDA + Tortuosity Benchmark (Issue #250)

Method: `scripts/eda_mipo_variants.py`, reuses `geometry/describe/lof_scores/evaluate`
from `scripts/eda_mipo.py` (same 8 features, same transductive protocol as
MIPO_EDA.md). Labels from filename, evaluation only. Planar XY, unknown CRS,
no timestamps. Profile: `notebooks/mipo_variants/profile.json`.
Revision `70a9b0140f94a1d3e2349999c621392c18c439fc`.

## A. 8-feature stats per variant (normal p50 | outlier p50)

| Feature | AiSq5D (1060+55) | StSt10M (182+20) | UnCh10M (725+81) |
|---|---|---|---|
| `points` | 48 \| 56 | 27 \| 28 | 17 \| 20 |
| `length_xy` | 12300 \| 14910 | 4037 \| 3898 | 1070 \| 1242 |
| `endpoint_distance_xy` | 9620 \| 9626 | 2962 \| 2900 | 701 \| 691 |
| `tortuosity` | 1.277 \| 1.550 | 1.392 \| 1.362 | 1.533 \| 1.878 |
| `step_p50_xy` | 293.7 \| 279.7 | 163.5 \| 137.7 | 67.3 \| 77.8 |
| `step_max_xy` | 456.7 \| 470.0 | 350.0 \| 333.5 | 132.3 \| 165.3 |
| `zero_step_fraction` | 0 \| 0 | 0 \| 0 | 0 \| 0 |
| `turn_mean_rad` | 0.380 \| 0.442 | 0.473 \| 0.534 | 0.655 \| 0.697 |

Tortuosity quantiles vs ERR-03 prior (normal p05 1.2562–p95 1.4688; detour
p05 1.3584–p95 1.7888): AiSq5D normal 1.256–1.471, outlier 1.344–1.798
(matches within 0.015). StSt10M normal 1.179–1.918, outlier 1.233–1.814
(wide overlap, medians inverted). UnCh10M normal 1.456–1.603, outlier
1.462–4.695 (higher baseline, heavy outlier tail). Full quantiles in profile.json.
Coordinate ranges differ per variant (AiSq x 90.8k–98.3k; StSt x 97.6k–100.7k;
UnCh x 96.2k–98.1k, y ≈ −14k–−13k) — distinct cohorts/transforms, XY units not
comparable across variants.

## B. Tortuosity transductive benchmark (same method as MIPO_EDA)

| Variant | Prevalence (AP baseline) | Tortuosity AUROC / AP | LOF-k20 AUROC / AP |
|---|---:|---:|---:|
| AiSq5D | 4.93% (0.0493) | **0.9310 / 0.4141** | 0.7710 / 0.1694 |
| StSt10M | 9.90% (0.0990) | **0.4503 / 0.0916** | 0.6190 / 0.1525 |
| UnCh10M | 10.05% (0.1005) | **0.8681 / 0.7891** | 0.8755 / 0.5390 |
| AiSq10D ref (MIPO_EDA) | 10.00% (0.1000) | 0.9444 / 0.6124 | 0.7593 / 0.2356 |

## C. Verdict: prior generalizes on ONE variant, diverges on two

- **AiSq5D: GENERALIZES.** Same detour-injection family as AiSq10D (fixed O/D,
  endpoint p50 equal 9620 vs 9626, outlier = longer + more tortuous). Prior
  ranges hold; tortuosity AUROC 0.93 ≈ AiSq10D 0.94.
- **StSt10M: DIVERGES (inverted).** Outlier median tortuosity LOWER than normal
  (1.362 < 1.392), outlier median length SHORTER (3898 < 4037). Anomaly is not
  route-stretch; tortuosity AUROC 0.45 < chance. LOF 0.62 also weak. Different
  anomaly mechanism — do not score with tortuosity.
- **UnCh10M: PARTIAL (recalibrate).** Tortuosity ranks well (AUROC 0.87, AP 0.79
  above 0.10 baseline) but baseline geometry differs: normal median 1.533 far
  above AiSq10D 1.277; trajectories short (~17 pts, endpoint ~700). Prior
  thresholds do not transfer; per-variant calibration required. LOF 0.88 ≈ tortuosity.

## D. Config verdict (`config/telemetry_distribution.yaml`)

- `route.tortuosity_quantiles.normal` (p05 1.2562 … p95 1.4688) — **CONFIRMED**
  (retain AiSq10D values; AiSq5D confirms within 0.015, others are different
  cohorts, not replacements).
- `route.tortuosity_quantiles.detour` (p05 1.3584 … p95 1.7888) — **CONFIRMED**
  (same reason; StSt10M inverted and UnCh10M re-based, so no single replacement
  value exists — per-variant thresholds needed, follow-up).
- `route.zero_step_share_normal` (mean 0.0040, p95 0.0220) — **CONFIRMED**
  (AiSq5D matches: normal p95 0.0222; StSt10M all-zero, UnCh10M p95 0.038 — same
  order, no YAML change).
- No YAML values replaced. Per-variant quantiles live in
  `notebooks/mipo_variants/profile.json`.

## E. Limitations

Full-variant (not sliced) analysis, single run, no seed variation (deterministic
transductive scores, no CIs); LOF is the 8-feature Euclidean implementation from
`eda_mipo.py`, not MiPo polar features; planar XY units incomparable across
variants and never meters; no timestamps (no speed/SSD); labels are injected
anomalies, not adjudicated fraud; StSt10M n=202 small (20 outliers).

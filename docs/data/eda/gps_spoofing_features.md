# GPS-spoofing feature EDA — Nayfeh dataset (Issue #250)

Source: `data/raw/gps_spoofing_nayfeh` (no license → **EDA-ONLY**, never merged).
Script: [scripts/eda_spoofing.py](../../scripts/eda_spoofing.py).
Aggregates: [notebooks/spoofing/profile.json](../../notebooks/spoofing/profile.json).
Labels from filenames (attack vs clean); 6,983 pooled rows (3,487 attack /
3,496 clean). Lat/lon stored as deg×1e7 integers, rescaled. Timestamps are
constant within files, so no time-based implied speed exists (recorded as
unavailable, not zero).

## Attack-vs-clean feature ranges

| Feature | Attack p50 (p25–p75) | Clean p50 (p25–p75) |
|---|---|---|
| `vel_m_s` | 0.008 (0.005–0.011), max 19.46 | 0.109 (0.068–0.162), max 2.60 |
| speed jump \|Δvel\| (row-order) | 0.004 (0.002–0.007), max 19.45 | 0.034 (0.015–0.059), max 1.70 |
| position delta, m (row-order haversine) | 0.000 (0.000–0.011), max 50.15 | 0.024 (0.014–0.034), max 30.31 |
| `eph` | 2.52 (2.18–3.24), max 16.31 | 1.33 (1.26–1.36), max 1.51 |
| `epv` | 4.12 (3.53–5.26), max 18.71 | 1.77 (1.65–1.84), max 2.11 |
| `hdop` | 0.93 (0.90–0.93) | 0.93 (0.87–0.99) |
| `vdop` | 1.27 (1.13–1.27) | 1.26 (1.07–1.30) |
| `jamming_indicator` | 6 (4–10), max 33 | 70.5 (55–75), max 93 |
| `noise_per_ms` | 176 (169–185) | 96 (93–99) |
| `s_variance_m_s` | 0.165 (0.136–0.196) | 0.280 (0.247–0.335) |
| `satellites_used` | 10 (10–10) | 10 (10–11) |

## Best SIMPLE single-threshold kinematic rule (transductive AUROC)

Same convention as [MIPO_EDA.md](../MIPO_EDA.md): pooled-row ranking, labels
for evaluation only, pairwise AUROC with half credit for ties. No train/test
split, no generalization claim.

| Rule (higher = attack) | AUROC | n |
|---|---:|---:|
| `eph` | **1.0000** | 6,983 |
| `epv` | 1.0000 | 6,983 |
| `noise_per_ms` | 1.0000 | 6,983 |
| low `jamming_indicator` (negated) | 1.0000 | 6,983 |
| low `vel_m_s` (negated) | 0.9845 | 6,983 |
| low `s_variance_m_s` (negated) | 0.9733 | 6,983 |
| fewer `satellites_used` (negated) | 0.6011 | 6,983 |
| `vdop` | 0.4586 | 6,983 |
| `hdop` | 0.4118 | 6,983 |
| position delta | 0.1351 | 6,979 |
| speed jump | 0.0825 | 6,979 |
| `vel_m_s` (high = attack) | 0.0155 | 6,983 |
| implied speed | n/a | 0 (no time base) |

**Best single rule: `eph` threshold, AUROC 1.0000** (equivalently `epv`,
`noise_per_ms`, or negated `jamming_indicator`).

### Caveats (load-bearing)

1. Perfect separation on receiver-quality fields is almost certainly a
   **session artifact**: attack and clean logs were recorded under different
   conditions (note `jamming_indicator` runs *higher* in clean logs — inverted
   from any physical expectation of jamming under spoofing).
2. Kinematic features separate in the **wrong direction** (attack rows are
   near-stationary, clean rows moving) — a hover-vs-flight collection artifact,
   not a spoofing signature. Do not ship "low speed = spoofed".
3. Drone u-blox telemetry, not phone GNSS; no `isFromMockProvider` equivalent.

## ERR-05 threshold implication (`implausible_speed` 50 m/s)

Zero of 6,983 rows exceed 50 m/s in either class (attack max 19.46, clean max
2.60). The 50 m/s gate therefore has **zero false positives on this data**,
but the data also provides **zero positive support** — it cannot validate that
real spoof jumps exceed 50 m/s (the single 19.45 m/s attack jump and 50.15 m
position step are the closest observed anomalies, both far below the gate).
Keep 50 m/s as a conservative physics-based ceiling (urban ride speeds never
approach it), not as a data-calibrated detection threshold; detection must
rest on receiver-quality combinations, recalibrated on phone-level data.

## Reproduce

```bash
.venv/bin/python scripts/eda_spoofing.py  # reads data/raw, writes notebooks/spoofing/profile.json
```

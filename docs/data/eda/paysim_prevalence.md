# PaySim prevalence reference (Issue #250)

Source: `data/raw/paysim/paysim.csv` (HF mirror, MIT card; payments domain,
**EDA-ONLY**). Script: [scripts/eda_paysim.py](../../scripts/eda_paysim.py).
Aggregates: [notebooks/paysim/profile.json](../../notebooks/paysim/profile.json).
Method: streaming `chunksize=200,000`, deterministic systematic stride 12
(offset rotates per chunk): **6,362,620 rows scanned, 530,221 sampled**
(8.3%, within the ≤1M cap). No raw redistribution.

## Sampled `isFraud` rate

| | n | rate |
|---|---:|---:|
| Sampled fraud | 700 / 530,221 | **0.1320%** |
| Manifest full-file rate | 8,213 / 6,362,620 | 0.1291% |
| `isFlaggedFraud` overall (sampled) | — | 0.0003% |

Sampled rate reproduces the manifest rate to within 0.003 pp.

## Fraud-vs-legit amount distribution (sampled)

| | min | p05 | p25 | p50 | p75 | p95 | max | mean |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| fraud (n=700) | 458 | 86,540 | 237,268 | **469,723** | 810,440 | 2,394,546 | 10,000,000 | 1,468,978 |
| legit (n=529,521) | 0 | 1,085 | 13,953 | **74,773** | 213,945 | 771,048 | 92,247,170 | 178,063 |

Fraud amounts sit roughly 6× above legit medians; fraud concentrates in
`TRANSFER` (325/44,540 = 0.73%) and `CASH_OUT` (375/186,428 = 0.20%), with zero
fraud in `PAYMENT`/`CASH_IN`/`DEBIT` — a simulator construction rule, not a
discovered pattern.

## Benchmark class-mix note

Our benchmark class mix is deliberate enrichment for detection evaluation, not
natural prevalence: PaySim-scale natural fraud prevalence is ~0.1%, at which a
detector's alert burden and precision cannot be meaningfully benchmarked on a
10k-case set. Enriched mixes (e.g. ~10% like the MiPo slice) measure ranking
quality (AUROC/AP) under controlled conditions; they must not be presented as
production precision, and thresholds set on enriched data must be recalibrated
to the deployment base rate before any operational use.

## Reproduce

```bash
.venv/bin/python scripts/eda_paysim.py  # streams data/raw, writes notebooks/paysim/profile.json
```

# Issue #259 body (refresh — paste as issue body; keeps existing Q&A below)

## task(benchmark): independent validation of PR #258 (30k)

Reviewer: follow `docs/data/README.md` (quick path R0–R5,
~15 min + optional Railway check). Existing Q&A section below stays
authoritative for fraud-count, feature-chain, weakness, and leakage
questions — numbers updated for 30k where marked [30k].

### Updated pass criteria [30k]

| Check | Expected | Source |
|---|---|---|
| Batch shas v1/v2/v3 | `b6aed4a2…` / `8675f823…` / `8ba37647…`, `sha_ok` ×3 | `analyze_30k.py` → `metrics_30k.json` |
| Mix per batch / union | 7000/800/600/500/500/300/300 → 21000/2400/1800/1500/1500/900/900 | `combined_labels.csv` (30,001 lines) |
| Cross-batch dups (ref/id/assignment/geom) | 0/0/0/0 | `metrics_30k.json` → `cross_batch_duplicates` |
| Combined acc / macro-F1 | **0.6801 / 0.4904** exact | `metrics_30k.json` |
| Per-batch acc | 0.7043 / 0.6778 / 0.6583 | `metrics.json`, `metrics_v2.json`, `metrics_v3.json` |
| Guardrail-blocked | 5,563/30,000 (18.5%) | per-batch `guardrail_blocked` sum |
| Benchmark tests + ruff | green (`--noconftest`; root `jwt` gap is pre-existing env, not this PR) | `tests/unit/test_build_10k.py`, `test_grow.py`, `test_telemetry_generation.py` |
| Blind-spot probes | loop/slowcrawl → `insuff`; legit-cancel → `insuff` (#265); ghost → `no_violation` (#264) | R3 probe table in guide |
| Railway `greensentinel-benchmark-db` | 30,000 prediction rows (v1+v2+v3 runs) | optional R4 |
| Diff hygiene | no `src/` behavior change, no secrets, bulk data ignored | `git log --stat` |

### Verdict rule

VALIDATED → squash-merge #258. Any R1 number drift → request changes
(determinism is the core contract). Do not re-report: v2 missing
`seed_data.sql`, ERR-03/04 F1 0, E2E infra failure.

### New validation questions for this round [30k]

- Q7: 30k union shows 0 geometry duplicates across batches — what
  granularity does the check use, and could two trips still share a route?
  (A: rounded-5-decimal full coordinate-sequence hash; same landmark pair
  with different jitter/schedule still differs. Route reuse is by design —
  130 landmark pairs — identity duplication is what the gate forbids.)
- Q8: Combined acc (0.6801) sits between v1 and v3 — why isn't it
  batch-size-weighted toward v1? (A: it is the flat 30k mean; v2/v3 carry
  harder slices — 717 legit cancels, 371 G1/G2 — so the mean drops. The
  drop is composition, not regression; per-slice rates are stable.)
- Q9: 5,924 drivers, none spanning batches — why does this matter?
  (A: future detector training splits must group by driver; isolation
  across batches was verified now so v1/v2/v3 can serve as split folds
  without driver leakage.)

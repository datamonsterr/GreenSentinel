# Validation Guide — 30k Fraud Benchmark (Issue #259)

> [!NOTE]
> **Superseded by [BENCHMARK.md](../../BENCHMARK.md)**.
> This document is retained for historical audit provenance (2026-10-12 reviewer guide for issue #259).

Reviewer quick path: ~15 minutes + one optional Railway check. No prior
context needed. All commands run from the repo root with the project venv
(`./.venv/bin/python`). Bulk data (`data/benchmark-10k/*/trips.jsonl`,
~450 MB) is git-ignored — rebuild it via step R1, or reuse existing files.

## R0. Scope (read first, 2 min)

- PR #258 is data + generator + docs only. It changes **no detector
  behavior** in `src/` (only `config/telemetry_distribution.yaml` priors and
  `scripts/`). Detector fixes live in follow-ups #260–#264 — do not hold this
  PR for them.
- The 30% fraud mix is **enrichment, not prevalence** (PaySim measures 0.13%).
  Never present enriched-mix precision as production precision.
- The heuristic baseline is *supposed* to fail on ERR-03/ERR-04/G1/G2
  (combined acc 0.6801). Every failure cell traces to a filed ticket. A red
  metric is not a merge blocker; an unexplained metric is.

## R1. Rebuild determinism (5 min) — must match exactly

```bash
python3 scripts/benchmark/build_10k.py --n 10000 --seed 20261011 --noise happy
python3 scripts/benchmark/build_10k.py --n 10000 --seed 20261012 --noise happy
python3 scripts/benchmark/build_10k.py --n 10000 --seed 20261013 --noise happy
python3 scripts/analyze_30k.py
```

Pass criteria (from `notebooks/benchmark10k/metrics_30k.json`):

| Check | Expected |
|---|---|
| trips sha256 v1 / v2 / v3 | `b6aed4a2…` / `8675f823…` / `8ba37647…` (`sha_ok: true` ×3) |
| Class mix per batch | 7000/800/600/500/500/300/300 (no_violation/ERR-02/insuff/ERR-01/ERR-03/ERR-04/ERR-05) |
| 30k union mix | 21000/2400/1800/1500/1500/900/900 |
| Cross-batch duplicates (ref, trip_id, assignment_id, geometry) | 0, 0, 0, 0 |
| Combined acc / macro-F1 | 0.6801 / 0.4904 (exact — any drift means the generator or heuristic changed) |
| Per-batch acc | v1 0.7043, v2 0.6778, v3 0.6583 |

## R2. Tests + lint (3 min)

```bash
./.venv/bin/python -m pytest tests/unit/test_build_10k.py tests/unit/test_grow.py tests/unit/scripts/test_telemetry_generation.py -q --noconftest
ruff check scripts/benchmark/ scripts/analyze_30k.py tests/unit/test_build_10k.py tests/unit/test_grow.py
```

Pass: all green (53 tests at last run). Note: the full suite needs `jwt` in
the venv (pre-existing env gap, unrelated to this PR) — `--noconftest`
scopes the run to benchmark tests. Do not "fix" the env inside this review.

## R3. Spot-check the blind spots (5 min)

Pick one `trip_ref` from each row below (`data/benchmark-10k/v3/trips.jsonl`
+ `v3/predictions.jsonl`) and confirm the predicted category:

| Case | Why it matters | Expected prediction |
|---|---|---|
| a `loop_subset` trip (138 in v3) | G2 fraud the heuristic cannot see | `insufficient_evidence` (deferral is correct behavior) |
| a `slowcrawl_subset` trip (233 in v3) | G1 fraud below the SSD threshold | `insufficient_evidence` |
| a `legit_cancel_subset` normal (717 in v2+v3) | honest cancel scored as error | `insufficient_evidence` — known dual-label tension (#265), not a bug |
| an `ERR-04` ghost trip | completed + never picked up, reason None | `no_violation` (structural gap, #264) — confirm the conversation text *discusses* the ghost trip while the classifier ignores it |

## R4. Railway row count (optional, needs access)

`p063-benchmark-db` (project `caring-renewal`, env `dev`) must hold **30,000
prediction rows** across the v1/v2/v3 runs plus run-registry rows. If you
cannot access Railway, skip — local artifacts are authoritative.

## R5. Verdict

- **Approve** if R1 exact, R2 green, R3 matches, diff contains no `src/`
  behavior change and no secrets (`git log --stat`, eyeball filenames).
- **Request changes** if any R1 number drifts (blocks merge — determinism is
  the dataset's core contract), or if new ASSUMED columns lack a
  `label_provenance` tag.
- Known gaps to NOT re-report: v2 missing `seed_data.sql`; ERR-03/ERR-04
  recall 0 (#262–#264); E2E Playwright failure on PR CI is infra (fails on
  `main` too, zero frontend/API files in diff).

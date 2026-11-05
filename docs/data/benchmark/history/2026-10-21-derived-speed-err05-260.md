# Issue #260 — derived-speed ERR-05 gate on the current mapper (2026-10-21)

Evidence for [issue #260](https://github.com/AI20K-Build-Phase-Cohort-4/GreenSentinel/issues/260)
(PR #333, rebased onto current `main`). The original PR targeted
`bundle_to_input` in `scripts/benchmark/run_10k.py`; that path no longer exists —
`bundle_to_input` now delegates to the shared production mapper
`map_telemetry_event_to_jev_input` (`src/services/jev_state_builder.py`). The fix
was ported onto the current code instead of resurrecting the dead path:

- Mapper: removed the reported-`speed_mps` fallback (derived
  `fw.speed.max_mps` only; `0.0` when no derived signal). Producer speed is
  untrusted per `TELEMETRY_DISTRIBUTION.md` section 3.
- Heuristic (`jev_assessment_service.py`): ERR-05 now requires the mock flag OR
  an accuracy-corroborated derived jump (pairwise haversine/Δt, gaps > 30 s
  skipped, jump counts only if displacement exceeds 2× the worst endpoint
  accuracy). Branch order is mock ERR-05 → stall ERR-02 → derived-speed ERR-05,
  so confirmed stalls are not stolen by reported-speed spikes.
- Regression tests: `tests/unit/test_260_derived_speed_mapper.py`,
  `tests/unit/services/test_260_err05_derived_gate.py` (7 tests; 5 fail on
  pre-fix `main`, all pass post-fix).

## Measured results (releases_v1 corpus, 40,000 trips, offline heuristic)

Reproducible via `scripts/benchmark/fetch_dataset.py --profile releases_v1
--out data/benchmark-10k` + `scripts/benchmark/run_10k.py`
(corpus `trips.jsonl` sha256 `1a0f05b3e1276d8cc0f11a1a922efbecbb554c3c50a6458b24137923592031f7`).
Before = clean `main` (`f4f8e78e`); after = this PR head. Same inputs, only the
detector changed.

| Metric | Before (main) | After (PR) |
|---|---:|---:|
| ERR-05 precision | 0.4157 (1200 tp / 2887 pred) | **0.9274** (1200 tp / 1294 pred) |
| ERR-05 recall | 1.0000 (1200/1200) | **1.0000** (1200/1200) |
| ERR-01 recall | 0.5540 | 0.5635 |
| ERR-02 recall | 0.7566 | 0.7619 |
| Overall accuracy | 0.2459 | 0.2487 |
| Macro-F1 | 0.4920 | 0.5473 |

DoD verdict: ERR-05 precision ≥ 0.80 met (0.9274), recall 1.0 kept, ERR-01/02
recall not regressed (both improved slightly). False-positive ERR-05 predictions
fall from 1,687 to 94; all 1,200 mock-provider fixtures remain detected.

## Limits

- The releases_v1 corpus labels are synthetic ground truth; the numbers above
  measure detector behavior on that corpus, not production prevalence.
- `route_analytics.py` maneuver `max_speed_kmh` display values still derive from
  reported `speed_mps`; they feed prompt narrative, not the ERR-05 decision, and
  are out of scope for this issue.
- No UI surface; no preview environment applies (backend-only change).

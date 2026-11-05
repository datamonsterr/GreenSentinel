# Research Harness Metric Integrity, State Mapping Review, and Measurement Flaws Audit

- **Date**: 2026-10-17
- **Review Issue**: [#525](https://github.com/AI20K-Build-Phase-Cohort-4/GreenSentinel/issues/525)
- **Parent Epic**: [#494](https://github.com/AI20K-Build-Phase-Cohort-4/GreenSentinel/issues/494)
- **Related PRs Audited**:
  - [#499](https://github.com/AI20K-Build-Phase-Cohort-4/GreenSentinel/pull/499) (`feat(detector): Jev state builder with derived kinematics and natural-language rendering`)
  - [#500](https://github.com/AI20K-Build-Phase-Cohort-4/GreenSentinel/pull/500) (`feat(benchmark): experiment harness, metric suite, registry and staircase chart`)
  - [#501](https://github.com/AI20K-Build-Phase-Cohort-4/GreenSentinel/pull/501) (`feat(benchmark): releases_v2 realistic corpus generator + realism report`)
  - [#519](https://github.com/AI20K-Build-Phase-Cohort-4/GreenSentinel/pull/519) (`fix(benchmark): count and gate live-call failures in experiment harness`, addressing [#515](https://github.com/AI20K-Build-Phase-Cohort-4/GreenSentinel/issues/515))

---

## 1. Executive Summary & Verdict on PR #519

### Verdict
**PR #519 is necessary, but by itself INSUFFICIENT to guarantee harness measurement integrity.**

While PR #519 successfully introduced HTTP failure status capture in `JevAssessmentService`, live failure counters in `metrics.py`, and an early-abort threshold in `run_experiment.py`, critical measurement and gating loopholes remained in the shared harness:

1. **Variant Failure Propagation Bypass**: PR #519 patched `baseline_assess_async` in `scripts/benchmark/experiments/variants.py`, but neither `metrics.py` nor `run_experiment.py` enforced that custom experiment variants (e.g. E1, E2, E6) propagate `model_used`, `fallback_reason`, or `http_status`. An unpropagated or `None` model field evaluated as non-heuristic, silently scoring provider failure fallbacks as genuine model predictions with a `live_failure_rate` of 0.0.
2. **Gating Denominator Inconsistency**: The worker loop in `run_experiment.py` incremented `live_calls` based only on `model_used != "guardrail_short_circuit"`, whereas `metrics.py` classified guardrails using `guardrail_blocked` and `guardrail_reason`. Furthermore, when `live_calls` was 0, zero failures out of zero calls resulted in `valid: true`, permitting invalid live runs to pass.
3. **Paired Comparison Gaps**: `validate_paired_comparison` in `compare.py` checked corpus SHA and enum-blind mode, but failed to validate `split` (allowing cross-split comparisons, e.g., validation against test) and `sample` size. If predictions files were missing, `evaluate_decision` silently fell back to single-run bootstrap CI instead of paired bootstrap CI.
4. **Token Accounting Object Discrepancy**: In `variants._calculate_input_tokens`, the function passed the raw dataset dictionary `bundle` instead of `jev_inp`, hardcoded `variant="baseline"`, and re-parsed the bundle, ignoring state variants set on `jev_inp`.
5. **CI False-Green Guarantees**: GitHub Actions workflows `ci.yml` and `ci-draft.yml` only trigger on PRs targeting `main`. PRs opened against `exp/classifier-research-v2` only triggered `benchmark-dataset.yml`, which skipped, displaying "All checks were successful" without executing any linters or unit tests.
6. **Dataset Hash Discrepancy**: PR #501's initial pull request description referenced `350bd7e2...`, whereas the canonical corpus on disk and in `E0.json` is `9986acd1...`. This was caused by orchestrator re-reviews requiring Hanoi/HCMC kinematic calibrations and mock location rate adjustments before final merge.

---

## 2. Detailed Findings and Evidence

### Finding 1: Variant Failure Propagation Leak
- **Location**: [`scripts/benchmark/experiments/metrics.py`](../../scripts/benchmark/experiments/metrics.py) and [`scripts/benchmark/experiments/run_experiment.py`](../../scripts/benchmark/experiments/run_experiment.py).
- **Vulnerability**: In `compute_live_failure_metrics`, a failure was registered only if:
  ```python
  is_heuristic = (
      model == "jev_calibrated_heuristic" or "heuristic" in model.lower() or r.get("fallback_reason") is not None
  )
  if is_heuristic and not is_guardrail:
      failures += 1
  ```
  If an experiment variant (such as initial implementations of E1 or E2) omitted `model_used` from its return dictionary, `model` defaulted to `""` or `None`. Consequently, `is_heuristic` evaluated to `False`. The trip counted towards `live_calls += 1` in `run_experiment.py`, but contributed 0 to `failures`. A run where 100% of live LLM calls failed with HTTP 402 or 429 produced `live_failures: 0` and `live_failure_rate: 0.0`.
- **Fix Applied**:
  - `metrics.py`: Any non-guardrail record in a live run whose `model_used` is missing, empty, or `"unknown"` is now classified as an `untracked_variant_failure` and counted as a failure.
  - `run_experiment.py`: Untracked models in live mode are marked as `model_used = "unknown"` and `fallback_reason = "untracked_variant_failure"`.

### Finding 2: Soft Guardrail Exclusion, Denominator Dilution, and Zero-Call Validity
- **Location**: [`scripts/benchmark/experiments/run_experiment.py`](../../scripts/benchmark/experiments/run_experiment.py) and [`scripts/benchmark/experiments/metrics.py`](../../scripts/benchmark/experiments/metrics.py).
- **Vulnerability**: The first PR #527 patch excluded any record with `guardrail_blocked=True` or a non-null `guardrail_reason`. Both fields can describe a soft guardrail applied after a provider call, including a heuristic fallback. Excluding them hides failures and successful calls. A caller-supplied positive `live_calls` value could also dilute the failure rate. Zero-call live runs require an explicit invalidity gate.
- **Corrected rule**:
  - Only `model_used == "guardrail_short_circuit"` excludes a record from live-call and live-failure accounting, in both the worker and metric suite.
  - A real model response with a soft guardrail counts as a live call. A heuristic response with the same guardrail counts as a live call and a failure.
  - Metrics derive the denominator from prediction records even when callers supply a positive count. Cost metrics use that same count.
  - Missing, blank, whitespace-only, `None`, `unknown`, and non-string model attribution fail closed; worker records carry `untracked_variant_failure` unless a more specific fallback reason exists.
  - Live runs with zero provider-call records remain `valid: false` in the returned and persisted metrics.


### Finding 3: Comparator Split, Sample Size, and Unpaired Fallback Gaps
- **Location**: [`scripts/benchmark/experiments/compare.py`](../../scripts/benchmark/experiments/compare.py) and [`scripts/benchmark/experiments/compare.py`](../../scripts/benchmark/experiments/compare.py).
- **Vulnerability**:
  - `validate_paired_comparison` checked SHA and enum-blindness, but never verified `candidate["split"] == best["split"]` or `candidate["sample"] == best["sample"]`. A candidate evaluated on `test` could be directly registered against a baseline evaluated on `validation`.
  - In `evaluate_decision`, if `paired_ci_half_width is None`, the code fell back to `candidate.get("ci_half_width")` (the single-run bootstrap CI half-width). Single-run CI does not account for trip-level covariance between models and violates the paired-bootstrap decision rule specified in epic #494.
- **Fix Applied**:
  - Added strict validation for `split` and `sample` in `validate_paired_comparison`.
  - Raised `ValueError` in `evaluate_decision` when comparing against an existing `best` if `paired_ci_half_width` is not provided.
  - Preserved `split` and `sample` in `record_attempt_file`.

### Finding 4: Model Input Token Accounting Object Discrepancy
- **Location**: [`scripts/benchmark/experiments/variants.py`](../../scripts/benchmark/experiments/variants.py).
- **Vulnerability**: In `_calculate_input_tokens(bundle, jev_inp)`:
  ```python
  if build_jev_state is not None:
      try:
          state = build_jev_state(bundle, variant="baseline")
      except TypeError:
          state = build_jev_state(bundle)
  ```
  The function received `(bundle, jev_inp)`, but passed `bundle` (raw dataset dictionary) into `build_jev_state`, forcing `variant="baseline"`. This caused redundant re-mapping of the bundle via `map_telemetry_event_to_jev_input` and ignored any `state_variant` assigned to `jev_inp`.
- **Fix Applied**:
  - Updated `_calculate_input_tokens` to target `jev_inp` if provided, reading `getattr(jev_inp, "state_variant", "baseline")`.

### Finding 5: CI False-Green Guarantees on Research PRs
- **Location**: [`.github/workflows/ci.yml`](../../.github/workflows/ci.yml), [`.github/workflows/ci-draft.yml`](../../.github/workflows/ci-draft.yml), and [`.github/workflows/benchmark-dataset.yml`](../../.github/workflows/benchmark-dataset.yml).
- **Vulnerability**: GitHub Actions CI configurations only trigger on pull requests targeted to `main`:
  ```yaml
  pull_request:
    branches: [main]
  ```
  Pull requests opened against `exp/classifier-research-v2` (such as PRs #499, #500, #501, #519) never trigger `ci.yml` or `ci-draft.yml`. The only workflow listening on general PRs is `benchmark-dataset.yml`, which conditions its execution on `github.event.label.name == 'benchmark'`. Consequently, research PRs show "All checks were successful (0 successful, 1 skipped)" in `gh pr checks` without running any unit tests, typechecks, or linters.
- **Remediation**:
  - All research worker PRs must run full test suites locally (`uv run pytest tests/unit/benchmark/`) and ruff checks (`uv run ruff check` and `uv run ruff format --check`) and report verification logs directly in PR descriptions.

### Finding 6: Dataset Hash Discrepancy Resolution
- **Investigation**: PR #501's summary table listed `trips_sha256: 350bd7e2d6bf2b54e3ddc73651706b25fe4281cd4ab344f3675b2ecd3a4f0377`. However, the running corpus on disk (`/home/dat/releases_v2/trips.jsonl`), `manifest.json`, `checksums.json`, and committed baseline attempt `docs/data/experiments/attempts/E0.json` all specify `9986acd1b3cefd118f2696bd4ae3c3b3dd67e0ae210808792eae5e8fd8441d5d`.
- **Root Cause Provenance**: During orchestrator review round 3 of PR #501, the reviewer noted:
  > *"Verified on the full 40k build (sha 9986acd1…): mock_location_reported rate ERR-05 582/1200 = 0.485, no_violation 89/28000 = 0.003, all other classes 0."*
  The initial draft generation had hash `350bd...`. When kinematics were recalibrated to Hanoi/HCMC urban speeds and `mock_location_reported` shortcuts were calibrated, the 40k corpus was regenerated with seed `20261017`. The final committed artifacts and on-disk files match `9986acd1...`. The markdown description in PR #501 was simply not updated prior to merging.

---

## 3. Test Evidence

### Original Regression Coverage
The initial [integrity suite](../../tests/unit/benchmark/test_harness_metric_integrity.py) covered variant propagation, comparator parity, and token accounting:
1. `test_variant_omitting_model_used_counted_as_failure_in_live_mode`: Confirms untracked/missing models fail closed.
2. `test_live_calls_denominator_inferred_consistently`: Confirms denominator consistency and guardrail isolation.
3. `test_compare_rejects_mismatched_split`: Confirms rejection of cross-split comparisons.
4. `test_compare_rejects_mismatched_sample_size`: Confirms rejection of sample size discrepancies.
5. `test_compare_requires_paired_ci_half_width_when_best_present`: Confirms refusal when paired CI is omitted.
6. `test_calculate_input_tokens_uses_jev_input_and_respects_variant`: Confirms token accounting respects `jev_inp` and variant.

### Review Follow-up Evidence

The follow-up regression run first reproduced **17 failures and 11 passes** before the implementation changes. Failures covered soft guardrails, caller-supplied denominator dilution, malformed model attribution, and the placeholder chart fallback. Existing zero-live-call rejection remained passing.

After correction, the focused local suite passed **90 tests** with no skips. Full-repository `ruff check .` passed; `ruff format --check .` reported 684 files already formatted; `git diff --check` passed:

```bash
MPLCONFIGDIR=/tmp/greensentinel-pr527-matplotlib .venv/bin/python -m pytest \
  tests/unit/benchmark/ \
  tests/unit/services/test_jev_state_builder.py \
  tests/unit/services/test_jev_criteria.py -q
```

The [plotting regression](../../tests/unit/benchmark/test_experiment_staircase.py) verifies that missing matplotlib raises `ImportError` without creating artifacts. Existing chart tests render real SVG and PNG files with matplotlib installed. The placeholder SVG/empty PNG fallback introduced in the initial PR #527 patch was removed.

This is local unit/fixture evidence. Provider calls, bulk live evaluation, and hosted authenticated tests were not performed by this follow-up. PR #527 initially reported only a skipped `fetch-verify-benchmark` job; that is no lint or test proof. Research CI is tracked separately in [PR #526](https://github.com/AI20K-Build-Phase-Cohort-4/GreenSentinel/pull/526) and was not inherited when these checks ran.

Architecture decision: [ADR-029](../architecture/adr-029-harness-live-call-accounting.md). Historical delivery records: [worklog](../worklog/WORKLOG.md), [journal](../journal/JOURNAL.md).

---

## 4. Guidance for Parallel Workers (E1–E7)

1. **Variant Returns**: Ensure all variants return `model_used`, `fallback_reason`, and `http_status` extracted from `JevAssessmentResult`.
2. **Provider access and evidence**: Historical E0 recorded 942 heuristic fallbacks among 1,000 predictions and remains invalid as model-quality evidence. That historical result does not establish current credit exhaustion. The conductor reported three successful tiny generic probes (HTTP 200) on 2026-10-17: `typesafe/jev-1.14-20261014`, `perplexity/pplx-decider-flash-v1.2-20261016`, and `inception/mercury-decide-20260930`. Those probes show access/credits available for tiny requests only; they do not validate bulk capacity or classifier quality. Bulk benchmarking is currently blocked by automatic approval review of external data export, rather than demonstrated credit exhaustion. This follow-up made no provider calls.
3. **Paired Decisions**: Always generate `predictions.jsonl` and compare using `compute_paired_ci_from_predictions` on the identical 1,000 trips on `validation` split with `enum_blind=true`.

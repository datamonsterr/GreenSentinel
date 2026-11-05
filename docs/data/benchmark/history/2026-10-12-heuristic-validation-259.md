# Benchmark validation and versioned candidate comparison

> [!NOTE]
> **Superseded by [BENCHMARK.md](../../BENCHMARK.md)**.
> This document is retained for historical audit provenance (2026-10-12 heuristic frozen vs candidate comparison on issue #259).

Evidence recorded on 2026-10-12 for [issue #259](https://github.com/AI20K-Build-Phase-Cohort-4/GreenSentinel/issues/259). The original [benchmark report](2026-10-12-heuristic-30k.md) and v1 artifacts remain frozen. This report distinguishes a detector change on unchanged inputs from a separately generated v2 corpus. The source PR head reviewed is `45c1fc1fa77f3bbfbbfa5f8ff79f353bd80802f0`; the frozen detector is `e329dccbd2bb6526509f62b9dec28cd9de3bdadf`.

During delivery, upstream PR #258 advanced to `58a23051acf596a9c0fb11cfe5913d1b1dbb3ce4`, changing default dialogue generation and adding a different batch under the same `v2/` path. The follow-up integrates those additions as explicit `--profile feedback`, keeps default v1 generation frozen, and moves the evidence corpus to `profiles/evidence-v2`. The upstream `v2` feedback artifacts and their tests are retained. The detector comparisons below remain anchored to the frozen source revision; they do not claim acceptance of the new feedback batch.

## Measured results

Upstream subsequently advanced to `9ee7d2599156fb30dda758fdbd4574de71db1019` with G1/G2 scenarios and a recorded v3 batch. These additions are retained under explicit `--profile g1g2`; frozen v1 and feedback v2 remain separate. A fresh 10k G1/G2 build reproduces `8ba376474d2af19925eb160303f3cbf79dd370a5ce50089e04b54f1cb273fb1b` and its nine gates. The scenario/profile suite passes 93 tests. This is corpus reproduction proof; its historical detector metrics are not substituted for the candidate comparison below.

| Detector and corpus | Trips | Accuracy | Macro-F1, seven classes | Wall time |
|---|---:|---:|---:|---:|
| Frozen detector, unchanged v1 | 10,000 | 0.7043 | 0.5059 | 2.1 s |
| Candidate detector, unchanged v1 | 10,000 | 0.8391 | 0.6196 | 25.1 s |
| Candidate detector, opt-in v2 | 10,000 | 0.7039 | 0.6918 | 73.0 s |
| Candidate detector, v2 happy subset | 9,000 | 0.7507 | 0.7136 | Included above |
| Candidate detector, v2 stress subset | 1,000 | 0.2830 | 0.4863 | Included above |

Only the first two rows isolate the detector change. V2 changes input difficulty and available evidence, so its score is not a like-for-like improvement estimate. Timings were measured locally with concurrent verification work and are not controlled performance comparisons. Candidate mapping recomputes operational features rather than trusting stored feature summaries.

| Ground-truth class | Count | Frozen v1 F1 | Candidate v1 F1 | Candidate v2 F1 |
|---|---:|---:|---:|---:|
| no_violation | 7,000 | 0.8109 | 0.9269 | 0.7893 |
| ERR-01 | 500 | 0.9785 | 0.9806 | 0.9023 |
| ERR-02 | 800 | 0.9644 | 0.9577 | 0.8936 |
| ERR-03 | 500 | 0.0000 | 0.0000 | 0.6615 |
| ERR-04 | 300 | 0.0000 | 0.0000 | 0.2808 |
| ERR-05 | 300 | 0.3866 | 1.0000 | 1.0000 |
| insufficient_evidence | 600 | 0.4011 | 0.4717 | 0.3153 |

Machine evidence: metrics recorded in [notebooks/benchmark10k/metrics.json](../../../../notebooks/benchmark10k/metrics.json) (historical uncommitted artifacts: validation-259.json, candidate-v1/metrics.json, candidate-v2/metrics.json, candidate-v2/strata.json).

## Evidence boundaries and remaining weaknesses

- Timestamped positions supply speed, arrival, stationary duration and route geometry. Reported speed alone cannot establish fake GPS. On unchanged v1, ERR-05 false positives fall from 952 to zero; its 300 mock-provider fixtures remain detected.
- A recovered offline interval must be bounded by observations to at most 30 seconds. Long, unknown or sustained outages remain visible. Correctly classified honest v1 trips rise from 4,919 to 6,275; 725 still receive `insufficient_evidence`.
- V1 has no independent planned-route reference. All 500 historical ERR-03 labels remain unchanged and unclassified: 488 have unknown evidence sufficiency and 12 have blocked telemetry. DAVI alone is not route proof.
- Ghost-trip review requires completed lifecycle, observed pickup absence and an explicit passenger denial. Driver text, unattributed conversation, quoted statements and tested negations cannot provide that denial. V1 ERR-04 recall remains zero; v2 detects 49/300. Passenger phrase coverage and source ambiguity remain real limitations.
- V2 makes route comparison possible against an explicitly synthetic reference. Its 395 ERR-03 predictions contain 296 true positives and 99 false positives. The reference is not a measured shortest road route; these errors must not be hidden by changing labels.
- V2 has 2,481 blocked trips, including 715/1,000 stress trips. The stress subset exposes availability loss rather than proving production robustness.
- `label` remains synthetic ground truth. `evidence_sufficiency` is separately recorded as `blocked`, `unknown` or `available`, without consulting the ground-truth label. `available` means the current fallback emitted a category with known telemetry coverage; it is not a guarantee that every decision-relevant fact is present.
- Confidence remains `uncalibrated_model_confidence`. ECE/Brier are diagnostics for fixed heuristic scores. Neither synthetic class enrichment nor PaySim's synthetic financial-payment prevalence estimates ride-hailing prevalence. The historical `jev_calibrated_heuristic` identifier remains for compatibility, not as a calibration claim.

The architectural contract is [ADR-025](../../../architecture/adr-025-benchmark-evidence-boundaries.md). Predictions remain advisory; no sanction or dismissal action is added.

## Reproduction and corpus checks

V1 reproduces byte-for-byte: `b6aed4a2a6058c9bd6c4a002493f27254e70fcaba2f3df154b7931ed12a88154`. Its five gates pass, its exact class counts remain 7,000/800/600/500/500/300/300, and all 10,000 trips carry label provenance. A deterministic sample of five trips per class was read for conversation, driver objection, passenger report and telemetry coherence; no concrete contradictions were observed. Synthetic coherence does not establish external ground truth.

After reconciling the newer upstream changes, fresh full builds reproduce both frozen v1 and recorded feedback batch v2. The explicit feedback profile with seed 20261012 has SHA-256 `8675f823b27e0b79768e89ea4cc30834f59069ca155f1a891598fef75207c1b0`, matching its recorded manifest and sample; its five gates pass. Existing sparse-dialogue, feedback and customer-action checks remain in a dedicated profile suite. This preserves newer work without silently changing the frozen baseline.

The opt-in [v2 configuration](../../../../config/benchmark_distribution_v2.yaml) produces:

- 1,000 stress trips; 2,000 Porto trips; 2,000 sixteen-turn dialogues.
- 700 honest gridlock fixtures, including 21 controlled SSD >=180-second boundary fixtures. The 3% boundary fraction comes from a synthetic historical calibration, not a real traffic prevalence measurement.
- Persistent driver history from strictly earlier terminal operational events, with no current or future outcome or evaluation label. Driver splits are disjoint; observed trip shares are 6,942 train, 1,775 validation and 1,283 test because hashing assigns drivers rather than exact row quotas. No trained-model holdout result is claimed.
- Per-leg speed variation derived from pooled Porto quantiles with explicit interpolation and clipping assumptions. Second-city geometry remains synthetic.
- A nested Parquet export with schema, environment and hash metadata. All 10,000 rows round-trip exactly to their JSONL representations; Parquet size is 19.48 MB.

Two complete evidence-profile builds reproduce identical JSONL, Parquet, driver-ledger and sample bytes. JSONL SHA-256: `8ef959316f650320927db857bdfafdd9fec08e7771bf7f8c3805f64f942aa754`. All applicable gates pass; the stress gridlock-boundary gate is explicitly not applicable. The evidence-v2 profile manifest and sample (historical generation; successor profile evidence-v4 is tracked under [profiles/evidence-v4/](../../../../data/benchmark-10k/profiles/evidence-v4/)). Bulk JSONL, Parquet, ledger and predictions stay ignored.

Porto EDA was rerun against the existing licensed raw archive. Every substantive value matches the committed [profile](../../../../notebooks/porto/profile.json); four runtime fields differ. Raw EDA rows remain outside Git. Both benchmark schemas apply and roll back in a fresh disposable PostGIS 16 database created from the operational core schema. Constraints and nullability restore exactly; a rollback requiring non-null values refuses a null row without deleting it. This is scratch database proof, not hosted Railway proof.

Use the [manual runbook](../../../testing/manual/BENCHMARK_EVIDENCE.md) for clean-checkout commands. The environment for candidate data proof was Python 3.11.15, NumPy 2.4.6, PyYAML 6.0.3, PyArrow 26.0.0, Pydantic 2.14.0 and Shapely 2.2.0. Benchmark dependencies are declared in the `benchmark` extra and lockfile; CI requirements include PyArrow for the lossless export test.

## Verification and acceptance limits

The reconciled delivery checkout passed all 1,102 unit tests after G1/G2 integration. The previous `942482c` revision passed 1,079 units and 15 affected local integration tests, plus full remote CI; the new parent reconciliation receives a separate final CI run. The prior delivery snapshot passed 330 focused checks; current results additionally cover preserved upstream feedback and new profile coexistence regressions. The seeder requires explicit `DATABASE_URL` and keeps connection URLs out of logs. Quote, negation, evidence-status and profile coexistence regressions failed before their fixes. Ruff lint and formatting, whitespace checks and `uv lock --check` pass.

The required full `scripts/check.sh` reaches a pre-existing type error in unchanged `src/api/test_routes.py:569`: `Name "results" already defined on line 548`. New mapper typing errors are fixed and its target mypy check passes. No API, webapp or agent files were changed.

The first full CI unit run reported 1,054 passes and one GPS-jitter expectation failure. All 40 failing synthetic trips had valid jitter ratios and measured 45-second gaps; the new guardrail correctly blocked them. The corrected test retains its 95% gate and passes its complete 31-test suite. The next CI run passed units but exposed four integration fixtures that lacked measured stall coverage, lifecycle actors or continuous normal telemetry. The bounded repair adds those operational facts and a missing-evidence control; its 15-test suite passes on the reconciled checkout. Final remote CI is recorded separately and remains required for acceptance.

The Railway `greensentinel-benchmark-db` service exists in `caring-renewal/dev` and its TCP proxy list is empty. Live table and recorded-run row counts remain unverified because SSH reports `No registered SSH keys found.` No proxy or key was created. Historical credential revocation also remains unverified; current source removal is not revocation proof. Hosted authentication and live-model quality are not established by these local results. Therefore issue #259 is not reported as fully VALIDATED.

## Issue #281 — hardened evidence-v4 corpus and reliability gates

Independent EDA on evidence-v2 (#259) exposed four dataset-reliability gaps that made the 10k corpus gameable rather than a measurement instrument. The dataset-side hardening (issue #281) ships as a **new profile `evidence-v4`**; frozen v1/v2/v3 and evidence-v2 remain byte-identical and untouched.

| Reliability gap (evidence-v2) | Before | After (evidence-v4) | Gate |
|---|---|---|---|
| Enum latch: `(status, actor, reason) → label` | 3,100 trips single-label; cancelled recall 1.00 | 0/10,000 single-label cohorts; cancelled recall 0.44 (per-class 0.38–0.44) | enum-latch recall < 0.5 |
| Locale: city vs telemetry bbox | consistent in evidence-v2; gate missing | gate + `city`/`country`/`locale` metadata, locale gate 1.00 | locale consistency = 1.0 |
| Fare: cancelled trips carry completed fare | up to 3.7M VND/km on cancelled | no fare on cancelled; completed per-km ≤ 100k (model 12k + 12k/km) | fare coherence = 1.0 |
| Dialogue: template starvation | 1,225 unique / 96,043 (1.28%) | 53,801 unique (56.0%); held-out templates train/val/test disjoint | unique fraction > 5% |

Profile/schema: builder `build_10k_v2 --profile evidence-v4`; two full builds reproduce `trips_sha256` `8379d090a55650c5d476b0ad7edbe5668c276591ed4688c75f05ce6626923071`. All v4 gates and the pre-existing feature gates pass on both builds.

### Frozen-detector comparison (10k trips, offline heuristic)

| Detector × corpus | Accuracy | Macro-F1 |
|---|---:|---:|
| Frozen detector, baseline evidence-v2 | 0.7039 | 0.6918 |
| Frozen detector, evidence-v4 strict | 0.6233 | 0.5106 |
| Frozen detector, evidence-v4 enum-blind | 0.7144 | 0.5199 |

Strict accuracy drops below the 0.7043 v1 figure exactly because the enum latch is gone — the reliability gain, not a regression. Enum-blind isolates the telemetry/conversation-only floor: ERR-02/ERR-05/insufficient remain behavioral (recall 0.85/1.00/1.00 enum-blind), while ERR-01/ERR-04 keyword/enum paths lose their shortcut (recall 0.14/0.12 strict). Detector-side recovery is tracked by #260–#265, not this issue.

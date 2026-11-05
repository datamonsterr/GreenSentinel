# P-063 Ride-Hailing Fraud & Violation Benchmark Suite

This document serves as the **single canonical index** of all benchmark evaluations conducted across the P-063 project lifecycle. Entries are recorded in chronological order from the earliest 30k-era heuristic assessments to the final out-of-sample test split evaluation of the stacked research classifier.

**Review-budget limitation:** The saved R3D final evaluation reports `adverse_recall_at_budget=0.0`; all top 300 ranked test predictions were `insufficient_evidence` (378 such rows total). The 5% review budget therefore routes data-quality cases, not fraud cases, and requires a separate recovery queue. Variant artifact failures can silently yield uniform base probabilities while retaining a stacker label, so production integration requires artifact validation and explicit degradation provenance.

**Companion Documents:**
- **Current Dataset Card:** [DATASET.md](DATASET.md)
- **Reference Dataset Cards:** [DATASET_CARDS.md](DATASET_CARDS.md)
- **AutoResearch Loop & Staircase:** [AUTORESEARCH.md](AUTORESEARCH.md)
- **Overall Model Narrative:** [../CLASSIFICATION_MODEL.md](../CLASSIFICATION_MODEL.md)
- **Historical Benchmark Reports Archive:** [benchmark/history/](benchmark/history/)

---

## Benchmark Index Timeline

| # | Date | Milestone / Model | Corpus Reference | Mode | Primary Macro-F1 [95% CI] | Accuracy | `no_violation` FPR | Status & Validity |
|---|---|---|---|---|---|---|---|---|
| **1** | 2026-10-12 | Heuristic Detector (30k-era) | `v1`/`v2`/`v3` (30,000 trips) | Offline Strict | 0.4904 *(v1: 0.5059)* | 0.6801 *(v1: 0.7043)* | — | Historical baseline ([Archive](benchmark/history/2026-10-12-heuristic-30k.md)) |
| **2** | 2026-10-12 | Candidate Detector (Issue #259) | `evidence-v4` (`8379d090...`, 10k) | Offline Blind vs Strict | 0.5199 *(Strict: 0.5106)* | 0.7144 *(Strict: 0.6233)* | — | Hardened validation ([Archive](benchmark/history/2026-10-12-heuristic-validation-259.md)) |
| **3** | 2026-10-16 | `synthesized_vietnam_trip` | `vietnam_trip` (`c4c80903...`, 1k) | Offline Blind vs Strict | 0.4107 *(Strict: 0.7143)* | 0.8000 *(Strict: 0.9350)* | — | Vietnam OSRM road corridor pilot |
| **4** | 2026-10-17 | Round-1 Jev Decision Models | `releases_v2` (`9986acd1...`, 1k val) | Live Enum-Blind | 0.4737 [0.438, 0.508] *(E0)* | 0.6450 | 0.251 | **Contaminated**: 942/1,000 silent fallbacks |
| **5** | 2026-10-18 | Round-3 Decision Models | `releases_v2.1` (`d52e52ff...`, dev300) | Live Enum-Blind | **0.6372 [0.577, 0.685]** | 0.7533 | 0.275 | Mercury free + `classref` (PR #557) |
| **6** | 2026-10-18 | Trained Supervised Models | `releases_v2.1` (`d52e52ff...`, 6k val) | Offline Enum-Blind | **0.8705 [0.864, 0.877]** *(R3D)* | 0.9525 | **0.030** | R3D Stacker (PR #556) |
| **7** | 2026-10-18 | **FINAL Test Split Evaluation** | `releases_v2.1` (`d52e52ff...`, 6k test) | **Offline Enum-Blind** | **0.8680 [0.861, 0.875]** *(R3D)* | **0.9507** | **0.027** | **Final Out-of-Sample Production Result** |
| **8** | 2026-10-19 | Production deployment latency (R3D on Railway) | `releases_v2.1` (`cd008ee1...`, dev300) | Live Production API (`/assess`) | **0.8688** *(parity with offline)* | — | — | Railway prod (sfo) load test; infer p95 ≤ 50ms, server p95 ≤ 300ms met |

---

## 1. 2026-10-12: Heuristic Detector on 30k Corpus

- **Date**: 2026-10-12
- **Model ID**: `jev_calibrated_heuristic` (`JevAssessmentService._calibrated_heuristic`), tag `jev_calibrated_heuristic`. Rule-based offline heuristic detector.
- **Dataset Reference**:
  - `data/benchmark-10k/v1/trips.jsonl`: 10,000 trips, seed `20261011`, SHA-256 `b6aed4a2a6058c9bd6c4a002493f27254e70fcaba2f3df154b7931ed12a88154`
  - `data/benchmark-10k/v2/trips.jsonl` (feedback): 10,000 trips, seed `20261012`, SHA-256 `8675f823b27e0b79768e89ea4cc30834f59069ca155f1a891598fef75207c1b0`
  - `data/benchmark-10k/v3/trips.jsonl` (g1g2): 10,000 trips, seed `20261013`, SHA-256 `8ba376474d2af19925eb160303f3cbf79dd370a5ce50089e04b54f1cb273fb1b`
  - **Combined 30k Union**: 30,000 bundles, full census run ($0 LLM cost).
- **Evaluation Mode**: Offline, strict lifecycle cancellation enums visible.
- **Metrics**:
  - **v1 Baseline (10,000 trips)**: Accuracy **0.7043**, Macro-F1 **0.5059**, ECE **0.1496**, Brier **0.1734**.
    - Per-class F1: `no_violation` 0.8109, `ERR-01` 0.9785, `ERR-02` 0.9644, `ERR-03` 0.0000, `ERR-04` 0.0000, `ERR-05` 0.3866, `insufficient_evidence` 0.4011.
  - **Combined 30k Union (30,000 trips)**: Accuracy **0.6801**, Macro-F1 **0.4904**. (v2 batch acc 0.6778 / F1 0.4941; v3 batch acc 0.6583 / F1 0.4695).
- **Confusion Matrix (30k Union, rows=true, cols=pred)**:

```
                  no_viol  ERR-01  ERR-02  ERR-03  ERR-04  ERR-05  insuff
no_violation      [ 14273       0       0       0       0    2625    4102 ]
ERR-01            [     0    1427       0       0       0      73       0 ]
ERR-02            [     0       0    2004       0       0     108     288 ]
ERR-03            [     0       0       0       0       0      75    1425 ]
ERR-04            [   642       0       0       0       0      93     165 ]
ERR-05            [     0       0       0       0       0     900       0 ]
insufficient      [     0       0       0       0       0       0    1800 ]
```

- **Validity & Diagnostic Notes**:
  - Constant uncalibrated confidence scheme (0.0 for guardrail, 0.85 for cancellation, 0.95 for telemetry rules); ECE diagnoses the heuristic steps rather than a statistical model.
  - `ERR-03` and `ERR-04` were structurally unemittable (0% recall) because `measured_features` carried no planned route reference, and ghost trips lacked lifecycle denial integration.
  - High speed-spike false positives: 2,625 honest trips misclassified as `ERR-05`.
  - Archived in [benchmark/history/2026-10-12-heuristic-30k.md](benchmark/history/2026-10-12-heuristic-30k.md).

---

## 2. 2026-10-12: Evidence-v4 Hardened Validation (Issue #259 / #281)

- **Date**: 2026-10-12
- **Model ID**: Heuristic candidate detector vs frozen baseline.
- **Dataset Reference**:
  - `profiles/evidence-v4/trips.jsonl`: 10,000 trips, seed `20261011`, SHA-256 `8379d090a55650c5d476b0ad7edbe5668c276591ed4688c75f05ce6626923071`
  - Preceding `evidence-v2` profile: SHA-256 `8ef959316f650320927db857bdfafdd9fec08e7771bf7f8c3805f64f942aa754`
- **Evaluation Mode**: Offline, strict vs `--enum-blind` comparative audit.
- **Metrics**:
  - Candidate on unchanged v1: Accuracy **0.8391**, Macro-F1 **0.6196** (ERR-05 F1 1.000, no_violation F1 0.9269).
  - Candidate on opt-in v2: Accuracy **0.7039**, Macro-F1 **0.6918** (ERR-03 F1 0.6615, ERR-04 F1 0.2808).
  - Candidate on hardened `evidence-v4` (Strict): Accuracy **0.6233**, Macro-F1 **0.5106**.
  - Candidate on hardened `evidence-v4` (Enum-Blind): Accuracy **0.7144**, Macro-F1 **0.5199**.
- **Validity & Diagnostic Notes**:
  - Decoupled cancellation enum shortcuts per [ADR-025](../architecture/adr-025-benchmark-evidence-boundaries.md).
  - Unmasked that high strict-mode scores were inflated by models reading `driver_cancelled_unjustified` enums directly from lifecycle fields.
  - Mandated that future benchmarks evaluate in `--enum-blind` mode.
  - Archived in [benchmark/history/2026-10-12-heuristic-validation-259.md](benchmark/history/2026-10-12-heuristic-validation-259.md).

---

## 3. 2026-10-16: `synthesized_vietnam_trip` Corridor Benchmark

- **Date**: 2026-10-16
- **Model ID**: Frozen heuristic detector (`jev_calibrated_heuristic`), offline.
- **Dataset Reference**: `synthesized_vietnam_trip`, 1,000 trips, seed `20261015`, SHA-256 `c4c8090333d45543666b6c8ba8735df68b55d28b3a58e65860d5bfa780d6b412` (HF Hub revision `a914d500...`).
- **Evaluation Mode**: Offline, strict vs enum-blind side-by-side.
- **Metrics**:
  - **Strict Mode**: Accuracy **93.5%** (0.9350), Macro-F1 **0.7143**, ECE **0.0578**.
  - **Enum-Blind Mode**: Accuracy **80.0%** (0.8000), Macro-F1 **0.4107**, ECE **0.1488**.
- **Validity & Diagnostic Notes**:
  - First corpus grounded in real OpenStreetMap / OSRM corridors in Hanoi and Ho Chi Minh City ([[REF-OSM-VN]](DATASET_CARDS.md#ref-osm-vn)).
  - Stark divergence between strict (71.4% F1) and enum-blind (41.1% F1) reaffirmed the critical need for enum-blind benchmarking.
  - Documented in [SYNTHESIZED_VIETNAM_TRIP_394.md](SYNTHESIZED_VIETNAM_TRIP_394.md).

---

## 4. 2026-10-17: Round-1 Jev Decision Models (`~typesafe/jev-latest`)

- **Date**: 2026-10-17
- **Model ID**: `~typesafe/jev-latest` (resolved `typesafe/jev-1.14-20261014`), OpenRouter `/api/alpha/decisions`.
- **Dataset Reference**: `releases_v2`, 40,000 trips, seed `20261017`, SHA-256 `9986acd1b3cefd118f2696bd4ae3c3b3dd67e0ae210808792eae5e8fd8441d5d`. 1,000-trip validation split sample (E0–E5) and `dev300` (E6).
- **Evaluation Mode**: Live (`--live`), `--enum-blind`.
- **Metrics Across Attempts**:
  - **E0 (Baseline)**: Macro-F1 **0.4737 [0.438, 0.508]** *(Strict: 0.6698)*, FPR **0.251**, ECE **0.192**.
  - **E1 (Numeric State)**: Macro-F1 **0.4632 [0.428, 0.496]**, FPR **0.300**, ECE **0.264**.
  - **E2 (Natural Language)**: Macro-F1 **0.4540 [0.422, 0.487]**, FPR **0.292**, ECE **0.296**.
  - **E3 (Risk-Band Criteria)**: Macro-F1 **0.5352 [0.503, 0.570]**, FPR **0.281**, ECE **0.212**.
  - **E4 (Hybrid GBM + LLM)**: Macro-F1 **0.8419 [0.811, 0.869]**, FPR **0.000**, ECE **0.078** *(Offline 6k: 0.7791)*.
  - **E5 (Two-Stage Gate)**: Macro-F1 **0.4593 [0.426, 0.492]**, FPR **0.282**, ECE **0.177**.
  - **E6 (Compact dev300)**: Macro-F1 **0.4789 [0.419, 0.537]**, FPR **0.230**, ECE **0.258**.
- **Confusion Matrix: E0 Live Blind (1,000 trips)**:

```
                  no_viol  ERR-01  ERR-02  ERR-03  ERR-04  ERR-05  insuff
no_violation      [   525       0      22       5       2     147       0 ]  (F1: 0.787)
ERR-01            [    45       4       0       0       0       0       0 ]  (F1: 0.151)
ERR-02            [     0       0      82       0       0       0       0 ]  (F1: 0.882)
ERR-03            [    37       0       0       3       0       9       0 ]  (F1: 0.105)
ERR-04            [    26       0       0       0       2       2       0 ]  (F1: 0.118)
ERR-05            [     1       0       0       0       0      30       0 ]  (F1: 0.274)
insufficient      [     0       0       0       0       0       0      58 ]  (F1: 1.000)
```

- **Validity & Integrity Failure**:
  - **Contamination Unmasked**: Post-hoc review revealed that **942 out of 1,000 predictions in E0 were silent heuristic fallbacks** caused by OpenRouter credit and context limits ([HARNESS_INTEGRITY_REVIEW.md:136](HARNESS_INTEGRITY_REVIEW.md#4-guidance-for-parallel-workers-e1e7)).
  - Heavy prompt payload (~39,383 tokens/trip; raw maneuvers represented 84–93% of tokens); 5.2% of calls threw `max_tokens_exceeded`.
  - Led to strict harness gating in [PR #519](https://github.com/AI20K-Build-Phase-Cohort-4/P-063/pull/519) and [PR #527](https://github.com/AI20K-Build-Phase-Cohort-4/P-063/pull/527).

---

## 5. 2026-10-18: Round-3 Decision Models (Mercury Free + Pplx Fallback)

- **Date**: 2026-10-18
- **Model ID**: Default `inception/mercury-decide:free` (resolved `inception/mercury-decide-20260930`, $0 cost), fallback `perplexity/pplx-decider-flash-v1.2` ([PR #550](https://github.com/AI20K-Build-Phase-Cohort-4/P-063/pull/550)).
- **Dataset Reference**: `releases_v2.1` (`d52e52ff...`), evaluated on fixed `dev300` validation screening set (300 trips, seed `20261017`, SHA-256 `cd008ee10b22520fbd71598d1718d06cf9ba9a9f3af38ca8736a11019a9a9ed9`).
- **Evaluation Mode**: Live (`--live`), `--enum-blind`, rule-free evidence context.
- **Progression Iterations (dev300)**:
  - **R3A (Old Rule Context)**: Blind **0.5901 [0.512, 0.661]**, Strict **0.7077 [0.639, 0.763]**, FPR **0.049**, ECE **0.143**. 227 Mercury calls, 42 Pplx, 14 failed (context overflow). Failure rate 4.9% marked INVALID by failure gate.
  - **R3B (Pickup Null Bug)**: Blind **0.4248 [0.389, 0.454]**, Strict **0.5657**, FPR **0.358**.
  - **R3B Fix (Pickup Wired, No Anchors)**: Blind **0.3353 [0.297, 0.370]**, Strict **0.4786**, FPR **1.000** (flagged 190/300 trips as ERR-03 due to missing normal baseline).
  - **R3H (Phase Split: Approach vs Trip)**: Blind **0.4854 [0.424, 0.534]**, Strict **0.6029**, FPR **0.451**.
  - **R3H Phase + Train Medians (`evidence_classref`)**: Blind **0.6372 [0.577, 0.685]**, Strict **0.7113 [0.652, 0.763]**, FPR **0.275**, ECE **0.316**. Adopted as state default ([PR #557](https://github.com/AI20K-Build-Phase-Cohort-4/P-063/pull/557)). *(Note: PR #557 set default state_variant="evidence_classref", but JevAssessmentInput in code defaults criteria_variant="baseline" which still contains >=180s and >35% rules; benchmark research variant explicitly evaluated with criteria_variant="semantic").*
- **Confusion Matrix: R3H `evidence_classref` Blind (dev300, 300 trips)**:

```
                  no_viol  ERR-01  ERR-02  ERR-03  ERR-04  ERR-05  insuff
no_violation      [   148       0       2       9       9      36       0 ]  (F1: 0.802)
ERR-01            [     3      10       0       1       1       0       0 ]  (F1: 0.769)
ERR-02            [     1       1      21       0       2       0       0 ]  (F1: 0.875)
ERR-03            [     3       0       0       8       0       4       0 ]  (F1: 0.485)
ERR-04            [    10       0       0       0       2       0       0 ]  (F1: 0.154)
ERR-05            [     0       0       0       0       0      12       0 ]  (F1: 0.375)
insufficient      [     0       0       0       0       0       0      17 ]  (F1: 1.000)
```

- **Validity Notes**:
  - 100% audit provenance: 0 heuristic fallbacks, 0 failed calls, $0 LLM cost.
  - State token size compressed 16$\times$ (~1,470 tokens vs 38k–49k raw).
  - Caveat: `dev300` selection optimism (used to tune the prompt; test split scores lower).

---

## 6. 2026-10-18: Trained Supervised Models, Leak-Audited (R3C, R3F, R3D)

- **Date**: 2026-10-18
- **Model IDs**:
  - `R3C`: Clean LightGBM (37 audited features from raw telemetry, [PR #553](https://github.com/AI20K-Build-Phase-Cohort-4/P-063/pull/553))
  - `R3F`: Trajectory 1D-CNN (128-step resampled GPS sequence, [PR #552](https://github.com/AI20K-Build-Phase-Cohort-4/P-063/pull/552))
  - `R3D`: Stacker Meta-Learner (LightGBM over R3C + R3F OOF probabilities, [PR #556](https://github.com/AI20K-Build-Phase-Cohort-4/P-063/pull/556))
- **Dataset Reference**:
  - Primary: `releases_v2.1` (`d52e52ff...`), 6,000-trip validation split.
  - Cross-generator evaluation: `releases_v1` (`1a0f05b3...`), 6,000 validation trips.
- **Evaluation Mode**: Offline, enum-blind = strict (models do not ingest cancellation enums).
- **Validation Split Metrics (6,000 Trips)**:

| Model | Architecture | v2.1 Macro-F1 [95% CI] | v2.1 FPR | ECE | v1 Transfer Macro-F1 | v1 Transfer FPR |
|---|---|---|---|---|---|---|
| **R3C** | Clean LightGBM (37 features) | 0.8695 [0.863, 0.877] | 0.078 | 0.059 | 0.4024 | 0.524 |
| **R3F** | Trajectory 1D-CNN | 0.8171 [0.809, 0.824] | 0.0005* | 0.170 | 0.5562 | 0.056 |
| **R3D** | **Stacked LightGBM Meta-Learner** | **0.8705 [0.864, 0.877]** | **0.030** | **0.056** | **0.5347** | **0.246** |

*\*R3F validation FPR is 0.000476 (~0.05%, 2 false positives / 4,200 normal validation trips), rounded to 0.000 in earlier summaries. R3D validation ECE is 0.055917 (~0.056); 0.030209 is FPR.*

- **Confusion Matrix: R3D Stacker (Validation Split, 6,000 trips)**:

```
                  no_viol  ERR-01  ERR-02  ERR-03  ERR-04  ERR-05  insuff
no_violation      [  4077       0       0       0     127       0       0 ]  (F1: 0.966)
ERR-01            [     0     292       0       0       0       0       0 ]  (F1: 1.000)
ERR-02            [     0       0     493       0       0       0       0 ]  (F1: 1.000)
ERR-03            [     0       0       0     295       0       0       0 ]  (F1: 1.000)
ERR-04            [   160       0       0       0      21       0       0 ]  (F1: 0.128)
ERR-05            [     0       0       0       0       0     188       0 ]  (F1: 1.000)
insufficient      [     0       0       0       0       0       0     347 ]  (F1: 1.000)
```

- **Validity & Architectural Observations**:
  - Leak audit enforced: all features with univariate validation macro-F1 $> 0.30$ were dropped ([R3C_LEAK_AUDIT.md](experiments/R3C_LEAK_AUDIT.md)).
  - R3D meta-learner slashed false positive rate by $>60\%$ (0.078 $\to$ 0.030) compared to R3C alone.
  - Cross-generator transfer on `releases_v1` revealed significant drop (0.87 $\to$ 0.53), demonstrating generator-specific kinematic overfitting.

---

## 7. 2026-10-18: FINAL Evaluation on Held-Out Test Split (Used Once)

- **Date**: 2026-10-18
- **Model Evaluated**: **R3D Stacker** (LightGBM meta-learner over R3C Clean LightGBM + R3F Trajectory CNN out-of-fold probabilities). Compared with single-model components and the Mercury decision model.
- **Dataset Reference**: `releases_v2.1` (`d52e52ff...`), cold-storage **test split** (6,000 trips, disjoint driver grouping, seed `20261017`). Stratified 300-trip test sample evaluated for Mercury.
- **Evaluation Mode**: Offline enum-blind, live audit provenance, zero heuristic fallback.
- **Final Comparative Results**:

| Model Candidate | Sample Size | Macro-F1 [95% CI] | Accuracy | `no_violation` FPR | ECE | Per-Class F1 (no_viol / E01 / E02 / E03 / E04 / E05 / insuff) |
|---|---:|---|---|---|---|---|
| **R3D Stacker (Candidate)** | **6,000** | **0.8680 [0.861, 0.875]** | **0.9507** | **0.027** | **0.056** | 0.967 / 1.000 / 1.000 / 0.997 / 0.115 / 0.997 / 1.000 |
| R3C Clean LightGBM | 6,000 | 0.8618 [0.856, 0.869] | 0.9398 | 0.080 | 0.053 | 0.940 / 1.000 / 1.000 / 0.980 / 0.119 / 0.994 / 1.000 |
| R3F Trajectory CNN | 6,000 | 0.8205 [0.813, 0.828] | 0.9610 | 0.0005* | 0.170 | 0.977 / 0.900 / 0.948 / 0.978 / 0.000 / 0.940 / 1.000 |
| R3D Stacker (Test 300) | 300 | 0.8841 [0.851, 0.921] | 0.9600 | 0.034 | 0.061 | 0.966 / 1.000 / 1.000 / 1.000 / 0.222 / 1.000 / 1.000 |
| Mercury `evidence_classref` | 300 | 0.5155 [0.455, 0.575] | 0.5833 | 0.357 | 0.391 | 0.745 / 0.370 / 0.750 / 0.357 / 0.143 / 0.243 / 1.000 |
| Mercury (Strict Enums) | 300 | 0.6707 [0.600, 0.733] | 0.7033 | 0.353 | 0.326 | 0.781 / 0.706 / 0.800 / 0.581 / 0.581 / 0.247 / 1.000 |

*\*R3F test FPR is 0.000481 (~0.05%, 2 false positives / 4,159 normal test trips), rounded to 0.000 in integer summaries; not zero.*

- **Final Test Confusion Matrix: R3D Stacker (6,000 trips)**:

```
                  no_viol  ERR-01  ERR-02  ERR-03  ERR-04  ERR-05  insuff
no_violation      [  4046       0       0       1     112       0       0 ]
ERR-01            [     0     297       0       0       0       0       0 ]
ERR-02            [     0       0     492       0       0       0       0 ]
ERR-03            [     0       0       0     314       0       0       0 ]
ERR-04            [   165       0       0       0      18       0       0 ]
ERR-05            [     0       0       0       1       0     176       0 ]
insufficient      [     0       0       0       0       0       0     378 ]
```

- **Final Test Confusion Matrix: Mercury `evidence_classref` Enum-Blind (300 trips)**:

```
                  no_viol  ERR-01  ERR-02  ERR-03  ERR-04  ERR-05  insuff
no_violation      [   133       2       3       7      11      51       0 ]
ERR-01            [     3       5       2       0       5       0       0 ]
ERR-02            [     1       5      18       0       1       0       0 ]
ERR-03            [     7       0       0       5       0       4       0 ]
ERR-04            [     6       0       0       0       2       1       0 ]
ERR-05            [     0       0       0       0       0       9       0 ]
insufficient      [     0       0       0       0       0       0      19 ]
```

- **Final Conclusion & Production Assessment**:
  - The **R3D Stacker** is the **best in-generator candidate** within `releases_v2.1` (**0.8680 macro-F1, 2.7% FPR, 35ms latency, $0 cost** on held-out test drivers).
  - **Cross-Generator Transfer & Generalization Caveat**: R3D did **not** meet the cross-generator acceptance guard on `releases_v1` (macro-F1 **0.534732** vs R3F **0.556208**, FPR **0.246135**). R3D's small F1 advantage over R3C (0.8705 vs 0.8695 validation) has overlapping confidence intervals ([0.864, 0.877] vs [0.863, 0.877]); we do not claim statistical significance or absence of overfit. It is reported as the best candidate for `releases_v2.1`, but not a universally accepted production winner. Furthermore, "leak-audited" does not prove leak-free or real-world operational generalization; matched val/test alone demonstrates in-generator stability, not real-world deployment safety.
  - **Review-Budget Triage Disconnect**: In the saved R3D test evaluation, `adverse_recall_at_budget` is 0.0 because risk ranking by $1 - P(\text{no\_violation})$ places guardrail-emitted `insufficient_evidence` trips ($P(\text{no\_violation}) = 0.0$) at the top of the queue. All top 300 test predictions are `insufficient_evidence` (out of 378 total), consuming the entire 5% analyst review budget with data-quality outages rather than fraud cases. Production triage requires a separate data-recovery queue.
  - The decision model (`mercury-decide:free`) with `evidence_classref` is maintained in `JevAssessmentService` as an **advisory secondary opinion and customer dialogue reader**, but must not be used as the primary kinematic classifier.
  - The known limitation remains **`ERR-04` (ghost trip)** detection under enum-blind conditions (F1 0.115), requiring multimodal text evidence fusion in future iterations.

---

## 8. 2026-10-19: Production deployment latency (R3D on Railway)

- **Date**: 2026-10-19
- **Service & Deployment**:
  - Railway `p063-backend` production (region `sfo`).
  - Deployed 2026-10-19 by workflow run `39287451597` from `main`.
  - Model: `r3d-2026.10.18`.
  - Artifacts: HF `datamonsterr/p-063-r3d-classifier` @ `268003f795b2950893e9ef6a54b250dec13eeee6` (`r3c.txt` `0eb2e54522e8`, `r3f.onnx` `23e9d5a2b96a`, `stacker.txt` `1559cd14cd74`).
  - Artifact load time: **44.6 ms**.
  - Decision-model advisory: `inception/mercury-decide:free`.
- **Load Test Configuration**:
  - Test runner: [`scripts/loadtest/classifier_load_test.py`](../../scripts/loadtest/classifier_load_test.py).
  - Corpus: 300 `dev300` trips (`releases_v2.1` `dev300` sha256 `cd008ee10b22...`) per level.
  - Client location: Vietnam.
  - Baseline: `GET /health` baseline **465.5 ms** (network RTT dominates client latency).
  - Accuracy: Served macro-F1 **0.8688** at every level = offline benchmark parity.
  - Cold start server timing: `feat` **4.8 ms**, `infer` **11.4 ms**, `total` **16.6 ms**.
- **Load Test Latency & Throughput**:

| Concurrency | ok/errors | Throughput req/s | Client p50/p95/p99 ms | Server Total p50/p95/p99 ms | Inference p50/p95/p99 ms | Features p50/p95 ms |
|---|---|---|---|---|---|---|
| 1 | 300/0 | 3.79 | 237.8 / 395.1 / 545.3 | 10.6 / 56.5 / 129.8 | 2.5 / 6.6 / 8.8 | 7.2 / 53.1 |
| 4 | 300/0 | 13.27 | 264.9 / 511.1 / 620.3 | 15.3 / 78.4 / 268.5 | 4.0 / 19.7 / 27.0 | 8.7 / 73.9 |
| 8 | 300/0 | 23.19 | 308.4 / 532.4 / 824.4 | 18.9 / 114.1 / 242.2 | 4.8 / 23.9 / 41.1 | 9.6 / 89.2 |
| 16 | 300/0 | 30.89 | 455.0 / 879.5 / 1123.4 | 43.6 / 165.3 / 332.1 | 10.7 / 43.8 / 71.8 | 12.9 / 118.8 |

- **Advisory Layer (Mercury, Concurrency 4, 100 requests, 0 errors)**:
  - Advisory latency: p50 **364.0 ms** / p95 **522.2 ms** / p99 **1492.6 ms**.
  - Client latency: p50 **609.1 ms** / p95 **1068.8 ms**.
  - Advisory is optional per request and non-blocking in the worker.
- **Targets (ADR-030 / PROD_DESIGN)**:
  - Inference p95 $\le$ 50 ms: **MET** at all levels (max 43.8 ms at concurrency 16).
  - Server p95 $\le$ 300 ms: **MET** at all levels (max 165.3 ms at concurrency 16).
  - Error rate 0: **MET**.
  - Client-side p95 exceeds 300 ms only because of WAN RTT from Vietnam to sfo.
- **PR Preview Comparison (`pr-576`, 2026-10-19)**:
  - Server p95: 76 / 75 / 113 / 182 ms at concurrency 1 / 4 / 8 / 16.
  - Inference p95: 13 / 18 / 31 / 52 ms at concurrency 1 / 4 / 8 / 16.
  - Advisory: p50 497 ms / p95 1566 ms.
- **Known Gap**:
  - Issue [#601](https://github.com/AI20K-Build-Phase-Cohort-4/P-063/issues/601) (R3D misses violations on 1–3 point telemetry windows; mitigation planned).


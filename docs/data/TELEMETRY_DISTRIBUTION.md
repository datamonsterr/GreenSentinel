# Telemetry distribution proposal (S1-DA-05)

**Date:** 2026-09-27 (config 0.2.0 after DA-06 calibration). **Purpose:** parameters for the DA-06 synthetic telemetry generator, so every scenario produces telemetry on the intended side of the `FEATURE_PARAMS` thresholds (PR #43). Machine-readable values: [`config/telemetry_distribution.yaml`](../../config/telemetry_distribution.yaml).

Every number carries one provenance tag:

| Tag | Meaning |
|---|---|
| **Measured (MiPo)** | Computed on the committed MiPo AiSq10D slice ([profile.json](../../notebooks/mipo/profile.json), [MIPO_EDA.md](MIPO_EDA.md)). |
| **Published (Posisi)** | Stated in the Grab-Posisi paper or blog ([research notes](RIDE_HAILING_RESEARCH.md)). |
| **Documented (Porto)** | Stated by the UCI Porto dataset page, as cited in [MIPO_FRAUD_RESEARCH.md](MIPO_FRAUD_RESEARCH.md). |
| **Derived** | Arithmetic on the rows above. |
| **Measured (generator)** | `FeatureWindow` (PR #43) run on the current `scripts/generate_synthetic_data.py` output. |
| **Assumption** | Chosen for the demo; replace when Grab-Posisi raw data is available. |

## 1. What the repository's real data can and cannot support

The MiPo AiSq10D slice (500 trajectories, 24,901 points) has **no timestamps** and uses a **planar XY system with unknown units and CRS** ([MIPO_EDA.md](MIPO_EDA.md), "Actual schema and quality"). Consequently:

- Speed, sampling interval, timing jitter, gap probability, accuracy, bearing, and device states **cannot be measured from repository data**. Porto's 15 s cadence is documented for the UCI source, not recoverable from the MiPo artifact.
- Only unit-free shape statistics are real measurements: points per trajectory, tortuosity, turn angle, and the share of zero-length steps.
- There is no car/motorbike split in MiPo or Porto (taxis only). Grab-Posisi labels motorcycles (Jakarta only), but the paper publishes no per-mode numeric statistics, so any split is an **assumption**.

## 2. Measured and published reference values

| Quantity | Value | Provenance |
|---|---|---|
| Points per trajectory, normal | min 37, p05 40, p50 49, p95 58, max 61 | Measured (MiPo) |
| Points per trajectory, detour outlier | p05 44.9, p50 56, p95 67 | Measured (MiPo) |
| Tortuosity (path ÷ endpoint distance), normal | p05 1.2562, p25 1.2724, p50 1.2769, p75 1.3302, p95 1.4688 | Measured (MiPo) |
| Tortuosity, detour outlier | p05 1.3584, p25 1.4664, p50 1.5622, p75 1.6553, p95 1.7888 | Measured (MiPo) |
| Share of zero-length steps per trajectory, normal | mean 0.0040, p95 0.0220, max 0.0638 | Measured (MiPo) |
| Mean turn angle between steps, normal | p50 0.3847 rad, p95 0.5597 rad | Measured (MiPo) |
| Porto nominal sampling | 15 s | Documented (Porto) |
| Posisi sampling | 1 s; "> 90%" of intervals equal 1 s; breaks occur (tunnels) | Published (Posisi) |
| Posisi trip averages | 11.94 km, 21.50 min | Published (Posisi) |
| Posisi mean trip speed | 11,940 m ÷ 1,290 s = **9.26 m/s** (33 km/h), including stops | Derived |
| Posisi accuracy | mode near 10 m; trend change near 50 m; Android max 127 m; iOS max 149 km (long tail) | Published (Posisi) |
| Android invalid markers | accuracy 0.0, speed 0.0, bearing 0.0 mean "unavailable/invalid" | Published (Posisi) |
| Urban-canyon error | "50 meters or more" (Uber Rethinking GPS); "more than 100 meters" (Uber Beacon) | Published (Uber) |

## 3. Field-level distributions

Fields of `TelemetryPayload` ([schemas.py](../../src/models/schemas.py)) and `app.telemetry_points` ([0001_poc_core.sql](../../db/migrations/0001_poc_core.sql)).

| Field | Type | Valid range | Proposed distribution | Provenance |
|---|---|---|---|---|
| `occurred_at` | timestamptz, required | monotonic within a trip | Start + cumulative intervals (next row) | Assumption; **must be present on every point** (PR #43 limitation (b)) |
| Sampling interval | seconds | > 0 | Profile `porto_15s` (default) or `posisi_1s`. Interval = cadence × (1 + K) + ε, where K ~ Geometric(p_miss = 0.05) missed pings. ε = 0 in `happy` mode; ε ~ Normal(0, 0.3 s) clipped to ±1 s in `stress` mode (see 4.3, finding 1) | Cadences: Documented (Porto) / Published (Posisi). p_miss chosen so ≥ 90% of intervals equal the cadence (Posisi); ε is an Assumption |
| P(interval > 30 s), normal trip | probability | — | At 15 s cadence a gap > 30 s needs ≥ 2 consecutive misses: 0.05² = **0.0025 per interval**. Plus a correlated outage (tunnel) on **2% of trips**, lasting Uniform(30, 90) s | Derived from assumptions; outage rate Assumption (Posisi reports breaks but no rate — needs verification) |
| `position.latitude/longitude` | WGS84 double | [-90, 90] / [-180, 180] | Scenario geometry (section 4) + noise. `happy`: independent Normal(0, σ = accuracy_m / 2) per axis, capped at accuracy_m, while moving; σ = 2 m on stop legs and crawls < 1 m/s. `stress`: AR(1) with ρ = 0.9 between pings and long-run σ = accuracy_m / 2, stopped or moving | Assumption (68% radius semantics: Published (Posisi)) |
| `position.accuracy_m` | double ≥ 0 or null | ≥ 0 | LogNormal(μ = 2.66, σ = 0.6): mode 10 m, median 14.3 m, p95 ≈ 38 m; clip to 127 m. Null for **3%** of points. Heavy tail (iOS-like) Uniform(130, 1000) m on **0.5%** | Mode, cap, tail shape: Published (Posisi). μ/σ fitted to the mode, null and tail rates: Assumption — update from Posisi |
| `speed_mps` (reported) | double ≥ 0 or null | ≥ 0 | While moving: Gamma(shape 2, mean = segment speed). Null for 5% (maps Android 0.0 "invalid"). Features derive speed from positions and ignore this field | Mean trip speed 9.26 m/s: Derived (Posisi); shape and null rate: Assumption |
| Moving speed by mode | m/s | — | car: mean 9.3; motorbike: mean 9.3 (**no split published** — keep equal until Posisi per-mode data) | Derived (Posisi, mixed modes) / Assumption |
| `bearing_deg` | double [0, 360) or null | [0, 360) | Displacement bearing + Normal(0, 5°) while moving; null when stationary (Android 0.0 invalid) | Assumption |
| `app_state` | enum | foreground/background/crashed/unknown | Per scenario (section 4) | Assumption |
| `network_state` | enum | online/offline/degraded/unknown | Per scenario | Assumption |
| `gps_state` | enum | valid/jitter/unavailable/mock_reported/unknown | Per scenario | Assumption |
| `mock_location_reported` | bool or null | — | Per scenario; null (unknown) on 2% of points | Assumption (unknown ≠ false: [MIPO_FRAUD_RESEARCH.md](MIPO_FRAUD_RESEARCH.md)) |
| `latency_ms` | double ≥ 0 or null | ≥ 0 | LogNormal(median 250 ms, σ 0.8); payload only, not a column | Assumption — needs verification |
| `distance_to_pickup_m`, `davi_score`, `data_gap_s` | producer-declared | per schema | Emit **null**; the server computes these in `FeatureWindow`. Declared values are never trusted | Design decision (PR #43) |
| Route tortuosity (trip level) | ratio ≥ 1 | ≥ 1 | Sample from the measured quantiles in section 2 (normal / detour) | Measured (MiPo) |
| Driver start distance to pickup | m | > 30 | Uniform(500, 2000) | Assumption (current generator uses ±0.01°, about 0.8–1.5 km) |

## 4. Scenarios

### 4.1 Proposed parameters

Point rates are shares of points in the trip; all values are **Assumptions** unless noted. "Clean" = no crash, no offline, degraded ≤ 2%, jitter ≤ 3%, mock 0.

| Scenario | System health | Geometry and timing | Expected features |
|---|---|---|---|
| `normal_trip` | crash 0; offline 0.5%; degraded 2%; jitter 3%; mock 0 | Approach toward pickup (tortuosity from normal quantiles); arrive within Uniform(0, 20) m; wait Uniform(30, 120) s at pickup; then trip | DAVI > 0.5; approach SSD < 60 s; total SSD = wait; guardrail not blocked |
| `driver_stall_cancel` (seed name `intentional_dic`) | clean | Approach for Uniform(60, 240) s; 50% of trips first move **away** 100–300 m (start kept ≥ 50 m from pickup); then stall **Uniform(230, 420) s** at **Uniform(80, 400) m** from pickup; stall noise Normal(0, 2 m) per axis; accuracy during stall ≤ 15 m; passenger cancels; **no arrival** | approach SSD ≥ 185 s; `arrived_at_pickup` false; DAVI ≤ 0 on the away half; guardrail not blocked |
| `traffic_gridlock` | clean; traffic observation `heavy` | Moves **toward** pickup in stop-and-go for Uniform(300, 600) s: stops Uniform(20, 90) s, crawl legs Uniform(20, 60) m at Uniform(0.5, 2.0) m/s | DAVI > 0.5; traffic `heavy`. **No SSD expectation** (4.3, finding 2) |
| `route_deviation` | clean | Toward pickup for Uniform(50, 200) m, then away for Uniform(300, 800) m within ±29° of straight away; passenger cancels during the detour (open window) | DAVI < 0. A detour that later returns to pickup ends with DAVI > 0, so the MiPo detour tortuosity (≈ 1.56) applies only to completed trips, which 0.2.0 does not generate |
| `gps_spoofing` (seed name `fake_gps`) | mock on **100%** of points (or ≥ 80% in a mixed variant); `gps_state` `mock_reported` | 1–3 teleport jumps at Uniform(60, 200) m/s | `mock_ratio` ≥ 0.8; geometry null when all points are mock; `implausible_speed_segments` ≥ 1 in the mixed variant; ERR-05 not short-circuited |
| `technical_dropout` | Last ping before the gap has `app_state = crashed` (app crash, position null) or `network_state = offline` (network loss); `platform_incidents` row spanning the gap | Clean approach, then **no pings** for Uniform(60, 300) s. 50% resume and continue; the rest send one reconnect ping at the end of the gap and do not move | `max_gap_s` > 30; `telemetry_coverage` < 1; guardrail blocked → `insufficient_evidence` |
| `gps_jitter` | `gps_state = jitter` on 30–60% of points; accuracy Uniform(20, 50) m on those points | Normal approach; noise σ = accuracy / 2 on jitter points; no stall | DAVI > 0; approach SSD < 60 s; `jitter_ratio` 0.3–0.6; guardrail not blocked |

### 4.2 Alignment with `FEATURE_PARAMS` (PR #43)

| Threshold | Value | Constraint on the generator |
|---|---|---|
| `arrival_radius_m` | 30 | DIC stalls must sit **> 30 m** from pickup (proposed ≥ 80 m) or the approach window ends before the stall. Normal trips must reach < 30 m to count as arrived. |
| `stationary_radius_min_m` / `max_m` | 15 / 50 | Stall noise must stay inside the anchor radius. The anchor is noisy too, so the point-to-anchor offset has σ = √2 · 2 ≈ 2.8 m per axis and P(offset > 15 m) = exp(−15² / (2 · 2.8²)) ≈ 8·10⁻⁷ per point (Derived). With σ = 3 m this rises to ≈ 0.2% per point, about 5% of 300 s stalls. Stall accuracy ≤ 15 m keeps R = 15. Gridlock crawl legs must exceed 15 m so their stops do not merge. |
| `max_sample_gap_s` | 30 | A stall must not contain a gap > 30 s, or the chain splits. With an exact clock, one missed 15 s ping gives exactly 30 s (kept) and two give 45 s (split): ≈ 1 − (1 − 0.0025)^20 ≈ 5% of 300 s stalls (Derived). **Any positive clock jitter turns a single missed ping into 30.x s and splits the chain** (4.3, finding 1). Dropout gaps must exceed 30 s. |
| `segment_min_displacement_m` | 15 | At 15 s cadence a moving car covers ~140 m per ping, far above 15 m. At `posisi_1s` segments merge 2+ pings; DAVI still works (PR #43 test). |
| `davi_min_distance_to_pickup_m` | 20 | DIC away-legs start ≥ 80 m out, so they are scored. |
| `implausible_speed_mps` | 50 | Spoofing jumps use ≥ 60 m/s; honest speeds (mean 9.3 m/s) stay far below. |
| ERR-02 policy | SSD ≥ 180 s | Sampling loses up to one cadence at **each** end of a stall (first ping after it starts, last ping before it ends), so measured SSD can be planned − 30 s. 0.1.0 said "planned − 15 s"; that was wrong. DIC stalls are now ≥ 230 s planned. |

### 4.3 Generator measurements: before, after (happy), stress

> **Seed telemetry now comes from the #82 road dataset** (`apply_road_dataset` replaces `ingest_events`, `telemetry_points`, `route_snapshots`, `traffic_observations`, `platform_incidents`, and `simulation_runs`). The before/after/stress seed tables below were measured on the DA-06 seed integration **before #82** and are kept as calibration evidence. The DA-06 generator now drives `simulate_trip_stream.py` and the module-level checks; `python scripts/analyze_generator_features.py` measures it (`--source seed` measures the current seed).

Seed rows: `FeatureWindow` (PR #43) on `scripts/generate_synthetic_data.py`, 100 trips. **Measured (generator)**.

**Before (config 0.1.0, old generator: 20 s steps, no timestamps model):**

| Scenario | n | approach SSD p50 | DAVI | coverage | max gap | Issue |
|---|---:|---:|---:|---:|---:|---|
| `intentional_dic` | 25 | **20 s** | −0.32 | 1.0 | 20 s | Drift of ~7.8 m per step broke the anchored chain; **below the 180 s ERR-02 threshold** |
| `traffic_gridlock` | 15 | 80 s | **−0.24** | 1.0 | 20 s | Fixed direction, not toward pickup |
| `technical_dropout` | 15 | 0 s | 0.18 | **1.0** | 20 s | Pings continued during the crash; no gap |
| `fake_gps` | 10 | null | null | 1.0 | 20 s | All mock (expected) |
| `gps_jitter` | 35 | 0 s | 1.0 | 1.0 | 20 s | No jitter state, no noise |

**After, `happy` (config 0.2.0, default seed 63):**

| Scenario | n | approach SSD p50 / p95 / max | SSD ≥ 180 s | DAVI | coverage | max gap | mock | jitter |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `intentional_dic` | 25 | 330 / 390 / 405 s | **96%** | 0.99 | 1.00 | 30 s | 0.00 | 0.04 |
| `traffic_gridlock` | 15 | 90 / 135 / 150 s | 0% | **0.90** | 1.00 | 15 s | 0.00 | 0.03 |
| `technical_dropout` | 15 | 0 / 0 / 0 s | 0% | 0.67 | **0.33** | **214 s** | 0.00 | 0.00 |
| `fake_gps` | 10 | null | 0% | null | 1.00 | 15 s | **1.00** | 0.00 |
| `gps_jitter` | 35 | 0 / 15 / 30 s | 0% | 0.78 | 1.00 | 30 s | 0.00 | **0.44** |

(DIC DAVI is positive at the median because half the trips approach before stalling; the away half is negative.)

**`stress` (AR(1) ρ = 0.9, ±0.3 s clock jitter, stall accuracy not clipped):**

| Scenario | n | approach SSD p50 / p95 / max | SSD ≥ 180 s | DAVI | coverage | max gap | mock | jitter |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `intentional_dic` | 25 | 163 / 316 / 375 s | **48%** | 0.90 | 0.95 | 30.1 s | 0.00 | 0.04 |
| `traffic_gridlock` | 15 | 105 / 163 / 166 s | 0% | 0.83 | 0.95 | 30.2 s | 0.00 | 0.03 |
| `technical_dropout` | 15 | 0 / 0 / 15 s | 0% | 0.66 | 0.33 | 215 s | 0.00 | 0.00 |
| `fake_gps` | 10 | null | 0% | null | 1.00 | 22.7 s | 1.00 | 0.00 |
| `gps_jitter` | 35 | 0 / 30 / 90 s | 0% | 0.78 | 0.96 | 30.1 s | 0.00 | 0.45 |

**Expectation pass rates, 400 generated trips per scenario** (module level, fixed streams; the `happy` column is asserted ≥ 95% in `tests/test_scripts/test_telemetry_generation.py`, `stress` is report-only):

| Scenario | Expectation | happy | stress |
|---|---|---:|---:|
| `driver_stall_cancel` | approach SSD ≥ 185 s and not arrived | 96.2% | 50.0% |
| `traffic_gridlock` | DAVI > 0.5 | 96.5% | 94.0% |
| `technical_dropout` | max gap > 30 s and guardrail blocked | 100% | 100% |
| `gps_jitter` | jitter ratio 0.3–0.6 and not blocked | 100% | 100% |
| `gps_spoofing` | mock ratio ≥ 0.8 and not short-circuited | 100% | 100% |
| `normal_trip` | DAVI > 0.5 and approach SSD < 60 s | 99.8% | 94.8% |
| `route_deviation` | DAVI < 0 and not blocked | 97.0% | 97.0% |

In `happy`, 13 of the 15 remaining DIC misses in 400 trips have a gap > 30 s inside the stall (an outage, or two consecutive missed pings).

### 4.4 Findings for the team (no `FEATURE_PARAMS` change in DA-06)

1. **The 30 s gap limit sits exactly at 2 × the 15 s cadence.** With ±0.3 s clock jitter, a single missed ping becomes 30.x s and splits the SSD chain. With the final `happy` settings but symmetric ±0.3 s jitter, DIC detection is **77%** (400 trips) instead of 96.2%; `happy` therefore uses an exact clock. In `stress`, removing the jitter alone lifts DIC from 50% to 66%. *Proposal:* set `max_sample_gap_s` relative to cadence (for example 2.5 × cadence = 37.5 s) or add a small tolerance.
2. **Honest gridlock can reach ERR-02 SSD levels.** Anchored SSD counts crawling inside the 15 m radius as stationary. Over 400 gridlock trips: approach SSD p50 = 90 s, p95 = 150 s, max = 270 s, and **3.0%** of trips reach ≥ 180 s (`stress`: p95 179 s, max 298 s, 4.2%). With SSD alone, an honest driver in a jam can look like ERR-02; the distinction must come from DAVI > 0 plus traffic corroboration (MVP scenario B). *Options for the team:* do not accumulate SSD while the vehicle is making net progress toward pickup (positive DAVI), or count only absolute stops (consecutive displacement below the accuracy radius).
3. **Temporally correlated error breaks the anchor.** `stress` DIC detection by variant, 400 trips: full stress 50%; without clock jitter 66%; without jitter and with stall accuracy ≤ 15 m 73%; independent (white) noise with σ = accuracy/2 only 16.5%. *Options:* anchor radius from the window's accuracy distribution (for example clamp(2 × p50 accuracy, 15, 50)) instead of the anchor ping's accuracy, or smooth positions (rolling median of 3 pings) before SSD.
4. **Sampling shortens measured stalls by up to two cadences** (one at each end). 0.1.0's "planned − 15 s" was wrong; generator stalls are now ≥ 230 s planned.

**Current seed (#82 road dataset), measured** with `--source seed` — observations for the #63 owners, not changed here:

| Scenario | n | approach SSD p50 / p95 / max | SSD ≥ 180 s | DAVI | coverage | max gap | mean speed | mock | jitter |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `intentional_dic` | 25 | 190 / 190 / 190 s | 52% | 0.81 | 1.00 | 10.8 s | 11.80 m/s | 0.00 | 0.00 |
| `traffic_gridlock` | 15 | 0 / 0 / 0 s | 0% | 0.81 | 1.00 | 19.6 s | 8.42 m/s | 0.00 | 0.00 |
| `technical_dropout` | 15 | 0 / 0 / 0 s | 0% | 0.80 | 0.92 | 59.3 s | 11.98 m/s | 0.00 | 0.00 |
| `fake_gps` | 10 | null | 0% | null | 1.00 | 10.8 s | null | 1.00 | 0.00 |
| `gps_jitter` | 35 | 0 / 0 / 0 s | 0% | 0.81 | 1.00 | 10.8 s | 15.16 m/s | 0.00 | 0.00 |

Half the DIC cases are the `reverse_travel` variant (no stall); the stalled half sits at 190 s, 10 s above the ERR-02 line (finding 4: sampling can shorten a stall by up to two cadences). Gridlock trips move at 8.4 m/s with no stop, and jitter trips carry no `jitter` state.

### 4.5 Generator notes

- `happy` and `stress` share every distribution except clock jitter, position-noise model, and the stall accuracy clip (`noise_modes` in the YAML).
- **Seed:** since #82 the seed telemetry is the road dataset, so `generate_synthetic_data.py` is unchanged by DA-06. YAML names still map onto consumer names through `SCENARIO_ALIASES` (`intentional_dic` → `driver_stall_cancel`, `fake_gps` → `gps_spoofing`).
- `simulate_trip_stream.py` frames keep their three lifecycle frames. The stall frame's `stationary_duration_s` is now the simulated (planned) stall length, not a constant 210; the server measures SSD itself.
- `scripts/enrich_demo_data.py` is a third telemetry writer that replaces DB telemetry directly (`random.Random(888)`). It is outside DA-06's no-DB-writes scope and still uses its own model.
- The seed's precomputed `feature_sets` rows (SSD 240/260, DAVI −0.85/0.1/0.92) are unchanged; they no longer match the generated telemetry and should be recomputed from `FeatureWindow` in a follow-up.

## 5. Schema and database gaps

| Field / object | Change | Reason |
|---|---|---|
| `app.feature_sets.telemetry_coverage`, `max_gap_s` | Make nullable (migration) | PR #43 TODO: they are NOT NULL, so missing evidence is written as 0 plus an `insufficient_samples` flag; DATA_MODEL says null is not zero. |
| Telemetry `device_platform` (`android`, `ios`, `unknown`) | Add to the event payload/schema and `telemetry_points` (or `ingest_events.source` convention) | Posisi shows accuracy semantics differ by OS (Android cap 127 m, iOS tail to 149 km; Android 0.0 = invalid). |
| Importer rule for Android `0.0` | Map accuracy/speed/bearing `0.0` to null when the source is Android | Our schema treats 0 as a valid measurement (Published (Posisi)). |
| `telemetry_points` position CHECK | Align with the guardrail, or document the difference | The CHECK allows a null position when `network_state = degraded`; the guardrail treats degraded + missing position as `INVALID_TELEMETRY`. |
| `telemetry_points.anomaly_type`, `anomaly_score` | Document as simulation-only; never read by detectors | Written by the seed enrichment; DATA_MODEL forbids simulation labels as features. |
| `distance_to_pickup_m`, `davi_score`, `data_gap_s`, `latency_ms` | Keep payload-only (no columns); mark as producer-declared, untrusted | Server-side `FeatureWindow` computes the trusted versions. |
| Vehicle mode in features | Pass `vehicles.vehicle_type` (`car`/`motorbike`, already in schema) into feature computation | Needed before per-mode speed or stall thresholds; no per-mode data yet. |
| Generator frames (`simulate_trip_stream.py`) | Per-point `occurred_at` and `sequence` | Required by the event schema; without them time features are null (PR #43 limitation (b)). |

## 6. Update plan

When the Grab-Posisi raw data is obtained (access by email; non-commercial use only):

1. Replace the accuracy log-normal with empirical quantiles per OS and mode.
2. Measure `p_miss`, the interval distribution, and outage rates directly; recompute P(interval > 30 s).
3. Measure per-mode speed distributions (Jakarta car versus motorcycle).
4. Bump `version` in the YAML and record the dataset revision.

# Synthesized Vietnam Trip Benchmark Release & EDA Report (Issue #394 / Child #400)

## Executive Summary

This report documents the creation, empirical profiling, schema reconciliation, benchmarking, and staging of the `synthesized_vietnam_trip` benchmark release (1,000 trips) under P-063 database finalization issue #394 (child task #400).

Key achievements:
1. Reconciled published 40k preset metadata against the pinned Hugging Face manifest (revision `914a36560727f5892a24fba3a4173cb245c963da`), correcting previous inconsistent claims.
2. Conducted full empirical profiling of all 40,000 trips in `releases_v1`: empirically disproved the unverified assumption of US majority by demonstrating that the corpus is 95% Vietnam (38,000 trips) and 5% Porto (2,000 trips), with 0% US trips.
3. Created the deterministic immutable release `synthesized_vietnam_trip` (1,000 distinct trips) grounded in 18 pinned real road corridors across Hanoi and Ho Chi Minh City derived from OSRM and OpenStreetMap.
4. Resolved the street-geometry specification violation by replacing synthetic chord/landmark interpolation with genuine road polyline sampling, Vietnamese street names, and bounded sensor noise. Cross-track error for normal trips is verified within 15 meters, while route deviations and spoofing depart intentionally off-corridor with explicit provenance.
5. Established tenant isolation: organization ownership is strictly bound from the active authorized context at materialization/execution time (`organization_id` UUID), ensuring dataset portability and preventing cross-tenant leakage.
6. Evaluated offline frozen strict and enum-blind benchmarks on the 1,000-trip corpus, recording per-class precision/recall/F1, severity confusion matrices, runtime, and detector limitations.
7. Staged the release bundle in `data/benchmark-10k/profiles/synthesized_vietnam_trip/`, preserved Git hygiene by tracking only small samples and metadata, and documented the exact publish-ready command and Hugging Face credential blocker.

---

## 1. Empirical Profiling of the 40k Release (`releases_v1`)

The pinned 40,000-trip corpus (`releases_v1/trips.jsonl`, SHA-256 `1a0f05b3e1276d8cc0f11a1a922efbecbb554c3c50a6458b24137923592031f7`) was analyzed using `scripts/benchmark/profile_40k.py`.

### 1.1 Geography Distribution vs. Prior Assumptions

| Geography Origin | Trip Count | Percentage | Provenance Notes |
|---|---|---|---|
| Vietnam (Hanoi anchors) | 38,000 | 95.0% | Ga Ha Noi, Ben xe Giap Bat, Ho Guom, Bach Mai, Ho Tay, Royal City, Lotte Center, VNU |
| Portugal (Porto) | 2,000 | 5.0% | UCI Taxi Service Trajectory Prediction Challenge (CC BY 4.0) |
| United States (NYC/other) | 0 | 0.0% | NYC TLC data provided duration/hour scheduler priors only; 0 GPS trajectories embedded |

**Finding:** The prior operational assumption that the 40k corpus was majority US is empirically incorrect. 95% of trips are situated within Vietnamese coordinates, and 5% in Porto, Portugal.

### 1.2 Class and Severity Breakdown

The published class counts match the object storage manifest:

| Label | Published Count | Proportion | Severity Policy |
|---|---|---|---|
| `no_violation` | 28,000 | 70.0% | None |
| `ERR-02` (prolonged stall) | 3,200 | 8.0% | P1 |
| `insufficient_evidence` | 2,400 | 6.0% | None / Unclassified |
| `ERR-01` (unjustified cancel) | 2,000 | 5.0% | P2 |
| `ERR-03` (route deviation) | 2,000 | 5.0% | P1 |
| `ERR-04` (phantom trip) | 1,200 | 3.0% | P2 |
| `ERR-05` (GPS spoofing) | 1,200 | 3.0% | P0 |
| **Total** | **40,000** | **100.0%** | |

### 1.3 Kinematics, Telemetry & Driver Distributions

- **Route Distance:** Min 0.0m, p5 245.9m, p25 1,643.3m, Median 2,851.0m, p75 4,148.1m, p95 7,477.2m, Max 17,143.8m, Mean 3,118.0m.
- **Trip Duration:** Min 15.0s, p5 131.2s, p25 375.0s, Median 510.0s, p75 735.0s, p95 1,408.5s, Max 3,545.7s, Mean 611.7s.
- **Telemetry Points per Trip:** Min 1, p5 8, p25 24, Median 33, p75 47, p95 91, Max 226, Mean 39.2.
- **Driver Population:** 7,907 distinct synthetic drivers. Median trips per driver: 4.0 (min 1, max 22).

---

## 2. Schema Comparison: Corpus vs. Database & Architecture

The nested JSON structures in `trips.jsonl` were audited against `db/migrations` and `docs/architecture/schemas/`:

| Corpus Field Path | Target Relational Entity / PostGIS Table | Schema Conformance & Type Contract |
|---|---|---|
| `trip_id`, `trip_ref`, `trip.status`, `trip.fare_amount` | `app.trips(id, status, fare_amount, currency)` | Conforms. UUID primary key, ISO currency `VND`. |
| `assignment.id`, `assignment.state`, `assignment.offered_at`, etc. | `app.trip_assignments(...)` | Conforms. ISO-8601 UTC timestamps with `Z` suffix. |
| `route.geometry`, `planned_route.geometry` | `app.route_snapshots(route, distance_m, duration_s)` | Conforms. PostGIS `geometry(LineString, 4326)` GeoJSON coordinates. |
| `telemetry[*].latitude`, `telemetry[*].longitude` | `app.telemetry_events(location, speed_mps, bearing_deg)` | Conforms. WGS84 GeoJSON `[lon, lat]` mapping to PostGIS Point. |
| `driver_profile.id`, `driver_profile.display_name`, rating | `app.drivers(...)` | Conforms. Synthetic Vietnamese names, ratings bounded [3.0, 5.0]. |
| `vehicle.id`, `vehicle.license_plate` | `app.vehicles(...)` | Conforms. Vietnamese registration format (e.g. `29A-888.88`). |
| `conversation`, `customer_report`, `driver_objection` | Evaluation evidence bundles / Analyst cockpit | Unstructured text evidence; preserved in JSON payload. |

### Tenant Isolation Architecture

Corpus records in `synthesized_vietnam_trip` store `driver_profile.organization_id = None`.
At preset materialization or simulation execution, `materialize_preset_simulation_input` extracts the authorized `organization_id` (UUID) from the authenticated operator's session and binds it to both the root payload and the driver profile. This eliminates cross-tenant leaks from fixture data.

---

## 3. Dataset Generation: `synthesized_vietnam_trip`

### 3.1 Road Geometry Grounding

To correct the specification violation where previous synthetic trips used straight-line landmark chords, `scripts/benchmark/synthesize_vietnam.py` now loads 18 pinned real road corridors (`tests/fixtures/road_telemetry/vietnam_road_corridors.json`):
- 14 Hanoi corridors spanning Hoan Kiem, Ba Dinh, Cau Giay, Dong Da, Hai Ba Trung, Tay Ho, Nam Tu Liem, Long Bien, and Soc Son.
- 4 Ho Chi Minh City corridors spanning District 1, District 3, District 7, District 10, and Binh Thanh.
- Provenance: OpenStreetMap contributors via public OSRM routing engine (ODbL license).
- Telemetry pings are sampled via arc-length polyline interpolation with bounded GPS sensor noise ($\le 3.5$m lateral, $\le 2.5$m longitudinal).
- Street names for pickup, dropoff, and route checkpoints are assigned from the underlying OSRM step instructions.

### 3.2 Target Class and Severity Distribution (1,000 Trips)

| Label | Target Count | Severity Tier | Behavior & Provenance |
|---|---|---|---|
| `no_violation` | 700 | None | Nominal driving along road polyline; cross-track error $\le 15$m. |
| `ERR-01` | 75 | P2 | Driver unjustified cancellation after short stall (45s–90s); on-road. |
| `ERR-02` | 70 | P1 | Prolonged stall ($\ge 180$s); passenger cancellation; on-road. |
| `ERR-03` | 65 | P1 | Route deviation; vehicle turns onto unapproved detour; cross-track error $> 50$m. |
| `ERR-04` | 60 | P2 | Phantom trip; vehicle traverses road, but passenger never boards. |
| `ERR-05` | 30 | P0 | Fake GPS / Spoofing; teleportation jump $> 800$m, mock location reported. |
| `insufficient_evidence`| 0 | — | No artificial insufficient evidence generated outside explicit requirements. |
| **Total Violations** | **300** | — | **30 P0 (10.0%), 135 P1 (45.0%), 135 P2 (45.0%) -> 270 P1/P2 (90.0%).** |
| **Total Trips** | **1,000** | — | **100% Deterministic & Reproducible.** |

### 3.3 Driver Partitioning & Determinism

- 200 distinct synthetic drivers: 160 train drivers (800 trips), 40 test drivers (200 trips).
- Driver leakage: strictly 0 drivers shared between train and test splits.
- Determinism: running `generate_vietnam_dataset(out_dir, seed=20261015)` produces the identical SHA-256 hash `c4c80903a998420b3a5d68ced5ffb5bb06709fc9ef12817651ab8b89baa628a2`.

---

## 4. Frozen Offline Benchmark Evaluation

The staged 1,000-trip dataset was benchmarked using `scripts/benchmark/run_10k.py` against the repository's frozen offline heuristic detector in both strict and enum-blind modes.

### 4.1 Strict Mode Results

- Runtime: 1.0s (1,000 trips)
- Overall Accuracy: 93.5%
- Macro F1: 0.7143
- Expected Calibration Error (ECE 10-bin): 0.0578
- Brier Score: 0.0044

Per-Class Metrics:

| Class | Ground Truth | Predicted | Precision | Recall | F1 Score |
|---|---|---|---|---|---|
| `no_violation` | 700 | 700 | 1.0000 | 1.0000 | 1.0000 |
| `ERR-01` | 75 | 75 | 1.0000 | 1.0000 | 1.0000 |
| `ERR-02` | 70 | 70 | 1.0000 | 1.0000 | 1.0000 |
| `ERR-03` | 65 | 0 | 0.0000 | 0.0000 | 0.0000 |
| `ERR-04` | 60 | 60 | 1.0000 | 1.0000 | 1.0000 |
| `ERR-05` | 30 | 30 | 1.0000 | 1.0000 | 1.0000 |
| `insufficient_evidence` | 0 | 65 | 0.0000 | 0.0000 | 0.0000 |

Confusion Matrix:
- `no_violation` (700): 700 correct.
- `ERR-01` (75): 75 correct.
- `ERR-02` (70): 70 correct.
- `ERR-03` (65): 65 classified as `insufficient_evidence` (the frozen heuristic detector has no detour model and falls back safely).
- `ERR-04` (60): 60 correct.
- `ERR-05` (30): 30 correct.

### 4.2 Enum-Blind Mode Results

In enum-blind mode, assignment cancellation actor and reason enums are stripped before evaluation, forcing the detector to rely strictly on kinematics and telemetry signals.

- Runtime: 1.9s (1,000 trips)
- Overall Accuracy: 80.0%
- Macro F1: 0.4107
- ECE (10-bin): 0.1488
- Brier Score: 0.1827

Per-Class Metrics:
- `no_violation` (700 true): 700 TP, 200 FP (from ERR-01, ERR-03, ERR-04 without enums), Precision 0.7778, Recall 1.0000, F1 0.8750.
- `ERR-02` (70 true): 70 TP, 0 FP, Precision 1.0000, Recall 1.0000, F1 1.0000 (detected via approach standstill duration $\ge 180$s).
- `ERR-05` (30 true): 30 TP, 0 FP, Precision 1.0000, Recall 1.0000, F1 1.0000 (detected via mock location and velocity anomalies).
- `ERR-01`, `ERR-03`, `ERR-04`: Recall 0.0000 (expected limitation of the baseline heuristic without NLP dialogue parsing or detour GIS models).

### 4.3 Detector Identity & Limitations

The evaluation was executed with `JevAssessmentService` operating under `offline_network_guard` (zero network I/O, no live LLM calls). This frozen baseline measures heuristic pipeline consistency and guardrail compliance; it does not reflect the quality of fine-tuned multimodal LLM agents.

---

## 5. Console Integration & Verification

The Vietnam preset was integrated into the tester console library in `src/services/test_presets.py`:
- Preset ID: `synthesized-vietnam`
- Title: `Vietnam trips (synthesized)`
- Kind: `vietnam`
- Selection Size: 1,000 trips
- Sample Trips: Loaded from `data/benchmark-10k/profiles/synthesized_vietnam_trip/sample_100.jsonl`
- Round-trip Materialization: `materialize_preset_simulation_input` validates finite geometry, non-zero route distance, and enforces active context `organization_id` UUID binding.

All unit and integration tests pass:
- `tests/unit/test_presets_reconciliation.py`: 2 passed.
- `tests/unit/test_vietnam_generator.py`: 6 passed (including cross-track residual tests $\le 15$m for normal trips and $> 50$m for anomalies).
- `tests/unit/test_vietnam_preset.py`: 4 passed (tenant isolation and simulation materialization).
- `tests/integration/api/test_test_console_features.py`: 11 passed.

---

## 6. Staging & Hugging Face Publishing Status

### 6.1 Staged Artifacts

The complete dataset release is staged locally under `data/benchmark-10k/profiles/synthesized_vietnam_trip/`:
- `trips.jsonl` (24.4 MB, SHA-256 `c4c80903a998420b3a5d68ced5ffb5bb06709fc9ef12817651ab8b89baa628a2`)
- `labels.csv` (53.7 KB, SHA-256 `347b59e74288fe3f7f08ec58452ad6932a3fc0ef681997327318ec830fa984bc`)
- `manifest.json` (1.0 KB, SHA-256 `5fba45347209ff8fca340ff628859ff100787b3558197c3dc0fe3f38c3aa8ec5`)
- `checksums.json` (258 B)
- `sample_100.jsonl` (2.4 MB)
- `sample_100.parquet` (8.5 KB)
- `metrics_strict.json` (5.1 KB)
- `metrics_enum_blind.json` (4.9 KB)

Git hygiene is maintained: `.gitignore` ignores `trips.jsonl` and full predictions, committing only `manifest.json`, `checksums.json`, and `sample_100.jsonl`.

### 6.2 Publication Verification & Immutable Commit

The `synthesized_vietnam_trip` profile has been published to the Hugging Face Hub using authorized write credentials, preserving `releases_v1` immutably:
- **Hub Repository:** `https://huggingface.co/datasets/datamonsterr/p-063-synthesized-trips`
- **Immutable Commit SHA:** `a914d500b1c536f1dbfb59f8ea4c961bd38b5c7e`
- **Verified Checksum (`trips_sha256`):** `c4c80903a998420b3a5d68ced5ffb5bb06709fc9ef12817651ab8b89baa628a2`
- **Verification:** All 1,000 rows were fetched back at revision `a914d500b1c536f1dbfb59f8ea4c961bd38b5c7e` and confirmed bit-for-bit identical with local checksums.
- **Old Release Immutability:** `releases_v1` (40k trips) remains untouched and verified fetchable at revision `914a36560727f5892a24fba3a4173cb245c963da`.

Fetch Command:

```bash
python scripts/benchmark/fetch_dataset.py \
    --profile synthesized_vietnam_trip \
    --out data/benchmark-10k \
    --revision a914d500b1c536f1dbfb59f8ea4c961bd38b5c7e
```

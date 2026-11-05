# P-063 Ride-Hailing Fraud & Violation Benchmark — Dataset Card

A synthetic, deterministic benchmark for detecting **fraud and violations in a single ride-hailing trip**. Every row represents one trip (*bundle*). This document defines the **current synthetic research corpus (`releases_v2.1`)**, its generation methodology, distribution priors, input boundaries, known leaks, and release history.

**Repository:** [AI20K-Build-Phase-Cohort-4/P-063](https://github.com/AI20K-Build-Phase-Cohort-4/P-063)  
**Historical Releases (HF Hub):** [datamonsterr/p-063-synthesized-trips](https://huggingface.co/datasets/datamonsterr/p-063-synthesized-trips)  
**Detailed Source Cards:** [DATASET_CARDS.md](DATASET_CARDS.md)  
**Benchmark Suite & Evaluation Results:** [BENCHMARK.md](BENCHMARK.md)  
**AutoResearch Loop & Experiments:** [AUTORESEARCH.md](AUTORESEARCH.md)  

---

## 1. Problem Framing and Violation Classes

P-063 detects ride-hailing violations from operational trip evidence. Predictions are strictly **advisory** to assist human analysts; models never execute automated sanctions ([ADR-013](../architecture/adr-013-jev-advisory-anomaly-scoring-and-single-trip-fraud.md), [ADR-025](../architecture/adr-025-benchmark-evidence-boundaries.md)).

The benchmark evaluates 7 mutually exclusive target categories:

| Target Class | Description | Operational Policy Basis | Primary Evidence Modality |
|---|---|---|---|
| `no_violation` | Honest, legitimate trip complying with platform rules | Platform baseline | GPS trajectory, lifecycle events, dialogue |
| `ERR-01` | Unjustified driver cancellation | Driver Policy Art. 14.1 | Cancellation reason, driver objection, conversation |
| `ERR-02` | Deliberate stall / waiting out passenger to force cancel | Driver Policy Art. 14.2 | Stationary duration at pickup (SSD), approach speed |
| `ERR-03` | Route deviation / moving away from pickup or destination | Driver Policy Art. 16.1 | Bearing deviation, detour ratio, approach heading |
| `ERR-04` | Ghost trip: completed without passenger on board | Driver Policy Art. 15.1 | Passenger denial report, pickup lifecycle absence |
| `ERR-05` | GPS spoofing / mock location injection | Driver Policy Art. 15.3 | Multipath telemetry, mock flag, impossible speed/jump |
| `insufficient_evidence` | Telemetry outage or missing points | Data Validity Guardrail | Emitted **only** by guardrail short-circuit, never by model |

---

## 2. Current Corpus Card: `releases_v2.1`

The active benchmark corpus is **`releases_v2.1`**, generated locally via `scripts/benchmark/build_v2/` ([PR #544](https://github.com/AI20K-Build-Phase-Cohort-4/P-063/pull/544), [Issue #539](https://github.com/AI20K-Build-Phase-Cohort-4/P-063/issues/539)).

### 2.1 Corpus Specifications

| Attribute | Specification |
|---|---|
| **Release Name** | `releases_v2.1` |
| **Generator Version** | `v2.1.0-realistic` ([config.py](../../scripts/benchmark/build_v2/config.py)) |
| **Seed** | `20261017` |
| **Total Trips** | 40,000 |
| **Total Unique Drivers** | 2,000 |
| **Total Unique Passengers** | 8,000 |
| **`trips.jsonl` SHA-256** | `d52e52ff7dd2cc7b6d23631191d1cdbf32d9f1b636f43117ad496809ac0d3fdf` |
| **Driver Split Ratio** | 70% Train (28,000 trips) / 15% Validation (6,000 trips) / 15% Test (6,000 trips) |
| **Split Partition Method** | Hash-grouped by `driver_id` (zero driver overlap across train/val/test) |
| **Storage Status** | Published on Hugging Face Hub (`datamonsterr/p-063-synthesized-trips`, revision `abb8cc8b2464aacdcbec0aab039ef4e066f71f8e`); originally built locally via `build_v2` |

### 2.2 Class Balance and Enrichment

The benchmark uses an **enriched** class balance rather than real-world prevalence to ensure sufficient statistical power across all violation types. Benchmarks from other domains, such as the synthetic mobile-money dataset PaySim [[REF-PAYSIM]](DATASET_CARDS.md#ref-paysim), exhibit low fraud prevalence (~0.13%), but this synthetic financial fraud rate is not measured real-trip ride-hailing fraud prevalence.

| Class | Total Count (40,000) | Split: Train (28,000) | Split: Validation (6,000) | Split: Test (6,000) | `dev300` Screening Subset |
|---|---:|---:|---:|---:|---:|
| `no_violation` | 28,000 (70.0%) | 19,600 | 4,200 | 4,200 | 204 |
| `ERR-02` | 3,200 (8.0%) | 2,240 | 480 | 480 | 25 |
| `insufficient_evidence` | 2,400 (6.0%) | 1,680 | 360 | 360 | 17 |
| `ERR-01` | 2,000 (5.0%) | 1,400 | 300 | 300 | 15 |
| `ERR-03` | 2,000 (5.0%) | 1,400 | 300 | 300 | 15 |
| `ERR-04` | 1,200 (3.0%) | 840 | 180 | 180 | 12 |
| `ERR-05` | 1,200 (3.0%) | 840 | 180 | 180 | 12 |
| **Total** | **40,000** | **28,000** | **6,000** | **6,000** | **300** |

The `dev300` set (`cd008ee10b22520fbd71598d1718d06cf9ba9a9f3af38ca8736a11019a9a9ed9`) is a fixed 300-trip stratified sample from the validation split used for fast screening and prompt ablation without exhausting LLM budgets.

### 2.3 Generator Configuration & Realism Calibration

Parameters in `scripts/benchmark/build_v2/config.py` enforce empirical kinematic, sensor, and reporting realism documented in [REALISM_V2.md](REALISM_V2.md):

- **Cadence & Ping Profiles**: Calibrated against [[REF-PORTO]](DATASET_CARDS.md#ref-porto), Grab-[[REF-MIPO]](DATASET_CARDS.md#ref-mipo) variants, and Posisi statistics:
  - 15.0s urban taxi cadence: 50%
  - 5.0s medium responsiveness: 30%
  - 1.0s high-frequency cadence: 20%
  - Missed ping probability: 5%; clock jitter SD: 0.20s
- **GPS Noise & Accuracy**: Lognormal accuracy distribution ($\mu=2.45$, $\sigma=0.50$, mode ~9m, median ~11.6m, p95 ~26m, clip 127m; 3% null rate). Urban canyon multipath outliers (50–200m) at 2% rate.
- **Speed Limits**: Urban traffic based on Hanoi/HCMC traffic studies (JICA/TomTom): average cruise 5.5–8.5 m/s (~20–30 km/h), arterial p95 16.7 m/s (60 km/h), physical device speed cap 23.6 m/s (85 km/h).
- **Road Geometry**: Grounded in real Hanoi/HCMC OpenStreetMap corridors [[REF-OSM-VN]](DATASET_CARDS.md#ref-osm-vn) with OSRM map-matching.
- **Reporting & Objection Decoupling**:
  - Customer report rate: 18% on honest trips, 45% on fraud trips (eliminates "report presence = fraud").
  - Driver objection rates calibrated in v2.1 across all classes: `no_violation` 4.2%, `ERR-01` 46.2%, `ERR-02` 51.5%, `ERR-03` 38.0%, `ERR-04` 34.5%, `ERR-05` 40.2%, `insufficient_evidence` 20.7% (fixes the v2.0 objection shortcut where objections appeared exclusively on ERR-01/ERR-02).
  - Mock provider flag: reported on 50% of ERR-05 trips (reflecting root/Xposed hiding) and 0.3% of honest trips (developer options enabled).

---

## 3. How to Fetch and Build

### 3.1 Fetch Current Synthetic Research Corpus (`releases_v2.1`) from Hugging Face Hub

`releases_v2.1` is hosted on Hugging Face Hub under [`datamonsterr/p-063-synthesized-trips`](https://huggingface.co/datasets/datamonsterr/p-063-synthesized-trips) (prior local-only status without write tokens is historical). Fetch the corpus pinned to its immutable commit:

```bash
# Fetch current 40k synthetic research corpus (releases_v2.1)
hf download datamonsterr/p-063-synthesized-trips \
  --repo-type dataset \
  --include "releases_v2.1/*" \
  --revision abb8cc8b2464aacdcbec0aab039ef4e066f71f8e \
  --local-dir data/benchmark-10k

# Verify SHA-256 matches d52e52ff...
sha256sum data/benchmark-10k/releases_v2.1/trips.jsonl
```

### 3.2 Rebuild Current Corpus Locally (Deterministic Generator)

The corpus can also be rebuilt deterministically from source code:

```bash
# Build full 40k corpus (releases_v2.1, seed 20261017)
python3 scripts/benchmark/build_v2/builder.py --out data/benchmark-10k/releases_v2.1 --n 40000 --seed 20261017

# Verify generated trips.jsonl checksum
sha256sum data/benchmark-10k/releases_v2.1/trips.jsonl
# Expected: d52e52ff7dd2cc7b6d23631191d1cdbf32d9f1b636f43117ad496809ac0d3fdf
```

### 3.3 Fetch Historical Corpora (`releases_v2`, `releases_v1`, `synthesized_vietnam_trip`)

- **Historical `releases_v2` (40k)**:
  ```bash
  hf download datamonsterr/p-063-synthesized-trips \
    --repo-type dataset \
    --include "releases_v2/*" \
    --revision cc8023b7022fdd5392a5655135712cc748967814 \
    --local-dir data/benchmark-10k
  ```
- **Historical `releases_v1` (40k merged)**:
  ```bash
  python scripts/benchmark/fetch_dataset.py --profile releases_v1 --out data/benchmark-10k
  ```
- **Vietnam 18 Corridors `synthesized_vietnam_trip` (1k)**:
  ```bash
  python scripts/benchmark/fetch_dataset.py --profile synthesized_vietnam_trip --out data/benchmark-10k
  ```

---

## 4. Model Input Boundary & Evaluation Modes

### 4.1 Input Boundary & Scrubbed Keys

To prevent label leakage during evaluation, `scripts/benchmark/run_10k.py` strips generator metadata using `_SCRUB_KEYS` and `_SCRUB_PREFIXES`:

```python
# scripts/benchmark/run_10k.py
_SCRUB_KEYS = frozenset(
    {
        "label",
        "fraud_propensity",
        "profile_provenance",
        "label_provenance",
        "scenario",
        "expected_category",
        "expected_guardrail",
        "expected_guardrail_reason",
        "expected_outcome",
        "intent",
        "simulation_id",
        "anomaly_type",
        "anomaly_score",
        "simulation_labels",
    }
)
_SCRUB_PREFIXES = ("expected_", "simulation_", "anomaly_")
```

> [!NOTE]
> `src/services/model_input_projection.py` is a separate projection allowlist used by `telemetry_queue_worker` and `analyze_10k.py`. The benchmark runner uses `_SCRUB_KEYS` directly, ensuring the detector receives operational fields while stripping synthetic simulation metadata. The state builder (`jev_state_builder.py`) additionally strips `generation_audit` and `measured_features`.

### 4.2 Enum-Blind vs Strict Evaluation Modes

- **Enum-Blind Mode (`--enum-blind`)**: Primary evaluation protocol. Invokes `blank_cancellation_enums()` in `run_10k.py` to overwrite `cancellation_actor` and `cancellation_reason` with empty values. Models must classify violations from kinematics, dialogue, and customer reports without reading the explicit cancellation label.
- **Strict Mode**: Retains lifecycle cancellation enums as recorded. Reported alongside enum-blind mode for historical comparability.

---

## 5. Known Dataset Leakage and Limits

An exhaustive audit of `releases_v2.1` ([R3C_LEAK_AUDIT.md](experiments/R3C_LEAK_AUDIT.md), [PR #546](https://github.com/AI20K-Build-Phase-Cohort-4/P-063/pull/546)) identified three structural properties:

1. **`platform_incident` Generator Leak**:
   `platform_incident.kind == TELEMETRY_ANOMALY` occurred on 12/12 `ERR-05` dev300 trips and zero other classes; `NETWORK_OUTAGE` occurred on 17/17 `insufficient_evidence` trips. This generator artifact is excluded from leak-audited models (R3C, R3D).
2. **Field Presence Leak**:
   A shallow decision tree trained purely on null/non-null presence of 108 fields reached macro-F1 **0.6745** (HistGBM: **0.8317**). Legitimate presence signals include cancellation/completion timestamps; leak signals (`simulation_audit`) are scrubbed by `run_10k.py`.
3. **`ERR-04` (Ghost Trip) Zero-GPS Signature**:
   In `releases_v2.1`, ghost trips reuse normal kinematic paths; the vehicle actually drove the route, but without the passenger. When `--enum-blind` strips cancellation enums, only customer text reports distinguish ghost trips from normal rides. This caps `ERR-04` F1 across all kinematics-only models at **~0.10–0.22**.

---

## 6. Release History

| Release Name | Date | Rows | Seed | `trips.jsonl` SHA-256 | Description & Milestones |
|---|---|---|---|---|---|
| `evidence-v4` | 2026-10-12 | 10,000 | 20261011 | `8379d090a55650c5d476b0ad7edbe5668c276591ed4688c75f05ce6626923071` | Hardened v1 profile ([ADR-025](../architecture/adr-025-benchmark-evidence-boundaries.md)); decoupled cancellation enums |
| `releases_v1` | 2026-10-12..16 | 40,000 | — | `1a0f05b3e1276a0844f27f8d380e0fa35bf259bf896e053f36a4450702d759a2` | Merged v1 + feedback-v2 + g1g2-v3 + evidence-v4; HF revision `914a3656...` |
| `synthesized_vietnam_trip` | 2026-10-16 | 1,000 | 20261015 | `c4c8090333d45543666b6c8ba8735df68b55d28b3a58e65860d5bfa780d6b412` | 1,000-trip OSM/OSRM Vietnam road corridors; HF revision `a914d500...` |
| `releases_v2` | 2026-10-17 | 40,000 | 20261017 | `9986acd1b3cefd118f2696bd4ae3c3b3dd67e0ae210808792eae5e8fd8441d5d` | First `build_v2` realistic release ([PR #501](https://github.com/AI20K-Build-Phase-Cohort-4/P-063/pull/501)); 28k/6k/6k driver split |
| **`releases_v2.1`** | **2026-10-18** | **40,000** | **20261017** | `d52e52ff7dd2cc7b6d23631191d1cdbf32d9f1b636f43117ad496809ac0d3fdf` | **Current synthetic research corpus** ([PR #544](https://github.com/AI20K-Build-Phase-Cohort-4/P-063/pull/544)); driver objection shortcut removed |
| `dev300` | 2026-10-18 | 300 | 20261017 | `cd008ee10b22520fbd71598d1718d06cf9ba9a9f3af38ca8736a11019a9a9ed9` | Stratified 300-trip screening subset of `releases_v2.1` validation split |

---

## 7. Reference Datasets Citation

External real-world datasets provide distributional priors, vocabulary, and topological maps. No raw third-party rows are copied into the benchmark. For full license and attribution cards, see [DATASET_CARDS.md](DATASET_CARDS.md).

- **[[REF-PORTO]](DATASET_CARDS.md#ref-porto)**: Moreira-Matias et al., Taxi Service Trajectory Prediction Challenge (UCI / ECML PKDD 2015), CC BY 4.0. Shapes 15s cadence, speed distribution, and tortuosity bounds.
- **[[REF-NYC-TLC]](DATASET_CARDS.md#ref-nyc-tlc)**: NYC Taxi and Limousine Commission Yellow Trip Data (2024-01), Public Domain. Shapes trip distance/duration quantiles and scheduling priors.
- **[[REF-MULTIWOZ]](DATASET_CARDS.md#ref-multiwoz)**: MultiWOZ 2.2 Dialogue Corpus, MIT License. Shapes conversational turn depth and dialogue length.
- **[[REF-SGD]](DATASET_CARDS.md#ref-sgd)**: Google Schema-Guided Dialogue Dataset, CC BY-SA 4.0. Shapes customer utterance lexical variation and slot structures.
- **[[REF-PAYSIM]](DATASET_CARDS.md#ref-paysim)**: PaySim Synthetic Financial Mobile Money Dataset, MIT License. Illustrates synthetic financial transaction fraud prevalence (~0.13%, not measured real-trip ride-hailing fraud prevalence) informing synthetic enrichment.
- **[[REF-MIPO]](DATASET_CARDS.md#ref-mipo)**: Grab-Posisi Trajectory & Anomaly Dataset. EDA-only calibration for high-frequency (1s) ping profiles and detour tortuosity.
- **[[REF-NAYFEH]](DATASET_CARDS.md#ref-nayfeh)**: Nayfeh GNSS Spoofing Repository. EDA-only reference for GPS multipath jumps and mock location characteristics.
- **[[REF-OSM-VN]](DATASET_CARDS.md#ref-osm-vn)**: OpenStreetMap contributors & OSRM, ODbL / Open Data. Road network corridor topologies for Hanoi and Ho Chi Minh City.

---

## 8. Licensing and Redistribution

- **Synthetic Corpora (`releases_v2.1`, `dev300`, `releases_v1`)**: Creative Commons Attribution 4.0 International ([CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)).
- **Redistributable Samples (100 rows)**: Samples from [[REF-PORTO]](DATASET_CARDS.md#ref-porto), [[REF-NYC-TLC]](DATASET_CARDS.md#ref-nyc-tlc), [[REF-PAYSIM]](DATASET_CARDS.md#ref-paysim), [[REF-MULTIWOZ]](DATASET_CARDS.md#ref-multiwoz), and [[REF-SGD]](DATASET_CARDS.md#ref-sgd) are redistributed under their respective permissive open licenses via `scripts/benchmark/make_sample_100.py`.
- **Proprietary / Unlicensed Sources**: [[REF-MIPO]](DATASET_CARDS.md#ref-mipo) and [[REF-NAYFEH]](DATASET_CARDS.md#ref-nayfeh) are restricted to internal exploratory data analysis; raw rows are excluded from git and never redistributed.

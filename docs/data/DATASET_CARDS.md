# Reference Dataset Cards

Cards for external reference datasets feeding the P-063 ride-hailing fraud benchmark. Our synthetic corpus is documented in [DATASET.md](DATASET.md); benchmark evaluation results are in [BENCHMARK.md](BENCHMARK.md).

Reference datasets provide **distributional priors, lexical structures, and geographic topologies**. No raw third-party rows are embedded in the benchmark; redistributable 100-row sample parquets are published under `samples/` on Hugging Face Hub ([datamonsterr/p-063-synthesized-trips](https://huggingface.co/datasets/datamonsterr/p-063-synthesized-trips)).

---

## [REF-PORTO]: UCI Taxi Service Trajectory Prediction

- **Identifier**: `[REF-PORTO]`
- **Title**: Taxi Service Trajectory Prediction Challenge (ECML PKDD 2015)
- **License**: Creative Commons Attribution 4.0 International ([CC BY 4.0](https://creativecommons.org/licenses/by/4.0/))
- **Provenance**: UCI Machine Learning Repository (`dataset/339`, doi:10.24432/C55W25), retrieved 2026-10-11. 1,710,670 trips across 442 taxis in Porto, Portugal; WGS84 polylines at regular 15-second cadence.
- **What it shapes**:
  - Telemetry cadence: 15-second urban taxi sampling profile (50% share in `build_v2`).
  - Speed prior: moving-speed gamma distribution ($\mu \approx 7.0$ m/s, trip mean $7.55$ m/s).
  - Normal trip tortuosity prior ($1.12$–$1.45$).
  - Dwell/stop duration priors for normal stops and waiting intervals.
- **Generator usage**:
  - **v1-era generator (`build_10k_v2.py`)**: 20% of `evidence-v2`/`evidence-v4` trips directly embedded Porto coordinate anchors and landmark sampling (`porto_share = 0.20`, city `"Porto"` vs `"Hanoi"`).
  - **`build_v2` generator (`scripts/benchmark/build_v2/`)**: **Zero Porto coordinates or anchors are used.** Geometries are 100% grounded in Vietnamese road networks (`[REF-OSM-VN]`). `[REF-PORTO]` is strictly used as an empirical parametric prior for cadence (15s), speed, and tortuosity bounds.
- **Limits**: European road topology and Portuguese urban density; completed trips only without granular fraud labels. 100-row sample published on Hub.

---

## [REF-NYC-TLC]: NYC TLC Yellow Taxi Trip Records

- **Identifier**: `[REF-NYC-TLC]`
- **Title**: New York City Taxi and Limousine Commission Yellow Taxi Trip Records (2024-01)
- **License**: Public Domain (NYC Open Data / TLC Terms of Use)
- **Provenance**: NYC Open Data portal, retrieved 2026-10-11; 2,964,624 trip records from January 2024.
- **What it shapes**:
  - Trip duration and distance distribution quantiles (median duration ~703s, median distance ~2,736m).
  - Hourly and day-of-week demand scheduling priors (morning/evening rush weights `h04`/`h05`/`h17`/`h18` and full weekday vector).
- **Generator usage**:
  - **v1-era generator (`build_10k.py`)**: Adopted scheduling weight vector and macro distance/duration scale.
  - **`build_v2` generator (`build_v2/config.py`)**: Calibrates trip duration distributions and pickup-to-dropoff distance quantiles.
- **Limits**: Coarse taxi zone IDs rather than granular GPS breadcrumbs; Manhattan grid geometry and fare structures do not reflect Southeast Asian ride-hailing dynamics. 100-row sample published on Hub.

---

## [REF-MULTIWOZ]: Multi-Domain Wizard-of-Oz Dialogue Corpus

- **Identifier**: `[REF-MULTIWOZ]`
- **Title**: MultiWOZ 2.2: A Multi-Domain Task-Oriented Dialogue Dataset
- **License**: MIT License (`budzianowski/multiwoz`)
- **Provenance**: University of Cambridge; 10,437 multi-turn dialogues (1,872 taxi-domain conversations), retrieved 2026-10-11.
- **What it shapes**:
  - Conversational turn depth: turn count bounds (cap 4–12 turns, 20% at 16 turns; median turn length ~11 customer words).
  - Dialogue flow: passenger pickup queries, driver confirmation, delay notifications, cancellation dispute structure.
- **Generator usage**:
  - **v1-era generator (`build_10k.py`)**: Informed the turn-count distribution of the committed YAML conversation bank (`data/conversation_bank/`).
  - **`build_v2` generator (`build_v2/dialogue.py`)**: Shapes utterance length and turn pacing in the synthetic Vietnamese colloquial dialogue synthesizer, preventing turn count from leaking fraud labels.
- **Limits**: English task-oriented booking dialogues; adapted for Vietnamese ride-hailing dispute vernacular through domain-specific lexical expansion. 100-row sample published on Hub.

---

## [REF-SGD]: Google Schema-Guided Dialogue Dataset

- **Identifier**: `[REF-SGD]`
- **Title**: The Schema-Guided Dialogue Dataset (DSTC8)
- **License**: Creative Commons Attribution-ShareAlike 4.0 International ([CC BY-SA 4.0](https://creativecommons.org/licenses/by/4.0/))
- **Provenance**: Google Research, retrieved 2026-10-11; over 20,000 multi-domain conversations across 45 services.
- **What it shapes**:
  - Dialogue state transition schemas and slot-filling semantics for ride-hailing services (driver status, estimated arrival, passenger cancellation intents).
  - Lexical diversity for edge-case customer inquiries.
- **Generator usage**:
  - **v1-era generator**: Secondary structural cross-reference for dialogue bank slots.
  - **`build_v2` generator**: Structural validation of dialogue states; no surface text is transferred directly.
- **Limits**: Synthesized from crowd-workers on synthetic API schemas; conversational style is neutral and lacks Southeast Asian localized slang. 100-row sample published on Hub.

---

## [REF-PAYSIM]: Financial Mobile Money Fraud Simulator

- **Identifier**: `[REF-PAYSIM]`
- **Title**: PaySim: A Financial Mobile Money Simulator for Fraud Detection
- **License**: MIT License (`theman10/paysim`)
- **Provenance**: Lopez-Rojas et al.; 6,362,620 transactions based on African mobile financial transactions, retrieved 2026-10-11.
- **What it shapes**:
  - Financial domain proxy reference for natural fraud sparsity (~0.13% or 13 positives per 10,000 transactions in mobile money).
  - Methodological justification for synthetic dataset enrichment: natural sparsity makes per-class evaluation statistically impossible at 10k–40k scale without enrichment (note: this financial proxy must not be conflated with true operational ride-hailing dispute prevalence).
- **Generator usage**:
  - **v1-era and `build_v2` generators**: Purely an external reference justification for class enrichment (~24% fraud, 6% insufficient evidence, 70% honest) and prevalence reweighting formulas (`GeneratorV2Config.calculate_prevalence_weight`). No financial transaction attributes enter the ride-hailing telemetry generator.
- **Limits**: Financial banking domain; transactions lack spatial-temporal kinematics, GPS tracks, or vehicle lifecycle mechanics. 100-row sample published on Hub.

---

## [REF-MIPO]: Grab-Posisi & AiSq Trajectory Variants

- **Identifier**: `[REF-MIPO]`
- **Title**: Grab-Posisi GPS Trajectory Dataset & AiSq Anomaly Variants
- **License**: No license stated (Internal research only — **Restricted / Not Redistributed**)
- **Provenance**: SUTD / Grab-Posisi Singapore/Jakarta trajectory publications and internal synthetic anomaly slices (`TimeIsAFriend/mipo_variants`), analyzed 2026-10-11.
- **What it shapes**:
  - High-frequency cadence: 1.0-second ping profile (20% share in `build_v2`).
  - `ERR-03` route deviation tortuosity calibration (AiSq detour tortuosity median ~1.5622).
  - Stationarity and stop-run duration distributions under urban congestion.
- **Generator usage**:
  - **v1-era generator**: Evaluated in exploratory data analysis (`scripts/eda_mipo_variants.py`).
  - **`build_v2` generator**: Shapes high-frequency cadence profile and detour ratio thresholds. Raw planar coordinates are never converted or merged into WGS84 benchmark data.
- **Limits**: Planar/local coordinate representations without explicit CRS; raw rows stay in local git-ignored storage (`data/raw/`) and are never published or redistributed.

---

## [REF-NAYFEH]: GNSS Spoofing and Multipath Repository

- **Identifier**: `[REF-NAYFEH]`
- **Title**: Nayfeh GNSS Spoofing and Multipath Telemetry Archive
- **License**: No license stated (Internal research only — **Restricted / Not Redistributed**)
- **Provenance**: Academic GNSS spoofing testbed logs from Raspberry Pi receivers, retrieved 2026-10-11.
- **What it shapes**:
  - GPS multipath error profiles (abrupt 50–200m spatial teleportation without speed consistency).
  - Mock location flag behavior (Android `ALLOW_MOCK_LOCATION` vs root-level mock provider hiding).
- **Generator usage**:
  - **v1-era generator**: Exploratory reference for mock provider separability (`scripts/eda_spoofing.py`).
  - **`build_v2` generator**: Informs lognormal accuracy noise and the 50% mock flag hiding rate for `ERR-05`.
- **Limits**: Stationary receiver hardware; lacks vehicle dynamics, road constraints, and cellular tower handover telemetry. Raw rows stay local and are never redistributed.

---

## [REF-OSM-VN]: Vietnam Road Corridors (OpenStreetMap / OSRM)

- **Identifier**: `[REF-OSM-VN]`
- **Title**: OpenStreetMap Vietnam Metropolitan Road Corridors & OSRM Routing
- **License**: Open Database License 1.0 ([ODbL 1.0](https://opendatacommons.org/licenses/odbl/), © OpenStreetMap contributors)
- **Provenance**: Road network extracts from Hanoi and Ho Chi Minh City queried via Open Source Routing Machine (OSRM). Corridors stored in `data/benchmark-10k/vietnam_road_corridors.json`.
- **What it shapes**:
  - True road network topologies, arc-length distance, intersection density, and genuine Vietnamese street names (Đinh Tiên Hoàng, Điện Biên Phủ, Kim Mã, Cầu Giấy, Giải Phóng, Nguyễn Trãi, etc.).
  - Real-world travel speeds calibrated against urban transit studies (JICA/TomTom): 5.5–8.5 m/s (~20–30 km/h) cruise speed, 16.7 m/s (60 km/h) arterial p95.
- **Generator usage**:
  - **v1-era generator**: Used in the 1,000-trip `synthesized_vietnam_trip` pilot release (Issue #394).
  - **`build_v2` generator**: **Primary topological backbone for all 40,000 trips in `releases_v2` and `releases_v2.1`.** Every trip's nominal route is an interpolated polyline along real Vietnamese urban corridors.
- **Limits**: Curated metropolitan corridors (Hanoi and HCMC); rural corridors, non-navigable alleyways (*ngõ ngách*), and unmapped temporary construction diversions are not represented.

# Public Dataset Survey — Fraud Benchmark Acquisition (Issue #249)

Survey and acquisition of public datasets relevant to single-trip fraud classification
(ERR-01 unjustified driver cancellation, ERR-02 deliberate stalling ≥180s before pickup,
ERR-03 route deviation/detour, ERR-04 phantom trips, ERR-05 fake GPS/mock location) plus
`no_violation` and `insufficient_evidence` (technical dropout).

- Retrieval date: 2026-10-11. Host free disk before downloads: 49 GB (≥10 GB gate passed).
- Caps honored: ≤2 GB per download (largest single file 533,605,607 B), ≤5 GB total.
  Total downloaded: 1,187,873,658 B (1.19 GB / 1.11 GiB); `data/raw/` on disk is 2.0 GiB
  including extracted tarball contents.
- Every downloaded dataset has `data/raw/<dataset_name>/manifest.json` with url,
  retrieval_date, license, per-file sha256, row_count, fields, size_bytes.
- `data/raw/` is git-ignored (`.gitignore`: `data/*`). Nothing under `data/raw/` is committed.
- All downloads used `curl` with `--retry 1`, connect timeout 30 s. Failures below record
  exact HTTP status.

## Summary table

| Dataset | Source URL | License | Size (downloaded) | Key fields | Labels | ERR relevance | Verdict |
|---|---|---|---:|---|---|---|---|
| Porto Taxi UCI (train.csv) | https://archive.ics.uci.edu/dataset/339/taxi+ | CC BY 4.0 | 508.9 MB zip | TRIP_ID, TAXI_ID, TIMESTAMP, CALL_TYPE, MISSING_DATA, POLYLINE (WGS84 lon/lat @15 s) | none (completed trips) | ERR-03 route geometry; ERR-02 in-trip dwell proxy; ERR-04 per-driver frequency baselines; insufficient_evidence via MISSING_DATA | **MERGE** |
| MiPo variants AiSq5D / StSt10M / UnCh10M | https://github.com/TimeIsAFriend/trajectory_MiPo (rev 70a9b01) | not specified (author repo) | 3.1 MB | planar [x,y] trajectory arrays | normal / outlier per file | ERR-03 detour/anomaly geometry priors (unit-relative) | **MERGE** |
| NYC TLC yellow taxi 2024-01 | https://www.nyc.gov/site/tlc/about/tlc-trip-record-data.page | public domain | 47.6 MB parquet | pickup/dropoff datetimes, trip_distance, zone IDs, fare components, store_and_fwd_flag | none | trip-duration/distance/fare priors; dropout proxy (store_and_fwd_flag); no GPS | **MERGE** (priors) |
| MultiWOZ 1.0–2.2 | https://github.com/budzianowski/multiwoz | MIT | 57.7 MB tar.gz | multi-turn dialogues, belief states; taxi domain in 1,872/10,437 dialogues (v2.2) | dialogue acts | driver–customer conversation text priors (booking, pickup point, cancellation talk) | **MERGE** |
| GPS spoofing dataset (Nayfeh) | https://github.com/mnayfeh/gps_spoofing_detection | not specified | 10.4 MB | GNSS receiver telemetry: lat/lon, eph, epv, hdop, vdop, jamming_indicator, velocities, fix_type | attack vs clean (per file) | ERR-05 spoof/clean receiver-quality feature distributions (drone, not phone) | EDA-ONLY |
| PaySim (full CSV, HF mirror) | https://huggingface.co/datasets/theman10/paysim | MIT (HF card) | 470.7 MB | step, type, amount, balances, isFraud | isFraud: 8,213/6,362,620 = 0.129% | fraud class-mix prevalence prior only (payments domain) | EDA-ONLY |
| Schema-Guided Dialogue (DSTC8) | https://github.com/google-research-datasets/dstc8-schema-guided-dialogue | CC BY-SA 4.0 | 35.1 MB tar.gz | 22,825 dialogues (16,142/2,482/4,201 train/dev/test), schemas, intents, slots | dialogue acts | conversational structure priors; weak ride-hailing domain match | EDA-ONLY |
| Chicago Taxi Trips (SODA) | https://data.cityofchicago.org/resource/wrvz-psew.csv | CC0-family (city open data) | not acquired | trip times, distances, fares, census tracts | none | would have added trip priors | **SKIP** — HTTP 403 (see below) |
| DiDi GAIA | https://outreach.didichuxing.com/ | research agreement | not acquired | trajectory + order data (Beijing/Chengdu/Xi'an) | none | ERR-01/02 pickup-phase, ERR-03 | SKIP — registration-gated (manual item) |
| Grab-Posisi | https://www.grab.com (dataset page 404) | research agreement | not acquired | bookings, trajectories (Singapore/Jakarta) | none | ERR-01/02/03, SE-Asia context | SKIP — email-gated (manual item) |
| IEEE Dataport GPS spoofing sets (Aissou 2022 doi:10.21227/8x3h-2817; Agrebi 2025 doi:10.21227/9zcb-qb02; UAV Attack doi:10.21227/00dg-0d12) | https://ieee-dataport.org/keywords/gps-spoofing | per-dataset | not acquired | RF/receiver features, trajectory + spoof labels | spoofed vs legitimate | ERR-05 | SKIP — subscription-gated |
| IEEE-CIS Fraud Detection | https://www.kaggle.com/competitions/ieee-fraud-detection | competition terms | not acquired | transaction + device/identity features | isFraud | class-mix prior only | SKIP — Kaggle-gated |
| PaySim on Kaggle (paysim1) | https://www.kaggle.com/datasets/eornuebi/paysim1 | see Kaggle | acquired via HF mirror instead | — | — | — | SKIP Kaggle copy (mirror used) |
| Vietnamese dialogue corpora (ViCoQA, VLSP resources, ViMSDuT) | https://vlsp.org.vn/ | research-only | not acquired | Vietnamese conversational/QA text | varies | Vietnamese conversation priors | SKIP — request/registration-gated; ViMSDuT: no public download found |

## Downloaded datasets (details)

All checksums, row counts, and field lists are in the per-dataset `manifest.json`; only
highlights here.

### Porto Taxi UCI — `data/raw/porto_taxi_uci/`
- File: `train.csv.zip` 533,605,607 B, sha256 `210dd0a20da66a8fc2de3440aecd84670921bc257591f8365a4475e31453c5ea`; zip integrity verified (`unzip -t`: no errors).
- Rows: 1,710,671 lines = header + 1,710,670 trips (UCI metadata: 1,710,671 instances).
- 9 fields; POLYLINE = WGS84 `[lon,lat]` pairs at 15 s cadence; `MISSING_DATA` flags dropped GPS streams (real dropout process).
- License CC BY 4.0 → redistribution/attribution OK. Requires credit: Moreira-Matias et al., UCI, doi:10.24432/C55W25.
- Note: UCI static bundle URL (`/static/public/339/taxi+.zip`) returned 404; the legacy ML-repository URL above returned 200 and was used.

### MiPo variants — `data/raw/mipo_variants/`
- 3 additional variants downloaded at pinned revision `70a9b0140f94a1d3e2349999c621392c18c439fc`:
  - AiSq5D: 1,060 normal + 55 outlier trajectories (2,258,405 B)
  - StSt10M: 182 normal + 20 outlier (228,481 B)
  - UnCh10M: 725 normal + 81 outlier (604,623 B)
- File sizes match GitHub API byte-for-byte; sha256 recorded.
- AiSq10D was already assessed: see [MIPO_EDA.md](MIPO_EDA.md) and the installed slice in `data/mipo/` (500 trajectories, imported via `scripts/import_mipo.py` into `app.research_trajectories`).
- Caveat carried over from MIPO_EDA.md: coordinates are planar with unknown CRS — geometry priors only, never merged into WGS84 telemetry columns. Repo has no license file; treat as research-internal.

### NYC TLC yellow taxi 2024-01 — `data/raw/nyc_tlc_sample/`
- `yellow_tripdata_2024-01.parquet` 49,961,641 B, sha256 `c4d59da7bbc8abaeeeb1727947ee93d9891a71acb42854bd80db1571b2030510`.
- 2,964,624 rows, 19 fields (verified with pyarrow). One month sample of an ongoing monthly series.
- Tabular only (zone IDs, no GPS traces). Useful for: trip-duration/distance/fare distributions, `store_and_fwd_flag` dropout proxy, airport-fee/congestion-surcharge context features.

### GPS spoofing (Nayfeh) — `data/raw/gps_spoofing_nayfeh/`
- 4 xlsx (attack/clean × testing/trainval, 1,771+1,793+1,716+1,703 rows, 27 GNSS fields) + `raspberry_pi_data.csv` (27,906 data rows) + README.
- u-blox-style receiver telemetry from drone experiments: eph/epv/hdop/vdop, jamming_indicator, velocity NED, fix_type. Labels are per-file (attack vs clean).
- No license file in repo → EDA-ONLY. Do not merge derived features into shipped synthetic data without written permission (maintainer contact in README).

### PaySim — `data/raw/paysim/`
- `paysim.csv` 493,534,783 B, sha256 `16910f90577b0d981bf8ff289714510bb89bc71bff7d3f220f024e287e4eea6b`; 6,362,620 records + header (size matched HF `x-linked-size` exactly).
- `isFraud` = 8,213 (0.129%); `isFlaggedFraud` column also present. Kaggle copy (`eornuebi/paysim1`) is login-gated; HF mirror `theman10/paysim` (MIT card) used instead — full canonical schema.
- Use: class-mix / prevalence priors for rare-fraud regimes only. Payments domain, no mobility content.

### MultiWOZ — `data/raw/multiwoz/`
- Repo tarball 60,513,917 B, sha256 `6813f7e9e2e2ac13cf947b4a39fc9d68237b5ed1c020108a7176e735b810446b`; extracted to `multiwoz-master/`.
- MultiWOZ 2.2: 10,437 dialogues counted from JSON, of which 1,872 include the `taxi` service (booking, pickup/destination negotiation, car/contact details). MultiWOZ 1.0/2.0/2.1 ship as inner zips.
- MIT license. English only — style/act priors for driver–customer chat, not Vietnamese surface text.

### Schema-Guided Dialogue — `data/raw/sgd_dialogue/`
- Repo tarball 36,788,119 B, sha256 `f703636bd043057c7f492b78f82ea8a80d004ff49d60b9d66d5593b417ccc708`; extracted.
- 22,825 dialogues counted (16,142 train / 2,482 dev / 4,201 test). CC BY-SA 4.0 — share-alike applies if derivative text is redistributed; keep as structural reference (EDA-ONLY).

## Failed and gated acquisitions

### Chicago Taxi Trips — HTTP 403 (all endpoints, domain-wide)
- `https://data.cityofchicago.org/resource/wrvz-psew.csv?$limit=50000` → **403 Forbidden** (body: nginx "403 Forbidden" page).
- `https://data.cityofchicago.org/resource/wrvz-psew.json?$limit=5` → **403 Forbidden** (also with browser User-Agent).
- `https://data.cityofchicago.org/api/views/wrvz-psew/rows.csv?accessType=DOWNLOAD` → **403 Forbidden**.
- Domain root `https://data.cityofchicago.org/` → **403 Forbidden** — Socrata WAF blocks this network/IP, not a per-endpoint gate. Retried per constraint; `webfetch` (different egress) also returned 403.
- The 118-byte 403 HTML stub was deleted; no partial data kept.
- Recovery options: retry from another network/VPN; Kaggle mirror `svaksh/... chicago-taxi-trips` (gated); BigQuery public dataset `bigquery-public-data.chicago_taxi_trips` (needs GCP).

### Registration/email-gated (manual acquisition plan)
1. **DiDi GAIA** (https://outreach.didichuxing.com/, HTTP 200 reachable): register account, sign research agreement, request trajectory + order datasets (Beijing/Chengdu/Xi'an). Highest-value gated item: order records with pickup timestamps would inform ERR-01/ERR-02 directly. Owner: data-acquisition lead; ETA: manual, ~1–2 weeks for approval.
2. **Grab-Posisi**: dataset page `https://www.grab.com/sg/en/grab-positi/` → **404**; `https://developer.grab.com/docs/grab-positi` → **302** redirect (login). Acquisition route: email Grab research (per historical Grab-Posisi/KDD Cup 2017 process) requesting the booking + trajectory dump; SE-Asia ride-hailing context closest to GreenSM/Vietnam. Manual item.
3. **IEEE Dataport GPS spoofing datasets**: Aissou et al. 2022 (doi:10.21227/8x3h-2817, 246.57 MB zip, 158,170 samples, 3 attack types); Agrebi 2025 maritime synthetic GPS (doi:10.21227/9zcb-qb02, CSV, Normal/Spoofed labels); UAV Attack Dataset (doi:10.21227/00dg-0d12, open access but download requires IEEE DataPort subscription per page). Requires subscription (free for IEEE society members). Manual item; relevant to ERR-05.
4. **IEEE-CIS Fraud Detection (Kaggle)**: login + competition rules acceptance; `kaggle competitions download -c ieee-fraud-detection` with API token. Class-mix priors only. Skipped per instructions.
5. **Vietnamese conversation corpora**: ViCoQA (10k questions / 2k conversations, request-gated, research-only); VLSP resources (registration form via vlsp.org.vn, e.g. VLSP2016 agreement); ViMSDuT — no public download located in this survey. No public "taxi driver–passenger conversation" corpus in Vietnamese was found. Plan: submit ViCoQA/VLSP requests with university affiliation; interim substitute = MultiWOZ taxi-domain English dialogues + LLM-generated Vietnamese surface forms anchored on MultiWOZ dialogue acts.

## MERGE shortlist (feeds 10k synthesis priors)

1. **Porto Taxi UCI** — only large-scale real WGS84 ride telemetry acquired: 1.71 M trips, 15 s GPS cadence, driver IDs, timestamps, MISSING_DATA dropout flags. Directly calibrates ERR-03 route-geometry distributions, per-driver trip-frequency baselines (ERR-04 plausibility), in-trip dwell/stall segments (ERR-02 proxy), and technical-dropout rates for `insufficient_evidence`. CC BY 4.0 permits merge with attribution.
2. **MiPo variants (+ already-assessed AiSq10D)** — labeled normal/detour-anomaly trajectory geometry. Tortuosity, length, and step distributions per class give ERR-03 detour-severity priors and a documented benchmark baseline (tortuosity AUROC 0.9444 in MIPO_EDA.md). Merge as unit-relative geometry priors only (unknown CRS); AiSq10D slice already lives in `app.research_trajectories`.
3. **NYC TLC 2024-01** — trip-duration, distance, fare, and time-of-day priors over 2.96 M real trips; `store_and_fwd_flag` adds a real device-dropout rate for `insufficient_evidence` mixing. Public domain, no attribution burden.
4. **MultiWOZ (taxi domain)** — 1,872 real human-annotated taxi-booking dialogues: pickup negotiation, cancellation/modification phrasing, driver–customer register. MIT license. Anchors the driver–customer conversation text feature until Vietnamese corpora are unblocked.

Held out of MERGE: PaySim (domain mismatch; prevalence number 0.129% usable as a reference, not as ride-fraud mixing), SGD (weak domain match + ShareAlike), Nayfeh GPS (no license → EDA-ONLY until permission; its eph/hdop/jamming distributions remain the best public ERR-05 feature reference).

## Coverage gaps

- **ERR-01 (unjustified cancellation)**: no public dataset with adjudicated cancellation labels was found. DiDi GAIA order data is the strongest gated candidate. Interim: synthesize from Porto trip-start distributions + MultiWOZ cancellation dialogues + policy text already in `data/processed/`.
- **ERR-05 (phone-level mock location)**: public spoofing data is receiver/drone-level (Nayfeh, IEEE Dataport), not Android `isFromMockProvider` logs. No public ride-hailing mock-location dataset exists; feature ranges must come from the Nayfeh GNSS-quality distributions plus documented simulator behavior.
- **Vietnamese surface text**: all acquired conversation data is English. Gated requests (ViCoQA, VLSP) recorded above.

## Reproduce

```bash
# checksums and row counts recorded in data/raw/<dataset>/manifest.json
sha256sum data/raw/porto_taxi_uci/train.csv.zip
python3 -c "import pyarrow.parquet as pq; f=pq.ParquetFile('data/raw/nyc_tlc_sample/yellow_tripdata_2024-01.parquet'); print(f.metadata.num_rows)"
```

Related: [MIPO_EDA.md](MIPO_EDA.md), [RIDE_HAILING_RESEARCH.md](RIDE_HAILING_RESEARCH.md), [TELEMETRY_DISTRIBUTION.md](TELEMETRY_DISTRIBUTION.md).

# Preview Seed Coverage & Analyst Workspace Evidence Audit

> Audit of evidence fields in the Analyst Workspace (Case Detail `src/services/case_service.py` L2460–3060, Driver History endpoint `src/services/driver_service.py`, schemas in `src/models/schemas.py`) against database contracts (`db/migrations/*.sql`), identifying seeded status, owning issues, and flagged fabricated fallbacks violating the "no fabricated metrics" invariant.

---

## 1. Field-by-Field Coverage Matrix

| Field | Source Table.Column | Persisted Contract? | Seeded? (Before Slice) | Seeded? (After Slice) | Owning Issue | Notes / Provenance |
|---|---|---|---|---|---|---|
| **Driver Vehicle Type / Model** | `app.vehicles.model`<br/>`app.vehicles.vehicle_type` | ✅ YES (`0001_poc_core.sql`, `20260923181144_mipo_research_and_driver_profile.sql`) | ⚠️ Partial (`vehicle_type='car'`, `model=NULL`) | ✅ YES | #366 | Populated with VinFast EV models (VF e34, VF 8, VF 9, VF 5 Plus, Feliz S, Klara S). |
| **Driver Status** | `app.drivers.account_status` | ✅ YES (`0001_poc_core.sql`) | ✅ YES (`'active'`) | ✅ YES | #366 | Validated across all demo drivers (`active`, `suspended`, `pending_investigation`). |
| **Driver Statement** | `app.driver_submissions.statement` | ✅ YES (`0001_poc_core.sql`) | ❌ Partial (40/144 cases only) | ✅ YES (144/144) | #366 | Tailored Vietnamese explanations per violation category with `provenance.source='synthetic_seed'`. |
| **Driver Average Rating** | `app.drivers.rating` | ✅ YES (`20260926130000_center_panel_driver_trip_enrichment.sql`) | ⚠️ Default only (4.85) | ✅ YES | #366 | Deterministic distribution [4.65–4.95] per driver with `profile_provenance`. |
| **Driver Acceptance Rate** | `app.drivers.acceptance_rate` | ✅ YES (`20260926130000_center_panel_driver_trip_enrichment.sql`) | ⚠️ Default only (92.5) | ✅ YES | #366 | Deterministic distribution [89.0–99.0]% per driver with `profile_provenance`. |
| **Driver Cancellation Rate** | `app.drivers.cancellation_rate` | ✅ YES (`20260926130000_center_panel_driver_trip_enrichment.sql`) | ⚠️ Default only (2.1) | ✅ YES | #366 | Deterministic distribution [0.8–3.8]% per driver with `profile_provenance`. |
| **Driver Total Trips** | `app.drivers.total_trips` | ✅ YES (`20260926130000_center_panel_driver_trip_enrichment.sql`) | ⚠️ Default only (1250) | ✅ YES | #366 | Deterministic trip counts [650–2450] per driver with `profile_provenance`. |
| **Driver History: Violation Ratio (90d)** | Dynamic aggregation: `app.fraud_cases` / `app.trips` (last 90d) | ✅ YES (`driver_service.py:150-167`) | ❌ 100.0% (all seed trips were fraud cases) | ✅ YES (~2.5%–6.5%) | #366 | Seeded nominal non-fraud historical trips in 90d window so ratio reflects fleet reality. |
| **Driver History: Fined Ratio** | Dynamic aggregation: `app.adjudications.outcome IN ('fine','suspend','reject')` / `app.fraud_cases` | ✅ YES (`driver_service.py:157-167`) | ⚠️ Skewed / unadjudicated | ✅ YES | #366 | Adjudicated past cases with valid outcomes ('fine', 'warn', 'dismiss', 'suspend'). |
| **Driver History: Repeat Offense Risk** | Heuristic formula: `clamp(10, 99, total_cases*15 + penalized*25)` | ✅ YES (`driver_service.py:44`) | ⚠️ Clamped to 99 | ✅ YES (realistic score) | #366 | Balanced by realistic case and penalty counts per driver. |
| **Driver History: Benchmark Ratio** | `BENCHMARK_VIOLATION_RATIO = 5.0` | ✅ YES (`driver_service.py:32`) | ✅ Static constant (5.0%) | ✅ YES (5.0%) | #366 | GreenSM platform baseline. |
| **Driver History: Tenure Months** | Dynamic: `months_between(NOW, app.drivers.created_at)` | ✅ YES (`driver_service.py:53`) | ❌ 1 month for all drivers (`created_at` was 2026-09-07) | ✅ YES (8–28 months) | #366 | Backdated `app.drivers.created_at` across 8–28 months prior. |
| **Driver History: Past Incidents** | Dynamic query: `app.fraud_cases` + `app.adjudications` + `app.trips` (limit 3) | ✅ YES (`driver_service.py:168-196`) | ❌ Empty or missing rationale | ✅ YES (3 rich rows/driver) | #366 | 3 adjudicated incidents per driver with Vietnamese findings and outcomes. |
| **Customer Profile** | `app.passengers.display_name`<br/>`app.passengers.phone_number` | ✅ YES (`0001_poc_core.sql`, `20260923181144_mipo_research_and_driver_profile.sql`) | ✅ YES | ✅ YES | #366 | Verified seeded with authentic Vietnamese passenger names and phone numbers. |
| **Customer / Passenger Statement** | `app.passenger_feedback.statement` | ✅ YES (`0001_poc_core.sql`) | ❌ Partial (25/144 cases only) | ✅ YES (144/144) | #366 | Seeded realistic Vietnamese dispute / feedback statements for all 144 cases. |
| **Customer Rating** | `app.passenger_feedback.rating_smallint` | ✅ YES in DB (`20261008090000_passenger_feedback_rating.sql`); ❌ NO column on `app.trips` | ❌ NULL on all rows | ✅ YES in DB (1–5 stars) | #367 | Persisted in `app.passenger_feedback.rating_smallint`. Endpoint exposure in `trip` belongs to #367. |
| **Trip Fare Amount (VND)** | `app.trips.fare_amount_vnd`<br/>`app.fare_quotes.estimated_amount_minor` | ✅ YES (`20260926130000_center_panel_driver_trip_enrichment.sql`, `0001_poc_core.sql`) | ❌ NULL on all 144 trips | ✅ YES (45k–285k VND) | #366 | Populated direct fare VND and matching VND fare quotes, giving realistic fare economics. |
| **Trip ID** | `app.trips.id` | ✅ YES (`0001_poc_core.sql`) | ✅ YES | ✅ YES | #366 | Populated and linked via `app.trip_assignments.trip_id`. |
| **Trip Match Type** | `app.trips.match_type` | ✅ YES (`20260926130000_center_panel_driver_trip_enrichment.sql`) | ⚠️ Default `'auto'` on all | ✅ YES (`'auto'` / `'now'`) | #366 | Balanced distribution between instant `'now'` and dispatched `'auto'` matching. |
| **Trip Pickup / Dropoff Addresses** | `app.trips.pickup_address`<br/>`app.trips.dropoff_address`<br/>`app.trips.district` | ✅ YES (`20260924061235_trip_enrichment_and_district.sql`, `20260926130000_center_panel_driver_trip_enrichment.sql`) | ❌ NULL on all 144 trips | ✅ YES | #366 | Seeded with 30 Hanoi landmarks across 12 urban and suburban districts. |
| **Traffic Corroboration** | `app.traffic_observations` (observations table exists, but composite object has NO DB contract) | ⚠️ Partial in DB; ❌ NO composite contract in `case_service.py` (`traffic_corroboration = None`) | ❌ `None` | ❌ `None` (deferred) | #365 | `app.traffic_observations` has 100 observations. Synthesis of `traffic_corroboration` object belongs to #365. |
| **Sensor Reliability: GPS Accuracy** | `app.telemetry_points.accuracy_m` | ✅ YES (`0001_poc_core.sql`) | ✅ YES | ✅ YES | #366 | Populated from log-normal kinematic GPS CEP radius (3.5–18.0 m). |
| **Sensor Reliability: Ping Latency** | `app.ingest_events.payload->>'ping_latency_ms'` | ✅ YES (`case_service.py:2557`, jsonb payload) | ❌ `None` in all payloads | ✅ YES (25–95 ms) | #366 | Populated in `ingest_events.payload` with synthetic provenance. |
| **Sensor Reliability: Battery Level** | `app.ingest_events.payload->>'battery_level_pct'` | ✅ YES (`case_service.py:2559`, jsonb payload) | ❌ `None` in all payloads | ✅ YES (45–95 %) | #366 | Populated in `ingest_events.payload` with synthetic provenance. |
| **Sensor Reliability: Stall Duration** | `app.feature_sets.stationary_duration_s` | ✅ YES (`0001_poc_core.sql`) | ✅ YES (for ERR-02 cases) | ✅ YES | #366 | Preserved and correlated with category and driver statements. |
| **Sensor Reliability: Drift Distance** | `ST_Distance(tp.position, rs.route)` from `app.route_snapshots` | ✅ YES (PostGIS dynamic calculation) | ✅ YES (when routes exist) | ✅ YES | #366 | Computed on-the-fly against OSRM route corridors. |
| **Motivation Assessment** | Dynamic synthesis in `case_service.py:2466` from `fare_delta_vnd`, `features`, `telemetry` | ✅ YES (`motivation_assessment_service.py`) | ❌ Incomplete (fare delta was None due to NULL fare) | ✅ YES (rich Vietnamese narrative) | #364 / #366 | Derived from fare quote delta only, judgment not seeded (by design). Unlocked by seeding positive `fare_amount_vnd` + `fare_quotes`. |
| **Willingness Assessment** | None (`workspace-data.ts:13: { state: 'unavailable', followup: 364 }`) | ❌ NO contract exists | ❌ Unavailable | ❌ Unavailable (deferred) | #364 | Explicitly documented as unpersisted intent contract owned by issue #364. |

> [!IMPORTANT]
> **Active Queue Judgment & Adjudication Invariant (No Synthetic Fabrication)**
> Preliminary judgments (`app.preliminary_judgments`) and adjudications (`app.adjudications`) of active, open, or claimable cases (`ready`, `in_review`, `evidence_requested`, `escalated`, `driver_disputed`, `pending_analyst_review`) are **never seeded**.
> Fabricating preliminary judgments violates the core product invariant: *"independent preliminary judgment before AI reveal; human-confirmed final adjudication"*, as it would prematurely unlock the UI AI reveal gate without genuine human analyst evaluation.
> Historical adjudications are strictly attached only to cases that are already terminal (`resolved`, `auto_dismissed`, etc.) and never touch active queue cases or alter their status or version.

---

## 2. Invariant Violations: Flagged Fabricated Fallbacks in `src/services/case_service.py`

Per **Rule §3 of `.agents/rules/backend.md`** ("Forensic Brief & Case Policy Invariant: must only report measured telemetry, trip, and guardrail abnormalities without fabricating metrics") and the "no fabricated metrics" architectural standard, hardcoded metric fallbacks in service layers violate system integrity.

The following hardcoded fabricated fallbacks exist in `src/services/case_service.py`:

### 2.1 Database Path Fallbacks (`_get_case_detail_data` L2803–2828)
```python
# L2803: Fabricated driver display name
driver_disp_name = row.get("driver_name") or "Nguyễn Văn Hùng"

# L2804: Fabricated vehicle registration plate
driver_plate = row.get("vehicle_plate") or "29E-123.45"

# L2805: Fabricated vehicle model
veh_type = row.get("vehicle_model") or row.get("vehicle_type") or "GreenCar (VF e34)"

# L2812: Fabricated trip fare amount (85,000 VND)
fare_vnd = 85000

# L2821: Fabricated driver rating
driver_rating = float(row.get("driver_rating") or prov.get("rating") or 4.85)

# L2822: Fabricated driver acceptance rate
driver_acc = float(row.get("driver_acceptance_rate") or prov.get("acceptance_rate") or 92.5)

# L2823: Fabricated driver cancellation rate
driver_cancel = float(row.get("driver_cancellation_rate") or prov.get("cancellation_rate") or 2.1)

# L2824: Fabricated driver total trip count
driver_trips = int(row.get("driver_total_trips") or prov.get("total_trips") or 1250)

# L2826-2828: Fabricated trip addresses and district
pickup_addr = row.get("pickup_address") or "Hồ Hoàn Kiếm, Tràng Tiền, Hoàn Kiếm"
dropoff_addr = row.get("dropoff_address") or "Sân bay Quốc tế Nội Bài, Sóc Sơn"
district_name = row.get("trip_district") or "Hoàn Kiếm"
```

### 2.2 In-Memory Fallbacks (`_get_case_detail_data` L3047–3063)
```python
# L3047-3063: Identical fabricated metric injections in test/in-memory mode
driver_name = driver_obj.get("display_name") or "Nguyễn Văn Hùng"
trip.setdefault("vehicle_plate", "29E-123.45")
trip.setdefault("vehicle_type", "GreenCar (VF e34)")
trip.setdefault("rating", float(driver_obj.get("rating", 4.85)))
trip.setdefault("acceptance_rate", float(driver_obj.get("acceptance_rate", 92.5)))
trip.setdefault("cancellation_rate", float(driver_obj.get("cancellation_rate", 2.1)))
trip.setdefault("total_trips", int(driver_obj.get("total_trips", 1250)))
trip.setdefault("fare_amount_vnd", trip.get("fare_amount_vnd") or 85000)
trip.setdefault("pickup_address", trip.get("pickup_address") or "Hồ Hoàn Kiếm, Tràng Tiền, Hoàn Kiếm")
trip.setdefault("dropoff_address", trip.get("dropoff_address") or "Sân bay Quốc tế Nội Bài, Sóc Sơn")
```

### 2.3 Supersession Strategy
Per the issue #366 instructions:
1. These fallback lines are **not altered in this slice** to prevent breaking legacy unseeded test runs or in-memory fixtures.
2. The preview enrichment script (`scripts/seed_preview_enrichment.py`) guarantees that **every database column backing these fields is populated with authentic synthetic Vietnamese data**.
3. Consequently, for all preview and demo cases, database query rows return non-null values, completely superseding these fallbacks at runtime without triggering them.

---

## 3. Seed Architecture & Execution

### 3.1 Existing Seed Flow Integration
1. `./scripts/migrate.sh --seed` executes `scripts/migrate_postgres.py --seed`.
2. `migrate_postgres.py` applies all schema migrations from `db/migrations/`.
3. `migrate_postgres.py` invokes `seed_preview_enrichment.py:enrich_preview_cases()`.
4. The enrichment runs in **apply mode** during migration seeding.

### 3.2 Standalone Migration-Safe CLI
`scripts/seed_preview_enrichment.py` provides an isolated, idempotent tool:
```bash
# Dry run: prints counts of cases, drivers, vehicles, and events to enrich without touching DB
python3 scripts/seed_preview_enrichment.py --database-url "$DATABASE_URL" --dry-run

# Apply run: commits enrichment to the target database
python3 scripts/seed_preview_enrichment.py --database-url "$DATABASE_URL" --apply
```
- **Default mode**: `--dry-run` is active by default; mutations require explicit `--apply` flag.
- **Idempotency**: All `INSERT` statements use `ON CONFLICT DO NOTHING` / `DO UPDATE`. Re-running does not produce duplicate rows or alter existing valid state.
- **Provenance**: Synthetic rows and payloads are tagged with `provenance.source = 'synthetic_seed'` or `sensor_provenance = 'synthetic_seed'`.

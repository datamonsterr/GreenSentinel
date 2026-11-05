# Database Performance Profiling, Index Optimization & Workload-Supported Index Migrations

**Goal:** Provide repository-owned, safe, read-only database performance profiling, index inventory, and additive workload-supported index migrations with comprehensive before/after empirical verification on realistic fixtures without mutating live production data.

**Parent Issue:** #394  
**Child Issue:** #399  
**Slice:** `indexes`

---

## 1. Context & Architecture Review
- **Railway Environments Audited:**
  - `dev`, `staging`, `production` on Project `c49458fb-d741-468f-a3ed-d35b96788f68`, Service `9710a2f5-ed77-472e-8e79-3b748bb73df2`.
  - Credentials fetched exclusively in memory via Railway CLI proxy parameters; zero secrets or DSNs logged.
- **Tenancy & Invariants Verification:**
  - Each environment contains 1 organization (`orgs=1`), with strict 100% non-null `organization_id` on all trips and 0 cross-org driver-trip linkages.
- **Workload Profiling Findings:**
  - Case queue (`app.fraud_cases`): Frequent queries filter by `(organization_id, status)` and order by `(priority_tier ASC, priority_score DESC, created_at DESC)`. While `idx_case_queue` exists, it does not include `organization_id`, causing Seq Scan + Sort on organization-scoped queues.
  - Trip assignment lookup (`app.trip_assignments`): Queries filter by `trip_id` (e.g. `SELECT ... WHERE trip_id = %s`). The table only had a partial unique index on active states (`uq_trip_one_active_assignment`), leaving completed/cancelled queries to perform full Seq Scans.
  - Telemetry retrieval (`app.telemetry_points`): Filtered by `(assignment_id, occurred_at ASC)`. Existing index `idx_telemetry_assignment_time` covers `(assignment_id, occurred_at, event_id)`.
  - Key Foreign Keys without leading indexes: 71 foreign keys lacked indexes, notably `trip_assignments(trip_id)` and `trip_assignments(vehicle_id)`.
  - Migration Runner Transaction Compatibility: `scripts/migrate_postgres.py` wraps each `.sql` file in `with conn.cursor() as cur: ... conn.commit()`. Postgres forbids `CREATE INDEX CONCURRENTLY` inside transaction blocks. Therefore, standard transactional migrations use standard `CREATE INDEX IF NOT EXISTS`, and an opt-in non-transactional concurrent CLI script is provided for zero-lock production operational apply.

---

## 2. Implementation & Test Plan

### Step 1: Profiling & Inventory Tool (`scripts/db_profile.py` & `src/services/db_profiler.py`)
- Safe allowlisted read-only workloads (case queue, trip-assignment lookup, driver scorecard, telemetry query, precedent lookup).
- Bound parameters, bounded timeouts (`statement_timeout = '5s'`).
- JSON output with `EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)`.
- Live audit mode (sanitized, zero secrets) writing structured evidence to `/tmp/greensentinel-indexes-before.json`.
- Test suite: `tests/unit/test_db_profiler.py` mocking DB connections, validating allowlist enforcement, timeout bounds, and plan parsing.

### Step 2: Additive Index Migration & Rollback
- Migration [`db/migrations/20261015150000_workload_performance_indexes.sql`](../../db/migrations/20261015150000_workload_performance_indexes.sql):
  - `idx_trip_assignments_trip_id`: `ON app.trip_assignments (trip_id)` (addresses missing general trip_id coverage; verified 58% speedup and 75% buffer reduction).
  - Evaluated case queue index: pruned and removed from migration per empirical evidence (showed no demonstrated speedup on 100-case fixture).
  - Speculative/redundant indexes removed (evidence snapshots covered by unique constraint backward scan).
- Rollback [`db/rollbacks/20261015150000_workload_performance_indexes.down.sql`](../../db/rollbacks/20261015150000_workload_performance_indexes.down.sql).
- Bounded migration runner [`scripts/apply_workload_indexes.py`](../../scripts/apply_workload_indexes.py) with lock and statement timeouts and `--expected-plan-hash` preflight.

### Step 3: Disposable Benchmark & Performance Comparison Test
- Integration fixture test [`tests/integration/test_db_performance_bench.py`](../../tests/integration/test_db_performance_bench.py):
  - Strict pre-connect target guards (`validate_disposable_database_url()`).
  - Controlled realistic fixture (3,100 trip assignments, 100 trips, 100 cases).
  - Repeated warm runs (N=15) recording medians, buffer counts, costs, and plan nodes.
  - 100% byte-for-byte query result equality asserted.
  - Retained machine artifact in [`docs/testing/artifacts/db_bench_evidence_394.json`](../testing/artifacts/db_bench_evidence_394.json).

### Step 4: Documentation & Conductor Artifacts
- Record detailed evidence in [`docs/testing/DB_OPTIMIZATION_394.md`](../testing/DB_OPTIMIZATION_394.md).
- Multi-environment sanitized audits saved in `/tmp/greensentinel-indexes-before-{dev,staging,prod}.json`.
- Conductor command provided for staged live apply post-review.

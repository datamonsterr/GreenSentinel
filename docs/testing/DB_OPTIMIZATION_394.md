# Database Optimization & Workload Performance Evidence (#394 / #399)

**Date:** 2026-10-16  
**Slice:** `indexes`  
**Parent Issue:** #394  
**Child Issue:** #399  
**Target Environments Audited:** Railway `dev`, `staging`, `production` (Project `c49458fb-d741-468f-a3ed-d35b96788f68`, Service `9710a2f5-ed77-472e-8e79-3b748bb73df2`)  
**Disposable Benchmark DB:** PostgreSQL 16.4 container on `localhost:5432/test_greensentinel_bench`  
**Retained Machine Artifact:** [`artifacts/db_bench_evidence_394.json`](artifacts/db_bench_evidence_394.json)  

---

## 1. Executive Summary & Safety Guardrails

- **Zero Live Mutations During Remediation:** Live databases were audited strictly in read-only mode using bounded `EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)` within transactional rollbacks (`conn.transaction(force_rollback=True)`), bounded statement timeouts (`5000ms`), and zero `enable_seqscan` toggling. No shared database indexes were applied.
- **Zero Credential Exposure:** Database connection parameters are resolved in-process through Railway CLI proxies. DSNs, conninfo strings, passwords, and tokens are automatically redacted by `DatabaseProfiler.sanitize_connection_info()` and `redact_dsn_password()`. Reports expose only public environment identities (`target`, `host`, `database`).
- **Target Safety Validator:** Integration benchmark tests enforce pre-connect target validation via `validate_disposable_database_url()`. Execution strictly requires loopback hostnames (`localhost`, `127.0.0.1`, `::1`), a `test_` prefixed database name, and an explicit opt-in variable (`CONFIRM_DISPOSABLE_TEST_DB=1`). Rejects all Railway, production, staging, and dev shared instances.
- **Deduplication & Justification:**
  - Removed redundant `app.evidence_snapshots(case_id, version DESC)` index: table `app.evidence_snapshots` already contains a unique constraint `UNIQUE (case_id, version)` defined in [`db/migrations/0001_poc_core.sql`](../../db/migrations/0001_poc_core.sql#L315), which PostgreSQL B-tree scans backwards natively with identical efficiency.
  - Evaluated case queue ordering on 100 cases fixture: showed no demonstrated benefit (0.154 ms -> 0.150 ms) because the small table sequential scan is executed sub-millisecond in memory. Unsupported queue index was pruned and removed from the migration per empirical evidence.
  - Retained only the single justified, workload-measured index: `app.idx_trip_assignments_trip_id`.
- **Bounded Migration Tooling:** Deprecated and eliminated recommendations to use `scripts/migrate_postgres.py` for live index operations (which executes destructive `DROP EXTENSION CASCADE` and mock data seeding). Created dedicated [`scripts/apply_workload_indexes.py`](../../scripts/apply_workload_indexes.py) with lock timeouts (`5s`), statement timeouts (`30s`), dry-run preflight emitting canonical SHA256 plan hashes, and `--expected-plan-hash` fail-closed verification.

---

## 2. Multi-Environment Live Database Audits (BEFORE State)

Audited via `scripts/db_profile.py --env <env> --audit-all` across all three environments with zero secret exposure.

### Environment Baseline Entity Counts
| Environment | Organizations | Principals | Drivers | Trips | Assignments | Telemetry Points | Cases | Simulation Runs | Schema Migrations |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `dev` | 1 | 43 | 121 | 102 | 102 | 2,585 | 102 | 5 | 27 |
| `staging` | 1 | 33 | 120 | 100 | 100 | 1,400 | 100 | 5 | 27 |
| `production` | 1 | 35 | 120 | 100 | 100 | 1,400 | 100 | 5 | 17 |

### Multi-Environment Schema & Tenant Invariants
- **Tenant Isolation Verified:** All three environments confirmed to have 1 organization (`orgs=1`), 0 null `organization_id` trips, and 0 cross-organization driver-trip linkages (`cross_org_linkages=0`).
- **Live Schema History Divergence:** Production reflects migration history up to `20261014000000_case_documents.sql` (17 migrations applied), whereas dev and staging have 27 migrations applied. Read-only preflight schema verification checks table and column availability prior to any migration execution.
- **Index Inventory & Foreign Key Status:**
  - `dev`: 165 indexes in schema `app`, 71 unindexed foreign key constraints.
  - `staging`: 165 indexes in schema `app`, 71 unindexed foreign key constraints.
  - `production`: 145 indexes in schema `app`, 70 unindexed foreign key constraints.
- **Primary Bottleneck Identified:**
  - `app.trip_assignments(trip_id)`: Foreign key only partially indexed by `uq_trip_one_active_assignment` on active states (`state IN ('accepted', 'arrived', 'started')`). All queries for historical, completed, or cancelled trips were forced into sequential scans across `app.trip_assignments`.

---

## 3. Empirical Controlled Benchmark (BEFORE vs AFTER on Disposable DB)

Benchmarking executed on disposable local PostgreSQL 16 container (`localhost:5432/test_greensentinel_bench`) with realistic cardinality fixture:
- Trips: 100
- Trip assignments: 3,100
- Fraud cases: 100

Each metric reflects statistical medians computed over **15 repeated warm sample runs** (after 5 initial cache warm-ups). Machine evidence recorded in [`artifacts/db_bench_evidence_394.json`](artifacts/db_bench_evidence_394.json) with full execution plans retained.

### Comparison Table (Generated from Machine Artifact `db_bench_evidence_394.json`)
| Workload Query | Metric | BEFORE (Baseline) | AFTER (Indexed) | Improvement / Delta |
| :--- | :--- | :--- | :--- | :--- |
| **Trip Assignment by Trip** (`trip_assignment_by_trip`) | Plan Node | `Seq Scan` | `Bitmap Heap Scan` on `idx_trip_assignments_trip_id` | Full table scan eliminated, direct index lookup |
| | Total Cost | 172.75 | 78.51 | **54.55% cost reduction** |
| | Median Exec Time | 0.274 ms | 0.115 ms | **58.0% speedup** |
| | P95 Exec Time | 0.414 ms | 0.153 ms | **63.0% p95 tail reduction** |
| | Shared Hit Blocks | 134 blocks | 33 blocks | **75.37% buffer I/O reduction** |
| **Organization Case Queue** (`org_case_queue`) | Plan Node | `Limit` | `Limit` | Baseline in-memory table scan |
| | Total Cost | 4.76 | 4.76 | Unchanged (no index applied) |
| | Median Exec Time | 0.154 ms | 0.150 ms | Sub-millisecond on 100-case fixture |
| | Shared Hit Blocks | 3 blocks | 3 blocks | In-memory buffer parity |
| | Scope Status | - | - | **Pruned from migration** (no benefit demonstrated on 100 cases) |

### Correctness & Data Integrity Invariants
- **100% Query Result Equality:** Full result set tuples before and after index application were asserted to be 100% byte-for-byte identical in [`tests/integration/test_db_performance_bench.py`](../../tests/integration/test_db_performance_bench.py). Zero row drift, data corruption, or sort divergence.
- **Retained Full Execution Plans:** Both baseline and indexed execution plans are retained in full JSON structure in [`artifacts/db_bench_evidence_394.json`](artifacts/db_bench_evidence_394.json).
- **Index Sizes:**
  - `app.idx_trip_assignments_trip_id`: 40 kB (40,960 bytes)

---

## 4. Additive Migration & Conductor Instructions

### Additive Migration Scripts
- Migration: [`db/migrations/20261015150000_workload_performance_indexes.sql`](../../db/migrations/20261015150000_workload_performance_indexes.sql)
- Rollback: [`db/rollbacks/20261015150000_workload_performance_indexes.down.sql`](../../db/rollbacks/20261015150000_workload_performance_indexes.down.sql)

### Conductor Instructions for Live Application
> [!IMPORTANT]
> **DO NOT APPLY TO SHARED DB DIRECTLY.** Final conductor performs reviewed apply using the bounded runner [`scripts/apply_workload_indexes.py`](../../scripts/apply_workload_indexes.py). Never use `scripts/migrate_postgres.py` for live index operations.

```bash
# 1. Dry-run preflight check (verifies schema readiness and emits canonical plan hash without executing DDL)
python3 scripts/apply_workload_indexes.py --env dev
python3 scripts/apply_workload_indexes.py --env staging
python3 scripts/apply_workload_indexes.py --env production

# 2. Conductor-approved execution with lock timeout (5s), statement timeout (30s), and expected-plan-hash:
python3 scripts/apply_workload_indexes.py --env dev --confirm-apply --expected-plan-hash <HASH_DEV>
python3 scripts/apply_workload_indexes.py --env staging --confirm-apply --expected-plan-hash <HASH_STAGING>
python3 scripts/apply_workload_indexes.py --env production --confirm-apply --expected-plan-hash <HASH_PROD>

# 3. Post-apply audit and verification:
python3 scripts/db_profile.py --env dev --audit-all --output-json /tmp/greensentinel-indexes-after-dev.json
python3 scripts/db_profile.py --env staging --audit-all --output-json /tmp/greensentinel-indexes-after-staging.json
python3 scripts/db_profile.py --env production --audit-all --output-json /tmp/greensentinel-indexes-after-prod.json
```

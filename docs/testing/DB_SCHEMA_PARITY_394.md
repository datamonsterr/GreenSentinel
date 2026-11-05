# Database Schema Parity Verification & Safe Ownership Migration — Issue #394 / Child Task #423

Date: 2026-10-16  
Author: AGY Implementation Worker  
Parent Map: [#394](https://github.com/AI20K-Build-Phase-Cohort-4/P-063/issues/394)  
Child Task: [#423](https://github.com/AI20K-Build-Phase-Cohort-4/P-063/issues/423)  
Bounded Ownership: `db/migrations/20261016000000_test_store_schema_parity.sql`, `db/rollbacks/20261016000000_test_store_schema_parity.down.sql`, `scripts/rollback_schema_parity_394.py`, `tests/unit/test_db_schema_parity.py`, `tests/integration/test_db_schema_parity_integration.py`, and this document.

---

## 1. Scope and Isolation Boundary

This verification establishes additive schema parity across Railway `dev`, `staging`, and `production` database clones without mutating shared environments or root worker clones.

> [!IMPORTANT]
> **Isolated Validation Proof Only**: All verification was executed on dedicated, disposable local clones (`test_p063_schema_parity_dev`, `test_p063_schema_parity_staging`, `test_p063_schema_parity_prod`) hosted within local Docker container `p063-postgres` at `127.0.0.1:5432`. No shared database writes, live Railway applies, PR merges, or deployments were performed. Final live application remains blocked until accepted review under coordinator issue [#397](https://github.com/AI20K-Build-Phase-Cohort-4/P-063/issues/397).

---

## 2. Root Cause Analysis of Schema Drift

Original catalog audits (`/tmp/p063-schema-audit.json`, `/tmp/p063-schema-parity-diff.json`) revealed discrepancies across environments:

1. **Historical Migration In-Place Mutation**:
   - In commit `3277f576896f91e481628cf09efd19699dd4c4f6`, `db/migrations/20261014090000_tester_org_ownership.sql` originally added nullable `organization_id uuid` columns to 8 test-store child tables (`app.test_controls`, `app.test_definition_revisions`, `app.test_events`, `app.test_idempotency_keys`, `app.test_notifications`, `app.test_outbox`, `app.test_runs`, `app.test_samples`).
   - Dev and staging environments applied this initial version, recording `20261014090000_tester_org_ownership.sql` in `public.schema_migrations`.
   - Subsequently, `db/migrations/20261014090000_tester_org_ownership.sql` was modified in-place in the source repository to declare `app.test_run_requests` and `app.test_cases`, add `messages jsonb NOT NULL DEFAULT '[]'::jsonb`, and convert `test_plans.created_by` from `UUID` to `TEXT`.
   - Because dev and staging ledgers already recorded the version as applied, the newly added tables and columns were never executed on dev or staging.
2. **Production Backup Lag**:
   - The production full backup was taken at ledger version 17 (`20261014000000_case_documents.sql`).
   - Applying the 10 missing migrations brought production to ledger version 27, creating `app.test_run_requests`, `app.test_cases`, and `messages`, but leaving production missing the 8 child `organization_id` columns.
3. **Apparent Constraint Divergence Was Artifact of Session `search_path`**:
   - Unnormalized catalog comparison showed 252 constraint differences due to session search path formatting in `pg_get_constraintdef()`.
   - Normalizing comparison with `SET LOCAL search_path=pg_catalog` confirmed zero foreign key mismatches on pre-existing tables.

---

## 3. Implementation: Additive Migration 20261016000000

The migration [`db/migrations/20261016000000_test_store_schema_parity.sql`](file:///home/dat/dev/vinuni_aia/P-063-worktrees/worktrees/jev-9e132981a0fe4dd4/db/migrations/20261016000000_test_store_schema_parity.sql) reconciles all differences:

1. **Explicit Schema Qualification**: All table, column, and index declarations explicitly use `app.` prefixes with zero reliance on session `search_path`.
2. **Strictly Additive**:
   - Adds `organization_id uuid NULL` via `ADD COLUMN IF NOT EXISTS` to all 8 child tables: `app.test_controls`, `app.test_definition_revisions`, `app.test_events`, `app.test_idempotency_keys`, `app.test_notifications`, `app.test_outbox`, `app.test_runs`, `app.test_samples`.
   - Adds `messages jsonb NOT NULL DEFAULT '[]'::jsonb` to `app.test_definition_revisions`.
   - Safely alters `app.test_plans.created_by` to `TEXT` using `created_by::text` only if the column is currently `uuid` or compatible, preserving existing data.
   - Creates missing tables `app.test_run_requests` and `app.test_cases` matching source contracts with cascading foreign keys to `app.test_runs(id)`.
3. **Workload-Appropriate Foreign Key Indexing**:
   - Created `idx_test_run_requests_run` on `app.test_run_requests(run_id)` per Postgres best practices to support cascading deletes and joins.
   - Synchronized `idx_test_cases_run`, `idx_test_runs_definition`, and test-store org composite indexes across all environments.
4. **Safe Organization Ownership Propagation**:
   - Propagates `organization_id` strictly when unambiguous from a validated parent row referencing an existing `app.organizations(id)`.
   - Preserves existing non-NULL child `organization_id`.
   - Conflicting parent/child organization IDs are quarantined in `app.org_quarantine` with reason `parent_child_org_conflict`, never silently overwritten.
   - Unowned legacy rows (with NULL organization) are preserved as NULL and recorded in `app.org_quarantine`.
   - No global backfill to default org; no fake mock seeding.
5. **Fail-Closed Diagnostics**: Validates pre-existing table schemas before alteration; raises descriptive exceptions if schema contracts differ incompatibly.

---

## 4. Exact Catalog Parity Results

Catalog definitions were extracted using `SET LOCAL search_path=pg_catalog` and compared across all three restored disposable clones:

| Metric | `test_p063_schema_parity_dev` | `test_p063_schema_parity_staging` | `test_p063_schema_parity_prod` | Parity Status |
|---|---|---|---|---|
| Total Tables (`app` + `public`) | **71** (70 `app`, 1 `public`) | **71** (70 `app`, 1 `public`) | **71** (70 `app`, 1 `public`) | **100% Match** |
| Total Columns (`app` + `public`) | **671** (669 `app`, 2 `public`) | **671** (669 `app`, 2 `public`) | **671** (669 `app`, 2 `public`) | **100% Match** |
| Constraints (`app`) | **359** | **359** | **359** | **100% Match** |
| Indexes (`app`) | **170** | **170** | **170** | **100% Match** |
| Column Types & Nullability | Identical | Identical | Identical | **100% Match** |
| Foreign Key & Check Definitions | Identical | Identical | Identical | **100% Match** |

---

## 5. Data Preservation & Idempotency Evidence

### 5.1 Pre-existing Data Preservation
- Evaluated all 63 pre-existing tables in production and dev against their baseline fingerprints.
- Pre-existing table data hashes and row counts remained **100% unchanged** after applying migration `20261016000000_test_store_schema_parity.sql`.
- `app.test_plans.created_by` logical UUID string values were preserved during type widening to `TEXT`.

### 5.2 Idempotency Proof
- Migration `20261016000000_test_store_schema_parity.sql` was re-applied to the already-migrated database clones.
- Result: **Zero schema drift** and **zero data drift**. Table, column, constraint, and index counts remained identical.

---

## 6. Safe Rollback Guidance

> [!CAUTION]
> **Destructive Down-Scripts Are Prohibited**:
> Executing `DROP TABLE` or `DROP COLUMN` on test-store tables would drop columns (`organization_id`, etc.) that pre-existed on Railway `dev` and `staging` before this migration, causing severe data loss.

### Rollback Strategy:
1. **In-Place Backward Compatibility**:
   All changes in `20261016000000_test_store_schema_parity.sql` are purely additive. Application code natively tolerates both pre- and post-migration states. To unmark the migration without dropping schema objects:
   ```sql
   DELETE FROM public.schema_migrations WHERE version = '20261016000000_test_store_schema_parity.sql';
   ```
2. **Full Hard Restore (If Exact Pre-Migration Snapshot Required)**:
   Use the verified restore-tested full backups (taken at `20261015T173125Z`):
   - **Dev**: SHA256 `ca1b85fbf900de8c5187e68dfac251ea5cd7ef04fc1096b35b7d85401d34b166` (`dev.dump`)
   - **Staging**: SHA256 `71133c4f5020bcbd2066708a4dd4d761607a54ce9311c4d280cc9410670b82f2` (`staging.dump`)
   - **Production**: SHA256 `f72331f9085c5f87ce0d91ebeb018228dfcc84f4205833ca02690fc62a8cc321` (`production.dump`)

Tool script [`scripts/rollback_schema_parity_394.py`](file:///home/dat/dev/vinuni_aia/P-063-worktrees/worktrees/jev-9e132981a0fe4dd4/scripts/rollback_schema_parity_394.py) verifies backup archive availability on disk via `--check-backups`.

---

## 7. Test Suite Summary

- **Unit Tests**: [`tests/unit/test_db_schema_parity.py`](file:///home/dat/dev/vinuni_aia/P-063-worktrees/worktrees/jev-9e132981a0fe4dd4/tests/unit/test_db_schema_parity.py)
  - 10 passed (syntax validation, schema qualification, non-destructive constraints, FK index coverage, quarantine reason registry, rollback script invariants).
- **Integration Tests**: [`tests/integration/test_db_schema_parity_integration.py`](file:///home/dat/dev/vinuni_aia/P-063-worktrees/worktrees/jev-9e132981a0fe4dd4/tests/integration/test_db_schema_parity_integration.py)
  - 5 passed (full backup restore, missing 10 precondition, catalog parity across dev/staging/prod, data hash preservation, idempotency, unambiguous backfill, unknown owner quarantine, conflicting owner preservation).
- **Total Test Execution**: 15 passed, 0 failed, 0 skipped.

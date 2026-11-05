# Database Identity Reconciliation Report (#394 / #402 / #410)

- **Date**: 2026-10-16
- **Slice**: `sync` (Bounded database identity reconciliation and mock cleanup)
- **Parent Issues**: [#394](https://github.com/AI20K-Build-Phase-Cohort-4/GreenSentinel/issues/394) (Master Data Finalization), [#402](https://github.com/AI20K-Build-Phase-Cohort-4/GreenSentinel/issues/402) (Aggregate Identity)
- **Child Task**: [#410](https://github.com/AI20K-Build-Phase-Cohort-4/GreenSentinel/issues/410)
- **Implementation Branch**: `jev-587cd00e04964446`
- **Deliverables**:
  - Service: [`identity_reconciliation.py`](file:///home/dat/dev/vinuni_aia/GreenSentinel-worktrees/worktrees/jev-587cd00e04964446/src/services/identity_reconciliation.py)
  - CLI: [`reconcile_identity.py`](file:///home/dat/dev/vinuni_aia/GreenSentinel-worktrees/worktrees/jev-587cd00e04964446/scripts/reconcile_identity.py)
  - Unit Tests: [`test_identity_reconciliation.py`](file:///home/dat/dev/vinuni_aia/GreenSentinel-worktrees/worktrees/jev-587cd00e04964446/tests/unit/test_identity_reconciliation.py)
  - CLI Tests: [`test_reconcile_identity_cli.py`](file:///home/dat/dev/vinuni_aia/GreenSentinel-worktrees/worktrees/jev-587cd00e04964446/tests/unit/test_reconcile_identity_cli.py)
  - Integration Tests: [`test_identity_reconciliation_integration.py`](file:///home/dat/dev/vinuni_aia/GreenSentinel-worktrees/worktrees/jev-587cd00e04964446/tests/integration/test_identity_reconciliation_integration.py)
  - Implementation Design: [`docs/superpowers/plans/2026-10-15-db-identity-reconciliation.md`](file:///home/dat/dev/vinuni_aia/GreenSentinel-worktrees/worktrees/jev-587cd00e04964446/docs/superpowers/plans/2026-10-15-db-identity-reconciliation.md)

---

## 1. Executive Summary & Boundary Isolation

This slice delivers repository-owned, audited dry-run and transactional apply tooling to synchronize Clerk identity state across Railway `dev`, `staging`, and `production` PostgreSQL databases, remediating SQLSTATE 23514 CHECK constraint failures, handling append-only trigger maintenance, enforcing catalog-derived FK closure, and preventing destructive deletion of real business records.

### Sibling Ownership & Non-Overlap
- **Sync Slice (This Worker, #410)**:
  - Repository-owned dry-run audit, plan validation, and transactional apply tooling.
  - Paginated completed fetch verification for Clerk organizations and memberships.
  - Dynamic discovery of established Clerk organization mapping from `app.organizations.clerk_organization_id` (zero hardcoded IDs).
  - Deterministic UUID5 organization mapping with collision detection for newly discovered Clerk organizations.
  - Canonical role reconciliation (`org:admin` -> `admin`, `org:member`/`analyst` -> `fraud_analyst`, `org:driver` -> `driver`; unknown roles rejected).
  - Demotion handling and stale role removal (no silent retention of admin privileges).
  - Deactivation of orphaned real principals (`status='disabled'`, satisfying `principals_status_check` constraint; preserving historical FK records).
  - Display name synchronization from trusted Clerk profile names (zero invented `User xxxx` fake aliases).
  - Proven mock lineage deletion with audited 24-table child-first topological FK closure.
  - Fail-closed isolation: raises [`MockPrincipalReferenceError`](file:///home/dat/dev/vinuni_aia/GreenSentinel-worktrees/worktrees/jev-587cd00e04964446/src/services/identity_reconciliation.py) if any mock principal has references outside approved fixture cases; real cases and audit events are NEVER deleted via mock actor FKs.
  - Transactional append-only trigger maintenance (`app.reject_mutation()`, SQLSTATE 55000): temporary scoped disable/re-enable under lock with restoration proof.
  - Real restorable recovery export dumping actual row data with strict `mode 0600`.
  - Disposable DB guard with mandatory loopback, disposable prefix, and explicit opt-in.
- **Binding Slice (Sibling Worker)**:
  - Owns `src/services/access_control.py` (driver JIT binding).
  - Owns `src/services/auth.py`.
  - Owns `.github/workflows/deploy-railway.yml` (disabling automatic mock seeder execution).
  - Owns migration runners (`scripts/migrate_postgres.py`).

---

## 2. Source Audit Baseline (Clerk Development Instance)

- **Total Clerk Users**: 18
- **Total Clerk Organizations**: 10
- **Total Clerk Memberships**: 12 (10 `org:admin`, 1 `org:member`, 1 `org:driver`)
- **Established Seed Organization**: Discovered dynamically from database (`app.organizations.clerk_organization_id`).
- **New Organizations**: 9 organizations mapped deterministically via UUID5 (`https://greensentinel.internal/org/{clerk_org_id}`).

---

## 3. Sanitized Environment Audits & Reconciliation Plans

All emails, personal names, and database connection strings are masked via 12-character SHA-256 opaque digests.

### Environment: `dev`
- **Initial Counts**: 1 organization, 43 principals, 102 fraud cases, 102 trips.
- **Migration History**: 27 migrations applied (latest: `20261015130000_tester_publish_submissions.sql`).
- **Organizations**:
  - Create: 9 new organizations with deterministic UUID5.
  - Unchanged: 1 established seed organization.
- **Principals & Roles**:
  - Create: 9 real principals with mapped active Clerk roles.
  - Role Update / Demotion: 1 real principal demoted/adjusted to exact Clerk membership role.
  - Deactivate (Preserve FK): 10 real principals with no active membership marked `status='disabled'` (satisfying `CHECK status IN ('active', 'disabled')`).
  - Delete (Proven Mock): 30 mock principals (`user_clerk_analyst_001`..`010`, `drv_gsm_0001`..`0020`).
- **Mock Cases & Data**:
  - Delete: 100 proven mock cases (`018f2f4e-a000-7000-8000-000000000001`..`0100`).
  - Preserve: 2 real non-mock cases (`6ed41b7e-8bab-40c4-b1bb-741bb543ffd9`, `22c3b317-c414-432e-94db-c28d10bd82eb`).
  - Topological Deletion Closure: 24 child-first tables (including `model_assessments`, `feature_sets`, `sanctions`, `case_agent_messages`, `precedent_workflows`, `audit_events`).

### Environment: `staging`
- **Initial Counts**: 1 organization, 33 principals, 100 fraud cases, 100 trips.
- **Migration History**: 27 migrations applied.
- **Organizations**:
  - Create: 9 new organizations with deterministic UUID5.
  - Unchanged: 1 established seed organization.
- **Principals & Roles**:
  - Create: 9 real principals with mapped active Clerk roles.
  - Role Update / Demotion: 3 real principals with conflicting or stale roles reconciled.
  - Deactivate: 0
  - Delete (Proven Mock): 30 mock principals.
- **Mock Cases**:
  - Delete: 100 proven mock cases.
  - Child-first FK cleanup across 24 tables.

### Environment: `production`
- **Initial Counts**: 1 organization, 35 principals, 100 fraud cases, 100 trips.
- **Migration History**: 17 migrations applied (latest: `20261014000000_case_documents.sql`).
- **Organizations**:
  - Create: 9 new organizations with deterministic UUID5.
  - Unchanged: 1 established seed organization.
- **Principals & Roles**:
  - Create: 12 real principals with mapped active Clerk roles.
  - Role Update / Demotion: 0
  - Deactivate (Preserve FK): 5 real principals with no active membership marked `status='disabled'`.
  - Delete (Proven Mock): 30 mock principals.
- **Mock Cases**:
  - Delete: 100 proven mock cases.
  - Dynamic discovery adapts for absent tables without unreviewed migrations.

---

## 4. Safety Architecture & Invariants

1. **Deterministic UUID5 Org Idempotence & Collision Detection**:
   - Seed org mappings discovered dynamically from `app.organizations`.
   - All new orgs derive UUID5 deterministically; collision detection rejects conflicting mappings before write.
2. **Safe Role Synchronization**:
   - `org:admin` -> `admin`
   - `org:member` / `member` / `analyst` -> `fraud_analyst` (canonical internal)
   - `org:driver` -> `driver`
   - Unknown roles are rejected. Demotions cleanly replace stale roles; no silent retention of admin privileges.
3. **Zero Destruction on Incomplete Data**:
   - Paginated Clerk fetch validates that received counts equal total counts.
   - Partial API failures or HTTP 429 rate limits raise [`ClerkAPIError`](file:///home/dat/dev/vinuni_aia/GreenSentinel-worktrees/worktrees/jev-587cd00e04964446/src/services/identity_reconciliation.py) and refuse plan generation.
4. **Human Record Preservation & Status Check Compliance**:
   - Real principals without active memberships are set to `status = 'disabled'` (eliminating SQLSTATE 23514) and have roles removed, preserving historical references.
5. **Fail-Closed Real Record Protection**:
   - `_verify_mock_principals_isolation` raises [`MockPrincipalReferenceError`](file:///home/dat/dev/vinuni_aia/GreenSentinel-worktrees/worktrees/jev-587cd00e04964446/src/services/identity_reconciliation.py) if any mock principal has relationships outside approved fixture closure.
   - Real cases, adjudications, and audit records referencing mock actors are NEVER deleted.
6. **Append-Only Trigger Maintenance**:
   - 10 tables protected by `EXECUTE FUNCTION app.reject_mutation()` raising SQLSTATE 55000.
   - Scoped maintenance temporarily disables ONLY the identified trigger under bounded transaction lock, restores it before commit and on rollback, and proves unrelated append-only records remain protected.
7. **Mode 0600 Scoped Recovery Export**:
   - Before any live database mutation, all affected row contents are dumped to a recovery file with strict owner-only permissions (`0o600`).
8. **Transaction Isolation & Stale-Plan Protection**:
   - `SET LOCAL lock_timeout = '5s'` executed before acquiring `pg_advisory_xact_lock`.
   - Under lock, canonical schema fingerprint (columns, types, CHECK, FKs, triggers) and data identity fingerprints are re-read and validated; any drift fails closed.
9. **Disposable DB Guard**:
   - [`assert_disposable_db_guard`](file:///home/dat/dev/vinuni_aia/GreenSentinel-worktrees/worktrees/jev-587cd00e04964446/src/services/identity_reconciliation.py) verifies loopback connection (`127.0.0.1` / `localhost`), prefix requirement (`test_greensentinel_finalize_394_` or `test_greensentinel_disposable_`), and opt-in env var (`GREENSENTINEL_RECONCILE_DISPOSABLE_DB=1`). No remote bypass.

---

## 5. Verification & Test Evidence

### Test Execution
```bash
.venv/bin/pytest tests/unit/test_identity_reconciliation.py \
                 tests/unit/test_reconcile_identity_cli.py \
                 tests/integration/test_identity_reconciliation_integration.py
```

### Observed Result
```
============================= test session starts ==============================
platform linux -- Python 3.13.13, pytest-9.1.1, pluggy-1.6.0
rootdir: /home/dat/dev/vinuni_aia/GreenSentinel-worktrees/worktrees/jev-587cd00e04964446
configfile: pyproject.toml
plugins: asyncio-1.4.0, langsmith-0.12.4, anyio-4.15.1, xdist-3.8.0
asyncio: mode=Mode.AUTO, debug=False, asyncio_default_fixture_loop_scope=None, asyncio_default_test_loop_scope=function
collected 32 items

tests/unit/test_identity_reconciliation.py ..................            [ 56%]
tests/unit/test_reconcile_identity_cli.py .....                          [ 71%]
tests/integration/test_identity_reconciliation_integration.py .........  [100%]

============================= 32 passed in 14.30s ==============================
```

- **Unit Suite (18 tests / 23 cases)**:
  - Role mapping & unknown role rejection
  - UUID5 determinism & collision detection
  - Pagination completeness & error handling
  - Conflicting membership role resolution ([`ClerkMembershipConflictError`](file:///home/dat/dev/vinuni_aia/GreenSentinel-worktrees/worktrees/jev-587cd00e04964446/src/services/identity_reconciliation.py))
  - Orphaned principal deactivation with `status='disabled'`
  - Display name synchronization without synthetic aliases
  - Mode 0600 file permissions and recovery dump structure
  - FakeConnection / FakeCursor unit boundary contracts
  - PII sanitization and masking
- **CLI Suite (5 tests)**:
  - Required environment flags
  - Read-only audit with snapshot file
  - JSON plan output formatting
  - Expected plan hash enforcement
  - Live apply protection guards
- **Integration Suite (9 tests against real PostgreSQL clones in `greensentinel-postgres`)**:
  - `test_e2e_reconciliation_full_lifecycle`: Full audit -> plan -> apply -> verify -> repeated no-op lifecycle on real PostGIS clone.
  - `test_rollback_after_mid_delete_error`: Proves 100% transactional rollback when mid-delete execution errors.
  - `test_schema_drift_rejection_under_lock`: Detects table schema alterations and rejects stale plan under advisory lock.
  - `test_stale_data_rejection_under_lock`: Detects concurrent row insertions/mutations and rejects execution.
  - `test_unrelated_real_case_referencing_mock_principal_rejected`: Proves fail-closed isolation when a real fraud case references a mock principal.
  - `test_trigger_restoration_and_unrelated_record_protection`: Verifies append-only triggers (`app.reject_mutation()`, SQLSTATE 55000) are re-enabled and continue protecting unrelated audit/case rows.
  - `test_two_org_isolation`: Asserts cross-org boundaries are strictly preserved during mutation.
  - `test_missing_column_or_table_detection`: Validates catalog discovery against schema differences.
  - `test_loopback_connection_guard`: Enforces loopback, disposable prefix, and opt-in guards.

---

## 6. Runnable Tooling Commands

```bash
# 1. Read-only Audit (Offline Mode)
python scripts/reconcile_identity.py --audit --env dev --clerk-snapshot-file /tmp/greensentinel-identity-audit.json --offline

# 2. Output Plan in JSON format
python scripts/reconcile_identity.py --plan --json --env staging --offline

# 3. Apply on Disposable Clone (Requires opt-in env var)
GREENSENTINEL_RECONCILE_DISPOSABLE_DB=1 python scripts/reconcile_identity.py --apply --env dev \
    --database-url "postgresql://postgres:postgrespassword@127.0.0.1:5432/test_greensentinel_finalize_394_dev_20261015t173125z" \
    --expected-plan-hash "<computed-hash>" \
    --recovery-dir "$TMPDIR"
```

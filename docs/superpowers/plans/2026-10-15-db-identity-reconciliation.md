# Implementation Plan: Database Identity Reconciliation (#410 / #402 / #394)

- Date: 2026-10-16
- Author: AGY-only Sync Worker
- Parent Issues: [#402](https://github.com/AI20K-Build-Phase-Cohort-4/GreenSentinel/issues/402), [#394](https://github.com/AI20K-Build-Phase-Cohort-4/GreenSentinel/issues/394)
- Child Task Issue: [#410](https://github.com/AI20K-Build-Phase-Cohort-4/GreenSentinel/issues/410)
- Branch: `jev-587cd00e04964446`
- Slice: `sync` (bounded)

## 1. Scope & Non-Overlap Contract

### Owned Files
- [`src/services/identity_reconciliation.py`](file:///home/dat/dev/vinuni_aia/GreenSentinel/src/services/identity_reconciliation.py) (NEW reconciliation service)
- [`scripts/reconcile_identity.py`](file:///home/dat/dev/vinuni_aia/GreenSentinel/scripts/reconcile_identity.py) (NEW audited dry-run/apply CLI)
- [`tests/unit/test_identity_reconciliation.py`](file:///home/dat/dev/vinuni_aia/GreenSentinel/tests/unit/test_identity_reconciliation.py) (NEW focused unit suite)
- [`tests/integration/test_identity_reconciliation_integration.py`](file:///home/dat/dev/vinuni_aia/GreenSentinel/tests/integration/test_identity_reconciliation_integration.py) (NEW disposable DB suite)
- [`docs/testing/DB_IDENTITY_RECONCILIATION_394.md`](file:///home/dat/dev/vinuni_aia/GreenSentinel/docs/testing/DB_IDENTITY_RECONCILIATION_394.md) (Reconciliation audit report)
- [`docs/superpowers/plans/2026-10-15-db-identity-reconciliation.md`](file:///home/dat/dev/vinuni_aia/GreenSentinel/docs/superpowers/plans/2026-10-15-db-identity-reconciliation.md) (This plan)

### Excluded Files (Owned by Sibling Workers)
- `src/services/access_control.py` (sibling binding worker owns driver JIT)
- `src/services/auth.py` (sibling binding worker owns token verification)
- `.github/workflows/deploy-railway.yml` (sibling binding worker owns bootstrap prevention)
- `scripts/migrate_postgres.py` (migration runner untouched)

---

## 2. Technical Architecture & Invariants

```
 +-----------------------------------------------------------------------------------+
 |                             Clerk API (Single Dev Instance)                        |
 |  10 Organizations (1 established, 9 new) | 18 Users | 12 Active Memberships        |
 +-----------------------------------------------------------------------------------+
                                           |
                                           v
 +-----------------------------------------------------------------------------------+
 |                   IdentityReconciliationService (Read-Only Audit)                 |
 |  1. Paginated Completed Fetch Verification (fail closed on partial / 429)         |
 |  2. Deterministic UUID5 Organization Mapping (canonical preservation of seed org) |
 |  3. Strict Role Mapping: org:admin->admin, member/analyst->fraud_analyst, driver  |
 |  4. Orphaned Principal Deactivation (preserve human FK records, revoke access)    |
 |  5. Proven Mock Lineage Identification (fixture external refs & seed cases)       |
 |  6. Complete FK Closure Audit for Mock Deletions                                  |
 |  7. Schema Preflight Fingerprint (handle prod 17 vs dev/staging 27 migrations)   |
 |  8. Deterministic Plan Hash (sha256 digest of normalized action plan)             |
 +-----------------------------------------------------------------------------------+
                                           |
                                           v
 +-----------------------------------------------------------------------------------+
 |                         Transactional Apply Guards                                |
 |  - Mode 0600 Scoped Recovery Export BEFORE any mutation                           |
 |  - Advisory Lock: pg_advisory_xact_lock() + bounded 5s lock timeout               |
 |  - Refuse Stale Plan: require --expected-plan-hash matching computed digest        |
 |  - Atomic Single-Transaction Execution + Instant Rollback on Error                |
 |  - Preflight Opt-in Guards: ZERO live apply without explicit Conductor Review     |
 +-----------------------------------------------------------------------------------+
```

### Invariant Rules
1. **Zero Fabricated Accounts**: No synthetic Clerk users or replacement applications.
2. **Deterministic UUID5 Idempotence**: Existing seed org `org_3JeWZxDcpdvFmff2fW1nXP7tjm6` maps to `018f2f4e-0000-7000-8000-000000000001`; new orgs map deterministically via `uuid5(NAMESPACE_URL, f"https://greensentinel.internal/org/{clerk_org_id}")`. Conflicting or colliding mappings immediately abort.
3. **Safe Role Synchronization**:
   - `org:admin` -> `admin`
   - `org:member` / `member` / `analyst` -> `fraud_analyst` (internal canonical)
   - `org:driver` -> `driver`
   - Unknown roles -> rejected with error.
   - Stale roles (e.g. demotions from admin to driver/analyst) are completely overwritten; no silent admin retention.
4. **No Destruction on Incomplete Data**: If Clerk API pagination fails or returns partial rows, no plan is generated.
5. **Human Record Preservation**: Real principals with no active Clerk memberships are marked `status='inactive'` and have active roles revoked, but their principal row is NEVER deleted (preserves historical audit/case records).
6. **Proven Mock Lineage Only**: Deletion candidate scope is strictly limited to fixture-proven external subjects (`user_clerk_analyst_001`..`010`, `drv_gsm_0001`..`0020`) and seed cases (`018f2f4e-a000-7000-8000-000000000001`..`0100`).
7. **Complete FK Closure**: Audit and delete all dependent child rows across all FK relations in correct dependency order (audit events, review leases, actions, agent sessions, turns, adjudications, workflow questions/minutes/answers, submissions, snapshots, sanctions, solved precedents).
8. **Schema Adaptation**: Dynamically inspect table/column existence to seamlessly handle migration differences between production (17 migrations) and dev/staging (27 migrations).
9. **Zero Shared DB Writes**: All execution tests run against mocked transports or isolated disposable databases with loopback guards.

---

## 3. Targeted RED/GREEN Implementation Steps

### Phase 1: RED - Unit Test Suite (`tests/unit/test_identity_reconciliation.py`)
- `test_role_mapping`: Validates mapping rules and rejection of unknown roles.
- `test_deterministic_org_uuid5`: Validates UUID5 determinism, preservation of existing seed org mapping, and collision detection.
- `test_clerk_pagination_verification`: Asserts error on incomplete pagination or network failure.
- `test_plan_hash_determinism`: Asserts identical plan hash for identical audit state, and hash change on any deviation.
- `test_plan_hash_rejection`: Asserts stale plan hash is rejected during apply preflight.
- `test_mode_600_recovery_export`: Validates that recovery export file is written with strict `0600` permissions.
- `test_orphaned_principal_deactivation`: Validates that real principals without memberships are deactivated and never deleted.
- `test_proven_mock_filter`: Validates strict separation of mock lineage from real user accounts.
- `test_fk_closure_dependency_order`: Validates that mock case and principal dependents are ordered correctly for deletion.
- `test_schema_difference_adaptation`: Validates behavior on schemas with missing migration tables (e.g. prod 17 vs dev 27).
- `test_sanitized_report_no_pii`: Validates that generated audit reports mask emails, org names, and contain no credentials.

### Phase 2: GREEN - Implement `src/services/identity_reconciliation.py`
- Implement models: `ClerkOrg`, `ClerkUser`, `ClerkMembership`, `ClerkSnapshot`, `ReconciliationPlan`, `AuditDiff`.
- Implement `map_clerk_role(clerk_role: str) -> str`.
- Implement `compute_org_uuid(clerk_org_id: str, existing_mappings: dict) -> str`.
- Implement `fetch_clerk_snapshot(...)` with full pagination check and offline file adapter.
- Implement `audit_database_state(conn, schema_name='app') -> DatabaseAuditState`.
- Implement `generate_reconciliation_plan(clerk_snapshot, db_state, env: str) -> ReconciliationPlan`.
- Implement `export_recovery_snapshot(plan, path: str)`.
- Implement `execute_reconciliation_apply(conn, plan, expected_plan_hash: str)`.
- Implement `generate_sanitized_report(plan) -> str`.

### Phase 3: RED - Integration Tests (`tests/integration/test_identity_reconciliation_integration.py`)
- Test disposable PostgreSQL/SQLite schema creation and seed.
- Test dry-run idempotency.
- Test transactional apply and advisory lock.
- Test transactional rollback on injected failure.
- Test negative cross-org isolation post-reconciliation.

### Phase 4: GREEN - Implement CLI `scripts/reconcile_identity.py`
- Build CLI with `--audit`, `--plan`, `--apply`, `--expected-plan-hash`, `--env`, `--database-url`, `--clerk-snapshot-file`.
- Wire default `--dry-run` and guardrails.

### Phase 5: Verification & Deliverables
- Run local unit and integration tests.
- Produce `docs/testing/DB_IDENTITY_RECONCILIATION_394.md` with sanitized audit and ready plan.
- Update `docs/worklog/WORKLOG.md` and `docs/journal/JOURNAL.md`.
- Commit, push, and open PR linking #410, #402, #394.

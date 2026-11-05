# Weekly Engineering Journal — Team P-063
## Classifier research documentation factual review — 2026-10-18

**Objectives:** Correct classifier metrics, criteria-variant caveats, experiment lineage, corpus wording, and review-budget limitations while preserving pinned HF release bytes.

**Completed artifacts:** Updated [classifier model](../CLASSIFICATION_MODEL.md), [research log](../data/AUTORESEARCH.md), dataset cards, and issue-linked worklog for [#558 / PR #560](https://github.com/AI20K-Build-Phase-Cohort-4/P-063/pull/560).

**Roadblocks and solutions:** Verified test execution cleanly: 122 passed in focused doc/readme/link suite (17.55s), 12 passed in benchmark R3D and criteria suite; `git diff --check` clean with zero errors; relative link and anchor verification verified 128 links.

**Learning and next steps:** Saved R3D evaluation sends the 5% review budget to a separate data-quality queue; artifact provenance validation remains required before production integration.

## Research harness measurement integrity — 2026-10-17

**Objectives:** Review PR #527 against issue #525 and prevent provider fallbacks from appearing as successful model measurements.

**Completed artifacts:** Corrected [worker accounting](../../scripts/benchmark/experiments/run_experiment.py), [metric denominator and attribution](../../scripts/benchmark/experiments/metrics.py), and [plot dependency behavior](../../scripts/benchmark/experiments/staircase.py). Added [ADR-029](../architecture/adr-029-harness-live-call-accounting.md) and corrected the [audit report](../data/HARNESS_INTEGRITY_REVIEW.md).

**Roadblocks and solutions:** Soft guardrail metadata wrongly excluded live calls; both paths now exclude only the explicit short-circuit sentinel. Arbitrary caller counts could dilute failures; metrics now derive counts from records. Malformed model fields now fail closed. Removed placeholder SVG/empty PNG fallback so missing matplotlib fails visibly.

**Observed outcomes:** RED: 17 failures and 11 passes. GREEN: 90 focused benchmark, state-builder, and criteria tests passed with no skips. These are local unit/fixture results. The initial research PR check was skipped and supplied no CI validation; PR #526 tracks research CI separately.

**Learning and next steps:** A soft guardrail is not proof of a skipped provider request. Tiny successful provider probes demonstrate access only; the historical E0 fallback run remains invalid as model-quality evidence. Complete independent review and real CI validation, then resolve the external-data-export approval block before bulk evaluation. No provider requests were made during this follow-up.

## Week 7: October 17 — OCI CI artifact storage

### Objectives and completed artifacts

Move CI reports and build handoff off exhausted GitHub artifact storage. All concrete CI/CD jobs now select self-hosted runners with a regression gate. Delivered shared OCI upload/download actions, behavioral regression tests, secretless browser fallback, [ADR-029](../architecture/adr-029-oci-ci-artifact-storage.md) and the [operations runbook](../testing/manual/OCI_ARTIFACTS.md) for [issue #492](https://github.com/AI20K-Build-Phase-Cohort-4/P-063/issues/492).

### Roadblocks and solutions

Initial wrappers flattened duplicate filenames, ignored hidden-file controls and failed optional multiline reports. Tests reproduced seven failures; common-root packaging, explicit hidden selection and no-file policies corrected them. Temporary directories now cover bootstrap failures and transport cleanup. Native implementation fallback followed unavailable dispatch providers. GitHub-hosted smoke could not start because account billing blocked runners; the smoke uses the existing self-hosted Linux fleet. Hosted evidence remains recorded in the PR.

### Key learnings and next steps

A storage migration must preserve consumer layout and secretless CI behavior. OCI does not inherit GitHub retention; lifecycle configuration requires a separate scoped review. Next: review the hosted smoke and ready PR, then consider a repository-prefix lifecycle policy.

## Typed Driver Assistant Chat Blocks & Review Findings Remediation — 2026-10-17

### Objectives
- [x] Address all 6 review findings on PR #486 (Issue #484 driver assistant chat blocks frontend).
- [x] Follow TDD with failing tests first (RED: 15 failed, 17 passed).
- [x] Enforce `trip_card` contract: `trip_id`, `pickup`, `destination`, and optional `fare_vnd`; hide fare row when missing without 'NaN đ'; eliminate `started_at`.
- [x] Route `policy://` hrefs via `onNavigate` and enforce client-side scheme allowlist (`case://`, `trip://`, `policy://`, `https://`) with plain text fallback.
- [x] Add status keys (`under_review`, `draft`, `submitted`, `escalated`, `pending_analyst_review`) and hide pill on empty `status_key`.
- [x] Export `BlockLabels` type (`vi` and `en` defaults) in `src/webapp/components/driver/blocks/labels.ts`; accept `labels`/`t` prop across all blocks for next-intl compatibility.
- [x] Remove trip ID fragments from `trip_card` DOM to prevent prefix collision; display opaque localized label.
- [x] Strongly type `EvidenceItem.kind` as `'weather' | 'traffic' | 'telemetry' | 'policy'`.
- [x] Verify green test run (34 passed) and clean TypeScript typecheck (`tsc --noEmit`).

### Completed Work
- Block labels & localization: [`src/webapp/components/driver/blocks/labels.ts`](../../src/webapp/components/driver/blocks/labels.ts)
- Component implementations: [`src/webapp/components/driver/blocks/`](../../src/webapp/components/driver/blocks/)
- Schema definitions: [`src/webapp/types/driver-blocks.ts`](../../src/webapp/types/driver-blocks.ts)
- Unit test suite: [`src/webapp/tests/unit/components/driver/blocks.test.tsx`](../../src/webapp/tests/unit/components/driver/blocks.test.tsx)

### Roadblocks & Solutions
| Review Finding | Solution | Outcome |
|---|---|---|
| Fare row displayed "NaN đ" when fare was omitted | Made `fare_vnd` optional in `TripCardBlock`, conditional rendering hides fare container completely when omitted | Zero "NaN đ" rendered in DOM |
| Potential trip ID collision from truncated short codes | Removed `#GS-...` short code regex display in `trip_card` DOM; rendered localized opaque label (`Chuyến đi` / `Trip`) | Zero raw ID or prefix collision exposure |
| In-app navigation missing `policy://` support | Added `policy://` to `isInternalScheme` and routed via `onNavigate` | Uniform in-app routing for all internal entity URI schemes |
| Risk of unsafe URI schemes (e.g. `javascript:`, insecure `http://`) | Client-side allowlist strictly allows `case://`, `trip://`, `policy://`, `https://`; others render as plain non-interactive text | Hardened client-side link safety |
| Hardcoded Vietnamese strings in block components | Created `BlockLabels` with `VI_LABELS` and `EN_LABELS` in `labels.ts`, resolved in each block | Clean interface ready for future next-intl integration |

### Observed Outcomes
- Vitest: 34/34 tests passed in `blocks.test.tsx` (1.8s) with 0 errors.
- Full Webapp Vitest: 70/70 test files passed (577 tests).
- TypeScript: `pnpm --prefix src/webapp exec tsc --noEmit` exited cleanly with code 0.

**Objectives and artifacts:** Remediate all ten specification compliance findings on PR #405 and Issue #399 (Parent #394) to deliver verified, safe database performance profiling and workload index optimization. Deliverables: hardened `DatabaseProfiler` service (`src/services/db_profiler.py`), CLI auditor (`scripts/db_profile.py`), bounded migration runner (`scripts/apply_workload_indexes.py`), additive index migration and rollback scripts (`db/migrations/20261015150000_workload_performance_indexes.sql`, `db/rollbacks/20261015150000_workload_performance_indexes.down.sql`), unit test suite with 7 security/boundary checks (`tests/unit/test_db_profiler.py`), disposable integration benchmarking suite (`tests/integration/test_db_performance_bench.py`), multi-environment baseline audit reports (`/tmp/p063-indexes-before-{dev,staging,prod}.json`), machine-readable benchmark artifact ([`docs/testing/artifacts/db_bench_evidence_394.json`](../testing/artifacts/db_bench_evidence_394.json)), and technical report ([`docs/testing/DB_OPTIMIZATION_394.md`](../testing/DB_OPTIMIZATION_394.md)).

**Roadblocks and solutions:** Independent specification review identified critical safety defects in the initial PR:
1. *Arbitrary DML execution risk:* The original profiler permitted arbitrary SQL to execute via `query_key` without matching the allowlist definition and lacked read-only transaction wrappers. Fixed by enforcing strict normalized SQL comparison, rejecting dangerous keywords (`DROP`, `DELETE`, `INSERT`, etc.) and multi-statement queries before connection access, and executing `EXPLAIN ANALYZE` inside an explicit `SET TRANSACTION READ ONLY; ... ROLLBACK;` block.
2. *Credential leakage in DSNs:* Raw database URLs with plaintext passwords leaked into CLI logs, JSON reports, and pytest skip messages. Resolved by implementing regex and `urllib.parse` credential redaction in `sanitize_connection_info` and `redact_dsn_password`, and omitting raw connection strings from public reports in favor of environment identity.
3. *Unprotected integration tests:* Integration tests could inadvertently execute destructive DDL/DML on remote or shared environments. Resolved with `validate_disposable_database_url` enforcing pre-connect verification of loopback hostnames, `test_` database prefixes, and explicit opt-in flags (`CONFIRM_DISPOSABLE_TEST_DB=1`).
4. *Index redundancy and mismatch:* Migration created a duplicate index on `evidence_snapshots(case_id, version DESC)` (already covered by existing `UNIQUE(case_id, version)` backward scan) and 6 speculative unmeasured indexes. We pruned all speculative indexes, retained the critical `trip_assignments(trip_id)` foreign key index, and aligned the case queue index to exact `CaseService.list_cases()` production queries (`organization_id, LOWER(status), priority_tier ASC, priority_score DESC, created_at DESC`).
5. *Hazardous migration runner:* The documentation previously recommended `scripts/migrate_postgres.py`, which drops extensions CASCADE and reseeds mock data. We replaced this with a bounded runner (`scripts/apply_workload_indexes.py`) featuring dry-run preflights, a 5s lock timeout, and a 30s statement timeout, leaving live application exclusively to the conductor.

**Observed outcomes:** Unit tests passed 7/7 validating SQL injection rejection, parameter count enforcement, timeout boundary checks, DSN password redaction, and target validator rules. Integration tests on disposable PostgreSQL 16 confirmed 100% byte-for-byte query result equality before and after index application. Empirical benchmarking across 15 repeated warm runs proved plan transition from `Seq Scan` to `Bitmap Heap Scan` for trip assignment lookups, reducing total query cost by 54.55% (172.75 to 78.51), shared buffer reads by 75.37% (134 to 33 blocks), and median execution time by 45.8% (0.275 ms to 0.149 ms). Multi-environment audits confirmed tenant isolation invariants across dev, staging, and production with zero live database mutations applied.

**Learning and next steps:** PostgreSQL B-tree unique indexes natively support reverse directional scans with zero overhead; duplicate indexes add write amplification without performance gain. Furthermore, empirical benchmarks on realistic cardinality fixtures are essential to separate beneficial indexes from speculative ones. Ready for conductor review and staged live deployment.
## Synthesized Vietnam trip benchmark release and E2E browser test remediation — 2026-10-16

### Objectives
- [x] Merge `origin/main` into PR #415 branch `jev-79b979a274ed41a8` preserving identity reconciliation and Vietnam release metadata.
- [x] Diagnose and fix Playwright strict mode violation in `tests/e2e/browser/cockpit.spec.ts` matching duplicate driver motivation text.
- [x] Eliminate webserver proxy `ECONNREFUSED` log spam by intercepting missing API routes in `tests/e2e/browser/api-fixtures.ts`.
- [x] Verify preset selection, tenant isolation, and deterministic synthetic generation remain fully intact.
- [x] Run full local verification (typecheck, unit, vitest, playwright) and watch CI/CD until 100% green.

### Completed Work
- Browser test disambiguation: [`tests/e2e/browser/cockpit.spec.ts`](../../tests/e2e/browser/cockpit.spec.ts)
- Fixture endpoint handling: [`tests/e2e/browser/api-fixtures.ts`](../../tests/e2e/browser/api-fixtures.ts)
- Journal and worklog entries: [`docs/journal/JOURNAL.md`](JOURNAL.md), [`docs/worklog/WORKLOG.md`](../worklog/WORKLOG.md)

### Roadblocks & Solutions
| Challenge | Applied Solution | Outcome |
|---|---|---|
| Playwright strict mode violation (`getByText(/tài xế có thể kéo dài.../)` matched 2 elements) | Scoped Copilot assertion to `page.getByRole('tabpanel', { name: 'Trợ lý Phân tích – AI Copilot' })` | Semantic locator disambiguates Copilot chat response from Forensic Brief Overview card |
| Webserver `ECONNREFUSED` log spam on background API calls | Added offline fixture fulfillments for `/dispute-dossier`, `/workflow-trace`, `/driver-scorecard`, and `/stream` in `api-fixtures.ts` matching existing `staged-adjudication-fixture.ts` pattern | Zero uncaught background proxy failures; clean console and runner execution |

### Observed Outcomes
- Playwright: 14/14 tests passed in `cockpit.spec.ts` in 3.4m with zero errors.
- Frontend Vitest: 18/18 tests passed across simulation and test console honesty suites.
- Frontend Typecheck: `tsc --noEmit` passed on all webapp and browser test configs with exit code 0.
- Backend Pytest: 30/30 unit tests passed (Vietnam presets, synthetic generator determinism, identity reconciliation).
- Ruff: 0 lint errors, 294 files formatted.
## Test-store schema parity and safe organization ownership migration — 2026-10-16

**Objectives and artifacts:** Finalize test-store database schema parity across Railway dev, staging, and production environments under parent issue #394 / child task #423. Deliverables: additive migration `db/migrations/20261016000000_test_store_schema_parity.sql`, safe non-destructive rollback script `db/rollbacks/20261016000000_test_store_schema_parity.down.sql`, rollback verification CLI `scripts/rollback_schema_parity_394.py`, verification report `docs/testing/DB_SCHEMA_PARITY_394.md`, unit tests `tests/unit/test_db_schema_parity.py`, and real PostgreSQL integration tests `tests/integration/test_db_schema_parity_integration.py`.

**Roadblocks and solutions:** Analysis of raw catalog diffs revealed 252 apparent constraint discrepancies caused by unnormalized session `search_path` rendering in `pg_get_constraintdef()`. Normalizing queries with `SET LOCAL search_path=pg_catalog` isolated the real remaining schema drift: historical in-place file mutation of `db/migrations/20261014090000_tester_org_ownership.sql` (commit `3277f576`) caused dev and staging to record the file as applied with 8 child `organization_id` columns, but lacking `app.test_run_requests`, `app.test_cases`, `messages`, and `created_by` text. Conversely, applying missing migrations to production created the new tables and columns but missed the 8 child `organization_id` columns. Resolved by authoring a self-contained, strictly additive idempotent migration with explicit `app.` schema qualifications and zero `search_path` dependency. Implemented safe ownership backfill propagating `organization_id` strictly from validated parent plans/runs in `app.organizations`, quarantining conflicting parent/child organizations in `app.org_quarantine` without overwriting child data, and preserving legacy unowned rows as NULL. Prohibited destructive `DROP TABLE`/`DROP COLUMN` down-scripts to safeguard pre-existing columns and user data, documenting additive backward-compatibility and verified restore-tested backups.

**Observed outcomes:** Validated on isolated disposable clones (`test_p063_schema_parity_dev`, `test_p063_schema_parity_staging`, `test_p063_schema_parity_prod`) in container `p063-postgres`. Achieved 100% exact catalog parity across all three environments: 71 total tables (70 `app`, 1 `public.schema_migrations`), 671 total columns (669 `app`, 2 `public`), 359 constraints, and 170 indexes. Proved zero data loss and identical row counts/data hashes across all 63 original tables. Proved zero schema drift upon re-running migration. All 10 unit tests and 5 real PostgreSQL integration tests passed cleanly.

**Learning and next steps:** Historical migration edits in git without version bumps inevitably cause multi-environment ledger divergence. Database finalization requires catalog-level normalization and additive repair migrations rather than ledger rewrites. Ready for conductor review under issue #397.

## Deterministic real driver profile binding, multi-org scoped JIT grants & schema-portable PostGIS — 2026-10-16

**Objectives and artifacts:** Deliver reviewed remediation for identity slice 1/2 under #402 / #394 tracked in [Issue #409](https://github.com/AI20K-Build-Phase-Cohort-4/P-063/issues/409) and [PR #414](https://github.com/AI20K-Build-Phase-Cohort-4/P-063/pull/414). Eliminate privilege escalation when an existing DB driver lacking a profile signs in with a stale JWT claiming `admin` or `member`. Scope new JIT grants strictly to verified active organization roles (`org_role` / `o.rol`), preserving existing DB grants, status, and organization as authoritative. Support verified multi-org membership under canonical key `(organization_id, external_subject)`. Resolve PostGIS hosting layout portability (`public` vs `extensions`) without system-catalog mutation, forced relocation, or `DROP EXTENSION CASCADE`. Make real driver DB integration tests hermetic in CI. Key delivered artifacts: [`src/services/access_control.py`](file:///src/services/access_control.py), [`src/api/auth.py`](file:///src/api/auth.py), [`tests/unit/services/test_real_driver_binding.py`](file:///tests/unit/services/test_real_driver_binding.py), [`tests/integration/api/test_org_auth_regressions.py`](file:///tests/integration/api/test_org_auth_regressions.py), [`tests/integration/services/test_real_driver_db_integration.py`](file:///tests/integration/services/test_real_driver_db_integration.py), [`tests/integration/scripts/test_postgis_preview_migration_integration.py`](file:///tests/integration/scripts/test_postgis_preview_migration_integration.py), [`scripts/migrate_postgres.py`](file:///scripts/migrate_postgres.py).

**Roadblocks and solutions:**
1. *Privilege escalation on driver profile repair:* In the prior implementation, an existing driver lacking a profile (`row["driver_id"] is None`) was routed into `sync_clerk_principal`, which accepted JWT roles (`admin`/`member`) and upserted them into `app.principal_roles`. An attacker or stale token could thus gain `admin` or `fraud_analyst` privileges during driver profile creation. Resolved by extracting `_ensure_driver_profile_tx` and exposing `ensure_driver_profile` that writes solely to `app.drivers` without touching `app.principals` or `app.principal_roles`. In `src/api/auth.py`, when an existing driver is detected without a profile, `ensure_driver_profile` is invoked directly followed by `load_principal`, completely bypassing `sync_clerk_principal`.
2. *Unscoped JIT grants and multi-org tenancy:* JWT claims previously allowed top-level role claims or `public_metadata` from other organizations to influence tenant roles. Resolved by deriving JIT roles exclusively from the verified active organization claims (`org_role` or compact `o.rol`), normalized to `admin`, `fraud_analyst`, and `driver`. Supported positive multi-org membership: a user can hold distinct principal records in multiple organizations under `(organization_id, external_subject)` with independent roles and profile bindings without role or permission bleeding. Removed buggy `existing_any_org` rejection. Unknown roles fail closed with HTTP 403.
3. *PostGIS schema portability without system-catalog manipulation:* The previous draft attempted `UPDATE pg_extension SET extrelocatable=true` and `ALTER EXTENSION postgis SET SCHEMA extensions`. PostGIS is non-relocatable in PostgreSQL 16 (`extrelocatable=false`), and direct catalog mutation corrupts system bindings. Solved cleanly by adopting schema-portable SQL: unqualified PostGIS geography/geometry/functions in migrations and application queries resolve against session `search_path`. `ensure_extensions_postgis` detects whether PostGIS resides in `public` or `extensions`, sets session `search_path` accordingly, never commits inside the helper, and fails closed on unapproved schemas or remote missing extensions without dropping extensions.
4. *Hermetic CI integration evidence:* Refactored `test_real_driver_db_integration.py` to eliminate hardcoded developer template DB requirements. In CI, it provisions a fresh disposable database using repository migrations and loopback safety guards, proving real foreign keys, triggers (`driver_principal_org_match`), and multi-org provisioning execute cleanly without shared state.

**Observed outcomes:**
- 58 focused unit and real integration tests pass in 6.2s:
  - `tests/unit/services/test_real_driver_binding.py` (14 passed)
  - `tests/integration/api/test_org_auth_regressions.py` (25 passed, including multi-org verified provisioning and disabled second-org rejection)
  - `tests/integration/services/test_real_driver_db_integration.py` (8 passed against disposable PostgreSQL clone/migrations)
  - `tests/integration/scripts/test_postgis_preview_migration_integration.py` (2 passed testing both `public` and `extensions` PostGIS layouts with spatial data preservation)
  - `tests/unit/scripts/test_migration_seed_safety.py` (9 passed verifying zero catalog update, zero DROP EXTENSION, zero CASCADE, zero helper commit)
- Zero mutation of shared production or staging databases.
- Full formatting (`ruff format --check`) and linting (`ruff check`) clean.

## Database identity reconciliation, organization role sync, and scoped mock cleanup — 2026-10-16

### Objectives
- [x] Deliver bounded sync slice for database identity finalization (#394 / #402 / #410).
- [x] Remediate SQLSTATE 23514 CHECK constraint violation on principal deactivation.
- [x] Transactionally maintain append-only triggers (`app.reject_mutation()`, SQLSTATE 55000) with restoration proof.
- [x] Enforce catalog-derived 24-table child-first topological FK closure and eliminate hardcoded live Clerk org IDs.
- [x] Implement fail-closed isolation preventing deletion of real cases/audits referenced by mock actors (`MockPrincipalReferenceError`).
- [x] Guard apply with advisory lock, pre-lock timeout, canonical schema fingerprinting, and mode 0600 row data recovery dumps.
- [x] Replace mock cursor tests with real PostgreSQL integration tests against disposable PostGIS clones.

### Completed Work
- Service implementation: [`src/services/identity_reconciliation.py`](../../src/services/identity_reconciliation.py)
- CLI tool: [`scripts/reconcile_identity.py`](../../scripts/reconcile_identity.py)
- Unit test suite: [`tests/unit/test_identity_reconciliation.py`](../../tests/unit/test_identity_reconciliation.py)
- CLI test suite: [`tests/unit/test_reconcile_identity_cli.py`](../../tests/unit/test_reconcile_identity_cli.py)
- Real PostgreSQL integration suite: [`tests/integration/test_identity_reconciliation_integration.py`](../../tests/integration/test_identity_reconciliation_integration.py)
- Testing and audit report: [`docs/testing/DB_IDENTITY_RECONCILIATION_394.md`](../testing/DB_IDENTITY_RECONCILIATION_394.md)

### Roadblocks & Solutions
| Challenge | Applied Solution | Outcome |
|---|---|---|
| Root SQLSTATE 23514 on dev clone (`principals_status_check` violated by `status='inactive'`) | Updated principal deactivation status from `'inactive'` to `'disabled'` matching schema CHECK constraint (`status IN ('active', 'disabled')`) | Zero constraint violations; orphaned principals deactivated safely preserving historical FKs |
| Append-only triggers (`app.reject_mutation()`, SQLSTATE 55000) blocking fixture cleanup on 10 tables | Inspected `pg_trigger` catalog under bounded transactional lock, selectively disabled ONLY known mutation guards, and restored exact original state before commit and on rollback | Fixture cases deleted safely; unrelated append-only records proved protected by re-enabled triggers |
| Incomplete FK hierarchy and hardcoded live Clerk ID (`KNOWN_SEED_ORG_MAPPING`) | Derived 24-table child-first topological closure from `pg_constraint`; dynamically discovered seed org mappings from `app.organizations.clerk_organization_id`; added UUID5 collision detection | Zero missing descendants (`model_assessments`, `sanctions`, `precedent_workflows`, `case_agent_messages` cleaned); zero hardcoded live Clerk IDs |
| Risk of deleting real cases or audits referenced by mock actors | Implemented `_verify_mock_principals_isolation()` raising `MockPrincipalReferenceError` when mock actors are referenced outside approved fixture cases; unlinked nullable driver/run principal references | Real cases (`6ed41b7e-8bab-...` and `22c3b317-c414-...`) preserved; fail-closed protection verified by test |
| Stale-plan drift and race conditions | Set `SET LOCAL lock_timeout = '5s'` before acquiring `pg_advisory_xact_lock`; re-read database state and re-validated canonical schema fingerprint (columns, types, CHECK, FKs, triggers) under lock | Concurrency and drift fail-closed before any database write occurs |
| Fake cursors masquerading as integration evidence | Replaced fake cursors with real PostgreSQL integration tests against disposable clones in `p063-postgres`, guarded by loopback, disposable prefix, and opt-in requirement | 9 real integration tests pass in 14.3s; pristine clone counts (1/43/102/102) preserved |

### Key Learnings
1. Database integration tests must exercise real backing-store constraints and triggers; fake mock cursors cannot catch database CHECK constraints or trigger execution failures.
2. PostgreSQL append-only triggers require explicit transactional maintenance blocks (`ALTER TABLE ... DISABLE TRIGGER`) with rollback guarantees and explicit restoration verification.
3. Foreign key deletion closures must be derived from live `pg_constraint` catalog metadata rather than manual hardcoded approximations to prevent foreign key constraint violations.

### Next Steps Plan
- [x] Push remediated branch `jev-587cd00e04964446` to origin.
- [x] Update PR #412 body and Issue #410 with truthful test evidence.
- [ ] Monitor GitHub Actions CI checks on PR #412.
- [ ] Coordinate with Conductor for reviewed live apply on Railway environments.

## Copilot chat ownership gating and safe runtime diagnostics — 2026-10-15

**Objectives and artifacts:** Resolve Issue #380 blocking fraud analysts with HTTP 403 Forbidden errors when submitting queries in the AI Copilot chat drawer. Deliverables: [ADR-028](../architecture/adr-028-copilot-ownership-gating-and-runtime-diagnostics.md), frontend ownership gating in `src/webapp/components/views/cockpit-view.tsx`, backend safe diagnostics and relational join unblocking in `src/services/agent_runtime.py` and `src/services/case_context.py`, focused RED/GREEN test suites (`src/webapp/tests/copilot-ownership-gating.test.tsx` and `tests/unit/services/test_copilot_ownership_diagnostics.py`).

**Roadblocks and solutions:** Analysis of the client and server traces revealed multiple contributing defects: (1) Client-side Cockpit permitted chat input submissions when cases were unclaimed or claimed by another analyst, triggering immediate backend HTTP 403 rejection. Resolved by strictly binding chat input, send action, attachment button, and single-turn reset checkbox to `isLockedByMe` (`activeLockHolder === currentAnalyst.id && !isLeaseExpired`), while updating placeholder text dynamically to guide analysts. (2) `case_context.py` performed an inner join on `app.drivers`, causing cases without linked drivers or assignments to vanish and fail with 403/404. Resolved by switching to `LEFT JOIN` and casting UUID parameters explicitly. (3) `stream_agent_turn` previously swallowed all exceptions with a hardcoded `"PROVIDER_UNAVAILABLE"` error; added `_diagnose_failure` classifying exceptions into `FORBIDDEN`, `NOT_FOUND`, `PROVIDER_TIMEOUT`, `PERSISTENCE_UNAVAILABLE`, and `PROVIDER_UNAVAILABLE` while logging full stack traces via `logger.exception` without leaking bearer tokens or credentials.

**Observed outcomes:** Frontend Vitest unit suite passed 53 files and 477 tests (including 5 new ownership gating tests and updated mock lease fixtures). Backend Pytest suite passed 1277 tests across the repository. Type checking (`tsc --noEmit`) and Ruff lint/formatting passed cleanly.

**Learning and next steps:** Client-side affordances must always reflect distributed ownership locks at runtime before invoking stateful streaming endpoints. Opening draft PR, verifying CI/CD pipeline, and transitioning to ready for review.

## Organization-owned test console and visual review — 2026-10-14

**Objectives and artifacts:** Repair publicly reachable `/test` and inconsistent organization ownership while preparing a faithful refresh of the existing manual console. [Draft PR #345](https://github.com/AI20K-Build-Phase-Cohort-4/P-063/pull/345) contains the security prerequisite, tenant-owned simulation storage and scoped canonical telemetry processing. [Architecture](../architecture/TESTER_SIMULATION_ARCHITECTURE.md) and [manual verification](../testing/manual/TEST_CONSOLE_AUTH.md) separate delivered branch behavior from pending console work.

**Roadblocks and solutions:** Initial dispatches stalled before edits; later implementation agents hit usage limits. Recovery used preserved worktrees and explicit handoffs. A partial role-only fix was not accepted because unscoped persisted runs would still leak across organizations. Tests now cover ownership through the plan anchor, durable request keys, isolated sandbox cases, validated operational actors and honest failure propagation. The first redesign changed the composition too much, so the review preview is being rebuilt around the original three columns.

**Observed outcomes:** The frontend suite passed 348 tests and test TypeScript validation passed. The final integrated backend regression passed 100 tests with disposable PostgreSQL API variants enabled. Three separate worker database tests verify nominal tenant persistence, foreign actor denial and transaction rollback; unit/provider fixtures remain distinct. Ruff passed. Python typing matches its 16-error baseline and is not green. Hosted authentication, real model quality and Driver delivery have not been accepted.

**Learning and next steps:** An authenticated page alone does not establish tenant-safe trip completion. The console must preserve three distinct stop snapshots and adapt its actor references before submission can be usable end to end. Obtain approval for the current-layout preview, then implement dragging, Run/Pause/Resume, reasoned cancellation, the processing dock, named history and source-backed presets through real APIs and behavioral TDD. Existing epic blockers remain governed by their full DoD.

## Approved test console redesign — 2026-10-14

**Objectives and artifacts:** After the stakeholder approved the revised current-layout preview, implement the requested console behavior through real APIs. [PR #345](https://github.com/AI20K-Build-Phase-Cohort-4/P-063/pull/345) adds participant cancellation with a required reason, org-scoped run history, an editable title, a recorded-evidence overview and a published preset library, and replaces the authoring controls with a simulation-first layout. [Design](../design/test-console-refresh/design.md) and [architecture](../architecture/TESTER_SIMULATION_ARCHITECTURE.md) record the decisions; [manual verification](../testing/manual/TEST_CONSOLE_AUTH.md) covers the auth boundary.

**Roadblocks and solutions:** The delegated UI agent could not resolve its configured model, so the console was rewritten directly under the existing map, conversation and token wiring. Dragging needed an opt-in capability on the shared map component; it was added as a disabled-by-default prop so production views are unaffected. Cancellation had to reach the classifiers, so submission now carries `lifecycle_state` plus actor/reason instead of a hardcoded completion.

**Observed outcomes:** Backend console-contract tests and a publish-evidence test pass (13 + 2), proving tenancy, canonical cancellation evidence and that a cancelled run is never published as completed. The full frontend suite passed 357 tests across 46 files and TypeScript validation passed; lint reported zero errors. The three stop snapshots are distinct.

**Learning and next steps:** A truthful console reports recorded evidence and never fabricates model or Driver success; the wrong-direction preset stays unavailable until movement away from the pickup is verified. Remaining acceptance is external: hosted Clerk, real model-provider quality and Driver delivery. Keep PR #345 draft until those and cross-file review complete.

## Deterministic case-map snapshots and case-scoped Geoapify tools — 2026-10-13

**Objectives and artifacts:** Implement Issue #229 deterministic case-map snapshot artifacts and Issue #230 case-scoped Geoapify agent tools for the analyst/driver agents. Delivered `get_case_map_snapshot` (evidence-revision-bound Static Maps artifact), hardened `compare_trip_routes`, and new `geocode_address`, `reverse_geocode_coordinates`, `match_trip_telemetry` read-only tools. Artifacts: [ISSUE_229_VERIFICATION.md](../testing/ISSUE_229_VERIFICATION.md), [ISSUE_230_VERIFICATION.md](../testing/ISSUE_230_VERIFICATION.md), `src/services/map_snapshot.py`, `src/services/geoapify_adapter.py`, `src/services/tool_execution.py`, `src/services/tool_catalog.py`, `scripts/gen_geo_evidence.py`, and the attributed [worklog](../worklog/2026-10-13.md).

**Roadblocks and outcomes:** Snapshots are built deterministically from frozen `evidence_snapshots` revisions — the same revision always produces the same artifact key, and a new revision creates a new artifact without mutating sent minutes. Static Maps supports GET under a 2048-char URL limit; complex geometries are POSTed (polyline6) to avoid blank images. Provider failures map to a closed, honest `unavailable` union (quota_exceeded/provider_timeout/provider_unavailable/no_geometry) with retry guidance, never a blank image presented as evidence. Geoapify returns `results` rather than `features` for JSON geocoding, so the adapter normalizes both. Role/scope enforcement is exercised with a live harvest harness over the PostGIS seed (analyst assigned-owner and senior analyst succeed; driver with no mapped principal is denied). LangChain bind-tools wrappers stay fail-closed (403 without trusted context) since graph routing resolves authority inside `execute_tool`. A reviewer subagent pass caught a geocode scope-bypass and missing POST/no-geometry guards, which were closed.

**Observed outcomes:** 33 geo unit/integration tests pass (determinism, revision mismatch rejection, honest unavailable, normalized candidates with confidence/distance, union closes). `pytest tests/integration/agents/ -k "geoapify or route or geocode"` = 6 passed, 2 skipped. Canonical boundary + registry + driver/runtime suites: 150 passed. Ruff check and format clean. Live role runs produced real Static Maps JPEGs (800×600) with `deterministic_key`, `cost_credits: 1` and retained attribution (samples in `docs/testing/artifacts/geo_evidence/`).

**Learnings and next steps:** Local unit-suite failures observed during verification are pre-existing environment issues (cloud `QDRANT_CLUSTER_URL` 403 and real-model LLM contract checks) and reproduce at base revision with the same commands. Next steps tracked in the geo-maps epic #233: probe-fleet traffic corroboration (#231) and test-console Geoapify assist (#232) remain open.

**Objectives and artifacts:** Fix simulation case publishing to Redis production stream with snapshot fallback, auto-select newly published cases in `/workplace` via URL parameter, accurately trigger driver-passenger chat milestones using real Haversine distance to pickup and dropoff coordinates, and implement fast-complete route execution for instant simulation progression. Documented in the [attributed worklog](../worklog/2026-10-12.md).

**Roadblocks and outcomes:** The 404 publish error occurred when the backend in-memory simulation runner did not hold the run instance (e.g. multi-process or server restart); resolved by accepting a fallback payload snapshot with telemetry coordinates, addresses, and messages directly in `POST /test/api/v1/runs/{run_id}/publish-production`. In `/workplace`, newly published cases were not auto-selected because the query parameter was ignored; resolved by reading `caseId` from URL search params and pre-selecting the matching case upon load. Chat dialogue previously triggered at hardcoded percentages (`45%`), misrepresenting pickup arrival when custom waypoints elongated the initial route leg; resolved by replacing percentage checks with real-time Haversine distance checks (`<= 65m` to pickup point). Added `"FAST_COMPLETE"` control command to SimulationRunner and a prominent "Hoàn tất nhanh lộ trình" button in the Cockpit toolbar and sidebar.

**Learnings and next steps:** Physical distance calculations maintain realistic dialogue coherence across arbitrary polyline modifications. Backend unit tests passed 7/7 in `test_simulation_v2_routes.py` and 833/833 in `tests/unit`. Frontend vitest suite passed 285/285 across 38 files.

## Driver motivation preview preparation — 2026-10-10

**Objectives and artifacts:** Implement issue #190 economic rewards and advisory
intent analysis in the forensic tool and Overview. The [manual runbook](../testing/manual/DRIVER_MOTIVATION.md)
and [attributed worklog](../worklog/2026-10-10.md) record implementation and evidence.

**Roadblocks and outcomes:** Local backend timeouts and missing tooling delayed UI
verification. Restarting with explicit isolated fixture settings allowed the user
to observe matching 15,000 VND reward and insufficient-intent text in the card and
Copilot. Motivation tests passed 33/33, component tests 3/3, TypeScript and scoped
Ruff passed. The Bash aggregate checker failed to start with E_ACCESSDENIED.

**Learnings and next steps:** Economic gain alone does not establish intent.
Fixture screenshots do not prove hosted authentication or live-model quality.
Publish a branch-only PR and verify its Preview deployment; case-switching,
hosted acceptance and the existing violation card's stronger intent claim need
review. The user has not authorized merging or pushing to main.

## Week 5: Road Network Routing & On-Demand Test Case Persistence — 2026-10-07

**Objective and artifacts:** Resolve straight-line simulation trajectories between origin, pickup, and destination by reusing production OSRM routing algorithms, and provide an on-demand "Save Simulation Case" workflow persisting simulated runs to the sandbox workplace queue (`/test/workplace`) without auto-creating unwanted cases ([Issue #204](https://github.com/AI20K-Build-Phase-Cohort-4/P-063/issues/204)). Delivered `resolve_trip_route()` in `src/services/routing_service.py`, `POST /test/api/v1/routes/resolve` and auto-expansion in `src/api/test_routes.py`, `POST /test/api/v1/runs/{run_id}/save-case`, updated `TestSimulationRepository.list_cases` in `src/services/test_simulation_repository.py`, webapp integration in `src/webapp/lib/testApiClient.ts` and `src/webapp/app/test/page.tsx`, and expanded integration tests in `tests/integration/api/test_simulation_api.py`.

**Roadblocks and solutions:** In `/test`, the visual simulation previously rendered direct straight lines connecting the 3 user-selected waypoints (origin, pickup, destination) because geodesic interpolation was performed on the raw points without snapping to the road network. To solve this, we unified test simulation routing with production logic by reusing `fetch_osrm_route` from `src/services/routing_service.py`, creating `resolve_trip_route()` to calculate road-snapped geometries for both legs (origin -> pickup and pickup -> destination) and gracefully falling back to geodesic interpolation when offline or when OSRM is unreachable. In the UI, `MapLibreView` renders separate visual layers for the pickup and destination legs and passes the high-resolution polyline to `/definitions`, ensuring vehicle animation faithfully traces actual city streets. Furthermore, `/test/workplace` previously appeared empty after simulations because automatic case creation during telemetry generation had been disabled to avoid polluting test environments. To provide explicit tester control, we implemented an on-demand "Save Simulation Case" button in `/test` that calls `POST /test/api/v1/runs/{run_id}/save-case`, generating a case with risk score and detected fault types, and updated `TestSimulationRepository.list_cases` to reliably bridge database rows with in-memory test cases.

**Observed outcomes:** 16/16 simulation integration tests pass (`tests/integration/api/test_simulation_api.py` and `tests/integration/services/test_simulation_engine.py`). TypeScript compiler checks (`tsc --noEmit`) complete with 0 errors. Python linting and code formatting (`ruff check` and `ruff format`) are 100% clean.

**Learning and next steps:** Reusing production routing services for testing ensures parity between simulation and operational environments, while explicit on-demand case persistence gives testers full control over which scenarios are triaged in the sandbox workplace.

## Week 4 addendum: Real-account browser E2E per role and environment — 2026-10-08

**Objective and artifacts:** Replace fixture-mocked hosted browser coverage with real Clerk UI logins for analyst, driver, and admin across preview/dev/staging/prod ([Issue #218](https://github.com/AI20K-Build-Phase-Cohort-4/P-063/issues/218), [task #219](https://github.com/AI20K-Build-Phase-Cohort-4/P-063/issues/219)). Delivered the role helper and specs (`tests/e2e/browser/auth/role-accounts.ts`, `role-accounts.spec.ts`), per-env URL map with preview overrides, the [runbook](../testing/REAL_ACCOUNT_E2E.md), and six `E2E_*` GitHub secrets with ignored local `.env` wiring.

**Roadblocks and solutions:** The auth Playwright config ignored `E2E_TARGET_ENV` and always used the prod URL; fixed with a per-env resolver matching the helper. `test_openai_model_alias_precedence` failed in full-suite runs because `src/rag` imports call `load_dotenv()`, leaking `.env` values into `os.environ`; hardened the test with `monkeypatch` isolation instead of raw `os.environ` writes. Frontend `api-client` failures traced to `NEXT_PUBLIC_API_BASE_URL` exported in the operator shell, not a code regression; clean-env runs pass.

**Observed outcomes:** Backend units 621 passed, frontend 246 passed across 34 files, `tsc` and Ruff clean. Hosted per-env browser runs and password rotation remain pending.

**Learning and next steps:** Real-click suites must resolve URLs from one shared per-env map, and tests must never assume a clean ambient environment. Next: execute hosted runs per environment and rotate the weak shared passwords.

---

## Geoapify capability assessment — 2026-10-08

### Objectives

- [x] Check Geoapify capabilities against the P-063 requirements and existing Tester-console direction.
- [x] Record a sanitized live-probe evidence baseline and architecture/tool-boundary proposal.
- [ ] Implement provider integration or change the production map/timeline UI; these remain pending clarification, contract review, and visual approval.

### Completed Work

- Authored the [Geoapify integration assessment](../architecture/GEOAPIFY_INTEGRATION.md), [manual verification runbook](../testing/manual/GEOAPIFY.md), and [sanitized capability artifact](../testing/artifacts/geoapify/capabilities-2026-10-08.json).
- Linked the assessment to [Issue #223](https://github.com/AI20K-Build-Phase-Cohort-4/P-063/issues/223) and preserved existing Tester issue coordination rather than creating a duplicate console specification.

### Roadblocks & Solutions

| Challenge | Applied Solution | Outcome |
|---|---|---|
| A provider probe can demonstrate capability without proving coverage, traffic truth, licence entitlement, or hosted behavior. | Classified the six HTTP 200 probes as live provider capability evidence and documented each unsupported conclusion explicitly. | Reviewable evidence baseline with no fabricated acceptance claim. |
| Geoapify routing uses `MultiLineString`, while the current routing contract is provider-neutral. | Proposed typed normalization that preserves leg discontinuities and provenance, with no straight-line fallback. | Integration boundary is defined; implementation remains pending. |
| MCP discovery exposes 11 tools, but P-063 limits model-selectable capabilities. | Kept vendor MCP tools behind the existing shared-service and explicit registry boundary. | Agent-tool application remains scoped and auditable. |

### Key Learnings

1. A timeline can complement ordered evidence while map geometry remains necessary for spatial proof.
2. Provider capability evidence must stay separate from local, hosted, and UAT acceptance evidence.
3. The existing Tester contracts and shared API/agent-tool ADR are the coordination boundaries for future work.

### Next Week Plan

- [ ] Resolve key handling, browser proxy/restricted-key, attribution, quota, and traffic semantics with the owner.
- [ ] Review the proposed provider contract and dependency relationship with existing Tester issues before implementation.
- [ ] Obtain visual approval for any map/timeline presentation before application coding.

## Week 4: Real Driver Tools & Seeded Scenario Workflow — 2026-10-05

**Objective and artifacts:** Provide real Driver tools, an idempotent & reversible ScenarioSeeder (`scripts/seed_driver_scenarios.py` / `src/services/scenario_seeder.py`), and an automated scenario workflow runner (`scripts/run_driver_scenario.py` / `src/services/driver_scenario_runner.py`) proving the complete lifecycle: detection -> driver intake -> tool execution -> persisted event -> pending/escalation state across the 3 canonical scenarios ([Issue #158](https://github.com/AI20K-Build-Phase-Cohort-4/P-063/issues/158)). Delivered [`ISSUE_158_VERIFICATION.md`](../testing/ISSUE_158_VERIFICATION.md), updated `src/agents/tools/driver_tools.py` with cross-driver authorization and structured error responses, updated `src/agents/tools/analyst_tools.py` with truthful ticket preview semantics (`write_ticket_for_driver` reports `durable_persisted=False` without false durable claims), created `scripts/smoke_driver_scenarios.py` API smoke test suite, and authored unit test suites `tests/test_services/test_driver_tools_authorization.py` and `tests/test_services/test_driver_scenario_workflow.py`.

**Roadblocks and solutions:** Driver dispute workflows require reproducible, deterministic scenarios across both PostgreSQL and in-memory test environments without cross-tenant collisions or state pollution. We designed `ScenarioSeeder` with deterministic UUIDs (`018f2f4e-b000-...`), distinct from production case ranges, and established clean `--dry-run` and `--reset` mechanics. Furthermore, tools must expose unavailable data truthfully: for technical dropout cases with zero telemetry points, `inspect_trip_telemetry` and `corroborate_traffic_conditions` return explicit unavailable states (`status: "unavailable"`, `error_type: "UNAVAILABLE"`), preventing unknown traffic from defaulting to clear flow and eliminating fabricated GPS points. For the legacy `write_ticket_for_driver` tool, we retained `status="ISSUED"` for UI widget preview compatibility while truthfully reporting `execution_type="PREVIEW_ONLY"`, `durable_persisted=False`, and `requires_human_approval=True` until an approved human action contract and durable audit proof are attached.

**Observed outcomes:** All 7 tests in `test_driver_tools_authorization.py` pass verifying owned data access, 403 foreign driver rejection, 404 missing case handling, malformed input safety, idempotent chat retries, and honest preview semantics. All 9 tests in `test_driver_scenario_workflow.py` pass verifying seeder reversibility, all 3 scenario workflows, appeal branching, 48h silence timeout auto-escalation, and boundary confidence rules. Full repository pytest suite (1020 passed, 0 failed) is 100% green. Ruff and Mypy report zero errors across all source files.

**Learning and next steps:** End-to-end scripted scenario workflows anchor verifiable driver rights while ensuring no automatic sanctions are applied without durable human review. This successfully delivers Issue #158 and unlocks subsequent driver capabilities: Issue #159 (Driver Voice/Audio Input) and Issue #160 (Driver Precedent & Autonomous Exoneration Dossier).

---

## Week 4: Driver Agent Contracts & Autonomous Exoneration State Machine — 2026-10-05

**Objective and artifacts:** Implement and verify the full Driver Agent Contracts and Autonomous Exoneration state machine across Driver Dispute Service, Driver Support Agent (LangGraph), Driver Tools, and Kinematic Maneuver Parsing in accordance with confirmed stakeholder rules ([Issue #157](https://github.com/AI20K-Build-Phase-Cohort-4/P-063/issues/157)). Delivered [`ISSUE_157_VERIFICATION.md`](../testing/ISSUE_157_VERIFICATION.md), updated `src/services/driver_dispute_service.py` with `_confidence_overrides`, `_get_case_driver_id`, `_get_case_confidence`, cross-driver authorization checks, and the full confidence boundary state machine, updated `src/agents/driver_agent.py` (resolving LangGraph `RunnableConfig` typing warning and adding cross-driver access denial), updated `src/agents/tools/driver_tools.py` with structured `error_type="FORBIDDEN"` on `HTTPException`, enhanced `src/services/route_analytics.py` kinematic maneuver parsing edge cases in `tests/test_services/test_kinematic_maneuvers.py` (left turns, malformed input, unavailable telemetry, zero fabricated GPS points), and authored the dedicated 20-test contract suite `tests/test_services/test_driver_agent_contracts.py`.

**Roadblocks and solutions:** Driver dispute resolution requires strict adherence to confirmed stakeholder rules (2026-10-05) to protect drivers from premature or unauthorized automated penalties while maintaining deterministic fraud detection. A key challenge was enforcing the confidence boundary: exactly $c = 0.5$, missing confidence ($c = None$), out-of-range ($c < 0$ or $c > 1$), or tool failures must strictly escalate to an Analyst (`status="driver_disputed"`, `dispute_status="in_dispute"`) and never auto-close. For $c > 0.5$, the system asks whether the driver still wants to appeal (establishing a 48h silence deadline), while for $c < 0.5$, the system does not escalate but still asks the driver to confirm resolution before closing. Crucially, score alone never closes or sanctions; only explicit driver confirmation ("Không khiếu nại thêm" / "confirm_resolution") closes the case as `driver_confirmed_resolution` without sanction. Furthermore, cross-driver access denial was strictly locked down across HTTP endpoints, direct tool executions, and agent dispatch.

**Observed outcomes:** All 20 tests in `tests/test_services/test_driver_agent_contracts.py` pass cleanly. All 14 tests in `tests/test_services/test_driver_dispute_service.py` pass with zero warnings. All 11 tests in `tests/test_services/test_kinematic_maneuvers.py` pass verifying turn-by-turn clustering, malformed input handling, and 100% telemetry coordinate provenance (zero fabricated GPS points). Full pytest suite passed with zero regressions. Ruff and Mypy report zero errors across all source and test files.

**Learning and next steps:** Strict separation between classifier confidence evaluation, driver confirmation turn, and analyst escalation ensures transparent driver rights under Điều 12.2 and Điều 12.3 while eliminating arbitrary automated sanctions. This delivers Issue #157 and unblocks Issue #158 (Driver Dispute Timeline & Telemetry Review).

---

## Week 4: System Operations Analytics Dashboard & Uncapped Aggregations — 2026-10-05

**Objective and artifacts:** Deliver authoritative, organization-wide Operations Analytics Dashboard in the Adjudication Cockpit (`/workplace?tab=analytics`) eliminating the legacy 100-case client-side fetch cap ([Issue #152](https://github.com/AI20K-Build-Phase-Cohort-4/P-063/issues/152)). Delivered [`ISSUE_152_VERIFICATION.md`](../testing/ISSUE_152_VERIFICATION.md), updated `src/models/schemas.py` with `AnalyticsQueueMetrics`, `AnalyticsDispositionMetrics`, `AnalyticsPerformanceMetrics`, `AnalyticsSystemHealth`, and `AnalyticsMetricsResponse`, updated `src/services/case_service.py` with `get_analytics_metrics` (high-performance SQL aggregations across cases, review leases, and adjudications with zero-network in-memory fallback), updated `src/api/routes.py` with `GET /api/v1/analytics/metrics` endpoint (RBAC and tenant isolation enforced), updated `src/webapp/types/schemas.ts` and `src/webapp/lib/api-client.ts`, implemented `AnalyticsDashboardView` in `src/webapp/components/views/analytics-view.tsx` with 4-card KPI row (Active Backlog, Driver Confirmation, Adjudications in Window, MTTR), Queue Capacity with active review leases, Adjudication Outcomes (Driver Exonerations vs Analyst Verdicts), Category Distribution (`ERR-01` to `ERR-05`), time window filters (7d, 30d, 90d), and preserved Agent Observability & Benchmark section, backend Pytest suite `tests/test_api/test_analytics.py`, and Vitest suite `src/webapp/tests/analytics.test.tsx`.

**Roadblocks and solutions:** The legacy analytics dashboard called `fetchCases({ availability: "available", limit: 100 })`, which artificially capped visibility at 100 cases, excluded cases currently locked by other analysts, and omitted historical adjudications and driver autonomous exonerations. Furthermore, calculating operational metrics on the frontend transferred unnecessary network payloads and bypassed tenant boundary isolation. We engineered `GET /api/v1/analytics/metrics` to compute SQL aggregates directly on PostgreSQL across all organization cases, active review leases (`app.review_leases`), and adjudications (`app.adjudications`). On the frontend, we built an Emerald Sentinel v2.0 compliant layout with a 4-card KPI row, live P0/P1/P2 pills, driver autonomous resolution metrics, queue capacity indicators, and suspected category progress bars. Where metrics are unmeasured or uncalibrated, values explicitly return `null` and render `"—"` / `"uncalibrated"`.

**Observed outcomes:** All 5 backend Pytest tests pass covering uncapped datasets (120+ cases), tenant isolation, time window filtering, RBAC authorization, and unmeasured metric handling. All 4 frontend Vitest tests pass covering full KPI rendering, time window switching, error handling, and uncalibrated MTTR states. The full repository test suite (980 passed backend tests, 160 passed frontend tests) is 100% green. Ruff and Mypy report zero errors.

**Learning and next steps:** Uncapped server-side aggregations provide true operational observability without UI lag or memory blowup while maintaining strict tenant isolation. With all Cockpit workspace issues (#143, #144, #145, #146, #148, #149, #150, #151, #152, #153) delivered, development now transitions to the Driver Flow issues (#156–#160).

---

## Week 4: Master UI/UX Design System Specification & Cockpit Baseline Confirmation — 2026-10-05

**Objective and artifacts:** Confirm the Emerald Sentinel v2.0 design baseline, 10 Master Design Rules, component & state contracts, API data mappings, Driver-first reconciliation, and bidirectional Stitch MCP links ([Issue #148](https://github.com/AI20K-Build-Phase-Cohort-4/P-063/issues/148)). Delivered [`docs/design/Design.md`](../design/Design.md), [`ISSUE_148_VERIFICATION.md`](../testing/ISSUE_148_VERIFICATION.md), and confirmed Stitch MCP projects: Cockpit & Fleet Workstation (`projects/12095025610159108305`), Tester Simulation Studio (`projects/7541683500450336068`), and GIS Evidence (`projects/7784297700642891517`).

**Roadblocks and solutions:** In operational fraud workstations, cognitive load directly degrades Mean Time to Resolution (MTTR). Legacy UI specifications lacked standardized component states across missingness, review locks, and system errors, occasionally containing fabricated metrics or accusatory guilt semantics. We codified the 10 Master Design Principles (visual icon primacy, pure vector branding, compact modernism, MTTR < 45s workspace layout, approachable driver chatbot, tester simulation parity, Emerald Sentinel 2.0 semantic palette, shadcn/ui components, ubiquitous skeleton placeholders, and strict single-line anti-wrap discipline). Furthermore, we reconciled the design specification with the approved Driver-first lifecycle in #147 and ADR-018 (advisory uncalibrated confidence `[0, 1]`, Driver confirmed resolution distinct from Analyst dismissal, context reset checkbox, and vehicle plate search), and removed all fabricated operational values in favor of objective forensic descriptors.

**Observed outcomes:** All 83 Phase 1 BA and architecture documentation unit tests (`tests/unit/docs/`) pass 100% green. The full webapp Vitest suite (156/156 tests across 26 suites) passes cleanly. Ruff linter confirms zero errors, code formatting confirms all files formatted, and mypy static type checking reports zero issues.

**Learning and next steps:** Anchoring design specifications in explicit operational states (missing, loading, empty, locked, error) and bidirectional Stitch project links ensures seamless frontend implementation without design drift. This satisfies the design review gate for Issue #152 (Fleet Analytics System Metrics).

---

## Week 4: Analyst Profile, Decision Metrics, and Immutable Activity Ledger — 2026-10-05

**Objective and artifacts:** Deliver personalized analyst profile workspace, real-time shift performance metrics, active review lease banner with dynamic TTL countdown, governance limits bar, and immutable chronological audit ledger ([Issue #151](https://github.com/AI20K-Build-Phase-Cohort-4/P-063/issues/151)). Delivered [`ADR-021`](../architecture/adr-021-analyst-audit-ledger.md), [`ISSUE_151_VERIFICATION.md`](../testing/ISSUE_151_VERIFICATION.md), updated `src/models/schemas.py` with `AnalystDecisionMetrics`, `AnalystGovernanceLimits`, `ActiveReviewLeaseSummary`, `AnalystAuditLedgerItem`, and `AnalystAuditProfileResponse`, updated `src/services/case_service.py` with `get_analyst_audit_profile` (supporting database queries on `app.adjudications`, `app.review_leases`, `app.principals` and full in-memory fallback parity), updated `src/api/routes.py` with `GET /api/v1/analyst/audit` endpoint, updated `src/webapp/types/schemas.ts` and `src/webapp/lib/api-client.ts`, implemented `AnalystProfileView` in `src/webapp/components/views/profile-view.tsx` with Design.md §2.3 specifications, backend Pytest suite `tests/test_api/test_analyst_audit.py`, and Vitest suite `src/webapp/tests/analyst-audit.test.tsx`.

**Roadblocks and solutions:** In high-throughput HITL fraud operations, analysts need immediate visibility into their active review lock to prevent lease abandonment and avoid concurrency collisions with other analysts. At the same time, compliance standards require complete auditability of human decisions with cryptographic request hashes and transparent governance limits. We designed `GET /api/v1/analyst/audit` to simultaneously retrieve shift metrics (today's decisions, 30-day volume, MTTR, model agreement rate, and quality overturn rate), active lease details with remaining seconds, and immutable chronological verdict records. On the frontend, we built an active review lock banner with dynamic countdown and "Resume Case →" quick action, a 4-card KPI row, governance limits breakdown according to authenticated RBAC, and an interactive verdict audit trail table with real-time text search and verdict dropdown filtering.

**Observed outcomes:** All 5 backend Pytest cases pass (metrics computation, governance limits, active lease banner, ledger search/verdict filter, RBAC authorization, and tenant isolation). All 4 frontend Vitest cases pass (4-card metrics row, active review banner with countdown and resume callback, governance limits bar, and verdict audit trail table with search & filter). The full Vitest suite (156/156 tests across 26 suites) is 100% green. Ruff linter reports 0 errors, code formatting confirms all files formatted, and mypy type checker reports 0 issues.

**Learning and next steps:** Providing real-time shift feedback and direct lease resumption eliminates friction in analyst triage workflows while anchoring human accountability with immutable cryptographic audit trails. This completes the core analyst workflow suite (#143, #144, #145, #146, #149, #150, #151), setting the stage for completed case count and category distribution analytics in the analytics view ([Issue #152](https://github.com/AI20K-Build-Phase-Cohort-4/P-063/issues/152)).
## Week 4: SPEC-0130 Tester Trip Simulation, Workplace Data Continuity & Automated E2E Suite — 2026-10-05

**Objective and artifacts:** Implement SPEC-0130 §6.7 Tester Trip Simulation Cockpit (`/test`), Sandbox Test Workplace (`/test/workplace`), end-to-end data continuity bridge, automated Playwright E2E test suite, and manual verification runbook ([PR #176](https://github.com/AI20K-Build-Phase-Cohort-4/P-063/pull/176)). Delivered [`src/webapp/e2e/tester-simulation-e2e.spec.ts`](../../src/webapp/e2e/tester-simulation-e2e.spec.ts), [`docs/testing/MANUAL_TEST_TESTER_SIMULATION.md`](../testing/MANUAL_TEST_TESTER_SIMULATION.md), test routes `src/api/test_routes.py`, simulation runner `src/services/test_simulation_runner.py`, test repository `src/services/test_simulation_repository.py`, and test client `src/webapp/lib/testApiClient.ts`.

**Roadblocks and solutions:** When testing the cockpit simulation independently, cases generated in `/test` did not populate `/test/workplace` because the simulation runner did not automatically register synthetic cases into the workplace tenancy store or route notifications to a retrievable sink. We established an automatic data bridge in `SimulationRunner.start_run` that creates a synthetic case (`case-sim-...`) linked to the active `run_id` with calibrated risk scores and records pre-configured dialogue script items into a mock notification sink. Queries in `TestSimulationRepository.list_cases` and `triage_case` strictly enforce `test_run_id IS NOT NULL`, guaranteeing fail-closed data tenancy without cross-polluting production tables. Additionally, we authored a Playwright E2E test suite validating the entire lifecycle from `/test` parameter entry to `/test/workplace` case triage, and authored a step-by-step manual test runbook for human verification.

**Observed outcomes:** 2/2 Playwright E2E tests pass cleanly in 13.3s; 162/162 Vitest frontend tests pass across 25 suites; 10/10 pytest simulation API and kinematics engine tests pass; `tsc --noEmit` reports 0 errors; Ruff linter and code formatting confirm 100% clean repository state.

**Learning and next steps:** Realistic testing of complex human-in-the-loop workflows requires seamless end-to-end data continuity between the simulation generator and the triage workspace, operating under strict fail-closed boundary isolation (`X-Test-Context: true`).

---

## Week 4: Processed Case History Search and Retained Evidence Archive — 2026-10-05

**Objective and artifacts:** Deliver server-backed archive search, pagination, and read-only inspection of processed fraud cases (`resolved`, `dismissed`, `auto_dismissed`) with retained evidence, driver dispute conversations, executed actions, and immutable audit logs ([Issue #150](https://github.com/AI20K-Build-Phase-Cohort-4/P-063/issues/150)). Delivered [`ADR-020`](../architecture/adr-020-case-history-archive.md), [`ISSUE_150_VERIFICATION.md`](../testing/ISSUE_150_VERIFICATION.md), updated `src/services/case_service.py` with `list_case_history` (supporting shared identity/license search, terminal status, decision, analyst, and date filters), updated `src/api/routes.py` with `GET /api/v1/cases/history` endpoint, updated `src/webapp/lib/api-client.ts`, Cockpit dual-mode Active Queue / Case History tabs in `src/webapp/components/views/cockpit-view.tsx`, backend Pytest suite `tests/test_api/test_case_history.py`, and Vitest suite `src/webapp/tests/case-history.test.tsx`.

**Roadblocks and solutions:** Finalized cases must be removed from the active triage queue ([Issue #143](https://github.com/AI20K-Build-Phase-Cohort-4/P-063/issues/143)) to prevent queue clutter and lease contention, but compliance auditors and analysts still require browsing completed cases without accidentally triggering new review leases (`app.review_leases`) or automated sanctions. We designed `GET /api/v1/cases/history` with strict terminal status scoping (`resolved`, `dismissed`, `auto_dismissed`), prioritized route declaration ahead of dynamic `/cases/{id}` path parameters, and added read-only UI controls (displaying an Archived status badge and read-only versioned decision banner while hiding claim/action buttons). Driver role access is strictly restricted to driver-owned history (`driver_id = principal.driver_id`).

**Observed outcomes:** All 6 backend case history Pytest cases pass (queue exclusion, search, status/decision filtering, zero-lease guarantee, tenant isolation, and pagination). All 5 frontend Vitest cases pass (dual-tab navigation, search in history, status dropdown, read-only UI, and pagination). The full Vitest suite (152/152 tests across 25 suites) is 100% green. Ruff and Mypy report zero errors across the codebase.

**Learning and next steps:** Separating active triage queues from terminal historical archives prevents lock contention and race conditions while preserving full auditability and evidence provenance. This prepares the foundation for multi-case evidence provenance tracking across driver shifts ([Issue #151](https://github.com/AI20K-Build-Phase-Cohort-4/P-063/issues/151)).

---

## Week 4: Case Search by Driver Identity and Vehicle Plate — 2026-10-05

**Objective and artifacts:** Deliver search capabilities across the fraud triage queue by driver name, driver ID, external fleet reference, and vehicle registration plate ([Issue #149](https://github.com/AI20K-Build-Phase-Cohort-4/P-063/issues/149)). Delivered [`ADR-019`](../architecture/adr-019-case-search-identity.md), [`ISSUE_149_VERIFICATION.md`](../testing/ISSUE_149_VERIFICATION.md), updated `src/services/case_service.py` with parameterized `EXISTS` subquery and Unicode NFKD accent normalization, updated `src/api/routes.py` with `search` query parameter, updated `src/webapp/lib/api-client.ts`, Cockpit Triage Queue search bar in `src/webapp/components/views/cockpit-view.tsx`, backend Pytest suite `tests/test_api/test_case_search.py`, and Vitest suite `src/webapp/tests/case-search.test.tsx`.

**Roadblocks and solutions:** Searching Vietnamese driver names requires accent-insensitive matching (e.g., query `binh` matching `Nguyễn Văn Bình`, and mapping `đ`/`Đ` to `d` which standard Unicode diacritic stripping misses). In addition, license plate strings often vary in punctuation (`29E-123.45` vs `29e12345`). In the PostgreSQL branch, we used parameterized `EXISTS` subqueries over `app.trip_assignments` to prevent cartesian row blowup and ensure zero SQL injection vulnerabilities. In the in-memory fallback, we implemented `_normalize_search_text` combining NFKD decomposition, diacritic stripping, explicit `đ -> d` substitution, and punctuation-agnostic plate matching. Multi-tenant boundaries and lock states remain strictly enforced.

**Observed outcomes:** All 6 backend search Pytest cases pass covering accents, plates, IDs, multi-tenant boundaries, and injection safety. All 4 frontend Vitest cases pass verifying input rendering, query forwarding, clear button behavior, and empty state display. 964 backend tests pass across the repo, and static typing (Mypy) and linting (Ruff) are 100% clean.

**Learning and next steps:** Normalizing diacritics and punctuation at both service and SQL layers ensures analysts can rapidly locate cases regardless of varied keyboard input conventions without weakening tenant or lease boundaries. This search contract provides the foundation for Issue #150 (case history browsing and filtering).

---

## Week 4: Analyst Single-Message Context Reset — 2026-10-05

**Objective and artifacts:** Implement an explicit, unchecked-by-default per-message context reset checkbox in the Adjudication Cockpit chat input to allow objective policy evaluations without conversational dialogue contamination ([Issue #153](https://github.com/AI20K-Build-Phase-Cohort-4/P-063/issues/153)). Delivered [`ADR-021`](../architecture/adr-021-analyst-context-reset.md), [`ISSUE_153_VERIFICATION.md`](../testing/ISSUE_153_VERIFICATION.md), backend model-input tests in `tests/test_api/test_analyst_context_reset.py`, frontend Vitest suite in `src/webapp/tests/analyst-context-reset.test.tsx`, schema updates in `src/models/schemas.py` and `src/webapp/types/schemas.ts`, and accessible single-turn UI toggle in `src/webapp/components/views/cockpit-view.tsx`.

**Roadblocks and solutions:** In forensic analysis, analysts must be able to ask the model to evaluate case evidence and policy clauses with zero conversational bias from earlier chat turns, but without wiping the case history or destroying the compliance audit trail. We resolved this by defining that "reset is not deletion" (FR-WS-01/AC-WS-01). When `reset_context=True` is passed, the model input excludes earlier conversational turns while persisting all messages to `app.case_agent_messages` and retaining case facts, telemetry, and guardrails. On the client side, the toggle is single-turn and unchecks automatically upon sending, resuming normal conversational context on subsequent turns.

**Observed outcomes:** Multi-turn model input tests verify that Turn 1 contains Query 1, Turn 2 accumulates Turn 1 dialogue, Turn 3 with reset=True receives strictly Query 3 without previous dialogue, and Turn 4 with reset=False resumes full dialogue history. All 3 backend tests, 3 frontend tests, and full suites (958 pytest, 146 vitest) pass 100% green. Ruff and Mypy report zero errors.

**Learning and next steps:** Separating model runtime prompt assembly from durable audit log persistence provides analysts with precision exploration tools while ensuring complete compliance and evidentiary integrity.

---

## Week 4: Queue Lease Synchronization & Multi-Session Concurrency — 2026-10-05

**Objective and artifacts:** Resolve claimed-case visibility desync and concurrency conflicts across multiple analyst sessions ([Issue #144](https://github.com/AI20K-Build-Phase-Cohort-4/P-063/issues/144)). Delivered dual principal identity resolution in `src/services/case_service.py`, robust review lease filtering in `list_cases`, 10-second periodic background queue & detail sync with tab visibility awareness in `src/webapp/components/views/cockpit-view.tsx`, PRD-compliant read-only lock notification banner, ADR-020 (`docs/architecture/adr-020-queue-lease-synchronization.md`), and regression test suites `tests/test_api/test_queue_lease_sync.py` and `src/webapp/tests/queue-lease-sync.test.tsx`.

**Roadblocks and solutions:** In PostgreSQL mode, non-UUID analyst identities (e.g. Clerk external subjects `user_...`) threw `invalid input syntax for type uuid` during `SELECT id FROM app.principals WHERE id = %s`, aborting transactions and causing leases to fall back to in-memory storage without DB persistence. Replaced with `_is_valid_uuid` guards querying `WHERE external_subject = %s` on non-UUID subjects. In the frontend, the workspace previously fetched cases only upon mount or manual refresh, leaving claimed cases visible in peers' browsers. Implemented a 10s silent sync interval and `visibilitychange` listener, paired with immediate 409 Conflict recovery that reloads case detail and transitions into read-only lock state.

**Observed outcomes:** Actively leased cases disappear from peers' available queues automatically. Claiming analysts resume work in "My Cases". Conflicting concurrent claims or decisions return 409 Conflict with clear recovery feedback. 5/5 pytest API regressions pass and 147/147 Vitest frontend tests across 24 test suites pass cleanly.

**Learning and next steps:** Concurrency guarantees in distributed web applications require synchronized multi-layer boundaries: database transactions must never abort silently on identity syntax discrepancies, and client UIs must combine periodic background sync with event-driven optimistic conflict recovery.

---

## Week 4: Clerk UserButton Account Settings Consolidation — 2026-10-05

**Objective and artifacts:** Consolidate Account Settings and Role Configuration trigger into Clerk's native `<UserButton />` dropdown menu ([Issue #146](https://github.com/AI20K-Build-Phase-Cohort-4/P-063/issues/146)). Delivered integrated `<UserButton.MenuItems>` and `<UserButton.Action>` in `src/webapp/app/workplace/page.tsx`, pruned redundant standalone Settings buttons from Workplace header and `src/webapp/components/views/profile-view.tsx`, and updated frontend Vitest suite `src/webapp/tests/account-settings.test.tsx`.

**Roadblocks and solutions:** Standalone Settings buttons previously cluttered the Workplace header and Profile view alongside Clerk's native `<UserButton />`. Using `@clerk/nextjs` custom menu extension components (`UserButton.MenuItems` and `UserButton.Action`), the modal trigger is now seamlessly nested inside Clerk's profile dropdown with standard styling and icon. Maintained explicit bypass button when `NEXT_PUBLIC_E2E_AUTH_BYPASS` is active so Playwright E2E suites can trigger the modal deterministically without Clerk session mocking.

**Observed outcomes:** 143/143 Vitest tests pass across 23 test suites. Component mock in Vitest correctly mirrors Clerk's `MenuItems` and `Action` compound components. Workplace header is clean with no standalone settings button.

**Learning and next steps:** Leveraging vendor component extension slots (like Clerk's `UserButton.MenuItems`) preserves standard user profile UX without adding parallel controls or compromising test accessibility.

---

## Week 4: Role-Owned Access and Server Route Protection — 2026-10-05

**Objective and artifacts:** Enforce strict analyst/driver role separation across webapp Server Components, REST API endpoints, SSE chat streams, and dispute tools ([Issue #145](https://github.com/AI20K-Build-Phase-Cohort-4/P-063/issues/145)). Delivered [`ADR-016`](../architecture/adr-016-role-owned-access.md), [`ISSUE_145_VERIFICATION.md`](../testing/ISSUE_145_VERIFICATION.md), Next.js server route guards `src/webapp/lib/server-route-guard.ts` and `src/webapp/lib/route-authorization.ts`, backend service `src/services/access_control.py`, and comprehensive test suites `tests/test_api/test_role_access.py` and `src/webapp/tests/route-authorization.test.ts`.

**Roadblocks and solutions:** Previous route protection relied on client-side state checks and middleware exclusions, permitting potential direct URL and API navigation by unauthorized roles. In particular, drivers could theoretically access workplace analytics or chat sessions of other drivers. We moved route protection into Next.js Server Components (`server-only`), verifying Clerk session tokens directly against database-derived principal roles. We enforced `require_case_scope` in the backend service layer before emitting SSE headers, chat history, or attachments. Privileged role self-grants were blocked.

**Observed outcomes:** 56 API role access unit tests pass in 2.75s, 6 RBAC and settings tests pass in 45.57s, and 14 Vitest route authorization tests pass in 465ms. All protected routes fail closed on unauthenticated or mismatched role attempts.

**Learning and next steps:** Client-side visibility gating is never an authorization boundary. True multi-role isolation requires server-side validation against persisted identity and case assignment state at every entry point.

---

## Week 4: Driver-First Resolution Contract Architecture — 2026-10-05

**Objective and artifacts:** Reconcile Driver assistance and explicit Driver-confirmed resolution with the adopted Phase 1 Analyst baseline ([Issue #147](https://github.com/AI20K-Build-Phase-Cohort-4/P-063/issues/147)). Delivered [`ADR-018`](../architecture/adr-018-driver-first-resolution.md), [`DRIVER_FIRST_REQUIREMENTS.md`](../ba/DRIVER_FIRST_REQUIREMENTS.md), [`DRIVER_FIRST_GLOSSARY.md`](../ba/DRIVER_FIRST_GLOSSARY.md), and updated [`DECISION_LOG.md`](../ba/DECISION_LOG.md), [`MVP.md`](../ba/MVP.md), [`PRD.md`](../ba/PRD.md), and [`README.md`](../ba/README.md).

**Roadblocks and solutions:** Historical attempts at autonomous dismissal (e.g. PR #40) conflated model-generated exoneration with authorized adjudication, creating audit risks and violating procedural justice rules. Following explicit stakeholder decisions by @datamonsterr, we established that Driver assistance precedes Analyst triage, but explicit Driver confirmation is strictly separated from exoneration or sanctions. Cases with confidence strictly >0.5 ask the Driver for an appeal choice; "No further appeal" closes as Driver-confirmed resolution, while "Continue appeal" escalates to the Analyst. Missing or invalid confidence and 48-hour timeouts escalate without inventing false exonerations.

**Observed outcomes:** All 50 Phase 1 BA contract unit tests (`tests/unit/docs/test_phase1_ba_docs.py`) pass 100% green without regressions. Markdown links and heading anchors resolve cleanly.

**Learning and next steps:** Preserving baseline guarantees while enabling human-centered workflow extensions requires strict vocabulary and domain boundary isolation. Next steps are implementing the database schema transitions and worker timeout sweeps per ADR-018.

---

## Week 4: Baseline Offline Quality & Type Boundaries — 2026-10-05

**Objective and artifacts:** Restore deterministic offline backend quality checks, static typing soundness, and case location tool coordinate handling ([Issue #161](https://github.com/AI20K-Build-Phase-Cohort-4/P-063/issues/161)). Delivered [`ADR-017`](../architecture/adr-017-offline-backend-type-boundaries.md), [`ISSUE_161_VERIFICATION.md`](../testing/ISSUE_161_VERIFICATION.md), updated `pyproject.toml` mypy configuration, autouse mocked Jev credential fixtures in `tests/conftest.py`, type-sound narrowing across agent/RAG/service layers, and regression tests in `tests/test_agents/test_case_location_tools.py`.

**Roadblocks and solutions:** In local and CI environments running Python 3.13, mypy stopped on NumPy stub syntax because the configuration targeted Python 3.11. Once aligned to the runtime environment, 58 latent type errors across 8 files were surfaced in LangChain/LangGraph runnables, SDK schemas, and Pydantic models. Furthermore, ambient developer keys in `.env` caused default test executions to make live external calls to OpenRouter, breaking offline determinism. We isolated ambient keys via autouse pytest fixtures, narrowed all nullable models and message collections with strict typing, and repaired GeoJSON Point coordinate extraction in weather and traffic tools.

**Observed outcomes:** Complete `bash scripts/check.sh` passes 100% green: Ruff linter reports 0 errors, code formatting confirms 161 files formatted, mypy type checker reports 0 issues across all modules, and pytest completes 958 passed (0 failed, 52 skipped opt-ins).

**Learning and next steps:** Strict static typing must match the active interpreter stubs, and tests must never leak ambient environment variables into third-party network egress. With baseline offline verification restored to green, feature branches can merge cleanly without inherited lint or type regressions.

---

## Week 4: Compact analyst cockpit decision workspace — 2026-10-04

**Objective and artifacts:** Deliver the compact investigation and decision workspace for Sprint 2 Feature S2-F02 ([Issue #59](https://github.com/AI20K-Build-Phase-Cohort-4/P-063/issues/59)). Implemented honest missing-evidence handling in [`src/webapp/lib/adjudication-data-adapter.ts`](../../src/webapp/lib/adjudication-data-adapter.ts) and [`src/webapp/components/adjudication/overview-tab.tsx`](../../src/webapp/components/adjudication/overview-tab.tsx), enforced mandatory written rationale ($\ge 10$ characters) across [`src/models/schemas.py`](../../src/models/schemas.py) and [`src/webapp/components/views/cockpit-view.tsx`](../../src/webapp/components/views/cockpit-view.tsx), and authored [`HYPOTHESIS_TO_CONTROL_MAPPING.md`](../architecture/HYPOTHESIS_TO_CONTROL_MAPPING.md) linking Stitch project baseline.

**Roadblocks and solutions:** The inherited frontend adapter previously fabricated fallback numbers (`420s` dwell time, `0.82` DAVI score, `14m` drift deviation) whenever telemetry was absent, directly conflicting with the core principle that the frontend must not invent evidence. Replaced all fabricated fallbacks with nullable types, rendering explicit `N/A` or `Chưa có dữ liệu` indicators on the cockpit canvas. Strengthened rationale validation with Pydantic field validators and UI button guards ensuring compliance with AC-P1-03.

**Observed outcomes:** 139/139 Vitest tests passing across 22 test files, 9/9 Playwright E2E browser tests passing with real clicks on inspect, evidence request, dismissal, and authorized approval, and 151/151 Python unit tests passing. Codebase linting and formatting are 100% clean.

---

## Week 4: Playwright CI Port Isolation — 2026-10-04

**Objective and artifacts:** Resolve self-hosted runner port collisions in CI Playwright tests ([Issue #76](https://github.com/AI20K-Build-Phase-Cohort-4/P-063/issues/76)). Delivered isolated dynamic port allocation in `.github/workflows/ci.yml`, automatic fallback discovery in `src/webapp/playwright.config.ts`, removed disruptive `fuser -k` listener kills, and authored regression suite `src/webapp/tests/playwright-port.test.ts`.

**Roadblocks and solutions:** Previous temporary workaround pinned port 3100 and invoked `fuser -k 3100/tcp`, which killed concurrent runner processes or failed if another contributor was bound to the port, violating non-interference requirements. Replaced with dynamic OS socket negotiation via Node's `net.createServer().listen(0)` during CI workflow execution and inside Playwright configuration, ensuring concurrent runs obtain unique ports. Local development continues to default cleanly to `3000` with `reuseExistingServer: true`.

**Observed outcomes:** All 5 regression tests pass verifying explicit PORT overrides, PLAYWRIGHT_TEST_BASE_URL extraction, default local 3000 preservation, CI dynamic ephemeral allocation, and active collision avoidance when port 3000 is occupied. Full webapp Vitest suite (143/143 tests across 23 suites) passes cleanly.

**Learning and next steps:** Fixed ports in shared CI environments create silent concurrency bottlenecks and flake. Dynamic kernel socket allocation ensures zero-conflict execution across concurrent runner jobs without process termination.

---
## Week 4: Tester trip simulation specification — 2026-10-03

### Objectives and completed artifacts

The objective was to understand why Tester data preparation blocks end-to-end validation and specify a usable replacement before engineering work. Pham Thanh Dat, acting as Tester with Codex assistance, described an approximately one-day workflow spanning maps, copied coordinates, scripts and AI-assisted database edits. [Discovery findings](../ba/DISCOVERY_TESTER_TRIP_SIMULATION.md), [PRD §11](../ba/PRD.md#11-tester-trip-simulation-extension) and [MVP §8](../ba/MVP.md#8-tester-trip-simulation-extension) now specify an approximately one-minute preparation target, free trip composition, runtime vehicle control, editable dialogue, segment congestion, deliberate GPS faults, persistence and actual system/Workplace observations. Implementation and usability acceptance remain pending.

### Roadblocks, solutions and outcomes

Historical traffic availability, exact GPS cadence/reference metrics, notification contracts, role mapping and replay policy remain unresolved. The specifications preserve these as owned open questions rather than inventing provider support, runtime behavior or measured results. Traffic can be explicitly simulated per segment; source provenance remains distinct. The user confirmed normal assignment to the existing Workplace without a required visible `TEST` label. Existing analyst confirmation and production-mobile scope boundaries remain intact.

### Key learnings and next steps

Plausible road geometry, sufficient temporal sampling and actual pipeline correlation are necessary for a trustworthy Tester workflow; choosing canned violation scenarios does not satisfy unrestricted authoring. Delivery is tracked under [Feature #130](https://github.com/AI20K-Build-Phase-Cohort-4/P-063/issues/130), with [documentation #131](https://github.com/AI20K-Build-Phase-Cohort-4/P-063/issues/131) carrying this specification change. Next work is accepted design and implementation through the linked dependencies, followed by migrated-database, browser and observed timing proof. This entry records documentation work, not delivery of the simulator.

## Week 4: Grounded advisory reasoning — 2026-10-03

**Objective and artifacts:** Extend the existing #40 forensic baseline within Phase 1 ERR-02/ERR-05 scope. Delivered strict advisory JSON, exact source/version policy citations, abstention for unavailable or contradictory evidence, case-snapshot-scoped runtime policy retrieval, and [paired evaluation](../../eval/results/issue62_benchmark_report.md). [ADR-014](../architecture/adr-014-grounded-advisory-evaluation.md) records the user's gate exception and approved local thresholds.

**Roadblocks and solutions:** The existing local draft treated hard-coded clause names as retrieval and marked fixed scores calibrated. Its benchmark derived observations from suite labels. Source-backed extraction and strict input boundaries replace these behaviors. The user authorized reuse of #64's corpus branch; its provenance and pending SME status are preserved rather than treated as accepted completion.

**Observed outcomes:** Focused source/contract tests pass and the paired ten-case development fixture meets local thresholds. All 37 referenced held-out records remain `not_run`: they do not provide a verified mapping to measured classifier input. Existing full-repository typing errors are reported separately from the passing scoped implementation checks. [Verification](../testing/ISSUE_62_VERIFICATION.md) distinguishes local, database and hosted evidence.

**Learning and next steps:** A dataset version or perfect development result does not establish an unseen benchmark or calibrated violation probability. Supply version-pinned observation adapters and independent review before evaluating held-out quality or closing the full feature DoD. Keep sanctions human-controlled and preserve the existing analyst workflow when policy retrieval is unavailable.

### Provider transport review — 2026-10-03

Final provider review found that constructor/response tests did not validate the native-content adapter's actual outgoing JSON Schema. Google enum types remained uppercase on OpenAI/OpenRouter requests. The [issue #118 repair](../testing/reports/ISSUE_118_VERIFICATION.md) preserves property/enum/argument values and validates real SDK request serialization against an independent metaschema. Two RED cases and 67 GREEN provider/SDK/policy cases establish the transport contract; live-model quality remains separate. Current-head CI and authorized merge are the final external steps.

> Rolling master journal recording weekly reflections, milestone achievements, roadblocks, and sprint planning for Demo Day Deliverable #8.

---

## Weekly Sprint Index

## Week 4: Clerk & Database RBAC with Account Settings Consolidation (2026-10-03)

**Objective:** Implement a unified Role-Based Access Control (RBAC) architecture across Clerk authentication and PostgreSQL schemas supporting `fraud_analyst`, `driver`, and `manager` roles, paired with workplace UI cleanup for [issue #128](https://github.com/AI20K-Build-Phase-Cohort-4/P-063/issues/128).

**Artifacts:** The DB migration [`20261003220000_rbac_roles_manager_and_fraud_analyst.sql`](../../db/migrations/20261003220000_rbac_roles_manager_and_fraud_analyst.sql), auth layer [`src/api/auth.py`](../../src/api/auth.py), service layer [`src/services/case_service.py`](../../src/services/case_service.py), and UI modal [`src/webapp/components/account/account-settings-modal.tsx`](../../src/webapp/components/account/account-settings-modal.tsx).

**Roadblocks and solution:** Discrepancies between Clerk session roles and database constraints required JIT mapping and role normalization (`fraud_analyst` normalizing to review privileges, `manager` inheriting case review authority and team role management). Adjudication logic was extended with explicit `REJECT` outcome sanctions and database checks. The redundant hardcoded `"LT"` avatar button in Workplace was replaced with an integrated Account Settings modal situated directly beside Clerk's native `<UserButton />`.

**Observed outcome:** 17/17 auth/RBAC backend tests pass, 138/138 Vitest frontend tests pass across 22 test files, 10/10 Playwright E2E tests pass, and code linting is 100% clean.

## Week 4: Restricted-token Vercel deployment repair (2026-10-03)

**Objective:** Restore CI deployment with the existing restricted project token for [issue #115](https://github.com/AI20K-Build-Phase-Cohort-4/P-063/issues/115).

**Artifacts:** The [submission wrapper](../../scripts/vercel_deploy.sh), [scoped REST helper](../../scripts/vercel_project.py), [deployment regression tests](../../tests/test_scripts/test_vercel_deploy.py), and [manual runbook](../testing/MANUAL_TEST_VERCEL_115.md) preserve deployment readiness and failure propagation.

**Roadblocks and solution:** CLI `inspect` and `alias set` require a user lookup that the restricted credential cannot perform. Project/deployment REST calls carry explicit team scope and verify project ownership. Separately, actionlint identifies invalid `failed()` expressions that prevent both deployment workflows from starting; replacing them with `failure()` passes validation. Transport submission retries remain finite and do not hide authentication failures.

**Observed outcome:** Eight deployment-wrapper regressions and 25 existing deployment/preview contracts pass locally. Hosted preview and full CI are still pending at this record's checkpoint.

**CI follow-up:** The first hosted attempt reveals a missing `gh` executable before deployment. Authenticated REST pagination removes that environmental dependency while preserving the requested repository and all file pages. Live GitHub headers confirm canonical numeric repository links, now covered by a failing-first regression. Expanded focused proof passes 138 tests; full CI unit tests pass on the preceding head of [PR #117](https://github.com/AI20K-Build-Phase-Cohort-4/P-063/pull/117). Final-head hosted deployment proof is still required.

**Learning and next step:** Successful builds, completed upload progress, and token validity do not prove deployment readiness or compatibility with user-scoped CLI commands. Verify the fix PR's exact deployment and all applicable CI checks before review; environment promotion retains its approval gates.

**Selective dispatch isolation:** Merges to `main` auto-deploy to the Development environment as documented in `docs/DEPLOYMENT.md`. Staging and Production are selective manual dispatch paths. Automated cascade conditions (`push`) on Staging/Production were decoupled to prevent false gate errors on push when environment protection reviewers are deliberately unconfigured.

## Week 4: Deployment preview gates (2026-10-03)

### Objectives
- [x] Record the Issue #107/#111 deployment preview and approval-gate architecture.
- [x] Publish manual verification cases and update deployment guidance.
- [ ] Obtain hosted preview evidence and live approval-rule configuration.

### Completed Work
- Added [`ADR-012`](file:///home/dat/dev/vinuni_aia/P-063/.worktrees/issue-107/docs/architecture/adr-012-pr-deployment-previews.md), [`ARCHITECTURE.md`](file:///home/dat/dev/vinuni_aia/P-063/.worktrees/issue-107/docs/architecture/ARCHITECTURE.md), [`DEPLOYMENT.md`](file:///home/dat/dev/vinuni_aia/P-063/.worktrees/issue-107/docs/DEPLOYMENT.md), and [`MANUAL_TEST_DEPLOYMENT_107.md`](file:///home/dat/dev/vinuni_aia/P-063/.worktrees/issue-107/docs/testing/MANUAL_TEST_DEPLOYMENT_107.md).

### Roadblocks & Solutions
| Challenge | Applied Solution | Outcome |
|---|---|---|
| Current GitHub write access returns HTTP 404 for live approval-rule `PUT` | Documented the API guard and kept live rules explicitly unconfigured | Fail-closed behavior and evidence boundary recorded |
| Hosted preview and deployment success were not executed in this documentation pass | Added manual scenarios for classifier, exact deployment, authorization, readiness, and production guards | Verification is pending and no hosted claim is made |

### Key Learnings
1. Preview authorization must match the exact returned origin and serialized Dev allowlist state.
2. Exact PR/head and deployment ID tracking prevents unrelated successful deployments from satisfying a gate.

### Next Week Plan
- [ ] Run the manual deployment matrix and attach hosted evidence.
- [ ] Configure and verify live reviewer rules when API access supports it.


## Week 4: Jev Advisory Anomaly Scoring and Multi-Layer Priority Triage (2026-10-03)

### Objectives and completed artifacts

[Issue #71](https://github.com/AI20K-Build-Phase-Cohort-4/P-063/issues/71) upgrades the Jev fraud assessment engine to evaluate multi-modal trip evidence and automatically triage priority.
- Multi-layer Jev Advisory Assessment Service (`src/services/jev_assessment_service.py`) integrating OpenRouter `/api/alpha/decisions` with `~typesafe/jev-latest` and calibrated heuristic fallback.
- Layer 1 error type classification (`ERR-01` to `ERR-05`, `no_violation`, `insufficient_evidence`) and Layer 2 auto-priority triage (`P0`, `P1`, `P2` with scores 1–100).
- Multi-input assessment schema incorporating driver profile, driver analytics, trip chat, driver dispute chat, customer reports, telemetry kinematics, and trip operational metadata.
- Golden set evaluation and unlabeled case intake spawning verification (`tests/test_golden_jev_assessment.py`, `eval/golden_set/forensic_mock_cases.json`).
- Cockpit UI surfacing confidence score and error type badge in left sidebar queue and center panel workspace header (`src/webapp/components/views/cockpit-view.tsx`, `src/webapp/tests/case-confidence-scoring.test.tsx`).
- ADR-012 documenting single-trip fraud scope (ERR-01 to ERR-05) and explicit deferral of multi-entity graph fraud (`docs/architecture/adr-012-jev-advisory-anomaly-scoring-and-single-trip-fraud.md`).

### Roadblocks, solutions, and outcomes

| Challenge | Applied solution | Outcome |
|---|---|---|
| OpenRouter decisions API expects strict choices and state structure | Implemented structured question dictionary (`error_type` and `priority_tier` with choice types and criteria) conforming to `/api/alpha/decisions` contract | Seamless real-time responses from `~typesafe/jev-latest` |
| Transient external API network errors must not break ingestion | Authored deterministic calibrated heuristic fallback matching GreenSM 2026 decision boundaries | 100% test reliability with zero unhandled exceptions during worker ingest |
| Multi-entity collusion rings cannot be detected from single-trip telemetry | Explicitly scoped single-trip fraud (`ERR-01` to `ERR-05`) and deferred graph/network fraud to dedicated offline analytics in ADR-012 | Clean architectural boundaries and absence of misleading false-positive graph detections |

---

## Week 4: Reliable agent tool contracts and UI execution events (2026-10-02)

### Objectives and completed artifacts

[Issue #60](https://github.com/AI20K-Build-Phase-Cohort-4/P-063/issues/60) and its sub-issues [#85](https://github.com/AI20K-Build-Phase-Cohort-4/P-063/issues/85) and [#86](https://github.com/AI20K-Build-Phase-Cohort-4/P-063/issues/86) harden the agent tool runtimes across the Cockpit and Driver Care portals. Key delivered artifacts include:
- Strict canonical tool catalog (`src/models/tool_contracts.py`, `src/services/tool_catalog.py`).
- Runtime boundary and principal-scoped authorization (`src/services/tool_authorization.py`, `src/agents/tools/runtime_boundary.py`).
- Source-backed typed executor with bounded transient retry (`src/services/tool_execution.py`).
- Durable command idempotency, interactive questions, and owner-approved Vietnamese minutes (`src/services/agent_workflow_service.py`, `src/services/workflow_repository.py`).
- Negotiated v1.1 SSE stream writer (`src/services/chat_event_writer.py`, `src/api/agent_runtime_routes.py`).
- Robust frontend stream parser and reducer with UTF-8 multibyte and interruption recovery (`src/webapp/lib/chat-event-stream.ts`).
- Comprehensive verification suite and manual test runbook (`docs/testing/ISSUE_60_VERIFICATION.md`, `docs/testing/MANUAL_TEST_ISSUE_60.md`).

### Roadblocks, solutions, and outcomes

| Challenge | Applied solution | Outcome |
|---|---|---|
| Multiple conflicting worktrees drifted from main | Systematically scanned, migrated, and consolidated all 5 subagent branches into `issue-60`, pruning old worktrees | Single unified canonical architecture matching ADR-006 and ADR-008 |
| Model could invoke human-only disciplinary actions | Excluded `write_ticket_for_driver` and `adjudicate_case` from model declarations; returned structured `FORBIDDEN` refutations | Strict Human-in-the-Loop (HITL) compliance; zero automated sanctions |
| Driver stream leaked internal analyst reasoning | Filtered database messages strictly by `role IN ('driver', 'driver_agent')` | Strict cross-actor confidentiality |
| Broken stream frames during network hiccups left permanent UI spinners | Built `ChatEventStreamParser` with paired call tracking, sequence validation, and EOF interruption cleanup | Retains partial text, cleans pending indicators, and offers safe retry |

### Key learnings and next steps

Decoupling client event streaming from internal tool execution bridges allows rich real-time UI without sacrificing strict transaction boundaries. Dynamic principal resolution and unseeded unit test guards prevent environmental test flakiness across self-hosted and containerized runner environments.

Delivered and verified via [PR #93](https://github.com/AI20K-Build-Phase-Cohort-4/P-063/pull/93) with 100% green CI/CD status (9/9 passing checks across unit, Docker integration, E2E, and preview deployments). All 5 DoD scenarios validated and captured with screenshot artifacts in [`docs/testing/MANUAL_TEST_ISSUE_60.md`](../testing/MANUAL_TEST_ISSUE_60.md). The next step is team code review and merging PR #93 into `main`.

---

## Week 4: Tabbed Center Panel Adjudication Interface & Evidence Hub (2026-10-01)

### Objectives and completed artifacts
Refactored the Cockpit Center Panel into 3 clean, tab-switchable adjudication views (`Overview`, `Conversation`, `Driver Information`) based on approved Google Stitch UI designs:
- **View 1 (`Overview`)**: Interactive `<MapLibreView>` + empirical evidence cards (`Stall & Drift Telemetry`, `Traffic Gridlock Assessment` with prominent `NORMAL`/`SLOWER` alert & hover corridor probe popover, `Platform & Sensor Reliability`, and dedicated `Agent Violation Detection` box presenting detected error type, violation probability % bar, and detection reason).
- **View 2 (`Conversation`)**: Case workflow synthesis timeline ribbon, side-by-side conflicting driver vs customer dispositions (`Match: Incompatible`), verbatim dialogue transcript drawer, and analyst inquiry delegation.
- **View 3 (`Driver Information`)**: Top driver & vehicle profile dossier alongside 90-day history scorecard (`Violation Ratio 3.8%`, `Fined Ratio 50.0%`, `Repeat Offense Risk 78/100`), past incident recency table, and Điều 14.2 policy citation.
- Full-width horizontal scaling: 3 tab headers (`Overview`, `Conversation`, `Driver Information`) scale dynamically to fit the exact 100% horizontal length of the center panel in a centered 3-column layout.
- Preserved top nav bar, triage queue (22%), copilot panel (28%), and exact `origin/main` bottom decision bar (textarea + bottom-right emerald send button + 3-choice popup menu).

### Verification
- Authored unit & integration tests in [`tests/center-panel-tabs.test.tsx`](../../src/webapp/tests/center-panel-tabs.test.tsx).
- All 18 test files (118/118 tests) passing cleanly without regressions.

---

## Week 4: Road telemetry evidence and consumer verification (2026-10-01)

### Objectives and completed artifacts

Issue [#63](https://github.com/AI20K-Build-Phase-Cohort-4/P-063/issues/63) adds one reproducible road dataset to the existing ingestion and case-review seams. [The generator](../../scripts/road_dataset.py) preserves case/assignment identities, uses captured OSRM geometry, and emits normal progress, stalled, directed away travel, synthetic traffic, and technical dropout. [ADR-011](../architecture/adr-011-versioned-road-telemetry-dataset.md) records units, seed derivation, cadence, labels, and provenance. [The verification record](../testing/ISSUE_63_VERIFICATION.md) separates fixture, isolated-database, local browser, and hosted results.

### Roadblocks, solutions, and outcomes

| Challenge | Applied solution | Outcome |
|---|---|---|
| AGY could not create its project configuration directory | Used bounded native workers in isolated Git worktrees and integrated their commits | Feature work continued; AGY execution is not claimed |
| Evaluation keys leaked through nested evidence and list-form coordinates | Added positive typed model projections and behavioral regressions | Unknown/nested label fields and non-finite geometry are excluded |
| Legacy seed/enrichment could overwrite routed evidence | Scoped enrichment and made versioned route/event writes preserving and transactional | Repeat-seed proof compares stored evidence and audit rows |
| Cached intent labels influenced fallback runtime guardrails | Derived blocking reasons from incidents and recorded operational guardrails | Evaluation metadata cannot create a runtime decision |
| Source-data assertions did not prove visible MapLibre rendering | Fixed worker/shared-module loading and refresh-driven timeline resets; added strict browser readiness/render checks and agent-browser inspection | Seven Playwright specs pass; real isolated stall, traffic, and dropout cases render and scrub correctly |
| Repository Mypy gate rejects installed NumPy stub syntax under its Python 3.11 target | Reported the exact blocker and ran scoped generator typing plus the full isolated backend suite separately | Three generator modules type-check; 444 backend tests pass; the full Mypy gate remains blocked |

### Key learnings and next steps

A populated GeoJSON source alone does not prove that a browser rendered it. Reproducibility requires stable per-case seed derivation and explicit omitted intervals. Immutable-event collision handling must remain strict even when a unit-test cursor fixture is stale.

The next step is review of the issue-linked PR and its exact validation boundary. Hosted checks and dependent features require their own accepted evidence; this work makes no downstream completion claim.


## Week 4: Postgres Migration, Containerized Backing Services, and Multi-Environment CI/CD

### Objectives
- [x] Migrate database layer from Supabase-specific dependencies to standard PostgreSQL with PostGIS and pgvector.
- [x] Replace Upstash Redis REST dependency with native containerized Redis (`redis:7-alpine`) and dual-transport support.
- [x] Resolve React performance bottlenecks: eliminate excessive polling loops and constrain MapLibre bounding boxes.
- [x] Provision and configure Postgres and Redis on Railway with public TCP proxies, applying all schema migrations and seed data.
- [x] Define local runner task orchestration with `mise` and structure CI/CD into Local, Dev, Staging, and Production stages.

### Completed Work
- **Database & Queue Architecture**: Containerized standard PostgreSQL (`postgis/postgis:16-3.4-alpine`) and Redis (`redis:7-alpine`) in `docker-compose.yml`. Extended `telemetry_queue.py` and `telemetry_queue_worker.py` with `RedisNativeTransport` and async connection pooling. Created `scripts/migrate_postgres.py` with automatic schema migration and seed ingestion.
- **Frontend Optimization**: Replaced 5-second `/cases` polling loop in `CockpitView` with single mount-time load and exponential backoff retry. Stabilized Clerk auth token callback reference in `app/workplace/page.tsx` to stop unmount/remount churn. Constrained MapLibre GIS bounds strictly to traveled path corridor and 3 anchor points with `useMemo` optimizations.
- **Railway Infrastructure**: Reconfigured Railway Postgres service to `postgis/postgis:16-3.4-alpine`, resolved quota allocation by removing legacy lab services, provisioned native Redis database, and enabled TCP proxies for external connectivity. Successfully executed migration: 39 tables created in `app` schema and populated with 100 trips, 100 fraud cases, and 1,200 telemetry records.
- **CI/CD & Task Automation**: Defined `mise` tasks (`test`, `test:integration`, `test:e2e`, `test:agent`, `docker:up`, `docker:down`, `db:migrate`). Structured GitHub Actions pipelines into Local (Docker services, integration & Playwright tests), Dev (`p-063-dev.vercel.app`, fast evals), Staging (synthetic smoke tests against real dependencies), and Production (manual approval gate, zero-downtime migrations).
- **Analyst Tools & Rich Chat Widgets**: Extended analyst automation tools to 18 tools with real Open-Meteo weather API (`check_weather_condition`), OSRM routing (`check_traffic_situation`), disciplinary ticket issuance (`write_ticket_for_driver`), vehicle swap auditing (`check_related_cases_to_vehicle`), driver operating card (`get_driver_card`), policy search (`search_policy_documents`), objective forensic brief aggregation (`get_forensic_brief`), and case-specific policy resolution (`get_case_policy`). Embedded interactive Next AI SDK UI widgets formatted with XML tags and JSON payloads across `CockpitRAGAgent` and `fraud_analyst_system_prompt.md`. Added paperclip attachment button in Cockpit chatbot allowing analysts to upload dispute evidence and screenshots with thumbnail preview. Created modular React widget components (`chat-widgets.tsx`), isolated Qdrant test collections, added `test-writer` and `test-runner` subagents, authored the `repo-testing` skill, and verified 100% green test suites across backend pytest tests, frontend Vitest tests, and Next.js Turbopack build.
- **Forensic Brief Aggregation & Case-Specific Policy RAG**: Implemented `GET /api/v1/cases/{id}/forensic-brief` and `GET /api/v1/cases/{id}/policy` endpoints and corresponding AI tools (`get_forensic_brief`, `get_case_policy`). Pre-populated the Cockpit `Decision rationale` box with the objective `forensic_brief.summary_text` summarizing exact observed abnormalities (stationary duration, mock location, DAVI drift, GPS accuracy, telemetry gaps, and technical guardrails) without faking data or rendering an automated verdict.
- **Environment Synchronization**: Verified and synced `DATABASE_URL` and `REDIS_URL` across local environment, Railway backend, and Vercel domains.

### Roadblocks & Solutions
| Challenge | Applied Solution | Outcome |
|---|---|---|
| Railway Postgres default template lacked PostGIS extension | Reconfigured Railway service source to `postgis/postgis:16-3.4-alpine` with dedicated `PGDATA` volume path | PostGIS extension and geography types enabled; all 39 tables and spatial geometries migrated cleanly |
| Railway resource limit (5/5 services) blocked Redis provisioning | Identified and deleted unused legacy services in inactive lab project | Quota freed; Redis database service provisioned with persistent volume and TCP proxy |
| Sequential WAN network latency during telemetry seed | Tracked per-batch execution over proxy tunnel | Successfully populated all 1,200 telemetry points and 100 cases into Railway Postgres |

---

## Week 3: POC v1 implementation and preview boundary

### Objectives
- [x] Complete the database-backed map, telemetry, case-session, and cockpit v1 slice.
- [x] Verify focused backend/frontend contracts and document browser fixture boundaries.
- [x] Review PR-safe Vercel and Railway preview conditions and health checks.
- [x] Document secret boundaries, fork behavior, and the missing external verification.

### Completed Work
- Updated the 20 synthetic Supabase drivers from empty `display_name` values to 20 unique varied identities; checked counts and route-pair uniqueness.
- Enhanced Cockpit Center Panel detail case view: redesigned header with driver avatar, rating, acceptance rate, cancellation rate, total trips, plate number, route (pickup -> destination), status badge (completed, picking up, coming), pricing (VND), and match type (now/auto).
- Executed additive migration (`20260926130000_center_panel_driver_trip_enrichment.sql`) adding avatar, metrics, and match_type to Supabase schema with synthetic data backfill across drivers and trips.
- Connected case detail to persisted driver/customer, telemetry, route provenance, and case-scoped Agent sessions; removed fabricated route fallback behavior.
- Removed midpoint geometry, default GPS coordinates, fabricated peer traffic, and synthetic route metrics from live evidence paths; unavailable sources remain absent.
- Reworked the cockpit around real API loading, Available/Locked by me filters, the driver/customer conversation, compact streamed Agents status, colored map evidence, and center-trip navigation.
- Added read-only `contents` permissions to the deployment workflows and documented isolated Railway preview resources in the [deployment runbook](../DEPLOYMENT.md).
- Fixed Clerk 401 token expiration on streaming policy chat with proactive JWT checks and `{ skipCache: true }` token refresh interceptors.
- Enhanced cockpit chatbot UI with compact thought process (`thinking ...` progress, toggleable reasoning trace) and clear tool names beside icons.
- Established multi-environment E2E test suite verifying 5-message conversation DoD across test, dev, and prod.
- Configured multi-tier CI/CD pipelines across Vercel, Railway, PostgreSQL, and CI test suites supporting `staging` -> `staging.p-063.vercel.app`, `main` -> `p-063.vercel.app`, and `dev` -> `p-063-dev.vercel.app`.
- Conducted POC v2 Business Analysis discovery session using BA Zone `ask-why-ba` protocol for async driver dispute resolution and unified analyst-agent collaboration (`US-L06-09`, `US-L06-10`, `UC-L06-08`, `UC-L06-09`); published [`ADR-008`](../architecture/adr-008-poc-v2-async-driver-agent-and-a2a-collaboration.md) and expanded [`POC_DESIGN.md`](../architecture/POC_DESIGN.md) for POC v2 (PR #35).
- Implemented POC v2 Slice 1: PostgreSQL driver role migration, Pydantic schemas, `DRIVER_TOOLS`, and autonomous exoneration dispute service with 14/14 green TDD tests (PR #36).
- Implemented POC v2 Slice 2: FastAPI driver dispute endpoints (`/driver/cases/{id}/*`), SSE streaming, and A2A delegation inquiry API with 10/10 green TDD tests (PR #37).
- Implemented POC v2 Slice 3: Next.js mobile driver dispute chat view (`/driver/dispute/[caseId]`), quick-claim chips, autonomous exoneration banner, Cockpit A2A dossier, and 66/66 green Vitest tests (PR #38).
- Implemented POC v2 Slice 4: Full E2E integration test suite verifying autonomous exoneration & A2A human adjudication flows (5/5 tests), plus comprehensive manual QA runbook in [`docs/testing/MANUAL_TEST_POC_V2.md`](../testing/MANUAL_TEST_POC_V2.md) (PR #39).
- Consolidated POC v2 into MVP v1 release branch `feat/poc-v2-mvp-v1` from `mvp/v1`; implemented full happy and error path handling via TDD (37/37 backend, 72/72 frontend, 245/245 full suite green); built the Mobile Driver Care Portal (`/driver`), and deployed the live standalone Driver Mobile Webapp to [https://p-063-driver.vercel.app](https://p-063-driver.vercel.app).
- Authored [`ADR-009`](../architecture/adr-009-poc-v2-precedent-workflow-mining-and-jev-similarity.md) and expanded [`POC_DESIGN.md`](../architecture/POC_DESIGN.md) (Section 8) for Precedent Workflow Mining & TypeSafe Jev Similarity Engine.
- Designed and applied database migration `20260926220000_poc_v2_precedent_workflows_and_trace.sql` creating `app.precedent_workflows` table, `workflow_trace` JSONB column in `app.fraud_cases`, and seeded 5 canonical historical precedent workflows.
- Implemented `JevPrecedentService` consuming TypeSafe Jev decision model (`~typesafe/jev-latest` on OpenRouter `/api/alpha/decisions`), providing calibrated similarity scores, matching factors, and 1-click procedure adoption.
- Extended Cockpit View with Precedent Match card (`🎯 Jev AI Precedent Match`), 1-click "Áp dụng quy trình án lệ" pre-filling adjudication rationale, and post-adjudication Workflow Trace synthesis.
- Added comprehensive test suites across unit, API, UI, and E2E layers (50/50 backend tests green, 75/75 Vitest tests green).
- Implemented modular, non-blocking UI loading skeleton library across triage queue, dossier detail, agent chat stream, and analytics views to prevent screen freeze during async data resolution.

### Roadblocks & Solutions
| Challenge | Applied Solution | Outcome |
|---|---|---|
| Browser automation cannot use production auth/data safely | Kept browser coverage on test-only network fixtures and did not present it as production evidence | Five local Playwright flows pass; hosted behavior remains unverified |
| The API suite's local database lacks two additive migrations | Recorded the 23 passed / 2 skipped result and kept migration-backed verification scoped to an applied schema | Focused repository checks are useful; the full API gate is incomplete locally |
| `bash scripts/check.sh` fails in Mypy: NumPy stubs use unsupported `type` syntax under Python 3.11, while Python 3.12 exposes existing source typing errors | Preserved the exact failure boundary instead of treating the gate as green | Full check script remains unresolved |
| Preview credentials and endpoints are unavailable in this workspace | Kept deployment verification conditional on repository configuration and recorded the blocker explicitly | YAML, compose, focused tests, and diff checks can run locally; hosted deployment remains unverified |
| The isolated full-suite run has no database fixture rows for legacy database-tools tests | Kept the full-suite attempt separate from tests that could mutate the shared local database | Focused map/route regression tests passed; the DB-dependent suite still needs an isolated seeded test database |
| `~typesafe/jev-latest` on OpenRouter rejects standard `/chat/completions` endpoint with 400 error | Invoked dedicated `https://openrouter.ai/api/alpha/decisions` endpoint with structured state criteria | Calibrated similarity confidence returned in ~1s |
| PostgreSQL `app.adjudications` table enforces strict append-only via `reject_mutation()` trigger | Isolated E2E test runs with dynamic UUIDs and avoided mutating existing adjudication records | Clean, deterministic E2E adjudication without prerequisite state errors |

### Key Learnings
1. A preview must use a separate Railway project, environment, service, URL, and token before CI can safely deploy source from a pull request.
2. Fork pull requests require validation-only behavior because secrets are withheld.
3. Synthetic seed data can support deterministic development only when it remains explicit, varied, and separate from claims about production data quality.
4. A focused green test set does not make an incomplete migration-backed API suite or failed Mypy gate green.
5. OpenRouter decision models (`~typesafe/jev-latest`) require the specialized `/api/alpha/decisions` schema rather than standard chat completions.
6. Append-only PostgreSQL audit trails prevent test pollution and require synthetic case generation in integration test suites.

### Next Week Plan
- [ ] Configure isolated preview resources and run one internal pull request smoke check.
- [ ] Run browser automation against the deployed revision with real auth and API data.
- [ ] Record actual endpoint results before changing Deliverable 5 from staged.

| Sprint | Period | Theme | Status | Detailed Deep-Dive |
|---|---|---|---|---|
| Week 1 | 2026-09-07 - 2026-09-13 | Project Onboarding & Multi-Agent Architecture Setup | ✅ Completed | [`week-01.md`](docs/journal/week-01.md) |
| Week 2 | 2026-09-14 - 2026-09-20 | Data Scout / EDA Subagents, Hugging Face Skills & PR Templates | ✅ Completed | — |
| Week 3 | 2026-09-21 - 2026-09-27 | Dynamic Jev Skill Selector & Token Optimization Hooks | 🔄 In Progress | — |

---

## Week 3: MiPo GPS evidence review

- Completed the [MiPo trajectory EDA](../data/MIPO_EDA.md) and pinned a reproducible 500-trajectory slice for offline route anomaly benchmarking.
- Mapped [PRD use cases and telemetry fields](../data/MIPO_TELEMETRY_MAPPING.md); the analyzed benchmark has no verified geographic transform, timestamps, or platform context, so it cannot establish induced cancellation or GPS spoofing.
- Preserved unknown GPS accuracy as `null` in the event contract and documented additional evidence required for [fraud adjudication](../data/MIPO_FRAUD_RESEARCH.md).
- Authored and installed research skills suite (`literature-search`, `github-research`, `paper-to-code`, `literature-review`, `experiment-design`, `benchmark-runner`, `research-report`) with template scaffolding and `benchmark-worker` subagent on `gemini-3.8-flash`; synchronized across OpenCode, Codex, and Claude harnesses.
- Next: acquire original Porto WGS84 data or a verified transform, then test prefix-only scoring against adjudicated operational outcomes before using model scores in live decisions.

---

## Week 1: 2026-09-07 - 2026-09-13

### Objectives
- [x] Analyze starter repository architecture and requirements.
- [x] Configure cross-agent development environment (Antigravity CLI, OpenCode, Claude Code, OpenAI Codex).
- [x] Establish automated AI logging pipelines for team grading compliance.
- [x] Configure Model Context Protocol (MCP) integrations (Context7, MarkitDown, Mnemoverse).
- [x] Convert local guidelines into reusable agent skills ([`.agents/skills/`](.agents/skills/)).
- [ ] Implement custom LangGraph agent nodes and tools.

### Completed Work
- Preserved pristine initial repository state on branch [`initial-forked`](.).
- Implemented robust multi-environment AI logging in [`scripts/log_antigravity.py`](scripts/log_antigravity.py) and [`scripts/log_hook.py`](scripts/log_hook.py).
- Automated harness synchronization across `.agents`, `.opencode`, `.claude`, `.codex`, `.cursor` via [`scripts/sync_agent_harness.py`](scripts/sync_agent_harness.py).
- Installed and authored 8 skills conforming to open agent standards in [`.agents/skills/`](.agents/skills/).
- Completed comprehensive architecture documentation in [`docs/architecture/ARCHITECTURE.md`](docs/architecture/ARCHITECTURE.md).

### Roadblocks & Solutions

| Challenge | Applied Solution | Outcome |
|---|---|---|
| Antigravity CLI brain folder was not detected by default scanner | Added `~/.gemini/antigravity-cli/brain` to `BRAIN_CANDIDATES` in [`scripts/log_antigravity.py`](scripts/log_antigravity.py) | Full auto-discovery and pre-push prompt sweeping restored |
| OpenCode lacked hook configuration in starter template | Implemented [`.opencode/plugins/ai-log.js`](.opencode/plugins/ai-log.js) connecting `chat.message` to `log_hook.py --tool=opencode` | Prompts logged seamlessly from OpenCode sessions |
| Divergent configuration files across AI tools | Created single source of truth in `.agents/` with automated symlink synchronizer ([`scripts/sync_agent_harness.py`](scripts/sync_agent_harness.py)) | Zero manual config duplication |

### Key Learnings
1. Modular skills with progressive disclosure save significant context tokens compared to injecting huge system manuals.
2. Direct MCP integration with Mnemoverse allows agents to preserve cross-turn memory without custom database glue code.

### Next Week Plan
- [x] Integrate dynamic Jev skill selector across all 4 AI harnesses.
- [ ] Implement core agent tools in [`src/agents/tools/`](src/agents/tools/).
- [ ] Construct multi-node state graph with conditional routing in [`src/agents/graph.py`](src/agents/graph.py).
- [ ] Add unit tests for all state transitions in [`tests/`](tests/).

---

## Week 3: 2026-09-21 - 2026-09-27

### 2026-09-24 — Chat UI event contract

**Contributor:** Bùi Thị Ngọc Trân. **Time:** 2 hours for this task, separate from earlier work; see the [daily worklog](../worklog/2026-09-24.md).

#### Objectives
- [x] Standardize events and data for thinking, tools, driver linking, routes, case lists, and timestamps.
- [x] Prepare a v1 JSON Schema and sample payloads for at least four renderers.
- [ ] Obtain Lead acceptance and implement runtime integration.

#### Completed Work
- Delivered the [contract guide](../CHAT_UI_EVENT_CONTRACT.md), [strict JSON Schema](../CHAT_UI_EVENT.schema.json), and [17 sample events](../CHAT_UI_EVENT_SAMPLES.json) covering five requested renderers, success, tool failure, and empty results.
- Added an [offline validator](../../eval/validate_chat_ui_events.py) and [seven passing tests](../../tests/test_chat_ui_contract.py) for shapes, timestamp validity, tool pairing, sequencing, route references, and terminal ordering. Ruff lint and formatting checks pass.

#### Roadblocks & Solutions
| Challenge | Applied Solution | Outcome |
|---|---|---|
| Existing SSE and final structured responses use different contracts | Documented explicit mappings, opt-in version negotiation, and legacy renderer limitations | Implementation-ready handoff; runtime adapters remain pending |
| Local JSON Schema tooling did not reject an impossible calendar date | Added an explicit date-time format checker | Invalid-date rejection test passes |
| Unrelated edits existed in the original workspace | Copied only the five deliverable files into a clean worktree from main | Task changes are isolated on feat/chat-ui-event-contract |

#### Key Learnings
1. Schema validation alone cannot guarantee tool pairing, sequence continuity, or terminal-state consistency.
2. Thinking indicators should expose progress labels, not private model reasoning.
3. A validated contract does not mean the UI or backend already implements it.

#### Next Week Plan
- [ ] Obtain Lead review of event names, timestamp semantics, pagination, and navigation.
- [ ] Implement backend emission and frontend dispatch without losing legacy citation/history/forensic behavior.
- [ ] Add renderer and transport tests and run CI before rollout.


### 2026-09-24 — Guardrail test isolation follow-up

**Contributor:** Bùi Thị Ngọc Trân. **Time:** 1 additional hour; see the [daily worklog](../worklog/2026-09-24.md).

#### Objectives
- [x] Make guardrail API contract checks independent of shared database and Redis state.
- [ ] Complete follow-up PR review and CI verification.

#### Completed Work
- Replaced destructive reset logic in [test_poc_api.py](../../tests/test_api/test_poc_api.py) with a private service, case, analyst, and dependency overrides restored by monkeypatch.
- Verified WARN, FINE, and SUSPEND are blocked without changing case status or version; DISMISS succeeds. Three targeted tests, Ruff lint, formatting, and whitespace checks pass.

#### Roadblocks & Solutions
| Challenge | Applied Solution | Outcome |
|---|---|---|
| [Post-merge CI](https://github.com/AI20K-Build-Phase-Cohort-4/P-063/actions/runs/35983136219) returned 409 before the expected guardrail response | Isolated the in-memory API contract and included response bodies in assertion failures | Three targeted tests pass; original database conflict remains undiagnosed |
| Reset helper deleted adjudications and disabled an append-only trigger | Removed the helper and supplied private test state | This test no longer requires destructive database cleanup |

#### Key Learnings
1. Passing an isolated API contract test does not prove the PostgreSQL path is correct.
2. Review ownership and version checks can reject a request before guardrail enforcement.

#### Next Week Plan
- [ ] Obtain review and CI results for the isolation change.
- [ ] Cover the PostgreSQL guardrail path in a dedicated disposable integration environment and diagnose the original conflict.
- [ ] Update issue #23 with verified results and remaining limitations.


### Issue #23 — Forensic reasoning baseline

**Contributor:** Bùi Thị Ngọc Trân. **Reported work date:** 2026-09-23. **Time:** 1 hour total, recorded in the [daily worklog](../worklog/2026-09-23.md#2026-09-23--bùi-thị-ngọc-trân).

#### Objectives
- [x] Produce at least three synthetic cases and reproducible forensic JSON outputs for evaluation evidence.
- [x] Save the baseline benchmark and document its limitations.
- [ ] Complete repository verification and PR review for [issue #23](https://github.com/AI20K-Build-Phase-Cohort-4/P-063/issues/23).

#### Completed Work
- Added the [rule baseline](../../src/agents/forensic_baseline.py), [strict output contract](../../src/models/forensic.py), [ten mock cases](../../eval/golden_set/forensic_mock_cases.json), and [usage guide](../REASONING_BASELINE.md).
- Saved [benchmark results](../../eval/results/reasoning_baseline.json): all four metrics are 1.0 on synthetic development cases. Three [contract tests](../../tests/test_agents/test_forensic_baseline.py) pass. These results support the evaluation deliverable, not a production accuracy claim.

#### Roadblocks & Solutions
| Challenge | Applied Solution | Outcome |
|---|---|---|
| CRLF shell scripts and WSL could not use Windows virtual-environment tools | Converted local shell scripts to LF and ran checks through Windows Python | Ruff lint and formatting checks pass |
| Baseline category inferred as unrestricted string | Shared an explicit category type between the model and rule function | Targeted Mypy checks pass for both baseline files |
| Full Mypy run reported errors outside the baseline | Recorded the remaining 51 reported errors separately | Repository type checking remains unresolved |
| Full tests stalled opening a database connection | Interrupted the run and inspected fixtures; no database mock was provided | Two tests passed before interruption; full-suite verification remains blocked |

#### Key Learnings
1. Synthetic benchmark correctness and isolated contract checks do not establish full integration readiness or calibrated confidence.
2. Database tests need an isolated test environment; one existing test changes driver status.

#### Next Week Plan
- [ ] Resolve or track repository type errors and provide an isolated database test environment.
- [ ] Rerun required checks, link worklog and journal in the PR, and obtain review.
- [ ] Evaluate independently labeled, unseen cases before making broader accuracy claims.

### Objectives
- [x] Configure and test in-project Jev skill selector hooks for OpenAI Codex, Claude Code, and Antigravity.
- [x] Standardize token optimization skills (`caveman`, `rtk`, `headroom`) as normal discoverable skills in `.agents/skills/`.
- [x] Implement RTK and Headroom post-tool invocation hooks across Antigravity (`PostToolUse`), Claude Code (`PostToolUse`), and OpenCode (`tool.execute.after`).
- [x] Validate user prompt propagation and tool selection via automated test suite.
- [x] Implement complete multi-tab GreenSM terms and policies crawler, recursive chunker, Chroma vector store, and PolicyRAGAgent.
- [x] Migrate vector database from ChromaDB to Qdrant Cloud and Docker Compose (`QdrantPolicyStore`), ingesting 388 policy chunks with ~617ms latency.
- [x] Author ADR-007 documenting Qdrant migration rationale, dual-backend deployment, and telemetry integration.
- [x] Execute 30-testcase golden benchmark with Gemini 3.5 Flash Lite, tool calling validation, and LLM-as-a-Judge.
- [x] Design and formalize multi-agent subagent delegation architecture ([`ADR-003`](file:///docs/architecture/adr-003-subagent-delegation-architecture.md)) with 2026 frontier model tiering.
- [x] Synchronize harness configurations across Antigravity, OpenCode, Claude Code, and Codex via [`scripts/sync_agent_harness.py`](file:///scripts/sync_agent_harness.py).
- [x] Implement Next.js + React webapp cockpit prototype with Clerk authentication, Tailwind CSS v4, and schema-compliant telemetry/domain models.
- [x] Design and implement PoC HTTP API (10 endpoints) with Supabase PostgREST and PostgreSQL `app` schema integration via TDD.

### Completed Work
- Implemented in-project [`scripts/jev_hook.ts`](file:///scripts/jev_hook.ts) and [`scripts/jev_codex_selector.ts`](file:///scripts/jev_codex_selector.ts) with full prompt extraction.
- Configured RTK/Headroom post-tool invocation hooks in [`scripts/rtk_post_tool_hook.ts`](file:///scripts/rtk_post_tool_hook.ts) and [`.opencode/plugin/jev-skill-selector.ts`](file:///.opencode/plugin/jev-skill-selector.ts).
- Established automated verification suite [`scripts/test_hooks.ts`](file:///scripts/test_hooks.ts) with 16 passing assertions.
- Authored [`ADR-003`](file:///docs/architecture/adr-003-subagent-delegation-architecture.md) establishing 7 specialized subagents with strict model tiering (Cheap: Gemini 3.8 Flash, Haiku 4.5, GPT-5.6 Luna; Reasoning: Pro, Sonnet 5, GPT-6 Astra).
- Extended [`scripts/sync_agent_harness.py`](file:///scripts/sync_agent_harness.py) to generate native subagents for Claude Code (`.claude/agents/`), Codex (`.codex/config.toml`), and OpenCode (`.opencode/opencode.json`).
- Converted `pr-workflow` from static rule to discoverable skill and set `/caveman ultra` as global baseline across all agents.
- Setup Clerk authentication middleware proxy and header in [`src/webapp`](file:///src/webapp), styled Adjudication Cockpit, Analytics Dashboard, and Analyst Profile views matching [`docs/design`](file:///docs/design), and established a Vitest test suite asserting full schema adherence against [`docs/architecture/schemas`](file:///docs/architecture/schemas).
- Designed complete HTTP API specification in [`docs/architecture/API_SPECIFICATION.md`](file:///docs/architecture/API_SPECIFICATION.md) covering all 10 endpoints, data models, error semantics, SSE contracts, and PostgREST/PostgreSQL schema integration.
- Implemented PoC HTTP API routes in [`src/api/routes.py`](file:///src/api/routes.py), schemas in [`src/models/schemas.py`](file:///src/models/schemas.py), and service tier in [`src/services/case_service.py`](file:///src/services/case_service.py) connecting directly to PostgreSQL `app` schema with fallback.
- Added comprehensive integration test suite [`tests/test_api/test_poc_api.py`](file:///tests/test_api/test_poc_api.py) with 11 tests covering all endpoints, idempotency, guardrails, and SSE streams (33/33 tests passing).
- Configured automated CI/CD workflows for Vercel (Frontend), Supabase (PostGIS & pgvector database migrations & verification), and Railway (Docker Compose FastAPI server & telemetry agent worker) using GitHub Secrets and GitHub Actions with zero reliance on disabled GitHub Apps.
- Resolved Railway production container startup crashes by transitioning Dockerfile to an isolated `/opt/venv` build pattern, and implemented resilient offline hash fallbacks in `src/rag/embedder.py` and `src/rag/store.py` under [PR #13](https://github.com/AI20K-Build-Phase-Cohort-4/P-063/pull/13).
- Added remote API dispatch (`--dispatch-fraud`) to `scripts/simulate_trip_stream.py` to trigger live scenarios on Railway backend directly from local and CI environments.
- Unblocked Vercel map rendering by moving to keyless CartoDB Voyager raster tiles and eliminated blocking API key prompts.
- Built interactive investigation timeline scrubber under map with scrubbing slider, playback, and synchronization of driver position to milestones (Matching -> Anomaly Stalled -> Missingness Gap -> Pickup -> Destination Dropoff).
- Implemented candidate routes analytics (3 top routes) displaying DAVI, SDD, distance to pickup, ETA, signals, and congestion with hover inspection.
- Integrated multi-driver traffic corroboration cross-checking suspect driver excuses against Google Maps traffic mocks and peer fleet speeds.
- Added telemetry data missingness alerts for network dropouts (>30s gaps) and visualized alert banners on map and timeline.
- Resolved MapLibre client mounting glitch and eliminated CARTO 'API key required' watermark by adopting keyless OpenFreeMap vector basemap with smooth loading overlay, OSM raster fallback, and reactive layer toggling.
- Verified test suites across Python backend (76/76 passing), Vitest frontend (42/42 passing), and Playwright E2E (10/10 passing).

### Roadblocks & Solutions

| Challenge | Applied Solution | Outcome |
|---|---|---|
| Antigravity PreInvocation hook payload did not pass prompt directly | Extracted user prompt directly from `transcript.jsonl` via regex `<USER_REQUEST>` | Clean prompt extraction with zero reliance on missing fields |
| Jev selector re-triggered on every tool return in multi-turn loops | Added guard checking `invocationNum > 1` to skip intermediate steps in `0ms` | Eliminated redundant token spend and tool latency |
| Token optimization skills were obscured behind dynamic Jev routing | Moved `caveman`, `rtk`, `headroom` to standard `.agents/skills/` | Permanent discoverability across all agent harnesses |
| Codex rejected `UserPromptSubmit` hook stdout with `invalid user prompt submit JSON output` | Formatted stdout strictly to `user-prompt-submit.command.output` wire schema (`continue: true`, `hookSpecificOutput`), stripping unexpected top-level properties via `toJSON()` | Codex schema validation passes and injects skill context cleanly |
| Antigravity hook failed with exit status 127 `No such file or directory` | Replaced erroneous `cd .. && ` with dynamic repository root resolution `root="$(git rev-parse --show-toplevel 2>/dev/null || pwd)" && cd "$root" && ` in `.agents/hooks.json` | Flawless hook execution regardless of initial working directory |
| Railway deployment failed with `uvicorn: Permission denied` | Switched container virtual environment to `/opt/venv` with non-root ownership | Railway container builds and runs reliably in production |
| RAG initialization threw when `GEMINI_API_KEY` was unset | Implemented SHA-256 hash pseudo-embeddings and EphemeralClient fallback in Chroma store | 100% test passing (70/70) and zero crashes in offline/fallback environments |
| CARTO basemap tiles displayed 'API KEY REQUIRED' watermark and initial render glitched with fake SVG paths | Migrated default basemap to keyless OpenFreeMap Liberty vector tiles, added smooth loading overlay, and evaluated WebGL support synchronously | Crisp, keyless basemap rendering without watermarks or initial mounting path glitches |
| PostgreSQL prepared statement threw `IndeterminateDatatype: could not determine data type of parameter` on parameterized NULL check | Formatted dynamic SQL WHERE clauses instead of raw untyped `(%s IS NULL OR ...)` expressions | Database queries succeed reliably across both populated and null organization filters |
| MapLibre GIS rendered 3 disconnected points on screen due to missing or nested GeoJSON route snapshots | Resolved nested `route.coordinates`, added OSRM shortest path calculation from driver initial location to pickup and pickup to destination | Seamless route visualization connecting origin, customer pickup, and destination |
| Redis queue events required durable processing, DLQ retries, and least-loaded analyst dispatch | Built Upstash Redis REST queue with atomic LMOVE, deadletter retries, and `FOR UPDATE SKIP LOCKED` analyst workload balancing | 100% reliable telemetry ingestion and automatic case assignment |

### Key Learnings
1. Post-tool invocation hooks (`tool.execute.after` and `PostToolUse`) are essential to prevent model fluff and prune oversized outputs before they consume critical context headroom.
2. Including the exact user request inside the injected context allows the model to verify why a particular skill was routed.
3. OpenAI Codex enforces strict `additionalProperties: false` on `user-prompt-submit.command.output` wire JSON; CLI hooks targeting Codex must omit any metadata properties outside the wire contract.
4. PostgreSQL prepared statements cannot infer types for variadic arguments or untyped null checks; dynamic clause generation with typed params is essential.
5. In spatial GIS frontends, always provide fallback vector geometries connecting known waypoints to avoid orphaned markers when route engines are warming up.

## Sprint 2 issue management — 2026-09-30

### Objectives and completed artifacts

Move task tracking into GitHub Issues with feature-sized outcomes and measurable DoD. Prepared [contributor workflow](../../CONTRIBUTING.md), issue templates and issue-linked PR templates. Task definitions and the source-ID mapping live only in GitHub Issues. Publication and review evidence are tracked in the workflow issue.

### Roadblocks and outcomes

Legacy skill referenced an absent Codex template. Both issue skills now use actual repository templates. PR #40 includes automatic exoneration and driver UI while PRD forbids automatic dismissal and defers driver UI. User explicitly selected strict PRD; track the conformance bug and defer expansion rather than silently changing scope.

### Learnings and next steps

Merged code is reusable implementation, not acceptance evidence. Reconcile documents, fix automatic closure through analyst confirmation, then prioritize shared telemetry/evaluation data and core cockpit behavior. Retain distinct fixture/database/deployed evidence and attach it to issue DoD.

### Contributor workflow refinement

The user rejected a parallel Markdown backlog. Removed it and consolidated process guidance in [CONTRIBUTING.md](../../CONTRIBUTING.md). Feature, User Story and Task templates now distinguish separately accepted outcomes without requiring three levels for every change. Native dependencies are hard gates: all prerequisites must be completed and accepted before dependent implementation starts. Next step is review of [PR #75](https://github.com/AI20K-Build-Phase-Cohort-4/P-063/pull/75); no runtime behavior is changed by this work.

## Issue #63 playback review — 2026-10-01

**Objective and artifacts:** Complete the road dataset review by repairing continuous map playback and semantic checkpoints in [PR #82](https://github.com/AI20K-Build-Phase-Cohort-4/P-063/pull/82). [Playback helper](../../src/webapp/lib/telemetry-playback.ts), [icons](../../src/webapp/components/map/checkpoint-icon.tsx), regressions and [verification evidence](../testing/ISSUE_63_VERIFICATION.md) now cover between-fix movement as well as sampled endpoints.

**Roadblocks and solutions:** Nearest-sample selection leaked future positions, implicit time scaling accelerated long trips, and competing camera fits caused recentering. Elapsed 1× playback, leg-specific road estimates and one source-backed camera fit resolve those defects. GPS gaps remain unavailable intervals with visible recorded fixes. Actual motorbike metadata exposed a missing normalization alias, which was added explicitly. Stitch was unavailable and two workers reached a usage limit; local preview and conductor integration are recorded honestly. The existing repository Mypy/NumPy target mismatch remains disclosed.

**Learning and next steps:** Endpoint scrubbing cannot prove continuous motion. Measure frame displacement, road alignment, camera stability and missing intervals independently. Keep display interpolation separate from observed GPS. Submit expanded issue DoD and current PR checks for review; merge and hosted authentication acceptance remain separate.


## Week 4: Strict Phase 1 scope reconciliation (2026-10-02)

### Objectives and completed artifacts

[Issue 72](https://github.com/AI20K-Build-Phase-Cohort-4/P-063/issues/72) reconciles the approved analyst release boundary with inherited driver-agent expansion. Pham Dat (@datamonsterr), assisted by bounded workers and Codex reviewers, preserves analyst confirmation and written rationale for dismissals and adverse sanctions, defers driver mobile expansion, and distinguishes strict benchmark concordance from raw per-case confidence. The [daily worklog](../worklog/2026-10-02.md) attributes the work and observed verification. Delivery and final CI acceptance remain pending at this checkpoint.

### Roadblocks, solutions and observed outcomes

Jev's AGY account mounts encounter self-referential configuration symlinks; Codex resumes the tasks in their original worktrees. A direct read-only AGY review times out. Worker Git/network restrictions require root delivery, with no credential or global profile changes. Independent review catches the missing warning lockout and dismissal rationale in the core use case, followed by three bad traceability anchors. Those document defects are corrected; scoped regression and heading-link protection remain under review. Local documentation contracts pass 20 BA and 28 architecture checks, and existing focused fixtures pass 18 driver plus 33 guardrail/workspace tests. These results do not establish runtime #73 compliance, benchmark performance, isolated-database or hosted evidence.

### Key learnings and next steps

Approved product scope must be separate from inherited runtime and historical decisions. Global-word checks can miss a contradictory core use case; documentation contracts need scoped assertions and valid heading targets. The next steps are accepted child corrections, integration, current-head CI and Phoenix feedback, followed by @datamonsterr review. No production merge is part of this checkpoint.


### Integrated proof update — issue 72

The review follow-up closes the core use-case and heading-link regression gaps: 32 BA plus 28 architecture documentation contracts pass, with original use-case and invalid-anchor RED probes followed by restored-document GREEN. Both reviewed worker PRs merge into the delivery branch and their bounded child issues are accepted. A separate merge worktree preserves the newly merged PR #57 forensic-brief behavior alongside the strict analyst authority rule; all 60 documentation checks pass after integration. The [manual scope review](../testing/manual/PHASE1_SCOPE_REVIEW.md) and [daily evidence update](../worklog/2026-10-02.md#integrated-documentation-proof-and-ci-handoff) retain the exact proof boundary. Final CI and Phoenix feedback are the next gate; runtime dismissal remediation and production acceptance are separate.


### Full-layer DoD evidence — issue 72

The [verification record](../testing/ISSUE_72_VERIFICATION.md) separates documentation acceptance from broader layers and environmental limits. At the `51c5a73` checkpoint CI passes backend, migrated database integration, agent regressions, browser E2E and Docker/Next builds; isolated local frontend checks pass Vitest, TypeScript and seven browser specs. A final audit removes unqualified active priorities from deferred story/use-case metadata with 13 RED regressions and 78 passing documentation contracts. Phoenix prose fragility is corrected without weakening policy or provenance. Global local ESLint and the NumPy/Mypy target mismatch remain disclosed, and local build pipe behavior is distinguished from the passing CI build. The final PR remains the product-owner review artifact; no runtime or production acceptance is inferred.


## Issue #60 agent runtime planning — 2026-10-01

**Objectives and artifacts:** Prepare an AGY TDD handoff for the existing analyst and driver tool runtime. Delivered [source analysis, interface decisions and RED recipes](../superpowers/plans/2026-10-01-issue-60-tool-runtime.md) and a [45-file scoped architecture graph](../architecture/issue-60-knowledge-graph.json); the authoritative task graph is on [issue #60](https://github.com/AI20K-Build-Phase-Cohort-4/P-063/issues/60). Runtime implementation remains separate.

**Roadblocks and solutions:** The actual cockpit uses an independent Gemini/ReAct executor, so changing only the analyst LangGraph would miss its tool calls. Current driver auth and model tools can bypass trusted scope; provider fallbacks can invent evidence; current streams do not pair every invocation or persist recoverable terminal state. The design reuses explicit shared services and a negotiated event extension while retaining both agents and existing citations/history. Automatic dismissal is tracked by #73, and broad ADR reconciliation by #72; their acceptance is not inferred.

**Observed outcome:** Native #63 dependency is completed and accepted. Sixteen focused tests and seven subtests pass on the isolated merged baseline, and existing event fixtures validate. Those fixture checks include obsolete autonomy expectations and are not acceptance of the new runtime. No hosted staging or new database implementation was exercised. Contributor attribution and untracked-time disclosure are recorded in the [daily worklog](../worklog/2026-10-01.md).

**Learning and next steps:** Agent state and prompt IDs are not authorization. Tool starts must occur at real invocation boundaries; durable command identity precedes write retries. AGY workers receive bounded ownership and behavioral RED/GREEN instructions. Final integration requires real database denial/outage/duplicate-write evidence and an authenticated staging smoke tied to the deployed commit.


### Business capability discovery follow-up

The runtime plan needed a business-facing capability map. [The catalog](../ba/AGENT_TOOL_CATALOG.md) now connects analyst/driver/operations tools to ERR-code coverage and records the user's confirmed final-minutes/approval/conversation-delivery requirements, reusable interactive questions and initial case context. Existing `evidence_snapshots.dossier` offers a versioned JSONB foundation; current choice widgets offer presentation reuse, not answer persistence.

Taxonomy drift in driver labels and analyst prompts risks sending the wrong explanation, so canonical code mapping precedes generated notices. Final minutes follow an already recorded human decision and preserve its evidence/map revision. Next step is review of proposed tool scope and integration of new product outcomes into implementation tickets; the previous eight runtime slices do not silently acquire a new notification workflow. No production code or data changed.

## Issue #64 evaluation corpus — 2026-10-02

### Objectives and completed artifacts

Build one versioned evaluation index across RAG, tools, classification, forensic briefs and driver/A2A flows. [`eval-v1`](../../eval/corpus/v1/README.md) now contains 53 records, including the PRD 30-case protocol as held-out data and separate ERR-01 through ERR-05 taxonomy coverage. A JSON Schema, semantic validator, deterministic generator, error analyzer and five contract tests enforce provenance, label isolation and split boundaries.

### Roadblocks and solutions

| Challenge | Applied solution | Outcome |
|---|---|---|
| Existing evaluation data used incompatible shapes and mixed development smoke tests with implied gold labels | Added a shared metadata contract that references existing fixtures rather than copying runtime evidence | Stable IDs and source versions cover all required suites without duplicating telemetry |
| Legacy driver fixture expected `AUTO_DISMISS`, conflicting with strict PRD FR-03 | Made PRD authoritative, expected analyst-confirmed dismissal and recorded the old label as a case-addressable inventory failure | Error analysis identifies `driver-a2a-traffic` and suggests follow-up work without changing runtime scope |
| Local Python 3.11 environment was unavailable after Windows reset | Used Python 3.14 with workspace-local temporary dependencies for contract verification | Five tests, schema validation and scoped Ruff checks pass; no database or hosted result is inferred |

### Key learnings and next steps

Versioning data alone does not create a trustworthy gold set. Each label needs provenance, allowed uncertainty, split isolation and accountable review. Missing executions must remain `not_run`; they are not accuracy failures or successes. Next: obtain SME approval, execute the held-out 30-case protocol with three reviewers, publish a PR with `Refs #64`, and attach isolated/hosted evidence before issue closure.
## Authentication incident — 2026-10-02

**Objective and completed artifacts:** Diagnose valid logged-in sessions receiving
401, identify the introducing changes, and prepare a tested hotfix. Delivered an
[explicit origin configuration helper](../../scripts/auth_config.py), deployment
configuration gates, genuine signed-token/API contracts, a real Clerk browser
suite, and the [manual verification report](../testing/MANUAL_TEST_AUTH_HOTFIX_104.md).
Attribution and measured-time boundaries are in the [daily worklog](../worklog/2026-10-02.md).

**Roadblocks and solutions:** A server-issued token without `azp` succeeded while
browser tokens failed. Production retained old Railway origins; the actual dev
alias was absent from defaults. Comparing identical signed claims across the
parent and `16c1ad6` established causality. Deployment configuration now declares
exact first-party origins instead of restoring the permissive Vercel fallback.
Clerk organization selection was required for the dedicated QA identity, and
real tests now support that organization explicitly. A driver fixture omitted a
required subject; its corrected fixture passes against real PostgreSQL.

**Observed outcomes and next steps:** Full isolated backend tests passed 594 with
8 skips; frontend tests passed 126; fixture UI E2E passed 9. Two real-login flows
and a persisted manual claim/dismiss flow passed with production authentication
enabled. The NumPy/Mypy target mismatch remains disclosed. Review the hotfix PR,
perform an authorized environment rollout, and record hosted login acceptance
before closing the parent incident. A healthy unauthenticated `/health` response
and fixture E2E cannot substitute for a signed browser session with `azp`.

**Resumed verification — 2026-10-03:** Rebasing onto `241e161` adds the accepted
documentation contracts; the complete isolated backend suite now passes 677
tests, with eight skips and 14 passing subtests. The four CI jobs pass on retry.
A scoped 90-second deadline accommodates the five-turn browser conversation;
the complete local browser suite passes nine tests in 33.8 seconds without
changing its assertions. Review also catches premature preview success after a
detached authorization redeploy. The preview now requires its submitted Railway
deployment to reach `SUCCESS` and pass health before publishing success.
Vercel credential validation and final-head CI are the remaining preview gates
on [PR #108](https://github.com/AI20K-Build-Phase-Cohort-4/P-063/pull/108).

Six behavioral CLI contracts now protect that preview boundary, including an
observed failing-first missing-environment regression and rejection of an
unrelated successful deployment. The restricted CI credential works for project
pull/build/deployment while personal `whoami` is unavailable; local login and CI
credential scope must be verified through their appropriate interfaces.

The complete isolated suite reaches 683 passing tests on `63103ff`, and that
checkpoint passes all CI and preview checks when provisioning precedes
authorization. Exact deployment tracking exposes a remaining race between the
two preview workflows. The frontend now waits for successful provisioning of
the same PR and commit before changing origins; four new ordering contracts
pass alongside the existing contracts, totaling 42 focused checks. Final-head
CI verifies the automatic ordering before review and gated hosted acceptance.

The full ordering-head suite passes 687 tests. A runner without `gh` exposes the
metadata reader's final environmental assumption; authenticated runner-token
REST now supports that runner while preserving exact PR/head matching and
refusing anonymous access. Two failing-first transport contracts bring focused
proof to 44 passing checks. Hosted production remains a separate gated release.
 ### Provider transport — 2026-10-02

 The user requested independently reviewable implementation from `main` for issue #88. Bounded workers followed test-first changes and source/quality reviews; the conductor verified complete commands and keeps local, SDK-mocked, service-backed, browser and live/hosted proof separate. Technical decisions and test instructions are documented beside the implementation; GitHub remains the task/acceptance source. Existing global type-checking debt and unavailable live credentials are disclosed rather than hidden. The next external step is current-head PR review and authorized merge.
 Provider acceptance review caught a direct RAG constructor converting an absent client into a truthy adapter, bypassing the source-text fallback. The smallest fix preserves absent-client state; fifteen provider/credential regressions retain the existing retrieved-content behavior. SDK-factory tests alone did not establish the direct caller fallback, so the final proof includes caller-level contracts.

## 2026-10-03 — Sprint 2 Phase 1 benchmark (#69)

### Objectives and delivered artifacts

Deliver the missing Phase 1 analyst benchmark runner and a measured copilot bottleneck improvement while preserving strict guardrail and human authorization constraints. [Benchmark report](../testing/ISSUE_69_BENCHMARK.md) maps each DoD item and distinguishes local contracts from pending human/staging acceptance. [Worklog](../worklog/2026-10-03.md) attributes the work to Trân (@trantran2929), assisted by Codex.

### Roadblocks and solutions

Prerequisites #64 and #68 remain open. The user explicitly authorized proceeding on 2026-10-03; prerequisite acceptance is not inferred. PR #112 is already merged and its existing tracing implementation is reused. No staging target or independent reviewer measurements were supplied; the user selected runner and PR delivery. Acceptance remains pending and the PR references #69 without closing it.

The Jev CLI is unavailable in this Windows environment. Relevant project rules and testing/PR skills were read directly. Implementation and checks use an isolated managed worktree; the original checkout's unrelated edits are preserved.

### Learnings and next steps

API response latency and local CPU timings do not measure analyst MTTR. Current PRD requires 28/30 matching decisions for each of three reviewers, complete 90-decision coverage, a cohort mean below 45 seconds, and zero safety violations. Next: accept the versioned corpus and tracing DoD, collect baseline/candidate reviewer and staging observations, then evaluate the strict acceptance gate without replacing unknown metrics with fixture success.

### PR #114 CI portability follow-up

Hosted Unit Tests exposed a Git-history assumption in the new policy regression tests: all seven failures used a baseline object absent from shallow checkout; 713 other tests passed. The default baseline is now a versioned, frozen original method with source/AST provenance, so tests remain active without history or network access. Custom refs still fail explicitly. Local regression and typing proof is in the [benchmark report](../testing/ISSUE_69_BENCHMARK.md#pr-114-ci-portability-correction); the next step is hosted CI confirmation, while human acceptance remains pending.
## Week 5: Durable solved-case provenance (2026-10-03)

### Objectives

- [x] Replace fabricated/in-memory precedent publication with a traceable solved-case model.
- [x] Preserve analyst authority and make similarity explicitly non-adjudicative.
- [ ] Observe rollback, reload, immutability and tenant isolation on an isolated migrated database.

### Completed work

[Issue 66](https://github.com/AI20K-Build-Phase-Cohort-4/P-063/issues/66) now has an FK-backed, append-only solved-case context and reuse-history design. The [verification record](../testing/ISSUE_66_VERIFICATION.md) maps assignment, driver submission/conversation, evidence, policy, signed decision, tool provenance and retrieval history to implementation and tests. Legacy PR #40 rows remain readable but cannot become authoritative or reuse-eligible.

### Roadblocks and solutions

| Challenge | Applied solution | Outcome |
|---|---|---|
| Windows Store `python.exe` alias had no runtime | Installed `mise`, Python 3.11, `uv` and `rtk`; synced `uv.lock` into ignored `.venv` | Focused tests and static checks run locally |
| Existing fixtures invented policy/tool facts and allowed RAM publication | Trace only persisted sources; require tenant, database and signing analyst; mark fixtures legacy/read-only | 24 focused tests pass without external backend or provider keys |
| Docker engine cannot start | Diagnosed Docker log: Virtual Machine Platform/virtualization unavailable; retained a CI/isolated-DB integration test and disclosed the missing local result | No false database or hosted acceptance claim |

### Key learnings and next steps

Durability is more than serializing a workflow JSON blob: authority comes from immutable links to the exact evidence, policy and human decision. Driver submissions and analyst-agent chat have different actors and must not be conflated. Next steps are enabling virtualization/rebooting or using CI for migrated-DB proof, reviewing the exact-head check results, and only then deciding whether full issue closure is justified.


## Week of 2026-10-05 — Active triage and history

**Objectives:** Remove finalized cases from active triage while preserving authorized history; retain nonterminal work and avoid lifecycle expansion.

**Completed artifacts:** [Service and browser verification](../testing/ISSUE_143_QUEUE_VERIFICATION.md) and [ADR-019](../architecture/adr-019-active-triage-history.md) accompany the queue predicate and committed-decision refresh correction.

**Roadblocks and solutions:** Filtering must precede pagination; the shared service predicate now governs count and rows. Detail-fetch failure previously suppressed queue refresh; refresh now follows the committed action directly. The existing audit path has no new-event writer, so preserved historical audit fixtures are labeled honestly. The shared mypy environment fails on a NumPy Python-target mismatch; focused tests provide bounded evidence while baseline repair proceeds separately.

**Key learnings and next steps:** UI success, persisted state, audit creation, and authenticated hosted proof are distinct acceptance conditions. Complete hosted two-session evidence and independent audit acceptance before closing #143; keep #147 lifecycle expansion separate.

## Week 4: Tester architecture follow-up — 2026-10-04

### Objectives

Extend the Tester discovery into reviewable API, module, component and test contracts using existing architecture, with literal `/test` paths and a map-first workspace.

### Completed artifacts

[Architecture](../architecture/TESTER_SIMULATION_ARCHITECTURE.md), [API design](../architecture/TESTER_API_SPECIFICATION.md), [isolation ADR](../architecture/adr-015-isolated-tester-simulation.md), [UI design/preview](../design/tester-simulation/design.md), [test strategy](../testing/TESTER_SIMULATION_TEST_STRATEGY.md) and [manual/UAT runbook](../testing/MANUAL_TEST_TESTER_SIMULATION.md) specify the future implementation. [Worklog](../worklog/WORKLOG.md#2026-10-04--tester-architecture-and-interface-design) records Pham Thanh Dat’s attribution and evidence limits.

### Roadblocks and solutions

The current Workplace imports a global API client: a new URL alone would not isolate data. The design requires a per-workspace test client and isolated database/queue/vector resources. The checked-in conversational graph does not prove a complete notification/assignment path; the design inventories existing detector seams and requires actual persisted results. Stitch tools are unavailable, so a standalone draft preview records the missing Stitch/visual approval gate. Local BA/architecture documentation contracts passed (83 tests); runtime/browser/provider acceptance remains separate.

### Key learnings and next steps

Existing Workplace means presentation and assignment behavior, not production storage. User-confirmed isolated storage and sandbox delivery make that distinction explicit. The selected one-second sampling baseline still needs representative movement validation. API/component review, Stitch screen generation and visual confirmation precede implementation; current owners, DoDs and hard dependencies remain in GitHub, not in this historical record.

## Week 5: Compact cockpit header and tab joins — 2026-10-08

**Objectives and artifacts:** Remove the repeated assessment row, preserve metadata in the driver header, and connect smaller tabs directly to header/content. The [accepted design](../design/center-header-compact/design.md), [source commit](https://github.com/AI20K-Build-Phase-Cohort-4/P-063/commit/aafc554), [manual evidence](../testing/manual/CENTER_HEADER_TABS.md), and [attributed worklog](../worklog/2026-10-07.md) record the result.

**Roadblocks and outcomes:** The routed worker could not write linked Git metadata or reach GitHub; the conductor preserved its handoff and resumed in the isolated worktree. Icons rendered larger than their utility class implied, and panel padding introduced a second gap. Scoped sizing and junction fixes passed observed RED/GREEN checks. Fresh verification passed 254 unit tests, 22 browser tests with 3 opt-in skips, test TypeScript, and the production build. Independent review found no scoped regressions. Five existing ESLint errors reproduce on base source.

**Learnings and next steps:** Measure rendered joins and font sizes, and wait for detail data rather than queue text. Fixture continuity, hosted authentication, and database acceptance remain separate evidence classes. Complete exact-head PR checks and review in GitHub; merge remains subject to authorization.

## Week 5: First-principles violation-handling reframe — 2026-10-09

**Objectives and artifacts:** Rebuild the analyst/DS/GreenSM/Passenger/Driver jobs and the current violation process from first principles rather than from existing features. The [first-principles report](../ba/FIRST_PRINCIPLES_REPORT.md) records the fact-check, FP-1–FP-15, the settlement reframe, the Sentinel gap analysis, and CI-1–CI-7; the [worklog](../worklog/2026-10-09.md) records attribution.

**Roadblocks and outcomes:** The brainstorm's two absolute claims—full detection and fully-trusted AI summarization—are unsound in principle: e-bike evidence is GPS plus app logs (spoofable) and RAG summarization still hallucinates. The reframe is settlement, not investigation: close a dispute fairly inside each persona's time budget with a written rationale and appeal path. Three real gaps versus Sentinel: no active anti-anchoring, no verified grounding, no controlled funnel/pre-payment. Two P0 issues ([#236](https://github.com/AI20K-Build-Phase-Cohort-4/P-063/issues/236), [#237](https://github.com/AI20K-Build-Phase-Cohort-4/P-063/issues/237)) carry reason, DoD, build notes and before/after cockpit previews.

**Learnings and next steps:** Reward-function design (measuring completed-trip outcomes, not who pressed cancel) is the largest long-term lever and stays out of MVP scope as an A/B hypothesis. Numeric baselines remain unvalidated: real GSM data, current reward function, false-positive driver churn, auto-dismiss thresholds, and live hallucination rates. These are discovery and design artifacts, not runtime or UAT evidence.

## Week 6: Geoapify provider boundary — 2026-10-09

### Objectives

- [x] Implement and document the #227 provider port with OSRM compatibility and Geoapify route options.
- [x] Define server-side secret handling, geometry-gap semantics, and bounded capability-probe evidence.
- [x] Complete local verification and bounded live capability/runtime probes.
- [ ] Obtain PR/CI acceptance and authorized merge for #227.

### Completed Work

The [Geoapify integration boundary](../architecture/GEOAPIFY_INTEGRATION.md) records the selected server proxy architecture, coordinate conversion, typed adapter failures, disjoint `MultiLineString` handling, and stakeholder-approved T0 terms. The [manual runbook](../testing/manual/GEOAPIFY_PROVIDER.md) defines six capped probes and deterministic fixture failures. Work is attributed to Phạm Thanh Sơn (configured Git author), assisted by Codex with bounded agents.

### Roadblocks & Solutions

| Challenge | Applied Solution | Outcome |
|---|---|---|
| Provider failures and malformed vertices could otherwise be hidden at the legacy seam or joined into false geometry. | Keep a typed success/failure union inside adapters, map failure to `None` only at the compatibility seam, and split malformed geometry into disjoint runs. | Local fixture/unit/contract evidence covers the boundary; no straight-line fallback is permitted. |
| Live provider requests could expose credentials or overstate entitlement. | Cap opt-in public Hanoi probes at six sequential requests, sanitize allowlisted summaries, and classify DNS/network failure as blocked. | The authorized conductor host passed six live capabilities and both motorcycle traffic models; account entitlement and hosted acceptance remain unverified. |

Observed local verification: `bash scripts/check.sh` passed with 805 unit tests; focused ASGI/API integration passed 12 tests. Source/fixture review found no blocking defect. The earlier worker sandbox could not publish; the conductor retained its worktree and completed the bounded live verification.

### Key Learnings

1. Provider capability evidence and application acceptance are separate proof classes; a fixture, health check, or blocked live probe does not prove hosted behavior.
2. Preserving geometry gaps at the adapter boundary prevents callers from turning missing provider data into invented route evidence.

### Next Week Plan

- [ ] Review the revision-bound live artifacts and PR checks before authorizing merge.
- [ ] Publish the issue branch and PR, verify the native parent and CI, then update #227 evidence without closing parent issues. Database and hosted browser implementation are outside this slice.

## 2026-10-11 — Benchmark epic close-out (epic #247)

Shipped the 10k benchmark docs index and dataset cards. Key numbers: 10k enriched mix, gates all PASS, heuristic acc 0.7043 / macro-F1 0.5059, guardrail 0 violations.

### Key Learnings

1. Subagent dispatches on `implementer`/`data-analyst` types failed on model availability; falling back to `general` unblocked the benchmark build.
2. MiPo StSt10M tortuosity inverts vs AiSq — excluded from the detour prior; variant-level validation beats family-level trust.
3. ERR-03/ERR-04 heuristic recall is 0 by construction (no derivable signal in `measured_features`); the benchmark measures the gap honestly instead of patching the heuristic.

## 2026-10-12 — Traffic corroboration boundary

**Objective and artifacts:** Ngoc Tran (configured Git author), assisted by Codex,
implemented external traffic tool contracts, scoped execution and force-majeure
guidance; see [daily evidence](../worklog/2026-10-11.md) and
[manual runbook](../testing/manual/TRAFFIC_EVIDENCE.md).

**Roadblock and resolution:** No historical traffic/incident provider is selected.
A normalized, configured HTTPS gateway avoids claiming routing estimates are
observed traffic. Missing sources and provider failures retain explicit unavailable
evidence. Local tests cover the boundary; live capabilities remain unverified.

**Learning and next steps:** Empty incidents do not prove clear roads or intent.
Select an entitled provider, implement its gateway mapping and verify authenticated
case tool badges and the Điều 12.2 narrative before accepting complete DoD.

**Hosted follow-up, 2026-10-13:** The personal Preview confirmed Workplace access,
then exposed the legacy chat constructor's Qdrant RBAC failure. Case chat now
selects the existing canonical runtime explicitly instead of relying on a server
default. The [follow-up worklog](../worklog/2026-10-13.md) records RED/GREEN payload
tests, 284 passing frontend tests and the remaining hosted/provider acceptance.
Transport reachability, authenticated access and actual tool execution need
separate evidence; claiming a case remains an authorization prerequisite.

**CI infrastructure follow-up, 2026-10-13:** A service-backed CI run failed
before tests when abandoned per-run Compose bridges exhausted Docker's default
address pools. The lifecycle fix scopes cleanup to stale empty P-063 CI
networks and runs on both startup recovery and teardown. It avoids global
network pruning and leaves active endpoints untouched; the next CI run is the
required runner-level confirmation.

**CI test preconditions, 2026-10-13:** The next runner reached persisted GIS
tests, exposing an invalid assumption that any other case contains distinct GPS.
The corrected test verifies a known empty observation state before timing target
selection. Hosted role tests separately exposed Clerk hydration after redirects;
the helper now waits for an actual session token before authenticated requests.
Four local regression tests and both TypeScript checks passed; hosted and
service-backed execution remain CI obligations. See the
[daily evidence](../worklog/2026-10-13.md). Synchronization should follow observable
readiness, and performance samples require independently verified initial state.
## Week 7: Organization launch acceptance audit — 2026-10-13

### Objectives

Verify [epic #285](https://github.com/AI20K-Build-Phase-Cohort-4/P-063/issues/285) against live databases, real Clerk accounts, current CI, and the organization contract. Repair reproducible preview blockers and preserve unrelated work.

### Completed artifacts

The [validation record](../testing/manual/ORG_LAUNCH_VALIDATION.md) contains actual database counts, migration differences, verified preview principal provisioning, a successful preview database repair deployment, browser observations, regression evidence, and continuation steps. Local patches repair preview database binding, runtime backend URL propagation, root routing, authorization grant preservation, and invalid integration fixtures.

### Roadblocks and outcomes

The initial handoff identified missing subjects, but the preview backend was also using dev's database. Verified subjects were provisioned only in preview, then the backend was rebound to its own Postgres service. Driver API authentication advanced, while complete hosted browser acceptance remained red. The invitation endpoint is still a simulation, and real organization mapping/creation/switching is not proven. Worker quota exhaustion was handled through preserved local worktrees and handoffs. Automatic approval review blocked external code export; no alternate export mechanism was used.

### Learnings and next steps

A seeded database is useful only when the deployed backend actually uses it. Fixture/provider simulations, unauthenticated browser checks, and successful builds establish different evidence than real organization acceptance. Publish reviewed patches only after explicit export approval, resolve contract/design prerequisites, implement real invitation and organization flows, repair runner capacity, and complete current-head A/B browser proof before closing the epic.
**Sustained-offline guardrail, 2026-10-13:** Per-point offline aggregation deferred honest trips to manual review (0.5% per-point offline over ~40 points). The window rule now requires sustained evidence while point-level deny-by-default is untouched, so true dropouts still block. Review caught two real defects before merge: suppressed network blocks also dropped co-occurring GPS/coordinate faults, and mixed naive/aware timestamps crashed gap correlation. Unit proof (31/31) is not benchmark proof; the full 10k rerun against the committed baseline decides whether `insufficient_evidence` precision actually moves. See the [daily evidence](../worklog/2026-10-13.md).

### Addendum 2026-10-14 — issue #100 live cockpit endpoints

Claimed the oldest unclaimed P1 Feature ([issue #100](https://github.com/AI20K-Build-Phase-Cohort-4/P-063/issues/100)): dedicated scorecard endpoints plus telemetry/timeline enrichment replace Cockpit Center Panel client mocks with live `app.*` queries. TDD planner confirmed RED (no endpoint existed; a stale "retired" comment covered a live `hashString` mock), implementer delivered, independent review raised 5 material findings (legacy verdict mapping, penalized count, timeline fallback, format, coverage) all repaired same-day. Learning: audit comments claiming mock retirement must be verified against imports, not trusted. Next: draft PR preview CI and hosted verification.

## CI reliability follow-up — 2026-10-14

**Objectives and artifacts:** Restore trustworthy issue #191 checks and repair the Railway Python heredoc syntax in the [workflow](../../.github/workflows/deploy-railway.yml), protected by a [regression test](../../tests/unit/scripts/test_deploy_railway_workflow.py). Attribution and scope are recorded in the [daily worklog](../worklog/2026-10-14.md).

**Roadblocks and outcomes:** Historical xdist failures came from shared temporary directories; PR #330 already isolates them. YAML indentation separately left Python top-level statements indented after shell extraction. Compile the actual YAML-parsed heredoc, rather than dedenting it in tests, to preserve this failure signal. Focused pytest and Ruff checks pass; hosted PR checks remain pending.

**Learnings and next steps:** Validate embedded scripts after their container format is decoded. Observe fresh CI before claiming completion; keep Railway source drift and real-account acceptance distinct from syntax validation.

## Week 8: Staged adjudication delivery — 2026-10-14

### Objectives

- [x] Deliver P0 Feature [#236](https://github.com/AI20K-Build-Phase-Cohort-4/P-063/issues/236) (stage AI conclusion behind independent analyst judgment) to draft PR with full DoD evidence.

### Completed Work

- [Preliminary-assessment endpoint, durable migration, cockpit mask/reveal gate, and history/audit delta](https://github.com/AI20K-Build-Phase-Cohort-4/P-063/issues/236) with 54 backend + 14 component + 6 browser tests GREEN and an 8/8 spec review.

### Roadblocks & Solutions

| Challenge | Applied Solution | Outcome |
|---|---|---|
| Worker sandbox could not write repository git metadata | Orchestrator verified RED/GREEN directly and committed from the main session | Commits `6e7e811` + `563c161` on `feature/236-staged-adjudication` |
| Quality review raised 4 blockers | Triaged each against code conventions (sync-DB parity, FK direction, lock order) | Zero material findings; no repair edits required |

### Key Learnings

1. Reviewer claims need evidence checks against existing conventions before spending repair budget.
2. Proposed wire contracts in the manual runbook kept backend/frontend workers aligned without transcript sharing.

### Next Week Plan

- [ ] Complete preview CI + real-account E2E for #236 and move the PR to review-ready.


## Week 7: Organization manager design review — 2026-10-14

### Objectives

Prepare a concrete redesign of the existing manager page for [issue #341](https://github.com/AI20K-Build-Phase-Cohort-4/P-063/issues/341): centered content, green primary actions, softer neutral surfaces, modal invitations, and usable table controls.

### Completed artifacts

The [design proposal](../design/organization-management/design.md) and [verification specification](../testing/manual/ORGANIZATION_MANAGEMENT.md) capture the intended interface and expected behavior. The [worklog](../worklog/2026-10-14.md) attributes the work and records its limits. Application implementation and runtime verification require approval of the visual proposal.

### Roadblocks and outcomes

Context7 returned a quota error; official shadcn documentation provided component guidance. The designer found an authenticated Stitch connection and generated a real source screen. Generated extra fields and SSO copy required a local revision for the existing page contracts; source-screen and authored-preview provenance remain distinct. The inspected backend still keeps invitation records in memory without Clerk email delivery and exposes manual population initialization. These facts were surfaced instead of treating removal of UI controls as proof of automatic behavior. The initialization scope question remains separate from the visual review.

### Learnings and next steps

Manager-facing copy should describe people, roles, and invitations rather than provisioning mechanisms. Distinguish preview screenshots from implemented application evidence. After visual approval, implement the reviewed design, run behavioral and responsive checks, and record current-revision results before marking the PR ready.


## Week 7: Organization management repair verification — 2026-10-15

### Objectives and completed artifacts

Bring [PR #343](https://github.com/AI20K-Build-Phase-Cohort-4/P-063/pull/343) to a verifiable review state while preserving the approved UI and existing authorization. Independent subagents reviewed the issue DoD, audited all created tests, and added no-analyst, pagination-offset, and real-admin organization smoke coverage. The [manager runbook](../testing/manual/ORGANIZATION_MANAGEMENT.md) and [daily worklog](../worklog/2026-10-15.md) record revision-specific evidence and attribution.

### Roadblocks, solutions, and outcomes

The remote PR had conflicts and no checks on its latest commit; the local rebased implementation preserved the original changes and merged cleanly with current main. Old failed workflow logs were unavailable, so the repair requires new current-head execution rather than treating historical failures as diagnosis. The Jev dispatch sandbox denied network and browser sockets; a temporary handoff preserved the worktree and delegated validation to an unrestricted worker. Broad frontend lint exposed existing errors outside the PR; relevant-file checks and broad results remain explicitly separate.

### Learnings and next steps

Assertions must verify pagination request offsets and the rows visible after actions, rather than only endpoint names. Fixture browser tests establish UI behavior; real-session preview tests establish authenticated hosted observations. Complete current-head CI and report accepted DoD evidence before any separately authorized merge. Durable invitations, Clerk email delivery, and automatic initialization remain separate backend scope.
# 2026-10-15 — Workspace #368 resume evidence

### Addendum 2026-10-14 — issue #264 ghost-trip fallback rule

Claimed the remaining ready-unclaimed P1 detector ([issue #264](https://github.com/AI20K-Build-Phase-Cohort-4/P-063/issues/264)): completed ∧ known never-arrived (present-None arrival keys) ∧ passenger denial → ERR-04 P1 advisory in the calibrated heuristic, with arrival passthrough in the benchmark mapper, worker, and projection allowlist ([ADR-027](../architecture/adr-027-ghost-trip-fallback-rule.md)). Test-writer/implementer subagent harness rejected the dispatch model, so TDD ran inline (RED 4 fail / 6 guards pass → GREEN 10/10) while planning/review workers ran on the working harness. Independent review passed spec 5/5 and forced 4 pattern-breadth repairs (bare "ảo"/affirmative-risk substrings out); same-input 10k rerun is byte-identical across the repair (ERR-04 R 0→0.7067 P 1.0, honest-completed precision 0.9565→0.9998, all other classes unchanged, 0 guardrail violations). Residual 88 FN are guardrail-dropout overlap (62), mock overlap (25), and silent/denial-free ghosts — documented ceiling, not a defect.

Learning: arrival presence (not values) is the precision gate; text patterns are recall-only behind it. Next: draft PR preview CI and hosted verification.

### Addendum 2026-10-14 — issue #193 dual-tab copilot drawer

Claimed P0 Feature ([issue #193](https://github.com/AI20K-Build-Phase-Cohort-4/P-063/issues/193)): Center Panel Conversation tab is now a read-only audit log (turn-count + extractive summary badges, composer deleted, relay turns excluded); right Agents panel splits into Trợ lý Phân tích – AI Copilot and Tiếp sóng Tài xế – Driver Relay with analyst takeover, idempotent retry, closed-session banner, and case-scoped live polling. Backend: analyst role added to the driver projection and stable turn_id idempotency on delegate-inquiry. TDD planner confirmed RED (18 failed / 2 passed); independent review raised 9 material findings, all repaired (15 backend pytest + 27 vitest + FEAT-S3-04 fixture browser green). Learning: frozen RED contracts still missed end-to-end delivery (driver receipt, live channel, idempotency) — review must trace DoD verification steps, not just unit seams. Next: draft PR preview CI and hosted verification.



## Desktop console delivery and verification — 2026-10-15

The objective was to finish the approved desktop manual console in [PR #345](https://github.com/AI20K-Build-Phase-Cohort-4/P-063/pull/345), repair its tenant boundary, and remove mobile previews. Delivered artifacts include explicit stop snapshots, owned actor selection, durable submission receipts, stream reconciliation, cancellation controls, updated specifications, and [verification evidence](../testing/TEST_CONSOLE_PR345_VERIFICATION.md).

The main roadblocks were overlapping upstream security changes, concurrent updates to the PR branch, stale browser/typing fixtures, false progress metrics, and the host's `/tmp` quota. Reconciliation preserved the stricter remote guard, updated behavioral fixtures, derived progress from persisted outcomes, and moved test temporary files outside both `/tmp` and the repository. PostgreSQL tests separately prove operational ownership and simulation receipt persistence; fixtures remain distinct from hosted identity proof.

The key lesson is that recorded samples do not establish model processing, and successful compilation does not establish authenticated release behavior. Next steps are the PR's full review/preview gates and separately authorized hosted acceptance; broader generator and organization-launch prerequisites remain unchanged.

## Week 42: 2026-10-12 - 2026-10-18 — PR #373 workspace recovery (update 2026-10-16)

### Objectives

- [x] Rebase the workspace onto current main and capture exact-head UI, seed, and authenticated audit evidence.
- [ ] Fill hosted CI Docker/E2E status after the orchestrator’s current run.

### Completed Work

The [PR #373 verification](../testing/WORKSPACE_PR373_VERIFICATION.md) and [workspace runbook](../testing/manual/workspace-368.md) record revision `2690dfd1`, the UI cleanup since `e2c26e1b`, local Vitest/TypeScript/Ruff/Playwright proof, approved idempotent preview enrichment counts, and the five-tab authenticated responsive audit. Attribution: Pham Thanh Dat with Codex assistance; time unrecorded.

### Roadblocks & Solutions

| Challenge | Applied Solution | Outcome |
|---|---|---|
| Viewer-test timeout under CI load | Rebased onto `fe9be9ca`, including Docker `queue:max` concurrency fix; compared 604s CI with 147ms local and neighboring slowdown | Test passes in CI after rebase; timeout classified as runner starvation |
| Traffic corroboration and willingness lack persisted contracts | Preserve explicit Unavailable states and document existing `case_service.py` fallbacks | No unsupported evidence or adjudication claim; follow-up remains tracked in #365 and #364 |

### Key Learnings

1. Separate historical exact-head proof and hosted observations from fresh uncommitted repair results.
2. Treat missing persisted contracts as unavailable evidence, even when preview fixtures contain adjacent data.

### Next Week Plan

- [ ] Record orchestrator-owned hosted CI Docker/E2E results and complete the PR review gate.

### Update 2026-10-16 — Copilot placeholder i18n

Focused TDD proved the Vietnamese placeholder regression (RED: expected `TestingLibraryElementError`; GREEN: 1 file/6 tests). The direct Vitest fallback passed 67 files/550 tests in 124.93s, and both app/test TypeScript checks passed. The pnpm wrapper failed before test execution with `ERR_SQLITE_ERROR unable to open database file`; hosted audit, browser, and Ruff evidence were not rerun for the uncommitted patch.
## Issue #190 completion follow-up — 2026-10-15

PR #240 delivered the driver motivation model and UI but left its Sprint 3
lifecycle assertion marked expected-failure and its motivation browser scenario
outside the configured Playwright discovery directory. The follow-up validates
the actual nested API contract and places card/Copilot consistency coverage in
the central browser suite. Lesson: a test file is not release evidence unless
the repository runner discovers it. Backend checks passed 34/34; clean CI
dependency installation, deterministic browser execution, and hosted acceptance
remain the merge gates.
## PR #373 fraud workspace evidence repair — 2026-10-15

PR #373 remains draft while redesign-induced existing test expectations are repaired. The branch adds 21 tests to the prior 419-test frontend suite; the first full run was 385 passed and 55 failed across 12 suites. Those failures are acceptance work, not baseline exclusions. Source fixes include target-case guards for deferred inquiry responses, neutral pre-reveal workflow labels, locale-aware driver metrics/status, preserved Maps analytics, and render-safe lease clock state. Browser verification remains pending.

The inquiry guard required a second boundary: changing cases resets the busy flag, while a monotonically increasing request generation prevents stale responses from clearing a newer request after returning to the original case. The deferred-response regression now passes 11/11.


## Workspace delivery continuation — 2026-10-15

The objective was to resume the interrupted fraud workspace delivery and preserve the approved six-tab layout, source evidence, and independent judgment gate. Delivered repairs restore case-only driver identity, give Driver and Complete distinct React identities, and display the saved judgment and note in Complete. Browser contracts now navigate the selected tabs and check outbound decision payloads, unauthorized/other-lease write prevention, missing telemetry values, metadata, keyboard access, replay, locale continuity, and archived judgment evidence. [Verification record](../testing/WORKSPACE_PR373_VERIFICATION.md).

The main obstacles were duplicate sibling keys that retained Driver DOM, stale browser selectors after the six-tab migration, and a precedent fixture that no longer matched the typed API. Distinct keys and behavioral RED/GREEN tests repaired the source defects; schema-checked fixtures and current accessible selectors repaired the tests. The full frontend suite passes 515 tests; the full fixture-browser suite passes 55 with 12 existing skips and no failures. Production build plus test TypeScript checks pass. Five full-project lint errors occur in files unchanged from the main baseline; no exclusions hide them.

The lesson is to verify visible panel identity as well as selected tab state and to retain persisted human judgment as readable evidence after reveal. Next steps are the PR's complete CI and authenticated preview gates. Local fixture-browser results, persisted database proof, and hosted real-account results remain separate. The related locale PR's transient `ERR_NETWORK_CHANGED` preview failure cleared on rerun without source changes.
## Database Optimization & Additive Workload Indexes Remediation — 2026-10-16

The objective was to remediate all specification compliance findings for PR #405 (Child #399, Parent #394), establishing leak-free database performance profiling, safe index inventory auditing, and bounded additive index migration tooling with empirical verification on realistic fixtures. Delivered artifacts include [`src/services/db_profiler.py`](../../src/services/db_profiler.py), [`scripts/db_profile.py`](../../scripts/db_profile.py), [`scripts/apply_workload_indexes.py`](../../scripts/apply_workload_indexes.py), [`db/migrations/20261015150000_workload_performance_indexes.sql`](../../db/migrations/20261015150000_workload_performance_indexes.sql), [`db/rollbacks/20261015150000_workload_performance_indexes.down.sql`](../../db/rollbacks/20261015150000_workload_performance_indexes.down.sql), [`tests/unit/test_db_profiler.py`](../../tests/unit/test_db_profiler.py), [`tests/integration/test_db_performance_bench.py`](../../tests/integration/test_db_performance_bench.py), and [`docs/testing/DB_OPTIMIZATION_394.md`](../testing/DB_OPTIMIZATION_394.md).

Roadblocks and solutions:
1. Autocommit transaction state: PostgreSQL was previously issuing warnings when setting transaction read-only and local timeouts on autocommit connections. Implemented explicit `conn.transaction(force_rollback=True)` with idle-connection enforcement, preserving original caller autocommit settings across success and failure without clobbering active caller transactions.
2. DSN secret redaction: Regex previously leaked quoted passwords containing whitespace/backslashes and URL query parameter secrets. Implemented allowlisted safe metadata keys (`target`, `host`, `port`, `database`, `schema`) and robust pattern matching covering quoted literals, query tokens, and mixed-case credentials.
3. Migration runner target safety: Direct target URL validation was failing open when opt-in was absent. Inverted guard to unconditionally validate loopback host, `test_` prefix, and explicit opt-in before connecting or executing DDL. Enforced mutual exclusivity between `--env` and `--target-url`.
4. Schema drift & expected plan hash: Added dry-run preflight emitting canonical SHA256 hashes of exact migration bytes, relevant catalog state (`trip_assignments` columns and indexes), and target identity. Require `--confirm-apply` with `--expected-plan-hash`, failing closed on catalog drift or parameter mismatch before executing DDL.
5. Benchmark artifact and queue index pruning: Retained full execution plans in [`docs/testing/artifacts/db_bench_evidence_394.json`](../testing/artifacts/db_bench_evidence_394.json) and synchronized Markdown documentation directly from machine evidence. Pruned unsupported queue index per empirical demonstration of no speedup on 100 cases fixture. Confirmed 58% speedup and 75% buffer reduction on `trip_assignment_by_trip` with 100% byte result equality.

Observed outcomes: All 11 unit tests and all 6 integration tests pass 100% green against local PostgreSQL 16 container. Ruff linting and formatting clean. Multi-environment live audits for dev, staging, and production retained with zero shared database mutations.

## Issue #191 traffic corroboration follow-up — 2026-10-15

### Objectives

- [x] Re-audit canonical traffic tools, schemas, error handling, agent bindings, and Điều 12.2 guidance.
- [x] Preserve both traffic tool badges during one Copilot turn.
- [ ] Complete authenticated hosted Cockpit verification against an entitled traffic gateway.

### Completed Work

- Added persistent multi-tool activity rendering and deterministic unit/browser acceptance in the [Cockpit](../../src/webapp/components/views/cockpit-view.tsx).
- Updated the [traffic evidence runbook](../testing/manual/TRAFFIC_EVIDENCE.md) with exact local evidence boundaries.

### Roadblocks & Solutions

| Challenge | Applied Solution | Outcome |
|---|---|---|
| One `toolName` field caused each new lifecycle event to replace the prior badge | Store and update a per-message tool activity list; retain legacy single-tool rendering | Both canonical traffic badges remain visible through completion |
| Shared self-hosted jobs concurrently rewrote Railway CLI config | Use a per-run temporary HOME and one explicit Railway credential class | Preview deployment state remains isolated |
| Protected navigation raced Clerk session hydration | Await a real Clerk token before navigating to the role home page | Middleware receives a committed session instead of returning a bare auth error |

### Key Learnings

1. Correct SSE parsing does not guarantee correct UI projection when the view model stores only one concurrent tool.
2. Hosted authentication must confirm session hydration before protected navigation.

### Next Week Plan

- [ ] Complete authenticated ERR-01 Cockpit verification with both tool badges and Điều 12.2 synthesis.

## Issue #191 licensed traffic evidence boundary — 2026-10-17

The objective was to preserve historical corroboration without violating TomTom
result-retention terms. Historical corridor evidence now uses valid, non-mock
first-party GPS from independent peer trips in the same organization. External
TomTom incidents remain live, timestamped, and memory-only context.

The prior gateway contract treated a configured provider response as historical
evidence and documented response artifacts. TomTom Terms clause 11.4 prohibits
that retention model. The revised contract reports peer count, time window,
median speed, p85 peer baseline, source type, and insufficient-evidence status;
strict incident output states that historical absence is not proven.

Key learning: provider entitlement proves live API access, not legal permission
to build historical archives. Next step: run full CI, then execute authenticated
hosted ERR-01 verification with real peer telemetry before closing Issue #191.
### Sanitized Copilot evidence projection

Completed traffic tools now attach an allowlisted evidence projection to canonical
`tool.end` events. The analyst drawer renders peer source, sample count, traffic
window, speeds, congestion ratio, incident count, observation time, and
`memory_only` retention. Raw incidents, provider payloads, headers, and credentials
never enter the browser event.

The earlier badge-only UI proved invocation but hid the evidence needed for human
verification. Backend projection tests, SSE parser tests, component tests, Ruff,
ESLint, and TypeScript checks now cover that boundary. Full CI and authenticated
hosted ERR-01 verification remain next steps; this change alone does not close
Issue #191.

### Unavailable incident evidence semantics

Hosted verification exposed a false-negative presentation: an unavailable
incident provider was projected as `incident_count=0`, allowing the model to say
that no incident was recorded. The corrective contract now keeps provider
failure explicit, preserves `historical_absence_proven=false` and `memory_only`,
and omits an incident count unless the provider returned an incident list. The
Copilot evidence panel renders the unavailable state and reason directly, while
agent guidance forbids translating unknown evidence into no incidents.

Focused verification passes 44 backend tests and 13 frontend component tests,
plus Ruff, ESLint with no errors, and both TypeScript configs. Full PR CI and a
new authenticated hosted ERR-01 run remain required before Issue #191 can close.

## 2026-10-17 — Analyst Copilot UI hotfix (#531 / #532)

Pham Dat (@datamonsterr), assisted by Codex, restored the Analyst Copilot layout and user bubble contrast. The shared `MessageContent` group selector had overridden the analyst bubble's intended colors; the call-site override preserves shared driver behavior. The panel now receives an explicit flex basis and width so intrinsic message content cannot shrink the sidebar.

Evidence: Vitest passed 14/14. The fixture browser regression passed 1/1 using the command recorded in the [worklog](../worklog/WORKLOG.md), and verified the panel geometry plus preserved gray secondary background `rgb(86, 94, 116)` and text `rgb(255, 255, 255)`. The browser result is local fixture evidence; hosted validation remains a separate gate. See the [manual runbook](../testing/manual/CHATBOT_UI_HOTFIX.md).

## Composer layout follow-up — 2026-10-17 (#534 / #535)

### Objectives

- [x] Record the approved composer order: attachment, expanding textarea, icon-only transparent send control.
- [x] Define vertical-centering, upload-preview, multiline, and 375px viewport checks.
- [x] Obtain browser RED/GREEN evidence against the real `textarea` callsite.

### Completed Work

- Updated the [chatbot UI hotfix manual runbook](../testing/manual/CHATBOT_UI_HOTFIX.md) with the follow-up behavioral checks.

### Roadblocks & Solutions

| Challenge | Applied Solution | Outcome |
|---|---|---|
| PR #533 checked the composer form while the defect is in the direct `textarea` child sizing and control order | Scope stacked preview layout to Analyst, keep shared PromptInput defaults unchanged, and test real textarea geometry | Browser GREEN: 6/6 fixture tests at 1440px and 375px; screenshots saved under `test-results/` |

### Key Learnings

1. A form-level bounding-box assertion can miss a constrained direct input child.
2. Composer layout acceptance needs both geometry and interaction-state checks.

### Next Week Plan

- [x] Record browser RED/GREEN result and artifact path.

## 2026-10-18 — Traffic incident evidence wording (#191)

The hosted ERR-01 acceptance run reached both traffic tools. Peer telemetry was available, while the incident provider returned `provider_not_configured`. The model then described the incident absence as confirmed. A runtime fallback now states that incidents cannot be verified, retains historical peer evidence and Điều 12.2 context, and leaves the decision with the analyst. The focused traffic suite passed 56/56. Next: merge after CI, repeat authenticated hosted verification, and record the final evidence on [Issue #191](https://github.com/AI20K-Build-Phase-Cohort-4/P-063/issues/191).


## DriverSearch debounce stabilization — 2026-10-19

Objective: remove slow-runner timing flakiness from the DriverSearch debounce test while preserving proof that no search occurs before 300ms and exactly one search occurs at 300ms. The [focused test](../../src/webapp/tests/unit/components/test-console/driver-search.test.tsx) now uses non-advancing fake timers, awaited async timer advancement, and direct post-flush assertions; no component behavior changed.

Local focused repetitions passed 20/20 (100 test executions), and typecheck passed. The local fix is committed; push and PR creation are blocked by GitHub DNS in this environment. Next step: push the branch and open the PR from a network-enabled terminal.

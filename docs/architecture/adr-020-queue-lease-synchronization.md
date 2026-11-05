# ADR-020: Queue Lease Synchronization and Multi-Analyst Session Concurrency

## Context
In the Fraud Adjudication Workspace Cockpit, multiple analysts concurrently triage and review fraud cases. Under PRD requirement FR-01 and AC-MVP-01, claiming a case establishes an exclusive 300-second review lease.

Prior to this fix (Issue #144):
1. **Stale UI Visibility**: The frontend Cockpit workspace only loaded cases on initial mount or manual refresh. When Analyst A claimed a case, Analyst B's open browser session retained the case in their "Available" list until manual refresh.
2. **Database Principal Resolution Flaw**: In PostgreSQL mode, `claim_case_lease` attempted `SELECT id FROM app.principals WHERE id = %s` with non-UUID analyst identities (e.g. Clerk external subjects `user_...`). This caused PostgreSQL to abort the transaction with `invalid input syntax for type uuid`, rolling back the transaction and failing to persist the lease in `app.review_leases`.
3. **Queue Lease Query Inaccuracy**: The SQL query in `list_cases` used `lease.analyst_id::text IS DISTINCT FROM %s` unconditionally, causing mismatch when analyst identifiers were external subjects or null.
4. **Stale Action Feedback**: When an analyst attempted to adjudicate or claim a case already held by another analyst (409 Conflict), the UI displayed an error message but did not automatically refresh the case detail or queue to reflect the read-only locked state.

## Decision

1. **Dual Principal Identity Resolution**:
   - In `claim_case_lease` and `release_case_lease`, resolve principal identity safely by checking `self._is_valid_uuid(analyst_id)` before querying `WHERE id = %s`, falling back to `WHERE external_subject = %s`, preventing PostgreSQL transaction aborts.
   - Accurately record the resolved principal UUID in `app.review_leases` and `app.fraud_cases.assigned_analyst_id`.

2. **Durable Multi-Principal Lease Filtering in `list_cases`**:
   - For `availability == "available"`:
     - When `analyst_id` is provided, exclude cases actively leased by other analysts via:
       ```sql
       NOT EXISTS (
           SELECT 1 FROM app.review_leases lease
           LEFT JOIN app.principals p ON lease.analyst_id = p.id
           WHERE lease.case_id = c.id
             AND lease.expires_at > now()
             AND lease.analyst_id::text != %s
             AND COALESCE(p.external_subject, '') != %s
       )
       ```
     - When `analyst_id` is None, exclude all actively leased cases (`lease.expires_at > now()`).
   - For `availability == "mine"`:
     - Match against both UUID and external subject (`lease.analyst_id::text = %s OR p.external_subject = %s`).
   - In-memory and Redis fallbacks mirror this contract using `self._analyst_matches`.

3. **Periodic Client-Side Queue & Detail Synchronization**:
   - Introduce a 10-second periodic background sync in `CockpitWorkspaceView` via `loadCases(silent = true)`.
   - Sync only when document is visible (`document.visibilityState === 'visible'`) and not currently submitting (`!isSubmitting`).
   - Listen for tab focus/visibility transitions via `document.addEventListener('visibilitychange')`.
   - Also refetch `fetchCaseDetail(selectedCaseId)` so lock holder status updates automatically without user intervention.

4. **PRD-Compliant Read-Only Lock Notification**:
   - When a case is locked by another analyst (`isLockedByOther`), render an explicit `role="status"` notice banner:
     `Case is currently claimed by analyst {holder}. Review actions and adjudication are read-only.`
   - Disable Claim button and show `Locked by another analyst`.
   - Disable Send decision actions.
   - On 409 Conflict on claim or decision submission, immediately refetch case detail and queue to transition smoothly into the read-only locked state.

## Consequences
- Claimed cases disappear from other analysts' available triage views automatically without manual page reloads.
- Claiming analysts can resume their cases in "My Cases".
- Conflicting concurrent claims or stale submissions return deterministic 409 Conflict responses.
- Historical audit records and case telemetry are completely preserved.

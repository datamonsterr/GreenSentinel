# ADR-020: Processed Case History Search and Retained Evidence Archive

## Status

Accepted, 2026-10-05. [Issue #150](https://github.com/AI20K-Build-Phase-Cohort-4/GreenSentinel/issues/150).

## Context

In [Issue #143](https://github.com/AI20K-Build-Phase-Cohort-4/GreenSentinel/issues/143), finalized cases (`resolved`, `dismissed`, `auto_dismissed`) were removed from the active triage queue to prevent queue bloat and conflicting analyst leases. However, fraud analysts and compliance auditors require the ability to browse, search, and inspect all processed cases with complete retained evidence, driver dispute conversations, executed tool actions, and immutable audit logs.

Furthermore:
- Opening a historical case must be strictly read-only: it must **not** trigger a new review lease (`app.review_leases`), overwrite the assigned analyst, or trigger automated sanctions.
- The archive search must support the shared identity/license matching established in [ADR-019](adr-019-case-search-identity.md) alongside date range, status, decision, and analyst filters.
- Driver users accessing history must be strictly constrained to their own cases (`driver_id = principal.driver_id`).

## Decision

1. **Terminal Status Scope**:
   - Processed history is defined by terminal statuses: `resolved`, `dismissed`, and `auto_dismissed`.
   - In-flight, draft, or failed nonterminal decisions never appear as finalized archive records.

2. **API & Service Endpoints**:
   - Implement `GET /api/v1/cases/history` served by `CaseService.list_case_history`.
   - Supported query parameters:
     - `search: str | None`: Case ID, driver display name, driver ID, external ref, or vehicle registration plate.
     - `status: str | None`: Filter by terminal status (`resolved`, `dismissed`, `auto_dismissed`).
     - `decision: str | None`: Filter by adjudication decision (`APPROVE`, `DISMISS`, `AUTO_DISMISS`).
     - `analyst_id: str | None`: Filter by deciding/assigned analyst.
     - `start_date`, `end_date`: Filter by finalization timestamp (`updated_at`).
     - `limit: int`, `offset: int`: Server-side pagination.
   - Route priority: Declared before `/cases/{id}` in `src/api/routes.py` to prevent dynamic path parameter shadowing.

3. **Read-Only Inspection Guarantee**:
   - Accessing `GET /api/v1/cases/history` and subsequent `GET /api/v1/cases/{id}` performs pure read operations.
   - No row is inserted or updated in `app.review_leases`.
   - The preserved version (`version`), forensic brief, telemetry samples, driver dialogue, precedent trace, and audit log entries remain completely accessible and immutable.

4. **Tenant & Role-Based Authorization**:
   - Enforce `require_role(principal, "analyst", "senior_analyst", "admin", "driver")`.
   - When the caller's role is `driver` (and not `analyst`), queries are strictly partitioned by `driver_id = principal.driver_id`.
   - Multi-tenant boundary is strictly enforced via `organization_id`.

5. **Frontend Cockpit Integration**:
   - `fetchCaseHistory` added to `src/webapp/lib/api-client.ts`.
   - `CockpitWorkspaceView` left sidebar provides dual-mode navigation tabs: **Active Queue** and **Case History**.
   - History mode provides dedicated status filtering (`All Processed`, `Resolved`, `Dismissed`, `Auto-dismissed`), identity/plate search, and pagination controls.
   - When a terminal/archived case is opened in the center workspace:
     - The top header renders a prominent `Archived · {status}` badge instead of Claim/Release buttons.
     - The bottom adjudication panel renders a read-only `Preserved Archive · Read-only` summary banner showing version and decision maker, completely replacing the decision textarea and submit buttons.

## Verification

- **Backend Pytest**: [`tests/test_api/test_case_history.py`](../../tests/test_api/test_case_history.py) (6 test cases covering queue exclusion, search, status/decision filtering, zero-lease guarantee, tenant isolation, and pagination).
- **Frontend Vitest**: [`src/webapp/tests/case-history.test.tsx`](../../src/webapp/tests/case-history.test.tsx) (5 test cases covering dual-tab navigation, search in history, status dropdown filtering, read-only UI controls, and pagination).

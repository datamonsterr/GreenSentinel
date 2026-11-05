# Issue 150 Verification Report: Processed Case History Search and Retained Evidence Archive

## Scope and Context
- **Issue**: [#150](https://github.com/AI20K-Build-Phase-Cohort-4/GreenSentinel/issues/150)
- **Branch**: `feat/150-case-history`
- **Base commit**: `feat/149-search-driver-plate` / `4e23250` (origin/main)
- **Target**: Allow fraud analysts and permitted drivers to browse and search all processed cases (`resolved`, `dismissed`, `auto_dismissed`) with retained evidence, driver conversation, executed actions, and immutable audit logs. Guarantee read-only access without claiming leases or triggering sanctions.

## Implemented Deliverables

1. **Backend Service & API**:
   - `src/services/case_service.py`: Implemented `CaseService.list_case_history` with PostgreSQL query and in-memory fallback supporting:
     - Shared driver identity & vehicle plate search (`search`).
     - Terminal status filtering (`status`: `resolved`, `dismissed`, `auto_dismissed`).
     - Adjudication decision filtering (`decision`: `APPROVE`, `DISMISS`, `AUTO_DISMISS`).
     - Assigned analyst filter (`analyst_id`).
     - Date range filter (`start_date`, `end_date`).
     - Server-side pagination (`limit`, `offset`).
     - Tenant and driver role isolation (`organization_id`, `driver_id`).
   - `src/api/routes.py`: Added `GET /api/v1/cases/history` endpoint with appropriate role requirements (`analyst`, `senior_analyst`, `admin`, `driver`) positioned before `/cases/{id}` to avoid routing conflicts.

2. **Frontend Cockpit Workspace**:
   - `src/webapp/lib/api-client.ts`: Added `fetchCaseHistory` function and `FetchCaseHistoryOptions` interface.
   - `src/webapp/components/views/cockpit-view.tsx`:
     - Dual-mode navigation tabs: **Active Queue** and **Case History** in the left sidebar.
     - Case history search and terminal status dropdown (`All Processed`, `Resolved`, `Dismissed`, `Auto-dismissed`).
     - Pagination controls when history records exceed page size.
     - When inspecting an archived case:
       - Displays prominent `Archived · {status}` badge instead of Claim/Release buttons.
       - Displays read-only `Preserved Archive · Read-only` decision banner indicating version and deciding analyst, replacing the decision form and preventing accidental re-adjudication.
       - Retains full access to forensic brief, driver profile, GPS telemetry map, and conversation history without claiming a lease or submitting sanctions.

3. **Architecture Documentation**:
   - `docs/architecture/adr-020-case-history-archive.md`: Detailed ADR on terminal statuses, search scope, read-only guarantees, and role-based access.

## Verification Evidence

1. **Ruff Linter & Formatter**:
   ```bash
   ruff check src/ tests/
   ruff format --check src/ tests/
   ```
   Result: `0 errors`, `all files already formatted`.

2. **Mypy Static Type Checking**:
   ```bash
   mypy src/
   ```
   Result: `Success: no issues found in 62 source files`.

3. **Backend Case History Tests (Pytest)**:
   ```bash
   pytest tests/test_api/test_case_history.py -v
   ```
   Result: `6 passed in 4.01s`:
   - `test_list_processed_case_history_excludes_active_cases` PASSED
   - `test_case_history_search_by_driver_and_plate` PASSED
   - `test_case_history_filter_by_decision_and_status` PASSED
   - `test_case_history_read_only_access_does_not_claim_lease` PASSED
   - `test_case_history_tenant_isolation` PASSED
   - `test_case_history_pagination` PASSED

4. **Frontend Vitest Suites**:
   ```bash
   npm test tests/case-history.test.tsx tests/case-search.test.tsx tests/cockpit-live.test.tsx
   ```
   Result: `18 passed in 3 test files`:
   - `tests/case-history.test.tsx` (5/5 passed)
   - `tests/case-search.test.tsx` (4/4 passed)
   - `tests/cockpit-live.test.tsx` (9/9 passed)

5. **Full Webapp Vitest Suite**:
   ```bash
   npm test
   ```
   Result: `152 passed across 25 test files` (100% green).

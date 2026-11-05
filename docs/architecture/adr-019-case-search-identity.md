# ADR-019: Case Search by Driver Identity, Driver ID, and Vehicle Registration Plate

## Status

Accepted, 2026-10-05. [Issue #149](https://github.com/AI20K-Build-Phase-Cohort-4/GreenSentinel/issues/149).

## Context

Fraud analysts triaging dispute cases frequently receive alerts referencing specific drivers (by name, driver ID, or fleet reference number) or vehicles (by registration plate number). Prior to this change, the case listing endpoint (`GET /api/v1/cases`) only allowed filtering by `status`, `priority`, and lease `availability`, forcing analysts to manually scan through paginated lists to find target cases.

Furthermore, driver names in Vietnamese ride-hailing datasets contain diacritics and varied accent representations (e.g. `Nguyễn Văn Bình`), while search queries entered by analysts may omit accents (`nguyen van binh` or `binh`) or include varied punctuation in license plates (e.g. `29E-123.45` vs `29e12345`).

## Decision

1. **API & Service Contract**:
   - Add optional `search: str | None = Query(default=None, max_length=100)` to `GET /api/v1/cases` and `CaseService.list_cases`.
   - Empty or whitespace-only search defaults to unfiltered queue listing.

2. **Search Matching Scope**:
   - Matches driver display name (`app.drivers.display_name` or `app.principals.display_name`).
   - Matches driver ID (`app.trip_assignments.driver_id`).
   - Matches driver external reference (`app.drivers.external_ref`).
   - Matches vehicle registration plate (`app.vehicles.registration_ref` / `app.fraud_cases.vehicle_plate`). Per stakeholder decision on 2026-10-05, "license number" specifically refers to the vehicle registration plate (biển số xe).

3. **Parameterized SQL Implementation**:
   - Implemented via a parameterized `EXISTS` subquery over `app.trip_assignments` joining `app.drivers`, `app.principals`, and `app.vehicles` with `ILIKE %s`.
   - Zero SQL concatenation: all search patterns are passed safely as query parameters (`%s`), completely eliminating SQL injection risks.

4. **In-Memory Normalization for Test & Fallback**:
   - Implement `_normalize_search_text` using Unicode `NFKD` decomposition, stripping combining diacritics (`Mn` category) and converting `đ`/`Đ` to `d`.
   - Also strips non-alphanumeric characters for flexible vehicle plate matching (e.g., matching `29E-123.45` when searching `29e12345`).

5. **Tenant & Role Isolation**:
   - The search filter is strictly combined with `c.organization_id = %s` and lease availability locks (`NOT EXISTS (SELECT 1 FROM app.review_leases ...)`). Cross-tenant cases are never exposed.

6. **Webapp Cockpit Integration**:
   - `fetchCases` in `src/webapp/lib/api-client.ts` supports `search?: string`.
   - `CockpitWorkspaceView` provides a search text input with accessible labeling (`aria-label="Search cases by driver identity or vehicle plate"`), search icon, and a one-click clear button (`close`).
   - Displays clear "No cases match search" empty state feedback when query yields no results.

## Rationale & Alternatives Considered

| Option | Pros | Cons | Decision |
|---|---|---|---|
| **Parameterized EXISTS subquery + NFKD in-memory** | Zero join duplication, safe against SQL injection, resilient to accented/unaccented Vietnamese text | Requires subquery execution in PostgreSQL | **Selected** |
| Client-side in-memory filtering in React | No backend changes | Fails for paginated datasets; only searches currently loaded page | Rejected |
| Dedicated Full-Text Search (tsvector / pg_trgm) | Fast for massive corpora | Unnecessary infrastructure overhead for queue triage (< 10k active cases) | Deferred for future scale |
| Driving license number search | Matches driver's personal license card | Not recorded in trip telemetry or fraud case payload; plate was confirmed as intended scope | Rejected |

## Security and Boundary Protection

- Parameterized SQL execution via `psycopg` ensures wildcards and special characters (`'`, `DROP TABLE`, `%%`, `[]`) are treated purely as literal string patterns.
- Role checks (`require_role(principal, "analyst", "senior_analyst", "admin")`) and tenant boundary enforcement (`organization_id`) are applied prior to query execution.

## Verification

- Backend Pytest suite: [`tests/test_api/test_case_search.py`](../../tests/test_api/test_case_search.py) (6 test cases covering accents, plates, IDs, multi-tenant boundaries, filter combos, and SQL injection safety).
- Frontend Vitest suite: [`src/webapp/tests/case-search.test.tsx`](../../src/webapp/tests/case-search.test.tsx) (4 test cases covering input rendering, parameter forwarding, clear button, and empty state).

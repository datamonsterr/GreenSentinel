# ADR-016: Enforce Strict Role and Case-Owned Access Across Webapp, API, and SSE

## Status
Accepted, 2026-10-05. [Issue #145](https://github.com/AI20K-Build-Phase-Cohort-4/P-063/issues/145).

## Context
The application serves two distinct user personas: Fraud Analysts operating in `/workplace` and Driver Partners responding to inquiries in `/driver`. Prior implementation relied primarily on client-side route checks and permissive middleware. In particular, `/driver` was excluded from middleware role checks, and backend chat endpoints did not verify driver case assignment before streaming SSE events or emitting chat history. Furthermore, privileged roles could potentially be self-asserted through client metadata rather than verified from the database.

## Decision
1. **Server-Side Route Authorization Boundary (`server-only`)**:
   Implement `requirePageAccess` and `requireDriverCaseAccess` in Next.js Server Components. The server verifies the Clerk JWT against the backend `/api/v1/account/settings` endpoint. If unauthorized or unauthenticated, the user is redirected to `/sign-in` or served `notFound()`. Client-side route hiding is never trusted as an authorization boundary.

2. **Database-Driven Principal Roles and Assignment Ownership**:
   All roles (`analyst`, `fraud_analyst`, `senior_analyst`, `manager`, `admin`, `driver`) are loaded exclusively from `app.principals` and `app.principal_roles` via `load_principal()`. Drivers are mapped via `app.drivers.principal_id`. Self-granting of privileged roles via client headers or unverified tokens is strictly forbidden.

3. **Strict Case-Scope Ownership (`require_case_scope`)**:
   Before reading case history, dispute details, or establishing SSE chat streams (`/driver/cases/{id}/chat/stream`), the backend service verifies that:
   - The caller's `organization_id` matches the case `organization_id`.
   - If the caller has role `driver`, their `driver_id` matches the case assignment's `driver_id`.
   Cross-driver and cross-organization requests return `403 Forbidden` fail-closed before any payload, headers, or streaming bytes are transmitted.

4. **Fail-Closed Default**:
   Revoked, expired, missing, or unverified credentials immediately return 401/403. Production environments strictly forbid bypassing authentication via test flags (`localTestAuthentication()` is restricted to `process.env.APP_ENV === "test"` and non-production).

## Consequences
- Analysts cannot access `/driver` or driver case chats.
- Drivers cannot access `/workplace`, `/analytics`, or dispute sessions belonging to other drivers.
- All 56 API role access unit tests, 6 RBAC settings tests, and 14 Vitest server-route authorization tests pass cleanly.

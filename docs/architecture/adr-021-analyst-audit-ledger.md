# ADR-021: Analyst Profile, Decision Metrics, and Immutable Audit Ledger

## Status

Accepted, 2026-10-05. [Issue #151](https://github.com/AI20K-Build-Phase-Cohort-4/GreenSentinel/issues/151).

## Context

Under PRD §4, Design.md §2.3, and regulatory compliance standards for Human-in-the-Loop (HITL) fraud investigation systems:
1. Every fraud investigation decision (approve/sanction, dismiss, warning, suspension) must be permanently attributed to a Clerk-authenticated human analyst.
2. Individual analysts require a personalized operational dashboard displaying their real-time shift performance (today's decisions, 30-day adjudications, mean time to resolution / MTTR, model agreement rate, and quality overturn rate).
3. The analyst's active review lock (exclusive lease from `app.review_leases`) must be surfaced immediately with an active TTL countdown and a direct "Resume Case →" quick action to avoid work collisions or abandoned review locks.
4. Delegated governance authority limits (dismiss authority, warning authority, direct fine limits in VND, suspension limits) must be explicitly shown according to least-privilege role boundaries.
5. All completed decisions must be recorded in an immutable, append-only chronological audit ledger (`app.adjudications` and `app.review_actions`) with cryptographic request hashes, tamper-evident timestamps, and searchable by driver identity, license plate, or case token.

## Decision

1. **Schema & Contract**:
   - `AnalystDecisionMetrics`: Tracks `today_decisions_count`, `thirty_day_decisions_count`, `average_mttr_seconds`, `model_agreement_pct`, and `quality_overturn_pct`.
   - `AnalystGovernanceLimits`: Encapsulates role-based authority (`dismiss_authority`, `warning_authority`, `direct_fine_limit_vnd`, `suspension_authority`, `role`).
   - `ActiveReviewLeaseSummary`: Summarizes active lease (`case_id`, `case_code`, `severity`, `driver_name`, `vehicle_plate`, `expires_at`, `remaining_seconds`).
   - `AnalystAuditLedgerItem`: Immutable record (`id`, `case_id`, `case_code`, `timestamp`, `actor_id`, `actor_name`, `actor_type`, `action`, `verdict`, `subject_entity`, `triggered_violation`, `sanction`, `rationale`, `snapshot_version`, `request_hash`).
   - `AnalystAuditProfileResponse`: Unified payload uniting profile metadata, metrics, governance limits, active lease, and paginated ledger.

2. **Backend Service & API Implementation**:
   - Implemented `CaseService.get_analyst_audit_profile(analyst_id, organization_id, search, verdict, limit, offset)` in `src/services/case_service.py`.
   - Primary database pathway executes parameterized queries on `app.principals`, `app.principal_roles`, `app.review_leases`, `app.adjudications`, `app.fraud_cases`, `app.trip_assignments`, `app.drivers`, and `app.vehicles`.
   - In-memory fallback handles lightweight evaluation and local test environments with full parity.
   - Endpoint `GET /api/v1/analyst/audit` declared in `src/api/routes.py` with strict RBAC:
     `require_role(principal, "analyst", "senior_analyst", "admin")`.
     Non-analyst roles (e.g. driver) are strictly rejected with HTTP 403 Forbidden.
   - Multi-tenant isolation guarantees analysts only observe cases and records belonging to their authenticated `organization_id`.

3. **Frontend Analyst Profile View (`src/webapp/components/views/profile-view.tsx`)**:
   - Integrated `fetchAnalystAuditProfile` into `src/webapp/lib/api-client.ts`.
   - Structured according to Design.md §2.3:
     - **Header**: Analyst display name, authenticated role badge, and Account & Role Settings modal trigger.
     - **Active Review Lock Banner**: Displays currently claimed case (`#FC-XXXX P0 CRITICAL`), subject driver identity, dynamic TTL countdown clock, and "Resume Case →" / "Open workspace" button.
     - **4-Card Metrics Row**:
       - Today's Decisions (+5% quota context).
       - Average MTTR (< 45s SLA target context).
       - Quality & Overturn (< 3% benchmark context).
       - 30-Day Adjudications (100% HITL, zero automated bypass context).
     - **Governance Limits Bar**: Displays authority limits, direct fine caps (≤ 2M / 5M VND), suspension policies (24h/48h lockout), model agreement, and authentication provenance.
     - **Verdict Audit Trail Table**: Interactive search input (case token, driver, plate) and verdict filter dropdown (APPROVE, DISMISS, WARN, FINE, SUSPEND), rendering timestamp, token, entity, violation, verdict badge, sanction, actor, and sha256 request hash.

## Verification

- **Backend Pytest**: [`tests/test_api/test_analyst_audit.py`](../../tests/test_api/test_analyst_audit.py) (5 test cases covering decision metrics, governance limits, active lease banner, ledger search/filter, RBAC, and tenant isolation).
- **Frontend Vitest**: [`src/webapp/tests/analyst-audit.test.tsx`](../../src/webapp/tests/analyst-audit.test.tsx) (4 test cases covering 4-card metrics row, active review banner with countdown and resume callback, governance limits bar, and verdict audit trail table with search & filter).
- **Regression Suite**: 156/156 Vitest frontend tests passed; 100% green Ruff format/check and mypy typechecking.

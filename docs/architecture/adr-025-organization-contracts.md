# ADR-025: Organization Contracts and Tenant Isolation (S4-CONTRACT #291 / S4-TENANT #294)

## Status
Accepted, 2026-10-12. Issues [#291](https://github.com/AI20K-Build-Phase-Cohort-4/GreenSentinel/issues/291) (contract), [#294](https://github.com/AI20K-Build-Phase-Cohort-4/GreenSentinel/issues/294) (implementation).

## Context
Clerk provides browser identity, but authorization and tenancy live in Postgres
(`app.principals`, `app.principal_roles`, per-row `organization_id`). Prior code
silently collapsed unknown orgs to a default organization UUID and defaulted
unknown users to `fraud_analyst`, so a new Clerk signup could read another
tenant's cases. Child tables without `organization_id` relied on join-time
filtering only.

## Decision
1. **Active org source of truth**: the Clerk active organization (`org_id` /
   `o.id` JWT claims), server-verified per request. When the claim is a
   provisioned UUID, `DB principal.organization_id` must match or the request
   is a 403 (`Clerk organization mismatch`).
2. **Clerk-to-DB mapping**: principals keyed by
   `(organization_id, external_subject)`. JIT sync (`sync_clerk_principal`)
   requires a real UUID org (never `org_*`, never a default) and an explicit
   role; it runs only when the session carries a Clerk `org_role` or a DB row
   already exists. Unknown identities with no org are denied 403
   (`Clerk user has no active assigned role`) — no `fraud_analyst` fallback.
3. **Multi-role routing**: one documented priority
   Admin → `/organization`, Analyst → `/workspace`, Driver → `/driver`,
   resolved by a canonical resolver shared by backend and frontend.
   (Resolver UI wiring is #296; this ADR only fixes the server contract.)
4. **Seeded driver/customer entities are not Clerk accounts.** An invited
   Driver binds explicitly via the Admin API driver-link
   (`app.drivers.principal_id` set only through an admin-scoped update);
   `principal_id` is never inferred from `principal.id`.
5. **Simulation/test tenants stay isolated**: the `/test/*` stack
   (`APP_ENV=test` + `test_auth_enabled`, `demo_operator` / `driver-guest`)
   is untouched and keeps its existing fixtures. Worker synthetic writes
   (`telemetry_queue_worker.DEFAULT_ORG_ID`) belong to that simulation tenant.
6. **Server identity propagation**: routes take no client `organization_id`
   input; every case/trip/detail/search/count/history, assignment, evidence,
   profile, chat/tool, SSE, notification, export, and worker write binds
   `organization_id` from the server-owned `Principal`. Persisted service reads
   without org scope are 403 outside the `/test/*` stack
   (`_require_org_scope`). Model-facing tool schemas forbid `organization_id`
   args (`tool_catalog.model_input_schemas` strips them); the runtime injects
   org from context.
7. **Database**: migration `20261012*_org_isolation.sql` adds missing
   org-scoped indexes, ownership triggers (`trip_assignment_org_match`,
   `fraud_case_org_match`, `driver_principal_org_match`), and an
   `app.org_quarantine` table. Ambiguous legacy rows are quarantined and
   documented, never auto-assigned to every org.

## Consequences
- New Clerk users without an org assignment get 403 until an admin provisions
  them; `org_*` ids never collapse to a default org.
- Cross-org reads/writes (REST, swapped IDs, counts, SSE pre-header checks,
  exports) fail closed with 403 before any payload bytes.
- `/test/*` simulation flows keep working unchanged in `APP_ENV=test`.
- Known gap: legacy agent tools (`analyst_tools`, `rag.db_tools`) take no org
  argument by design; unscoped direct calls fail closed (403) when a database
  is present. Threading server org context into those tools is follow-up work.

# Org Onboarding Runbook (S4-ENTRY #296)

## Routing
- Canonical: Admin → `/organization`, Analyst → `/workspace`, Driver → `/driver`.
- `/workplace` is a compat alias for `/workspace`. Dashboards/analytics/profile map to analyst area.
- `/` is the single server-verified resolver: reads `GET /api/v1/account/route`
  (fallback: derive from `GET /api/v1/account/settings`). Sign-in/sign-up use
  `fallbackRedirectUrl="/"` so the resolver runs after auth, invite accept, reload, org switch.

## Invite flow
1. Admin opens `/organization`, fills invite form (email + admin|analyst|driver).
2. Backend `POST /api/v1/admin/invitations` validates admin-only, own-org,
   supported role; returns 501 when `CLERK_SECRET_KEY` is missing.
3. Invitee accepts the Clerk invite, signs in, lands on `/` → canonical route.
4. Admin manages roster: `GET /account/users?limit=&offset=`, `PATCH .../role`,
   `POST /admin/invitations/{id}/revoke|resend`.

## Guards
- Non-admin invite/role change → 403. Unsupported role → 422.
- Demoting the last admin → 403 (`Cannot demote the last admin`).
- Zero analysts → banner on `/organization` (no fake members seeded).

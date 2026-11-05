# ORG_BOOTSTRAP — retry / repair runbook (S4-ACTORS #295)

Endpoint: `POST /api/v1/admin/organizations/{org_id}/bootstrap` (admin, own org).
CLI: `python scripts/bootstrap_org_population.py --org-id <uuid>`.

## Normal run
1. Apply migrations (`db/migrations/20261013000000_org_bootstrap.sql`).
2. Run CLI or POST endpoint.
3. Confirm `GET .../bootstrap` → `{"status": "ready", "drivers": 100, "customers": 1000}`.

## Retry (safe, idempotent)
- Any failure: **rerun the exact same command/request**. IDs are deterministic
  (uuid5 org+seed+template+index) and inserts are `ON CONFLICT DO NOTHING`,
  so retries converge — never delete rows to "start over".
- `status: running` with short counts = interrupted run. Rerun resumes it.
- `503 database unavailable`: check `DATABASE_URL`, then rerun. A 503 never
  means ready — only exact 100/1000 flips state to `ready`.

## Repair
- `status` stuck `running` but counts already 100/1000: rerun once; the
  verify step flips it to `ready`.
- Counts exceed 100/1000 for the seed prefix: foreign rows were inserted
  manually — quarantine them, never auto-delete seeded rows.
- Driver link wrong person: Admin re-POSTs
  `/admin/drivers/{driver_id}/link` with the correct `principal_id`
  (same-org only; cross-org → 403, enforced also by DB trigger
  `driver_principal_org_match`).

## Never do
- Never set `principal_id` in bulk — binds happen only via explicit Admin link.
- Never copy trips/cases/ratings into the seed path; bootstrap writes
  drivers + passengers only.

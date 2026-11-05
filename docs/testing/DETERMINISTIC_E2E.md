# Deterministic browser E2E matrix (local fixtures, no hosted backend)

Every local browser spec runs against `next dev` with `page.route`
fixtures (`tests/e2e/browser/api-fixtures.ts` plus per-spec routes).
No Clerk keys, no Railway backends, no real data. Hosted real-account
proof lives separately in [REAL_ACCOUNT_E2E](REAL_ACCOUNT_E2E.md).

## Manual runbook coverage

| Runbook | Status | Covering spec |
|---|---|---|
| `manual/ISSUE_60.md` S1 (thinking + tool trace) | Covered | `tests/e2e/browser/tool-runtime.spec.ts` (thinking indicator + paired tool activity) |
| `manual/ISSUE_60.md` S2 (interruption recovery) | Covered | `tests/e2e/browser/tool-runtime.spec.ts` (partial text retained, error shown) |
| `manual/ISSUE_60.md` S3 (disciplinary refusal) | Covered | `tests/e2e/browser/runtime-guardrails.spec.ts` (refusal renders, zero mutation POSTs) |
| `manual/ISSUE_60.md` S4 (driver privacy) | Covered (browser contract) | `tests/e2e/browser/runtime-guardrails.spec.ts` (driver history only; server-side role filter proven by integration API tests) |
| `manual/ISSUE_60.md` S5 (turn idempotency/409) | Covered (browser contract) | `tests/e2e/browser/runtime-guardrails.spec.ts` (exact replay, 409 on conflict) |
| `manual/COCKPIT.md` queue/evidence/claim/dismiss | Covered | `tests/e2e/browser/cockpit.spec.ts`, `mvp-full-flow.spec.ts`, `active-queue.spec.ts` |
| `manual/COCKPIT.md` dropout/GPS-gap states | Covered | `tests/e2e/browser/gis-persisted.spec.ts`, `road-telemetry.spec.ts` |
| `MANUAL_TEST_TESTER_SIMULATION.md` | Covered | `tests/e2e/browser/tester-simulation-e2e.spec.ts` (fully mocked `/test/api`) |
| `manual/AUTHENTICATION.md` fixture-eligible steps | Covered | `tests/e2e/browser/cockpit.spec.ts` (RBAC/lease guards), `mvp-full-flow.spec.ts` |
| `manual/ROAD_TELEMETRY.md` browser playback | Covered | `tests/e2e/browser/road-telemetry.spec.ts`, `gis-persisted.spec.ts` |

## Hosted real-session coverage (no fixtures, read-only)

`tests/e2e/browser/auth/manual-flows.spec.ts` runs inside `pnpm test:e2e:auth`
(local via `AUTH_E2E_*` overrides, preview CI via `preview_url`/`backend_url`
outputs), so the same flows prove both environments:

| Runbook | Covering spec |
|---|---|
| `manual/COCKPIT.md` analyst queue -> case evidence -> overview | `manual-flows` analyst test (triage region, case tabs, zero access-denied) |
| `manual/COCKPIT.md` driver dispute read path | `manual-flows` driver test (`/driver`, dispute links, zero access-denied) |
| `manual/AUTHENTICATION.md` org scope | `manual-flows` admin test (`/api/v1/me` + `/api/v1/account/settings` 200; the `/organization` UI itself ships with epic/285) |

Writes stay out: no adjudication, no invites, no driver linking. Anything
needing writes remains a human runbook step with explicit reviewer decisions.

## Intentionally not fixture-mocked (hosted or CI-only by nature)
- `manual/AUTHENTICATION.md` live-login steps: covered by hosted opt-in
  `tests/e2e/browser/auth/live-clerk-auth.spec.ts` (`RUN_LIVE_AUTH_E2E`)
  and `role-accounts.spec.ts` (`RUN_REAL_ACCOUNT_E2E`). A fixture cannot
  prove Clerk token verification.
- `manual/DEPLOYMENT.md` D1-D9 and `MANUAL_TEST_VERCEL_115.md` hosted
  steps: CI workflow behavior; unit contracts in `tests/unit/scripts/`
  cover the gates. Claiming them from fixtures would be false proof.
- `manual/LLM_PROVIDERS.md` live-key steps: unit SDK-boundary contracts
  in `tests/unit/services/`; hosted keys stay opt-in and unrecorded.
- `manual/PHASE1_SCOPE_REVIEW.md`: documentation contracts
  (`pytest tests/unit/docs`), not browser behavior.
- `manual/ROAD_TELEMETRY.md` CLI/dataset validation: `scripts/road_dataset`
  contracts and opt-in `ISSUE63_DATABASE_URL` persistence proof.

## TDD flow

New deterministic specs follow the same loop as the real-account suite:
failing behavior first (missing route or wrong selector fails fast),
smallest fixture change, then `pnpm --dir src/webapp test:browser`
for the touched file followed by the adjacent boundary
(`test:typecheck`, backend `bash scripts/test.sh` when shared code moves).

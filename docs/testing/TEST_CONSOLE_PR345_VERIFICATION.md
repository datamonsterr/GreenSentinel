# Desktop manual console verification — PR #345

Date: 2026-10-15. Owner: Pham Thanh Dat (@datamonsterr), assisted by Codex and bounded implementation/review agents. Scope is [#370](https://github.com/AI20K-Build-Phase-Cohort-4/P-063/issues/370), [#346](https://github.com/AI20K-Build-Phase-Cohort-4/P-063/issues/346), and [#348](https://github.com/AI20K-Build-Phase-Cohort-4/P-063/issues/348). The stakeholder confirmed the desktop manual-console scope and removed mobile support. Broader generator and launch issues retain their prerequisites.

## Environment and evidence

Local Python 3.12, Node/pnpm, Chromium, disposable PostgreSQL simulation storage on loopback port 55432, and a separate disposable operational database on port 55433. PostgreSQL migrations include organization ownership, cancellation/history, explicit stop snapshots, and durable publish receipts. No customer database was used.

| Check | Observed result | Evidence class |
| --- | --- | --- |
| Backend unit discovery | 1,182 passed | Local isolated units; provider/SDK transport fixtures |
| API, tenant boundaries, operational persistence, receipt restart/concurrency | 68 passed, zero skips | Real disposable PostgreSQL and public API tests; classifier transport mocked |
| Mypy | All 83 source files passed | Static typing |
| Ruff lint and format | Passed | Static checks |
| Frontend production compilation | Passed | Next.js production build; not hosted authentication |
| Desktop browser flow and result dock | 4 passed at 1024px and 1600px | Local browser with explicit API/provider fixtures |

Frontend discovery passed 442 tests before the final replay regression; all 18 affected UI/stream tests pass afterward. Latest full discovery and hosted CI results are recorded separately in the PR. The desktop browser screenshots are Playwright artifacts named `desktop-1024.png` and `desktop-1600.png`. They contain fixture data, not real authenticated identities.

## Commands

Use [the test guide](README.md). `TMPDIR=/var/tmp/p063-pr345-temp` avoids the host's exhausted per-user `/tmp` quota; placing temporary logs inside the repository also changes the logger scope test's meaning.

```bash
APP_ENV=test TMPDIR=/var/tmp/p063-pr345-temp .venv/bin/python -m pytest tests/unit/ -q -n 2 --tb=short
.venv/bin/ruff check src/ tests/
.venv/bin/ruff format --check src/ tests/
.venv/bin/mypy src/
pnpm --dir src/webapp test
pnpm --dir src/webapp test:typecheck
pnpm --dir src/webapp build
PORT=3145 pnpm --dir src/webapp exec playwright test --config=playwright.config.ts tester-simulation-e2e.spec.ts
```

For database proof, set `TEST_SIMULATION_DATABASE_URL` and `DATABASE_URL` to the two disposable migrated databases, then run:

```bash
.venv/bin/python -m pytest -q \
  tests/integration/api/test_test_console_features.py \
  tests/integration/api/test_simulation_api.py \
  tests/integration/api/test_simulation_tenant_boundary.py \
  tests/integration/services/test_telemetry_worker_tenancy.py \
  tests/integration/services/test_simulation_publish_receipt.py
```

## Behavioral evidence

The regression suites cover organization-member admission without console role filtering; anonymous/missing-org/foreign-ID denial; persisted ownership and idempotency; explicit initial/pickup/destination snapshots; tenant-owned actor selection; honest geocoding failure; stale route/address/history handling; frozen setup during run creation; same-run controls; destination-only normal completion; reason-bearing participant cancellation; error preservation; keyboard modal behavior; stream event deduplication, cursor resume and REST reconciliation; titles/history; and metadata-only presets.

Retained RED/GREEN cycles include oversized submissions (HTTP 413 rather than truncation), concurrent publish (two processor calls before locking, one afterward), nominal Overview receipts (no fraud case required), stream cursors/reconnect, stale history/run responses after organization switches, setup freeze, modal keyboard behavior, and measured desktop layout. Earlier inherited security changes retain their original evidence limits; no retroactive test-first claim is made.

The publish receipt is scoped through the owned run. A PostgreSQL advisory lock serializes concurrent submissions across repository instances, and restart/retry tests return the recorded receipt without invoking the processor again. Stable event/assignment identities are retained. This bounded mechanism is not acceptance of the broader distributed queue/outbox durability work in #300.

Normal `COMPLETED` and participant `CANCELLED` runs may submit recorded telemetry. `FAILED` runs may be assessed as recorded diagnostic evidence in the isolated case view, but cannot masquerade as normally completed production trips. Publication above 2,000 samples fails explicitly. Process-local stream history is reconciled against persisted REST state after gaps; durable cross-process event replay remains part of the broader pipeline scope.

## Hosted acceptance boundary

Local fixtures and a green build do not prove real Clerk sessions, real-provider model quality, notifications reaching a real Driver, or broader organization launch acceptance. Follow [the manual runbook](manual/TEST_CONSOLE_AUTH.md) and [real-account guide](REAL_ACCOUNT_E2E.md). PR preview deployment and real-account results must be reported separately. No merge or production deployment is authorized by this record.

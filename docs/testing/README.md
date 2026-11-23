# Test guide

Add tests at the correct boundary. Directory discovery includes new files; do not add filenames to a runner or edit CI for each test.

| Boundary | Location | Command |
|---|---|---|
| Backend units | `tests/unit/` | `bash scripts/test.sh` |
| Backend integration/API | `tests/integration/` | `bash scripts/test_integration.sh` |
| All backend suites | `tests/unit/`, `tests/integration/`, `tests/e2e/backend/` | `bash scripts/test_backend.sh` or `.venv/bin/python -m pytest tests/` |
| Agent/RAG subset | Agent/RAG test subdirectories | `bash scripts/test_agent.sh` |
| Frontend units/components | `src/webapp/tests/unit/` | `pnpm --dir src/webapp test` |
| Browser E2E | `tests/e2e/browser/` | `pnpm --dir src/webapp test:browser` |
| Deterministic matrix (manual runbook mapping) | `tests/e2e/browser/` + fixture routes | [DETERMINISTIC_E2E](DETERMINISTIC_E2E.md) |
| Real-account browser E2E (preview/dev/staging/prod) | `tests/e2e/browser/auth/` | `E2E_TARGET_ENV=<env> RUN_REAL_ACCOUNT_E2E=true pnpm --dir src/webapp test:e2e:auth` |
| Real-session manual-flow coverage (read-only, same runner) | `tests/e2e/browser/auth/manual-flows.spec.ts` | Same command; local via `AUTH_E2E_FRONTEND_URL`/`AUTH_E2E_BACKEND_URL` overrides |
| Existing CI frontend entry | Units followed by browser E2E | `pnpm --dir src/webapp test:e2e` |
| Manual checks | `docs/testing/manual/` | [Manual guide](manual/README.md) |

Use `.venv/bin/python`, not an unrelated system interpreter. Install dependencies through existing project setup. Python fixtures live in `tests/fixtures/`; test support owns repository-root resolution. Use `pnpm --dir src/webapp test:typecheck` for unit and browser test TypeScript validation. Frontend setup/support remains beside its test configuration; the central browser specs use the installed webapp Playwright package through a thin support export.

For integration, use disposable backing services. The wrapper can provision local Docker services; set `GREENSENTINEL_EXTERNAL_SERVICES=1` only with explicit `DATABASE_URL`, `REDIS_URL` and `QDRANT_URL` to use an existing isolated environment. Never redirect tests to production. Required integration prerequisites must fail clearly; optional provider/live checks remain explicit opt-ins.

Real-account browser suites log in through the real Clerk UI with real
clicks and real data; they never install `page.route` fixtures. Setup,
per-environment URLs, and secrets live in [REAL_ACCOUNT_E2E](REAL_ACCOUNT_E2E.md).
Role credentials stay in the ignored local `.env` and GitHub Actions
secrets; only placeholders ship in `.env.example`.

Write a failing behavioral test, observe the expected failure, implement the smallest change, then run its suite. Unit tests isolate storage, HTTP, provider state, time and caches. Prefer independent expected values and real module boundaries; mock external transports rather than the result under test. Use accessible RTL queries, user events and async assertions; restore timers/mocks after each frontend test. Keep backend/browser E2E under the central E2E tree.

CI runs the preview real-account suite automatically: `preview-real-account-e2e`
in `.github/workflows/deploy-vercel.yml` needs `deploy-preview` and reuses its
`preview_url` / `backend_url` outputs with role creds from `E2E_*` secrets
(see [REAL_ACCOUNT_E2E](REAL_ACCOUNT_E2E.md)). Existing broad backend discovery and stable wrapper/package commands execute new tests automatically. The legacy CI step named “Unit Tests” still invokes broad backend discovery; the service-backed job verifies integrations separately. `test:e2e` is the compatibility bundle that executes frontend units before browser tests; `test:browser` runs only the browser suite.

Record commands, revision, environment, counts and artifacts. Distinguish fixtures, mocked SDK contracts, isolated database/API, local browser and authenticated hosted results. A deployment workflow or mocked model is not hosted/model-quality acceptance. Historical evidence keeps revision-specific command paths; use this guide for current paths. Historical evidence stays outside active runbooks; the old POC v2 workflow is [archived](archive/POC_V2_LEGACY_MANUAL.md).

Fixture browser tests use an explicit offline basemap; route/GPS sources remain the supplied case evidence. Test TypeScript checks do not emit incremental cache artifacts.

## CI job layout

The main continuous integration workflow ([`.github/workflows/ci.yml`](../../.github/workflows/ci.yml)) verifies changes across parallel, memory-bounded, cached jobs:

- `format-and-lint`: Ruff linting and formatting.
- `unit-tests`: Backend unit tests (`tests/unit/`, including agent and RAG suites in `tests/unit/agents/` and `tests/unit/rag/`) run via `uv run` in parallel with uv cache.
- `frontend-vitest`: Webapp unit tests and TypeScript typechecking.
- `webapp-build`: Webapp production build (`pnpm build` with Next.js build cache `nextjs-build-` and 3GB Node memory limit), uploading the prebuilt Next.js bundle for browser E2E.
- `integration-tests`: Docker backing services (Postgres, Redis, Qdrant) with container memory limits (`GREENSENTINEL_PG_MEMORY: 768m`, `GREENSENTINEL_REDIS_MEMORY: 256m`, `GREENSENTINEL_QDRANT_MEMORY: 768m`), serialized under concurrency group `greensentinel-docker-services`, running migrations, seeds, and the integration suite via [`scripts/test_integration.sh`](../../scripts/test_integration.sh). Integration tests are dynamically discovered via the `docker` pytest marker (`-m docker`). To add a new integration test requiring Docker services, add `pytestmark = pytest.mark.docker` to the test file.
- `browser-e2e`: Playwright E2E browser tests (runs `next start` on isolated test bundle) with downloaded build bundle and retries capped at 1, configurable via `PLAYWRIGHT_SERVER_MODE`, bounded by concurrency group `greensentinel-browser-e2e`.
- `build-and-cache`: Docker Compose configuration validation and backend image build verification run alongside the tests.

The isolated persisted GIS gate has been removed from automated CI and is run manually when needed via [`scripts/test_gis_persisted.sh`](../../scripts/test_gis_persisted.sh).

CI jobs run on GitHub-hosted Linux runners. Frontend jobs restore the shared pnpm store keyed by the webapp lockfile. The frontend test job saves new entries on pushes to `main`.

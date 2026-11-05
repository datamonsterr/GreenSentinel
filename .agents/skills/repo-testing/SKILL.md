---
name: repo-testing
description: Run and improve GreenSentinel unit, integration, E2E and manual verification with boundary-based discovery and honest evidence.
---

# Repository testing

Read [the test guide](../../../docs/testing/README.md). Use `.venv/bin/python`; preserve unrelated work and backing services.

- Place Python units in `tests/unit/`, cross-service/API checks in `tests/integration/`, all E2E in `tests/e2e/{backend,browser}/`, and frontend units/components in `src/webapp/tests/unit/`.
- Add tests by directory; never maintain filename lists. Use `scripts/test.sh`, `test_integration.sh`, `test_backend.sh`, `test_agent.sh`, and webapp `test`, `test:browser`, `test:e2e` commands.
- Follow RED, smallest implementation, GREEN. Test observable behavior and independently expected data; mock external boundaries only.
- Units must not call real storage, HTTP or model providers. Reset caches, timers and mocks. Prefer accessible RTL queries, user events and async assertions.
- Use explicit disposable integration targets. Required prerequisites fail; optional live provider checks need their documented opt-in and configured credentials. Never print keys or read credential files for test setup.
- Run browser tests and production build sequentially in one webapp checkout. Do not reuse or terminate another listener.
- Manual runbooks live in `docs/testing/manual/`; results include revision, environment, case IDs, actual steps and artifacts. Distinguish fixture, isolated/local, SDK-mock and authenticated hosted proof.
- Real-account browser E2E (`tests/e2e/browser/auth/`, `docs/testing/REAL_ACCOUNT_E2E.md`): real Clerk UI clicks per role, no `page.route` fixtures, traces/screenshots off. PR previews run them in CI (`preview-real-account-e2e` reuses `deploy-preview` URL outputs plus `E2E_*` secrets). Related skills: `clerk`, `clerk-cli`, `vercel-cli`, `github-actions-docs`, `test-driven-development`; Playwright stays the runner.
- Before completion, inspect fresh full results and the diff. Report failures/skips exactly; green deployment automation does not establish hosted acceptance. Read `CONTRIBUTING.md` for PR and attribution requirements.

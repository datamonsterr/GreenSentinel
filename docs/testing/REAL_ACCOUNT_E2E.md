# Real-account browser E2E (preview / dev / staging / prod)

Real Clerk UI login with real clicks. No `page.route` fixtures, no sign-in
tickets. Three role accounts cover analyst, driver, and admin flows against
real backends and real data.

## Accounts

| Role | Email | Password env |
|---|---|---|
| Analyst (member) | `analyst@greensm.com` | `E2E_ANALYST_EMAIL` / `E2E_ANALYST_PASSWORD` |
| Driver | `driver@gmail.com` | `E2E_DRIVER_EMAIL` / `E2E_DRIVER_PASSWORD` |
| Admin | `admin@greensm.com` | `E2E_ADMIN_EMAIL` / `E2E_ADMIN_PASSWORD` |

Passwords live only in the ignored local `.env` and in GitHub Actions
secrets. Placeholders stay in `.env.example`. This repo is public.

## Skills

Routed dynamically via `jev-skill-selector`; pre-installed in
`.agents/jev_skills/`:

| Task | Skill |
|---|---|
| Real-account sign-in, session checks, test-user management | `clerk`, `clerk-cli` |
| Preview URLs, deployment inspection | `vercel-cli` |
| CI workflow authoring and debugging | `github-actions-docs` |
| Red-green-refactor loop for new specs | `test-driven-development` |

The runner stays Playwright (`pnpm test:e2e:auth`).
`agent-browser-automation` (CDP CLI) is not used by this suite.
`manual-flows.spec.ts` (read-only manual-runbook coverage) runs in the same
command, locally and in preview CI — no separate wiring.

## Local setup

```bash
cp .env.example .env   # first time only
```

Add to `.env` (ignored by git):

```bash
E2E_ANALYST_EMAIL=analyst@greensm.com
E2E_ANALYST_PASSWORD='<analyst-password>'
E2E_DRIVER_EMAIL=driver@gmail.com
E2E_DRIVER_PASSWORD='<driver-password>'
E2E_ADMIN_EMAIL=admin@greensm.com
E2E_ADMIN_PASSWORD='<admin-password>'
E2E_TARGET_ENV=preview
RUN_REAL_ACCOUNT_E2E=true
# Preview only: point at the PR-specific URLs from the Railway/Vercel comments.
AUTH_E2E_FRONTEND_URL=https://<pr-preview>.vercel.app
AUTH_E2E_BACKEND_URL=https://<pr-preview>.up.railway.app
```

## Run per environment

```bash
cd src/webapp
# Preview (PR URLs required, see above)
E2E_TARGET_ENV=preview RUN_REAL_ACCOUNT_E2E=true pnpm test:e2e:auth
# Dev
E2E_TARGET_ENV=dev RUN_REAL_ACCOUNT_E2E=true pnpm test:e2e:auth
# Staging
E2E_TARGET_ENV=staging RUN_REAL_ACCOUNT_E2E=true pnpm test:e2e:auth
# Prod (read-only clicks; no adjudication writes)
E2E_TARGET_ENV=prod RUN_REAL_ACCOUNT_E2E=true pnpm test:e2e:auth
```

Default URL map (overrides win):

| Env | Frontend | Backend |
|---|---|---|
| preview | PR Vercel URL (`AUTH_E2E_FRONTEND_URL` required) | PR Railway URL (`AUTH_E2E_BACKEND_URL` required) |
| dev | `https://green-sentinel-dev.vercel.app` | `https://greensentinel-backend-dev.up.railway.app` |
| staging | `https://green-sentinel-staging.vercel.app` | `https://greensentinel-backend-staging.up.railway.app` |
| prod | `https://green-sentinel.vercel.app` | `https://greensentinel-backend-production.up.railway.app` |

Traces, screenshots, and video stay off in
`tests/e2e/browser/auth/playwright.config.ts` so credentials never persist
in artifacts. The suite revokes nothing; it uses normal Clerk sign-in and
leaves hosted data untouched (analyst spec reads and reloads only).

## GitHub secrets

`gh` must be authenticated (`gh auth login`). Secret names match the `.env`
keys:

```bash
gh secret set E2E_ANALYST_EMAIL --body 'analyst@greensm.com'
gh secret set E2E_ANALYST_PASSWORD --body '<analyst-password>'
gh secret set E2E_DRIVER_EMAIL --body 'driver@gmail.com'
gh secret set E2E_DRIVER_PASSWORD --body '<driver-password>'
gh secret set E2E_ADMIN_EMAIL --body 'admin@greensm.com'
gh secret set E2E_ADMIN_PASSWORD --body '<admin-password>'
```

Verify with `gh secret list` (names only; values never print).

## CI preview run

Every PR preview deployment runs this suite automatically. Job
`preview-real-account-e2e` in `.github/workflows/deploy-vercel.yml` needs
`deploy-preview` and takes both URLs from its outputs: no scraping of PR
comments, no hardcoded URLs.

- Frontend URL: `deploy-preview` output `preview_url` (the `vercel deploy`
  result from `scripts/vercel_deploy.sh`), passed as `AUTH_E2E_FRONTEND_URL`.
- Backend URL: `deploy-preview` output `backend_url` (scoped Railway PR
  preview, or stable dev backend for frontend-only PRs), passed as
  `AUTH_E2E_BACKEND_URL`.
- `E2E_TARGET_ENV=preview`, `RUN_REAL_ACCOUNT_E2E=true`, role creds from
  the `E2E_*` secrets above.

Missing secrets skip the job with a step-summary note (fork PRs have no
secret access); with secrets present a failure blocks the PR. Results land
in the job summary plus a PR comment. Rerun from the Actions tab
(`Deploy Vercel` workflow, re-run `preview-real-account-e2e`), or locally
with the PR URLs from the Vercel/Railway bot comments.

## TDD flow

1. Write the failing behavioral test first (`role-accounts.spec.ts` per role).
2. Observe the expected failure (missing creds or wrong env URLs fail fast).
3. Implement the smallest change (helper, selector, or origin allowlist).
4. Run its suite (`pnpm test:e2e:auth`), then the adjacent boundary:
   `bash scripts/test.sh`, `pnpm --dir src/webapp test`,
   `pnpm --dir src/webapp test:typecheck`.
5. Record commands, revision, environment, and counts in the PR. Fixture
   suites stay local; hosted real-account runs are the acceptance proof.

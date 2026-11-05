# Authentication hotfix verification — issue #104

Date: 2026-10-02. Owner: Pham Thanh Dat (`datamonsterr`), assisted by Codex.
Source baseline: `05c685e`. [Incident](https://github.com/AI20K-Build-Phase-Cohort-4/P-063/issues/104).

## Reproduction and introducing commits

A real Clerk browser login on both `https://p-063.vercel.app/workplace` and
`https://p-063-dev.vercel.app/workplace` succeeded. Their automatic `/api/v1/me`
and `/api/v1/cases?availability=available` requests carried Bearer tokens but
returned `401 {"detail":"Unauthorized browser origin"}`.

Production's deployed `CLERK_AUTHORIZED_PARTIES` still contained the two old
`p063-sentinel-cockpit` origins. The dev backend used defaults that omitted the
actual `p-063-dev.vercel.app` hostname. The configured Clerk issuer and JWKS
matched the browser tokens; refreshing a token did not resolve the rejection.

- `97fa024` introduced the Vercel dev fallback alias `p-063-dev.vercel.app`
  without adding that exact hostname to the backend origin defaults.
- `16c1ad6` removed permissive Vercel/localhost matching and propagated origin
  rejection in dev/staging as well as production. This exposed the stale
  production configuration and the missing dev hostname. With identical valid
  RS256 claims and the old production allowlist, its parent accepts the token;
  `16c1ad6` and the current baseline reject it with the reported 401.
- The obsolete production environment value is external Railway state. Its
  original author/change cannot honestly be assigned to a Git commit.

The hotfix retains exact origin, signature, issuer, expiration, and database-role
checks. It repairs the explicit deployment configuration and adds the current
dev hostname to defaults. It does not restore suffix/wildcard authentication.

## Verification boundary

The positive browser checks use the actual hosted frontends and actual Clerk
sign-in/session tokens. Playwright forwards their API requests to a real local
FastAPI backend; it does not supply fixture response bodies. The backend runs
with `APP_ENV=production`, genuine Clerk verification, and a separately migrated
and seeded disposable PostgreSQL database. A dedicated QA identity has an
explicit analyst principal only in that disposable database.

This proves the fix with production authentication enabled. It does not prove
that hosted production has been repaired: production deployment remains a
separate gated release. The supplied staging frontend URL was the production
URL; the documented distinct staging aliases returned 404 or failed DNS.
Staging origins have signed-JWT/API contract coverage, not a hosted staging
browser acceptance claim.

## Automated evidence

| Check | Observed result |
|---|---|
| Full isolated backend `pytest tests/ -q --tb=short` on `456e78f` after rebasing onto `241e161` | 687 passed, 8 skipped; 14 subtests passed |
| Genuine signed JWT and deployment/provisioning contracts | 32 passed |
| Preview rollout CLI contracts | 6 passed; explicit PR scope, submitted deployment completion, and health required |
| Preview workflow ordering contracts | 4 passed; exact PR/head, queued/in-progress, failure/cancellation, and timeout |
| Workflow metadata transport contracts | 2 passed; authenticated REST when `gh` is unavailable, no anonymous fallback |
| Frontend Vitest | 126 passed |
| Existing Playwright UI suite | 9 passed; API fixture coverage |
| Real Clerk production-origin browser flow | 1 passed; automatic `/me` and `/cases`, case detail, reload, 65-second refresh interval |
| Real Clerk dev-origin browser flow | 1 passed with the same checks |
| Frontend build, TypeScript, focused ESLint | Passed |
| Ruff lint/format | Passed |
| `bash scripts/check.sh` | Mypy blocked by installed NumPy stubs: `numpy/__init__.pyi:737: Type statement is only supported in Python 3.12 and greater` under the configured Python 3.11 target |

The original run passed 594 tests. After the hotfix was rebased onto the newly
accepted documentation changes at `241e161`, the complete isolated run passed
677 tests in 177.61 seconds with the same eight skips and 14 passing subtests.
The 32 focused signed-token and deployment contracts also passed on that head.

The [preview workflow contracts](../../../tests/unit/scripts/test_preview_workflow.py)
execute the actual authorization step against CLI stubs. The positive case was
observed failing first with `missing scope: --environment pr-108`, then passing
after restoring the explicit PR environment. Six cases cover success, failed or
incomplete deployment despite another deployment succeeding, missing submission
ID, upload failure, and unhealthy backend. The submitted ID comes from Railway's
detached JSON response; a status-only CI response is insufficient.

Adding those six CLI contracts brought the complete isolated run on `63103ff`
to 683 passing tests, eight skips and 14 passing subtests in 178.24 seconds.
All CI and both previews passed on that head after sequencing the backend
provisioning and frontend authorization runs.

The exact-ID gate exposed a workflow race: backend provisioning submitted a
replacement seven seconds after frontend authorization, leaving the latter
deployment `REMOVED`. The frontend now waits for the matching PR number and head
SHA's Railway provisioning workflow before changing origins. Four ordering
contracts reject unrelated runs, failed/cancelled workflows and timeouts. The
42 focused origin, provisioning and preview contracts pass together. A real
read-only `wait-provisioning` call also accepted the completed matching workflow.

The complete ordering-head run on `456e78f` passed 687 tests in 176.80 seconds,
with the same skips and subtests. CI then exposed a runner without `gh`.
Two transport regressions were observed failing first with `FileNotFoundError`;
the metadata reader now uses the runner's `GH_TOKEN` for authenticated REST when
the CLI is unavailable. It requires credentials and retains the exact PR/head
checks. All 44 focused contracts pass.

The full run includes the existing live OpenRouter/Gemini agent tests using an
authorized test credential. The initial credential-free run failed three such
tests; providing the credential made all three pass. The isolated full run also
exposed an existing driver test fixture that omitted the required
`external_subject`; the fixture now supplies a unique test subject.

The new default-origin regression was observed failing first with
`401: Unauthorized browser origin`, then passing after the default changed.
Negative contracts reject an arbitrary `attacker.vercel.app`, a lookalike host,
a forged signature, expiration, and a different issuer.

## Manual browser procedure and observed result

Run against an isolated backend/database when performing writes.

1. Sign in through Clerk and complete the required organization selection.
2. Open the workplace. Verify `/me`, case queue, case detail, progress SSE,
   workflow trace, dispute dossier, and agent session requests authenticate.
3. Select the seeded case ending `000040`; inspect the map and recorded
   driver–customer conversation.
4. Click **Claim case**. Verify the authenticated claim succeeds and the button
   changes to **Release case**.
5. Enter an evidence-based rationale; open **Send decision** and choose
   **Dismiss**. Verify the authenticated adjudication succeeds and **Dismiss
   saved** appears.
6. Reload the browser and independently query the disposable database. Verify
   the case remains `resolved`, version `2`, with the QA analyst's adjudication.
7. Wait beyond the 60-second Clerk token lifetime and refresh the queue. Verify
   valid requests continue to return 200; invalid origins still return 401.

Observed: all listed API requests returned 200. Claim and adjudication used the
real API and persisted in the disposable database; no hosted case was changed.
[Manual browser evidence](../assets/auth104/manual-dismiss.png) shows the loaded
case workspace and **Dismiss saved** result. The data in this evidence is
explicitly synthetic seed data.

## Repeat the real authentication check

Configure a test user with an approved application principal, and an active
Clerk organization when organization selection is required. Keep credentials in
the environment. Set `AUTH_E2E_FRONTEND_URL` and `AUTH_E2E_BACKEND_URL` to the
matching frontend and real backend. Backend forwarding is optional; a hosted
backend may be used directly after release.

```bash
cd src/webapp
RUN_LIVE_AUTH_E2E=true AUTH_E2E_WAIT_SECONDS=65 pnpm test:e2e:auth
```

Required credential variables: `CLERK_SECRET_KEY`, `CLERK_TEST_USER_ID`.
Optional organization variable: `CLERK_TEST_ORGANIZATION_ID`.
The test revokes only its own session. Traces, screenshots, and videos are
disabled for this suite so credentials and sign-in tickets are not retained.

## Release verification

After an authorized deployment, run the same real-login checks against the
hosted backend. Check the scoped Railway environment's actual
`CLERK_AUTHORIZED_PARTIES` value; default code values do not override a stale
explicit environment variable. Confirm unmapped principals still receive 403,
and arbitrary Vercel origins still receive 401. Keep the parent incident open
until hosted release verification is recorded.

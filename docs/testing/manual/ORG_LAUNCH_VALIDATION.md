# Organization launch validation: 2026-10-13

This is a revision-bound validation record and continuation runbook for [epic #285](https://github.com/AI20K-Build-Phase-Cohort-4/GreenSentinel/issues/285) and [PR #312](https://github.com/AI20K-Build-Phase-Cohort-4/GreenSentinel/pull/312). Acceptance is **not met**. Live inspection supersedes the earlier handoff's claims of completed hosted proof.

## Revision and environments

The published PR remains at `171de9e6260a4240c05afba207a9662d84caeb26` on `epic/285-org-setup`. Local repairs are assembled on `verify/285-dod-20261013` in `/tmp/greensentinel-epic285-verify`; they have not been exported or deployed.

- Frontend: `https://green-sentinel-47dhf7jz8-datpt226024-husteduvns-projects.vercel.app`
- Backend: `https://greensentinel-backend-pr-312.up.railway.app`
- Railway environment: `pr-312`, `04ac3ba6-51ad-47fb-ba83-0f5391367027`
- Preview database repair deployment: `92cd440f-4f63-4be1-ace8-afe5b835de8c`, observed `SUCCESS`

## Live database and identity evidence

Independent read-only SQL checks confirmed the organization isolation and bootstrap migrations in all four databases. Preview has `20261012000000_org_isolation.sql` and `20261013000000_org_bootstrap.sql`. The unrelated case-document migration was not present in preview, contrary to the previous handoff.

| Environment | Total distinct drivers | Total distinct customers | Bootstrap cohort | State |
|---|---:|---:|---|---|
| pr-312 | 100 | 1000 | 100 / 1000 | ready |
| dev | 120 | 1050 | 100 / 1000 | ready |
| staging | 120 | 1050 | 100 / 1000 | ready |
| production | 120 | 1050 | 100 / 1000 | ready |

Customers are stored in `app.passengers`, not `app.customers`. Existing legacy rows account for the additional 20 drivers and 50 customers outside preview. They were preserved. Cohort counts do not establish that every existing organization has exactly 100/1000 total entities.

Preview bootstrap was rerun and independent total counts remained 100/1000. Verified Clerk email lookup resolved the three named test subjects; no dashboard input or guessed identity was used. The preview principals received only their requested Analyst, Driver, and Admin grants. Driver was explicitly linked to one same-organization bootstrap entity. The patched principal SQL was also exercised against the real preview database and returned each persisted grant, including the Driver link.

The important deployment defect was a different database destination: preview backend `DATABASE_URL` pointed to dev, so provisioning pr-312 could not repair its authorization failures. Only the preview backend was rebound to `${{Postgres.DATABASE_URL}}`. The new deployment succeeded. The local setup-script repair prevents subsequent rebuilds from copying `DEV_DATABASE_URL` back into preview.

For independent verification, run read-only queries against the explicitly selected environment:

```sql
SELECT version FROM public.schema_migrations ORDER BY version;
SELECT organization_id, status, drivers_created, customers_created
FROM app.org_bootstrap_state;
SELECT organization_id, count(*), count(DISTINCT id)
FROM app.drivers GROUP BY organization_id;
SELECT organization_id, count(*), count(DISTINCT id)
FROM app.passengers GROUP BY organization_id;
```

Use the environment's public Postgres connection only in memory. `railway variable list --json` includes credentials; never print its raw output. Do not repeat the earlier runbook's claim that it prints only keys.

## Hosted browser observations

A real local Chromium session opened `/`, `/organization`, and `/workspace` signed out. All reached the rendered Clerk sign-in form. No page JavaScript errors were observed. The embedded browser renderer was disconnected; the local browser supplied the observation. The signed-out capture is `/tmp/epic285-signin.png`; it contains no credentials or authenticated session state.

Unauthenticated `/api/v1/me` and `/api/v1/admin/invitations` returned 401. Backend health returned `database: connected`. These are routing and denial checks, not authenticated organization acceptance.

Real-account CI run [38328925500](https://github.com/AI20K-Build-Phase-Cohort-4/GreenSentinel/actions/runs/38328925500), attempt 3, still failed after the database correction:

- Analyst: `/api/v1/me` returned 403.
- Driver: `/api/v1/me` passed, but `/driver` displayed `Access denied`.
- Admin: navigation failed with `net::ERR_NETWORK_CHANGED` before access assertions.
- The separate optional live-token test was skipped. It is not acceptance evidence.

The local Vercel submission repair passes the backend URLs into deployment runtime as well as the build, addressing a concrete configuration gap at the middleware boundary. Hosted browser proof for that repair requires publication and a new preview. No authenticated screenshots, traces, passwords, tokens, or browser state are retained in this record.

## Local repair evidence

Repairs cover preview database binding, Vercel runtime backend URLs, the three integration fixture regressions, root redirects swallowed by Next.js control-flow exceptions, and persisted authorization boundaries.

Authorization regressions reproduced **6 failures / 2 passes** against the original code. The repairs preserve database-owned roles, deny inactive and ambiguous identities, scope UUID claims before writes, and deny unprovisioned native Clerk organization claims. A single explicitly provisioned personal session remains compatible with existing behavior; it does not prove active-organization switching. Native `org_*` mapping still requires an accepted contract.

Root tests use throwing Next.js redirect/not-found mocks. Additional denial tests reproduced **4 failures / 9 passes** before tightening canonical routes, forbidding an authorization-denial fallback, and requiring assigned roles. The final focused root suite passed **13 tests**.

| Verification | Observed result |
|---|---|
| Automatically discovered Python units | 852 passed, 13 warnings |
| Combined authentication/org/access API tests | 120 passed |
| Preview setup and workspace fixture tests | 30 passed |
| Full Ruff lint and formatting | passed |
| TypeScript and changed frontend ESLint | passed |
| Configured `next build --webpack` | passed |
| Required `scripts/check.sh` | blocked by 7 MyPy errors in unchanged baseline files; same errors reproduced on `171de9e` |
| Full frontend suite with two workers | 307 passed across 40 files; default parallelism caused timing failures on both baseline and patched code, so local configuration now limits workers to two |

The MyPy failures are in motivation assessment, RAG embedder/store, and test routes. They are not new authorization errors. A successful build or focused test run does not make the full quality gate green.

The separately dispatched CI repair run [38351454598](https://github.com/AI20K-Build-Phase-Cohort-4/GreenSentinel/actions/runs/38351454598) passed lint and Python units, but frontend validation was cancelled and integration could not start Docker: `all predefined address pools have been fully subnetted`. The integration code was not exercised by that failure. No shared Docker networks or services were pruned during this audit.

## Acceptance gaps and continuation

Required children #290/#294/#295/#296 remain open. The #291 contract and #292 design prerequisites also remain open; a checked-in ADR does not close their entire accepted scope.

Actual invitation create/resend code is an in-memory stub; it does not deliver Clerk invitations. This is an acceptance blocker, not an operational non-blocker. Organization creation, verified native-organization mapping, invitation acceptance, role revocation across real sessions, and authenticated A/B switching still need implementation and proof. Empty-roster guidance also currently excludes an entirely empty roster.

After publishing the reviewed repairs and obtaining the missing organization contract/design decisions:

1. Verify the exact preview revision and successful backend/frontend deployments. Confirm backend uses its own database and middleware uses that preview backend at runtime.
2. Sign in each real account. Assert the initial route from `/`: Admin `/organization`, Analyst `/workspace`, Driver `/driver`; repeat after reload and direct links.
3. Verify Analyst cannot access organization administration and Driver cannot access Analyst cases or another driver's stream/chat.
4. Create a fresh organization through the real supported flow. Verify creator Admin, empty/no-analyst guidance, and exactly 100 distinct drivers plus 1000 customers after repeated bootstrap.
5. Send, resend, revoke, and accept a real invitation. Verify persisted membership and assigned role after a fresh session; revoke/demote roles and confirm stale sessions cannot restore them.
6. Switch between organizations A/B and exercise reads, writes, search/counts, SSE, and swapped IDs. Record actual case IDs and observed denials without retaining session secrets.
7. Run current-head CI after fixing runner subnet exhaustion. Complete full acceptance before using `Closes #285` or merging.

Automatic approval review rejected external GitHub code export because trusted user content did not explicitly authorize that export. The patches and evidence remain local for review; publication requires explicit user approval. External context compression was also rejected, so local handoff files were used instead.

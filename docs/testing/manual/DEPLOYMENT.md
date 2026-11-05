# MANUAL TEST DEPLOYMENT 107

Purpose: verify Issue #107 deployment previews and approval gates. Evidence remains pending until a reviewer runs these checks against the target branch.

## Preconditions

- Repository checkout at the reviewed PR head.
- GitHub Actions access and the configured Vercel/Railway preview credentials.
- A pull request with a known head SHA.
- No production credentials in preview jobs.

## Checks

| ID | Scenario | Expected result | Evidence to record |
|---|---|---|---|
| D1 | Docs-only PR | Both workflows trigger; deployment is skipped | Run URLs and skip logs |
| D2 | Fork PR | Validation may run; deployment is skipped without secrets | Run URL and event log |
| D3 | Frontend-only `src/webapp` PR | Stable Dev backend is used immediately; no Railway provisioning/wait | Run log and preview URL |
| D4 | Backend/full-stack PR | Isolated `pr-N` environment; exact PR/head Railway workflow, deployment ID, 120-second health gate | Railway run, deployment ID, health response |
| D5 | Failed or unrelated Railway deployment | Vercel job fails closed; no shared-backend fallback | Failed run log |
| D6 | Exact preview authorization | Preview origin is added to existing Dev allowlist through serialized rollout; no wildcard | Authorization deployment log and resulting allowlist |
| D7 | Vercel readiness/error | Error propagates; readiness wait requires `READY` | Vercel run log |
| D8 | Staging/prod dispatch | Staging is selective; production succeeds only from `main` | Dispatch inputs and run logs |
| D9 | Live rules guard | Missing reviewers or non-main production fails closed; current rules `PUT` HTTP 404 is recorded as unconfigured | API response and guard log |
| D10 | Persistent environment code upload | Config apply is followed by a source upload; the exact returned deployment ID reaches `SUCCESS` before health checks | Checkout SHA, upload deployment ID, terminal status |
| D11 | Staging contract smoke | A bounded read-only probe verifies healthy staging/database and the account-settings authentication contract; stale routes, unhealthy responses, and timeouts fail | Probe output and workflow URL |
| D12 | Authenticated staging organization | Sign in with an existing authorized staging account, open `/organization`, and reload. Account settings and `/api/v1/me` return 200; the organization page does not show Access denied | Frontend/backend URLs, role, time, and redacted observations |

For D12, keep tokens and credentials out of screenshots, logs, and reports. An
unauthenticated 401 proves the route is protected; it does not prove signed-in
organization access. Token-authenticated API checks and browser sign-in are
separate evidence. The contract smoke does not create trips or prove a synthetic
trip lifecycle.

## Evidence record

Record date, actor, PR/head SHA, workflow run URLs, Railway deployment ID, preview URL, health response, and any failure. Do not claim hosted success from local or fixture tests. No migration or data changes are part of this test.

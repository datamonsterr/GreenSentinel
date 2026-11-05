# Driver motivation assessment

## Contract and source evidence

`DriverMotivationAssessment` contains the estimated incremental reward in VND,
an advisory intent profile, and a Vietnamese prose narrative. It never authorizes
a sanction or proves intent. The factual forensic summary and reviewer rationale
remain separate from the motivation hypothesis.

The database path compares recorded `trips.fare_amount_vnd` with the latest fare
quote. This repository stores quote amounts as 100 minor units per VND (see the
synthetic generator); conversion uses that contract and requires currency VND.
Display default fares are excluded. This total delta is incentive-inclusive, so
surge and subsidy are not added again. Explicit feature inputs may instead supply
`fare_delta_vnd`, `surge_capture_incremental_vnd`, `subsidy_incremental_vnd`, and
`fare_delta_includes_incentives`. Separate incentive breakdowns require their own
source evidence; they are never inferred from a total fare.

Missing/nonpositive delta or missing telemetry yields reward `0.0` and
`unclear_insufficient_data`. Provider failures, a five-second timeout, invalid
language, or template output yield a concise factual Vietnamese fallback. Input
instructions are excluded from the model's whitelist of measured facts.
Process-local caching uses evidence and the source trip/case identity after authorization for five minutes;
it does not persist narratives across restarts or different API processes.

## Local automated verification

From the repository root, with its Windows virtual environment:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_services/test_motivation_assessment.py -q
```

Frontend checks from `src/webapp`:

```powershell
node node_modules/vitest/vitest.mjs run
node node_modules/typescript/bin/tsc --noEmit
node node_modules/next/dist/bin/next build --webpack
```

Provider mocks prove the contract and fallback behavior, not live narrative
quality. Component tests use synthetic evidence, not hosted authentication.

## Verification record — 2026-10-09

Baseline: `4c677cf`, branch `feat/driver-motivation-assessment`, uncommitted feature changes.

- Required motivation unit/contract file: 33 passed. Includes economics, timeout,
  language/instruction fallback, API role denial, case/tool consistency, Jev and
  concurrent generation.
- Motivation plus existing Jev anomaly tests: 39 passed before the final cache
  scope adjustment; the complete 33 motivation tests passed again afterward.
- Existing factual summary and Copilot forensic-routing regressions: 2 passed,
  6 deselected. These use generated local synthetic JSON and offline database,
  Redis, OSRM and Qdrant configuration.
- Frontend: 35 test files / 257 tests passed; TypeScript passed.
- Next.js production build passed after allowing font download. Existing
  middleware/Edge Runtime warnings remain.
- Scoped Ruff lint, formatting, and `git diff --check` passed.

The broader legacy forensic integration run was interrupted while waiting in its
API path; it is not a full integration pass. No production database was changed.
No live-model, authenticated browser, deployment, or hosted acceptance is claimed.

## Local screenshot observation — 2026-10-10

The user supplied a screenshot of local `/workplace` in E2E Mode, selected case
`#00000020`. The Overview motivation card displayed 15,000 VND and insufficient
intent evidence; Copilot's Vietnamese motivation query returned the same amount
and assessment. This uses manually adjusted synthetic economics (10,000 fare
delta + 2,000 surge + 3,000 subsidy), not persisted hosted fare evidence.
Case switching, hosted Clerk authentication and successful live LLM generation
are not established by this screenshot. The existing violation card still makes
a stronger intent claim; that detector's wording needs separate review.

## Human acceptance

### GIS selection follow-up — 2026-10-10

Persisted GIS browser evidence at `f0e33ee` showed 4/6 passing tests. The gap test
ended on the first queue case after a network-change error, instead of its chosen
GPS-gap case. Selection rendering measured 1,834 ms against the unchanged
1,500 ms budget. Every stream emitted four pipeline statuses, each triggering
queue/analyst reads; non-silent refresh failures also cleared selection.

The follow-up retains selection across failed refreshes, refreshes silently on
terminal/lifecycle events rather than intermediate pipeline stages, and guards
background detail responses against selection changes. Queue/live regression
suites passed 17 tests locally, including failed refresh and intermediate stream
progress. Persisted GIS browser and timing acceptance require fresh CI evidence;
the timing limit and GPS gap assertions are unchanged.

Fresh Windows Chromium verification used disposable PostGIS/Redis containers,
database `issue61_motivation`, API port 18690 and frontend port 3169. The warm-map
test now requires an existing visible MapLibre container/canvas before waiting
for its overlay to disappear: an absent overlay must not count as a warm map.
With the corrected prerequisite, all 6 persisted GIS tests passed (1.5 minutes),
including the original gap test and a 1,296 ms fresh selection against the same
1,500 ms budget. The earlier local degraded-Redis runs passed 5 tests but failed
timing (3,339 ms before warm readiness and 1,779 ms afterward); these are not
passing evidence. Local DB/browser proof remains distinct from fresh CI/hosted
acceptance. The temporary Windows launch config is not included in the PR.

### CI regression follow-up — 2026-10-10

Exact-head CI at `6b58eaf` reported 806 passing units and one failure: the
wrong-direction Jev assessment lost its existing `Điều 16.1` reference when
motivation replaced the old brief. The follow-up preserves classifier-supplied
article references separately from the natural motivation prose. The existing
kinematic tests and required motivation contract tests then passed together
(44 tests); the original failure was reproduced before the fix.

At that revision, hosted Preview was blocked by Railway's expired trial. RAG indexing failed
with Gemini `402 RESOURCE_EXHAUSTED` (prepayment credit depleted). Neither
provider failure establishes a failure of the motivation unit contract.

At `dd57550`, after Railway renewal, Railway backend and Vercel frontend Preview
deployment both passed in run `38059805461`. Hosted role-account acceptance still
failed: the sign-in helper selected a social OAuth Continue button and waited for
a disabled password input (three failed roles, one skipped optional ticket test).
CI run `38059805237` passed five persisted GIS checks but measured 1,583 ms for
fresh case selection against the unchanged 1,500 ms limit. This supersedes the
local 1,296 ms result as hosted-runner performance evidence; CI is not green.
RAG run `38059805224` still failed during Gemini embedding with depleted credits.

The follow-up scopes login clicks to native credential-form submit buttons and
waits for an enabled password field. It also publishes case details before an
optional forensic-brief request completes; a delayed-response regression checks
that detail appears first and the factual rationale updates afterward. Local
checks passed: 33 motivation backend tests, 18 frontend tests covering auth,
motivation and live Cockpit behavior, and both frontend test TypeScript projects.
The GIS trace contains no separate forensic-brief request, so this follow-up does
not establish a fix for the 1,583 ms CI measurement. Fresh hosted login and GIS
performance results remain required.

At `5824093`, CI deployment and backend Unit Tests passed, but the local E2E job
stopped at nine frontend test timeouts (257 passed); persisted GIS did not run.
The same nine failures were reproduced locally. The optional brief call could
throw synchronously before its rejection handler was attached, setting the case
detail error. Moving invocation inside the promise chain catches both synchronous
and asynchronous failures. A regression covers the synchronous failure, and the
complete frontend suite then passed 267/267 on Windows. Windows-only Node shell
quoting diagnostics still appeared in script tests; this is not hosted browser
proof. The hosted auth trace also selected a Clerk password input with
`tabindex=-1` behind a divider; selectors now exclude that input. Real-account
CI remains the required verification for the selector fix.

At `77a97e6`, CI Unit Tests passed. The local E2E job passed all 262 frontend
units, then failed before browser execution because the motivation test fixtures
lacked required `generated_at` and `case.version`. The follow-up supplies those
fields and uses typed assignments instead of casts. Both test TypeScript
projects and the three motivation component tests passed locally afterward.

Use a disposable case and an authorized analyst account. Record revision,
environment, case ID, input economics, and actual results.

1. Open `/workplace`, select an active escalated case, and enter Overview.
2. Check the Forensic Brief card displays an intent label, Vietnamese narrative,
   and estimated incremental reward. Compare the amount with the recorded fare
   and quote, or explicitly sourced incremental components.
3. Confirm a case without economic evidence shows zero and insufficient intent
   evidence rather than an invented estimate.
4. Open Copilot and ask `Tóm tắt động cơ và hành vi của tài xế`. Confirm the
   narrative and reward agree with the selected case's assessment, and the answer
   still includes factual forensic evidence.
5. Change cases and verify the previous case's assessment is not retained.
6. On an isolated provider test, simulate timeout/non-Vietnamese output; confirm
   the endpoint and card remain usable with a Vietnamese fallback.

Do not dismiss, fine, or suspend a case as part of these read-only checks. Hosted
and live-provider acceptance remain pending until these observations are recorded.

### PR #240 follow-up: GIS lifecycle and Clerk controls (2026-10-11)

Follow-up measurement uses an optimized `.next-gis` test artifact rather than
`next dev`. Twenty target selections after one untimed warm-up produce the
nearest-rank p95, with the unchanged 1,500 ms budget. Each selection must fetch
fresh detail, leave the previous case's GPS source, and render both routes and
the observed GPS on a visible map. The attachment retains every sample;
this is warm-selection evidence, not cold-start or hosted acceptance proof.
The artifact is loopback-only and must never be deployed. Its explicit GIS
test flag requires a loopback API and existing test-auth settings; middleware
still requires authentication on hosted request domains. Normal builds retain
the production authentication policy. Local validation passed 283 frontend
tests, followed by 22 route/auth tests including a hosted Host-header denial,
and TypeScript checks. Optimized compilation and local workspace HTTP 200 were
also verified. Vitest retained
the previously observed Windows Node subprocess quoting messages. CI timing
remains pending for the new measurement.

The next patch retains the mounted detail/map while another case loads, hides
stale detail and decision controls, and switches map identity only when fresh
detail arrives. The GIS completion check still requires the target GPS data
and rendered layers within 1,500 ms; it no longer requires a replacement map.
Local validation passed all 273 frontend tests and production, unit-test and
browser TypeScript checks. The new regression verifies map retention and
hidden stale decisions during a delayed case fetch. Hosted GIS timing remains
pending CI. Vitest also emitted two Node subprocess quoting errors on Windows
despite reporting all tests passed; these are not hosted browser evidence.

At `6631808`, Unit Tests, lint, RAG evaluation, Railway preview and Vercel
preview passed. Hosted role E2E failed for analyst, driver and admin before a
session was created (`needs_first_factor`, form error present). The maintainer
confirmed only an analyst account had been created. All three real password
accounts and matching `E2E_*_EMAIL` / `E2E_*_PASSWORD` repository secrets remain
prerequisites; a production database role grant does not repair preview login.
The local GIS job passed five browser tests but measured case selection at
1,917 ms against the unchanged 1,500 ms budget. No hosted acceptance or GIS
performance pass is claimed for this revision.

Local recheck on 2026-10-11 passed all 33 motivation unit/contract tests and
all four credential-control/redirect unit tests. These isolated checks do not
validate the configured hosted passwords or the 1,500 ms browser requirement.

Personal preview manual screenshots showed an authenticated case queue and the
Overview motivation card (case 38, zero estimated reward, insufficient intent
data), but Copilot returned `network error`. Narrative consistency remains
unverified on that hosted preview.

CI at `a288803` measured GIS selection at 1,835 ms against the unchanged
1,500 ms requirement. Overview keyed the map by case ID, forcing a new map
on every selection. The follow-up retains the map and updates case data;
case identity resets playback without resetting the map. Regression checks
cover map DOM identity, mount count, and replay reset versus same-case refresh.

The same revision's hosted role tests could not find Clerk's credential submit.
Read-only inspection of its public preview sign-in DOM confirmed the visible
Continue button has no `type` attribute: the old submit selector matched zero
controls, while the form-scoped accessible Continue locator matched one visible,
enabled control. No credentials were entered in this diagnostic. The follow-up
uses exact credential button names and excludes inactive inputs and OAuth.

Local evidence: the frontend suite passed 270 tests before the final regression
refinement; the final three affected suites passed 50 tests. Frontend and browser
test TypeScript checks passed. These are local and public-DOM checks, not proof
that hosted role login or the persisted GIS performance budget passes after deployment.

### Completion follow-up — 2026-10-15

Current `origin/main` already contains the Issue #190 implementation from PR
#240. The completion branch removes the stale backend lifecycle `xfail`, checks
the nested `motivation_assessment` response contract, and adds a discovered
Playwright scenario for the Overview card plus the exact Copilot prompt from the
acceptance criteria. Its fixture carries one shared Vietnamese assessment so the
card and Copilot assertions detect reward or narrative drift.

Local backend evidence: the required motivation suite plus the unskipped
lifecycle scenario passed 34/34. Frontend TypeScript/browser execution was not
claimed locally because the existing pnpm dependency tree resolves through a
broken worktree symlink. Fresh CI dependency installation and browser execution
are mandatory before merge. Hosted Clerk, real case economics, and live-model
narrative quality remain separate pending acceptance evidence.

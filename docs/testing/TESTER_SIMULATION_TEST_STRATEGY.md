# Tester trip simulation: test strategy

Status: design contract for Epic [#130](https://github.com/AI20K-Build-Phase-Cohort-4/GreenSentinel/issues/130). This document defines proof required for implementation; it does not claim that the simulator exists or that any gate has passed.

## Scope and test environment

The feature is exposed through the existing architecture under `/test` (frontend route) and `/test/api/v1` (FastAPI routes). The test workspace uses an isolated database, Redis/queue namespace, and vector collection. Notification delivery is sandboxed to simulated Passenger and Driver identities. Runs retain `run_id`, environment, actor mapping, source/provenance, and storage namespace. A resulting case may appear in the existing Workplace assignment flow, without requiring a visible `TEST` badge; this appearance must be proven against the selected non-production environment.

Tests must keep four evidence classes separate:

| Class | Proves | Cannot prove |
|---|---|---|
| Unit/fixture | deterministic rules, schemas, rendering contracts | persistence, real worker/provider behavior |
| Isolated integration | migrated DB, queue, vector and notification seams | hosted deployment or external provider coverage |
| Local browser | real map/UI interaction and Workplace wiring on a dedicated server | production acceptance |
| Hosted/provider/UAT | deployed auth, workers, providers and operational roles | behavior absent from captured evidence |

No test may turn missing GPS, traffic, route, assessment, notification, or assignment into a fabricated success. Unknown, pending, unavailable, and failed are first-class results.

## Test pyramid and execution lanes

Use existing locations and discovery: backend pytest in `tests/test_agents/`, `tests/test_services/`, `tests/test_api/`; frontend Vitest/RTL in `src/webapp/tests/`; browser tests in `src/webapp/e2e/` and `tests/e2e/`. Do not create a parallel simulator test tree. Keep the existing `tests/conftest.py` offline defaults for unit tests, and add opt-in fixtures for a migrated disposable environment.

1. **Unit/TDD:** write failing tests for plan validation, road sampling, faults, metric semantics, provenance, state transitions, idempotency, role isolation, SSE cursors and UI state before implementation. The selected baseline is ordinary GPS every 1 second, with selectable slower cadence; proposed input bounds are `intervalS ∈ [1, 60]` and `maxPoints ∈ [1, 100000]`, pending representative-trip validation and API-owner approval. The selected fault catalogue is jump, offset/noise and dropout; their numeric bounds remain configuration-owned and must be validated before acceptance.
2. **API contract:** exercise `/test/api/v1/*` with HTTPX and OpenAPI/schema assertions. Check auth/RBAC, consistent structured errors, bounded inputs, additive response fields, idempotency keys and no production writes. Endpoint names and schemas remain subject to the API contract owner; this document does not establish them.
3. **Isolated integration:** apply migrations to a disposable PostgreSQL/PostGIS database; use unique Redis/vector namespaces, real repository adapters, real worker/LangGraph modules, and a sandbox notification adapter. Seed only source-backed fixtures and assert cleanup/namespace isolation.
4. **Worker/provider gates:** run real queue/worker and LangGraph paths with deterministic provider adapters. Separately opt into historical traffic, routing, map, LLM and notification provider contracts; record source/time/version and mark unsupported providers as unavailable.
5. **Browser/UAT:** run the real Next.js app against the isolated API on a dedicated port with Playwright, then agent-browser/manual UAT. Verify map rendering, keyboard/touch/focus, tooltips, actor windows, SSE reconnect/replay and Workplace assignment.

Required commands follow repository guidance: `./.venv/bin/pytest tests/`, `pnpm --prefix src/webapp test`, `pnpm --prefix src/webapp exec tsc --noEmit`, `pnpm --prefix src/webapp build`, and `src/webapp/node_modules/.bin/playwright test --config src/webapp/playwright.config.ts`. With current main/PR139 Playwright resolution, set an explicit dedicated `PORT` plus matching `PLAYWRIGHT_TEST_BASE_URL`, and use `CI=true`/`reuseExistingServer=false` to avoid attaching to another workspace; do not rely on the branch's older fallback behavior. A green fixture run is never reported as a DB, hosted, or provider proof.

## Use-case and requirement traceability

| FR IDs | AC IDs | Named use case | Required proof and failure assertions |
|---|---|---|---|
| FR-TST-01 | AC-TST-01, AC-TST-02 | Compose and persist a complete trip | Origin/pickup/destination/route/speed/time/cadence validate; accepted plan persists and reloads. Ordinary GPS baseline is 1 second with selectable slower cadence (`intervalS` proposed range 1–60); representative-trip validation and API-owner approval remain required. Ordinary gaps must respect the configured interval; jump, offset/noise and dropout faults are labelled and bounded by approved configuration. |
| FR-TST-02 | AC-TST-08 | Review and control a live run | After reviewing the complete saved plan, speed change, stop/resume, reroute and pause emit ordered immutable control events. Distinguish paused/stationary from stopped movement; original plan remains unchanged. Reload retains the original plan and ordered controls/emitted inputs; edits do not rewrite historical run evidence. Crash resumes or exposes interrupted/unknown state. |
| FR-TST-03 | AC-TST-03 | Role-play Passenger and Driver dialogue | Both panes send/receive sandbox messages with speaker, recipient and timestamp. AI draft is optional, editable, provenance-tagged; provider failure leaves manual entry usable. |
| FR-TST-04 | AC-TST-04 | Map-first workspace and controls | Real map renderer shows route, samples, controls and actor regions. Tooltips/icons work by hover, focus and touch; equivalent information is available without hover. |
| FR-TST-05 | AC-TST-04 | Contextual metrics and source-aware movement | Hover and non-hover equivalents expose units/references, route distance vs geometric radius, remaining distance, ETA/DAVI. Insufficient movement yields unavailable/unknown DAVI, never zero. |
| FR-TST-06 | AC-TST-05 | Historical and simulated traffic | Historical request records actual source/time or unavailable. At least two segments retain independent congestion level/density and simulated provenance; simulation never masquerades as observed history. |
| FR-TST-07 | AC-TST-06 | Persist, reload and assign through Workplace | Reload restores plan, run events, provenance, dialogue, notifications, assessments and assignment. Assignment is isolated to the selected environment/namespace and appears through the existing Workplace contract. |
| FR-TST-08 | AC-TST-07, AC-TST-08 | Exercise assessment, notification and case flow | Actual worker path can produce case, no-case, pending, unsupported or failed-assignment states. Detection is advisory; Analyst claim, rationale, evidence snapshot, policy version and existing HITL checks remain mandatory. |
| — | AC-TST-01 | Preparation-time target | Measure blank authoring start through accepted basic-trip/run submission; playback and detection-response latency are excluded. Do not claim the approximately one-minute target until real UAT timing is captured. |
| — | AC-TST-02 | Ordinary cadence and deliberate faults | Validate the selected 1-second baseline and slower cadence options against representative movement. Validate jump, offset/noise and dropout using configured numeric bounds; the proposed cadence range is 1–60 seconds, while fault bounds remain API/configuration-owner decisions. |
| — | AC-TST-03 | Actor responses and notifications | Verify both simulated actor responses and system notifications are recipient-isolated and persisted. |
| — | AC-TST-04 | Map and metric interaction | Verify the actual route renderer, not a static fixture image, plus accessible map controls and source-aware metrics. |
| — | AC-TST-05 | Segment congestion | Reload independently configured segment values and preserve historical versus simulated provenance. |
| — | AC-TST-06 | Complete reload | Verify all plan/run artifacts and assignment read model after a fresh session. |
| — | AC-TST-07 | Assessment outcomes | Verify case/no-case/pending/failed states without fabricating detection or assignment. |
| — | AC-TST-08 | Runtime controls and evidence immutability | Verify ordered controls survive reload and do not rewrite consumed evidence. |
| NFR-TST-01 | — | Preparation performance | Measure blank authoring-to-accepted-run submission with explicit start/stop and exclusions; do not claim target until UAT repeats it. |
| NFR-TST-02/03 | — | Provenance and explicit unknowns | Every generated or external datum has source, time, version and run lineage. Missing/insufficient evidence stays unknown/unavailable. |
| NFR-TST-04 | — | Recovery and isolation | Duplicate request, retry, worker crash, timeout and notification failure produce replay/reject/pending/unknown states with no duplicate effects. Runs, roles, storage, evaluation labels and model outputs cannot cross-contaminate. |
| NFR-TST-05 | — | Usability | Unrestricted map-first creation works without canned scenarios; responsive layout, keyboard focus, touch targets and accessible labels pass. |

## API and state-machine contract coverage

Contract tests must cover plan create/read/update, run start/control/stop/resume, actor messages, traffic segment edits, assessment status, notifications, stream cursor/replay and Workplace case lookup beneath `/test/api/v1`, including the proposed paths in `docs/architecture/TESTER_API_SPECIFICATION.md`. Use the API contract's structured error envelope for 400/401/403/404/409/422/503. State-changing calls require an intent-stable `Idempotency-Key`; exact replay returns the stored response, while the same key with a different payload or an in-flight duplicate returns `409`; timeout/unknown remains recoverable through run status. Endpoint names and exact schemas remain proposed until the API contract is adopted. The canonical catalog uses `/plans`, `/previews`, `/sampling-previews`, `/traffic-queries`, `/dialogue-drafts`, `/runs/{runId}/controls`, `/messages`, `/notifications/{notificationId}/replies`, `/results`, `/events`, `/stream` and `/snapshot`. Assert that no endpoint can force-create a case and that COMPLETED execution does not imply completed assessment. Test expired keys (`409`), expired cursors (`410`), rate limits (`429`) and sanitized internal/dependency failures (`500/503`).

SSE tests cover event ordering, `Last-Event-ID` replay, expired cursor, reconnect, token refresh, backpressure and terminal events. Browser tests must prove that reconnect does not duplicate messages or controls.

## Isolation and security gates

Every test run has a unique namespace and simulated actor principals. Assert no reads/writes to operational storage, no cross-run cases/messages/vector hits, no role escalation from Tester to Analyst, no recipient leakage, no evaluation labels in model input, and no production notification provider calls. RLS/auth tests run with real migrated policies where available; mocks are labelled fixture proof.

## Exit evidence

The implementation PR is ready only with a trace matrix linking all 8 functional requirements, all 5 non-functional requirements, and all 8 acceptance criteria to test files and captured output, plus focused and full suite results, migrated-isolated DB/worker proof, browser screenshots/traces where relevant, and hosted/provider/UAT results separately. The selected one-second baseline and slower cadence range still require representative-trip validation; fault numeric bounds, radius semantics, provider coverage, deployed isolation configuration, actor identities, notification contract, replay policy and duplicate/crash recovery remain open DoD items rather than inferred passes.

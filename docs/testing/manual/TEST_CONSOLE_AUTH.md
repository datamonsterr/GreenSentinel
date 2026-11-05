# Test console authorization and submission verification

Record revision, environment, test organization IDs, observed outcomes and artifact links. Use a disposable migrated test database and operational database. Never point this runbook at real customer data.

## Real authentication

Disable explicit test authentication and optimized GIS fixture mode for these checks. Use authorized real Clerk test accounts following [the real-account guide](../REAL_ACCOUNT_E2E.md); do not capture passwords or session tokens.

1. Open `/test` and `/test/workplace` signed out. Confirm sign-in redirect preserves the requested return URL.
2. Sign in as Driver, Analyst and Admin members of organization A. Confirm console admission for each; role does not select access.
3. Remove the active organization or expire the session. Confirm denial or sign-in recovery before protected data appears.
4. With the explicit `X-Test-Context: true` header, call the plans API without a session and with forged role/organization headers. Confirm denial; development must not create a demo principal.
5. Create an owned plan, definition and run in A. Switch to B and attempt the same plan/run IDs, samples, controls, notifications, cases and event stream. Confirm no A data or side effects.

## Disposable database and API checks

Explicit `APP_ENV=test` plus `TEST_AUTH_ENABLED=true` admits local fixture identities. Those requests must include an explicit organization. This mode proves API/storage boundaries and does not prove sign-in redirects.

1. Run the tenant API tests with `TEST_SIMULATION_DATABASE_URL` set to a freshly migrated disposable database. Run the worker database tests with their documented isolated `DATABASE_URL`; count skipped database parametrizations as missing evidence.
2. Restart the repository and repeat an organization-scoped request key. Confirm the same owned run returns; reusing a key in B must not return A's run.
3. Leave a legacy plan without organization ownership. Confirm scoped listing/detail hides it instead of guessing an owner.
4. Stop only the task-owned test database. Confirm a configured storage outage raises an error and never reports a memory-only success.
5. Submit recorded telemetry with verified organization context and owned actor IDs. Inspect persisted trip, assignment and assessment ownership. A normal result must not create a forced fraud case.
6. Try a foreign actor, caller-supplied organization, missing samples and a controlled persistence failure. Confirm explicit failure and no apparent successful submission.

## Desktop console verification

On a desktop viewport (1024px and wider), verify dragging all three stops, address updates, Run/Pause/Resume, destination completion and both early-cancellation reason dialogs. Confirm cancellation actor/reason reaches the event, authorized agent context and case evidence. Verify the collapsible 40% Log/Overview dock reports actual stages, and titles/presets/history survive reload through APIs. Record observed behavior at the tested revision; the design preview is not runtime proof.

Mobile test-console use and mobile previews are unsupported and removed. Verify the three-pane workstation at 1024px and 1600px. Explicit actor references and separate initial/pickup/destination snapshots must be validated through the actual API. No hosted authentication, model-quality or Driver-delivery acceptance is inferred from local tests.

## Console behavior cases

Run against a disposable migrated environment or the exact deployed revision. Record revision, environment, IDs, observed result, and artifact links. Empty evidence is a pending result.

| Case | Check | Required evidence |
|---|---|---|
| TC-01 | Compose exactly three stops; edit by search, drag, and keyboard; start run; try editing after start. | Persisted stop identities and explicit immutable-state response. |
| TC-02 | Use organization members as selected Passenger/Driver; attempt foreign actor and tenant-header substitution. | Authorized success plus server-side rejection and no cross-tenant side effect. |
| TC-03 | Exercise Run/Pause/Resume; reach destination; verify Complete trips is enabled only then. | Persisted lifecycle events and destination evidence. |
| TC-04 | Submit blank, whitespace, and valid Customer/Driver cancellation reasons; retry a forced uncertain failure. | Inline validation; canonical actor/reason event; failure remains unconfirmed until reconciliation. |
| TC-05 | Observe SSE reconnect, duplicate event, cursor resume, scope change, and REST gap reconciliation. | Event IDs, connection states, and reconciled persisted records. |
| TC-06 | Expand/collapse 40% Log/Overview dock while new events arrive. | Measured bounded layout and preserved focus/scroll/expanded-row state. |
| TC-07 | Inspect presets with metadata-only and replay-capable responses; reload saved titles/history; switch tenant. | Provenance, explicit unavailable state, persisted title, and isolated history. |
| TC-08 | Force missing route/address, metrics, model, notification, or case evidence. | Visible unknown/waiting/error state; no fabricated route, metric, verdict, or delivery claim. |

## Desktop release regression

1. At 1024px and 1600px, expand the results region and measure approximately 40% of the bounded console content; collapse it and verify 38px height. Check desktop keyboard navigation and modal focus wrapping. No mobile preview or mobile adaptation is supported.
2. Leave actor lists empty or make the actor database unavailable. Confirm an explicit empty/error state and no invented actor identity. Choose owned records and inspect all three definition snapshots before running.
3. Start a run and immediately attempt stop edits while creation is pending. Switch organization while creation/history requests are in flight. Confirm old results never reappear and the previous stream ends.
4. Disconnect the stream, resume with its last event ID, replay a duplicate, and compare the reconciled run/sample state. A normal completion event or persisted completed state enables normal submission; cancellation exposes its separate processing action.
5. Retry a successful publication after restarting the API, and submit the same run concurrently through two API instances. Confirm one recorded receipt, one canonical processing invocation in the controlled test, and the same response. Inspect a normal classifier receipt with no fraud case in Overview.
6. Attempt more than 2,000 samples and force geocoder, classifier, and persistence failures. Confirm explicit rejection/error; preserve cancellation reason on failure and never show a successful pipeline receipt without backend acknowledgement.

For current commands, counts, evidence classes, and known distributed-pipeline boundaries, see [PR #345 verification](../TEST_CONSOLE_PR345_VERIFICATION.md).

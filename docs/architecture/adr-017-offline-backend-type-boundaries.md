# ADR-017: Deterministic backend verification and typed provider boundaries

## Status

Accepted, 2026-10-05. [Issue #161](https://github.com/AI20K-Build-Phase-Cohort-4/P-063/issues/161).

## Context

The Python 3.13 baseline at `15b1b68` failed five default tests when ambient Jev credentials enabled live requests. Mypy targeted Python 3.11 while reading dependencies installed for Python 3.13, then exposed application errors after the target mismatch was removed. Two agent tools treated the case detail trip dictionary as an object, so recorded coordinates never reached weather or routing providers.

## Decision

Keep the default provider contract tests deterministic. The existing autouse credential fixture replaces both case variants of `project_jev_api_key` with a placeholder, unless `TEST_LIVE_JEV=1`. Tests supplying explicit mocked settings still exercise transport, payload, and error contracts. Production credential resolution is unchanged.

Let mypy follow the active Python interpreter and its installed dependency stubs. Keep every application module in scope. Repair inferred types with SDK enums, typed messages and runnables, concrete exception class unions, and validated optional-value narrowing. Missing embedding vectors fail explicitly; absent text stays empty rather than becoming fabricated evidence. Python compatibility remains `>=3.11`, with Ruff targeting Python 3.11.

Read case trip `pickup` and `dropoff` from their existing GeoJSON Point dictionaries. Validate recorded coordinates before converting `[longitude, latitude]` to provider arguments. Missing or invalid case coordinates remain unavailable. This repair does not establish the correctness of inherited weather or traffic fallback evidence.

## System topology and state lifecycle

The client still calls FastAPI routes, which validate requests and delegate to services; agent tools consume service results. Shared Pydantic schemas remain in `src/models/`. No database query moves into an agent node or API handler. `AgentState` explicitly declares the existing optional `system_prompt`, messages, runtime context, and case context. The graph still enters `agent`, selects `tools` or `END`, and returns from `tools` to `agent`.

## Tool contracts and data flow

A case-scoped tool obtains `CaseDetail` through `CaseService`, reads GeoJSON, validates coordinate ranges, and calls the existing provider. Tool exception handling and unavailable-coordinate responses remain intact. Native content declarations are validated as SDK models; tool payloads continue through existing schemas and service authorization. API response validation, graph routing, and SSE delivery retain their existing paths.

The legacy ticket helper's `RECORD_FINDING` payload never satisfied `CaseActionRequest`, so its swallowed validation exception always prevented an audit write. Remove that dead attempt rather than inventing a sanction action or hiding the static error. A characterization test proves the same zero-write behavior before and after removal. The inherited `ISSUED` preview remains misleading and is tracked in [issue #158](https://github.com/AI20K-Build-Phase-Cohort-4/P-063/issues/158); it is not durable adjudication evidence. Model declarations still exclude that tool, and a forced model call now returns a schema-valid forbidden response.

## Rationale & Alternatives Considered

| Option | Pros | Cons | Decision |
|---|---|---|---|
| Isolate default credentials and test explicit mocked transports | Repeatable local and CI checks; preserves provider contract coverage | Live quality requires a separate run | Selected |
| Consume ambient credentials in default tests | Exercises configured providers opportunistically | Nondeterministic, billable, and dependent on local secrets | Rejected |
| Match mypy to the active environment and fix precise types | Checks the actual dependency/API contracts without excluding application code | Requires explicit narrowing at nullable seams | Selected |
| Broad ignores, module exclusions, or casts of invalid literals | Hides immediate errors | Conceals real runtime defects and weakens verification | Rejected |
| Introduce a new sanction action to satisfy a legacy preview | Could create durable writes | Changes authorization and adjudication semantics outside this repair | Rejected |

## Security and boundary protection

No credentials are stored in source, logs, or evidence. Default test substitution reduces accidental provider use without changing runtime settings. Existing input validation, authentication, rate limits, service authorization, and human action controls remain authoritative. An offline success does not prove hosted authorization, database persistence, live provider quality, or delivery of sanctions.

## Consequences

The baseline quality command can validate the application against the active environment. Future nullable SDK changes should receive seam-level regression tests instead of broad suppression. Database and live-provider opt-ins remain explicit. Commands, observed counts, and manual verification steps are recorded in [the #161 verification report](../testing/ISSUE_161_VERIFICATION.md).

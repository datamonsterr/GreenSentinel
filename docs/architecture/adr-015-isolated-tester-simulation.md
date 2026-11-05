# ADR-015: Isolated Tester Simulation with Reused Domain Flows

## Status

Proposed architecture. The stakeholder confirmed the isolated environment and sandbox delivery decision on 2026-10-04; implementation, visual review and acceptance remain pending.

## Context

Epic #130 requires arbitrary trip authoring, live Driver controls, dialogue, traffic, notifications and inspection of actual assignment in the existing Workplace layout. A new URL alone cannot isolate the current global API clients, repository credentials, queues, vector retrieval or delivery channels. Fixture success cannot establish that the existing worker already supplies all requested notification/assignment contracts.

## Decision

Add frontend `/test`, `/test/runs/[runId]` and `/test/workplace`, and a separately mounted backend `/test/api/v1` with no unprefixed alias. Reuse existing ingestion, feature, assessment and analyst use cases with explicit test-bound dependencies. Use a dedicated test database, isolated queue/vector/checkpoint/storage resources and sandbox notification delivery. Inject a per-workspace test client throughout the existing Workplace presentation; never switch its global API base.

Persist whole definition revisions, actual emissions, ordered runtime controls, result references, delivery attempts and replies. A durable runner/outbox coordinates at-least-once processing with stable identities and reconciliation of unknown effects. The selected sampling baseline is 1-second GPS with selectable slower cadence and JUMP/OFFSET_NOISE/DROPOUT. Numeric limits and representative-trip validation remain acceptance gates.

The Tester has explicit simulation permission and run ownership, not analyst authority. Cases arise from actual assessment and normal assignment in the test environment; no endpoint forces successful detection or case creation. Authorized analyst confirmation and written rationale remain mandatory for dismissal and adverse decisions.

## Rationale and alternatives considered

| Option | Benefits | Costs / risks | Decision |
|---|---|---|---|
| Additive `/test` contracts, dedicated infrastructure, reused use cases | Honest full-flow evidence, isolation, arbitrary authoring | Durable orchestration and dependency injection work | Selected |
| Same operational database with test flags | Lower initial setup cost | Missed predicates contaminate operational evidence, metrics and actions | Rejected |
| New classifier or independent Workplace product | Independent development | Divergent authority and duplicate system behavior | Rejected |
| Corpus presets and browser-only runner | Quick visual demonstration | Cannot prove arbitrary authoring, persistence or actual outcomes | Rejected as runtime; useful only as declared fixtures |
| In-process FastAPI background task | Minimal plumbing | Worker restart loses progress and uncertain external effects | Rejected for durable run execution |

## Consequences

Existing operational routes remain compatible. Reusing presentation requires an explicit client seam across queue/detail/Agents/policy/account/stream/navigation paths. Long-lived run artifacts and idempotency tombstones add retention cost. Historical traffic cannot be accepted without supported source/time/licensing proof. Stochastic model replay is versioned observation, not guaranteed identical output.

## Required architecture answers

1. **Topology:** Next.js test pages call the test router; test service/repository and durable runner use isolated infrastructure. Actual assessment uses existing telemetry-worker logic. Optional AI drafting uses the conversational graph separately. Sandbox actor inboxes and test Workplace read actual persisted records.
2. **State and graph lifecycle:** Run execution has QUEUED/RUNNING/PAUSED/CANCELLING/terminal states independent of downstream stages. Current AgentState and `agent -> tools -> agent/END` graph remain unchanged; this diagram is not the detector's node inventory.
3. **Tool contracts:** Validated typed schemas and server-created organization/run/actor context constrain adapters and agent tools. Invalid inputs fail explicitly; provider/tool failures become typed stage events and never sanction authority.
4. **Data flow:** Compose/preview, immutable whole-definition revision, atomic run/outbox/idempotency commit, emitted telemetry, actual assessment/assignment, sandbox notification/reply evidence, snapshot/SSE replay, existing Workplace layout with test client.
5. **Trade-offs:** Dedicated storage costs setup/orchestration but prevents operational contamination and preserves reproducibility. Existing use-case reuse avoids a second policy path.
6. **Security:** Explicit authenticated Tester permission in every environment, owner/organization scoping, RLS and separate credentials, fail-closed environment validation, bounded inputs/rates, recipient isolation, sandbox egress, no secrets in logs and no automatic adjudication.

## Verification

[API contracts](TESTER_API_SPECIFICATION.md), [architecture](TESTER_SIMULATION_ARCHITECTURE.md), [UI design](../design/tester-simulation/design.md), [test strategy](../testing/TESTER_SIMULATION_TEST_STRATEGY.md) and [manual runbook](../testing/MANUAL_TEST_TESTER_SIMULATION.md) define the design and proof. Acceptance requires actual migrated test storage/worker/assignment observations, isolation failures, retries/crashes/SSE recovery, rendered browser behavior and usability timing. Documentation tests alone do not pass product DoD. Stitch screen generation and visual confirmation remain pending before application coding.

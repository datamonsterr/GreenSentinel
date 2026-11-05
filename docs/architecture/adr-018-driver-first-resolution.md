# ADR-018: Separate Driver-confirmed resolution from Analyst adjudication

## Status

Proposed implementation contract for the 2026-10-05 approved business extension. Requirement approval is recorded in [#147](https://github.com/AI20K-Build-Phase-Cohort-4/P-063/issues/147). This document delivers no runtime/schema changes. The remaining reasonableness criterion is explicitly pending in [the requirements](../ba/DRIVER_FIRST_REQUIREMENTS.md).

## Context

The adopted Analyst baseline forbids autonomous dismissal and requires signed Analyst adjudication. The stakeholder now schedules Driver assistance first and permits explicit Driver-confirmed resolution. Reusing `auto_dismissed` would erase the distinction between a person's accepted resolution and model-generated exoneration, misstate audit/metrics and weaken existing sanction controls. See the [glossary](../ba/DRIVER_FIRST_GLOSSARY.md).

## Decision

### System topology

Reuse the Next.js Driver and Workplace clients, FastAPI API, service layer, persistent case/session data, LangGraph assistance and existing inbox. Services own lifecycle writes and delivery outcomes; agent nodes return advisory evidence and score outputs. The worker escalates elapsed durable confirmation deadlines. Tester integration uses its separately isolated environment; no new production provider is assumed.

### State and graph lifecycle

The planned durable contract distinguishes `driver_assistance`, `awaiting_driver_confirmation`, `driver_confirmed_resolution` and `analyst_escalated` from existing Analyst dispositions. Names are proposed states, not existing schema facts. Persist organization, assigned Driver, policy version, question delivery time, 48-hour deadline, transition version, score semantics/model/prompt versions and evidence/error references. Evaluate boundary/failure escalation before requesting confirmation. Explicit Driver choices, timeout escalation and authorized Analyst reopening are separate events. Late confirmation after escalation never changes disposition. The LangGraph conversation cannot directly authorize a sanction or write an autonomous dismissal.

### Tool contracts

Tool inputs include trusted case/organization context and validated evidence requests. Return source references, actual missingness and typed failure status separately. Record model/tool/delivery failure; escalate rather than fabricate successful evidence. A valid confidence is within [0,1], defaults to uncalibrated semantics and uses strict `> 0.5`. Invalid/missing/exactly 0.5 confidence escalates. A successful retrieval with incomplete evidence stays explicitly incomplete.

### Data flow

1. Detector intake persists the case in the applicable policy version, then Driver assistance starts outside active Analyst triage.
2. Deliver the grounded summary, accept an owned Driver reply, retrieve policy/evidence and persist the conversation and advisory outputs.
3. Apply boundary/failure rules; either commit Analyst escalation or deliver the confirmation question and persist its acknowledged delivery/deadline.
4. A service transaction conditionally commits one explicit resolution or escalation against the current state/version. Atomically retain disposition, actor/rationale/confirmation and audit/outbox records as supported by the implementation; prove persistence before accepting delivery.
5. Timeout workers and retried/reconnected requests use the same transition condition and idempotency identity. SSE/replay observes committed state. Late replies remain in history without a reverse transition.
6. Analyst escalation enables active triage. Authorized Analyst decisions and sanctions retain existing guardrails. Resolution and all evidence remain readable in authorized history.

### Security and boundary protection

Derive organization, Driver and permissions from verified persisted identity, never request body or self-selected roles. Apply the same ownership checks to pages, APIs, tool context, SSE/replay, attachments and stored history. Missing/revoked/expired/unverifiable identity denies access. Reopening requires explicitly granted Analyst authority. Privileged role grants remain server-controlled; junior suspension restrictions and PII masking remain. Keep provider keys server-side in ignored secrets, validate inputs and retain existing rate-limit boundaries. No production test flag enables this policy or bypasses authorization.

## Rationale & Alternatives Considered

| Option | Pros | Cons | Decision |
|---|---|---|---|
| Explicit Driver resolution and versioned lifecycle | Honest actor/disposition, preserves audit and Analyst sanction controls | Requires durable transitions and new acceptance proof | Selected contract |
| Reuse autonomous dismissal/exoneration | Fewer labels | Misstates human choice, uncertainty and authority | Rejected |
| Keep every case Analyst-first | Preserves historical release flow | Does not meet the newly approved assistance sequence | Historical baseline only |

## Consequences

Lifecycle migration, worker scheduling, ownership enforcement and database/browser evidence belong to implementation issues. Preserve historical dispositions and the Analyst baseline tests; new tests cover the distinct resolution branch rather than blanket-changing dismissal permissions. Rollout identifies the policy version and preserves in-flight questions/deadlines. No pending reasonableness rule is silently implemented. Restart, duplicate reply, concurrent timeout and late confirmation must produce one accepted transition and retain evidence.

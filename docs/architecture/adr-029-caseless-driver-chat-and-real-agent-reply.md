# ADR-029: Case-less GSupport Chat and Real Agent Reply on Stream Routes

## Status

Accepted (Issue #482, driver app redesign slice 8/10, [PLAN.md](../design/driver-app-redesign/PLAN.md) Q4/Q5).

## Context

`docs/design/driver-app-redesign/PLAN.md` (Q4) requires a case-less GSupport
chat entry point: `POST /api/v1/driver/chat/stream`, where the agent resolves
the driver's cases via the existing `list_my_cases` tool instead of a bound
`case_id`. [Issue #482](https://github.com/AI20K-Build-Phase-Cohort-4/P-063/issues/482)
comment flagged a review finding from PR #485: `DriverDisputeService.process_driver_chat`
fired `run_driver_support_agent` via `asyncio.create_task(...)` and discarded
the result, so every chat caller — including the case-scoped SSE stream route
— only ever surfaced the deterministic policy-engine template text, never the
real LangGraph agent reply/blocks.

## Decision

1. **`run_driver_support_agent(case_id: str | None, ...)`** now accepts
   `case_id=None`. Case lookup/authorization is skipped when no case is
   bound; `list_my_cases` (already driver-scoped via `InjectedToolArg`)
   resolves the driver's cases from `driver_id` in `runtime_context` alone.
   `case_card`/`trip_card` blocks are only emitted when a case/trip id is
   actually resolved from tool output (no fabricated entities).
2. **`DriverDisputeService.stream_driverless_chat`** is the new case-less SSE
   generator: no `DriverChatRequest`/`case_id`, driver identity comes from
   the authenticated `Principal` (never a request body field), emits the
   same `token` / `blocks` / `done` lifecycle documented in
   [`CHAT_UI_EVENT_CONTRACT.md`](../CHAT_UI_EVENT_CONTRACT.md) Step 4, using
   the agent's real reply text. Agent failure emits `event: error` instead
   of crashing the stream.
3. **Real agent reply on stream routes**: `stream_driver_chat` (case-scoped)
   and `stream_driverless_chat` now await `run_driver_support_agent` once per
   turn and stream its `reply`/`blocks` (falling back to the deterministic
   compliance reply only if the agent run fails or returns empty). The dead
   `asyncio.create_task(...)` fire-and-forget call inside
   `process_driver_chat` is removed outright — it only ever discarded its
   result and duplicated LLM calls already made explicitly by the stream
   layer.
4. **The deterministic policy reply is kept, unchanged, as the authoritative
   response for the non-streaming `POST /driver/cases/{case_id}/chat`
   endpoint.** NFR-L06-02 confidence-boundary guardrails, the 48-hour
   silence deadline, and the driver-confirmation state machine in
   `process_driver_chat` are compliance-critical and asserted verbatim by
   existing tests (e.g. `test_driver_chat_rejected_on_expired_deadline`,
   `test_driver_chat_on_already_resolved_case`). Only the *streamed*
   presentation layer surfaces the richer real-agent text; the case status
   machine (`dispute_status`, `is_auto_dismissed`, `exoneration_receipt`,
   `needs_analyst_review`) is always derived from the deterministic engine.

## Rationale & Alternatives Considered

| Option | Pros | Cons | Decision |
|---|---|---|---|
| Make `process_driver_chat.reply` itself the agent's text | "Real reply everywhere" | Breaks ~10 existing tests asserting exact NFR-L06-02 compliance copy; conflates presentation with the compliance state machine | Rejected |
| Keep `asyncio.create_task(...)` but `await` it inside `process_driver_chat` and store on the response | Minimal diff | Non-stream callers pay full LLM latency for a value they discard (deterministic reply still wins); doesn't fix the stream routes, which separately re-invoked the agent only for blocks | Rejected |
| Fix only the stream layer: single explicit `await run_driver_support_agent(...)` per turn, reply/blocks surfaced, remove the dead fire-and-forget | Fixes the literal review finding, no duplicate agent calls, compliance state machine untouched | Non-stream endpoint still returns deterministic text (acceptable: it is compliance-authoritative by design) | **Selected** |

## Required architecture questions

| Question | Answer |
|---|---|
| System topology | Next.js driver client → FastAPI `POST /api/v1/driver/chat/stream` (new, case-less) or `.../cases/{case_id}/chat/stream` (existing) → `DriverDisputeService` → LangGraph `run_driver_support_agent` → `src/services/answer_formatter.py` (driver profile) → SSE `token`/`blocks`/`done`. |
| State and graph lifecycle | `AgentState` (`src/agents/state.py`) unchanged. `runtime_context.case_id` may now be `None`; conditional routing (`should_continue_driver`) and tool nodes are unaffected since tools already treat `case_id`/`driver_id` as optional/injected. |
| Tool contracts | `list_my_cases` (`src/agents/tools/driver_tools.py`) already requires only `driver_id` (`InjectedToolArg`); no new tool added. Tool execution failures still fall back to the safe fallback text in `run_driver_support_agent`. |
| Data flow | Case-less: client → route → `stream_driverless_chat` → `run_driver_support_agent(case_id=None, ...)` → token/blocks/done. Case-scoped: route → `stream_driver_chat` → `process_driver_chat` (compliance side effects) + one explicit `run_driver_support_agent` call → token (agent reply) / blocks / done (compliance fields + agent reply). |
| Trade-offs | See table above. |
| Security boundaries | Driver identity for the case-less route comes exclusively from `require_principal`/`require_role(principal, "driver")`; no request body field can impersonate another driver. Case-scoped route keeps existing `require_driver_identity`/`require_case_scope`. |

## Consequences

- `tests/unit/agents/test_driver_agent_caseless.py`, `tests/integration/services/test_driver_caseless_chat_service.py`,
  `tests/integration/api/test_driver_caseless_chat_api.py`, and a new case in
  `tests/integration/api/test_driver_api.py`
  (`test_driver_chat_sse_stream_uses_real_agent_reply`) cover this ADR.
- No change to the non-streaming compliance response contract; existing
  deterministic-reply assertions remain green.
- Frontend `/driver/chat` (greeting + suggestions) and `/driver/chat/[caseId]`
  (case thread) consume these two SSE endpoints per
  [PLAN.md](../design/driver-app-redesign/PLAN.md) Section 3.

# ADR-034: Driver explanation agent v2 session model

Status: accepted · Scope: slice S-D1 of `docs/plans/2026-11-20-prd-features.md` (PRD-A US1-US6, section 8). Migration `20261120120000_explain_sessions.sql`. Depends on [ADR-032](adr-032-knowledge-base-roles-and-lifecycle.md) (published knowledge, agent config, kill switch) and [ADR-031](adr-031-gsm-workflow-roles.md) (roles).

## Context

The driver explanation was a fixed wizard plus the free-form GSupport chat. There was no structured session, no immutable statement, no assessment history, no tool-based use of KSGL knowledge, no help loop and no bounded interview. The legacy chat and statement routes stay untouched; v2 is a new route set behind the `explain_agent_enabled` kill switch.

## Decision

**One session per case** (`app.explain_session`, unique `(organization_id, case_id)`). States: `draft` (form) -> `investigating` -> `asking` (chat) -> `summary` -> `submitted`. `mode` is `agent` or `fallback`. The `fraud_cases.status` machine is NOT changed (handover to UNDER_REVIEW stays with the existing flow; open question).

**Tables** (all additive, schema `app`): `explain_session` (form snapshot, answers, plan, memory, provenance, six flag columns, counters), `statement_version` (immutable: DB trigger rejects update/delete; v1 = form, later versions `chat|edit|summary|auto`), `assessment_round` (round 1 `form`, round 2 `chat`; state `eligible|not_eligible|needs_driver|missing_internal`), `explain_turn` (transcript + tool calls + plan updates + flags + guard hits, each row carries `kb_code`/`kb_version` when a tool used knowledge, `visible_to_driver`), `help_request`, `vh_feedback`.

**Form (US1)**: fixed typed questions per reason (`RealTrip, NotDone, Tech, Customer, Other`; `Other` = free text + photo) from `explain_forms.py`, plus at most K optional questions from the matched published workflow's `ask_first`. The snapshot and `form_version` (`<reason>.1[+<workflow>@<v>]`) are stored; the driver view hides the origin of dynamic fields.

**Loop (US2, 8.4)**: submit stores statement v1 and runs the investigation with code tools (`identify_behavior`, `list_motives`, `compute_motive`, `match_scenario`, `get_workflow`), assesses round 1, and, on `needs_driver`, enters the loop. One advance = think (`llm.step`) -> optional tool -> observe -> ask one question; at most 4 hops per advance. Turns used counts answered questions; `turns_used >= N_max` closes with `ai_inconclusive`. Done, end-early, N_max and idle all go to the summary; confirm runs the round-2 assessment. Summary edits are capped by `edit_limit` and do not count toward N_max (answers PRD Q2). Idle sessions auto-submit lazily after `t_draft_minutes` (any read/write ticks; `sweep(org)` exists for a worker) with `session_interrupted`.

**Tools (US6)**: read published knowledge only; every number is computed in code; failures return `ok:false` with a `không tra được: ...` reason. `match_scenario` scores 0.5 x reason similarity + 0.5 x behaviour matched against the published scenarios; below `similarity_threshold` sets `novel_scenario` and the default question set is used. A workflow restricts the tools the loop may call to its step tools (plus `request_help`, `propose_knowledge`); without a workflow all investigation tools are allowed. Provenance records `{type, code, version, tool}` per use.

**LLM seam** (`explain_llm.py`): `ExplainLLM` Protocol (`assess`, `step`, `summarize`) with pydantic outputs. Runtime: OpenRouter `z-ai/glm-5.3-flash` via `get_llm`, structured output, 25 s timeout. Any exception, timeout or schema error switches that call to `DeterministicExplainLLM` (default question set, conservative round 2: never `eligible`/`not_eligible` without a recorded contradiction) and writes a `llm_fallback` turn. Kill switch off -> `mode=fallback`: static form, statement v1, no tools, no LLM.

**Guard (8.6)**: `explain_guard.check_agent_text` rejects fines, conclusions, accusations, thresholds, motive/formula wording, other drivers, UUIDs, empty or over-long text; a rejected question is replaced by the plan point text or a neutral template and a `guard` turn is logged. Driver text is scrubbed; prompt-injection phrases only raise a `flag` turn for VH; safety words force `request_help`.

**Help (US3)**: `request_help` creates `help_request` (open -> claimed -> answered, or expired lazily after `help_sla_minutes`). Ceiling: open+claimed >= `help_ceiling` or `help_count >= help_max_per_session` -> no request, `asked_for_help_skipped`. `novel_scenario` and `low_confidence` requests are non-blocking (agent keeps asking); other triggers (unverifiable evidence, conflicting sources, safety, workflow step) block until reply/expiry and upgrade an open non-blocking request. A reply continues the loop immediately and creates a pending `kb_proposal` (source `help_reply`, type `workflow`) via `kb_service.create_proposal`; expiry records the stuck point as an open point.

**VH feedback (US4)**: `vh_feedback` (agree | disagree + at least one of six error types + comment), append-only, latest per author displayed.

**Auth**: driver routes require role `driver` and `case.driver_id == principal.driver_id` else 404 (no probing); analyst-family and VH roles read `/cases/{id}/explain`; help queue roles `analyst, senior_analyst, fraud_analyst, admin, reviewer, manager`. The driver payload never contains assessments, plan, provenance, motives, flags or N_max.

## Consequences

- No change to existing tables or the legacy chat. Rollback drops the new tables and trigger.
- `PgStore`/`MemoryStore` gained the six tables and `case_info`; services stay unit-testable (MemoryStore, scripted LLM, injected clock).
- Open: map `submitted` to the case status machine; retention/DPIA for per-driver history (US5 layer 2 not built); a periodic sweeper is not scheduled; audit rows use the principal id (the local test-auth `x-driver-id` header is not a principal and fails the audit FK).

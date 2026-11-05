# ADR-021: Analyst Single-Message Context Reset Architecture

## Status

Accepted, 2026-10-05. [Issue #153](https://github.com/AI20K-Build-Phase-Cohort-4/GreenSentinel/issues/153). Governed by [`FR-WS-01`](../ba/DRIVER_FIRST_REQUIREMENTS.md#remaining-workspace-defaults) and [`AC-WS-01`](../ba/DRIVER_FIRST_REQUIREMENTS.md#acceptance-scenarios-and-proof).

## Context

During fraud triage in the Adjudication Cockpit, human analysts frequently interact with the policy copilot agent to inspect trip events, examine telemetry anomalies, and clarify regulatory clauses. In standard multi-turn dialogue, the chat agent concatenates previous conversation turns into the LLM prompt to maintain conversational continuity.

However, during forensic dispute evaluation, analysts often require an unbiased, zero-prior-dialogue policy assessment on a specific question without influence from prior conversational turns. Previously, the system provided no mechanism to query the model without previous turns without clearing the entire session or discarding audit history.

## Decision

1. **Analyst Chatbot Target Only**:
   The context-reset capability is scoped exclusively to the Analyst Adjudication Cockpit (`CockpitWorkspaceView`). Driver assistance and dispute flows do not expose or accept arbitrary context resets.

2. **Unchecked Default & Single-Turn Toggle**:
   The context-reset toggle is an explicit checkbox (`data-testid="reset-context-toggle"`), unchecked by default (`false`). It acts as a single-turn reset: checking the box applies to the immediately submitted message only. Upon transmission, the client automatically resets the toggle back to unchecked, ensuring subsequent turns naturally resume conversational dialogue unless intentionally toggled again.

3. **Model Input Exclusion vs. Audit Preservation (Reset is Not Deletion)**:
   - When `reset_context=True`, `CaseService._begin_case_agent_turn` and `stream_agent_turn` clear prior dialogue turns (`history = []`) before appending the current user query for model execution.
   - All prior and current user and assistant messages remain fully persisted in `app.case_agent_messages` and are returned by `/api/v1/cases/{case_id}/agent-session`.
   - Authorized case context, dossier facts, spatial telemetry, error guardrails, and role-based tool catalogs are preserved without modification.

4. **Typed Contract & API Boundary**:
   - `PolicyChatRequest` in `src/models/schemas.py` and `src/webapp/types/schemas.ts` declares `reset_context: bool = Field(default=False)`.
   - Streaming endpoints (`/api/v1/policy/chat/stream`) and runtime services forward the typed boolean flag.

## Rationale & Alternatives Considered

| Option | Pros | Cons | Decision |
|---|---|---|---|
| Single-turn typed checkbox (`reset_context=True` on request) | Unbiased model queries on demand; zero audit data loss; automatic return to conversational mode | Requires client-side toggle state management | **Selected** |
| Deleting session messages from database (`DELETE FROM app.case_agent_messages`) | Model sees no history | Destroys forensic audit trail; violates compliance and evidence requirements | **Rejected** |
| Clearing chat bubbles on the frontend only | Simple frontend change | Does not change model input; prompt retains prior context | **Rejected** |
| Persistent sticky toggle (remains checked until unchecked) | Fewer clicks if running many zero-context queries | High risk of unintended context loss on subsequent follow-up questions | **Rejected** |

## Security & Boundary Protection

- **Audit Preservation**: Stored conversation history, actor identities, case versions, and timestamps remain immutable. A context reset cannot erase prior interactions.
- **Identity & Scope**: The endpoint strictly verifies analyst credentials via `require_principal` and ensures case scope permissions. Unauthenticated callers or unauthorized roles are rejected.
- **No Guardrail Bypass**: The context-reset flag affects only conversational dialogue history; system guardrails, evidence checks, and mandatory human confirmation steps cannot be bypassed.

## Consequences

- Analysts can perform isolated, objective policy consultations within an active case triage session.
- Full verification is evidenced by captured model-input tests (`tests/test_api/test_analyst_context_reset.py`), session audit retrieval assertions, and frontend UI tests (`src/webapp/tests/analyst-context-reset.test.tsx`).

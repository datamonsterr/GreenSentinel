# ADR-028: Copilot Ownership Gating and Safe Runtime Diagnostics

## Status
Accepted (Refs #380)

## Context
When fraud analysts opened unclaimed cases or cases claimed by other analysts, the AI Copilot chat input was active on the client. Submitting a chat query immediately failed at the backend with HTTP 403 Forbidden because `authorize_case` strictly validates case assignment and tenant boundaries. Additionally:
1. `case_context.py` performed an inner `JOIN app.drivers d ON d.id=a.driver_id` following a `LEFT JOIN app.trip_assignments a`, causing cases without linked drivers/assignments to return 0 rows and trigger false 403/404 errors.
2. Parameterized SQL queries in `case_context.py` and `agent_runtime.py` lacked explicit `::uuid` casting, causing PostgreSQL type mismatch errors.
3. `stream_agent_turn` in `agent_runtime.py` swallowed exceptions and hardcoded all errors to `"PROVIDER_UNAVAILABLE"`, preventing diagnosis of runtime failures.

## Decision
1. **Frontend Ownership Gating**:
   - Gate AI Copilot chat at the case-ownership seam in `src/webapp/components/views/cockpit-view.tsx`.
   - The chat text input, send button, attachment button, and context-reset toggle are disabled when:
     - No case is selected (`!selectedCaseId`).
     - Case is terminal / resolved (`isTerminalCase`).
     - Case is claimed by another analyst (`isLockedByOther`).
     - Active lease is expired (`isLeaseExpired`).
     - Case is not claimed by current analyst (`!isLockedByMe`).
   - Dynamically update input placeholder to reflect case ownership status:
     - Unclaimed: `"Claim case to chat with AI Copilot…"`
     - Claimed by other: `"Case claimed by another analyst. Claim required to chat."`
     - Lease expired: `"Review lease expired. Claim case to chat with AI Copilot…"`
     - Claimed by me: `"Ask Agents about this case…"`
   - Guard `handleSendMessage` and `handleFileUpload` with `!isLockedByMe` to prevent keyboard/programmatic bypass.

2. **Backend Safe Error Diagnostics**:
   - Implement `_diagnose_failure(exc)` in `src/services/agent_runtime.py`:
     - `PermissionError` / 403 -> `FORBIDDEN` (retryable=False)
     - 404 -> `NOT_FOUND` (retryable=False)
     - `TimeoutError` -> `PROVIDER_TIMEOUT` (retryable=True)
     - `psycopg.Error` -> `PERSISTENCE_UNAVAILABLE` (retryable=True)
     - Other -> `PROVIDER_UNAVAILABLE` (retryable=True)
   - Log full stack traces via `logger.exception` without exposing credentials or auth tokens in SSE event streams.
   - Use `LEFT JOIN` for `trip_assignments` and `drivers` in `authorize_case` and `fetch_case_context`.
   - Explicitly cast UUID parameters (`case_id=%s::uuid`, `actor_id=%s::uuid`) in SQL queries.

## Rationale & Alternatives Considered
| Option | Pros | Cons | Decision |
|---|---|---|---|
| Client-side ownership gating + server authorization | Fast UX feedback, zero wasted LLM turns, prevents 403s | Needs synchronizing lease states | Selected |
| Server-only check | No UI changes | Frustrating UX, analyst types query only to receive error | Rejected |
| Generic error for all failures | Simple | Obscures database vs auth vs provider timeouts | Rejected |

## Consequences
- Unclaimed and other-analyst cases cannot trigger copilot turn requests.
- Claiming an eligible case immediately enables copilot chat; releasing or lease expiry immediately disables it.
- Database joins accommodate cases with unlinked or synthetic driver assignments.
- SSE error streams provide actionable, safe error codes to the cockpit UI.

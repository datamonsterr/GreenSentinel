# ADR-019: Separate active triage membership from retained history

## Status
Accepted for the bounded queue correction in [issue #143](https://github.com/AI20K-Build-Phase-Cohort-4/P-063/issues/143).

## Context
The cockpit requests Available and My Cases without a status filter. The service previously included finalized records, and the client refreshed the queue only after a separate detail fetch succeeded. A committed decision could therefore leave an actionable row visible.

## Decision
`CaseService.list_cases` excludes `resolved`, `dismissed`, `suspended`, and historical `auto_dismissed` records when no explicit status is supplied and availability is `available` or `mine`. The predicate runs before both count and pagination. Explicit status queries and `availability=all` retain authorized history. Existing organization and lease restrictions still apply.

Current terminal adjudications persist `resolved`; the other excluded spellings are legacy values already recognized by the service. This decision does not authorize new transitions. `evidence_requested`, `escalated`, `pending_analyst_review`, and other nonterminal records remain eligible under existing ownership restrictions. Request Evidence remains supported; the current API rejects new Escalate requests. Lifecycle expansion belongs to #147.

After a successful decision, the cockpit awaits a queue refresh independently of detail retrieval. Request Evidence also reloads detail because the case remains active. A failed submission retains the row.

## Rationale & Alternatives Considered
| Option | Benefit | Limitation | Decision |
|---|---|---|---|
| Service predicate before count/page | Consistent HTTP and service consumers; correct totals | Must mirror the test fallback | Selected |
| Browser-only row filtering | Small visual change | Incorrect totals and stale reloads | Rejected |
| Delete finalized records | Removes visible rows | Destroys evidence and history | Rejected |
| Introduce a new lifecycle | Could clarify future states | Expands the agreed bug scope | Deferred to #147 |

## Consequences
No migration or graph change is required. History preservation, actual transitions, stale retries, pagination, and browser reload are covered separately. Preservation of seeded historical audit records does not demonstrate creation of new decision audit events; the existing adjudication path lacks that writer and complete audit acceptance remains open.

## Architectural boundaries
- **System topology:** React calls authenticated FastAPI routes, which delegate queue queries and decisions to `CaseService`; PostgreSQL owns persistence. The LangGraph layer and external providers are unchanged.
- **State and graph lifecycle:** No TypedDict, node, conditional edge, or agent authorization changes. Queue filtering consumes committed case status.
- **Tool contracts:** Existing validated API/service arguments remain unchanged. Invalid availability/status remains HTTP 400. Existing service failure handling remains in effect.
- **Data flow:** Analyst confirms with rationale; adjudication commits; client refetches active queue; service filters before count/page; selected case updates. Nonterminal detail reload and SSE behavior remain independent.
- **Trade-offs:** Central filtering preserves history and pagination correctness while avoiding a new lifecycle or client policy duplication.
- **Security:** Parameterized SQL and existing organization/lease restrictions remain enforced. No keys, identity rules, or rate limits change.

# ADR-010: Driver GSupport Case Session Management and Shadcn Chatbot UI Architecture

## Release authority and runtime boundary

The strict Phase 1 [PRD](../ba/PRD.md), adopted **2026-09-30 by @datamonsterr**, governs release scope. Recommendations and corroboration wait for **authorized analyst confirmation with written rationale**. No automatic dismissal is approved. All adverse sanctions, including warnings, require confirmation and rationale; blocking guardrails keep adverse sanctions blocked. Driver UI/mobile and appeal expansion are **deferred**.

[PR #40](https://github.com/AI20K-Build-Phase-Cohort-4/P-063/pull/40) is **MERGED historical runtime divergence**, commit `586caec05ddb7626a1f47066b55154e74d245cc0`, not accepted release scope. That baseline let traffic corroboration write `auto_dismissed` and return `needs_analyst_review=False`. Accepted upstream [PR #93](https://github.com/AI20K-Build-Phase-Cohort-4/P-063/pull/93), merged on 2026-10-02 at `16c1ad6bdc910badbe852418bc5de5b456759156`, removes the new automatic-dismissal transition and returns a recommendation awaiting analyst review. Legacy `auto_dismissed` records remain readable; this preserves history rather than authorizing a new autonomous outcome. [Issue #73](https://github.com/AI20K-Build-Phase-Cohort-4/P-063/issues/73) remains open for its independently accepted full DoD; merging #60/#86 does not close it by inference. Existing driver interfaces remain inherited baseline and do not approve driver/mobile/appeal expansion. This documentation correction changes no runtime and claims no separate hosted or database conformance proof.

## Status

Historical V2 design (originally accepted after Grill-with-Docs); conflicting release authorization superseded by the strict Phase 1 PRD adopted 2026-09-30 by @datamonsterr. Driver UI/mobile and appeal expansion are deferred; merged sessions/transports are inherited baseline.

## Context

The historical driver portal design recorded the following UX motivations; this ADR does not independently validate the operational feedback:
1. **Redundant Text & Tag Clutter:** The previous `/driver` landing page and dispute screen were overloaded with hero marketing text, multiple redundant badge tags, and excessive forms that overwhelmed drivers on mobile screens.
2. **Lack of Centralized Case Session Management:** Drivers could not view an overview of all their ongoing dispute sessions or case statuses (such as AI system predictions vs customer complaints) with timestamps and progress states.
3. **Disjointed Chat UI & Rich Evidence Ingestion:** The chat interface needed modern conversational UX (`GSupport` AI Care Agent) capable of rendering rich interactive evidence inline:
   - Interactive GIS Map with trip breadcrumbs, pickup/dropoff points, and speed/delay metrics.
   - Expandable Thinking & Tool Call execution traces (`corroborate_traffic_conditions`, `query_driver_policy`).
   - Grounded Policy RAG chunks with highlighted legal articles (e.g. GreenSM Code of Conduct Article 12.2).

## Decision (historical V2 design; new driver UI/mobile scope deferred)

The original decision rebuilt the Driver Portal as a **Shadcn Chatbot Interface** powered by **GSupport** and structured around **Case Sessions**. The details below preserve that design and inherited interfaces; they do not authorize Phase 1 driver/mobile or appeal expansion.

### 1. Case Session Management & Navigation
- **Initial View (historical):** Case session dashboard with violation title, timestamp, report source, and badges (`in_dispute`, `auto_dismissed`, `resolved`, `ready`). `auto_dismissed` is an inherited noncompliant status from the #73 gap, not an approved dismissal option or target state.
- **No Unnecessary "New Case" Button:** Dispute cases are strictly system-instantiated when fraud models detect anomalies or customer reports arrive; drivers do not arbitrarily create unbound cases.
- **Responsive Split Layout:**
  - **Desktop:** Left pane (35% width) shows the case session list; Right pane (65% width) renders the active GSupport chat workspace.
  - **Mobile:** Mobile view shows the case session list; tapping a session smoothly navigates into the full-screen GSupport conversation with a back button.
  - **Deep-Link Email Integration:** Notifications sent via email directly link to `/driver?caseId={case_id}` or `/driver/dispute/{case_id}`, instantly focusing that session.

### 2. GSupport Conversational Agent Experience
- **Identity:** Dedicated GreenSM AI Driver Care Agent named **`GSupport`**.
- **Historical Session Loading:** Clicking any case session calls `GET /api/v1/driver/cases/{case_id}/session` to restore conversation history.
- **SSE Token Streaming:** Driver responses stream incrementally via `POST /api/v1/driver/cases/{case_id}/chat/stream`.

### 3. Rich Inline Component Architecture
Inside the GSupport conversational stream, the UI renders:
- **Map & Telemetry Card:** Embedded `MapLibreView` route geometry, GPS breadcrumbs, and trip telemetry (distance, duration, average corridor speed, traffic congestion multiplier).
- **Thinking & Tool Execution Accordions:** Visual indicator (`progress_activity` spinner) during reasoning, expanding to show tool calls (`search_policy`, `corroborate_traffic_conditions`) and status.
- **Policy RAG Citations:** Cited articles from GreenSM policies with highlighted relevant clauses (e.g., Article 12.2 on traffic congestion exoneration).

### 4. UI Domain Autonomy & Rule
The historical presentation split follows [frontend guidelines](../../.agents/rules/ui.md):
- Driver GSupport UI (`/driver`) and Analyst Cockpit UI (`/workplace`) maintain separate presentation implementations to avoid tight coupling across divergent stakeholder workflows.
- Domain-tailored chat widgets (Map preview, Thinking/Tool traces, RAG policy highlights) are independently maintained in each view.

## Historical decision record

The original decision was accepted as a V2 GSupport driver session/dashboard redesign: desktop split panes, a mobile conversation flow, notification deep links, REST session loading, SSE replies, and rich map/policy/tool widgets. PR #40 merged this history. The strict PRD adopted 2026-09-30 supersedes any conflicting release authorization; driver UI/mobile and appeal expansion remain deferred. Existing transport/session schemas may be retained as baseline without approving new driver product work.

## Rationale & Alternatives Considered

| Option | Pros | Cons | Decision |
|---|---|---|---|
| Analyst cockpit as Phase 1 release client | Matches approved analyst decision flow | New driver UX waits | Current release boundary |
| Expand GSupport mobile/session UI | Historical design centralized disputes | Driver/mobile expansion is outside Phase 1 | Deferred |
| Separate presentation with shared inherited transport | Historical design avoided coupling actor views | Duplicate presentation components | Retained historical design; no new implementation authorization |

## Required architecture questions

| Question | Answer |
|---|---|
| System topology | Historical Next.js driver presentation uses FastAPI REST/SSE, inherited agent/tool services, and PostgreSQL case sessions. The approved release client is the analyst cockpit; see [release topology](POC_DESIGN.md#system-topology). |
| State and graph lifecycle | Case selection and conversation history are UI/session state, separate from [`AgentState`](../../src/agents/state.py). Inherited [`graph.py`](../../src/agents/graph.py) routes tool calls through `agent`/`tools`; no session badge authorizes a terminal decision. |
| Tool contracts | Context, telemetry, and policy widgets render scoped tool outputs. Inputs require validation; errors/unavailable data must remain visible and cannot become evidence. [Failure requirements](POC_DESIGN.md#tool-contracts-and-failure-behavior) are not proof that each legacy path enforces them. |
| Data flow | Historical session selection loads REST history; chat sends an authenticated request and consumes SSE reply/tool status. The approved boundary sends recommendations to an authorized analyst for confirmation and written rationale, never automatically resolves a case. Hidden reasoning is not a UI output contract. |
| Trade-offs | Actor-specific presentation reduces coupling; retaining old interfaces avoids unnecessary migration. New driver/mobile/appeal UX remains deferred. |
| Security boundaries | [Security requirements](POC_DESIGN.md#security-and-operations) keep keys server-side, sanitize rendered input, and require identity scoping, request bounds/rate limits, and analyst authorization. A URL or status badge grants no authority; blocked adverse sanctions remain blocked. Hosted behavior is unverified by this correction. |

## Consequences

This correction preserves the historical UI design while removing its release authority. It changes no UI, transport, database, or runtime tests and provides no deployment, authentication, or adjudication compliance proof.

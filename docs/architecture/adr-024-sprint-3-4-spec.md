# ADR-024: Sprint 3–4 System Enhancements, Motivation Modeling & Telemetry

## Status
Accepted

## Context
Following the stabilization of Phase 1 core triage and driver dispute intake (ADR-018, ADR-021, ADR-022), operational reviews revealed critical feature gaps for Demo Day:
1. **Forensic Motivation Analysis**: Current forensic briefs output deterministic rule strings without evaluating economic rewards (fare deltas, surge capture) or driver behavioral intent in natural Vietnamese.
2. **Cockpit UI/UX Confusion**: Analysts had access to an input box within the historical Driver–Customer conversation tab, creating a risk of accidental message leakage. Concurrently, analysts lacked a dedicated channel to view live Driver Agent chat and directly message drivers.
3. **Evidence Dossier Expansion**: The system lacked an upload interface to attach supplemental case documents (dashcam photos, toll receipts) and selectively submit them to the driver.
4. **Agent Self-Improvement & Closed-Loop Learning**: Model prompts were static. The platform lacked passive analyst tracking to extract golden trajectories for few-shot exemplars and negative pairs for DPO tuning.
5. **Hybrid Telemetry & E2E Validation**: Backend agent traces in LangSmith lacked correlation with frontend user interaction, tab dwell time, and end-to-end MTTR funnels in PostHog.

## Decision
1. **Motivation & Economic Incentive Model**: Introduce `DriverMotivationAssessment` schema evaluating financial gain, intent profiles, and generating un-templated, natural Vietnamese narratives.
2. **Dual-Tab Copilot Workspace**:
   - Make the Driver–Customer conversation tab strictly read-only with an LLM summary badge.
   - Refactor the Copilot drawer into two tabs: *AI Copilot* (internal tools, policy queries) and *Driver Relay* (live GSupport chat + direct analyst messaging stamped as `sender: "analyst"`).
3. **Case Document Store**: Create `app.case_documents` with storage URLs and an evidence sharing toggle linked to driver dispute sessions.
4. **Passive Telemetry & Closed-Loop Agent Learning**:
   - Track analyst dwell times and evidence clicks via `navigator.sendBeacon('/api/v1/telemetry/analyst-session')` without UI lag.
   - Promote verbatim-accepted briefs (<5% edit delta) to dynamic few-shot exemplars in `cockpit_agent`. Export overturned recommendations as DPO training pairs.
5. **Hybrid PostHog + LangSmith Observability**:
   - Instrument frontend clickstream and MTTR conversion funnels via `posthog-js`.
   - Bridge frontend sessions with backend LangSmith agent traces using shared `case_id` and `trace_id`.
6. **E2E Scenario Orchestrator**: Build a 1-click end-to-end simulation runner on `/test` dashboard demonstrating the complete lifecycle across driver and analyst personas.

## Rationale & Alternatives Considered
| Option | Pros | Cons | Decision |
|---|---|---|---|
| **Hybrid PostHog + LangSmith** | Best-of-breed: Native UI clickstream & MTTR funnels (PostHog) + deep LangGraph graph tracing (LangSmith) | Two client libraries | Selected |
| **LangSmith Only** | Single vendor | Zero DOM/click tracking; cannot measure UI dwell or MTTR funnels | Rejected |
| **PostHog Only** | Single vendor | Weak LangGraph nested span visualization & agent debugging | Rejected |
| **Dual-Tab Copilot Drawer** | Clean separation of internal AI assistance vs driver communication; eliminates chat leakage | Minor drawer UI refactor | Selected |
| **Passive Beacon Telemetry** | Zero main-thread UI jank, non-intrusive tracking | Requires backend aggregation endpoint | Selected |

## Consequences
- Preserves strict Human-in-the-Loop governance (NFR-L06-02) while equipping analysts with deeper economic motive insights.
- Eliminates analyst message pollution into passenger records.
- Closes the loop from human adjudication back into autonomous agent refinement without manual prompt rewriting.
- Enables audited sub-45s MTTR verification for Demo Day.

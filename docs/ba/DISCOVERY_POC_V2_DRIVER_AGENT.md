# POC v2 Business Analysis Discovery: Async Driver Agent & Copilot Collaboration

> **Methodology:** BA Zone Senior BA Elicitation Protocol (`ask-why-ba`)  
> **Session Date:** 2026-09-26  
> **Author:** Team GreenSentinel  
> **Status:** Historical discovery — **Superseded for Phase 1**
> **Target Scope:** Deferred POC v2 extension; reference to [existing implementation](https://github.com/AI20K-Build-Phase-Cohort-4/GreenSentinel/pull/40), not release acceptance

## Current Release Authority

**@datamonsterr adopted the strict Phase 1 [PRD](PRD.md#1-document-control) on 2026-09-30.** All dismissals and adverse sanctions, including warnings, require authorized analyst confirmation plus written rationale. Former autonomous exoneration is superseded; telemetry corroboration can only support a recommendation. Driver mobile/dispute expansion (`US-L06-09/10`, `UC-L06-08/09`) and appeals are deferred, requiring separate scope approval.

Metric, score, and optional top-k elaboration was approved on **2026-10-02** in the [decision baseline](DECISION_LOG.md#approved-phase-1-decision-baseline). CV-01 and operator UAT remain pending. [PR #40](https://github.com/AI20K-Build-Phase-Cohort-4/GreenSentinel/pull/40) is **MERGED** at `586caec05ddb7626a1f47066b55154e74d245cc0`; its runtime divergence is tracked by [#73](https://github.com/AI20K-Build-Phase-Cohort-4/GreenSentinel/issues/73), owned by [#86](https://github.com/AI20K-Build-Phase-Cohort-4/GreenSentinel/issues/86) / [#60](https://github.com/AI20K-Build-Phase-Cohort-4/GreenSentinel/issues/60). This historical record does not establish runtime conformance.

As of upstream PR #93, the corroborated-traffic path no longer introduces the new autonomous-dismissal behavior: it remains pending analyst review. This document records the upstream correction only; issue #73 remains open, and this reconciliation does not accept or close it or claim full runtime DoD. The former PR40 implementation remains historical evidence in the immutable [PR40 source snapshot](https://github.com/AI20K-Build-Phase-Cohort-4/GreenSentinel/blob/586caec05ddb7626a1f47066b55154e74d245cc0/src/services/driver_dispute_service.py).

---

## 1. Intent Detection

Classified under **Operational Pain + Process Bottleneck** with **Solution Bias**:

| Dimension | Observed State |
|---|---|
| **Stated Painpoint** | When risk models detect fraud and notify drivers, drivers reject with reasons. Fraud analysts must manually reach out, wait for driver responses, and verify claims using separate tools. Drivers wait in limbo; analysts waste time on repetitive phone calls. |
| **Proposed Solution** | Build an asynchronous AI Driver Agent to respond to drivers immediately, learn recurring verification procedures, summarize driver responses, and interface with the Fraud Analyst's Copilot in the same Cockpit chatbox. Share tools and add a database `driver` role. |
| **Solution Bias Flag** ⚠️ | Treating "AI Agent + unified chatbox" as the requirement before clarifying decision autonomy, fraud evasion risks, tool segregation boundaries, and legal admissibility of AI-collected driver statements. |

---

## 2. Requirement Layer Status (5 BABOK Layers)

| Layer | Question it Answers | Status | Gaps Identified |
|---|---|---|---|
| **Business Requirement** | *Why* are we doing this? | 🟡 Partial | Goal is reducing MTTR and manual analyst outreach, but specific quantitative KPI targets (e.g. % outreach automation, MTTR reduction target, driver dispute SLA) are not yet specified. |
| **Stakeholder Requirement** | *Who* needs what? | 🟡 Partial | Drivers need 24/7 instant dispute intake without phone tag. Analysts need pre-verified facts, automated routine inquiries, and unified cockpit interaction without leaving their workstation. |
| **Functional Requirement** | *What* must the system do? | 🟡 Partial | Driver-facing conversational agent, shared tool registry, database `driver` role in `app.principal_roles`, bi-directional handoff, and synthesis in the analyst cockpit chatbox. |
| **Non-Functional Requirement** | *How well* must it do it? | ⛔ Missing | Response latency SLA, prompt injection resilience, PII masking in agent context, audit logging of driver chat, and strict adherence to `NFR-L06-02` (zero automated sanctions). |
| **Transition Requirement** | How do we *get there*? | ⛔ Missing | PostgreSQL migration for `driver` role, RLS policies for driver-scoped data access, backfill of existing driver principals, and rollout strategy. |

---

## 3. Gap Detection (Known vs. Unknown)

```
Known:
- Current process: Synchronous manual phone/message outreach causes high investigation latency.
- Repeated patterns: Same violation types (ERR-02 stall, ERR-05 GPS spoofing) and reasons (traffic, app crash, road work).
- Architectural vision: Async Driver Agent collects explanation -> auto-corroborates via tools -> summarizes to Analyst Copilot in unified chatbox.
- Database requirement: Driver authentication role in PostgreSQL (`app.principals` / `app.principal_roles`).
- Tooling requirement: Shared/extended tools in `src/agents/tools/` for evidence verification.

Unknown:
- Autonomy Boundary: Does Driver Agent have authority to dismiss clear false positives, or strictly recommend to human analyst?
- Evasion / Jailbreak: How to prevent drivers from coaxing the Driver Agent into excusing obvious fraud?
- Communication Channel: Does the driver interact via mobile app, web portal, or simulated webhook API in POC v2?
- Chatbox Topology: In the Cockpit, how are Driver-Agent turns rendered vs Analyst-Copilot turns (tabs vs interleaved thread vs split pane)?
- Tool Permissions: Which tools are safe for Driver Agent vs strictly reserved for Fraud Analyst?
```

---

## 4. Historical Architecture Decisions — Superseded for Phase 1

The following decisions record the former discovery direction in [`ADR-008`](../architecture/adr-008-poc-v2-async-driver-agent-and-a2a-collaboration.md) and [`POC_DESIGN.md`](../architecture/POC_DESIGN.md). Their autonomy exception is **superseded**, and driver expansion is **deferred**. Historical confirmation is not current release approval.

1. **Decision Autonomy & Guardrails (`NFR-L06-02`):**
   - **Autonomous Exoneration (historical, superseded):** The former proposal allowed `status = 'auto_dismissed'` when deterministic telemetry/OSRM corroborated congestion/stall (traffic delay ratio > 2.0x, speed < 5 km/h, GPS valid, 0 past sanctions). Current Phase 1 forbids this transition without authorized analyst confirmation and written rationale.
   - **Zero Auto-Sanction Invariant:** Punitive actions (fines, suspensions, warnings) strictly require human Fraud Analyst approval in the Cockpit.

2. **Cockpit Chatbox Interaction Model:**
   - **Agent-to-Agent (A2A) Synthesis:** Sentinel Copilot renders a synthesized dispute brief (driver explanation, tool corroboration, discrepancy score) and forwards analyst delegation instructions to the Driver Agent asynchronously.

3. **Tool Access & RBAC Segregation:**
   - Partitioned registries: Dedicated [`src/agents/tools/driver_tools.py`](../../src/agents/tools/driver_tools.py) (`DRIVER_TOOLS`) containing `get_driver_dispute_context`, `corroborate_traffic_conditions`, `submit_driver_statement`, and `query_driver_policy` with strict driver-scoped RBAC. Privileged tools remain in [`src/agents/tools/analyst_tools.py`](../../src/agents/tools/analyst_tools.py).

4. **Driver Channel & Database Authentication:**
   - Add `driver` role to `app.principal_roles` check constraint in PostgreSQL.
   - Dedicated mobile-first Next.js page at `/driver/dispute/[caseId]`.
   - 48-hour dispute window following violation notice.
   - Neutral deflection against adversarial prompt injection attempts.

---

## 5. Deferred Draft User Stories (Specification Only)

These stories are historical references to existing implementation, not Phase 1 Must requirements or completed acceptance evidence. Their intake and collaboration scenarios require separate scope approval; every eventual dismissal still requires analyst confirmation and written rationale.

### US-L06-09 — Async Driver Fraud Disputation via Driver Agent
**As a** GreenSM Driver notified of a suspected fraud/violation finding  
**I want to** dispute the violation interactively with an AI Driver Agent at any time  
**So that** my explanation is evaluated immediately without waiting days for a manual phone call, and standard verifiable excuses are collected with appropriate evidence.

- **AC1 — Immediate async intake & evidence collection (happy):** Given a driver rejects a fraud notification with a reason, when the driver initiates chat with the Driver Agent, then the agent validates driver identity and assigned case, acknowledges the reason immediately, asks targeted follow-up questions or requests relevant evidence based on historical case procedures, and logs the structured response.
- **AC2 — Automatic routine verification via shared tools (edge):** Given the driver claims a verifiable condition (e.g. traffic jam, technical glitch), when the Driver Agent queries shared verification tools (telemetry, route history, traffic check), then it flags whether the claim is corroborated by data and prepares a synthesized dossier for analyst review without making an autonomous sanction or penalty decision.
- **AC3 — Unauthorized case access or adversarial manipulation (negative):** Given a request from a principal not authenticated with `role: driver` matching the specific `driver_id` or case, when accessing case chat, then access is denied with 403 Forbidden, and attempts to override system instructions are trapped and audited.

### US-L06-10 — Unified Analyst-Driver Agent Collaboration & Synthesis
**As a** Fraud Analyst reviewing a contested fraud case in the Cockpit  
**I want to** review the Driver Agent's summarized Q&A, corroboration status, and interact with the Driver Agent via the Cockpit chatbox  
**So that** I can make an informed adjudication without repetitive manual calling, and request specific follow-up questions or manual actions from the driver asynchronously.

- **AC1 — Synthesized dispute summary display (happy):** Given a driver has completed or is conducting an async chat with the Driver Agent, when the analyst opens the case in the Cockpit, then the Cockpit chatbox displays a synthesized dispute brief (driver claims, verified facts, discrepancy score, recommended actions) alongside raw transcripts.
- **AC2 — Analyst prompt delegation to Driver Agent (edge):** Given the analyst needs additional clarification from the driver, when the analyst enters an instruction in the Cockpit chatbox (e.g., "Ask the driver why they turned off GPS at 14:22"), then the system dispatches an asynchronous follow-up task to the Driver Agent to notify the driver.
- **AC3 — Zero automated adverse sanction (negative):** Given the Driver Agent determines a driver explanation is unconvincing or false, when the analysis completes, then the system strictly prohibits automated punitive actions (`NFR-L06-02`) and requires explicit human analyst approval to apply any sanction.

---

## 6. Historical Implementation References
1. **ADR Codification:** Published [`ADR-008: POC v2 Async Driver Dispute Agent, A2A Collaboration, and Autonomous Exoneration Protocol`](../architecture/adr-008-poc-v2-async-driver-agent-and-a2a-collaboration.md).
2. **System Design:** Widened technical scope in [`docs/architecture/POC_DESIGN.md`](../architecture/POC_DESIGN.md) covering topology, the historical deterministic auto-dismissal proposal, partitioned tool contracts, and API routes.
3. **Traceability:** Integrated `US-L06-09`, `US-L06-10` into [`docs/ba/USER_STORIES.md`](USER_STORIES.md) and `UC-L06-08`, `UC-L06-09` into [`docs/ba/USE_CASES.md`](USE_CASES.md).
4. **Historical PR record:** [#35](https://github.com/AI20K-Build-Phase-Cohort-4/GreenSentinel/pull/35). Current release authority is stated above; this reference does not assert current PR state.

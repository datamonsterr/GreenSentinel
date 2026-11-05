# ADR-008: Async Driver Dispute and A2A Handoff — Analyst Confirmation Boundary

## Status

Historical V2 decision; conflicting release authorization superseded by the strict Phase 1 [PRD](../ba/PRD.md), adopted **2026-09-30 by @datamonsterr**. Driver mobile and appeal expansion are deferred.

## Release authority and runtime boundary

The strict Phase 1 [PRD](../ba/PRD.md) was adopted 2026-09-30 by @datamonsterr. Driver UI/mobile and appeal expansion remain deferred.

Phase 1 permits recommendations and corroboration only until **authorized analyst confirmation with written rationale**. No automatic dismissal is approved. All adverse sanctions, including warnings, require the same confirmation and rationale; a blocking technical guardrail remains blocked despite a recommendation or confirmation attempt.

[PR #40](https://github.com/AI20K-Build-Phase-Cohort-4/GreenSentinel/pull/40) is **MERGED historical runtime divergence**, commit `586caec05ddb7626a1f47066b55154e74d245cc0`, not accepted release scope. That baseline let traffic corroboration write `auto_dismissed` and return `needs_analyst_review=False`. Accepted upstream [PR #93](https://github.com/AI20K-Build-Phase-Cohort-4/GreenSentinel/pull/93), merged on 2026-10-02 at `16c1ad6bdc910badbe852418bc5de5b456759156`, removes the new automatic-dismissal transition and returns a recommendation awaiting analyst review. Legacy `auto_dismissed` records remain readable; this preserves history rather than authorizing a new autonomous outcome. [Issue #73](https://github.com/AI20K-Build-Phase-Cohort-4/GreenSentinel/issues/73) remains open for its independently accepted full DoD; merging #60/#86 does not close it by inference. Existing driver interfaces remain inherited baseline and do not approve driver/mobile/appeal expansion. This documentation correction changes no runtime and claims no separate hosted or database conformance proof.

## Context

The historical V2 proposal extended the analyst design ([`POC_DESIGN.md`](POC_DESIGN.md)) with driver notifications and disputed alerts (`ERR-02` or `ERR-05`). It sought to address a manual contact bottleneck:
1. **Analyst Phone-Tag Bottleneck:** Fraud analysts had to dial or message drivers directly, waiting for drivers to answer while drivers waited in limbo.
2. **Repetitive Inquiries:** A high percentage of contested alerts stemmed from identical, verifiable operational situations (heavy traffic gridlock, signal loss in tunnels, app crashes) that followed routine verification checklists.
3. **Cockpit Context Switching:** Analysts had to leave their queue workspace to query separate tools and contact drivers, inflating investigation MTTR.

The historical proposal introduced an asynchronous Driver Agent and Sentinel Copilot collaboration. Existing transports, tools, and sessions are inherited baseline; their presence does not authorize new driver UI/mobile or appeal scope.

## Decision

Retain the historical multi-agent component boundaries as implementation context, with the following release correction. The approved target keeps adjudication in the analyst cockpit; driver product expansion remains deferred.

### 1. Decision Autonomy & Safety Boundaries

- **Corroboration is advisory:** Traffic delay, speed, GPS validity, and sanction history may support a dismissal recommendation. They never authorize a terminal transition or an exoneration receipt. The case waits for authorized analyst confirmation with written rationale, whether corroboration succeeds, fails, or is unavailable.
- **Zero automated adverse sanctions (`NFR-L06-02`):** Fines, suspensions, warnings, and punitive strikes require authorized analyst confirmation with written rationale. A technical guardrail keeps adverse sanctions blocked; corroboration and precedent scores cannot override it. The inherited compact commands (`REQUEST_EVIDENCE`, `DISMISS`, fraud-confirming `APPROVE`) are not the full strict PRD `FR-04` action panel. Evidence requests remain nonterminal; each approved human dismissal or sanction requires the analyst gate.

### 2. Agent-to-Agent (A2A) Collaboration Protocol

These are inherited V2 interfaces and historical design details, not newly approved release features.

- **Durable Session Persistence:** Inter-agent communication is stored in PostgreSQL `app.case_agent_sessions` with message roles `['analyst', 'assistant', 'driver', 'driver_agent']`.
- **Cockpit Synthesis Dossier:** When the analyst claims a disputed case, Sentinel Copilot renders a structured dispute dossier:
  - Driver statement & alleged extenuating condition.
  - Telemetry & traffic corroboration signals (traffic multiplier, stall duration delta).
  - Historical dispute precedent score.
  - Expandable verbatim driver-agent chat transcript.
- **Analyst Delegation:** Analysts can instruct Sentinel Copilot directly in the Cockpit chatbox (e.g. *"Ask driver why they turned off GPS at 14:22"*); Sentinel Copilot dispatches an asynchronous inquiry to the Driver Agent, alerting the driver upon next check-in.

### 3. Tool Segregation & Partitioned Registries

Tools are partitioned into isolated registries under `src/agents/tools/`:
- **`DRIVER_TOOLS` ([`src/agents/tools/driver_tools.py`](../../src/agents/tools/driver_tools.py)):**
  - `get_driver_dispute_context(case_id, driver_id)`: Read trip details, alleged violation, and dispute status. Scoped strictly to caller's `driver_id`.
  - `corroborate_traffic_conditions(case_id, start_time, end_time)`: Check OSRM and telemetry traffic congestion.
  - `submit_driver_statement(case_id, reason, claim_type)`: Append structured driver explanation and transition state.
  - `query_driver_policy(query)`: Retrieve driver rights, dispute timelines, and acceptable evidence rules.
- **`ANALYST_TOOLS` ([`src/agents/tools/analyst_tools.py`](../../src/agents/tools/analyst_tools.py)):**
  - Privileged tools are inherited baseline: [`adjudicate_case`, `claim_case`, `check_driver_suspension`, `trigger_simulation`](../../src/agents/tools/analyst_tools.py). Tool exposure is not proof of a compliant confirmation gate; the approved target requires server-side authorization and written rationale for every terminal decision.

### 4. Database Identity & Migration (historical baseline)

- **PostgreSQL Role Extension:** Historical migration [`20260926180000_poc_v2_driver_role_and_dispute.sql`](../../db/migrations/20260926180000_poc_v2_driver_role_and_dispute.sql) updates `app.principal_roles` check constraint:
  ```sql
  ALTER TABLE app.principal_roles DROP CONSTRAINT principal_roles_role_check;
  ALTER TABLE app.principal_roles ADD CONSTRAINT principal_roles_role_check 
    CHECK (role IN ('analyst', 'senior_analyst', 'demo_operator', 'admin', 'driver'));
  ```
- **RLS & Authorization:** FastAPI endpoints enforce `role: driver` and verify `principal.id == driver.principal_id`. Drivers cannot query other drivers' cases or global queues.

### 5. Frontend Channel & SLA Policies (historical proposal; deferred)

- **Dedicated Mobile Driver Page:** The historical design specified `/driver/dispute/[caseId]`; merged implementation does not authorize new driver/mobile development in Phase 1.
- **48-Hour Dispute Window:** The historical design specified a response deadline and forwarding to analyst triage. This is not a newly approved Phase 1 product SLA or permission to decide a case automatically.
- **Adversarial Neutral Deflection:** The Driver Agent ignores jailbreak prompts or demands to cancel fines, neutralising manipulation by restating: *"I can only record trip facts and check traffic conditions for human analyst review."*

## Historical decision record

The original accepted V2 decision authorized deterministic autonomous relief:

> When a driver disputes an `ERR-02` stall violation and deterministic telemetry corroboration confirms road gridlock, the Driver Agent autonomously dismisses the case (`status = 'auto_dismissed'`) and sends an exoneration receipt.

That authorization is superseded by the strict PRD adopted 2026-09-30. Its traffic thresholds (ratio > 2.0x, speed < 5 km/h, valid GPS, zero prior sanctions) remain historical design inputs, not a release dismissal gate. The original >60% inquiry automation, MTTR reduction, and 100% compliance statements were aspirations, not demonstrated results.

## Rationale & Alternatives Considered

| Option | Pros | Cons | Decision |
|---|---|---|---|
| Advisory corroboration with analyst confirmation | Meets strict PRD; preserves responsibility and rationale | Requires analyst time | Current release boundary |
| Autonomous exoneration from telemetry | Historical proposal reduced manual handling | Conflicts with approved no-auto-dismiss rule | Superseded authorization |
| New mobile driver/A2A product expansion | Historical proposal improved driver intake | Outside Phase 1 analyst scope | Deferred |

## Required architecture questions

| Question | Answer |
|---|---|
| System topology | Inherited driver REST/SSE interfaces call services and tools; PostgreSQL sessions feed analyst synthesis. The approved client remains the analyst cockpit; [topology](POC_DESIGN.md#system-topology) distinguishes the target. |
| State and graph lifecycle | Inherited [`AgentState`](../../src/agents/state.py) carries query, context, analysis, response, error, metadata, and messages. [`graph.py`](../../src/agents/graph.py) routes `agent` to `tools` when tool calls exist, otherwise ends; case status is separate. The release boundary forbids automatic terminal transitions. |
| Tool contracts | Existing driver/analyst registries remain documented above. Inputs must be scoped and validated; tool failures must remain explicit, never imply corroboration or a verdict. [Failure contract](POC_DESIGN.md#tool-contracts-and-failure-behavior) is a target, not a runtime audit. |
| Data flow | Inherited intake stores statements, reads corroboration, and synthesizes a dossier for analyst review. In the approved target only a confirmed authorized decision plus rationale reaches adjudication; REST/SSE streams replies and tool status, never hidden reasoning. |
| Trade-offs | Advisory reuse retains investigation assistance at the cost of human review; autonomous relief is rejected and new driver/mobile/appeal expansion is deferred. |
| Security boundaries | [Security requirements](POC_DESIGN.md#security-and-operations) keep keys server-side, validate/sanitize input, and bound requests/rate limits. Identity scoping, authorization, lease/version checks, and blocked adverse sanctions must hold at the server; no deployment or enforcement proof is claimed here. |

## Consequences

- **Safety:** Recommendations wait for an analyst decision with rationale; blocked adverse sanctions stay blocked. The #73 runtime gap must be resolved and independently verified before compliance is claimed.
- **Scope:** Existing driver interfaces are historical baseline, not approval for mobile or appeal expansion.
- **Evidence:** Session/audit structures support traceability; this documentation-only correction measures no throughput, MTTR, audit immutability, or hosted deployment outcome.

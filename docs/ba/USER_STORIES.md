# L06 User Stories — Release 1 HITL Enforcement

## Scope and Status

The strict Phase 1 [PRD](PRD.md#1-document-control) release scope was adopted by @datamonsterr on 2026-09-30. `US-L06-04` is its core story. Broader L06 stories remain future specifications subject to their linked [decisions](DECISION_LOG.md); project scope approval does not complete GreenSM CV-01 baseline confirmation or operator UAT. Estimates are `TBD` unless stated otherwise.

All dismissals and analyst Agree/Disagree outcomes require authorized analyst confirmation plus written rationale; the system never applies warnings, fines, clawbacks, or suspensions; algorithmic closure is deny-by-default. Stories describe acceptance requirements, not runtime test results.

> [!IMPORTANT]
> **Implementation Phasing Notice:**
> - **Target Release 1 Vision (L06):** Stories `US-L06-01` through `US-L06-08` represent the complete 8-epic target vision for full production rollout across passenger, driver, and internal operations.
> - **Phase 1 MVP Scope:** **Epic 5: Initial Adjudication ([`US-L06-04`](#us-l06-04--decide-an-initial-enforcement-case-phase-1-mvp-core))** and the **GreenSentinel Workplace (Fraud Analyst Adjudication Cockpit)**, governed by [`MVP.md`](MVP.md). All other stories, including `US-L06-09/10` driver expansion, are deferred to Phase 2+. Existing implementations or fixtures do not add them to release acceptance.

## US-L06-01 — Choose a Response to a Suspected-DIC Prompt

**As a** Passenger with an active pickup that enters the approved prompt band
**I want to** choose reassignment or continue the original trip
**So that** I can recover service without the platform declaring the Driver fraudulent.

**Metadata:** Epic: Live intervention; Priority: Deferred (Phase 2); Future vision priority: Must; Estimate: TBD; Dependencies: CV-06/08/11/20 decisions.

### Acceptance Criteria

**AC1 — Accept recovery (happy):** **Given** one trip enters the approved Passenger-prompt band and has no prior prompt, **when** the Passenger chooses reassignment, **then** the choice is recorded once, preserved reassignment is requested with dispatch, the original assignment transitions upon dispatch confirmation, and recovery status displays without labeling confirmed fraud.

**AC2 — No response (edge):** **Given** the prompt is outstanding, **when** the approved response window ends without Passenger action, **then** the original trip continues and no reassignment or Passenger cancellation is created by the prompt.

**AC3 — Duplicate or stale action (negative):** **Given** a terminal Passenger choice already exists or the trip is no longer eligible, **when** another prompt/action arrives, **then** no second trip action occurs and the rejected attempt is auditable.

### INVEST Self-Check

| Criterion | Status | Note |
|---|---|---|
| Independent | ✅ | One Passenger goal |
| Negotiable | ✅ | Copy/window remain decisions |
| Valuable | ✅ | Immediate service control |
| Estimable | ✅ | Bounded states |
| Small | ✅ | One interaction |
| Testable | ✅ | 3 GWT paths |

**Notes:** Exact bands, response window, copy, and accessibility require stakeholder approval. Traceability: FR-L06-01–04; DEC-L06-03–09.

## US-L06-02 — Receive a Preserved Replacement Trip

**As a** Passenger who accepted suspected-DIC recovery
**I want to** receive a replacement assignment with the original fare, voucher, pickup, and destination
**So that** recovery does not make me rebook or lose agreed trip value.

**Metadata:** Epic: Passenger recovery; Priority: Deferred (Phase 2); Future vision priority: Must; Estimate: TBD; Dependencies: dispatch/pricing/voucher decisions.

### Acceptance Criteria

**AC1 — Replacement found (happy):** **Given** recovery was accepted and a replacement Driver is available, **when** dispatch confirms reassignment, **then** the Passenger has one active replacement with the original fare, voucher, pickup, and destination.

**AC2 — Later Driver evidence (edge):** **Given** replacement is complete or in progress, **when** the original Driver later submits evidence, **then** the Passenger recovery remains unchanged and the evidence affects only adjudication.

**AC3 — Attribute mismatch (negative):** **Given** a replacement proposal changes a protected attribute, **when** reconciliation validates it, **then** the proposal is not finalized and the case enters the approved recovery exception path.

### INVEST Self-Check

| Criterion | Status | Note |
|---|---|---|
| Independent | ✅ | Recovery goal |
| Negotiable | ✅ | Dispatch design open |
| Valuable | ✅ | Preserves value |
| Estimable | ✅ | Four attributes defined |
| Small | ✅ | One outcome |
| Testable | ✅ | State assertions |

**Notes:** Traceability: FR-L06-05; DEC-L06-10.

## US-L06-03 — Submit Safe Evidence for Review

**As a** notified Driver whose pickup event is under suspected-DIC review
**I want to** submit an approved reason and permitted evidence within the policy window
**So that** an analyst considers legitimate pickup conditions before deciding enforcement.

**Metadata:** Epic: Driver evidence; Priority: Deferred (Phase 2); Future vision priority: Must; Estimate: TBD; Dependencies: CV-05/CV-09 policy.

### Acceptance Criteria

**AC1 — Submit allowed evidence (happy):** **Given** the Driver has an open submission opportunity and is safely stationary, **when** the Driver submits a written reason and any claim-required permitted video, **then** the submission is linked to the case with time/provenance and enters analyst-visible evidence.

**AC2 — No or late report (edge):** **Given** the approved deadline passes, **when** no report or a late report exists, **then** the case records the exact status and policy effect while retaining all system/application-error evidence.

**AC3 — Unsafe or unauthorized evidence (negative):** **Given** evidence violates the approved capture/content/type rule, **when** submission is attempted, **then** it is rejected or quarantined under policy, the reason is communicated, and no automatic sanction occurs.

### INVEST Self-Check

| Criterion | Status | Note |
|---|---|---|
| Independent | ✅ | Evidence goal |
| Negotiable | ✅ | Formats remain policy |
| Valuable | ✅ | Procedural fairness |
| Estimable | ✅ | Inputs bounded |
| Small | ✅ | One submission |
| Testable | ✅ | Happy/late/reject |

**Notes:** Moving-vehicle recording is prohibited. Exact deadline, authenticity, size, access, retention, deletion, and late-report rule are open. Traceability: FR-L06-07–09; DEC-L06-12–15.

## US-L06-04 — Decide an Initial Enforcement Case (Phase 1 MVP Core)

**As a** Fraud Analyst reviewing suspected Driver-Induced Cancellation (DIC) alerts
**I want to** inspect the unified spatial evidence dossier, verify system error guardrails, and execute an authorized adjudication outcome with mandatory rationale
**So that** legitimate drivers are protected from false alarms, predicted violations are verified, and 100% of adjudication actions remain auditable and human-signed.

**Metadata:**
- **Epic:** Epic 5: Initial Adjudication (Phase 1 MVP Core)
- **Priority:** Must
- **Estimate:** 5 Story Points
- **Traceability:** `FR-01`–`FR-05`, `NFR-01`–`NFR-04`, `DEC-L06-15`–`17`
- **Acceptance/test contract:** [AC-P1-01–09](PRD.md#101-phase-1-acceptance-and-test-traceability); [score and optional route boundary](PRD.md#94-per-case-classifier-confidence-and-route-alternatives).

### Acceptance Criteria (Gherkin Format)

#### Scenario 1: Successful Adjudication with Mandatory Rationale (Happy Path)
- **Given** Case `#C-101` is loaded in the cockpit with telemetry evidence and zero system errors
- **When** the Fraud Analyst selects an authorized outcome (`Agree` or `Disagree`) and enters a rationale of at least 10 non-whitespace characters
- **And** clicks "Submit Adjudication"
- **Then** the platform records the terminal decision, updates the case status to `Closed`, persists an immutable audit record binding analyst ID, case ID, decision, rationale, and evidence snapshot, and removes the case from the active triage queue within 1.5 seconds.

#### Scenario 2: System Error & Missingness Guardrail Advisory Signal (Safety Invariant)
- **Given** Case `#C-102` has an associated driver app crash or 4G network loss (> 30s) coinciding with the vehicle stall
- **When** the Fraud Analyst opens the case dossier
- **Then** the cockpit displays a prominent warning banner: `"⚠️ System Error Detected: Driver App Disconnect"`
- **And** the system marks the suggested outcome as `Disagree (System Error)` (advisory signal; it does not block or apply any outcome)
- **And** the case remains open until an authorized analyst confirms an outcome with written rationale of at least 10 non-whitespace characters (zero automated silent closures).

#### Scenario 3: Concurrency Lease Acquisition & Lock Timeout
- **Given** Case `#C-103` is currently claimed by Analyst A
- **When** Analyst B navigates to Case `#C-103`
- **Then** the cockpit renders the case in read-only mode with banner: `"Case locked by Analyst A. Auto-releases in MM:SS"`
- **And** after 300 seconds of Analyst A inactivity, the lease automatically expires, releasing the lock back to the active queue.

#### Scenario 4: Role-Based Access Control (RBAC Authority Boundary)
- **Given** an authenticated user without the authorized `Fraud Analyst` role
- **When** viewing the outcome bar or attempting to submit an adjudication outcome
- **Then** outcome submission is prohibited and attempts to submit an outcome via direct API return HTTP 403 Forbidden.

#### Scenario 5: Missing or Inadequate Rationale Validation
- **Given** an analyst selects `Agree` or `Disagree`
- **When** the analyst leaves the comment field blank or enters fewer than 10 non-whitespace characters
- **Then** the submit action remains disabled and an inline error appears: `"Rationale text is mandatory (minimum 10 characters)"`.

#### Scenario 6: Immutable Audit Trail Generation
- **Given** an analyst successfully signs off on any adjudication decision
- **When** the transaction commits
- **Then** an append-only audit record is stored with `case_id`, `analyst_id`, `action`, `rationale`, `decided_at`, and `evidence_snapshot_hash`
- **And** any attempt to update or delete the audit record is rejected by database security constraints.

### INVEST Self-Check

| Criterion | Status | Note |
|---|---|---|
| **Independent** | ✅ | Can be developed and tested independently of Phase 2 passenger/driver apps |
| **Negotiable** | ✅ | Rationale character limits and lease timeouts can be tuned per operational feedback |
| **Valuable** | ✅ | Targets MTTR <45s and protects against false alarms; backlog magnitude remains a CV-01 hypothesis |
| **Estimable** | ✅ | Well-bounded API, UI components, and audit persistence schema |
| **Small** | ✅ | Sized for delivery within the 5-week build phase |
| **Testable** | ✅ | 6 explicit Gherkin scenarios verifiable via automated unit, integration, and E2E tests |

## US-L06-05 — Obtain a Blinded Second Review

**As a** Driver with an appealable adverse decision
**I want to** request review by a different Fraud Analyst
**So that** the outcome can be reconsidered without prior-decision bias while remaining auditable.

**Metadata:** Epic: Appeals; Priority: Deferred (Phase 3); Future vision priority: Must; Estimate: TBD; Dependencies: CV-13/CV-16.

### Acceptance Criteria

**AC1 — Start blinded review (happy):** **Given** an eligible adverse decision, **when** the Driver requests second review and adds permitted material, **then** the sanction pauses and a different analyst receives raw authorized evidence without the appeal label, original decision, or rationale.

**AC2 — Preserve audit linkage (edge):** **Given** reviewer-facing fields are hidden, **when** an authorized auditor reconstructs the case, **then** the original/second decisions, identities, evidence versions, access and timestamps remain linked.

**AC3 — Same reviewer or exposed rationale (negative):** **Given** assignment violates separation or the blinded view exposes prohibited fields, **when** review opening is attempted, **then** review is blocked, the control failure is audited, and the sanction remains paused.

### INVEST Self-Check

| Criterion | Status | Note |
|---|---|---|
| Independent | ✅ | Appeal goal |
| Negotiable | ✅ | SLA/fields open |
| Valuable | ✅ | Fair reconsideration |
| Estimable | ✅ | Clear visibility states |
| Small | ✅ | One review |
| Testable | ✅ | Control paths |

**Notes:** Appeal SLA, compensation, exact field list, and final authority remain open. Traceability: FR-L06-13–15; DEC-L06-18–20/22.

## US-L06-06 — Complete Failed-Reassignment Recovery

**As a** Passenger whose replacement search reaches the approved no-driver condition
**I want to** receive the mandatory refund and approved voucher/support outcome
**So that** a failed recovery does not leave me charged or in an ambiguous trip state.

**Metadata:** Epic: Service-recovery exception; Priority: Deferred (Phase 2); Future vision priority: Must; Estimate: TBD; Dependencies: CV-14/CV-15.

### Acceptance Criteria

**AC1 — Refund after timeout (happy):** **Given** the approved no-driver condition is reached, **when** recovery closes, **then** the trip enters one failed-recovery state and the mandatory refund is recorded for reconciliation.

**AC2 — Voucher policy applied (edge):** **Given** an original voucher exists, **when** failed recovery closes, **then** the approved restore/replace/no-restoration outcome is recorded and communicated without inventing a fallback.

**AC3 — Refund integration failure (negative):** **Given** the refund cannot be confirmed, **when** the recovery close is attempted, **then** the Passenger is not shown a false completed refund, a reconciliation/support item is created, and retry does not duplicate payment action.

### INVEST Self-Check

| Criterion | Status | Note |
|---|---|---|
| Independent | ✅ | Terminal recovery |
| Negotiable | ✅ | Voucher option open |
| Valuable | ✅ | Avoids financial harm |
| Estimable | ✅ | States explicit |
| Small | ✅ | One exception |
| Testable | ✅ | Failure tested |

**Notes:** Timeout and voucher outcome require approval. Traceability: FR-L06-06; DEC-L06-11.

## US-L06-07 — Review Conflicting Decisions

**As a** Senior Fraud Analyst responsible for quality control
**I want to** review overturned cases on the approved weekly cadence
**So that** recurring policy, analyst, data, or model problems lead to governed corrective action.

**Metadata:** Epic: Quality governance; Priority: Deferred (Phase 3); Future vision priority: Should; Estimate: TBD; Dependencies: CV-17.

### Acceptance Criteria

**AC1 — Record weekly findings (happy):** **Given** the conflict queue contains eligible overturned cases, **when** the Senior Fraud Analyst completes the scheduled review, **then** each finding is classified against approved patterns with owner, action, evidence, and status.

**AC2 — Passenger contact (edge):** **Given** an approved review purpose permits contact, **when** the analyst requests Passenger contact, **then** purpose, authority, minimization, outcome, and access are audited without changing production thresholds.

**AC3 — Unapproved contact/change (negative):** **Given** contact or corrective action lacks authority, **when** it is attempted, **then** it is denied and audited and no Passenger communication or threshold activation occurs.

### INVEST Self-Check

| Criterion | Status | Note |
|---|---|---|
| Independent | ✅ | Review goal |
| Negotiable | ✅ | Taxonomy open |
| Valuable | ✅ | Learns from harm |
| Estimable | ✅ | Queue bounded |
| Small | ✅ | One review cycle |
| Testable | ✅ | Authority paths |

**Notes:** Pattern taxonomy, contact rules, and corrective-action powers are open. Traceability: FR-L06-16; DEC-L06-21.

## US-L06-08 — Control Release 1 Rollout and Rollback

**As a** Product Owner accountable for Release 1 safety
**I want to** enable, pause, or roll back approved live actions against versioned evidence
**So that** operational harm is bounded and no elapsed period silently expands enforcement.

**Metadata:** Epic: Release governance; Priority: Deferred (Phase 3); Future vision priority: Must; Estimate: TBD; Dependencies: CV-01–04/CV-10 and operations readiness.

### Acceptance Criteria

**AC1 — Authorize a bounded phase (happy):** **Given** the phase entry packet has required evidence, capacity, approvals, controls, and rollback values, **when** the Product Owner authorizes it, **then** only the named segment/action/policy version is enabled and the authorization is audited.

**AC2 — Trigger safe state (edge):** **Given** an approved rollback trigger occurs, **when** an authorized owner activates rollback, **then** the affected new action stops, accepted Passenger recovery and audit are preserved, enforcement is paused/rectified per policy, and restart requires reauthorization.

**AC3 — Unauthorized expansion (negative):** **Given** evidence, approval, or upstream gate is missing/expired, **when** enablement or expansion is attempted, **then** it is denied and audited and the existing safe boundary remains.

### INVEST Self-Check

| Criterion | Status | Note |
|---|---|---|
| Independent | ✅ | Release decision |
| Negotiable | ✅ | Phase values open |
| Valuable | ✅ | Bounds harm |
| Estimable | ✅ | Inputs enumerated |
| Small | ✅ | One phase change |
| Testable | ✅ | Enable/rollback/deny |

**Notes:** CV-18/CV-19 cannot be used to reduce human approval in L06. Traceability: FR-L06-17/18; DEC-L06-01/23–26.

## US-L06-09 — Conduct Async Fraud Dispute via Driver Agent

**As a** GreenSM Driver notified of a suspected fraud/violation finding  
**I want to** dispute the violation interactively with an AI Driver Agent at any time  
**So that** my explanation is evaluated immediately without waiting days for a manual phone call, and standard verifiable excuses (traffic, app drop, road closure) are collected with appropriate evidence.

**Metadata:** Epic: Driver Dispute & Handoff; Priority: Deferred (Phase 2+); Estimate: TBD; Dependencies: separate product approval.

**Release status:** Deferred reference to the [existing implementation in MERGED PR #40](https://github.com/AI20K-Build-Phase-Cohort-4/GreenSentinel/pull/40); not Phase 1 acceptance. Autonomous exoneration expectations are obsolete under [#73](https://github.com/AI20K-Build-Phase-Cohort-4/GreenSentinel/issues/73). The scenarios below specify a future intake flow, not evidence of delivery.

### Acceptance Criteria

**AC1 — Immediate async intake & evidence collection (happy):** **Given** a driver rejects a fraud notification with a reason, **when** the driver initiates chat with the Driver Agent, **then** the agent validates driver identity and assigned case, acknowledges the reason immediately, asks targeted follow-up questions or requests relevant evidence based on historical case procedures, and logs the structured response.

**AC2 — Automatic routine verification via shared tools (edge):** **Given** the driver claims a verifiable condition (e.g. traffic jam, technical glitch), **when** the Driver Agent queries shared verification tools (telemetry, route history, traffic check), **then** it flags whether the claim is corroborated by data and prepares a synthesized dossier for analyst review without making an autonomous sanction or penalty decision.

**AC3 — Unauthorized case access or adversarial manipulation (negative):** **Given** a request from a principal not authenticated with `role: driver` matching the specific `driver_id` or case, **when** accessing case chat, **then** access is denied with 403 Forbidden, and attempts to override system instructions (prompt injection) are trapped and audited.

### INVEST Self-Check

| Criterion | Status | Note |
|---|---|---|
| Independent | ✅ | Self-contained driver dispute session |
| Negotiable | ✅ | Intake prompts and question depth tunable |
| Valuable | ✅ | Eliminates driver wait time & intake backlog |
| Estimable | ✅ | Bounded conversational state machine |
| Small | ✅ | One async dispute cycle |
| Testable | ✅ | 3 GWT paths with verified assertions |

**Notes:** Traceability: PP-05, FR-L06-19. Zero automated penalty or exoneration without analyst sign-off (`NFR-L06-02`).

## US-L06-10 — Review Driver Agent Synthesis and Intervene in Cockpit Chatbox

**As a** Fraud Analyst reviewing a contested fraud case in the Cockpit  
**I want to** review the Driver Agent's summarized Q&A, corroboration status, and interact with the Driver Agent via the Cockpit chatbox  
**So that** I can make an informed adjudication without repetitive manual calling, and request specific follow-up questions or manual actions from the driver asynchronously.

**Metadata:** Epic: Analyst-Agent Collaboration; Priority: Deferred (Phase 2+); Estimate: TBD; Dependencies: separate product approval.

**Release status:** Deferred reference to the [existing implementation in MERGED PR #40](https://github.com/AI20K-Build-Phase-Cohort-4/GreenSentinel/pull/40); not Phase 1 acceptance. The scenarios below specify future driver-agent collaboration, not evidence of delivery.

### Acceptance Criteria

**AC1 — Synthesized dispute summary display (happy):** **Given** a driver has completed or is conducting an async chat with the Driver Agent, **when** the analyst opens the case in the Cockpit, **then** the Cockpit chatbox displays a synthesized dispute brief (driver claims, verified facts, discrepancy score, recommended actions) alongside raw transcripts.

**AC2 — Analyst prompt delegation to Driver Agent (edge):** **Given** the analyst needs additional clarification from the driver, **when** the analyst enters an instruction in the Cockpit chatbox (e.g., "Ask the driver why they turned off GPS at 14:22"), **then** the system dispatches an asynchronous follow-up task to the Driver Agent to notify the driver.

**AC3 — Zero automated adverse sanction (negative):** **Given** the Driver Agent determines a driver explanation is unconvincing or false, **when** the analysis completes, **then** the system strictly prohibits automated punitive actions (`NFR-L06-02`) and requires explicit human analyst approval to apply any sanction.

### INVEST Self-Check

| Criterion | Status | Note |
|---|---|---|
| Independent | ✅ | Analyst collaboration workflow |
| Negotiable | ✅ | Synthesis format and delegation syntax open |
| Valuable | ✅ | Eliminates manual phone outreach toil |
| Estimable | ✅ | Extension of case agent session stream |
| Small | ✅ | Cockpit integration slice |
| Testable | ✅ | 3 GWT paths covering synthesis, delegation, guardrails |

**Notes:** Historical traceability: PP-05, FR-L06-20. Strict HITL guardrails are required; runtime conformance is not established here.

## Coverage Summary

| Story | Happy | Edge | Negative | Principal coverage |
|---|---:|---:|---:|---|
| US-L06-01 | 1 | 1 | 1 | Prompt/no-response/deduplication |
| US-L06-02 | 1 | 1 | 1 | Preserved reassignment |
| US-L06-03 | 1 | 1 | 1 | Evidence safety/deadline |
| US-L06-04 | 1 | 1 | 1 | Analyst permissions/outcomes |
| US-L06-05 | 1 | 1 | 1 | Appeals/blinding/audit |
| US-L06-06 | 1 | 1 | 1 | Refund/voucher/reconciliation |
| US-L06-07 | 1 | 1 | 1 | Weekly review/contact governance |
| US-L06-08 | 1 | 1 | 1 | Rollout/rollback |
| US-L06-09 | 1 | 1 | 1 | Async driver dispute intake & tool verification |
| US-L06-10 | 1 | 1 | 1 | Analyst-agent synthesis & cockpit delegation |

All ten stories pass INVEST at specification level. Open policy values are explicit Notes, not assumed acceptance thresholds.

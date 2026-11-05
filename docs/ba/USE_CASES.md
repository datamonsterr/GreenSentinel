# L06 Use Cases — Release 1 HITL Enforcement

## Scope
 
The approved Phase 1 boundary is **initial analyst adjudication (`UC-L06-04`)**, adopted by @datamonsterr on 2026-09-30 in the [PRD](PRD.md#1-document-control). Other L06 use cases describe deferred live intervention, recovery, driver evidence, appeals, and governance. Each UC has one primary actor and one session-level goal. Values marked TBD require stakeholder approval; CV-01 baseline and operator UAT remain pending.

All dismissals and analyst Agree/Disagree outcomes require authorized analyst confirmation plus written rationale; the system never applies warnings, fines, clawbacks, or suspensions; algorithmic closure is deny-by-default. These are specifications, not runtime-conformance evidence.

> [!IMPORTANT]
> **Implementation Phasing Notice:**
> - **Target Release 1 Vision (L06):** Use cases `UC-L06-01` through `UC-L06-07` specify the full 8-epic lifecycle architecture for platform-wide enforcement.
> - **Phase 1 MVP Scope:** **Epic 5: Initial Adjudication ([`UC-L06-04`](#uc-l06-04-adjudicate-initial-case-phase-1-mvp-golden-path))** and the **GreenSentinel Workplace (Fraud Analyst Adjudication Cockpit)**, as detailed in [`MVP.md`](MVP.md). All other use cases, including `UC-L06-08/09` driver expansion, are deferred to Phase 2+. Existing implementation or event generators do not add them to release acceptance.

## UC-L06-01: Choose Passenger Recovery

| Field | Specification |
|---|---|
| **Use Case ID** | `UC-L06-01` |
| **Use Case Name** | Choose Passenger Recovery |
| **Created By / Date** | P-063 BA documentation / 2026-09-17 |
| **Last Updated By / Date** | P-063 BA documentation / 2026-09-17 |
| **Actor** | **Primary:** Passenger with an active pickup. **Secondary:** Notification channel. |
| **Description** | Because an approved real-time score enters the prompt band, the Passenger reviews cautious suspected-DIC information and chooses recovery or continuation. The use case ends with exactly one immutable Passenger choice and no fraud confirmation. |
| **Preconditions** | 1. Trip is active and assigned.<br>2. Approved pre-score policy/version enters the prompt band.<br>3. No terminal Passenger choice or prior prompt exists for the trip. |
| **Postconditions** | 1. Choice is `Reassign`, `Continue`, or `No response`.<br>2. Reassign starts preserved recovery; other outcomes leave the original trip active.<br>3. Prompt/choice/version are audited once. |
| **Priority** | Deferred (Phase 2) — future vision priority: High; live Passenger safety and agency. |
| **Frequency of Use** | At most once per eligible trip; expected volume TBD from CV-01 and rollout scope. |
| **Normal Course of Events** | 1. Passenger receives the suspected-DIC prompt.<br>2. Guardrail displays approved explanation and choices.<br>3. Passenger selects **Reassign**.<br>4. Guardrail records the Passenger choice.<br>5. Guardrail requests preserved reassignment with Dispatch.<br>6. Upon dispatch acknowledgement, Guardrail closes the original assignment under approved policy.<br>7. Guardrail displays recovery status without declaring confirmed fraud. |
| **Alternative Courses** | **UC-L06-01.AC.1: Continue original trip** — At step 3, when Passenger selects **Continue**: 3a. Guardrail records `Continue`; 3b. Guardrail leaves the assignment active; continue from step 7.<br><br>**UC-L06-01.AC.2: No response** — At step 3, when no action is received by the approved prompt expiry: 3a. Guardrail records `No response`; 3b. Guardrail leaves the assignment active; continue from step 7. |
| **Exceptions** | **UC-L06-01.EX.1: Stale trip** — Trigger: at step 4 the trip is no longer eligible. Response: reject choice and show current trip state. Final: no recovery action.<br>**UC-L06-01.EX.2: Duplicate action** — Trigger: a choice already exists. Response: return recorded outcome and audit duplicate. Final: one choice only.<br>**UC-L06-01.EX.3: Delivery/network failure** — Trigger: prompt/choice cannot be confirmed. Response: do not infer consent; expose retry/current state. Final: original trip remains unless a confirmed choice exists.<br>**UC-L06-01.EX.4: Permission/session mismatch** — Trigger: actor is not the trip Passenger. Response: deny and audit. Final: trip unchanged.<br>**UC-L06-01.EX.5: Reassignment dispatch unavailable** — Trigger: at step 5 Dispatch cannot accept or queue the reassignment intent. Response: retain original assignment active, notify Passenger of temporary dispatch unavailability, and display option to retry or remain with original driver. Final: original assignment remains active. |
| **Includes** | None. |
| **Special Requirements** | Accessibility and approved language; idempotent choice; no post-event input in pre-score; no confirmed-fraud terminology; prompt performance target TBD. |
| **Assumptions** | 1. G4 prompt safety is approved.<br>2. Notification identity maps to the Passenger.<br>3. Exact copy/window are unvalidated. |
| **Notes and Issues** | TBD-L06-01: Approve bands, error tolerance, copy, expiry, accessibility, and delivery failure rule. Owners: Product Owner + Legal/Policy + Data/BI. Traceability: CV-06/08/11/20; FR-L06-01–04. |

## UC-L06-02: Receive Preserved Reassignment

| Field | Specification |
|---|---|
| **Use Case ID** | `UC-L06-02` |
| **Use Case Name** | Receive Preserved Reassignment |
| **Created By / Date** | P-063 BA documentation / 2026-09-17 |
| **Last Updated By / Date** | P-063 BA documentation / 2026-09-17 |
| **Actor** | **Primary:** Passenger who selected recovery. **Secondary:** Dispatch, Pricing/Voucher, Payment services. |
| **Description** | After choosing recovery, the Passenger receives a replacement assignment without rebooking or losing original trip value. The use case ends in successful replacement or the approved failed-recovery state. |
| **Preconditions** | 1. UC-L06-01 ended with `Reassign`.<br>2. Original fare, voucher, pickup, and destination snapshots exist.<br>3. No replacement is active. |
| **Postconditions** | 1. Exactly one replacement preserves protected attributes, or recovery is terminally failed.<br>2. Passenger recovery is unaffected by later Driver evidence.<br>3. Dispatch/pricing/payment states are reconcilable. |
| **Priority** | Deferred (Phase 2) — future vision priority: High; completes promised Passenger recovery. |
| **Frequency of Use** | Once per accepted recovery; volume TBD from live prompt acceptance. |
| **Normal Course of Events** | 1. Passenger views recovery status.<br>2. Guardrail submits the preserved trip intent to Dispatch.<br>3. Dispatch returns an eligible replacement Driver.<br>4. Guardrail validates protected trip attributes.<br>5. Guardrail activates the replacement assignment.<br>6. Guardrail displays replacement details and preserved value.<br>7. Passenger continues with the replacement trip. |
| **Alternative Courses** | **UC-L06-02.AC.1: Search remains in progress** — At step 3, when Dispatch has not reached a terminal result: 3a. Guardrail displays search status; 3b. Passenger waits or uses approved support/cancel option; repeat from step 3 only within approved timeout.<br>**UC-L06-02.AC.2: No replacement available** — At step 3, when the approved no-driver condition is reached: 3a. Guardrail ends the search; 3b. Guardrail invokes the failed-recovery outcome specified in UC-L06-06; use case ends. |
| **Exceptions** | **UC-L06-02.EX.1: Attribute mismatch** — Trigger: step 4 detects a changed protected attribute. Response: reject activation and open reconciliation. Final: no mismatched replacement.<br>**UC-L06-02.EX.2: Concurrent replacement** — Trigger: another replacement activates first. Response: retain the first valid assignment and cancel duplicate request. Final: one active replacement.<br>**UC-L06-02.EX.3: Dispatch outage** — Trigger: Dispatch is unavailable. Response: expose unresolved recovery and approved support route. Final: no false replacement.<br>**UC-L06-02.EX.4: Unauthorized modification** — Trigger: protected attributes are edited without authority. Response: deny and audit. Final: snapshot unchanged. |
| **Includes** | UC-L06-06: Complete Failed Recovery (only for AC.2). |
| **Special Requirements** | Idempotent dispatch and reconciliation; protected pricing integrity; accessible status; availability/timeout targets TBD. |
| **Assumptions** | 1. Dispatch can accept preserved attributes.<br>2. Payment/voucher systems expose reconciliation states.<br>3. Timeout value is unapproved. |
| **Notes and Issues** | TBD-L06-02: Approve timeout, support choice, and cross-service reconciliation owner. Owners: Product Owner + Dispatch + Customer Operations. Traceability: CV-14/15; FR-L06-05/06. |

## UC-L06-03: Submit Driver Evidence

| Field | Specification |
|---|---|
| **Use Case ID** | `UC-L06-03` |
| **Use Case Name** | Submit Driver Evidence |
| **Created By / Date** | P-063 BA documentation / 2026-09-17 |
| **Last Updated By / Date** | P-063 BA documentation / 2026-09-17 |
| **Actor** | **Primary:** Driver notified after the approved Passenger event. **Secondary:** Evidence scanning/storage service. |
| **Description** | The Driver submits a reason and permitted evidence so legitimate conditions can be reviewed. The use case ends with an accepted, late, absent, rejected, or quarantined submission state without changing Passenger recovery. |
| **Preconditions** | 1. A deduplicated suspected-DIC case exists.<br>2. Approved notice event occurred.<br>3. Driver identity matches the assignment.<br>4. Submission state is open or late submissions are permitted. |
| **Postconditions** | 1. Submission status, timing, provenance and policy version are recorded.<br>2. Accepted evidence is available to authorized review.<br>3. Passenger recovery is unchanged. |
| **Priority** | Deferred (Phase 2) — future vision priority: High; procedural fairness and evidence safety. |
| **Frequency of Use** | At most one active submission set per case plus policy-approved amendments; volume TBD. |
| **Normal Course of Events** | 1. Driver opens the case notice while safely stopped.<br>2. Guardrail displays signal reason, deadline, allowed evidence, safe-capture rule, and late/no-report effect.<br>3. Driver enters a written reason.<br>4. Guardrail displays whether the selected claim requires permitted video.<br>5. Driver attaches permitted evidence.<br>6. Driver submits the report.<br>7. Guardrail validates timing, type, completeness, safety attestation, and provenance.<br>8. Guardrail records the accepted submission and receipt. |
| **Alternative Courses** | **UC-L06-03.AC.1: Written reason only** — At step 5, when the approved claim does not require video: 5a. Driver proceeds without attachment; continue from step 6.<br>**UC-L06-03.AC.2: Policy permits late evidence** — At step 7, when the deadline passed but late evidence remains admissible: 7a. Guardrail marks it `Late`; 7b. Guardrail records the approved evidentiary effect; continue from step 8. |
| **Exceptions** | **UC-L06-03.EX.1: Unsafe capture indication** — Trigger: submission indicates recording while moving. Response: reject/quarantine and show safety rule. Final: unsafe evidence unavailable for decision per policy.<br>**UC-L06-03.EX.2: Invalid/malicious file** — Trigger: validation/scanning fails. Response: quarantine and disclose status. Final: case retains other evidence.<br>**UC-L06-03.EX.3: Upload/network failure** — Trigger: evidence cannot be confirmed. Response: preserve confirmed text/draft only under approved rule and show retry. Final: no falsely accepted file.<br>**UC-L06-03.EX.4: Permission denied** — Trigger: non-assigned Driver accesses case. Response: deny and audit. Final: case unchanged. |
| **Includes** | None. |
| **Special Requirements** | No moving-vehicle recording; encryption, minimization, malware scanning, purpose-bound access, approved retention/deletion, accessible instructions. |
| **Assumptions** | 1. Evidence infrastructure supports approved formats.<br>2. Authentication and safe-capture controls can be tested.<br>3. Values are pending CV-05/CV-09. |
| **Notes and Issues** | TBD-L06-03: Approve deadline, late rule, formats/content/size, authenticity, retention, access and deletion. Owners: Driver Operations + Privacy/Legal + Security. Traceability: FR-L06-07–09. |

## UC-L06-04: Adjudicate Initial Case (Phase 1 MVP Golden Path)

| Field | Specification |
|---|---|
| **Use Case ID** | `UC-L06-04` |
| **Use Case Name** | Adjudicate Initial Case |
| **Created By / Date** | P-063 BA documentation / 2026-09-17 |
| **Last Updated By / Date** | P-063 BA documentation / 2026-09-28 |
| **Actor** | **Primary:** Fraud Analyst (Initial Reviewer). **Secondary:** Audit Subsystem. |
| **Description** | The Fraud Analyst inspects prioritized suspected-DIC cases, views the unified spatial GIS trajectory alongside legal shortest routes, checks the system error guardrail for technical outages, and signs off on an authorized outcome with mandatory rationale. |
| **Preconditions** | 1. Case is ingested and in status `Ready for review`.<br>2. Analyst possesses authenticated role (`Fraud Analyst`).<br>3. No conflicting active review lock exists (or previous lock has expired). |
| **Postconditions** | 1. Exactly one analyst outcome is recorded: `Agree` (confirms predicted violation), `Disagree` (dismisses prediction as false alarm), or `Request More Evidence`.<br>2. Case status transitions to `Closed` (for `Agree`/`Disagree`) or `Evidence Requested`.<br>3. An immutable audit record is appended binding case ID, analyst ID, decision, rationale, and evidence snapshot.<br>4. All dismissals and analyst Agree/Disagree outcomes require authorized analyst confirmation plus written rationale ($\ge 10$ characters); no warning, fine, clawback, suspension, termination, or escalation outcome exists. |
| **Priority** | High (Must — Core Phase 1 MVP deliverable). |
| **Frequency of Use** | Continuous throughout analyst shift (Target MTTR: < 45 seconds per case). |
| **Normal Course of Events** | 1. Fraud Analyst claims a case from the Priority Triage Queue.<br>2. Guardrail acquires a 300-second concurrency lease and renders the case dossier (GPS breadcrumbs vs planned route, stall pins, speed metrics, and evidence summary).<br>3. Guardrail scans technical telemetry logs; confirms zero app crashes or 4G network dropouts.<br>4. Guardrail displays authorized outcome actions (`Agree`, `Disagree`, `Request More Evidence`).<br>5. Analyst inspects spatial evidence and selects an authorized outcome (e.g. `Agree`).<br>6. Analyst enters mandatory operational rationale ($\ge 10$ characters).<br>7. Analyst clicks "Submit Adjudication".<br>8. Guardrail persists the append-only audit trail and marks case status as `Closed`.<br>9. Guardrail releases the review lease and removes the case from active triage within 1.5s. |
| **Alternative Courses** | **UC-L06-04.AC.1: System Error Guardrail Advisory Signal** — At step 3, when a driver app crash or 4G loss (> 30s) is detected: 3a. Guardrail displays warning banner: `"⚠️ System Error Detected: Driver App Disconnect"`; 3b. Guardrail marks suggested outcome as `Disagree (System Error)`; the signal is advisory only and must not block or apply any outcome; 3c. Authorized analyst reviews technical diagnostics, confirms `Disagree` (or another outcome) with written rationale ($\ge 10$ characters), and submits; case closes with recorded outcome.<br><br>**UC-L06-04.AC.2: Request More Evidence** — At step 5, when critical documentation is missing: 5a. Analyst selects `Request Evidence`; 5b. Guardrail records the analyst evidence request; new driver mobile intake is deferred; 5c. Case status transitions to `Evidence Requested`; use case ends. |
| **Exceptions** | **UC-L06-04.EX.1: Concurrent Review Lockout** — Trigger: case is actively locked by another analyst. Response: render dossier in read-only mode with lock banner and countdown timer. Final: no duplicate simultaneous reviews.<br><br>**UC-L06-04.EX.2: Lease Expiry / Inactivity Timeout** — Trigger: analyst takes $> 300$ seconds without submission. Response: automatically release review lease and return case to active queue. Final: unblocked queue.<br><br>**UC-L06-04.EX.3: Missing / Inadequate Rationale** — Trigger: analyst attempts submission of `Agree` or `Disagree` with fewer than 10 non-whitespace characters. Response: block submission and render validation error. Final: outcome not submitted without required rationale.<br><br>**UC-L06-04.EX.4: Unauthorized Adjudication Attempt** — Trigger: user without authorized Fraud Analyst role attempts outcome submission. Response: disable control and reject API submission with HTTP 403 Forbidden. Final: strict RBAC enforcement. |
| **Includes** | None. |
| **Special Requirements** | 100% authorized analyst confirmation and written rationale for all dismissals and analyst Agree/Disagree outcomes; the system never applies warnings, fines, clawbacks, or suspensions; initial dossier render $\le 1.5$ seconds; MTTR target $< 45$ seconds; append-only audit trail immutability; PII masking by default. |
| **Assumptions** | 1. Telemetry points and planned route geometries are available in the ingestion store.<br>2. Operational baseline alert volume and backlog are hypotheses pending CV-01 verification. |
| **Notes and Issues** | Traceability: `FR-01`–`FR-05`, `NFR-01`–`NFR-04`, `DEC-L06-15`–`17`. Phase 1 MVP core deliverable; [AC-P1-01–09](PRD.md#101-phase-1-acceptance-and-test-traceability) define acceptance/test traceability. |

## UC-L06-05: Appeal Enforcement Decision

| Field | Specification |
|---|---|
| **Use Case ID** | `UC-L06-05` |
| **Use Case Name** | Appeal Enforcement Decision |
| **Created By / Date** | P-063 BA documentation / 2026-09-17 |
| **Last Updated By / Date** | P-063 BA documentation / 2026-09-17 |
| **Actor** | **Primary:** Driver with an eligible adverse decision. **Secondary:** Different second-review Fraud Analyst, sanction/account services. |
| **Description** | The Driver requests a blinded second review to correct a potentially wrong fine or suspension. The use case ends with an upheld or overturned outcome, reconciled enforcement, and preserved internal audit linkage. Phase 1 applies no fine, suspension, or other sanction; this use case is retained only as deferred reference. |
| **Preconditions** | 1. Eligible adverse initial decision exists.<br>2. Appeal is within approved policy.<br>3. No terminal second review exists.<br>4. A different authorized analyst is available or queueable. |
| **Postconditions** | 1. Second decision is linked internally to the first.<br>2. Fine/suspension was paused while pending.<br>3. Uphold resumes approved state; overturn reverses fine/restores account and queues weekly conflict.<br>4. Driver is notified; compensation status follows approved policy. |
| **Priority** | Deferred (Phase 3) — future vision priority: High; procedural fairness and correction. |
| **Frequency of Use** | At most one standard second review per eligible initial decision unless policy approves another route; volume TBD. |
| **Normal Course of Events** | 1. Driver opens the eligible decision.<br>2. Guardrail displays appeal scope, submission rule, and unresolved/approved SLA.<br>3. Driver submits the review request and permitted additional material.<br>4. Guardrail pauses the fine/suspension.<br>5. Guardrail assigns a different Fraud Analyst.<br>6. Guardrail displays raw authorized evidence without appeal label, original decision, or rationale.<br>7. Second-review Fraud Analyst reviews the evidence.<br>8. Second-review Fraud Analyst records an independent outcome and rationale.<br>9. Guardrail validates separation, authority, and completeness.<br>10. Guardrail applies uphold or overturn reconciliation.<br>11. Guardrail notifies the Driver and records audit linkage. |
| **Alternative Courses** | **UC-L06-05.AC.1: Uphold** — At step 10, when the second decision upholds: 10a. Guardrail resumes the approved sanction state; continue from step 11.<br>**UC-L06-05.AC.2: Overturn** — At step 10, when the decision overturns: 10a. Guardrail reverses fine; 10b. Guardrail restores account; 10c. Guardrail queues weekly conflict and approved compensation assessment; continue from step 11. |
| **Exceptions** | **UC-L06-05.EX.1: Same-reviewer assignment** — Trigger: step 5 selects original analyst. Response: reject assignment and requeue. Final: sanction remains paused.<br>**UC-L06-05.EX.2: Blinding breach** — Trigger: step 6 exposes prohibited field. Response: block review, record incident, reassign after correction. Final: no second decision.<br>**UC-L06-05.EX.3: Reconciliation failure** — Trigger: step 10 cannot confirm reversal/restoration. Response: show pending correction and create reconciliation incident. Final: no false completed state.<br>**UC-L06-05.EX.4: Ineligible/duplicate request** — Trigger: policy check fails. Response: deny with reason and approved escalation route. Final: existing decision state remains. |
| **Includes** | None. |
| **Special Requirements** | Separation of duties; field-level blinding; immutable hidden linkage; idempotent sanction pause/reversal/restoration; SLA TBD. |
| **Assumptions** | 1. Appeals and pause rule are approved.<br>2. Exact visible fields and compensation remain unresolved.<br>3. Reviewer capacity exists. |
| **Notes and Issues** | TBD-L06-05: Approve SLA, field list, final authority, notification and lost-income compensation. Owners: Driver Operations + Fraud Operations + Legal/Policy. Traceability: CV-13/16; FR-L06-13–15. |

## UC-L06-06: Complete Failed Recovery

| Field | Specification |
|---|---|
| **Use Case ID** | `UC-L06-06` |
| **Use Case Name** | Complete Failed Recovery |
| **Created By / Date** | P-063 BA documentation / 2026-09-17 |
| **Last Updated By / Date** | P-063 BA documentation / 2026-09-17 |
| **Actor** | **Primary:** Passenger whose replacement search reached the approved no-driver state. **Secondary:** Payment, Voucher, Customer Support services. |
| **Description** | The Passenger receives a mandatory refund and the approved voucher/support outcome when reassignment fails. The use case ends only when the recovery result is truthful and reconcilable. |
| **Preconditions** | 1. Accepted recovery has no replacement at the approved timeout/state.<br>2. Original payment/voucher snapshot exists.<br>3. No completed recovery refund exists. |
| **Postconditions** | 1. Mandatory refund is confirmed or explicitly pending reconciliation.<br>2. Voucher outcome matches approved policy.<br>3. Passenger sees accurate terminal/pending status.<br>4. Duplicate financial action is prevented. |
| **Priority** | Deferred (Phase 2) — future vision priority: High; prevents financial and service-recovery harm. |
| **Frequency of Use** | Once per failed reassignment; volume TBD from rollout. |
| **Normal Course of Events** | 1. Passenger views the failed replacement status.<br>2. Guardrail displays approved refund and voucher outcome.<br>3. Passenger confirms the recovery acknowledgement where policy requires it.<br>4. Guardrail requests the mandatory refund.<br>5. Payment service confirms the refund state.<br>6. Guardrail applies the approved voucher outcome.<br>7. Guardrail records a reconciled failed-recovery state.<br>8. Guardrail displays completion and approved support route. |
| **Alternative Courses** | **UC-L06-06.AC.1: No acknowledgement required** — At step 3, when policy makes recovery automatic: 3a. Guardrail records automatic initiation; continue from step 4.<br>**UC-L06-06.AC.2: Manual support required** — At step 6, when voucher/payment type requires support: 6a. Guardrail creates a support item with snapshot; 6b. Guardrail displays pending status; continue from step 7 with state `Pending support`. |
| **Exceptions** | **UC-L06-06.EX.1: Payment timeout** — Trigger: step 5 lacks confirmation. Response: retain pending state and queue idempotent reconciliation. Final: no false refund completion.<br>**UC-L06-06.EX.2: Voucher conflict** — Trigger: step 6 conflicts with voucher state. Response: stop voucher mutation and queue support. Final: original snapshot retained.<br>**UC-L06-06.EX.3: Duplicate request** — Trigger: refund already exists. Response: return existing status and audit retry. Final: no duplicate refund.<br>**UC-L06-06.EX.4: Permission mismatch** — Trigger: non-Passenger accesses result. Response: deny and audit. Final: recovery unchanged. |
| **Includes** | None. |
| **Special Requirements** | Financial idempotency, reconciliation audit, privacy, accessible status, timeout/support targets TBD. |
| **Assumptions** | 1. Refund is mandatory.<br>2. Voucher rule and timeout remain unapproved.<br>3. Payment service exposes authoritative state. |
| **Notes and Issues** | TBD-L06-06: Approve timeout, voucher matrix, notification, support trigger and reconciliation SLA. Owners: Product Owner + Customer Operations + Dispatch. Traceability: CV-14/15; FR-L06-06. |

## UC-L06-07: Govern Release Phase

| Field | Specification |
|---|---|
| **Use Case ID** | `UC-L06-07` |
| **Use Case Name** | Govern Release Phase |
| **Created By / Date** | P-063 BA documentation / 2026-09-17 |
| **Last Updated By / Date** | P-063 BA documentation / 2026-09-17 |
| **Actor** | **Primary:** Product Owner accountable for Release 1. **Secondary:** Fraud, Driver, Customer, Dispatch Operations; Security, Data/BI. |
| **Description** | The Product Owner reviews a versioned gate packet and enables, pauses, rolls back, or holds one bounded Release 1 phase. The use case ends with an auditable boundary and never reduces human approval for fines/suspensions. |
| **Preconditions** | 1. G1–G4 evidence and phase configuration are versioned.<br>2. Required operational/control tests and capacity evidence exist.<br>3. Actor has release authority.<br>4. No unresolved stop incident permits enablement. |
| **Postconditions** | 1. Exactly one phase decision and boundary are recorded.<br>2. Enabled actions match approved segment/version.<br>3. Rollback preserves accepted recovery/audit and blocks restart pending approval.<br>4. Human sanction approval remains mandatory. |
| **Priority** | Deferred (Phase 3) — future vision priority: High; bounds live operational risk. |
| **Frequency of Use** | One decision per phase/configuration version and one event per rollback/restart request. |
| **Normal Course of Events** | 1. Product Owner selects the phase packet.<br>2. Guardrail displays gate evidence, policy versions, tests, metrics, capacity, risks, and rollback controls.<br>3. Product Owner reviews the permitted phase decisions.<br>4. Guardrail displays exact action/segment boundary and human-control invariant.<br>5. Product Owner selects **Enable bounded phase**.<br>6. Product Owner records rationale and required acknowledgements.<br>7. Guardrail validates approvals and evidence freshness.<br>8. Guardrail records and activates only the approved boundary.<br>9. Guardrail displays monitoring and rollback ownership. |
| **Alternative Courses** | **UC-L06-07.AC.1: Hold** — At step 5, when evidence is insufficient without active harm: 5a. Product Owner selects `Hold`; 5b. Guardrail records gaps/owners; continue from step 6 without activation.<br>**UC-L06-07.AC.2: Roll back** — At step 5, when an approved trigger or incident exists: 5a. Product Owner/authorized owner selects `Rollback`; 5b. Guardrail disables affected action and preserves accepted recovery/audit; 5c. Guardrail blocks restart; continue from step 6.<br>**UC-L06-07.AC.3: Remain L06** — At step 5, when G5 fails/unassessed: 5a. Product Owner records `Remain L06`; 5b. Guardrail verifies analyst approval remains mandatory; continue from step 6. |
| **Exceptions** | **UC-L06-07.EX.1: Missing/expired evidence** — Trigger: step 7 fails validation. Response: deny enablement and list gaps. Final: safe boundary remains.<br>**UC-L06-07.EX.2: Unauthorized expansion** — Trigger: requested segment/action exceeds approval. Response: deny and audit. Final: boundary unchanged.<br>**UC-L06-07.EX.3: Activation mismatch** — Trigger: actual configuration differs after step 8. Response: enter safe state, record incident and block restart. Final: affected action disabled.<br>**UC-L06-07.EX.4: Invalid upstream gate** — Trigger: G1–G4 evidence is withdrawn. Response: restrict outcome to rollback/stop and route to earliest leaf. Final: no L06 expansion. |
| **Includes** | None. |
| **Special Requirements** | Immutable approvals; configuration/version binding; rapid safe-state objective TBD; least privilege; complete incident/audit retention. |
| **Assumptions** | 1. Named owners can disable integrations.<br>2. Entry/rollback numbers are approved before use.<br>3. G5 is not passed. |
| **Notes and Issues** | TBD-L06-07: Approve phase sequence, sample/window, capacity, thresholds, stop triggers, safe-state objective, rollback/restart authorities. Owner: Product Owner. Traceability: CV-01–04/10/17; FR-L06-16–18. |

## UC-L06-08: Conduct Async Driver Disputation via Driver Agent

| Field | Specification |
|---|---|
| **Use Case ID** | `UC-L06-08` |
| **Use Case Name** | Conduct Async Driver Disputation via Driver Agent |
| **Created By / Date** | P-063 BA documentation / 2026-09-26 |
| **Last Updated By / Date** | P-063 BA documentation / 2026-09-26 |
| **Actor** | **Primary:** Driver notified of suspected fraud. **Secondary:** AI Driver Agent, Telemetry & Traffic Services, Case Service. |
| **Description** | A driver notified of a fraud alert disputes the finding via an asynchronous conversational session with the AI Driver Agent. The agent validates driver identity, conducts structured question-and-answer, triggers deterministic verification tools to corroborate factual claims, and compiles an evidence dossier for analyst review without imposing autonomous sanctions. |
| **Preconditions** | 1. A suspected fraud case exists in `driver_notified` or `in_review` status.<br>2. Driver is authenticated with `role: driver` in `app.principal_roles` matching `driver_id`.<br>3. Dispute window has not expired. |
| **Postconditions** | 1. Driver statements, timestamps, and attached evidence are recorded in the case session.<br>2. Tool verification corroboration score and discrepancies are computed.<br>3. Case transitions to `driver_disputed` with synthesized brief available to Fraud Analyst.<br>4. Zero automated sanction is applied (`NFR-L06-02`). |
| **Priority** | Deferred (Phase 2+) — reference to existing implementation in [MERGED PR #40](https://github.com/AI20K-Build-Phase-Cohort-4/P-063/pull/40), not Phase 1 acceptance. |
| **Frequency of Use** | Once per contested fraud notification; expected volume proportional to driver dispute rate. |
| **Normal Course of Events** | 1. Driver opens fraud notification and selects **Dispute Violation**.<br>2. System validates driver credentials against database `driver` role.<br>3. Driver Agent initiates session, disclosing suspected violation details and policy context.<br>4. Driver provides written explanation and context.<br>5. Driver Agent queries shared verification tools (telemetry, route history, traffic check).<br>6. Driver Agent prompts driver for targeted clarification or permitted media evidence based on similar case procedures.<br>7. Driver completes evidence submission.<br>8. Driver Agent acknowledges receipt, informs driver of async review SLA, and compiles structured dossier.<br>9. Driver Agent transitions case to `driver_disputed` and alerts Analyst Cockpit. |
| **Alternative Courses** | **UC-L06-08.AC.1: Driver accepts violation** — At step 4, when Driver confirms violation: 4a. Agent records admission; 4b. Case routes directly to analyst expedited resolution.<br>**UC-L06-08.AC.2: Driver requests human agent** — At step 4, when Driver insists on human contact: 4a. Agent records request and escalates priority; continue from step 8. |
| **Exceptions** | **UC-L06-08.EX.1: Unauthorized principal** — Trigger: step 2 detects non-driver role or driver ID mismatch. Response: return 403 Forbidden and audit security breach. Final: case remains unchanged.<br>**UC-L06-08.EX.2: Prompt injection / manipulation attempt** — Trigger: agent guardrails detect adversarial instructions to dismiss violation. Response: trap prompt, flag adversarial tag, and freeze automated intake. Final: case escalated to Senior Analyst.<br>**UC-L06-08.EX.3: Tool verification failure** — Trigger: step 5 telemetry or routing service unavailable. Response: mark evidence gap as `UNAVAILABLE` without penalizing driver. Final: manual analyst review required.<br>**UC-L06-08.EX.4: Expired dispute window** — Trigger: driver attempts dispute after deadline. Response: record late statement with `LATE` flag per policy. Final: analyst determines admissibility. |
| **Includes** | None. |
| **Special Requirements** | Mobile-responsive async chat; deterministic telemetry verification; PII masking; zero hallucinated policy commitments; tamper-evident audit logging. |
| **Assumptions** | 1. PostgreSQL schema supports authenticated `driver` role.<br>2. Driver app or web portal provides secure session token.<br>3. Dispute SLA target is approved. |
| **Notes and Issues** | TBD-L06-08: Approve dispute window duration, tool query quotas, prompt injection evaluation benchmark. Owners: Fraud Operations + Driver Operations + Security. Traceability: PP-05; FR-L06-19. |

## UC-L06-09: Collaborate with Driver Agent in Analyst Cockpit

| Field | Specification |
|---|---|
| **Use Case ID** | `UC-L06-09` |
| **Use Case Name** | Collaborate with Driver Agent in Analyst Cockpit |
| **Created By / Date** | P-063 BA documentation / 2026-09-26 |
| **Last Updated By / Date** | P-063 BA documentation / 2026-09-26 |
| **Actor** | **Primary:** Fraud Analyst holding active case lease. **Secondary:** Sentinel Copilot, AI Driver Agent, Case Service. |
| **Description** | The Fraud Analyst reviews the synthesized dispute summary generated by the Driver Agent within the unified Cockpit chatbox. The analyst can cross-examine findings, instruct the Driver Agent to ask specific follow-up questions, or request manual driver actions before finalizing adjudication. |
| **Preconditions** | 1. Case has active or completed Driver Agent interaction (`driver_disputed`).<br>2. Fraud Analyst holds valid review lease.<br>3. Case evidence snapshot is current. |
| **Postconditions** | 1. Driver Agent synthesis, discrepancy score, and transcript are rendered in cockpit.<br>2. Delegated follow-up prompts are asynchronously dispatched to Driver Agent.<br>3. Case remains open until explicit human adjudication (`AGREE`, `DISAGREE`, `REQUEST_EVIDENCE`). |
| **Priority** | Deferred (Phase 2+) — reference to existing implementation in [MERGED PR #40](https://github.com/AI20K-Build-Phase-Cohort-4/P-063/pull/40), not Phase 1 acceptance. |
| **Frequency of Use** | Repeated turns during active case investigation. |
| **Normal Course of Events** | 1. Fraud Analyst opens claimed case in Cockpit.<br>2. Cockpit chatbox displays Driver Agent synthesis badge: driver explanation summary, tool corroboration status, discrepancy score, and recommended next steps.<br>3. Analyst queries Copilot in the chatbox regarding driver claims or policy clauses.<br>4. Copilot returns policy citations and corroborating telemetry timestamps.<br>5. Analyst enters delegation instruction (e.g. "Ask driver to explain 5-minute stationary gap at Point B").<br>6. Cockpit dispatches asynchronous task to Driver Agent and displays delivery receipt.<br>7. Analyst proceeds with adjudication or leaves case in `evidence_requested` pending driver reply. |
| **Alternative Courses** | **UC-L06-09.AC.1: Direct transcript inspection** — At step 2, analyst expands full verbatim driver-agent chat transcript for forensic verification.<br>**UC-L06-09.AC.2: Autonomous recommendation override** — At step 7, analyst disagrees with Driver Agent recommendation and records human override rationale. |
| **Exceptions** | **UC-L06-09.EX.1: Lease expiration during interaction** — Trigger: analyst lease expires during active chat. Response: disable send controls and require re-claiming lease. Final: no orphaned commands.<br>**UC-L06-09.EX.2: Concurrent driver reply** — Trigger: driver replies while analyst drafts delegation. Response: update chat stream via SSE and notify analyst of fresh input. Final: version-incremented state.<br>**UC-L06-09.EX.3: Unauthorized delegation command** — Trigger: analyst attempts punitive action without formal adjudication payload. Response: block command and guide to standard adjudication send bar. Final: `NFR-L06-02` preserved. |
| **Includes** | UC-L06-04: Adjudicate Initial Case. |
| **Special Requirements** | Unified SSE streaming; compact badge display; sub-second query latency; persistent cross-session history. |
| **Assumptions** | 1. Cockpit chatbox can handle multi-agent message tagging (analyst, copilot, driver_agent, driver).<br>2. Analyst lease ownership checks are strictly enforced. |
| **Notes and Issues** | TBD-L06-09: Approve delegation message templates and analyst takeover protocols. Owners: Fraud Operations + Frontend UI. Traceability: PP-05; FR-L06-20. |

## 20-Point Validation Summary

Legend: ✅ pass; ⚠️ value deliberately pending stakeholder approval.

| # | Validation item | 01 | 02 | 03 | 04 | 05 | 06 | 07 | 08 | 09 | Note |
|---|---|---|---|---|---|---|---|---|---|---|---|
| C1 | Verb + object name | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | Active names. |
| C2 | User-goal level | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | Each ends in a business result. |
| C3 | Unique `UC-L06-NN` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | No duplicates. |
| C4 | One primary actor/goal | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | Secondary actors support only. |
| C5 | Clear boundary | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | L06 Guardrail. |
| C6 | Specific actor | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | No generic User. |
| C7 | Why + what + outcome | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | Present in descriptions. |
| C8 | Quantified frequency | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | Per trip/case/phase; volumes marked TBD. |
| C9 | Verifiable preconditions | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | State/version/identity checks. |
| C10 | Complete success state | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | Data, actor, and audit states. |
| C11 | Assumptions separated | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | Unverified beliefs isolated. |
| C12 | Numbered one-action steps | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | Sequential courses. |
| C13 | Explicit subjects | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | Actor/service/Guardrail named. |
| C14 | No embedded branch | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | Branches are alternatives/exceptions. |
| C15 | Trigger to postcondition | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | Complete flows. |
| C16 | Alternatives anchored | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | Step, condition, continuation/end stated. |
| C17 | Exceptions complete | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | Trigger, response, final state. |
| C18 | Relevant failures | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | Network, permission, concurrency, validation, integrations covered. |
| C19 | Includes valid | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | UC-L06-02 points to UC-L06-06; UC-L06-09 includes UC-L06-04. |
| C20 | Special requirements NFR-only | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | Safety/security/privacy/reliability only. |

**Validation result:** 20/20 specification checks pass for all nine use cases. Open values remain stakeholder TBDs and do not constitute policy approval.

Use-case structure and validation adapted from the BA Zone / Digital School Use Case Writer by Phúc NT.

---

## 3. Cockpit Multi-Tool & RAG Test Suite (100 Scenarios)

> **Traceability Note:** These 100 scenarios formally validate **UC-L06-04 (Fraud Analyst Adjudication Cockpit)**, verifying multi-tool coordination, GreenSM policy grounding, driver credential inspection, telemetry stall detection, and HITL outcome structuring.

### Overview Matrix

| Category # | Domain / Capability | Tool Tested | Display Format | Cases | Target Grounding |
|:---:|---|---|---|:---:|---|
| 1 | Driver Profile & Credentials | `get_driver_card` | `driver_card` | 10 | Mock Driver Repository (`MOCK_DRIVERS`) |
| 2 | Trip Telemetry & Stall Logs | `get_driver_trip_history` | `driver_history` | 10 | Driver Trip Histories (`MOCK_DRIVER_HISTORIES`) |
| 3 | General Terms & Contract Formation | `search_policy_documents` | `policy_answer` | 10 | `terms-of-use`, `procedures-for-users` |
| 4 | Car & Bike Transportation | `search_policy_documents` | `policy_answer` | 10 | `regulations-on-the-use-of-green-sm-car/bike` |
| 5 | Delivery & Express Services | `search_policy_documents` | `policy_answer` | 10 | `regulations-on-the-use-of-green-sm-delivery/express` |
| 6 | Food Delivery & Food Safety | `search_policy_documents` | `policy_answer` | 10 | `regulations-on-the-use-of-green-sm-food` |
| 7 | EV Rental & Operating Terms | `search_policy_documents` | `policy_answer` | 10 | `general-terms-applicable-to-vehicle-rental-services` |
| 8 | Online Promotions & Merchants | `search_policy_documents` | `policy_answer` | 10 | `terms-and-conditions-of-online-promotional-services` |
| 9 | Privacy Notice & Personal Data | `search_policy_documents` | `policy_answer` | 10 | `privacy-notice` (Decree 13/2023/ND-CP) |
| 10 | Forensic DIC Triage & Adjudication | Multi-Tool / Policy Search | `forensic_brief` | 10 | Unified Cockpit HITL Adjudication Engine |

### Category 1: Driver Profile & Credential Verification (get_driver_card)

| Test ID | Input Question / Trigger | Expected Tool | Expected Entity / Chunk ID | UI Format | Gold Verification & Acceptance Criteria |
|:---:|---|---|---|:---:|---|
| `TC-001` | Show me the driver profile card for Nguyen Van A (plate 29E-123.45). | `get_driver_card` | `drv-8492-nguyen-van-a` | `driver_card` | Driver Nguyễn Văn A (ID: drv-8492-nguyen-van-a), Vehicle: 29E-123.45 (Green SM Car - VF e34), Rating: 4.82, AR: 89.5%, CR: 91.0%, Status: ACTIVE. |
| `TC-002` | What is the operational status and rating of driver drv-3819-tran-dinh-trong? | `get_driver_card` | `drv-3819-tran-dinh-trong` | `driver_card` | Driver Trần Đình Trọng (ID: drv-3819-tran-dinh-trong) has status UNDER_INVESTIGATION, vehicle 30F-982.11 (VF 8), rating 4.65 ⭐, AR 78.0%, CR 82.5%. |
| `TC-003` | Look up driver credentials for vehicle license plate 29D-441.82. | `get_driver_card` | `drv-4418-pham-hoang-long` | `driver_card` | Driver Phạm Hoàng Long (ID: drv-4418-pham-hoang-long), Vehicle: 29D-441.82 (Green SM Bike - Feliz S), Rating: 4.95 ⭐, AR: 98.0%, CR: 99.1%, Status: ACTIVE. |
| `TC-004` | Retrieve driver card for Pham Hoang Long. | `get_driver_card` | `drv-4418-pham-hoang-long` | `driver_card` | Driver Phạm Hoàng Long operates Green SM Bike (Feliz S), plate 29D-441.82, with 3,100 completed trips and 4.95 rating. |
| `TC-005` | Display driver standing and completion rate for drv-5521-le-quang-minh. | `get_driver_card` | `drv-5521-le-quang-minh` | `driver_card` | Driver Lê Quang Minh (drv-5521-le-quang-minh), plate 51K-882.91 (VF 5 Plus), Rating: 4.71, Acceptance Rate: 84.0%, Completion Rate: 88.0%, Status: ACTIVE. |
| `TC-006` | Check driver card for Hoang Thuy Linh driving VF 9. | `get_driver_card` | `drv-9102-hoang-thuy-linh` | `driver_card` | Driver Hoàng Thùy Linh (drv-9102-hoang-thuy-linh), vehicle 29E-991.02 (VF 9), Rating 4.98 ⭐, AR 99.0%, CR 99.5%, Status: ACTIVE. |
| `TC-007` | Is driver Vu Duc Thanh currently active or suspended? | `get_driver_card` | `drv-6643-vu-duc-thanh` | `driver_card` | Driver Vũ Đức Thành (drv-6643-vu-duc-thanh) is currently SUSPENDED with rating 4.20, AR 65.0%, and CR 71.0%. |
| `TC-008` | Look up driver ID drv-6643-vu-duc-thanh and check their acceptance rate. | `get_driver_card` | `drv-6643-vu-duc-thanh` | `driver_card` | Driver Vũ Đức Thành has an Acceptance Rate of 65.0% and Completion Rate of 71.0%, operating vehicle 30H-664.31. |
| `TC-009` | Fetch driver card by plate number 51K-882.91. | `get_driver_card` | `drv-5521-le-quang-minh` | `driver_card` | Plate 51K-882.91 belongs to driver Lê Quang Minh (drv-5521-le-quang-minh), operating Green SM Car (VF 5 Plus). |
| `TC-010` | Show driver details for vehicle plate 30F-982.11. | `get_driver_card` | `drv-3819-tran-dinh-trong` | `driver_card` | Plate 30F-982.11 belongs to Trần Đình Trọng (drv-3819-tran-dinh-trong), status: UNDER_INVESTIGATION. |

### Category 2: Driver Trip Telemetry & Stall History (get_driver_trip_history)

| Test ID | Input Question / Trigger | Expected Tool | Expected Entity / Chunk ID | UI Format | Gold Verification & Acceptance Criteria |
|:---:|---|---|---|:---:|---|
| `TC-011` | What is the trip history and stall records for drv-8492-nguyen-van-a? | `get_driver_trip_history` | `drv-8492-nguyen-van-a` | `driver_history` | Driver drv-8492-nguyen-van-a has 3 recorded trips: trip-9021-hanoi (stall 210s, ERR-02), trip-8891-hanoi (stall 30s, completed), and trip-8744-hanoi (stall 195s, ERR-02). |
| `TC-012` | Did driver drv-8492-nguyen-van-a have any passenger cancellation due to stationary stalls? | `get_driver_trip_history` | `drv-8492-nguyen-van-a` | `driver_history` | Yes, driver drv-8492-nguyen-van-a had 2 passenger cancellations with anomaly flag ERR-02 (stalls of 210s and 195s). |
| `TC-013` | Check past trips and anomaly flags for drv-3819-tran-dinh-trong. | `get_driver_trip_history` | `drv-3819-tran-dinh-trong` | `driver_history` | Driver drv-3819-tran-dinh-trong has trip trip-7721-hanoi flagged with ERR-01 (stall 320s, status disputed). |
| `TC-014` | What was the longest stall duration recorded for drv-3819-tran-dinh-trong? | `get_driver_trip_history` | `drv-3819-tran-dinh-trong` | `driver_history` | The longest stall recorded for drv-3819-tran-dinh-trong is 320 seconds on trip trip-7721-hanoi. |
| `TC-015` | Fetch trip logs and violation records for drv-6643-vu-duc-thanh. | `get_driver_trip_history` | `drv-6643-vu-duc-thanh` | `driver_history` | Driver drv-6643-vu-duc-thanh has two flagged trips: trip-6601-hanoi (stall 260s, ERR-02) and trip-6589-hanoi (stall 240s, ERR-02). |
| `TC-016` | How many consecutive passenger cancellation incidents does drv-6643-vu-duc-thanh have? | `get_driver_trip_history` | `drv-6643-vu-duc-thanh` | `driver_history` | Driver drv-6643-vu-duc-thanh has 2 consecutive passenger cancelled trips (trip-6601-hanoi and trip-6589-hanoi) both with ERR-02 flags. |
| `TC-017` | Check trip history for drv-5521-le-quang-minh in Ho Chi Minh City. | `get_driver_trip_history` | `drv-5521-le-quang-minh` | `driver_history` | Driver drv-5521-le-quang-minh completed trip-5510-hcm from District 1 to Tan Son Nhat Airport with 10s stall and no anomaly flags. |
| `TC-018` | Did drv-5521-le-quang-minh trigger any DIC or fraud anomalies recently? | `get_driver_trip_history` | `drv-5521-le-quang-minh` | `driver_history` | No anomaly flags (None) are recorded for drv-5521-le-quang-minh; trip status is nominal and completed. |
| `TC-019` | Look up trip history for driver Pham Hoang Long. | `get_driver_trip_history` | `drv-4418-pham-hoang-long` | `driver_history` | Driver Pham Hoang Long has a clean record with nominal trips completed in Hanoi and no anomaly flags. |
| `TC-020` | View cancellation history and stall duration for trip-9021-hanoi. | `get_driver_trip_history` | `drv-8492-nguyen-van-a` | `driver_history` | Trip trip-9021-hanoi shows a stationary stall of 210 seconds resulting in passenger cancellation and ERR-02 flag. |

### Category 3: General Terms & User Procedures (search_policy_documents)

| Test ID | Input Question / Trigger | Expected Tool | Expected Entity / Chunk ID | UI Format | Gold Verification & Acceptance Criteria |
|:---:|---|---|---|:---:|---|
| `TC-021` | What is the minimum age required for an individual user to accept Green SM Terms of Use? | `search_policy_documents` | `greensm-policy-terms-of-use` | `policy_answer` | An individual user must represent and warrant that they are at least 18 years of age and possess full legal capacity. |
| `TC-022` | How many seconds does a user have to cancel after a partner confirms an order before the agreement concludes? | `search_policy_documents` | `greensm-policy-procedures-for-users` | `policy_answer` | Within thirty (30) seconds after the Partner confirms the order and neither party cancels, the legal electronic agreement is concluded. |
| `TC-023` | Are Green SM transportation partners considered direct employees or independent contractors? | `search_policy_documents` | `greensm-policy-terms-of-use` | `policy_answer` | Partners are independent entities and are not agents, employees, or representatives of Green SM. |
| `TC-024` | Is user consent to personal data collection for promotional marketing mandatory to use Green SM? | `search_policy_documents` | `greensm-policy-terms-of-use` | `policy_answer` | Consent for marketing or market research purposes is voluntary and shall not constitute a condition for using the service. |
| `TC-025` | Which entity operates and owns the Green SM Application in Vietnam? | `search_policy_documents` | `greensm-policy-terms-of-use` | `policy_answer` | The platform is owned and operated by Green and Smart Mobility Joint Stock Company (GSM). |
| `TC-026` | How are notices and formal communications delivered to users under Green SM Terms of Use? | `search_policy_documents` | `greensm-policy-terms-of-use` | `policy_answer` | Notices may be sent through the Application, SMS, or email registered by the user and are deemed received upon dispatch. |
| `TC-027` | Can a user transfer or assign their Green SM account to a third party? | `search_policy_documents` | `greensm-policy-terms-of-use` | `policy_answer` | Users shall not assign or transfer their account or rights under the Agreement to any third party without GSM's prior written consent. |
| `TC-028` | What is the official dispute resolution forum specified in the Green SM Terms of Use? | `search_policy_documents` | `greensm-policy-terms-of-use` | `policy_answer` | Disputes shall be settled by negotiation first, and if unresolved, referred to the competent People's Court in Vietnam. |
| `TC-029` | Under what conditions can Green SM immediately suspend or terminate a user account? | `search_policy_documents` | `greensm-policy-terms-of-use` | `policy_answer` | GSM may suspend or terminate an account immediately if the user breaches terms, violates applicable law, or compromises system security. |
| `TC-030` | What procedure must a user follow when placing a transportation booking order? | `search_policy_documents` | `greensm-policy-procedures-for-users` | `policy_answer` | The user enters pickup and destination points, reviews fare estimate, confirms payment method, and presses order to initiate partner dispatch. |

### Category 4: Car & Bike Passenger Transport Policies (search_policy_documents)

| Test ID | Input Question / Trigger | Expected Tool | Expected Entity / Chunk ID | UI Format | Gold Verification & Acceptance Criteria |
|:---:|---|---|---|:---:|---|
| `TC-031` | What is the maximum passenger capacity allowed in a Green SM Car for 4-seater and 7-seater vehicles? | `search_policy_documents` | `greensm-policy-regulations-on-the-use-of-green-sm-car` | `policy_answer` | Passengers must not exceed the maximum registered seating capacity of the vehicle (excluding the driver) in compliance with traffic law. |
| `TC-032` | What is the mandatory helmet requirement for passengers riding Green SM Bike? | `search_policy_documents` | `greensm-policy-regulations-on-the-use-of-green-sm-bike` | `policy_answer` | Passengers riding Green SM Bike must wear a standard quality helmet provided by the driver or their own conforming helmet. |
| `TC-033` | Can a driver refuse service if a passenger brings odorous or dangerous items into a Green SM Car? | `search_policy_documents` | `greensm-policy-regulations-on-the-use-of-green-sm-car` | `policy_answer` | Yes, drivers have the right to refuse service if the passenger carries prohibited, dangerous, toxic, or strongly odorous goods. |
| `TC-034` | What is the maximum weight and dimensions of passenger luggage allowed on Green SM Bike? | `search_policy_documents` | `greensm-policy-regulations-on-the-use-of-green-sm-bike` | `policy_answer` | Luggage on Green SM Bike must be compact, safely carried by the passenger, and not obstruct the driver's steering or vision. |
| `TC-035` | Is smoking or using e-cigarettes permitted inside Green SM electric vehicles? | `search_policy_documents` | `greensm-policy-regulations-on-the-use-of-green-sm-car` | `policy_answer` | Smoking, vaping, and using electronic cigarettes are strictly prohibited inside all Green SM vehicles. |
| `TC-036` | How long will a Green SM Car driver wait at the pickup point before free waiting time expires? | `search_policy_documents` | `greensm-policy-regulations-on-the-use-of-green-sm-car` | `policy_answer` | The driver waits at the designated pickup location; waiting time exceeding the free threshold may incur additional waiting surcharges. |
| `TC-037` | What should a passenger do if they leave personal belongings in a Green SM Car? | `search_policy_documents` | `greensm-policy-regulations-on-the-use-of-green-sm-car` | `policy_answer` | The passenger should contact Green SM Customer Support immediately via hotline 1900 2088 or in-app support to coordinate with the driver. |
| `TC-038` | Are children under a certain age permitted to ride Green SM Bike unaccompanied? | `search_policy_documents` | `greensm-policy-regulations-on-the-use-of-green-sm-bike` | `policy_answer` | Young children must be accompanied and supervised by an adult passenger; unaccompanied minors under the permitted threshold are not accepted. |
| `TC-039` | What are the sanitation and vehicle cleanliness obligations of Green SM Car drivers? | `search_policy_documents` | `greensm-policy-regulations-on-the-use-of-green-sm-car` | `policy_answer` | Drivers must maintain a clean, well-ventilated, odorless vehicle interior and adhere to 5-star service standards. |
| `TC-040` | What action occurs if a passenger requests a route deviation or unscheduled stop during a trip? | `search_policy_documents` | `greensm-policy-regulations-on-the-use-of-green-sm-car` | `policy_answer` | If the passenger changes the destination or adds stops, the trip fare shall be recalculated based on actual distance and time. |

### Category 5: Green SM Delivery & Express Regulations (search_policy_documents)

| Test ID | Input Question / Trigger | Expected Tool | Expected Entity / Chunk ID | UI Format | Gold Verification & Acceptance Criteria |
|:---:|---|---|---|:---:|---|
| `TC-041` | What is the maximum compensation amount for completely lost or damaged goods with a VAT invoice in Green SM Delivery? | `search_policy_documents` | `greensm-policy-regulations-on-the-use-of-green-sm-delivery` | `policy_answer` | The maximum compensation amount shall not exceed VND 2,000,000 (Two million dong) for goods with a VAT invoice. |
| `TC-042` | What compensation is provided for lost goods that DO NOT have a purchase invoice in Green SM Delivery? | `search_policy_documents` | `greensm-policy-regulations-on-the-use-of-green-sm-delivery` | `policy_answer` | Compensation is calculated at four (4) times the delivery service fee for parcels without verifiable purchase invoices. |
| `TC-043` | What is the maximum weight per package permitted under Green SM Express motorbike delivery? | `search_policy_documents` | `greensm-policy-regulations-on-the-use-of-green-sm-express` | `policy_answer` | The maximum permissible parcel weight for two-wheeled express delivery is 30 kg. |
| `TC-044` | What are the maximum package dimensions (length x width x height) for Green SM Express? | `search_policy_documents` | `greensm-policy-regulations-on-the-use-of-green-sm-express` | `policy_answer` | Standard dimensions must not exceed 50cm x 40cm x 50cm. |
| `TC-045` | Are live animals, precious gems, or cash permitted for shipment via Green SM Delivery? | `search_policy_documents` | `greensm-policy-regulations-on-the-use-of-green-sm-delivery` | `policy_answer` | Live animals, cash, gold, precious stones, and flammable items are strictly prohibited from shipment. |
| `TC-046` | What is the claim notification window for filing a lost or damaged parcel complaint in Green SM Delivery? | `search_policy_documents` | `greensm-policy-regulations-on-the-use-of-green-sm-delivery` | `policy_answer` | Claims must be submitted within fourteen (14) days from the scheduled delivery date. |
| `TC-047` | What happens if the recipient is unreachable after multiple delivery attempts? | `search_policy_documents` | `greensm-policy-regulations-on-the-use-of-green-sm-delivery` | `policy_answer` | The partner shall return the parcel to the sender, and the sender is responsible for applicable return delivery fees. |
| `TC-048` | Does Green SM Delivery provide a door-to-door delivery option for high-rise apartment buildings? | `search_policy_documents` | `greensm-policy-regulations-on-the-use-of-green-sm-delivery` | `policy_answer` | Door-to-door high-rise delivery is available where selected as an add-on service with the corresponding surcharge. |
| `TC-049` | Who is responsible for inspecting parcel packaging before handover in Green SM Express? | `search_policy_documents` | `greensm-policy-regulations-on-the-use-of-green-sm-express` | `policy_answer` | The sender is responsible for secure packaging; the delivery partner has the right to inspect outer condition before acceptance. |
| `TC-050` | Is Green SM liable if goods are confiscated by law enforcement authorities during transit? | `search_policy_documents` | `greensm-policy-regulations-on-the-use-of-green-sm-delivery` | `policy_answer` | Green SM and the delivery partner are exempt from liability if goods are seized or destroyed by competent state authorities. |

### Category 6: Green SM Food Service & Risk Distribution (search_policy_documents)

| Test ID | Input Question / Trigger | Expected Tool | Expected Entity / Chunk ID | UI Format | Gold Verification & Acceptance Criteria |
|:---:|---|---|---|:---:|---|
| `TC-051` | Who bears the risk regarding food quantity, quality, and hygiene in Green SM Food? | `search_policy_documents` | `greensm-policy-regulations-on-the-use-of-green-sm-food` | `policy_answer` | All risks relating to food hygiene, quantity, and preparation quality are borne by the Merchant Partner and/or Delivery Provider. |
| `TC-052` | Can a customer cancel a Green SM Food order after the restaurant has commenced preparation? | `search_policy_documents` | `greensm-policy-regulations-on-the-use-of-green-sm-food` | `policy_answer` | Once the merchant partner has accepted the order and commenced preparation, the customer cannot cancel without incurring full payment. |
| `TC-053` | What proof must a customer provide if food delivered is contaminated or spilled? | `search_policy_documents` | `greensm-policy-regulations-on-the-use-of-green-sm-food` | `policy_answer` | The customer must provide clear photographic or video evidence showing the spilled condition, packaging, and receipt within the reporting window. |
| `TC-054` | How is the delivery fee calculated for Green SM Food orders? | `search_policy_documents` | `greensm-policy-regulations-on-the-use-of-green-sm-food` | `policy_answer` | Delivery fees are calculated based on route distance from the restaurant to customer, dynamic surge, and inclement weather factors. |
| `TC-055` | Are merchant partners required to maintain valid Food Safety Eligibility Certificates in Green SM Food? | `search_policy_documents` | `greensm-policy-regulations-on-the-use-of-green-sm-food` | `policy_answer` | Yes, merchant partners warrant that they hold valid Food Safety Eligibility Certificates and business licenses required by law. |
| `TC-056` | What is the policy regarding allergic reaction disclosures on Green SM Food menus? | `search_policy_documents` | `greensm-policy-regulations-on-the-use-of-green-sm-food` | `policy_answer` | Merchant partners are solely responsible for ingredient descriptions; customers with severe allergies must verify directly before ordering. |
| `TC-057` | What happens if a food item ordered is out of stock when the driver arrives at the restaurant? | `search_policy_documents` | `greensm-policy-regulations-on-the-use-of-green-sm-food` | `policy_answer` | The partner or merchant shall contact the customer to propose a substitute item or cancel and refund the unavailable item. |
| `TC-058` | Who supplies thermal insulated delivery bags to Green SM Food drivers? | `search_policy_documents` | `greensm-policy-regulations-on-the-use-of-green-sm-food` | `policy_answer` | Delivery partners must use certified insulated delivery bags/boxes conforming to Green SM food transport hygiene guidelines. |
| `TC-059` | Is alcoholic beverage delivery permitted on Green SM Food? | `search_policy_documents` | `greensm-policy-regulations-on-the-use-of-green-sm-food` | `policy_answer` | Alcohol sales comply with statutory restrictions; delivery to persons under 18 years of age is strictly prohibited. |
| `TC-060` | What is the maximum response time for merchant partners to accept a food order? | `search_policy_documents` | `greensm-policy-regulations-on-the-use-of-green-sm-food` | `policy_answer` | Merchants must acknowledge and confirm orders within the designated SLA, failing which the order automatically re-routes or expires. |

### Category 7: Vehicle Rental Services & Penalties (search_policy_documents)

| Test ID | Input Question / Trigger | Expected Tool | Expected Entity / Chunk ID | UI Format | Gold Verification & Acceptance Criteria |
|:---:|---|---|---|:---:|---|
| `TC-061` | What is the daily late payment interest rate applied under Vehicle Rental Services GT? | `search_policy_documents` | `greensm-policy-general-terms-applicable-to-vehicle-rental-services` | `policy_answer` | A late payment interest rate of 0.05% per day is applied to the overdue rental balance. |
| `TC-062` | Is the security deposit in electric vehicle rentals refundable, and does it earn interest? | `search_policy_documents` | `greensm-policy-general-terms-applicable-to-vehicle-rental-services` | `policy_answer` | The deposit is refundable upon termination after deductions, and shall not accrue interest. |
| `TC-063` | What action must a rental customer take if the vehicle exhibits sudden brake failure or overheating? | `search_policy_documents` | `greensm-policy-general-terms-applicable-to-vehicle-rental-services` | `policy_answer` | The customer must not attempt repairs or continue driving; they must immediately implement safety measures and notify GSM. |
| `TC-064` | Can a customer start and drive a rented electric vehicle that has been submerged in water? | `search_policy_documents` | `greensm-policy-general-terms-applicable-to-vehicle-rental-services` | `policy_answer` | No. Customers are instructed: 'Do not start the vehicle if it is submerged in water and call for rescue.' |
| `TC-065` | Who is responsible for purchasing compulsory civil liability insurance for rented vehicles? | `search_policy_documents` | `greensm-policy-general-terms-applicable-to-vehicle-rental-services` | `policy_answer` | GSM is responsible for purchasing compulsory civil liability insurance for motor vehicle owners. |
| `TC-066` | What is the penalty if a customer returns a rented electric vehicle with a battery state of charge (SoC) below 20%? | `search_policy_documents` | `greensm-policy-general-terms-applicable-to-vehicle-rental-services` | `policy_answer` | Returning a vehicle below the minimum battery threshold incurs an administrative battery charging surcharge. |
| `TC-067` | Are customers permitted to sub-lease or rent out the GSM vehicle to third parties? | `search_policy_documents` | `greensm-policy-general-terms-applicable-to-vehicle-rental-services` | `policy_answer` | Sub-leasing, pledging, or assigning the rental vehicle to third parties without prior written consent from GSM is strictly prohibited. |
| `TC-068` | Who pays traffic violation fines (cold fines / phạt nguội) incurred during the rental duration? | `search_policy_documents` | `greensm-policy-general-terms-applicable-to-vehicle-rental-services` | `policy_answer` | The customer is solely responsible for paying all administrative traffic fines and processing fees incurred during their rental. |
| `TC-069` | What is the notice period required if a customer wishes to terminate a long-term vehicle rental early? | `search_policy_documents` | `greensm-policy-general-terms-applicable-to-vehicle-rental-services` | `policy_answer` | The customer must provide advance written notice and pay applicable early termination fees as stipulated in the rental contract. |
| `TC-070` | What vehicle handover inspection document must both parties sign at pickup and return? | `search_policy_documents` | `greensm-policy-general-terms-applicable-to-vehicle-rental-services` | `policy_answer` | Both parties must inspect and sign the Vehicle Handover Minutes recording vehicle status, battery SoC, odometer, and scratch marks. |

### Category 8: Promotions & Merchant Campaigns (search_policy_documents)

| Test ID | Input Question / Trigger | Expected Tool | Expected Entity / Chunk ID | UI Format | Gold Verification & Acceptance Criteria |
|:---:|---|---|---|:---:|---|
| `TC-071` | How many days cure period is allowed if a promotional partner breaches an obligation after written notice? | `search_policy_documents` | `greensm-policy-terms-and-conditions-of-online-promotional-services` | `policy_answer` | The partner must remedy such breach within ten (10) days from receiving written notice from Green SM. |
| `TC-072` | Are promotional discount codes (vouchers) convertible into physical cash in Green SM? | `search_policy_documents` | `greensm-policy-terms-and-conditions-of-online-promotional-services` | `policy_answer` | Promotional codes and vouchers have no cash value and cannot be converted or refunded into cash. |
| `TC-073` | Can Green SM unilaterally modify or terminate a promotional campaign before its planned end date? | `search_policy_documents` | `greensm-policy-terms-and-conditions-of-online-promotional-services` | `policy_answer` | Green SM reserves the right to modify, suspend, or terminate promotional campaigns in accordance with applicable advertising laws. |
| `TC-074` | What is the penalty if a promotional merchant provides fraudulent discount information to customers? | `search_policy_documents` | `greensm-policy-terms-and-conditions-of-online-promotional-services` | `policy_answer` | The merchant must immediately rectify the listing and fully indemnify Green SM for all third-party claims and regulatory penalties. |
| `TC-075` | How are intellectual property and trademark rights licensed between Green SM and promotional partners? | `search_policy_documents` | `greensm-policy-terms-and-conditions-of-online-promotional-services` | `policy_answer` | Parties grant each other a limited, non-exclusive, non-transferable license to use logos strictly for campaign marketing purposes. |
| `TC-076` | Can multiple promotional vouchers be stacked together on a single Green SM ride booking? | `search_policy_documents` | `greensm-policy-terms-and-conditions-of-online-promotional-services` | `policy_answer` | Unless explicitly stated otherwise in program terms, only one (1) promotional code may be applied per transaction. |
| `TC-077` | What happens if a trip utilizing a promotional voucher is cancelled by the driver? | `search_policy_documents` | `greensm-policy-terms-and-conditions-of-online-promotional-services` | `policy_answer` | If a trip is cancelled through fault of the driver, the promotional code is automatically re-credited to the user's wallet. |
| `TC-078` | What is the tax liability for promotional gifts or cash discounts provided to partners? | `search_policy_documents` | `greensm-policy-terms-and-conditions-of-online-promotional-services` | `policy_answer` | Each party is responsible for its own statutory tax obligations; personal income tax is withheld where required by Vietnamese tax law. |
| `TC-079` | How long must promotional partners maintain transaction and voucher redemption records? | `search_policy_documents` | `greensm-policy-terms-and-conditions-of-online-promotional-services` | `policy_answer` | Partners must maintain books and records for the period prescribed under Vietnamese statutory accounting and tax regulations. |
| `TC-080` | What constitutes an illegal exploitation or fraud of promotional campaigns on Green SM? | `search_policy_documents` | `greensm-policy-terms-and-conditions-of-online-promotional-services` | `policy_answer` | Creating fake accounts, collusion between driver and passenger, or using automated scripts to farm vouchers constitutes fraud resulting in immediate account ban. |

### Category 9: Privacy Notice & Data Protection (search_policy_documents)

| Test ID | Input Question / Trigger | Expected Tool | Expected Entity / Chunk ID | UI Format | Gold Verification & Acceptance Criteria |
|:---:|---|---|---|:---:|---|
| `TC-081` | What legal basis does Green SM rely upon for processing personal data under Decree 13/2023/ND-CP? | `search_policy_documents` | `greensm-policy-privacy-notice` | `policy_answer` | Processing is grounded on user consent, performance of transport agreements, and compliance with statutory legal obligations under Decree 13/2023/ND-CP. |
| `TC-082` | What types of sensitive personal data does Green SM collect from users? | `search_policy_documents` | `greensm-policy-privacy-notice` | `policy_answer` | Sensitive data includes real-time GPS geolocation, payment transaction data, and national ID/driver license identification. |
| `TC-083` | How long does Green SM retain passenger and driver personal data? | `search_policy_documents` | `greensm-policy-privacy-notice` | `policy_answer` | Personal data is retained as long as necessary to fulfill service purposes or meet statutory accounting, tax, and dispute resolution timeframes. |
| `TC-084` | What rights do data subjects possess regarding their personal data under Green SM Privacy Policy? | `search_policy_documents` | `greensm-policy-privacy-notice` | `policy_answer` | Data subjects have the right to be informed, consent, access, correct, delete, restrict processing, and withdraw consent. |
| `TC-085` | How can a user submit a request to delete their personal data or withdraw consent? | `search_policy_documents` | `greensm-policy-privacy-notice` | `policy_answer` | Users can submit data subject requests in-app or via official email to hotro@greensm.com / Data Protection Officer. |
| `TC-086` | Does Green SM share personal data with third-party service providers and cloud hosts? | `search_policy_documents` | `greensm-policy-privacy-notice` | `policy_answer` | Green SM may share data with payment gateways, cloud hosting providers, mapping vendors, and affiliate Vingroup companies under strict confidentiality. |
| `TC-087` | Under what circumstances may Green SM disclose personal data without the user's prior consent? | `search_policy_documents` | `greensm-policy-privacy-notice` | `policy_answer` | Data may be disclosed without consent in emergencies threatening life/health, national defense, or upon mandatory request by competent state agencies. |
| `TC-088` | What security measures does Green SM implement to protect personal data from breaches? | `search_policy_documents` | `greensm-policy-privacy-notice` | `policy_answer` | Green SM deploys encryption in transit and at rest, role-based access controls, firewalls, and regular security vulnerability assessments. |
| `TC-089` | Is driver camera and audio recording inside the vehicle covered under the Privacy Notice? | `search_policy_documents` | `greensm-policy-privacy-notice` | `policy_answer` | Cabin recording devices strictly serve safety and fraud prevention purposes with prominent in-vehicle advisory notices. |
| `TC-090` | How are international cross-border data transfers handled by Green SM? | `search_policy_documents` | `greensm-policy-privacy-notice` | `policy_answer` | Cross-border transfers adhere to Decree 13 requirements, including impact assessments and filings with the Department of Cyber Security (A05). |

### Category 10: Forensic Cockpit DIC Adjudication & Analyst Outcomes

| Test ID | Input Question / Trigger | Expected Tool | Expected Entity / Chunk ID | UI Format | Gold Verification & Acceptance Criteria |
|:---:|---|---|---|:---:|---|
| `TC-091` | Driver drv-8492-nguyen-van-a stalled for 210s in trip-9021-hanoi causing passenger cancellation. What outcome should the analyst select? | `search_policy_documents` | `greensm-policy-terms-of-use` | `forensic_brief` | ERR-02 Driver Induced Cancellation (210s stall confirmed). Predicted violation: ERR-02; analyst outcome: Agree with mandatory rationale. |
| `TC-092` | Review suspected DIC violation for drv-6643-vu-duc-thanh with repeated stall duration of 260s. | `search_policy_documents` | `greensm-policy-terms-of-use` | `forensic_brief` | Confirmed ERR-02 repeat violation with 240-260s stationary stalls. Predicted violation: ERR-02; analyst outcome: Agree. |
| `TC-093` | What is the policy classification under Green SM regulations for drivers who intentionally detour or delay pickup? | `search_policy_documents` | `greensm-policy-regulations-on-the-use-of-green-sm-car` | `forensic_brief` | Drivers intentionally detouring or delaying to coerce passenger cancellation are classified as ERR-02 violation pattern. |
| `TC-094` | Adjudicate anomaly ERR-01 reported for driver drv-3819-tran-dinh-trong with 320s stall duration. | `search_policy_documents` | `greensm-policy-terms-of-use` | `forensic_brief` | Stationary stall of 320s confirmed without heavy traffic. Predicted violation: ERR-01; analyst outcome: Agree (or Request More Evidence). |
| `TC-095` | Can a fraud analyst select Disagree if GPS evidence demonstrates road blockage? | `search_policy_documents` | `greensm-policy-terms-of-use` | `policy_answer` | Yes, if telematics confirms gridlock, accident, or road closure, the analyst selects Disagree (dismisses prediction as false alarm) with written rationale. |
| `TC-096` | What pre-filled rationale should be generated for confirming an ERR-02 DIC violation? | `search_policy_documents` | `greensm-policy-terms-of-use` | `forensic_brief` | Suggested rationale: 'Xác nhận vi phạm ERR-02: Dừng đỗ cố tình ép khách hủy. Đồng ý với dự đoán vi phạm (Agree).' |
| `TC-097` | What evidence threshold is required to confirm an Agree outcome for a predicted DIC violation? | `search_policy_documents` | `greensm-policy-terms-of-use` | `policy_answer` | Requires confirmed telemetry evidence showing stall >180s in normal traffic conditions and passenger cancellation without driver pickup attempt. |
| `TC-098` | What is the dispute escalation channel if a customer reports unfair cancellation fees due to driver non-movement? | `search_policy_documents` | `greensm-policy-procedures-for-users` | `policy_answer` | The system processes an automatic refund of the cancellation fee, and dispatches preserved recovery ride intent under UC-L06-01. |
| `TC-099` | Are drivers compensated for lost income if an appeal overturns a wrongful fraud finding? | `search_policy_documents` | `greensm-policy-terms-of-use` | `policy_answer` | Upon overturn, the platform restores account standing immediately and assesses compensation according to approved driver operations policy. |
| `TC-100` | How does the Fraud Cockpit prevent automated algorithmic closures without human-in-the-loop review? | `search_policy_documents` | `greensm-policy-terms-of-use` | `policy_answer` | Per UC-L06-04 invariant, the system only predicts violations and applies no penalties; all dismissals and Agree/Disagree outcomes require explicit HITL Fraud Analyst approval plus written rationale. |

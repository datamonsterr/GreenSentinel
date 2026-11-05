# L06 Decision Log — Phase 1 Baseline and Deferred Vision

## Approved Phase 1 Decision Baseline

The strict [PRD release scope](PRD.md#1-document-control) was adopted by **@datamonsterr on 2026-09-30**. It governs Phase 1 acceptance ahead of the broader L06 assumptions below. **CV-01 operational baselines and operator UAT remain pending**; scope adoption is not operational validation.

| Decision | Approved rule | Authority / date | Acceptance |
|---|---|---|---|
| DEC-P1-01 | All dismissals and adverse sanctions, including warnings, require authorized analyst confirmation plus written rationale. Technical guardrails recommend dismissal and block adverse sanctions. | @datamonsterr / 2026-09-30 | `AC-P1-02/03/04` |
| DEC-P1-02 | Only initial analyst adjudication is Phase 1 core; driver mobile/dispute expansion and appeals are deferred. | @datamonsterr / 2026-09-30 | `AC-P1-05` |
| DEC-P1-03 | Analyst Decision Concordance is strictly >90% against fixed gold decisions for each of 3 reviewers completing 30 cases; at least 28 matches each, 27/30 fails. Keep 100% guardrail adherence and the prescribed timing protocol. | @datamonsterr / 2026-10-02 | `AC-P1-06` |
| DEC-P1-04 | Per-case classifier confidence is [0,1], with `score_semantics=uncalibrated_model_confidence` by default; it is not accuracy, guilt probability, or authorization. Calibration needs separate held-out evidence and versioning. | @datamonsterr / 2026-10-02 | `AC-P1-07` |
| DEC-P1-05 | Top-k route alternatives are optional pending a scoped product decision; they are not a Must feature, detector, or score metric. | @datamonsterr / 2026-10-02 | `AC-P1-08` |
| DEC-P1-06 | Scope amendment: the system only predicts violations and flags system errors. Analyst outcomes are limited to `Agree`, `Disagree`, and `Request More Evidence`, each `Agree`/`Disagree` with confirmation and rationale. The product applies no warning, fine, clawback, suspension, termination, or escalation. Supersedes the sanction clause of `DEC-P1-01` and the Suspend/Escalate outcomes of `FR-04`. | Team decision requested by @datamonsterr / 2026-10-16 | `AC-P1-02/03/04` |

See the [acceptance and test matrix](PRD.md#101-phase-1-acceptance-and-test-traceability). [PR #40](https://github.com/AI20K-Build-Phase-Cohort-4/P-063/pull/40) is MERGED historical runtime divergence at `586caec05ddb7626a1f47066b55154e74d245cc0`, not release authorization. Runtime reconciliation stays with [#73](https://github.com/AI20K-Build-Phase-Cohort-4/P-063/issues/73), owned by [#86](https://github.com/AI20K-Build-Phase-Cohort-4/P-063/issues/86) / [#60](https://github.com/AI20K-Build-Phase-Cohort-4/P-063/issues/60).

The remaining L06 register preserves discovery history and future policy options. Its live recovery, appeal, and release-gate assumptions are not current Phase 1 requirements; stakeholder validations remain unresolved as recorded.

## Scheduled extension decisions — 2026-10-05

Authority: Pham Thanh Dat (@datamonsterr), saved-session lifecycle and defaults approvals, recorded in [#147](https://github.com/AI20K-Build-Phase-Cohort-4/P-063/issues/147). See the complete [requirements](DRIVER_FIRST_REQUIREMENTS.md), including the remaining reasonableness criterion, and [glossary](DRIVER_FIRST_GLOSSARY.md). No runtime conformance is inferred.

| Decision | Approved rule | Supersession boundary |
|---|---|---|
| `DEC-DF-01` | Driver assistance precedes Analyst triage; explicit Driver-confirmed resolution is distinct from exoneration and sanctions. | Scoped exception to `DEC-P1-01/02`; no autonomous dismissal or sanction. |
| `DEC-DF-02` | Strict confidence >0.5 asks the appeal choice; reasonable low-score explanation asks confirmation; exactly 0.5, missing/invalid confidence, unreasonable explanation and model/tool/delivery failure escalate. | Raw confidence semantics in `DEC-P1-04` remain. Reasonableness criterion awaits confirmation. |
| `DEC-DF-03` | No further appeal closes as Driver confirmed resolution, even with disclosed missing/conflicting evidence; Continue appeal escalates. Silence after delivered question escalates at 48 hours. | Requires a valid explicit confirmation step; boundary/error escalation has precedence. |
| `DEC-DF-04` | Late confirmation cannot reverse escalation; only authorized Analysts reopen. | Preserve prior evidence, dialogue, dispositions and actor events. |
| `DEC-WS-01` | Reset starts unchecked, affects one Analyst message, retains case context and audit; partial search uses Driver name/ID/vehicle plate. | Reset is not deletion; plate is not driving-license number. |
| `DEC-WS-02` | Metrics use 7/30/90-day windows, own activity plus organization aggregates for Analysts, authorized team detail for Managers; only explicitly granted multi-role permissions. | No invented operational counts, calibration or implicit privileged grants. |
| `DEC-WS-03` | Queue propagation within 5 seconds; expansion scheduled now; Stitch/explicit visual approval precede new screen coding; Tester UI implementation queued. | Native issue blockers and full DoD remain hard acceptance gates. |

## 1. Scenario Identity and Tree Path

**Leaf:** L06
**Path:** `G1 pass → G2 pass → G3 pass → G4a pass → G4b pass → G4c pass → G5 fail or not assessed`
**Posture:** Operate live passenger recovery and human-in-the-loop (HITL) enforcement. Every fine or suspension requires an authorized Fraud Analyst decision. CV-18 and CV-19 remain future automation gates and cannot weaken this control.

This scenario is hypothetical until GreenSM stakeholders validate the branch evidence and decisions below. A claimed G1–G4 pass is an entry assumption, not evidence created by this document.

## 2. Source Traceability

- Target scenario definition: [PRD](PRD.md) and [Phase 1 MVP](MVP.md).
- Evidence and classifications: [Discovery Log](DISCOVERY_LOG.md).
- Validation questions CV-01–CV-17 and CV-20: [Customer Interview Guide](CUSTOMER_INTERVIEW_GUIDE.md).

## 3. Historical L06 Decision Register

| Decision ID | Question | Practical options | L06 scenario selection | Status | Owner | Evidence required | Impact |
|---|---|---|---|---|---|---|---|
| DEC-L06-01 | Are the problem scale and Release 1 outcomes valid? | Proceed; narrow segment/scope; hold for evidence; stop/reframe | Proceed only if G1 evidence is signed | Customer validation required | Product Owner + Data/BI | CV-01–CV-04 baselines, source queries, definitions, targets, deadlines | Goals, metrics, entry gate |
| DEC-L06-02 | What operational definition distinguishes suspected DIC from legitimate pickup failure? | Approved rule with enumerated exceptions; analyst-only judgment; no enforceable definition | Approved testable rule before launch | Customer validation required | Product Owner + Fraud Operations + Legal/Policy | CV-03 rule, exception set, decision authority | Labels, case states, sanctions |
| DEC-L06-03 | Which pre-cancellation inputs are allowed? | Movement direction; stationary duration; elapsed pickup time; map traffic; trusted unanswered-call events; approved subset; no scoring | Approved subset; no post-event evidence | Proposed from discovery | Product Owner + Data/BI | CV-08/CV-20 definitions, quality, freshness, manipulation controls | FR-L06-01, score separation |
| DEC-L06-04 | How does each real-time signal trigger? | Independently; configured combination; segment-specific rule; disabled | Independently under approved thresholds | Confirmed discovery rule; thresholds unresolved | Product Owner + Fraud Operations | CV-08 specification and exception tests | Detection behavior |
| DEC-L06-05 | What pre-cancellation bands and actions apply? | No action; analyst alert only; passenger prompt; disable a band | Three bands; exact boundaries unresolved | Customer validation required | Product Owner + Fraud Operations + Data/BI | CV-06/CV-11 action matrix | Prompt and alert eligibility |
| DEC-L06-06 | What may post-cancellation scoring use? | Pre-score context only; add passenger reason; add driver report/video; add system errors; analyst review without score | Approved post-event set stored separately | Proposed from discovery | Fraud Operations + Legal/Policy + Data/BI | CV-07/CV-11 state and score specification | Adjudication evidence |
| DEC-L06-07 | How are duplicate detections handled? | Per signal; per trip; per driver/time window; suppress entirely | One combined notification/case per trip while retaining signal events | Confirmed discovery rule; key unresolved | Fraud Operations + Data/BI | CV-07 deduplication key and collision tests | Alerts, metrics, audit |
| DEC-L06-08 | What wording and choices appear in the passenger prompt? | Reassign; continue original trip; dismiss/defer; contact support; no prompt | Cautious suspected-DIC wording with reassign and continue; exact copy/accessibility unresolved | Proposed | Product Owner + Customer Operations + Legal/Policy | CV-06 approved content and usability evidence | FR-L06-03 |
| DEC-L06-09 | What happens when the passenger does not respond? | Continue; auto-reassign; cancel; escalate | Original trip continues | Confirmed discovery rule | Product Owner | Existing policy confirmation and event semantics | Passenger flow |
| DEC-L06-10 | What does passenger-selected recovery preserve? | Preserve all original attributes; preserve fare only; create new trip with recalculation; manual support | Reassign without rebooking; preserve fare, voucher, pickup, destination | Confirmed discovery requirement; downstream feasibility unverified | Product Owner + Dispatch + Payments | End-to-end reconciliation test | FR-L06-04 |
| DEC-L06-11 | What if reassignment cannot find a driver? | Continue search; support handoff; mandatory refund; restore voucher; issue replacement voucher; no recovery | Normal no-driver timeout then mandatory refund; voucher outcome unresolved | Partly confirmed | Product Owner + Customer Operations + Dispatch | CV-14/CV-15 refund/voucher matrix and timeout | Service recovery |
| DEC-L06-12 | When and how is the driver notified? | Immediately on signal; after passenger action; after cancellation; only when evidence invited; no notice | Passenger prompt first; post-cancellation notice when applicable | Confirmed sequence; exact timing unresolved | Driver Operations + Fraud Operations | CV-09 event/deadline policy | FR-L06-05 |
| DEC-L06-13 | What driver evidence is allowed and safely obtained? | Written reason; pre-existing/safely stationary video for congestion/stationary claim; other approved records; no video | Written reason plus conditional safe video; recording while moving prohibited | Partly confirmed; controls unresolved | Driver Operations + Privacy/Legal + Security | CV-05 format, content, authentication, retention, access, deletion | Evidence safety |
| DEC-L06-14 | What report deadline and late/no-report rule applies? | Fixed minutes/hours; trip-relative window; accept late with reduced weight; close submission; reminder; no adverse inference | Immediate post-cancellation opportunity; exact deadline and late rule unresolved | Customer validation required | Driver Operations + Fraud Operations + Legal/Policy | CV-09 approved timetable and exceptions | Fairness, case readiness |
| DEC-L06-15 | What confirms fraud? | Analyst confirmation only; score plus analyst; high-confidence no-report rule plus analyst sanction review; no confirmation until evidence complete | Approved CV-07 event required; system/application errors remain visible; no score alone can apply sanction | Customer validation required | Fraud Operations + Legal/Policy | CV-07 state model and authority | Metrics, terminology, enforcement |
| DEC-L06-16 | Which analyst roles may take which actions? | One role for all; tiered warning/fine/suspend/escalate; dual approval for defined actions; view-only; no sanctions | Least-privilege matrix; every fine/suspension requires authorized analyst approval | Core control confirmed; matrix unresolved | Fraud Operations + Security + Legal/Policy | CV-12 permission and severity matrix | RBAC, queue routing |
| DEC-L06-17 | What initial outcomes are permitted? | Dismiss; request evidence; warn; fine; suspend; escalate; defer; no action | Discovery-listed outcomes under approved criteria; unavailable actions blocked | Outcome set confirmed; criteria unresolved | Fraud Operations + Driver Operations + Legal/Policy | CV-12 sanction matrix and examples | FR-L06-07 |
| DEC-L06-18 | How does an appeal affect enforcement? | Sanction active; sanction paused; partial restriction; manual exception | Fine/suspension paused pending blinded second review | Confirmed discovery rule | Driver Operations + Fraud Operations | CV-13/CV-16 state-transition test | Appeal workflow |
| DEC-L06-19 | What may the second reviewer see? | Full case; raw evidence without original outcome; partial masking; external panel | Different Fraud Analyst sees raw evidence, submissions, telemetry, and extra message; appeal label, original decision/rationale hidden; audit linkage retained | Proposed interpretation requiring confirmation | Fraud Operations + Security + Legal/Policy | CV-16 field-visibility and separation test | Blinding, audit |
| DEC-L06-20 | What happens after an overturn? | Reverse fine; restore account; compensate income; notify parties; weekly review; no correction | Reverse fine, restore account, queue conflict weekly; compensation unresolved | Partly confirmed | Driver Operations + Legal/Policy + Finance | CV-13 compensation policy and reconciliation evidence | Remediation |
| DEC-L06-21 | How is weekly conflict review governed? | Aggregate review; case review; passenger contact under policy; model/process correction; no review | Higher-level Fraud Analyst reviews weekly and may contact affected Passenger under approved rules | Partly confirmed | Senior Fraud Analyst + Privacy + Model Risk | CV-17 agenda, contact policy, action log | Quality improvement |
| DEC-L06-22 | What audit record is mandatory? | Minimal outcome log; full immutable event chain; sampled audit; no retained linkage | Full authorized event chain with reviewer-hidden appeal linkage retained internally | Proposed | Security + Fraud Operations + Privacy | CV-16 schema, access and retention approval | NFR-L06-04 |
| DEC-L06-23 | How does Release 1 roll out? | Direct live; shadow→alerts→prompt→sanctions; segment/phased; time-boxed canary; do nothing | Only stakeholder-approved phased plan; no default sequence asserted | Customer validation required | Product Owner + Fraud Operations + Driver Operations | CV-10 phases, sample/window, entry/exit evidence | Rollout |
| DEC-L06-24 | What triggers rollback and who can act? | Metric breach; operational overload; safety/privacy incident; evidence outage; dispatch/refund failure; manual stop; no automatic rollback | Immediate safe-state path plus accountable restart approval; exact triggers unresolved | Customer validation required | Product Owner + Engineering + Security | CV-10 trigger matrix, drill, authority | Rollback |
| DEC-L06-25 | May Release 1 automate fines or suspensions? | Never in R1; bounded automation; score-only automation | No. Analyst approval for every fine/suspension | Confirmed Release 1 control | Product Owner + Fraud Operations | Audit test showing zero unapproved sanctions | All enforcement requirements |
| DEC-L06-26 | Is post-Release automation in scope? | Assess G5; defer; reject permanently | Defer CV-18/CV-19 to future gate | Out of scope | Product Owner + Model Risk | Separate G5 decision record | Prevents scope creep |

## 4. Option Guardrails

1. `Do nothing/disable` remains available for every live action when evidence or safety approval is absent.
2. Pre-cancellation scoring cannot consume driver reports, passenger cancellation reasons, post-cancellation video, or later error findings.
3. Passenger cancellation/reassignment is final for that service event; later evidence affects adjudication only.
4. A missing driver report does not hide system/application errors and never authorizes an automatic fine or suspension.
5. No unapproved number in this log is a product default. Numeric values must carry source, owner, version, effective date, and rollback rule.

## 5. Selected Scenario Assumption and Rationale

L06 assumes G1–G4 have evidence-backed approvals, live passenger recovery is safe, and authorized analysts can adjudicate cases. G5 is failed or unassessed, so human approval remains mandatory for every fine and suspension. This posture delivers immediate Passenger recovery while keeping adverse Driver actions reviewable, appealable, and auditable.

## 6. Evidence Classification

| Classification | L06 content |
|---|---|
| Confirmed in discovery | Independent candidate signals; one combined trip notification; non-response continues original trip; preserved reassignment attributes; mandatory refund after failed reassignment; analyst approval for every fine/suspension; paused sanction during second review; reversal/account restoration after overturn. |
| Proposed | Separate score/state model, cautious prompt pattern, least-privilege permissions, immutable audit chain, phased rollout. |
| Hypotheses | Detection improves outcomes; analysts have sufficient capacity; live recovery will not cause unacceptable false-positive harm or dispatch overload. |
| Assumed for leaf | Documented G1–G4 pass evidence exists and remains current. |
| Unresolved | Baselines/targets; exact signal/band values; evidence deadline/retention; sanction criteria; appeal SLA/compensation; voucher fallback; timeout; passenger-contact rules; rollout and rollback thresholds. |

## 7. Stakeholder/RACI and Evidence Plan

| Decision area | Accountable | Responsible | Consulted | Required adoption evidence |
|---|---|---|---|---|
| Outcomes and rollout | Product Owner | Release Lead | Fraud, Driver, Customer, Dispatch Operations | CV-01–04/10 signed gate packet |
| Detection and metrics | Product Owner | Data/BI | Fraud Operations, Model Risk | CV-06–08/11/20 versioned specification |
| Evidence and sanctions | Fraud Operations lead | Fraud + Driver Operations | Legal/Policy, Privacy, Security | CV-05/09/12 SOP and tests |
| Passenger recovery | Product Owner | Dispatch + Customer Operations | Payments, Legal/Policy | CV-14/15 reconciliation tests |
| Appeals and audit | Fraud Operations lead | Security + Driver Operations | Legal/Policy, Privacy, Finance | CV-13/16/17 field, state, audit, compensation decisions |
| Rollback/restart | Product Owner | Engineering/SRE | Security and all operations leads | Trigger matrix, drill result, named authority |

Owners must assign evidence-backed due dates. This document invents none.

## 8. Consequences, Risks, Dependencies, and Exit Criteria

### Consequences

- Passengers can choose live recovery without waiting for fraud adjudication.
- Drivers receive a bounded evidence and appeal process; their evidence cannot undo Passenger recovery.
- Fraud Operations assumes live queues, explicit permissions, sanction accountability, and weekly conflict review.
- Release 1 generates evidence for—not approval of—future automation.

### Risks and controls

| Risk | Required control |
|---|---|
| False-positive prompt or sanction | Approved error tolerance, visible errors, analyst decision, appeal and correction |
| Unsafe video capture | No recording while moving; approved capture instructions and access/retention policy |
| Passenger stranded or repriced | Preserve attributes; timeout fallback; refund reconciliation; voucher decision |
| Analyst overload | Capacity evidence, staged rollout, queue monitor, pause/rollback |
| Unauthorized or automated sanction | Deny-by-default RBAC, approval event, invariant monitor and audit |
| Biased second review | Different analyst, hidden prior outcome/rationale, retained audit-only linkage |
| Threshold drift or silent policy change | Versioned approval; CV-18/19 cannot activate in L06 |

### Dependencies

Approved G1–G4 gate packet; telemetry/trip/call/map/error sources; dispatch and payment recovery; case management; evidence storage; identity/RBAC; notification; immutable audit; staffed initial and second-review queues.

### Entry, exit, and rollback

- **Enter:** all CV-01–CV-17 and CV-20 Release 1 blockers have approved decisions/evidence; required integrations and safe-state drill pass.
- **Remain:** G5 fails or remains unassessed; analyst approval stays mandatory.
- **Exit to L07:** only through a separate approved G5 record covering CV-18/CV-19.
- **Rollback:** disable the affected live action, preserve cases/audit, complete Passenger recovery already accepted, pause new sanctions as policy requires, assess harm, and require named reauthorization.

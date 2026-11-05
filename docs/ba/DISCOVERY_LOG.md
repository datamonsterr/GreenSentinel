# Business Analysis Discovery Log

Source: [Product Requirements Document (PRD)](PRD.md)

Customer validation plan: [Customer Interview Guide](CUSTOMER_INTERVIEW_GUIDE.md)

Target release scenario: [Release 1 HITL Enforcement PRD](PRD.md) and [Phase 1 MVP Specification](MVP.md)

## 2026-10-02 — Approved Phase 1 Baseline

**Authority:** @datamonsterr adopted the strict [PRD release scope](PRD.md#1-document-control) on **2026-09-30**, then approved metric, score, and optional top-k elaboration on **2026-10-02**. Phase 1 delivers initial analyst adjudication. All dismissals and adverse sanctions (including warnings) require authorized analyst confirmation plus written rationale; driver mobile/dispute expansion and appeals are deferred.

The [decision baseline](DECISION_LOG.md#approved-phase-1-decision-baseline) and [PRD acceptance matrix](PRD.md#101-phase-1-acceptance-and-test-traceability) define the current contract. **CV-01 operational baselines and operator UAT remain pending.** Earlier elicitation rounds preserve historical proposals, not operational validation or scope authorization. The V2 autonomous-exoneration proposal is superseded. [PR #40](https://github.com/AI20K-Build-Phase-Cohort-4/GreenSentinel/pull/40), MERGED at `586caec05ddb7626a1f47066b55154e74d245cc0`, is historical runtime divergence tracked under [#73](https://github.com/AI20K-Build-Phase-Cohort-4/GreenSentinel/issues/73); documentation reconciliation does not prove runtime conformance.

## Status Legend

| Status | Meaning |
|---|---|
| Confirmed | Explicitly stated by the project team |
| Hypothesis | Assumed by the project team; evidence is not yet available |
| Customer validation required | Must be answered or verified with GreenSM stakeholders or operational data |

## 2026-09-26 — Async Driver Agent & Copilot Collaboration (Round 12, ask-why-ba elicitation)

Historical, deferred discovery: [`DISCOVERY_POC_V2_DRIVER_AGENT.md`](DISCOVERY_POC_V2_DRIVER_AGENT.md). Its former autonomy decisions are superseded by the approved Phase 1 baseline.

### PP-05 — Driver dispute bottleneck & repetitive phone outreach
- **Painpoint:** When risk models flag suspected fraud, drivers reject with reasons. Fraud analysts currently must manually call each driver and cross-verify statements using isolated tools. Drivers experience long wait times in limbo; analysts burn operational hours on repetitive phone tag.
- **Hypothesis:** An asynchronous AI Driver Agent responding immediately to driver disputes can automate repetitive evidence-collection procedures, verify factual claims (traffic, app crashes) via shared tools, and synthesize driver explanations directly into the Fraud Analyst's Cockpit chatbox.
- **Classification:** Confirmed operational bottleneck; technical and authority boundaries pending clarification (Round 12 ask-why-ba).

## 2026-09-19 — Defined Pain Point (Round 11, ask-why-ba validation)

The problem is now defined. These four statements anchor all downstream PRDs and replace per-round problem re-discovery.

### PP-01 — Primary persona and pain

**Primary persona: the Fraud Analyst.** Pain: manual violation review (10–15 min/case of map reconstruction and log auditing) while evasion methods grow increasingly sophisticated; data volume is far beyond human throughput, so humans process only a fraction of alerts. **Classification:** Confirmed framing; magnitude and exact baselines require operational evidence (CV-01, CV-02).

### PP-02 — Users and drivers are solution resources

The solution may require resources not only from the Agent but from Passengers and Drivers (via the GSM app) through proactive, supplementary prompts that improve violation detection. Examples validated in elicitation:

- Passenger real-time confirmation ("is the driver moving toward you?") is a decisive case-creation factor: confirm → live re-score → case if band exceeded; deny → downweight score, record status, kinematic evidence is never erased.
- Driver counter-reports and crowd-sourced street status (banned, flooded, congested) validated by an ensemble of 7 sources: agent, passenger, driver, algorithm, external data, fraud analyst, system data.

**Classification:** Hypothesis with confirmed direction; safety limits require customer validation (CV-06, CV-08, CV-11, CV-20). Deferred to Phase 2/3.

### PP-03 — Risk constraints on the solution

Added risk must be bounded: wrongful sanctions (xử phạt nhầm), missed detections (detect thiếu), creating new violation types, and over-pestering users and drivers. **Classification:** Confirmed constraint; numeric tolerances remain customer validation (CV-06, CV-09, CV-11).

### PP-04 — Cost and difficulty bounds

Cost and problem difficulty are not yet optimized but must not balloon. **Classification:** Confirmed constraint; budget/effort ceiling requires customer input.

### Round 11 open items

| Question | Owner |
|---|---|
| Case-creation band when a human confirms: reuse the L06 prompt band or a separate lower band? | Product Owner + Fraud Operations |
| Who seeds the street-status registry (cold start): operations team or trusted-driver program? | Driver Operations |
| Who maintains ensemble source-weighting by historical precision? | Data/BI |

## Discovery Record — Rounds 1–10 (Condensed)

Full per-round detail was consolidated once the pain point stabilized; the record below preserves every confirmed decision and its classification.

| Round | Topic | Key confirmed answers |
|---|---|---|
| 1 | Baselines, bottleneck, DIC vs legitimate failure, Release 1 outcomes | Baselines unavailable (CV-01–04). Manual-reconstruction bottleneck is a hypothesis. Candidate metrics: customer-reported cancellations, pickup completion, detected-fraud rate (with pairing warning). DIC separable via trajectory, system logs, driver reason + evidence, photo + map data for congestion claims. |
| 2 | Metric formulas, fraud-rate meaning, first action, false-positive mitigation | Provisional: pickup completion = completed pickups / assigned trips; customer-reported DIC rate = reported / all customer cancellations. Fraud rate = confirmed cases / all generated alerts. Action: cautious passenger reassignment prompt + human reviewer only. Mitigation: driver can submit a report. |
| 3 | Denominator, trigger signals, non-response, driver response | Denominator = all generated fraud alerts. Signals: movement away, no movement, elapsed time. Passenger non-response → original trip continues. Driver notified and may submit a report with clear evidence. |
| 4 | Signal independence, notification order, evidence, dedupe, conflict rule | Each signal triggers independently. Passenger prompt first; driver notified only after cancellation. Evidence: instructed video + optional written reason. One combined notification per trip. Passenger cancellation is never reversed by later driver evidence. |
| 5 | Pre-review fine, deadline, reviewer, video condition, shadow mode | No fine before human review. Driver report immediately after cancellation. Analyst decision target: within 8 hours. Video only for congestion/prolonged-stationary claims. Shadow mode: ask the customer (CV-10). |
| 6 | Recovery, attributes, no-report, analyst outcomes, appeal | Reassignment without a new booking; preserve fare, voucher, pickup, destination. No-report = automatic failure (later refined, Round 8). Analyst may dismiss, request evidence, warn, fine, suspend, escalate. Appeal allowed. |
| 7 | Automatic confirmation, timeout, sanction level, pause, second review | No report + no system error → fraud automatically confirmed (human still applies the sanction). Reassignment timeout → normal no-driver policy + mandatory refund. Second review by a different analyst, appeal label hidden. |
| 8 | Appeal pause, blinded view, overturn, confidence score, voucher | Sanction pauses during second review. Second analyst sees raw evidence only. Overturn → reverse fine, restore account, weekly conflict queue. Fraud-confidence score replaces absolute auto-confirmation; system errors block auto-confirmation; very low confidence produces no alert. Voucher on timeout: CV-14. |
| 9 | Pre-score inputs, bands, post-score inputs, sanction approval, weekly owner | Real-time inputs: movement direction, stationary duration, elapsed pickup time, map traffic, ignored phone calls. Three pre-bands: no action / analyst alert / passenger prompt. Post-score adds driver report, passenger reason, video, system errors. Release 1: analyst approval for every fine/suspension; senior analyst owns weekly review. |
| 10 | Contact scope, reliability metrics, threshold activation, ignored contact | Senior analyst may contact the affected passenger. Reliability metrics: ask the customer (CV-18). Threshold changes never self-activate; senior analyst approval required (CV-19). Ignored contact = phone calls only (CV-20). |

## 2026-09-19 — Round 11 Findings (per-error-class detection architecture)

From pain-point validation with the project team:

| ID | Finding | Classification |
|---|---|---|
| R11-01 | Detection is per error class (ERR-01–ERR-05, [PRD §3](PRD.md#3-taxonomy-of-violations--fraud-patterns)): single-trip fraud (stalling, GPS spoofing) uses single-trip signals with passenger/driver as model resources and parameters; group/incentive fraud (e.g., Xanh Now driver–passenger matching, ERR-03/04) requires graph-based analysis. | Confirmed direction; ERR-03/04 remain outside the single-trip DIC scope (deferred to batch/group governance). |
| R11-02 | "Low-and-slow" fraud (each trip below threshold, aggregate above) is only catchable via batch multi-trip network analysis, not real-time scoring. | Hypothesis; batch design deferred to shared governance. |
| R11-03 | Driver↔passenger bipartite graph visualization is a solution-side option, not a requirement. | Confirmed (parked). |
| R11-04 | Historical elicitation target: in-ride intervention within 2–3 minutes (deferred); Phase 1 case-review target is under 45 seconds (HITL), with baseline still unvalidated. | Target defined, not measured ([PRD protocol](PRD.md#93-standardized-mttr--quality-evaluation-protocol)). |

## Open Customer-Validation Questions

| ID | Question | Suggested owner | Why it matters |
|---|---|---|---|
| CV-01 | What are the current values and data sources for alert volume, analyst throughput, review time, confirmed-fraud yield, false-positive actions, DIC incidence, pickup completion, and customer cancellations by reason? | Product, Fraud Operations, Data/BI | Establishes the baseline and confirms problem scale (PP-01 magnitude). |
| CV-02 | What activities consume analyst handling time, and how much time does each activity require? | Fraud Operations, frontline analysts | Tests whether trajectory reconstruction is the true bottleneck. |
| CV-03 | What operational definition distinguishes suspected DIC from legitimate pickup failure, and who makes the final decision? | Product, Driver Operations, Legal/Policy | Makes labels and enforcement rules testable. |
| CV-04 | Confirm the denominator, attribution window, segments, exclusions, baseline, target, and deadline for each Release 1 metric. | Product Owner, Data/BI | Finalizes the provisionally accepted metric definitions. |
| CV-05 | For congestion or prolonged-stationary explanations, how is driver video safely captured and authenticated, what content is permitted, how long is it retained, and who may access it? | Driver Operations, Legal/Policy, Privacy | Reduces unsafe evidence capture, privacy exposure, and wrongful sanctions (PP-03). |
| CV-06 | What minimum precision or maximum false-positive rate is acceptable before showing a passenger reassignment prompt or sending a case for review? | Product Owner, Fraud Operations, Driver Operations | Defines the safety threshold for intervention and for user/driver prompts (PP-02, PP-03). |
| CV-07 | What adjudication event qualifies a fraud case as confirmed, how are duplicate alerts treated, and what reporting window applies? | Fraud Operations, Data/BI | Completes the confirmed-fraud-rate definition. |
| CV-08 | What distance, duration, GPS-quality, and exception thresholds apply to each independently triggering suspected-DIC signal? | Product Owner, Fraud Operations, Data/BI | Makes suspected-DIC detection testable. |
| CV-09 | What exact post-cancellation submission window applies, and what happens when the driver submits late or does not report? | Driver Operations, Fraud Operations, Legal/Policy | Defines procedural fairness and evidence timing. |
| CV-10 | Should rollout begin in shadow mode before passenger prompts and fines are enabled, and what exit criteria permit live intervention? | Product Owner, Fraud Operations, Driver Operations | Defines a safe transition from current to future operations (PP-03). |
| CV-11 | Define numeric thresholds for the three pre-cancellation bands and separate post-cancellation confidence bands, including the case-creation band after human confirmation. | Product Owner, Fraud Operations, Data/BI, Legal/Policy | Makes permitted actions testable without mixing real-time and post-event evidence (Round 11 open item). |
| CV-12 | Which analyst roles may warn, fine, suspend, or escalate, and what evidence and severity criteria govern each action? | Fraud Operations, Driver Operations, Legal/Policy | Prevents inconsistent or unauthorized sanctions. |
| CV-13 | What is the blinded second-review SLA, and is lost driver income compensated when the original decision is overturned? | Driver Operations, Legal/Policy | Completes the appeal and compensation process. |
| CV-14 | If reassignment times out, is the voucher restored in addition to the mandatory refund? | Product Owner, Customer Operations | Completes passenger service recovery. |
| CV-15 | What timeout value defines that no replacement driver is available? | Dispatch Operations, Product Owner | Makes the fallback behavior measurable. |
| CV-16 | Confirm that the original decision and rationale are hidden from the second analyst while the platform preserves the complete internal review relationship and audit trail. | Fraud Operations, Legal/Policy, Security | Balances reviewer independence with accountability. |
| CV-17 | Confirm what patterns weekly review examines, when the affected passenger may be contacted, and what corrective actions may result. | Fraud Operations, Model Risk, Product Owner, Privacy | Converts overturned cases into operational and model improvement. |
| CV-18 | Which reliability metrics, target values, sample sizes, and observation periods permit movement beyond mandatory analyst approval? | Model Risk, Fraud Operations, Data/BI, Legal/Policy | Creates an evidence-based automation gate. |
| CV-19 | What bounds, versioning, monitoring, audit, and rollback controls apply to metric-recommended threshold changes approved by a senior fraud analyst? | Model Risk, Engineering, Fraud Operations, Security | Prevents uncontrolled enforcement-policy changes. |
| CV-20 | How many unanswered phone calls within what period qualify as ignored contact, and which trusted system event records each attempt? | Product Owner, Customer Operations, Data/BI, Privacy | Makes the contact signal testable and resistant to manipulation. |

## Running Findings

Items below preserve confirmed framing and historical discovery. Phase 1 scope and authority follow the dated baseline above; future passenger/driver/appeal rules are not release acceptance or validated operational results.

### Confirmed

- Primary persona is the Fraud Analyst; manual review takes 10–15 minutes per case against alert volume humans cannot fully process (PP-01 framing confirmed; exact numeric baselines require operational evidence CV-01).
- Phase 1 MVP is strictly scoped around PP-01 (Fraud Analyst Triage Overload) via the Minimum Decision Flow: Queue -> Case Dossier & GIS -> System Error Guardrail -> Analyst Decision & Sanction -> Immutable Audit Trail.
- 100% Human-in-the-Loop (HITL) enforcement is non-negotiable: zero automated fines or account suspensions. All punitive actions require explicit analyst sign-off and mandatory written rationale.
- System Error Guardrail provides safety recommendations (pre-filling Dismiss recommendation and hard-locking punitive buttons during detected outages/dropouts); zero automated dismissals or sanctions occur without human confirmation.
- The solution may solicit supplementary real-time input from Passengers and Drivers via the app as model resources (PP-02, deferred to Phase 2/3).
- Wrongful sanctions, missed detections, new violations, and user/driver over-pestering are explicit risk constraints on the solution (PP-03).
- Reassignment preserves fare, voucher, pickup point, and destination without a new booking; timeout follows the normal no-driver policy with a mandatory refund (Phase 2).
- Passenger cancellation is never reversed by later driver evidence.
- Video evidence is limited to congestion/prolonged-stationary explanations; no fine before human review; analyst decision target within 8 hours.
- Analysts may dismiss, request evidence, warn, fine, suspend, or escalate; drivers may appeal; second review is blinded and pauses the sanction; overturn reverses the fine and restores the account into weekly conflict review.
- Historical score-band exploration covered no-report cases and low-confidence alert suppression. Under the approved Phase 1 baseline, no score confirms fraud or dismisses a case; an authorized analyst decision and written rationale are required. Exact future alert bands remain open.
- Real-time inputs: movement direction, stationary duration, elapsed pickup time, map traffic, ignored phone calls; three pre-bands (no action / analyst alert / passenger prompt); post-scoring adds reports, video, and errors.
- Detection methods are per error class; graph-based analysis applies to group fraud but stays outside DIC scope; low-and-slow fraud needs batch multi-trip analysis (R11).
- Quantified targets: sub-45-second HITL case review under standardized evaluation protocol (R11-04).

### Hypotheses

- **Operational Alert Volume & Backlog:** Daily alert volume of ~2,000+ alerts/day, ~75% triage backlog, and False Alarm Ratio (FAR) >35% are operational hypotheses modeled for capacity planning and simulation stress-testing, pending operational validation via CV-01.
- **Handling Overhead:** Manual trajectory reconstruction across disjoint tools taking 10–15 minutes per case is a working hypothesis under investigation (CV-02).
- Opposite-direction or non-optimal movement reliably indicates deliberate DIC.
- More detected fraud during Release 1 represents improved detection.
- Passenger confirm/deny re-scoring is reliable against tap-through and collusion behavior (PP-02).
- Crowd-sourced street status reaches break-even precision (>~60%) against analyst time saved.

### Assumptions

- GreenSM retains sufficient telemetry and event logs to reconstruct pickup behavior.
- Cancellation-reason data is structured and attributable to a specific trip and actor.
- Operational teams can adjudicate evidence and support an appeal workflow.
- GSM app surfaces prompts and collects supplementary input without unacceptable annoyance (PP-03).

### Clarifications Requiring Resolution

- The pre-cancellation score cannot use later driver-report behavior; inputs and thresholds are defined independently from post-cancellation adjudication.
- Future alert bands remain open (CV-06, CV-11). Phase 1 human-review obligations are approved: no automated dismissal or adverse sanctions; confidence is advisory under the [score contract](PRD.md#94-per-case-classifier-confidence-and-route-alternatives).
- Threshold adjustment is recommendation-driven and never self-activating; governance controls remain to be confirmed (CV-18, CV-19).
- Case-creation band after human confirmation, street-registry seeding owner, and ensemble weighting owner are open (Round 11 open items).

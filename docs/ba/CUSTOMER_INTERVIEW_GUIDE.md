# GreenSM Customer Interview Guide

## Purpose

Validate the defined pain point, operating policy, safety controls, and Release 1 decision rules for Xanh Bike driver-induced cancellation (DIC) detection.

The pain point is already framed ([Discovery Log, Round 11](DISCOVERY_LOG.md)):

1. **PP-01:** Primary persona is the Fraud Analyst; manual review (10–15 min/case) cannot keep up with alert volume and increasingly sophisticated evasion.
2. **PP-02:** Passengers and Drivers (via the GSM app) may be solution resources through proactive supplementary prompts.
3. **PP-03:** Added risk must be bounded — wrongful sanctions, missed detections, new violations, over-pestering users and drivers.
4. **PP-04:** Cost and difficulty are not yet optimized but must not balloon.

Interviews therefore **quantify and bound** this framing; they do not re-discover the problem. Answers validate the [Release 1 HITL Enforcement PRD](PRD.md) and its [Phase 1 MVP Specification](MVP.md).

## Priority Legend

| Priority | Meaning |
|---|---|
| P0 | Release 1 blocker or material safety/fairness risk |
| P1 | Required before pilot completion or live enforcement |
| P2 | Required before expanding automation beyond Release 1 |

## Facilitation Rules

1. Ask for current operational evidence before discussing the proposed solution.
2. Distinguish observed facts, policy decisions, hypotheses, and unavailable answers.
3. Use one recent anonymized trip or fraud case when validating workflows and exceptions.
4. Record each answer with its decision owner, evidence source, effective date, and follow-up deadline.
5. Do not combine the real-time passenger-intervention score with the post-cancellation adjudication score.
6. Do not describe a case as confirmed fraud before the applicable adjudication rule is satisfied.
7. For every proposed user/driver prompt, capture expected precision gain **and** annoyance/risk cost (PP-02 vs PP-03).

## Requested Pre-Interview Evidence

Request available, anonymized material; absence of evidence is itself a finding.

- Alert volumes, case outcomes, analyst throughput, handling time, false-positive actions, fraud loss, pickup completion, and cancellation-reason data.
- Fraud investigation and sanction SOPs; passenger cancellation, refund, voucher, and reassignment policies.
- Sample telemetry, dispatch, call-attempt, application-error, and map-traffic events with field definitions.
- Driver evidence, appeal, video-retention, access-control, and privacy policies; 2–3 anonymized DIC cases, legitimate pickup failures, and overturned decisions.

## Interview 1 — Quantify the Pain Point and Success

**Duration:** 60 minutes
**Required stakeholders:** Product Owner, Fraud Operations lead, Data/BI owner, frontline fraud analyst
**Outcome:** Measured baselines behind PP-01 and approved Release 1 outcomes

| Priority | ID | Question | Required evidence or decision |
|---|---|---|---|
| P0 | CV-01 | Current values and authoritative data sources for alert volume, analyst throughput, handling time, confirmed-fraud yield, false-positive actions, DIC incidence, pickup completion, and customer cancellations by reason? | Baseline value, period, segment, report owner, and known data-quality limitation per metric. |
| P0 | CV-02 | Walk through a recent investigation: time spent on trajectory reconstruction, alert validation, dashboard switching, policy interpretation, evidence collection, sanction approval? | Step-level timing, handoffs, queues, rework, and the actual bottleneck. |
| P0 | CV-03 | What operational definition separates suspected DIC from legitimate pickup failure, and who owns the final classification? | Testable definition, legitimate exceptions, decision owner, policy reference. |
| P0 | CV-04 | For each Release 1 metric: numerator, denominator, attribution window, segment, exclusion, baseline, target, deadline? | Approved metric dictionary and target table. |

### Challenge Questions

- If trajectory reconstruction were instant tomorrow, which investigation delays would remain?
- Could a higher detected-fraud rate indicate worsening fraud rather than better detection?
- Which outcome justifies stopping the initiative if it does not improve?

## Interview 2 — Real-Time Detection and Passenger Intervention

**Duration:** 60 minutes
**Required stakeholders:** Product Owner, Fraud Operations lead, Dispatch Operations, Data/BI owner
**Outcome:** Testable pre-cancellation inputs, thresholds, and prompt rules (PP-02 bounds)

| Priority | ID | Question | Required evidence or decision |
|---|---|---|---|
| P0 | CV-06 | Minimum precision / maximum false-positive rate before a passenger prompt or analyst alert? Also: case-creation band after a human confirm/deny re-score. | Separate error tolerances for passenger intervention, analyst alerts, and post-confirmation case creation. |
| P0 | CV-08 | Distance, duration, GPS-quality, map-traffic, and exception thresholds for movement-away, stationary, and elapsed-time signals? | Signal definitions, units, thresholds, data freshness, exception list. |
| P0 | CV-11 | Numeric bands for the three pre-cancellation actions and separate post-cancellation confidence bands? | Versioned score-to-action matrix with prohibited automated actions. |
| P0 | CV-20 | How many unanswered phone calls within what period qualify as ignored contact, and which trusted event records each attempt? | Call-event source, actor, count, window, failure handling, manipulation controls. |

### Edge Cases to Test

- GPS drift, tunnels, dead zones, low battery, application/network failure.
- One-way streets, police diversions, unsafe pickup points, congestion, passenger pin errors.
- Passenger taps through prompts (habitual confirm) or colluding deny answers (PP-03).
- Multiple signals on one trip; only one combined notification.

## Interview 3 — Driver Evidence and Initial Adjudication

**Duration:** 60 minutes
**Required stakeholders:** Fraud Operations lead, Driver Operations, Legal/Policy, Privacy representative
**Outcome:** Safe evidence policy and authorized initial-review outcomes

| Priority | ID | Question | Required evidence or decision |
|---|---|---|---|
| P0 | CV-05 | How may driver video be safely captured and authenticated, what content is permitted, retention, access? | Safe-capture instruction, formats, authenticity, retention, RBAC, deletion rule. |
| P0 | CV-07 | What event changes a suspected case to confirmed fraud, duplicate-alert treatment, reporting window? | Case-state model, confirmation authority, dedupe key, reporting period. |
| P0 | CV-09 | Exact post-cancellation window for driver reports; late or absent report handling? | Deadline, reminder behavior, late-evidence rule, effect on confidence. |
| P0 | CV-12 | Which analyst roles may dismiss, request evidence, warn, fine, suspend, or escalate, and on what criteria? | Role-permission matrix, sanction matrix, approval limits, escalation path. |

### Safety and Fairness Checks

- No recording while riding; every fine/suspension needs human approval (PP-03).
- System/application errors stay visible to reviewers even without a driver report.
- Passenger cancellation and reassignment are never reversed by later driver evidence.

## Interview 4 — Appeals and Passenger Service Recovery

**Duration:** 60 minutes
**Required stakeholders:** Driver Operations, Customer Operations, Fraud Operations, Legal/Policy, Security
**Outcome:** Complete appeal, compensation, refund, and audit rules

| Priority | ID | Question | Required evidence or decision |
|---|---|---|---|
| P1 | CV-13 | Blinded second-review SLA; lost driver income compensated on overturn? | SLA, paused-sanction rule, compensation policy, final authority. |
| P1 | CV-14 | When reassignment times out, is the voucher restored in addition to the mandatory refund? | Refund and voucher matrix by payment and promotion type. |
| P1 | CV-15 | What timeout defines that no replacement driver is available? | Timeout value, segment/location exceptions, manual-support trigger. |
| P0 | CV-16 | What the second analyst cannot see, and how the platform preserves linked history, identities, and timestamps for audit? | Field visibility list, hidden fields, separation of duty, immutable audit events. |

### Appeal Scenario to Walk Through

Fine/suspend → driver appeals → sanction pauses → different analyst sees raw evidence unlabeled → overturn reverses and queues weekly review. Confirm every state, notification, role, SLA, and compensation outcome.

## Interview 5 — Pilot, Reliability, and Model Governance

**Duration:** 60 minutes
**Required stakeholders:** Product Owner, senior Fraud Analyst, Model Risk, Data/BI, Engineering, Security
**Outcome:** Safe rollout plan and controlled threshold-change process (PP-03, PP-04)

| Priority | ID | Question | Required evidence or decision |
|---|---|---|---|
| P0 | CV-10 | Shadow mode before live prompts and fines? Exit criteria per live action? | Rollout phases, sample size, observation period, rollback trigger, accountable approver. |
| P1 | CV-17 | Weekly conflicting-decision review patterns, passenger-contact conditions, corrective actions? | Review agenda, owner, contact policy, action log, escalation path. |
| P2 | CV-18 | Reliability metrics, targets, sample sizes, observation periods to move beyond mandatory analyst approval? | Approved automation-readiness scorecard. |
| P1 | CV-19 | Bounds, versioning, monitoring, audit, rollback controls for metric-recommended threshold changes? | Change-control workflow, approver, version record, rollback authority. |

### Governance Constraint

Metrics may recommend a threshold adjustment, but no change activates without senior fraud-analyst approval. Weekly review may recommend but never directly modify production thresholds.

## Decision Gates

| Gate | Required evidence | Exit decision |
|---|---|---|
| G1 — Problem validated | CV-01 through CV-04 answered with operational evidence | Confirm, narrow, or reject the current problem statement. |
| G2 — Detection testable | CV-06, CV-08, CV-11, and CV-20 answered | Approve an offline evaluation specification. |
| G3 — Pilot safe | CV-05, CV-07, CV-09, CV-10, CV-12, and CV-16 answered | Approve shadow mode or return for policy remediation. |
| G4 — Live intervention safe | Passenger recovery, evidence, sanction, appeal, accuracy, and rollback rules approved | Enable analyst alerts and then passenger prompts in approved phases. |
| G5 — Automation eligible | CV-18 and CV-19 reliability and governance controls satisfied | Consider reducing human approval; not part of Release 1. |

## Interview Record Template

| Field | Entry |
|---|---|
| Question ID | CV-XX |
| Stakeholder and role |  |
| Answer |  |
| Classification | Confirmed fact / policy decision / hypothesis / unknown |
| Evidence source | Report, query, SOP, case ID, or owner statement |
| Decision owner |  |
| Effective date |  |
| Follow-up owner and due date |  |
| Impacted requirement or metric |  |

## Completion Criteria

- PP-01 quantified: measured baselines, targets, and deadlines behind the analyst bottleneck.
- Real-time and post-event inputs, bands, and actions independently testable, including post-confirmation case creation (PP-02).
- Passenger recovery, driver evidence, sanctions, appeals, privacy, and audit rules approved within PP-03 risk bounds.
- Cost/effort envelope accepted by stakeholders (PP-04).
- Remaining assumptions and unanswered questions have named owners and deadlines.

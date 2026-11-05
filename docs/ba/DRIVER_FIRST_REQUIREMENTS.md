# Driver-first resolution and Analyst workspace extension

## Authority and delivery boundary

Version `driver-first-v1`, dated 2026-10-05. Pham Thanh Dat (@datamonsterr) approved the lifecycle rules and scheduled this expansion in the saved session. [Issue #147](https://github.com/AI20K-Build-Phase-Cohort-4/GreenSentinel/issues/147) holds approval evidence and delivery acceptance. The [PRD](PRD.md) and [MVP](MVP.md) retain the adopted 2026-09-30 Analyst baseline; this extension supersedes Driver deferral and the requirement for Analyst involvement in **Driver-confirmed resolution only**. Analyst dismissal, exoneration and every adverse sanction still require authorized Analyst confirmation with rationale. No model score or silence authorizes closure or a sanction.

These requirements authorize implementation, not a claim that the inherited runtime already conforms. Existing Driver transports are reusable seams; autonomous `auto_dismissed` behavior from historical [PR #40](https://github.com/AI20K-Build-Phase-Cohort-4/GreenSentinel/pull/40) remains superseded. The old mobile upload and blinded appeal proposals are not automatically scheduled by this desktop Driver conversation extension. Tester UI implementation remains queued; its specifications and isolation requirements remain applicable.

## Lifecycle contract

| ID | Required behavior |
|---|---|
| `FR-DF-01` | A detected case enters Driver assistance before active Analyst triage. Read the case and send the Driver an evidence-grounded summary through the existing inbox. Await their explanation or request; retrieve relevant evidence and policy in response. |
| `FR-DF-02` | Store classifier confidence in [0,1], `score_semantics=uncalibrated_model_confidence`, model/prompt/version and evidence references. Confidence concerns suspected Driver violation; it is not measured guilt probability or accuracy. Missing, invalid or exactly 0.5 confidence escalates. |
| `FR-DF-03` | With confidence strictly `> 0.5`, ask whether the Driver still wants to appeal. **No further appeal** explicitly closes as **Driver confirmed resolution**; **Continue appeal** escalates to the fraud Analyst. The comparison is not `>= 0.5`. |
| `FR-DF-04` | With confidence `< 0.5` and a reasonable explanation, ask for explicit Driver confirmation before closing. An unreasonable explanation escalates. The grounded criterion for a reasonable explanation is an open decision below, not an inferred model capability. |
| `FR-DF-05` | At a valid confirmation step, explicit Driver confirmation is sufficient for resolution even if evidence remains missing or conflicting. Retain those gaps and the actor confirmation. Resolution never asserts exoneration, confirmed innocence or an executed sanction. Boundary/error escalation takes precedence over entering this step. |
| `FR-DF-06` | No reply/offline after the successfully delivered confirmation question permits 48 hours, then escalates automatically. Record the question delivery time and deadline durably. Delivery failure escalates; it does not start a fictional successful-delivery clock. |
| `FR-DF-07` | Model, tool or delivery failure before confirmation escalates. Do not treat a successful tool's disclosed missing evidence as proof of innocence or silently relabel a failure as successful retrieval. Preserve the actual error and evidence provenance. |
| `FR-DF-08` | Late confirmation cannot close an already escalated case. Only an authorized Analyst can reopen. Serialize confirmation, deadline and escalation races, retain the winning transition and record late replies without changing the disposition. |
| `FR-DF-09` | Active Analyst triage begins after escalation. Available and My Cases contain appropriate nonterminal Analyst work; resolved cases remain in authorized history with evidence, dialogue, actor, confirmation, decision and audit. Analyst sanctions retain existing role restrictions and technical guardrails. |

**US-DF-01:** As the assigned Driver, I want to understand the case and answer an evidence-grounded question so that I can explicitly accept resolution or ask for Analyst review. Given a valid confirmation question and my owned authenticated session, when I select No further appeal, the case records Driver confirmed resolution. Given escalation already committed, the same reply is retained without closing the case.

**UC-DF-01:** Detect → persist case → deliver summary → receive explanation/request → retrieve evidence/policy → evaluate the boundary/error rules → ask confirmation or escalate → persist explicit resolution or Analyst handoff. A delivered confirmation question with no response escalates after 48 hours. Reconnect/retry restores durable conversation and deadline rather than rerunning an already committed outcome. No response timeout before the confirmation question is invented by this specification.

## Remaining workspace defaults

| ID | Approved contract |
|---|---|
| `FR-WS-01` | Analyst chatbot context reset is an unchecked, explicit checkbox applying to one message. Remove prior conversational history from that model request; retain case context and stored conversation/audit. Reset is not deletion. |
| `FR-WS-02` | Search matches partial Driver name, Driver ID and vehicle registration/plate (biển số xe). “License number” does not mean driving-license number. Enforce the caller's organization and ownership before returning results or counts. |
| `FR-WS-03` | Processed-case history retains evidence, conversation, decision and audit; browsing history does not make a terminal case actionable. |
| `FR-WS-04` | Analytics and Profile/Audit use 7/30/90-day windows. Analysts see their own activity and organization aggregates; Managers see authorized team detail. Define numerator, denominator, time basis, source and unavailable state for every metric. No fabricated operational values. |
| `FR-WS-05` | Multiple roles grant only explicitly authorized permissions. Missing, revoked, expired or unverifiable identity/role denies protected access. Driver pages, API, SSE/replay, attachments and saved history use the same Driver/organization ownership boundary. Privileged role grants remain server-controlled. |
| `NFR-WS-01` | Committed queue updates reach other authorized Analyst sessions within 5 seconds. Concurrent claims have one winner; lease loss and expiry remove stale ownership without deleting history. |
| `FR-WS-06` | Revise the Emerald Sentinel cockpit in Stitch and obtain explicit visual approval, then generate Analytics and Analyst Profile/Audit in the same system before implementing those screens. Old PNGs and local drafts do not satisfy Stitch generation or approval. |

## Acceptance scenarios and proof

| ID | Observable acceptance | Required proof |
|---|---|---|
| `AC-DF-01` | Cases are absent from active Analyst triage before escalation and visible after committed handoff. | Actual detector/worker intake, persisted state and two authenticated browser sessions. |
| `AC-DF-02` | Confidence 0.49 with reasonable explanation requests confirmation; 0.50, missing/invalid confidence and unreasonable low-score explanation escalate; 0.51 requests the appeal choice. | Deterministic boundary and failure tests with recorded score semantics; no claim of calibration. |
| `AC-DF-03` | Explicit resolution retains missing/conflicting evidence and creates no exoneration or sanction. Continue appeal creates one handoff. Duplicate retries create no duplicate disposition. | Transactional integration tests plus independent database inspection. |
| `AC-DF-04` | A delivered question survives restart and escalates at 48 hours without a response; model/tool/delivery failure escalates without an invented successful question. | Controlled-clock tests, worker restart and persisted deadline checks. |
| `AC-DF-05` | Late confirmation cannot close escalated work. Driver cannot reopen; authorized Analyst reopening preserves history and actor identity. | Concurrent transition tests, role-negative API tests and browser reload/reconnect. |
| `AC-WS-01` | Reset is off by default, affects only one model request, retains case context and does not delete history/audit. | Model-input assertions, persisted history checks and browser submit/reload. |
| `AC-WS-02` | Partial identity/plate search respects role and organization, and processed history retains source evidence. | API/database pagination and negative-access tests plus browser search. |
| `AC-WS-03` | Windowed metrics derive from recorded data with documented definitions and unavailable states; Manager and Analyst permissions remain distinct. | Seeded isolated runs, independent source/count reconciliation and real Clerk role tests. |
| `AC-WS-04` | Cross-session queue changes appear within 5 seconds and no two sessions own the same live lease. | Two real sessions, competing claims and measured elapsed time. |

Specification checks validate these documents only. Runtime, database migrations, provider availability, hosted browser observations and final dev E2E remain separate evidence. The [architecture decision](../architecture/adr-018-driver-first-resolution.md) defines the transition boundary. [GitHub Issues](https://github.com/AI20K-Build-Phase-Cohort-4/GreenSentinel/issues) retain the native blockers and current DoD; this document is not a backlog.

## Known facts, inferences and open decisions

- **Confirmed:** the lifecycle and defaults above, expansion scheduled now, desktop Driver assistance, Analyst-only reset, exact two remaining screens, and queued Tester UI implementation.
- **Proposed, awaiting answer:** regard an explanation as reasonable only when available evidence supports it and confidence is below 0.5; uncertain or contradicted explanations escalate. This proposal must not silently override `FR-DF-05` for an already valid confirmation step. Owner: @datamonsterr, in #147.
- **Engineering inference:** persist delivery acknowledgment, deadline and transition version so restarts/retries/races can satisfy the approved behavior. This does not prescribe a new provider or claim one exists.
- **Unvalidated:** quantified improvement against operational baselines, classifier calibration, traffic-provider coverage/licensing and operator UAT. These require observed evidence; documentation cannot establish them.
- **Transition:** old Analyst-baseline acceptance tests still protect historical recommendation-only intake, Analyst confirmation and sanction controls. New tests must distinguish Driver-confirmed resolution from Analyst dismissal and exoneration rather than disabling the old controls globally. Deployment must identify its policy version; existing history cannot be rewritten into a new disposition.

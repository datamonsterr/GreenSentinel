# Discovery Findings — Tester Trip Simulation

> **Status:** Confirmed discovery draft · 2026-10-03
> **Method:** `ask-why-ba` elicitation by Phúc NT / BA Zone; analysis by Codex with stakeholder Dat (`@datamonsterr`, acting Tester)
> **Authority:** Product parent [#130](https://github.com/AI20K-Build-Phase-Cohort-4/GreenSentinel/issues/130), documentation child [#131](https://github.com/AI20K-Build-Phase-Cohort-4/GreenSentinel/issues/131)

## 1. Business Problem

The Tester currently spends about one day preparing, checking, and testing one trip: selecting locations in Google Maps, copying GPS coordinates, writing Python scripts, and editing the database to force failures. Sparse GPS does not show sufficient motion; off-road or in-river points and implausible trips undermine test confidence. The problem is slow, fragile, low-provenance test preparation for the actual detection, notification, dialogue, and case-assignment pipeline.

## 2. Business Goal

The confirmed stakeholder goal is approximately one minute to visually create a new trip ready for testing on the system, compared with the reported approximately one-day preparation process. The proposed acceptance measurement is composition to accepted basic-trip submission; that boundary, and the observed achievement of the target, still require validation. No delivery deadline or runtime completion is confirmed.

## 3. Stakeholders

| Role | Organisation | Interest |
|---|---|---|
| Acting Tester (`@datamonsterr`) | GreenSentinel / GreenSM project | Create, run, inspect, and repeat test trips quickly |
| Fraud Analyst | GreenSM operations | Receive assigned cases and review evidence |
| Product Owner | GreenSentinel | Accept scope and UAT evidence |
| Engineering / data owners | GreenSentinel | Preserve contracts, provenance, persistence, and operational safety |
| Passenger and Driver actors | Simulated workspace roles | Provide editable dialogue evidence and receive/respond to notifications |

## 4. Pain Points

- Preparation and validation take approximately one day per trip.
- Manual coordinate copying and database edits are error-prone and hard to audit.
- Sparse breadcrumbs fail to represent vehicle motion.
- Off-road, in-river, and otherwise implausible routes make tests unreliable.
- Existing canned examples do not meet the need for unrestricted, deliberate trip creation.

## 5. Root Causes

- **Confirmed process cause:** The reported test path separates manual map planning, coordinate copying, script generation and AI-assisted database changes. A test therefore requires coordinating multiple tools and inspecting the resulting inputs before it can be trusted.
- **Reported input-quality cause:** Samples produced by that workflow are too sparse and sometimes occupy implausible positions. This is stakeholder evidence about the current workaround, not a finding that the accepted road-aware generator from #63 is defective.
- **Hypotheses for engineering validation:** A shared editable plan, explicit cadence and spatial validation, consistent source/reference metrics and correlated run evidence could remove repeated manual reconstruction. Availability of these controls and downstream notification contracts must be audited before design lock; absence is not asserted across the entire system.

## 6. Functional Requirements

- **FR-TST-01** — Compose and persist vehicle origin, pickup, destination, route, speed, time, cadence, and temporal GPS positions.
- **FR-TST-02** — Review/edit the complete plan before execution; control the live run while retaining plan and runtime controls.
- **FR-TST-03** — Act as Passenger and Driver in one workspace; manually add/edit both dialogues; optional AI drafts are editable.
- **FR-TST-04** — Keep map and generation controls prominent; show actor regions and actual assessments/results distinctly.
- **FR-TST-05** — Show context-sensitive distance, driver-placement radius, remaining-distance, per-GPS reference, DAVI and ETA metrics during hover/selection and movement, with units and reference points.
- **FR-TST-06** — Select a past time, prioritize matching historical traffic where available, and let the Tester mark route segments and set congestion level/density independently on each segment.
- **FR-TST-07** — Persist/reload the whole trip and generated run data, including source/provenance and resulting Workplace assignment.
- **FR-TST-08** — Exercise actual suspected-violation detection, notifications, dialogue replies, and case assignment; AI remains advisory.

## 7. Non-functional Requirements

- **NFR-TST-01** — Target approximately one minute to compose and accept a basic trip; exclude full playback and detection-response latency from timing, pending validation.
- **NFR-TST-02** — Preserve and expose provenance for GPS, routes, traffic, simulation, dialogue drafts, model output, and run events.
- **NFR-TST-03** — Represent insufficient movement/context as unknown; never fabricate zero metrics or silently substitute traffic sources.
- **NFR-TST-04** — Keep interrupted/duplicate runs, role/storage mapping, notification contracts, evaluation leakage, and stochastic model behavior auditable.
- **NFR-TST-05** — Support unrestricted visual creation without requiring canned scenario selection.

## 8. Business Rules

- **BR-TST-01** — Build the whole plan before execution; live controls operate on the saved plan.
- **BR-TST-02** — Default GPS follows plausible roads with explicit temporal positions and sufficient cadence; deliberate abnormal GPS is allowed only with explicit fault/provenance labelling.
- **BR-TST-03** — Distinguish routing distance from geometric radius and identify units/reference points; omit DAVI when movement/context is insufficient.
- **BR-TST-04** — Historical traffic must state actual source/time. Simulated congestion must be visibly labelled and cannot masquerade as historical live traffic.
- **BR-TST-05** — AI assessments and dialogue drafts are advisory evidence. They never confirm guilt or trigger dismissal, fine, suspension, or another penalty.
- **BR-TST-06** — Test runs assign to the current Workplace; no TEST badge or separate Workplace is required.
- **BR-TST-07** — The current Workplace denotes the same application/assignment flow. Deployment/storage selection, simulated actor identities, reporting boundaries and permissions require a decision before run/notification integration. No live operational database target is selected by the no-badge requirement.
- **BR-TST-08** — Select and validate the default/minimum sampling profile with Engineering and the Tester before implementing the generator. Ordinary sample gaps must not exceed the configured interval; deliberate dropout/fault settings are recorded exceptions.

## 9. Constraints

- Phase 1 analyst adjudication remains the approved release baseline.
- This extension does not authorize Passenger or Driver production mobile work, chatbot products, or automated adjudication/penalties.
- General tools are unrestricted; the workflow must not force preset scenarios.
- No new traffic vendor commitment is made; provider, coverage, and licensing are unverified.
- Exact schema/API names are not defined here as implemented contracts.

## 10. Risks

| # | Risk | Likelihood | Impact | Mitigation |
|---|---|---:|---:|---|
| 1 | GPS defaults remain sparse or implausible | Medium | High | Validate road-following density and inspect generated traces in UAT |
| 2 | Historical traffic is unavailable or misrepresented | Medium | High | Expose source/time; label simulation; preserve unknowns |
| 3 | Duplicate/interrupted runs corrupt evidence | Medium | High | Define idempotency and recovery before acceptance |
| 4 | Model output leaks evaluation labels or varies across replay | Medium | Medium | Track provenance/version and decide replay policy |
| 5 | Role, notification, or storage contracts are missing | Medium | High | Assign owners and verify integration seams before design lock |
| 6 | Synthetic runs are mistaken for operational data because environment/reporting boundaries are unresolved | Medium | High | Decide target environment, simulated identities and reporting boundaries before integration; retain internal lineage without requiring a visible Workplace badge |

## 11. Assumptions

- “Approximately one minute” is the confirmed desired target, not a measured result.
- Timing starts at composition and ends at accepted basic-trip submission; playback and detection latency are excluded.
- The current Workplace has compatible assignment contracts for simulator-created inputs. The user explicitly wants those cases in the current Workplace without a required visible test label; compatibility still needs runtime proof.
- Notifications and actor dialogue can be represented in the same workspace, subject to contract verification.
- Operational UAT will determine cadence, defaults, references, persistence behavior, and traffic feasibility.

## 12. Dependencies

- Existing trip/GPS generation and detection pipeline.
- Routing and map provider capabilities, including historical traffic availability.
- Current Workplace case-assignment flow.
- Notification contracts and role/auth storage mapping.
- Persistence for trip plans, runs, dialogue, provenance, and assessments.
- Product Owner and Tester operational UAT.

## 13. Open Questions

- **Q-TST-01** — What exact start/stop events define the one-minute target? *(owner: Product Owner + Tester; needed by: UAT)*
- **Q-TST-02** — @datamonsterr selected a proposed one-second ordinary GPS cadence on 2026-10-04, with selectable slower cadence and explicit jump, offset/noise, and dropout controls. Engineering and Tester must validate representative trips and permitted ranges before generator implementation and acceptance; ordinary gaps must not exceed the configured interval. *(owner: Engineering + Tester; needed by: generator acceptance)*
- **Q-TST-03** — What is the exact radius center and reference for each per-GPS distance and DAVI metric? *(owner: Data/analytics; needed by: design)*
- **Q-TST-04** — Which historical traffic source, timestamp semantics, coverage, and licensing are acceptable? *(owner: Product + engineering; needed by: integration)*
- **Q-TST-05** — Environment resolved by @datamonsterr on 2026-10-04: isolated test storage and sandbox notification delivery, reusing the existing Workplace layout. Simulated identities, reporting separation and explicit Tester role provisioning still require implementation verification; no production database is authorized. *(owner: Product Owner + Engineering; needed by: run/notification integration)*
- **Q-TST-06** — What notification contracts are available, and what is in scope for this test workspace? *(owner: Engineering; needed by: integration)*
- **Q-TST-07** — How are evaluation leakage, interrupted/duplicate runs, replay/clone, and stochastic model outputs handled? *(owner: Product + engineering; needed by: UAT)*

## Acceptance Boundary

Requirements and targets above are specifications. They are not runtime completion or hosted/operational proof. Acceptance anchors are `FR-TST-01`–`08`, `NFR-TST-01`–`05`, and `AC-TST-01`–`08` in [PRD §11](PRD.md#11-tester-trip-simulation-extension). Operational UAT remains pending.

## Technical design follow-up — 2026-10-04

The stakeholder requested architecture and interface design using the current codebase, `/test` frontend/backend prefixes, all-use-case testing, and separate map/tools with Driver above Passenger on the left. They confirmed isolated test infrastructure and sandbox notification delivery. [Architecture](../architecture/TESTER_SIMULATION_ARCHITECTURE.md), [API contracts](../architecture/TESTER_API_SPECIFICATION.md), [UI preview](../design/tester-simulation/design.md), and [test strategy](../testing/TESTER_SIMULATION_TEST_STRATEGY.md) are reviewable designs; they do not establish delivered runtime functionality.

**Sampling/fault design baseline — 2026-10-04:** The stakeholder selected ordinary GPS every 1 second with slower cadence selectable and explicit jump, offset/noise, and dropout controls. This confirms the design baseline; representative-trip validation, permitted numeric ranges and diagnostic performance are not yet proved.

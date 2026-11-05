# Business Analysis Documentation Guide

## Scope

This directory contains evidence-backed business analysis for GreenSentinel fraud detection and Driver-Induced Cancellation (DIC) guardrails. GreenSM policy material is the initial corpus and example tenant. Facts, hypotheses, and validated decisions remain strictly auditable and distinguishable.

## Approved Phase 1 Baseline

**@datamonsterr adopted the strict [PRD release scope](PRD.md#1-document-control) on 2026-09-30** and approved metric, score, and optional top-k elaboration on 2026-10-02. Initial analyst adjudication is the core release flow. **CV-01 operational baseline confirmation and operator UAT remain pending.** Approval of scope does not complete operational validation.

Start with [PRD acceptance and test traceability](PRD.md#101-phase-1-acceptance-and-test-traceability), then [MVP completion criteria](MVP.md#7-acceptance-criteria-for-mvp-completion). Broader L06 discovery preserves future policy options. [V2 driver-agent discovery](DISCOVERY_POC_V2_DRIVER_AGENT.md#current-release-authority) is superseded/deferred; MERGED [PR #40](https://github.com/AI20K-Build-Phase-Cohort-4/P-063/pull/40) is historical runtime divergence, not scope approval. Runtime correction belongs to [#73](https://github.com/AI20K-Build-Phase-Cohort-4/P-063/issues/73), owned by [#86](https://github.com/AI20K-Build-Phase-Cohort-4/P-063/issues/86) / [#60](https://github.com/AI20K-Build-Phase-Cohort-4/P-063/issues/60).

---

## Scheduled Driver-first extension

The [2026-10-05 Driver-first and workspace requirements](DRIVER_FIRST_REQUIREMENTS.md) record @datamonsterr's approved lifecycle and scheduled expansion. [Domain terms](DRIVER_FIRST_GLOSSARY.md) distinguish explicit Driver-confirmed resolution from Analyst dismissal, exoneration and sanctions. This scoped exception supersedes historical Driver deferral and Analyst-only resolution; all Analyst sanctions and dismissals retain their original authority and rationale. Tester UI implementation remains queued, and the open reasonableness criterion is not silently accepted. Specification approval does not prove deployment or UAT.

## Core Artifacts

1. **Product Requirements & Problem Foundation**:
   - [`EXECUTIVE_BRIEF.md`](EXECUTIVE_BRIEF.md): One-page executive brief summarizing the core operational problem, dual crisis, end-to-end HITL solution, and target metrics in Vietnamese.
   - [`PRD.md`](PRD.md): Approved Phase 1 specification with `FR-01`–`FR-06`, `NFR-01`–`NFR-07`, metric definitions, and stable `AC-P1-...` acceptance/test traceability. [§11](PRD.md#11-tester-trip-simulation-extension) separately specifies the Tester extension with `FR-TST-01`–`08`, `NFR-TST-01`–`05` and `AC-TST-01`–`08`; implementation and Tester UAT remain pending.
   - [`CUSTOMER_INTERVIEW_GUIDE.md`](CUSTOMER_INTERVIEW_GUIDE.md): Priority stakeholder validation questions (`CV-01` to `CV-20`) for operations, legal, and dispatch leads.
   - [`DISCOVERY_LOG.md`](DISCOVERY_LOG.md): Structured log of observed operational bottlenecks, discovery evidence, and policy constraints.
   - [`DISCOVERY_TESTER_TRIP_SIMULATION.md`](DISCOVERY_TESTER_TRIP_SIMULATION.md): 2026-10-03 Tester discovery, approximately one-day preparation baseline, approximately one-minute desired target, confirmed controls, risks, assumptions and owned open questions. Cases use the existing Workplace without a required visible `TEST` label.

2. **Full-Flow Operational Specifications**:
   - [`USE_CASES.md`](USE_CASES.md): 9 use-case specifications; `UC-L06-04` is Phase 1 core. Others, including driver-agent `UC-L06-08/09`, are deferred. Specification self-checks are not runtime proof.
   - [`USER_STORIES.md`](USER_STORIES.md): 10 stories with Given-When-Then criteria; `US-L06-04` is Phase 1 core and driver-agent `US-L06-09/10` are deferred references.
   - [`DECISION_LOG.md`](DECISION_LOG.md): Comprehensive register of operational, legal, and algorithmic decision gates.

3. **Implementation Scoping**:
   - [`MVP.md`](MVP.md): Phase 1 MVP delivery boundary scoping down to **Epic 5 (Initial Adjudication)** and the **GreenSentinel Workplace — Fraud Analyst Adjudication Cockpit (WebApp)** for Demo Day; [§8](MVP.md#8-tester-trip-simulation-extension) specifies visual Tester tooling around that pipeline without expanding production mobile scope.

---

## Behavioral Invariants

- **Terminology:** Use `Passenger`, not `Customer`, for the ride-hailing rider.
- **Fraud Labeling:** Use `suspected DIC` prior to adjudication; use `confirmed fraud` only following an authorized human confirmation event.
- **Strict HITL Compliance:** All dismissals and adverse sanctions, including warnings, require authorized analyst confirmation plus written rationale (`NFR-01`). Algorithmic closure and penalization are deny-by-default.
- **Confidence:** Per-case classifier confidence is [0,1], with `score_semantics=uncalibrated_model_confidence` by default; it is not accuracy, guilt probability, or authority to act. Calibration requires separate held-out evidence and versioning.
- **Optional routes:** Top-k route alternatives await a scoped product decision; they are not Phase 1 Must, detector logic, or a score metric.

## Task tracking

Manage features, user stories, tasks, dependencies and acceptance in [GitHub Issues](https://github.com/AI20K-Build-Phase-Cohort-4/P-063/issues). Follow [CONTRIBUTING.md](../../CONTRIBUTING.md); do not maintain a Markdown backlog. Product specifications stay in this folder and are linked from issues.

## Tester technical design

The Tester extension is specified in [PRD §11](PRD.md#11-tester-trip-simulation-extension) and [MVP §8](MVP.md#8-tester-trip-simulation-extension). Implementation contracts live in [Tester architecture](../architecture/TESTER_SIMULATION_ARCHITECTURE.md), [API design](../architecture/TESTER_API_SPECIFICATION.md), [UI design and preview](../design/tester-simulation/design.md), and [test strategy](../testing/TESTER_SIMULATION_TEST_STRATEGY.md). [Tester glossary](TESTER_GLOSSARY.md) defines shared domain terms. These are design artifacts; GitHub Issues retain ownership, blockers and acceptance.

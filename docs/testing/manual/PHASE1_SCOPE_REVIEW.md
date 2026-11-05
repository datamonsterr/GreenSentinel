# Phase 1 Scope Reconciliation Review

This runbook reviews the documentation contract for [issue 72](https://github.com/AI20K-Build-Phase-Cohort-4/P-063/issues/72). It does not establish runtime, database, benchmark, UAT or hosted acceptance. The approved release scope and inherited implementation must remain distinguishable.

## Preconditions and commands

Use an isolated worktree, the project Python environment and the exact reviewed commit. Run from repository root:

```bash
.venv/bin/python -m pytest --noconftest -q tests/unit/docs
.venv/bin/ruff check src/ tests/
.venv/bin/ruff format --check src/ tests/
git diff --check
git diff --exit-code origin/main...HEAD -- src/ .github/workflows/
```

The documentation suite imports no application, model provider or database. Ordinary project/CI commands still discover it under `tests/`. Record the commit, commands, exit codes and artifact links. Passing this suite is documentation proof only.

## Review steps

1. Read [PRD release control](../../ba/PRD.md#1-document-control), [goals/non-goals](../../ba/PRD.md#5-goals-and-non-goals) and the [decision log](../../ba/DECISION_LOG.md). Confirm @datamonsterr's 2026-09-30 strict release choice and 2026-10-02 metric/score/route clarification. CV-01 and operator UAT must remain pending until independently accepted.
2. Compare PRD, [MVP](../../ba/MVP.md), [US-L06-04](../../ba/USER_STORIES.md#us-l06-04--decide-an-initial-enforcement-case-phase-1-mvp-core) and [UC-L06-04](../../ba/USE_CASES.md#uc-l06-04-adjudicate-initial-case-phase-1-mvp-golden-path). Every dismissal and adverse sanction needs authorized analyst confirmation with written rationale. System-error lockout includes Warning, Fine and Suspend; it recommends dismissal without closing the case.
3. Confirm the quality boundary: 27/30 fixed gold decisions fails; 28/30 passes. Each of three reviewers completes all 30 cases and is reported separately; pooling cannot hide a failing reviewer. Preserve the 100% guardrail condition and do not report this definition as a measured result.
4. Confirm confidence is raw, advisory and uncalibrated, distinct from accuracy, guilt probability and authorization. Any probability/calibration claim requires held-out evidence and its version. Route top-k remains optional pending scoped product approval, distinct from RAG retrieval top-k.
5. Review [architecture](../../architecture/ARCHITECTURE.md), [POC design](../../architecture/POC_DESIGN.md) and ADR-008/009/010. Old driver autonomy must be identifiable as superseded history. Driver mobile/appeal expansion remains deferred. PR #40's merged baseline and open #73/#86 runtime gap must be explicit; diagrams describe the approved gate rather than claim current runtime compliance.
6. Inspect [AC-P1-01–09 traceability](../../ba/PRD.md#101-phase-1-acceptance-and-test-traceability). Open requirement/story/use-case links and actual test functions. Obsolete auto-exoneration expectations remain labeled as divergent impact; documentation tests do not replace runtime proof. Check all relative files and heading anchors.
7. Confirm only documentation and its contracts changed, current-head CI is green, and the current-head Phoenix review has no outstanding actionable findings. Ask @datamonsterr to review the final PR; leave the PR open for that review.

## Evidence boundary

The [worklog](../../worklog/2026-10-02.md) and [journal](../../journal/JOURNAL.md#week-4-strict-phase-1-scope-reconciliation-2026-10-02) distinguish local documentation/mutation checks, inherited fixture checks and CI evidence. Documentation checks do not validate classifier quality, persistence, browser flows or deployments. Any inherited database/browser suites run by CI are reported separately from documentation proof and do not establish runtime dismissal compliance. Runtime dismissal remediation belongs to [issue 73](https://github.com/AI20K-Build-Phase-Cohort-4/P-063/issues/73) and its existing owner, not this review.

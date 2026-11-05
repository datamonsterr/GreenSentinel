# Issue 72 Verification Evidence

## Scope and tested revisions

[Issue 72](https://github.com/AI20K-Build-Phase-Cohort-4/GreenSentinel/issues/72) reconciles release documentation. [PR 98](https://github.com/AI20K-Build-Phase-Cohort-4/GreenSentinel/pull/98) remains open for @datamonsterr review. Approved scope was adopted on 2026-09-30; the metric/score/route elaboration was approved on 2026-10-02. The [PRD acceptance matrix](../ba/PRD.md#101-phase-1-acceptance-and-test-traceability) maps the source requirements and impacted tests.

The full-layer checkpoint below tests `51c5a73ca40fd32dd50b7264467722b07646f724`. Later metadata corrections mark every deferred story/use case with its future phase, preserve goals and heading anchors, and extend documentation contracts to 78 checks; subsequent upstream-provenance checks bring the final suite to 83. The final PR check links identify the latest tested head; a checkpoint result is not represented as a later-head result.

## Definition of done evidence

| Documentation outcome | Evidence and practical limit |
|---|---|
| Analyst confirmation and written rationale for dismissal/adverse sanctions; technical guardrails block adverse actions | PRD/MVP, core US-L06-04/UC-L06-04, DEC-P1-01 and scoped documentation contracts. No runtime change is implemented by this documentation PR; accepted upstream PR #93 supplies remediation and #73 full acceptance remains separate. |
| Consistent active release versus historical merged scope | BA documents, architecture/POC design, superseded ADR-008/009/010 and explicit future-phase metadata. PR #40 commit and #73/#86 runtime gap remain visible. |
| Strict >90% concordance, raw confidence and optional route alternatives | Three separate reviewers each complete 30 fixed-gold cases, minimum 28 matches; 27 fails. Raw confidence is advisory, not accuracy/probability/authority. Route and retrieval top-k remain distinct. This defines metrics, not measured benchmark quality. |
| Traceability, provenance, manual checks and attributed records | AC-P1-01–09 links verified source/test names; [manual review](manual/PHASE1_SCOPE_REVIEW.md), [daily worklog](../worklog/2026-10-02.md), [journal](../journal/JOURNAL.md). CV-01 and UAT stay pending. |
| Independent review and reproducible verification | Separate worker worktrees/PRs #96/#97; specification and quality reviews; final independent DoD audit; RED/GREEN and mutation checks described below. |

## Full-layer checkpoint

| Layer | Observed result | Reproduction / immutable evidence |
|---|---|---|
| Documentation contracts | 60 passed at checkpoint; 78 passed after deferred-metadata correction | `.venv/bin/python -m pytest --noconftest -q tests/unit/docs` |
| Ruff lint/format | Pass, including the owned Python files | `.venv/bin/ruff check src/ tests/`; `.venv/bin/ruff format --check src/ tests/` |
| Backend suite in CI | 502 passed, 11 skipped, 14 subtests | [successful unit job](https://github.com/AI20K-Build-Phase-Cohort-4/GreenSentinel/actions/runs/36984843041/job/110831888714), head `51c5a73` |
| Migrated/seeded CI database integration | 72 passed, 7 subtests | [integration job](https://github.com/AI20K-Build-Phase-Cohort-4/GreenSentinel/actions/runs/36984843041/job/110831886994) |
| Existing agent regressions in CI | 120 passed, 1 skipped, 7 subtests | Same integration job; do not infer live-model quality or PRD runtime conformance |
| Frontend unit/component suite | 114 passed across 17 files, isolated local worktree | `pnpm --dir src/webapp test` |
| Frontend TypeScript | Pass, isolated local worktree | `pnpm --dir src/webapp exec tsc --noEmit` |
| Browser E2E | 7/7 local fixture specs on unique port 34198; 7/7 CI specs after retry | `PORT=34198 pnpm --dir src/webapp test:e2e`; CI integration job above |
| Docker and Next production build | Pass in CI | [build job](https://github.com/AI20K-Build-Phase-Cohort-4/GreenSentinel/actions/runs/36984843041/job/110833240245), including six generated Next pages |
| Owned-file Python typing under actual local runtime | Pass for both documentation test modules | `.venv/bin/mypy --python-version 3.13 tests/unit/docs/` |
| Whitespace and local links | Pass; relative targets/heading contracts checked | `git diff --check`; documentation contract link tests and separate changed-document audit |
| Runtime/CI preservation | Application source, workflow configuration and dependency settings match main | `git diff --exit-code origin/main...HEAD -- src/ .github/workflows/ pyproject.toml uv.lock` |

The existing CI run completed successfully on attempt 2. Attempt 1 passed database/agent checks but the webserver exited before browser assertions. The first PR head also encountered an empty live-model reply; that unchanged test passed on the next head. Neither assertion was skipped, weakened or redefined to obtain a pass. Local tests use isolated worktrees and an unused browser port; no unrelated servers were killed.

## Review corrections and TDD proof

The initial tests reproduce inclusive 90% acceptance and active ADR automatic-dismissal authorization. Independent review then discovers a core-use-case warning lockout/rationale omission and invalid heading targets. Original use-case text produces two RED failures, an intentionally invalid anchor one RED failure, and restored documents pass.

Phoenix flags prose fragility. Normalization, numbered-section scoping and equivalent-word matching allow formatting variants to pass while 16 deliberate policy corruptions still fail; adoption date/author remain protected evidence. The purported `file:///` cockpit link does not exist on the reviewed head: POC_DESIGN uses a repository-relative target. The review response links tracked manual/worklog evidence.

Final DoD review catches unqualified future-priority metadata. Scoped tests reproduce 13 RED failures before the minimal metadata correction. All non-core stories/use cases now explicitly remain deferred; the core use case remains Phase 1 Must. Heading anchors and story/use-case goals are preserved; the full documentation suite passes 78 checks.

## Existing broader-check limits

- `bash scripts/check.sh` stops at Mypy: installed NumPy stubs use a Python 3.12 `type` statement while the repository config targets Python 3.11. The exact error is `Type statement is only supported in Python 3.12 and greater`. This unchanged dependency/configuration problem prevents claiming a passing repository-wide local check script. The owned modules pass with the actual Python 3.13 runtime override; that does not prove Python 3.11 dependency compatibility.
- Global frontend ESLint reports 38 errors and 116 warnings in unchanged application files, including existing React rules at `app/workplace/page.tsx`. No blanket suppressions or unrelated product cleanup were added. This PR does not claim global ESLint is green.
- Local Next build reports `Could not parse output from TypeScript's --showConfig`. Investigation reproduces valid direct compiler JSON but zero-byte stdout from the equivalent piped child process. CI builds the same application successfully; local process-environment failure is reported separately.
- No classifier calibration/benchmark, operator UAT, production deployment or authenticated hosted-browser acceptance was performed for this documentation issue. CI/local fixtures do not resolve the existing automatic-dismissal gap or establish database audit immutability. Deployment workflows are path-filtered for this docs-only diff; their absence is not a deployment pass.


## Accepted upstream integration

While this PR awaited final checks, current main advanced to accepted [PR #93](https://github.com/AI20K-Build-Phase-Cohort-4/GreenSentinel/pull/93), commit `16c1ad6bdc910badbe852418bc5de5b456759156`. Both contributors' journal and daily worklog sections are retained through conflict resolution. Active architecture notices now distinguish the old PR #40 automatic-dismissal behavior from PR #93's recommendation-only transition and readable legacy records. Issue #73 remains open and is not closed by inference. New documentation contracts reproduce five stale-notice failures before the correction. Traceability links follow the renamed current tests while obsolete test identities remain immutable historical references.

Earlier full-layer counts above are explicitly the `51c5a73` checkpoint and are not presented as proof of the enlarged upstream runtime. The final PR's exact-head CI separately runs the accepted runtime, updated documentation contracts, migrated database, browser and build layers. This PR adds no application, migration, dependency or CI changes relative to current main.

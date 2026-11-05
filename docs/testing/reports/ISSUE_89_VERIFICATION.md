# Issue 89 test organization verification

Base: `origin/main` at `f175f96`; independent from unmerged PR #87. CI workflow files remain byte-identical to the base. Test code moves preserve existing assertions and behavior; active runbooks and concise agent instructions now use the central test guide.

Observed parent verification:

| Boundary | Result |
|---|---|
| Python test inventory | All 399 original test functions retained; two meaningful isolation/tool-trace functions added |
| Pytest collection | 445 original cases; 447 after moves and added regressions |
| Fast isolated units | 199 passed, no skips |
| Required disposable-service integrations | 236 passed, no skips |
| Complete backend discovery | 444 passed; three explicit optional live-provider checks skipped |
| Frontend units | 113 passed in 17 files |
| Frontend unit and browser test TypeScript | Both passed; the old test config previously excluded all tests and failed with TS18003 |
| Combined existing frontend CI entry | Unit tests, test typechecks and seven browser cases passed |
| Production build / application TypeScript | Passed |
| Ruff / format / whitespace | Passed |

Python suites are now `tests/unit/`, `tests/integration/`, and `tests/e2e/backend/`; Playwright specs are all in `tests/e2e/browser/`. Browser framework imports resolve through a thin webapp support export, without a package-manager migration. Shared root resolution replaces directory-depth assumptions. The ordinary unit fixtures block backing-service access and keep provider flags offline. Live cases remain outside unit discovery.

New nested test discovery was verified with temporary unit/browser probes, including deliberate assertion failure propagation; probes were removed. Backend directory discovery and four stable runner entrypoints require the exact project interpreter, fail before setup if it is absent, and contain no per-filename lists. Required integration runs validate schema, Redis and Qdrant and use explicit disposable targets. Optional broad-collection skips are distinct from the zero-skip required integration proof.

`pnpm test:e2e` is the unchanged-YAML compatibility entry: units, unit/browser TypeScript, then browser E2E. `pnpm test` and `pnpm test:browser` remain isolated local commands. The test-specific typecheck now sees real tests; typed release/missingness fixture fields and Vitest matcher augmentation were corrected rather than suppressing errors. Accessible RTL queries, awaited user events and mock cleanup improve identified component tests without changing production UI.

Manual runbooks live in [manual/](../manual/README.md). The older POC v2 autonomous-dismissal walkthrough is marked historical, because current contributor rules require reviewer confirmation; this change does not implement deferred business/product reconciliation. Existing historical evidence keeps revision-pinned commands, with a current-layout pointer.

This is local fixture, service-backed API and browser evidence. No authenticated hosted or live-model acceptance is claimed. Current PR CI results are linked from the issue/PR after publication. Existing repository-wide NumPy/Mypy type-target debt is separate from the passed app/test TypeScript checks.

Final quality review removed generated TypeScript metadata and disabled test-config incremental output. A shared fixture basemap isolates the default fixture browser suite from third-party glyph outages; browser results do not claim live basemap/provider availability.

Final isolated-dependency combined frontend run passed 113 unit tests, unit/browser TypeScript and seven browser cases in 47.7 seconds using an explicit fixture basemap. Complete backend rerun passed 444 tests with three optional live-provider skips after ordinary graph tests were isolated from live model calls.

Final rebase onto main `241e161` preserves linear history, all 526 current-main Python test functions, and six additional isolation/configuration regressions. New upstream Phase 1 document links now use canonical test locations; remaining security tests resolve the repository root explicitly. Upstream deletion of Drawio and its obsolete tests is retained. The complete fresh-database run passed **664 tests**, with four explicitly optional skips and 14 subtests. Frontend verification passed 126 unit tests, unit/browser TypeScript checks, all nine centralized browser cases and production build. Full branch diff checks and shell syntax checks found no conflict markers. The integration wrapper retains automatic directory discovery. No production Python/UI source or workflow YAML differs from the rebase target. Current-head PR CI is recorded separately after publication.

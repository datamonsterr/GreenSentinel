# Issue 61 verification audit — 2026-10-02

## Scope and initial findings

Audit target: PR #87 at `4e257d7`, including every approved #61 slice and its tests. The original seven scheduled PR checks passed, but that did not establish complete DoD: the workflow excluded the dedicated persisted GIS suite and did not run the full frontend unit suite. The issue also held both in-progress and in-review labels.

Independent reviews identified fabricated lifecycle milestones for cancelled or unknown trips; SQL/fixture lifecycle projection mismatch; focusable per-gap timeline chips contrary to the approved design; misleading `>30s` labels for shorter recorded outages; randomized mutation of the shared canonical browser case; and unsupported idempotency/performance claims.

## Repairs under verification

- Require recorded lifecycle timestamps and completion evidence for milestones. Preserve planned map checkpoints without presenting them as actual arrival/completion.
- Keep gap descriptions passive and referenced by the native scrubber, with exact duration and source-specific explanations.
- Reuse the dedicated seeded GPS-unavailable case; browser gap tests no longer append random events to the canonical trip.
- Add non-skipped persisted GIS and full frontend unit gates before CI build, with isolated database naming and retained failure artifacts.
- Compare fingerprints of all app tables across repeated setup. Two green browser runs alone are not idempotency proof.
- Measure warm-application case selection from the real click to rendered expected routes and persisted observed GPS, retaining JSON measurement attachments. This does not establish cold startup or hosted performance.
- Restore the Python 3.11 type-checking target to match the supported minimum runtime. Raising the target did not make the full type gate pass; existing NumPy stub/type debt remains separate.

## Evidence boundaries

Original local fixture tests: 162 frontend tests and 20 focused backend tests passed on the unmodified PR head. Revised verification is recorded below only after complete commands finish. The original 1155/1273 ms resource-timing values and unqualified repeat-run idempotency claim are superseded by the revised measurement and fingerprint checks.

Hosted preview workflow success is deployment-automation evidence, not authenticated hosted GIS acceptance. No merge is authorized or performed by this audit.


## Fresh verification results

| Gate | Observed result | Evidence |
|---|---|---|
| Complete backend suite with isolated database and opt-in integrations | 497 passed, two optional live-provider checks skipped, 14 subtests passed | [Backend output](assets/issue61-audit/backend-summary.log) |
| Complete frontend unit suite | 166 passed in 19 files | [Frontend output](assets/issue61-audit/frontend-summary.log) |
| Persisted API/browser suite | Six passed on fresh database and six passed on complete repeat | [Fresh](assets/issue61-audit/persisted-fresh-summary.log), [repeat](assets/issue61-audit/persisted-repeat-summary.log) |
| Database preservation | All 40 app-table row counts and content hashes identical across complete repeat; repeated setup also enforces this in CI | [Before](assets/issue61-audit/database-before.json), [after](assets/issue61-audit/database-after.json) |
| Production build and TypeScript | Both passed | [Build output](assets/issue61-audit/build-summary.log) |
| Scoped ESLint | Zero errors, 38 warnings across map component, gap tests and persisted spec; original component had 32 render-time ref errors | Direct scoped command |
| Ruff / format / whitespace | Passed for source, tests and GIS setup helper | Direct repository commands |
| Repository check script | Stops at existing NumPy stub syntax under configured Python 3.11 target; backend tests were run independently | Explicit remaining limitation |

Warm application case selection measured **650 ms fresh** and **875.5 ms repeat** against a 1500 ms budget. Measurement begins at the target click, rejects the previous map, and requires both expected routes and the persisted observed GPS coordinate to render. This is a defined local warm-selection measurement with offline basemap, not cold application startup or hosted performance. [Actual repeated-run JSON attachment](assets/issue61-audit/render-budget-repeat.json) records environment and measurement.

The revised real persisted browser flow captures [desktop](assets/issue61-audit/gap-desktop.png) and [375 px mobile](assets/issue61-audit/gap-mobile.png) states and [200% desktop layout zoom](assets/issue61-audit/gap-zoom.png). It checks real pointer scrubbing, Home/End/arrow keys, pointer pan and wheel zoom with camera retention during replay, source restoration after page reload, reduced-motion operation, native scrubber hit testing/accessible description, zero added gap tab stops, and no horizontal mobile overflow. Vertical scrolling at 200% remains allowed. [Manual test steps](ISSUE_61_MANUAL_TESTS.md) cover reviewer follow-up and separate hosted acceptance.

## Test quality and DoD assessment

The repaired tests use independent source lifecycle/fixture expectations instead of penultimate-sample guesses, exercise cancelled and invalid lifecycle values, preserve exact fractional gap duration, and verify real MapLibre sources rather than SVG-only fallback elements. Missingness with a known recorded terminal boundary is covered; unknown ends remain unknown. Browser cases no longer contaminate the shared canonical scenario with randomized events. Full database seed checks now honor the explicitly supplied proof database instead of silently preferring another migration URL. The two backend skips are explicitly optional live Gemini/OpenRouter coverage. Default driver graph tests now use a scripted model and execute the real ToolNode; missing or placeholder credentials cannot select an embedded fallback key.

The five issue DoD outcomes have local fixture and persisted evidence, including distinct routes, timestamp replay, non-bridging gaps, and unavailable routing/GPS/traffic. The previously missing persisted and full Vitest CI steps are now configured as required predecessors of build and retain artifacts. At the local audit snapshot, published-revision CI had not yet run; subsequent results are recorded in [PR #87 checks](https://github.com/AI20K-Build-Phase-Cohort-4/P-063/pull/87/checks). Green checks from the original head do not prove the new gates ran. Authenticated hosted GIS acceptance remains unverified.


## Consolidated workspace and final browser proof

On 2026-10-02, the user requested consolidation into `P-063-worktrees/issue-61`. The current branch was fast-forwarded from `f175f96` to PR #87's `4e257d7` baseline; all 25 audit files were compared byte-for-byte after migration. Approved design assets were confirmed against `44a7b64`; the PR's later explicit approval record was retained. Twelve obsolete Issue 61 worktrees, including the nested T3 checkout and detached baseline review, were removed only after private archives and a verified Git branch bundle were created. Other issue worktrees and all source branches were preserved. Recovery records live outside the public repository in the permission-restricted sibling `.issue61-worktree-archive-20261002`.

The final expanded persisted suite passed six tests in 42.1 seconds using the initialized isolated database `issue61_audit_final20261002`. Repeat setup enforced identical fingerprints across all 40 app tables. The corrected warm-selection measurement was **1221 ms**, below 1500 ms. [Current browser output](assets/issue61-audit/persisted-current-summary.log) and [measurement JSON](assets/issue61-audit/render-budget-current.json) include the exact local measurement definition. A completely fresh migrated database `issue61_delivery20261002` then passed the expanded six-test suite in 39.5 seconds, measuring **775 ms**. The [fresh output](assets/issue61-audit/persisted-fresh-summary.log) records this final scope.

Both runtime OSRM adapter calls also succeeded against the actual public provider using labeled synthetic inputs: pickup and destination returned 394 and 410 coordinates respectively. [Provider proof](assets/issue61-audit/live-osrm.json) records distance, duration, provenance and timing. These are routing estimates, not observed traffic or shortest-distance proof. [OSRM's route-service definition](https://project-osrm.org/docs/v5.24.0/api/) identifies the service as a fastest-route calculation.

A direct SQL-backed lifecycle comparison used persisted cancelled case `018f2f4e-a000-7000-8000-000000000001` and completed case `018f2f4e-a000-7000-8000-000000000026`. Cancelled evidence retained measured start/stall events without invented completion; completed pickup/dropoff values matched assignment lifecycle timestamps. [Persisted lifecycle proof](assets/issue61-audit/persisted-lifecycle.json) records the source comparison. Invalid lifecycle chronology suppresses only invalid lifecycle milestones and preserves independent measured GPS/stall evidence.

The initial complete-suite rerun exposed three fixture tests that accidentally used configured SQL data and an unrelated live-model test with a nondeterministic empty reply. Fixture tests now explicitly isolate the in-memory connection boundary, including with a database URL configured. Default driver tests use deterministic model responses with real tool execution and independent policy-result assertions; live-provider checks require explicit opt-in. A pre-existing embedded credential fallback was removed. Credential rotation and historical-secret remediation require the credential owner's separate security action and are not claimed complete here.


The final complete backend suite passed **497 tests** with **14 subtests**; only the two explicitly optional live-provider tests were skipped. Independent policy regressions retain all three articles (12.1, 12.2 and 12.3), and scripted graph tests verify successful actual tool payloads rather than merely matching fake final text. Full frontend verification passed **166 tests in 19 files**, TypeScript and production build passed, and scoped ESLint reported zero errors with 38 existing/style warnings. Ruff checked/formatted all 103 relevant Python files. The repository-wide script still stops at the explicitly recorded NumPy stub parser error for the supported Python 3.11 target; [type audit](assets/issue61-audit/type-audit.txt) distinguishes that pre-existing gate from passed behavioral suites.


The complete expanded runner then passed all six tests again in **38.7 seconds** on `issue61_delivery20261002`, measuring **882 ms**. All 40 app-table counts and content hashes matched the pre-repeat snapshot. [Repeat browser output](assets/issue61-audit/persisted-repeat-summary.log), [measurement](assets/issue61-audit/render-budget-repeat.json), and the before/after database snapshots record the final consolidated scope. The desktop/mobile/zoom screenshots above come from this completed run.

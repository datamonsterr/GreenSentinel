> Historical, revision-pinned evidence. Commands below use paths from the tested revision. For the current layout, use [the test guide](README.md); the persistence suite is now `tests/integration/services/test_road_dataset_integration.py`.

# Issue #63 verification record

This record covers the approved road telemetry feature in an isolated `feat/63` worktree. [Issue #63](https://github.com/AI20K-Build-Phase-Cohort-4/P-063/issues/63) owns acceptance criteria. The canonical corpus is synthetic; captured OSRM road geometry supplies routing evidence, not live GPS or traffic observations.

## Environment and reproducibility

The local backend uses Python 3.13.13, a fresh PostgreSQL 16/PostGIS 3.4 disposable database with the repository migrations, an isolated Redis instance, and an isolated Qdrant instance. Credentials stay outside the repository and are omitted here. Generator base seed is `42`; each effective seed is derived from sorted case identity and recorded in the case manifest and route provenance. The simulated UTC clock begins at `2026-09-22T06:00:00Z`.

Checks were captured on 2026-10-01 against production implementation revision `8a1c53d5753037e33eb50b0b756edbb646839574`. The full backend suite was rerun after the test-fixture repair in `ac88a86db1f84192936624b1efeb3001e441e56a` and again passed with 444 tests and one skip. Browser verification used a separate freshly migrated/seeded database so test mutations could not supply browser evidence. That browser database contained 100 cases, 200 route snapshots, 17,972 telemetry samples, 15 synthetic traffic records, and 30 technical incidents.

The pinned [normal artifact](../../tests/fixtures/road_telemetry/normal_trip.json) is shared by public API ingestion, GIS unit contracts, and browser tests. [OSRM capture provenance](../../tests/fixtures/road_telemetry/PROVENANCE.json) and [directed-away provenance](../../tests/fixtures/road_telemetry/PROVENANCE_actual_away.json) remain explicit. Map version is unknown when the captured provider did not report it. OSRM fastest routes are not labeled shortest paths.

## Observed checks

| Boundary | Command or procedure | Observed result |
|---|---|---|
| Corpus | `.venv/bin/python -m scripts.road_dataset --validate` | All 100 cases validate; five scenario families; current shared artifact equals generator output |
| Isolated database | `ISSUE63_DATABASE_URL=<isolated-url> .venv/bin/pytest tests/test_services/test_road_dataset_integration.py -q` | Preserving repeat seed, 200 route legs, typed synthetic traffic, dropout incidents, ingestion/replay/conflict and case API round-trip |
| Backend suite | Explicit isolated database/Redis/Qdrant environment, `.venv/bin/pytest tests/ -q --tb=short` | 444 passed, 1 skipped; 14 subtests passed. One environment-dependent test is skipped; this does not provide live-agent acceptance evidence. |
| Python quality | Ruff check/format on `src/`, `tests/`, and changed generator modules | Pass |
| Scoped types | `.venv/bin/mypy --explicit-package-bases scripts/road_trip_generator.py scripts/road_dataset.py scripts/road_scenarios.py` | Pass, three modules |
| Repository gate | `bash scripts/check.sh` | Lint/format pass; Mypy stops on NumPy stubs under configured Python 3.11 target: `Type statement is only supported in Python 3.12 and greater` at `numpy/__init__.pyi:737`. The separate isolated pytest run reports backend results |
| Frontend suite | `pnpm --prefix src/webapp test` | Feedback rerun: 113 tests pass across 17 files |
| Frontend types/build | `pnpm --prefix src/webapp exec tsc --noEmit`; `pnpm --prefix src/webapp build` | Final checks pass; Webpack production output includes both MapLibre worker modules |
| Browser regression | `PORT=<dedicated-port> pnpm --prefix src/webapp exec playwright test` against the dedicated test-auth development server | Passive-mark rerun: 7 passed in 24.6 seconds; canonical routes render, exact GPS fixes retain source speed/coordinates, icons have fixed dimensions, and between-fix motion stays bounded on the road with a stable camera |
| Agent-browser | Dedicated local Next.js test-auth server connected to the real isolated FastAPI service; navigate, select cases, inspect map sources, scrub, capture screenshots | Stall, traffic, and dropout cases pass route, rendered-feature, position, and speed comparisons against stored API evidence; live OpenFreeMap basemap |
| Hosted | No deployment/revision browser check performed | Unverified; local results make no hosted/auth-provider acceptance claim |

The database proof uses case suffixes `000000000001` (stall), `000000000002` (directed away), `000000000026` (traffic), `000000000041` (dropout), and `000000000081` (normal), prefixed by `018f2f4e-a000-7000-8000-`. Canonical fixture ingestion adds one isolated case with its own stable UUID; the generated demo corpus remains 100 cases.

Captured local output: [backend suite](assets/issue63/backend-pytest.log), [frontend suite](assets/issue63/vitest.log), [Playwright](assets/issue63/playwright.log), and [production build](assets/issue63/production-build.log). These are local results; PR checks provide separate CI evidence.

## Browser procedure and evidence boundary

Use [the manual runbook](MANUAL_TESTS.md). Start a dedicated backend with `APP_ENV=test` and a dedicated frontend with the existing `E2E_TEST=true` / `NEXT_PUBLIC_E2E_TEST=true` controls. Point `API_BASE_URL` and `NEXT_PUBLIC_API_URL` at that backend. Authentication-provider behavior is excluded from this local test mode.

With `agent-browser --session issue63-road`, open `/workplace`, inspect the accessibility snapshot, scroll the target queue button into view, click it, and inspect actual MapLibre layers. Compare route coordinates with the case API's route objects, not guessed geometry. Focus the timeline range and use keyboard navigation; compare the driver point and displayed speed with the matching persisted telemetry sample. Capture screenshots only after route sources report loaded and rendered features are present. Merely populated sources do not constitute pixel proof.

During investigation, MapLibre worker assets failed to resolve through the bundler, which left source requests pending and the canvas blank. A minimal offline style isolated evidence layers. The committed Playwright regression uses this background-only style and intercepted fixture API responses; it verifies actual MapLibre rendering without claiming database-backed evidence. The final agent-browser captures use the real isolated API/database and the live OpenFreeMap basemap.

| Agent-browser case | Observed checks | Screenshot and machine record |
|---|---|---|
| Stall `…0001` | 98 samples; both route sources loaded; two rendered route features; scrub `963` seconds; position `[105.783595, 21.016748]` and `37.5 km/h` match the final stored observation. Selection remains stable across case refreshes. | [Screenshot](assets/issue63/stalled-scrub.png), [record](assets/issue63/stalled-browser-proof.json) |
| Synthetic traffic `…0026` | 244 samples; both route sources loaded; two rendered route features; scrub `4345` seconds; position `[105.808248, 21.224355]` and `33.6 km/h` match the final stored observation. | [Screenshot](assets/issue63/traffic-scrub.png), [record](assets/issue63/traffic-browser-proof.json) |
| Technical dropout `…0048` | 74 samples; an observed `59.966`-second gap remains; both route sources loaded; two rendered route features; scrub `773` seconds; position `[105.783595, 21.016748]` and `37.7 km/h` match the final stored observation. | [Screenshot](assets/issue63/dropout-scrub.png), [record](assets/issue63/dropout-browser-proof.json) |

The browser error collection was empty after these checks. This does not establish provider uptime or hosted authentication behavior. Planned destination geometry remains visible for cancelled trips; cancellation scenarios do not acquire a completed ride lifecycle.

## Review repairs

Regression tests were observed failing before repairs for endpoint/envelope replay, relationship integrity, malformed timestamps/route metadata, undeclared gaps, omitted destination observations, source-order-dependent seeds, and evaluation-label guardrails. Final review also corrected finite-coordinate sanitization while preserving the existing list input shape. Stale mock cursors were updated to model successful `RETURNING event_id`; production collision handling remains strict.

The rendered-browser check additionally repaired MapLibre 6 worker/shared-module emission and timeline resets on fresh case responses. Development and production use Webpack for this module pipeline. Next.js 16 generated page types also required the existing dispute page's `params` to be a promise. The production build passes with existing Clerk/Next Edge-runtime warnings.

The first published CI run exposed an expired fixed deadline in the legacy driver API smoke test. A database-unavailable fixture run reproduced `dispute_status="closed"` before the old dismissal assertion. The test now uses a relative two-day deadline and explicitly selects its required case rather than falling back to arbitrary evidence. That smoke passes in both fixture and isolated-database modes. Its existing automatic-dismissal assertions describe the inherited baseline; [issue #73](https://github.com/AI20K-Build-Phase-Cohort-4/P-063/issues/73) owns analyst-confirmation conformance. They are not PRD acceptance evidence.

Published CI results are linked from [PR #82](https://github.com/AI20K-Build-Phase-Cohort-4/P-063/pull/82). On revision `ac88a86`, [core CI](https://github.com/AI20K-Build-Phase-Cohort-4/P-063/actions/runs/36811980637) passed lint, unit tests, migrated Docker integration, agent checks, Playwright, and backend/frontend builds. [Railway preview automation](https://github.com/AI20K-Build-Phase-Cohort-4/P-063/actions/runs/36811980689) passed. The first Vercel preview attempt stopped before build with `The token provided via --token argument is not valid`; [the later retry](https://github.com/AI20K-Build-Phase-Cohort-4/P-063/actions/runs/36811980610) succeeded. Preview automation alone does not establish hosted dataset or browser acceptance. PR checks remain the current authority for subsequent documentation revisions.

AGY launch failed with `project: create projects dir /home/dat/.gemini/config/projects: mkdir /home/dat/.gemini/config: file exists`. Native workers implemented the bounded tasks instead. No AGY execution, production evidence, sanctions, merge, or downstream feature completion is claimed.

## Playback and checkpoint feedback verification — 2026-10-01

The earlier end-of-trip checks missed behavior between GPS samples. Four failing regressions reproduced future-fix jumps, missing-gap interpolation, road-corner skipping, and implicit acceleration (100 recorded seconds per wall-clock second for a 2,400-second trip). The repair uses elapsed time at 1×, brackets observed samples, and interpolates by distance along the corresponding supplied route leg only within a 30-metre corridor, at most 30 seconds between fixes, and below 50 m/s. Interpolation is a labeled display estimate; stored GPS, model input, and persisted source speed remain unchanged. Exact observed timestamps return source positions/speed. Unmatched or missing intervals hold the labeled last known fix with unavailable speed; the orange road trail breaks while actual observations remain visible as individual dots. Duplicate timestamps are not called GPS loss.

One camera fit includes both planned route legs and all observations. Playback preserves a manually adjusted view and no longer reloads unchanged routes every frame. Starting point, customer pickup, destination, and driver use circle/person/flag/actual-vehicle icons. Car and motorbike carriers are both 28px; checkpoints are 24px; timeline carriers are 20px with 14px glyphs. Actual `car`, `bike`, `motorbike`, `Green SM Car`, and `Green SM Bike` values are allowlisted; absent/unsupported types remain neutral. Dense timeline events use grouped native controls and exact event times. Overlapping static map badges use dashed visual leaders; their geographic coordinates remain unchanged and the moving driver stays centered at its displayed coordinate.

The [local design preview](../design/issue63-playback-checkpoints/design.md) was presented before icon coding. The user subsequently instructed completion of all remaining work. Stitch was unavailable; the preview is local HTML/SVG and is not claimed as Stitch generation.

Fresh checks include the complete isolated backend run: **444 passed, 1 skipped, 14 subtests passed in 155.02 seconds**, with opt-in persistence enabled. Frontend: **113 passed in 17 files**, TypeScript and scoped new-module ESLint pass, and **7 Playwright tests pass in 34.6 seconds**. The existing repository Mypy gate still stops on NumPy's Python 3.12 `type` syntax under its configured Python 3.11 target; scoped generator types pass. These checks use the feedback implementation on `feat/63`; the PR's current head identifies its published revision.

| Agent-browser check | Observed result | Evidence |
|---|---|---|
| Continuous traffic playback, case `…0026` | 31 frames over 4.6086 seconds; cursor advances 4.647 seconds (1.0083×); maximum frame displacement 1.6685m; maximum route separation 0.0010m; camera unchanged; both route sources loaded and two rendered route features. Driver uses actual `car` metadata at 28px, with circle/person/flag checkpoints at 24px. | [Machine record](assets/issue63/motion-browser-proof.json), [screenshot](assets/issue63/motion-playback.png) |
| Mid-gap dropout, case `…0048` | At second 69.247 inside an actual 59.966-second gap, driver remains at last measured `[105.8521993, 21.03185]`; mode `gap`, speed unavailable, five preceding GPS observations retained. | [Machine record](assets/issue63/dropout-playback-proof.json), [screenshot](assets/issue63/dropout-playback.png) |

Agent-browser uses the real isolated API/database and live OpenFreeMap. Playwright uses intercepted canonical API fixtures and an offline background style. Neither provides hosted authentication-provider acceptance. Two delegated workers hit a usage limit; the conductor completed their unfinished integration and reran verification. Review and merge remain separate from implementation evidence.

Narrow-screen agent-browser verification at 375px confirms no map/document horizontal overflow, the actual motorbike icon, fixed carrier sizes, named dense-group members, and a group panel within map bounds: [record](assets/issue63/checkpoints-mobile-proof.json), [screenshot](assets/issue63/checkpoints-mobile.png).

Independent final review found that a first observation without a leg could choose another road despite the next fix recording `destination`. A failing curved-route regression reproduced that shortcut. Playback now uses the known leg from either endpoint and still rejects contradictory legs. The final rerun passes 113 frontend tests, TypeScript, scoped ESLint, and all seven Playwright tests in 34.6 seconds (including cold server startup). Backend source is unchanged from the isolated 444-pass run above.

## Passive timeline marks correction — 2026-10-01

The user explicitly removed the newly added timeline checkpoint/count buttons. The current timeline renders each event as a passive 2px by 12px tick directly on the native scrubber, at its exact timestamp-to-range percentage. There are no checkpoint action buttons, count groups, details panels or additional tab stops. Informational marks retain accessible role/time names and cannot intercept pointer dragging. Existing replay/pause, native seeking and map icons retain their behavior. The earlier group-control design and browser captures above are historical evidence, superseded for timeline presentation by this correction.

A failing regression reproduced the former checkpoint controls before replacement. The updated frontend suite passes **113 tests**, TypeScript passes, and **all seven Playwright tests pass in 24.6 seconds**. Browser regressions verify marks centered on the track, 2px width, no count/button/popover controls and continued native seeking; playback, road alignment and camera checks remain active. Backend source is unchanged from the isolated 444-pass verification.

Agent-browser checks the real isolated API/database at 1440px and 375px. Both views contain four source-timestamp marks, zero checkpoint controls, one existing replay/pause button, marks centered on the track, no additional tab stops and no horizontal overflow. Percentages use the scrubber's actual fractional bounds, with CSS serialization tolerance below 0.0001 percentage point. Evidence: [desktop record](assets/issue63/timeline-marks-desktop-proof.json), [desktop screenshot](assets/issue63/timeline-marks-desktop.png), [mobile record](assets/issue63/timeline-marks-mobile-proof.json), [mobile screenshot](assets/issue63/timeline-marks-mobile.png). This remains local test-auth evidence, not hosted acceptance.

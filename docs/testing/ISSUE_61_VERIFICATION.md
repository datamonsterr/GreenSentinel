# Issue #61 verification record

> Historical implementation record. The [2026-10-02 verification audit](ISSUE_61_AUDIT.md) supersedes the earlier performance, idempotency, lifecycle and CI completion claims below. Use the audit for current evidence and remaining limitations.

This record covers the GIS evidence outcome (S2-F04) in an isolated `feat/61-t3-integration` worktree. [Issue #61](https://github.com/AI20K-Build-Phase-Cohort-4/GreenSentinel/issues/61) owns acceptance criteria. The delivery renders driver origin, pickup and destination, the planned legal OSRM route, and the actual telemetry trajectory from backend responses. Labeled synthetic data is allowed through ingestion; route durations are never asserted as observed congestion.

## Environment and reproducibility

The local backend uses Python 3.13.13, a disposable PostgreSQL 16/PostGIS 3.4 database migrated from `db/migrations`, an isolated Redis instance, and an isolated Qdrant instance. The browser runner is Chromium on Linux 7.2.4-arch1-2 x64 with 12 CPUs. Credentials stay outside the repository and are omitted here. `OSRM_BASE_URL` is pinned to an unroutable loopback so missing route legs remain unavailable; no geometry is invented when the router cannot answer.

Checks were captured on 2026-10-02 against branch `feat/61-t3-integration`.

## Persisted gate

The persisted gate is [`scripts/test_gis_persisted.sh`](../../scripts/test_gis_persisted.sh). It requires the environment variables `ISSUE61_DATABASE_URL`, `REDIS_URL`, and `QDRANT_URL`. When any requirement is missing, the gate fails before migration with the recorded errors:

- `ERROR: ISSUE61_DATABASE_URL must be set and isolated for this test runner.`
- `ERROR: REDIS_URL and QDRANT_URL must be explicitly configured.`
- `ERROR: ISSUE61_DATABASE_URL must be an explicit loopback issue61_* database URL.`

Six Playwright tests run against the real migrated database through the FastAPI backend and the Next.js frontend. They passed on a fresh database named `issue61_t5final2` and passed again on a repeat rerun, so the gate is idempotent.

| Persisted scenario | Observed check |
|---|---|
| Canonical legs and scrub | All three points and both route legs render from backend responses; the planned legal OSRM route and the actual trajectory are visually distinct; timeline scrubbing moves the vehicle by timestamp |
| Gap indicator tooltip | Gaps over 30 seconds carry a dashed warning annotation with an explanatory time/reason tooltip, separate from measured travel |
| GPS and traffic absent states | Missing GPS and absent traffic display their explicit unavailable states |
| GPS-unavailable gap band | A GPS outage renders the unavailable band without bridging the interval as measured travel |
| Unavailable route leg | A missing route leg stays unavailable when `OSRM_BASE_URL` cannot route; no invented geometry is substituted |
| AC-MVP-02 render budget | Case-fetch-to-render completes within the budget |

## AC-MVP-02 render budget

The budget measurement detects a 16 ms in-page tick from case fetch through route legs and the cursor-driven trail render. Measured durations were 1155 ms on the fresh database and 1273 ms on the repeat run, both at or below the 1500 ms budget.

## Observed checks

| Boundary | Command or procedure | Observed result |
|---|---|---|
| Persisted database | `scripts/test_gis_persisted.sh` with `ISSUE61_DATABASE_URL`/`REDIS_URL`/`QDRANT_URL` set | 6 Playwright tests pass on fresh database `issue61_t5final2` and again on repeat rerun; the gate fails before migration when its required variables are missing |
| Frontend suite | `pnpm --prefix src/webapp test` | 162 passed across 19 files |
| Frontend types | `pnpm --prefix src/webapp exec tsc --noEmit` | Clean |
| Backend targeted | `APP_ENV=test` targeted suite | 20 passed, 7 skipped, including 16 passed in `tests/test_services/test_telemetry_routes_traffic.py` |
| Python quality | Ruff check on touched files | Clean |
| Hosted | No deployment/revision browser check performed | Not yet run; pending CI/hosted acceptance |

## Mypy/NumPy gate

The repository Mypy gate previously stopped on NumPy 2 stubs under a Python 3.11 target (`Type statement is only supported in Python 3.12 and greater`). The `pyproject.toml` `python_version` was bumped from 3.11 to 3.12 so the gate runs again. Issue #61 touched files are clean or improved against base `f175f96`: `case_service` reports 8 errors versus 10 on base, and `routing_service`, `route_analytics`, and `jev_precedent_service` report 0. The remaining approximately 100 errors in `src/rag/` and `src/agents/` are pre-existing debt outside issue #61.

## Lifecycle milestone honesty

Pickup and dropoff milestone timestamps now come from the recorded `arrived_at` and `ended_at` values, or from the first destination-leg fix when the leg label exists. The case API telemetry projection does not carry the ingest leg label, so lifecycle fields are pulled from `trip_assignments`. Playback therefore reports recorded lifecycle times instead of guessing them from the route.

## DoD mapping

| DoD item | Evidence file | Result |
|---|---|---|
| All three points and both route legs render from backend responses; legal expected route and actual trajectory are visually distinct | [`scripts/test_gis_persisted.sh`](../../scripts/test_gis_persisted.sh) canonical legs and scrub scenario; this record | Pass on fresh and repeated persisted runs |
| Timestamp-based replay follows stored telemetry; gaps over 30 seconds are explicit and are not bridged as measured travel | Gap indicator tooltip and GPS-unavailable gap band scenarios; missingness tests from T2 | Pass |
| Routing outage, missing GPS and absent traffic data display unavailable states; shortest-path duration alone is never asserted as observed congestion | GPS/traffic absent states, GPS-unavailable gap band, unavailable route leg scenarios | Pass; no congestion assertion is made from route duration |
| Contract and browser tests verify replay, route legs and missingness against persisted data; top-k alternatives remain optional until product requirement is confirmed | Persisted gate plus backend targeted suite and frontend suite above | Pass; top-k alternatives remain out of scope |
| PR links this issue, maps every DoD item to evidence, and links worklog/journal attribution. Local, fixture, isolated-database and hosted results are distinguished | This record, [worklog](../worklog/2026-10-02.md), [journal](../journal/JOURNAL.md) | Pass for local and isolated-database evidence; hosted results are not yet run |

## Evidence classes

- **Fixture-based tests** cover the frontend suite (162 Vitest tests), frontend types, the backend targeted suite, and Ruff. They do not prove database-backed browser evidence.
- **Isolated-database persisted tests** are the six Playwright scenarios run by `scripts/test_gis_persisted.sh` against a migrated disposable database through the real API and frontend.
- **Hosted results** are not yet run. Local results make no hosted or authentication-provider acceptance claim; PR CI/hosted acceptance remains pending.

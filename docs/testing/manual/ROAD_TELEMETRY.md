# T7 Road Telemetry Manual Tests

This runbook verifies the local synthetic corpus and existing API/UI seams. It makes no hosted or production claim. It does not test driver UI, scoring, or Feature 61 behavior; those require PRD confirmation.

## Preconditions

Follow [the test guide](../README.md). Run from repository root:

```bash
.venv/bin/python -m scripts.road_dataset --validate
```

Optional outputs:

```bash
.venv/bin/python -m scripts.road_dataset --validate --output /tmp/road-v1.json --shared-fixture /tmp/road-fixture.json
```

Apply the existing migrations to a disposable PostgreSQL/PostGIS database, then run the opt-in persistence proof:

```bash
ISSUE63_DATABASE_URL='postgresql://...' .venv/bin/pytest -q tests/integration/services/test_road_dataset_integration.py
```

Do not report persistence as tested without `ISSUE63_DATABASE_URL`. Run browser regressions with `CI=true PORT=<free-port> pnpm --prefix src/webapp exec playwright test`. The API/GIS contract uses `tests/fixtures/road_telemetry/normal_trip.json`. Use a dedicated local Next.js server and the real isolated API for agent-browser checks; record any offline basemap separately from route and telemetry evidence.

## Expected validation

Output must contain `"passed": true`, `"dataset_version": "road-v1"`, and the complete case count. Re-running is deterministic. Validation must fail for missing/malformed OSRM fixtures, invalid WGS84 coordinates, or non-positive distance/duration. No fallback geometry, synthetic traffic assertion, or default GPS may replace missing source evidence.

## Scenario matrix

| Test case | Scenario | Expected |
|---|---|---|
| `018f2f4e-a000-7000-8000-000000000001` | `stalled` | Both legs retain route/telemetry links; stall evidence is explicit |
| `018f2f4e-a000-7000-8000-000000000002` | `reverse_travel` | Both legs remain present; directed reverse signal derives from samples |
| `018f2f4e-a000-7000-8000-000000000026` | `traffic_gridlock` | Both legs remain present; traffic source/status is explicit and synthetic |
| `018f2f4e-a000-7000-8000-000000000041` | `technical_dropout` | Both legs remain linked; telemetry gap and unavailable technical evidence are visible |
| `018f2f4e-a000-7000-8000-000000000081` | `normal_progress` | Both legs have source-backed telemetry; no gap is silently filled |

For every case verify assignment, trip, driver, vehicle, and fraud-case links; UTC `Z`; WGS84 lon/lat; metres; m/s. Confirm evaluation labels do not appear anywhere in recursively supplied model input.

## Ingest replay

Submit one generated envelope to `POST /api/v1/telemetry/ingest`, then the byte-equivalent envelope again. The second response is an exact replay and creates no duplicate evidence. Change one payload field while retaining the event identity; expect `409 Conflict`. Confirm seed application preserves unrelated rows and performs no global delete.

## Security and scope

Confirm existing server-side authentication/RBAC and RLS boundaries remain in force, and the unchanged LangGraph graph receives validated evidence only. Synthetic trajectories and traffic are test evidence. Record results separately for fixtures, isolated persistence, local browser behavior, and hosted environments; do not infer hosted acceptance from local checks.

## Playback and checkpoint regression

1. Select a recorded car trip, then a motorbike trip; compare actual `vehicle_type` with the car/motorbike glyph. Unsupported/missing types must show the neutral symbol. Inspect centered 24px circle/person/flag checkpoints and equal 28px driver carriers at desktop and narrow widths.
2. Seek between two consecutive fixes on a curved supplied road. Replay for at least three seconds: the cursor must advance approximately three seconds, movement must follow the corresponding leg, and the driver must remain attached to the display trail. Between-fix position and speed are labeled estimates; exact timestamps preserve recorded coordinates/speed.
3. Pan/zoom the map while paused and replay. Confirm the view stays stable and unchanged route sources remain loaded. Equivalent case refreshes must not reset the cursor.
4. Seek into a declared/observed GPS dropout. Confirm the labeled last known point, unavailable speed, disconnected path, and retained observed dots. Do not animate across the gap or snap an unmatched trajectory onto a planned route.
5. Verify compact 2px by 12px checkpoint marks directly on the scrubber at their recorded timestamps, including dense events and endpoints. Confirm no checkpoint/count buttons, details popovers or extra tab stops. Marks have accessible role/time labels and do not intercept dragging; seek with the native range input. Check desktop and 375px widths, focus, and overlapping static map badges without changing their coordinates.
6. Run `pnpm --prefix src/webapp test`, `pnpm --prefix src/webapp exec tsc --noEmit`, `pnpm --prefix src/webapp build`, and `pnpm --prefix src/webapp exec playwright test`. Capture agent-browser frame measurements and screenshots against the dedicated real isolated API. Separate these results from fixture E2E and hosted acceptance.

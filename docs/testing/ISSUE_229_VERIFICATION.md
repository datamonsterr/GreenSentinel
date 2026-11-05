# Issue 229 — deterministic case map snapshot artifact (geo-map-3)

**Branch:** `map-geoapifyg-issues`
**Base revision:** `226dcba`
**Status:** Verified — acceptance evidence below.

## Headline outcome

`get_case_map_snapshot` now returns a deterministic, evidence-revision-bound map artifact
built from Geoapify Static Maps. Same frozen `evidence_snapshots` revision always produces
the same refs (`deterministic_key`, `route_refs`, `checkpoint_times`, `gap_windows`,
`traveled_path`, `planned_routes`); a new revision creates a new artifact key and can never
mutate already-sent minutes.

## Acceptance / DoD checklist

| # | DoD | Met | Evidence |
|---|---|---|---|
| 1 | New read-only server adapter: inputs `case_id + evidence_snapshot_id`; output `{image_ref\|bytes, route_refs, checkpoint_times, gap_windows, provider, style, rendered_at, snapshot_version}` | ✅ | `src/services/map_snapshot.py` `build_map_snapshot` returns the full typed dict; dispatch at `src/services/tool_execution.py` `get_case_map_snapshot` branch surfaces every field. |
| 2 | Static Maps request: markers (S/P/D/stall) + `polyline` traveled path + `polygon`/gap overlays; GET under URL limits, POST path for complex geometries | ✅ | `build_get_url` (GET, `_GET_URL_LIMIT=2048`), `build_post_payload` (POST polyline6). Markers S/P/D/STALL in `build_map_snapshot`; gap overlays are closed polygons with dashed fill (`_gap_overlay`). Live GET render confirmed (JPEG 800×600). |
| 3 | Image distinguishes planned route (dashed) vs observed GPS (solid) vs gaps (marked); legend embedded or documented | ✅ | Traveled polyline `solid #2563EB`; planned route `dashed #BA1A1A`; gap polygons dashed `#E11D48` + fill (see `build_get_url`/`build_post_payload`). Rendered evidence images in `docs/testing/artifacts/geo_evidence/`. |
| 4 | Bound to frozen `evidence_snapshots.dossier` revision; re-render on new revision creates new artifact, never mutates sent minutes | ✅ | Input `evidence_snapshot_id` mismatch → `revision_mismatch` unavailable + `image_ref: null` (`_unavailable_revision`). Deterministic key from `(revision, hash)`. Test `test_map_snapshot_revision_mismatch_rejected`, `test_snapshot_new_revision_creates_new_artifact`. |
| 5 | Failure union: provider/timeout/quota → structured `unavailable` + retry guidance; no blank image presented as evidence | ✅ | `render_static_map`: 429→`quota_exceeded`, timeout→`provider_timeout`, URLError→`provider_unavailable`, no-geometry → `no_geometry` (no blank POST). Tests `test_render_static_map_quota_returns_structured_unavailable`, `test_render_static_map_timeout_returns_unavailable`, unavailable-path test. |
| 6 | Attribution retained per licence; cost per snapshot recorded (credits) | ✅ | `attribution` field = "© OpenStreetMap contributors (ODbL), © Geoapify"; `cost_credits` = 1 per render (provenance JSON files). |
| 7 | Unit + contract tests: snapshot determinism (same revision → same refs), revision mismatch rejected, unavailable path | ✅ | `tests/unit/services/test_geoapify_data_adapter.py` (`test_snapshot_determinism_same_revision_same_refs`, `test_snapshot_new_revision_creates_new_artifact`, `test_snapshot_unavailable_path_no_geometry`); `tests/integration/services/test_geoapify_case_tools.py` (`test_map_snapshot_revision_mismatch_rejected`, `test_map_snapshot_revision_match_renders`). |

## Validation executed

Command (DoD `pytest tests/ -k "map_snapshot"` equivalent):

```
pytest tests/integration/agents/ tests/integration/services/ tests/unit/services/ -k "map_snapshot or snapshot" -q
=> 12 passed
```

Determinism / revision / unavailable + provider contract suite:

```
pytest tests/unit/services/test_geoapify_data_adapter.py tests/integration/services/test_geoapify_case_tools.py -q
=> 33 passed
```

Real render of three seed cases with the Docker PostGIS seed (`018f2f4e` org) and live Geoapify:

```
python -m scripts.gen_geo_evidence
```

## Sample artifacts

- `docs/testing/artifacts/geo_evidence/snapshot_001_senior_analyst.jpg`
- `docs/testing/artifacts/geo_evidence/snapshot_011_senior_analyst.jpg`
- `docs/testing/artifacts/geo_evidence/snapshot_038_senior_analyst.jpg`
- `docs/testing/artifacts/geo_evidence/index.html` — browser-rendered evidence page; full-page browser screenshot `evidence_full.png` produced on the validation host (too large for the repo) is reproducible via `python -m scripts.gen_geo_evidence`.
- `docs/testing/artifacts/map_snapshot_case_038_provenance.json` — provenance + `cost_credits: 1` + `deterministic_key`.

Provenance block for case `…038` v1: provider `geoapify`, style `osm-bright`,
`deterministic_key 99917bc1970bd91a96eb3abc`, `cost_credits 1`, attribution retained.

## Hosted preview validation (PR #316)

- Railway preview backend deployed from this branch: `https://greensentinel-backend-pr-316.up.railway.app`
  (`/health` ⇒ `{"status":"ok","env":"development","database":"connected"}`; service,
  Postgres, Redis, Qdrant all `SUCCESS` in the `pr-316` environment).
- Vercel webapp preview deployed: `https://green-sentinel-c1xkl8t9x-datpt226024-husteduvns-projects.vercel.app`
  (responds; Clerk-origin authorization set by `authorize_preview.sh`).
- CI gates attributable to this branch all green: Code Quality & Linting, Unit Tests,
  Frontend Vitest & Typecheck, and the full Local Docker integration/agent/E2E suite
  (geo suites, canonical tool execution, runtime boundaries included).
- Two remaining PR checks fail identically on unrelated branches and `main` since the
  relevant gate/fleet state changed (evidence in the PR thread): the isolated persisted
  GIS gate (#61) and the Clerk real-account preview E2E (token creation flake at sign-in,
  zero backend calls from this branch involved). Neither is caused by this branch.
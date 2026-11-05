# Issue 230 — case-scoped Geoapify agent tools (geo-agt-1)

**Branch:** `map-geoapifyg-issues`
**Base revision:** `226dcba`
**Status:** Verified — acceptance evidence below.

## Headline outcome

Analyst/driver agents gain case-scoped, registry-governed Geoapify tools: hardened
`compare_trip_routes`, new `geocode_address`, `reverse_geocode_coordinates` and
`match_trip_telemetry`. Every output carries provenance; lookups explicitly state they are
not location proof; route/match context never asserts driver intent. Place tools remain in
scope-deferred (`search_places` not exposed). Sanctions stay human-only.

## Acceptance / DoD checklist

| # | DoD | Met | Evidence |
|---|---|---|---|
| 1 | `compare_trip_routes` hardened: Geoapify planned vs actual segments, progress/away metrics, leg refs, `traffic_model` + `match_type` (`matched\|unmatched\|interpolated`) preserved; route context never asserts intent | ✅ | `tool_execution.py` compare dispatch: `planned_segments` carry `traffic_model`; `progress_metrics` (distance + min distance to each leg, `advisory_only`); `match_summary` from live map matching with matched/unmatched/interpolated counts + per-index `match_distance_m`. No verdict/intent field in output. Tests: `test_route_context_never_asserts_intent`, `test_route_model_cannot_turn_route_context_into_sanction`. |
| 2 | `geocode_address` + `reverse_geocode_coordinates` (new, read-only, case-scoped): candidates with confidence + distance; lookup ≠ location proof in output text | ✅ | `geoapify_adapter.py` `geocode`/`reverse_geocode` normalize confidence + `distance_m`; dispatch returns `lookup_is_not_location_proof: true`. Tests `test_geocode_normalizes_candidates_with_confidence_and_distance`, `test_reverse_geocode_normalizes_candidates`. |
| 3 | `match_trip_telemetry` (new, read-only): snap stored GPS, return counts + `match_distance` per point; originals never overwritten | ✅ | `_match_trip_telemetry_tool` SELECT-only telemetry read; `originals_never_overwritten: true` in output; per-index `match_distance_m_by_index`. Test `test_match_trip_telemetry_normalized_with_real_telemetry`. |
| 4 | All tools registered in `tool_catalog` with role/model-selectability; trusted actor/scope injection; bounded timeout; structured error unions; key redaction in logs | ✅ | Catalog entries for 3 tools (`tool_catalog.py`) + compare/map-snapshot retained, `model_selectable=True`, `timeout_seconds=10`; `execute_tool` rejects model-supplied authority and scope-mismatched resources; Geoapify failures map to closed `GeocodeFailure`/`MapMatchFailure` codes; no key/URL logging (`routing_http` no-redirect, adapter closed unions). Tests `test_geo_tools_registered_model_selectable`, `test_geo_tools_registered_in_catalog`. |
| 5 | `MODEL_ANALYST_TOOLS` / driver allowlists updated; `claim_case`/`adjudicate_case`/sanctions remain human-only (no regression on #73) | ✅ | `analyst_tools.MODEL_ANALYST_TOOLS` and `driver_tools.MODEL_DRIVER_TOOLS` include the 3 tools; `claim_case`/`adjudicate_case`/`record_case_action`/`write_ticket_for_driver` still `model_selectable=False`. Tests `test_model_registry_excludes_human_commands`, `test_sanction_tools_stay_human_only_regardless_of_geo_routing`, `test_graph_toolnode_excludes_forbidden_commands`. |
| 6 | Places tools explicitly out of scope (deferred; no `search_places` exposure this slice) | ✅ | `search_places` absent from catalog surfaces and model tool names. Test `test_places_tools_explicitly_out_of_scope`. |
| 7 | Integration tests: same normalized output via API + tool adapters; unauthorized actor/scope denied; quota/timeout → honest `unavailable` | ✅ | `tests/integration/services/test_geoapify_case_tools.py`: same normalized dict via `execute_tool` (shared API/tool seam), driver/different-case scope denied (`test_unauthorized_actor_denied_map_snapshot`), `test_provider_timeout_yields_honest_unavailable` (503). Red-team sanction-via-route fails. |

## Validation executed

Command (DoD):

```
pytest tests/integration/agents/ -k "geoapify or route or geocode" -q
=> 6 passed, 2 skipped
```

Full geo + registry + canonical boundary suites (150 tests):

```
pytest tests/unit/services/test_geoapify_data_adapter.py tests/unit/services/test_routing_provider.py \
  tests/unit/api/test_route_resolve_provider.py tests/integration/services/test_canonical_tool_execution.py \
  tests/integration/services/test_geoapify_case_tools.py tests/integration/agents/test_tool_catalog.py \
  tests/integration/agents/test_geoapify_registry.py tests/integration/agents/test_driver_tools.py \
  tests/integration/agents/test_runtime_tool_boundary.py -q
=> 150 passed
```

Live role-scoped run (real PostGIS seed + live Geoapify): `python -m scripts.gen_geo_evidence`
produced per-role tool outputs for cases 001/011/038. Analyst (assigned owner) and senior
analyst succeed; driver (no mapped principal) is denied — scope enforcement confirmed.
Sample outputs rendered in `docs/testing/artifacts/geo_evidence/index.html`.

## Sample outputs (provenance blocks)

- `geocode_address("Hoan Kiem Lake, Hanoi")` → candidates with `confidence`, `distance_m`,
  `attribution`; `lookup_is_not_location_proof: true`.
- `reverse_geocode_coordinates(105.8342, 21.0278)` → candidates with provider `distance_m`.
- `match_trip_telemetry` → `point_count`, `matched_count`, `match_distance_m_by_index`,
  `originals_never_overwritten: true`.
- `compare_trip_routes` → `planned_segments`, `progress_metrics`, `match_summary`
  (counts + distances), `advisory_only: true`.

## Hosted preview validation (PR #316)

- Railway preview backend deployed from this branch: `https://p063-backend-pr-316.up.railway.app`
  (`/health` ⇒ `{"status":"ok","env":"development","database":"connected"}`).
- Vercel webapp preview deployed: `https://p-063-c1xkl8t9x-datpt226024-husteduvns-projects.vercel.app`.
- CI gates attributable to this branch all green (Lint, Unit, Vitest, Local Docker
  integration/agent/E2E). The `test_agent.sh` suite including the analyst tool registry
  now asserts the expanded surface explicitly (`ANALYST_TOOLS == 15` with the three #230
  tools). Two repo-wide checks (persisted GIS gate #61, Clerk real-account preview E2E)
  fail identically on unrelated branches and `main`; neither involves this branch's code — evidence in the PR thread.
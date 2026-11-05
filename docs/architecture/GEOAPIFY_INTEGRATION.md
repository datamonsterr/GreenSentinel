# Geoapify Integration Capability Assessment

**Status:** Historical assessment retained; provider foundation implemented in #227. Map/UI activation and subsequent epic slices remain gated. The #227 boundary below supersedes the earlier open product questions.

**Scope:** Capability and boundary assessment for Geoapify routing, geocoding, map matching, map tiles/styles, and MCP tools in P-063. This document does not authorize production rollout, national coverage, quota/licence entitlement, or a replacement of the existing map UI.

## Evidence baseline

Six sanitized authenticated probes ran against public Hanoi examples on 2026-10-08. The sanitized summary record is [capabilities-2026-10-08.json](../testing/artifacts/geoapify/capabilities-2026-10-08.json). All probes returned HTTP 200:

| Capability | Observed result | Boundary |
|---|---|---|
| Geocoding | One Vietnam `Point` feature | Example success only; address coverage and quality remain unverified. |
| Reverse geocoding | One Vietnam `Point` feature; distance `30.191869736884588` | Example success only. |
| Routing | `MultiLineString`; 1,317 m; 87.581 s; `drive`; `free_flow` | This is a free-flow estimate without traffic influence. No live or historical traffic proof. |
| Map matching | `MultiLineString`; 102 m; 23 s; `matched`, `matched`, `unmatched` | Unmatched points must remain explicit. |
| Map style | Style version 8; one source; 111 layers | Attribution and tile entitlement still require review. |
| MCP | 11 tools returned | Capability discovery only; agent exposure remains governed by P-063 registries. |

Authoritative references: [Geoapify Routing API](https://apidocs.geoapify.com/docs/routing/), [traffic route times](https://apidocs.geoapify.com/how-to/routing/traffic-route-times/), [map matching](https://apidocs.geoapify.com/docs/map-matching/), [map tiles](https://apidocs.geoapify.com/docs/maps/map-tiles/), and [Geoapify MCP](https://apidocs.geoapify.com/docs/mcp/).

## Local credential setup

The supplied key is configured under `GEOAPIFY_API_KEY` in the ignored local `.env` with file mode `0600`. Its value is excluded from all committed/public artifacts. No application consumer is added by this assessment. The six diagnostic requests read that local value; the committed artifact records only credential-free request metadata and result summaries. API credentials must never be part of a model prompt or tool arguments, browser bundle, response, provider error message, or persisted map-style asset URL.

## Requirements fit

The [Phase 1 PRD](../ba/PRD.md) defines FR-02 spatial map evidence and the Tester extension defines FR-TST-01 through FR-TST-08 plus NFR-TST-01 through NFR-TST-05. Geoapify can provide planned route geometry, address lookup context, reconstructed GPS geometry, and tile/style inputs for those requirements. It cannot by itself prove fraud intent, traffic truth, sanctions, or the approximately one-minute test-trip target.

The current `/test` implementation already renders a map with playback and timeline milestones; its existence does not satisfy the open runtime acceptance gates. A timeline may present ordered evidence milestones, but it should not silently replace spatial evidence. The proposed UX decision is therefore: retain map evidence where geometry is required and allow a timeline view for event ordering and provenance. Final replacement or split-pane behavior requires the Tester visual approval gate.

## Proposed service boundary

`routing_service.py` currently exposes an existing OSRM adapter return contract containing geometry, distance, duration, provider, and provenance. Geoapify routing returns `MultiLineString`; the adapter must normalize this typed geometry while preserving leg discontinuities and provider provenance. It must never silently substitute a straight-line route when provider data is unavailable.

The provider adapter should remain behind an application service. FastAPI routes, LangGraph nodes, and agent tools call that service; none should call Geoapify directly. Candidate read-only use cases include `compare_trip_routes`, `get_case_map_snapshot`, `geocode_address`, `reverse_geocode_coordinates`, and `match_trip_telemetry`. Exact names and schemas remain proposed until the shared service contract is accepted.

## Agent-tool application

The [shared API/agent-tools ADR](adr-006-shared-use-cases-for-api-and-agent-tools.md) requires thin adapters, explicit tool registration, trusted runtime identity, strict schemas, bounded timeouts, and structured failures. Geoapify's 11 MCP tools are source capabilities, not an authorization to expose all 11 to the model.

The existing `tool_catalog` and `tool_execution` boundaries must govern actor, scope, schema, budget, and audit context. A generic fetch tool, arbitrary vendor-MCP passthrough, secret access, adjudication, and sanction operations remain prohibited. Geoapify results are advisory evidence; a model cannot turn a route or match result into a sanction.

## Required architecture answers

| Question | Proposed answer |
|---|---|
| System topology | Browser calls FastAPI; FastAPI and LangGraph adapters call a shared Geoapify-capable application service; the service calls a provider port; Geoapify remains external. |
| State and graph lifecycle | No LangGraph state or node change is proposed. A graph may carry the immutable evidence snapshot and provider provenance already required by the case workflow. |
| Tool contracts | Typed read-only tools use case-scoped inputs, trusted actor/scope injection, explicit timeout and error unions, and provider provenance in outputs. |
| Data flow | Client or graph requests a use case; validation and authorization run in the service; provider response is normalized; evidence is attached to the case snapshot or test run; API/tool adapters map the result. |
| Trade-offs | Geoapify adds geocoding, matching, styles, and route alternatives with one provider boundary. It adds quota, licence, latency, coverage, and provider-lock-in questions. Keep the provider port replaceable. |
| Security and boundaries | Store the key server-side. Use provider-supported secret headers where available. Do not place the key in browser bundles. Browser use requires a restricted browser key or a server proxy decision. Apply timeouts, bounded retries, rate limits, redaction, and attribution checks. |

## Evidence semantics and capability mapping

| Input or capability | Proposed application use | Required distinction |
|---|---|---|
| Map tiles/style | Replace the basemap provider behind existing MapLibre; preserve playback and event timeline. | Basemap context is separate from the source of trip evidence. |
| Routing | Planned origin–pickup–destination route and comparison baseline for the existing Tester composer. | A legal/model-generated route is not an observed driver trajectory. |
| Forward/reverse geocoding | Search trip endpoints and describe street/place context. | Candidate addresses and returned distances are lookup results, not proof of an actor's location. |
| Map matching | Reconstruct a plausible route from supplied GPS, retaining original points and match metadata. | Matched, unmatched, and interpolated points must stay distinct; never overwrite original GPS. |
| Address autocomplete | Reduce endpoint-entry friction in the existing trip composer. | Suggestions need user selection; accuracy/coverage are unverified by this assessment. |
| Static maps | Candidate input for `get_case_map_snapshot` with a referenced evidence revision. | No snapshot generation was tested; retain source/time and required attribution. |
| Isolines | Optional travel-time reachability context when a future requirement needs it. | Estimated reachability is not an observed pickup radius or a guilt signal; no probe was run. |
| Route matrix / places / geometry | Possible later distance comparisons, pickup access context, and distance-to-route calculations. | Documentation capabilities only; these operations were not called in the six probes. |
| Routing traffic | Optional free-flow or approximated ETA context. | `free_flow` ignores traffic; `approximated` models congestion. Neither supplies live incidents or observed past conditions. |

The map-matching timestamps are authored sample inputs, not recorded trip evidence. Its derived speed/time does not validate real historical traffic. The approximately one-minute composition target and approximately ten-second initial cockpit render target remain application measurements, not vendor-probe conclusions.

## Proposed verification seams

These seams are submitted for stakeholder review; no integration tests are claimed as executed.

| Boundary | Proposed checks | Proof class |
|---|---|---|
| Public provider service | Finite/ranged coordinates; explicit lat/lon conversion; typed geometry/units; no route; unmatched/interpolated points; 401/403/429; malformed payload; bounded timeout and retry. | Offline unit/transport-contract tests. |
| Shared API/agent service | Same normalized output through thin adapters; trusted tenant/case/actor scope; catalog role/model-selectability; key redaction; provider result and source semantics. | API/tool integration and schema contract tests in an isolated environment. |
| Existing `/test` and cockpit | Route preservation on reload, provenance, failed-provider display, map/timeline synchronization, sampling gaps, keyboard access and measured composition time. | Browser regression and operator UAT after design approval and prerequisite acceptance. |

## Open decisions and risks

- Confirm whether the requested key is valid for the intended project, plan, quota, and tile/routing usage. The key value is intentionally absent from this repository.
- Confirm attribution, licence, caching, and production usage terms before displaying Geoapify tiles or derived data.
- Confirm whether the application needs live traffic, historical traffic, or only modeled/free-flow estimates. The probe proves none of the former.
- Define provider timeout, retry, rate-limit, and unavailable-data semantics. Preserve explicit unknowns and unmatched points.
- Decide server proxy versus a separate restricted browser key for map tiles and any client-side map requests.
- Reconcile Geoapify geometry with existing route and timeline evidence without deleting source provenance.
- Do not duplicate the existing Tester console work. Existing #130 parent, #131 contracts, #133, #136, and #155 capability work remain the coordination points; #133 and #136 have recorded blockers. Existing #204/PR #205 route/save work must be reviewed before adding overlapping route persistence.

## Proposed implementation slices

These are proposals for review, not approved requirements or a task register:

1. Provider foundation and a controlled CLI/probe console: typed adapter, secret handling, normalized route/geocode/match results, and sanitized evidence.
2. Case-scoped read-only services and agent tools: shared service calls, registry enforcement, provenance, failure unions, and authorization tests.
3. Existing `/test` integration: map/timeline presentation and route/matching evidence after the Tester contracts, acceptance gates, and visual approval are complete.


The [proposed design and rendered preview](../design/geoapify/design.md) illustrate the retained map and companion timeline. They are static design artifacts awaiting stakeholder review, not real tiles or application screenshots. Stitch generation is unavailable in this session and its required design gate remains open.

## #227 implemented boundary (2026-10-09)

Issue #227 implements the provider boundary in `src/services` while preserving the existing OSRM callers. A public route request uses finite, range-checked `(longitude, latitude)` coordinates. The Geoapify adapter converts each waypoint to the provider's `(latitude, longitude)` order and supports `drive`, `scooter`, and `motorcycle`, with `balanced` or `short` weighting, `instruction_details`, and `free_flow` or `approximated` traffic. GreenSM Bike's approved default is `motorcycle`; scooter remains supported. The default provider remains OSRM, with an explicit Geoapify selector for server-side use.

Adapters expose a typed success/failure union internally. At the legacy service compatibility seam, provider failures map to `None` so existing consumers remain compatible. OSRM retains its legacy `LineString` behavior. Geoapify `MultiLineString` legs stay disjoint; malformed vertices split the geometry into separate runs, and no straight-line or waypoint fallback is fabricated. The planned route store remains `LineString`; unavailable or disjoint provider geometry is rejected by the caller guard rather than replaced with a shortcut.

The selected deployment boundary is a server proxy: browser code receives normalized, sanitized results and never receives a provider key. A future tile/style proxy must rewrite requests to a fixed allowlist path and keep keys, provider headers, style URLs, raw bodies, and exception details out of responses, logs, prompts, bundles, and committed artifacts. This issue implements the routing server adapter; proxy and UI work remain outside #227.

Stakeholder-approved T0 terms retain MapLibre, store the timeline in the application, model Geoapify traffic as advisory (`approximated` is modeled congestion), and keep weather on Open-Meteo. Millisecond precision is permitted where data provides it; the system does not promise millisecond sampling. Conservative free-plan planning assumptions are 3,000 credits/day and 5 requests/second; the actual account plan remains unverified.

### Implemented architecture questions

| Question | Implemented answer |
|---|---|
| System topology | Browser calls the FastAPI/server service. The service selects the OSRM or Geoapify adapter through the provider port; the browser never calls Geoapify directly. |
| State and graph lifecycle | The LangGraph/tool graph is unchanged. Route results carry provider/provenance metadata through the existing application flow; timeline state remains application-owned. |
| Tool contracts | The provider port validates lon/lat inputs and route options. Adapters return typed success or failure codes internally; the legacy seam maps unavailable provider results to `None`. |
| Data flows | Caller validates coordinates and options, adapter builds a bounded provider request, Geoapify waypoints are converted to lat/lon, the response is normalized, and only valid geometry/provenance crosses the service seam. |
| Trade-offs | A replaceable port preserves OSRM compatibility while adding Geoapify capabilities. Multi-leg fidelity and explicit failures cost normalization complexity but prevent invented geometry and hidden gaps. |
| Security and boundaries | The key is read only by server-side provider code. Logs and errors use allowlisted summaries; provider URLs, bodies, raw headers, and secret values are never emitted. Rate/plan limits are treated as conservative planning constraints until entitlement is verified. |

Validation evidence is recorded in [GEOAPIFY_PROVIDER.md](../testing/manual/GEOAPIFY_PROVIDER.md). Local unit/ASGI contracts and bounded live-provider probes passed separately. No database migration, Geoapify map activation, or authenticated hosted acceptance is claimed.

T0 licence/quota/attribution terms were confirmed by the stakeholder on 2026-10-09 ([acceptance record](https://github.com/AI20K-Build-Phase-Cohort-4/P-063/issues/227#issuecomment-6076628622)). The conservative planning limits and required Geoapify/data-source attribution follow the published [pricing](https://www.geoapify.com/pricing/) and [terms](https://www.geoapify.com/terms-and-conditions/); actual account entitlement remains unverified. `ROUTING_PROVIDER=osrm` preserves existing case persistence; selecting `geoapify` enables the server routing port and route-resolution API. Case storage/rendering migration belongs to #228. Disjoint geometry is returned intact by resolution and rejected by the current single-line simulation-definition boundary, never flattened into a shortcut.

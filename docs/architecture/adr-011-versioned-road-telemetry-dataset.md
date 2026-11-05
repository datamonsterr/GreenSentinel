# ADR-011: Versioned Road Telemetry Dataset

## Status
Accepted for T7 documentation and deterministic local evaluation.

## Context

The analyst cockpit needs reproducible road evidence for origin→pickup and pickup→destination. Tests must distinguish normal progress, stall, directed reverse travel, traffic, and telemetry dropout without invented geometry or hidden evidence. The corpus is synthetic and separate from production claims; existing trip, assignment, case, agent, and RBAC contracts remain authoritative.

## Decision

Use the pinned OSRM corpus loaded by [`RoadTripFixture`](../../scripts/road_trip_generator.py) and materialized by [`road_dataset.py`](../../scripts/road_dataset.py). Version it as `road-v1`, use base seed `42`, and use clock origin `2026-09-22T06:00:00Z`. Keep OSRM geometry and distance/duration as source-backed inputs; derive speed from route distance and elapsed time. Generate `normal_progress`, `stalled`, `reverse_travel`, `traffic_gridlock`, and `technical_dropout`.

Each case uses base seed `42` plus its zero-based ordinal among sorted fraud-case UUIDs, independent of source iteration order. Its manifest and route provenance record the effective seed. Nominal sampling targets ten seconds with arc-length jitter; the manifest bounds intervals by `11.002` seconds. Traffic scales time and the cadence together, and dropout explicitly declares omitted intervals. Cancelled pickup scenarios have no fabricated arrival, ride-start, or completion timestamps.

Evaluation labels remain in evaluation structures only and are removed recursively from model inputs. Missing telemetry, unavailable traffic, and provider failures remain explicit; no fallback geometry, midpoint route, default GPS, or invented traffic is permitted.

Coordinates are WGS84 GeoJSON `[lon, lat]`; persisted WKT/PostGIS is `lon lat`. Producer fields are named latitude/longitude; timestamps are UTC ISO-8601 with `Z`; distance is metres and speed is metres per second. Every case retains its existing trip, assignment, driver, vehicle, and fraud-case identifiers and links both route legs and telemetry to the assignment.

The GIS browser must load MapLibre's actual worker modules and verify rendered route features, not only assigned GeoJSON. The same build pipeline must emit both the worker entry and its shared module for development and production. Case refreshes preserve the current timeline selection; switching cases initializes a new timeline.

Playback advances at one recorded second per elapsed second. Between fixes, display-only estimates follow the supplied route for the known leg from either endpoint, provided there is no contradictory leg, no missing interval, at most 30 seconds between fixes, a 30-metre road corridor, and speed below 50 m/s. Exact fixes retain recorded coordinates and speed; estimates never enter persisted telemetry or model input. Missing or unmatched intervals hold a labeled last known position with unavailable speed and disconnected trails; recorded GPS dots remain visible. One full source-backed camera fit preserves manual pan/zoom during playback. Circle/person/flag checkpoints and actual car/motorbike icons use fixed centered carriers; unknown vehicle types remain neutral.

Use Webpack for both Next.js development and production. Resolve the MapLibre worker entry with a module-relative URL and emit its sibling shared module from the installed package. This adds a bundler-specific configuration hook; a future bundler transition must preserve worker loading and rendered-route browser evidence. The production build and the local rendered-browser checks are recorded in [the verification record](../testing/ISSUE_63_VERIFICATION.md).

Ingesting an identical event identity and payload is an exact replay. The same identity with changed content returns `409 Conflict`. Seed application is isolated and preserving: it performs no global delete.

## Rationale & Alternatives Considered

| Option | Pros | Cons | Decision |
|---|---|---|---|
| Pinned OSRM corpus plus deterministic sampler | Reproducible, source-backed, offline, explicit provenance | Fixture maintenance | Selected |
| Live OSRM on every run | Fresh routes | Network drift and changed evidence | Rejected |
| Unversioned response cache | Faster warm runs | Misses/invalidation change evidence | Rejected |
| Invented geometry or traffic fallback | Keeps a demo moving | Hides unavailable evidence | Rejected |

The corpus accepts maintenance cost for reproducibility. Live routing may exist as a separate production integration, but cannot silently replace this fixture.

## Required Architecture Questions

1. **System topology:** Local tooling reads pinned OSRM JSON, adapts the existing seed, and FastAPI persists immutable events/projections; the cockpit reads linked case evidence.
2. **State and graph lifecycle:** Existing LangGraph nodes and typed state are unchanged; they receive normalized telemetry and explicit gap/unavailable flags, never scenario labels.
3. **Tool contracts:** Pydantic validates `TelemetryEventEnvelope`; fixture validation requires OSRM `Ok`, LineString geometry, coordinate bounds, and positive distance/duration; ingest handles replay/conflict.
4. **Data flow:** Load → validate two legs → sample deterministically → preserve identities → validate envelopes → persist → link assignment/case → expose existing APIs and map.
5. **Trade-offs:** The pinned corpus is selected over live routing and an unversioned cache for stable provenance and honest unavailable states.
6. **Security and boundary protection:** Existing authentication, RBAC, RLS, audit rules, and agent authority boundaries remain unchanged. Dataset generation grants no permissions.

## Consequences

The corpus is reviewable offline and reproducible. A new corpus requires a new version, provenance, validation, and review. T7 adds no driver UI, model scoring, or Feature 61 behavior; PRD confirmation remains required for expansion.


## Issue 61 verification audit — 2026-10-02

Case rendering consumes recorded assignment lifecycle timestamps through the existing case API. Planned pickup/dropoff coordinates remain map checkpoints; they never prove an actual arrival/completion. Missing or invalid lifecycle timestamps do not create timed milestones. Cancellation end time is not dropoff. Exact recorded GPS supplies speed only at its matching timestamp. SQL and fixture adapters expose the same lifecycle semantics. Existing LangGraph state and authorization boundaries are unchanged.

Gap bands remain passive time annotations, separate from measured trajectory geometry. The native scrubber references persistent gap explanations without added tab stops or per-frame live announcements. Missingness durations retain source precision. Test fixtures cannot silently replace unavailable routes, GPS or traffic.

The persisted GIS gate runs before CI build with a per-run disposable database and local services. Repeated setup compares counts/content fingerprints of app tables; browser scenarios are read-only against separately seeded cases. Failure traces and performance measurements are retained as CI artifacts. This supplies reproducible isolated evidence; it does not establish hosted authentication or cold-start performance. [Audit and evidence](../testing/ISSUE_61_AUDIT.md) records the limits and supersedes unsupported earlier completion claims.

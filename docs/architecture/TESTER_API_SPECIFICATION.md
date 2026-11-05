# Tester Simulation API Design

**Status:** Proposed contract for [Epic #130](https://github.com/AI20K-Build-Phase-Cohort-4/GreenSentinel/issues/130), not implemented endpoints. Frontend `/test` calls canonical backend `/test/api/v1`. Existing `/api/v1` contracts remain in [API_SPECIFICATION.md](API_SPECIFICATION.md). The test router has no root or `/api/v1/test` alias.

## Interface and authorization

All routes require a verified principal and explicitly provisioned `tester` permission, including development environments. A missing principal fails `401`; missing permission fails `403`. Organization and plan/run ownership are checked server-side; scoped absence returns `404`. Existing [auth helpers](../../src/api/auth.py) contain development fallbacks; the proposed test dependency must reject those fallbacks. User-supplied actor IDs, database targets, environment flags or privileged roles cannot select credentials or grant permissions.

The Tester owns plans/runs and operates server-mapped simulated `DRIVER` and `PASSENGER` identities. A Passenger reply is not an analyst decision. Analysts receive normal assignment/review permissions separately in the isolated environment. Case creation and assignment occur only through actual system assessment; there is **no force-create-case endpoint**. `/test/workplace` reuses the existing layout with an injected test client and test-scoped case APIs. Tester permission alone never grants claim/adjudication rights.

## Wire conventions and validation

Use camelCase JSON, UUID identifiers, RFC3339 UTC timestamps ending in `Z`, metres, metres/second and seconds. Coordinates are named latitude/longitude at authoring; route GeoJSON uses `[longitude, latitude]`. Reject non-finite numbers, invalid coordinate ranges, naive times, negative speed, out-of-route segments and unknown enum values. HTTP request types exclude server-generated identity/hash/result fields. Provider responses are validated before consumption. Adapters explicitly translate to existing snake_case [TelemetryEventEnvelope](../../src/models/schemas.py); never change that contract to match this new namespace.

The stakeholder selected **1-second ordinary GPS cadence**, selectable slower cadence, and `JUMP`, `OFFSET_NOISE`, `DROPOUT`. Proposed initial engineering bounds are cadence 1–60 seconds, speed 0–50 m/s, at most 100,000 samples per run, 5,000 characters per message, and 200 messages per definition. These are design proposals, not measured acceptance or policy facts. Fault displacement/noise/duration bounds, definition byte limit, concurrency/rate quotas and run duration caps must be frozen in a versioned capability profile after representative-trip validation. `/capabilities` reports the configured limits; unsupported values fail `422` with field details. A missing accepted profile disables execution, rather than permitting unlimited input.

## Typed input and output schemas

The following TypeScript descriptions specify proposed Pydantic V2/OpenAPI equivalents. All identifiers and generated fields are outputs unless a request explicitly references an existing resource. `JsonMap` below is restricted to structured validation-error details, not domain payloads.

```ts
type Id = string;
type Utc = string;
type ActorRole = "DRIVER" | "PASSENGER";
type LatLon = { latitude: number; longitude: number };
type LineString = { type: "LineString"; coordinates: [number, number][] };
type Page<T> = { data: T[]; pagination: { page: number; pageSize: number; totalItems: number } };
type Provenance = {
  kind: "AUTHORED" | "ROUTING_SOURCE" | "HISTORICAL_OBSERVED" | "MODELED" | "SIMULATED" | "UNAVAILABLE";
  sourceName: string | null; sourceRef: string | null; sourceVersion: string | null;
  requestedAt: Utc | null; observedAt: Utc | null; reason: string | null;
};
type Metric =
  | { state: "AVAILABLE"; value: number; unit: "m" | "s" | "ratio"; reference: string; version: string; provenance: Provenance }
  | { state: "UNAVAILABLE"; reason: string; reference: string; version: string };
type RouteLeg = { leg: "PICKUP" | "DESTINATION"; geometry: LineString; distanceM: number; durationS: number | null; provenance: Provenance };
type RouteInput = { waypoints: LatLon[]; selectedRouteSnapshotId: Id | null };
type FaultInput =
  | { kind: "JUMP"; atOffsetS: number; displacementM: number; bearingDeg: number }
  | { kind: "OFFSET_NOISE"; atOffsetS: number; durationS: number; offsetM: number; noiseStdDevM: number; seed: number }
  | { kind: "DROPOUT"; atOffsetS: number; durationS: number };
type SegmentTrafficInput = {
  segmentId: Id; leg: "PICKUP" | "DESTINATION"; startDistanceM: number; endDistanceM: number;
  mode: "SIMULATED"; density: number; speedFactor: number; mappingVersion: string;
};
type PlannedMessageInput = { localId: Id; speaker: ActorRole; recipient: ActorRole; text: string; atOffsetS: number; draftSource: "MANUAL" | "AI_EDITED" };
type DefinitionInput = {
  origin: LatLon; pickup: LatLon; destination: LatLon; startAt: Utc;
  route: RouteInput; speedMps: number; cadenceS: number; playbackRate: number;
  placementRadiusM: number; placementRadiusCenter: "PICKUP";
  faults: FaultInput[]; segmentTraffic: SegmentTrafficInput[];
  historicalTrafficSnapshotId: Id | null; plannedDialogue: PlannedMessageInput[];
};
type DefinitionRevision = { id: Id; planId: Id; revision: number; definition: DefinitionInput; routes: RouteLeg[]; contentHash: string; createdAt: Utc; provenance: Provenance[] };
type Plan = { id: Id; ownerId: Id; title: string; latestRevision: DefinitionRevision; createdAt: Utc; updatedAt: Utc };
type PlanCreateInput = { title: string; definition: DefinitionInput };
type PlanPatchInput = { title?: string; definition?: DefinitionInput; expectedRevision: number };
type PreviewInput = { definition: DefinitionInput };
type Metrics = { pickupDistance: Metric; destinationDistance: Metric; remainingRouteDistance: Metric; straightLineToPickup: Metric; etaPickup: Metric; etaDestination: Metric; davi: Metric };
type Preview = { routes: RouteLeg[]; routeSnapshotId: Id; metrics: Metrics; estimatedSampleCount: number; warnings: string[]; source: Provenance[] };
type Sample = { sequence: number; atOffsetS: number; occurredAt: Utc; simulatedPosition: LatLon; reportedPosition: LatLon | null; speedMps: number | null; accuracyM: number | null; faultKind: FaultInput["kind"] | null; metrics: Metrics };
type SamplingInput = { definitionRevisionId: Id; offset: number; limit: number };
type SamplingOutput = { samples: Sample[]; nextOffset: number | null; totalSamples: number; profileVersion: string };
type ProviderCapability = { provider: string; coverage: string; earliestAt: Utc | null; latestAt: Utc | null; semantics: "HISTORICAL_OBSERVED" | "MODELED"; licenseStatus: "APPROVED" | "UNVERIFIED"; isAvailable: boolean; reason: string | null };
type Limits = { profileVersion: string; executionEnabled: boolean; cadenceMinS: number; cadenceMaxS: number; maxSamples: number; maxMessageChars: number; maxMessages: number; maxRunDurationS: number; maxConcurrentRuns: number; faultMaxDisplacementM: number; faultMaxNoiseStdDevM: number; faultMaxDurationS: number };
type Capabilities = { limits: Limits; trafficProviders: ProviderCapability[]; notificationSupported: boolean; assessmentSupported: boolean };
type TrafficQueryInput = { routeSnapshotId: Id; requestedAt: Utc; provider: string };
type TrafficSegment = { segmentId: Id; leg: RouteLeg["leg"]; startDistanceM: number; endDistanceM: number; estimatedSpeedMps: number | null; density: number | null; provenance: Provenance };
type TrafficSnapshot = { id: Id; state: "AVAILABLE" | "PARTIAL" | "UNAVAILABLE"; routeSnapshotId: Id; requestedAt: Utc; segments: TrafficSegment[]; provenance: Provenance };
type AiDraftInput = { definitionRevisionId: Id; instructions: string; speakers: ActorRole[] };
type AiDraftOutput = { id: Id; messages: PlannedMessageInput[]; modelVersion: string; promptVersion: string; evidenceRefs: Id[]; isSubmitted: false };
type RunState = "QUEUED" | "RUNNING" | "PAUSED" | "CANCELLING" | "COMPLETED" | "CANCELLED" | "FAILED";
type Run = { id: Id; planId: Id; definitionRevisionId: Id; tripId: Id; assignmentId: Id; ownerId: Id; environment: "TEST"; state: RunState; lastEventSequence: number; lastSampleSequence: number | null; startedAt: Utc | null; finishedAt: Utc | null; participantIds: Record<ActorRole, Id>; errorCode: string | null };
type RunCreateInput = { planId: Id; definitionRevisionId: Id };
type ControlInput = { expectedControlSequence: number; command:
  | { type: "PAUSE" } | { type: "RESUME" } | { type: "CANCEL" }
  | { type: "SET_SPEED"; speedMps: number }
  | { type: "STOP_MOVEMENT" } | { type: "RESUME_MOVEMENT" }
  | { type: "REROUTE"; routeSnapshotId: Id; leg: RouteLeg["leg"] }
  | { type: "INJECT_FAULT"; fault: FaultInput }
};
type Control = { id: Id; runId: Id; controlSequence: number; input: ControlInput; status: "ACCEPTED" | "APPLIED" | "REJECTED" | "UNKNOWN"; acceptedAt: Utc; appliedAt: Utc | null; reason: string | null };
type MessageInput = { speaker: ActorRole; recipient: ActorRole; text: string; expectedRunSequence: number };
type Delivery = "STORED" | "PENDING" | "DELIVERED" | "FAILED" | "UNKNOWN";
type Message = { id: Id; runId: Id; speaker: ActorRole | "SYSTEM"; recipient: ActorRole; text: string; occurredAt: Utc; delivery: Delivery; notificationId: Id | null; source: "MANUAL" | "AI_EDITED" | "SYSTEM" };
type TestNotification = { id: Id; runId: Id; recipient: ActorRole; text: string; createdAt: Utc; delivery: Delivery; requiresReply: boolean; replyDeadlineAt: Utc | null; replyIds: Id[] };
type ReplyInput = { actor: ActorRole; text: string; expectedNotificationRevision: number };
type Stage = { name: "INGESTION" | "ASSESSMENT" | "NOTIFICATION" | "RESPONSE" | "ASSIGNMENT"; state: "PENDING" | "READY" | "UNAVAILABLE" | "FAILED"; reason: string | null; evidenceRefs: Id[] };
type Results = {
  runId: Id; stages: Stage[]; assessmentVersion: string | null;
  outcome: "PENDING" | "CASE_CREATED" | "NO_CASE_OBSERVED" | "INSUFFICIENT_EVIDENCE" | "UNSUPPORTED" | "FAILED";
  observedFrom: Utc | null; observedThrough: Utc | null;
  caseIds: Id[]; assignments: { caseId: Id; analystId: Id | null; state: "UNASSIGNED" | "ASSIGNED" | "FAILED" }[];
  observedSignals: string[]; advisoryReason: string | null; guardrailCodes: string[];
};
type EventBase = { eventId: Id; runId: Id; sequence: number; occurredAt: Utc; recordedAt: Utc; schemaVersion: 1 };
type RunEvent = EventBase & (
  | { type: "RUN_STATE_CHANGED"; state: RunState }
  | { type: "CONTROL_UPDATED"; control: Control }
  | { type: "TELEMETRY_EMITTED"; sample: Sample }
  | { type: "MESSAGE_UPDATED"; message: Message }
  | { type: "NOTIFICATION_UPDATED"; notification: TestNotification }
  | { type: "RESULTS_UPDATED"; results: Results }
  | { type: "RUN_ERROR"; code: string; message: string; retryable: boolean }
);
type EventPage = { data: RunEvent[]; nextSequence: number; hasMore: boolean };
type RunSnapshot = { run: Run; controls: Control[]; messages: Message[]; notifications: TestNotification[]; results: Results; lastEventSequence: number };
type ApiError = { error: { code: string; message: string; details?: Record<string, string[]>; requestId: Id } };
```

Snapshots exceeding configured limits use paginated resource reads; do not allow unbounded aggregate responses. `speedFactor` maps simulated segment density to a speed multiplier using a versioned mapping; engineering and Tester must validate that mapping before numerical acceptance. A route change invalidates old segment offsets until explicitly remapped. Planned `atOffsetS` resolves from definition `startAt`; the runner derives evidence `occurredAt` from the simulated clock. Event `recordedAt` is the actual server receipt time. Runtime actor input takes the current simulated time plus server receipt time; the client cannot backdate consumed evidence. Historical-query time, simulated clock and wall-clock execution latency are distinct. Historical traffic selection never silently changes simulation speed or substitutes current traffic for a past observation. Named route legs retain the existing pickup/destination meaning.

## Endpoint catalog

All paths below are relative to `/test/api/v1`. `Idempotency-Key` is required for every POST/PATCH; POST previews/query operations are recorded calculations, not telemetry submission. Lists use bounded `page/pageSize` or sequential cursors as stated.

| Method / relative path | Input | Output / success | Behavior |
|---|---|---|---|
| GET `/capabilities` | None | `Capabilities` / 200 | Actual configured support and accepted limits |
| POST `/plans` | `PlanCreateInput` | `Plan` / 201 | Save a complete definition; no run/case creation |
| GET `/plans` | `page,pageSize` | `Page<Plan>` / 200 | Owner-scoped list |
| GET `/plans/{planId}` | None | `Plan` / 200 | Latest saved revision |
| PATCH `/plans/{planId}` | `PlanPatchInput` | `Plan` / 200 | Optimistic revision check; changed definition creates immutable revision |
| GET `/plans/{planId}/revisions/{revisionId}` | None | `DefinitionRevision` / 200 | Immutable consumed/replay inputs |
| POST `/previews` | `PreviewInput` | `Preview` / 200 | Blank-plan route/metric preview before saving |
| POST `/sampling-previews` | `SamplingInput` | `SamplingOutput` / 200 | Bounded sample slice; never ingest |
| POST `/traffic-queries` | `TrafficQueryInput` | `TrafficSnapshot` / 200 | Supported historical evidence or explicit unavailable state |
| POST `/dialogue-drafts` | `AiDraftInput` | `AiDraftOutput` / 200 | Optional editable AI output; never sends or starts run |
| POST `/runs` | `RunCreateInput` | `Run` / 202 | Durable accepted submission, pins whole revision |
| GET `/runs` | `page,pageSize,planId?` | `Page<Run>` / 200 | Reload prior executions |
| GET `/runs/{runId}` | None | `Run` / 200 | Execution status independent of downstream outcome |
| GET `/runs/{runId}/snapshot` | None | `RunSnapshot` / 200 | Consistent snapshot at `lastEventSequence` |
| POST `/runs/{runId}/controls` | `ControlInput` | `Control` / 202 | Accepted control; APPLIED event proves effect |
| GET `/runs/{runId}/controls` | `page,pageSize` | `Page<Control>` / 200 | Runtime control history |
| GET `/runs/{runId}/samples` | `afterSequence,limit` | `SamplingOutput` / 200 | Persisted emitted samples, including faults |
| GET `/runs/{runId}/events` | `afterSequence,limit` | `EventPage` / 200 | Durable replay cursor |
| GET `/runs/{runId}/stream` | `Last-Event-ID` or `afterSequence` | `text/event-stream` / 200 | SSE `id=sequence`, event `run.event`, JSON `RunEvent` |
| POST `/runs/{runId}/messages` | `MessageInput` | `Message` / 201 | Timed actor message accepted into sandbox evidence; delivery independent |
| GET `/runs/{runId}/messages` | `page,pageSize,recipient?` | `Page<Message>` / 200 | Server checks actor mapping; role filter does not grant rights |
| GET `/runs/{runId}/notifications` | `page,pageSize,recipient?` | `Page<TestNotification>` / 200 | Actual sandbox delivery records |
| POST `/runs/{runId}/notifications/{notificationId}/replies` | `ReplyInput` | `Message` / 201 | Recipient/deadline/revision checked; replying actor is notification recipient |
| GET `/runs/{runId}/results` | None | `Results` / 200 | Actual system stages, case links and assignment; no result presets |

For live rerouting, the run snapshot returned by `GET /runs/{runId}/snapshot` is the client’s source of the current `routeSnapshotId`; a successful reroute produces a new snapshot and emits the applied control event before the next sample.

Edit planned manual messages or segment traffic through `PATCH /plans` with a complete replacement definition and expected revision. AI-draft edits become planned inputs only after explicit review/save; raw AI output is never automatically submitted. Runtime edits append messages/controls, not rewrites of consumed evidence. A new run of a pinned revision is a replay attempt with a **new run ID/key**; deterministic input replay does not promise identical model output.

The test-scoped Workplace client also binds the [existing case endpoints](API_SPECIFICATION.md#1-system-topology--endpoint-matrix) beneath `/test/api/v1/cases`: queue/detail/policy/forensic read, claim/release, actions, adjudication, case progress and Agents sessions/chat. Reuse the existing request/response schemas and stricter existing role/identity/lease/rationale/audit gates. Mount a separate test service dependency; **do not mount the global production router wholesale**. Every existing Cockpit dependency, account lookup, policy/precedent tool and linked navigation must be inventoried and covered by a test adapter or explicit unavailable state before Workplace integration acceptance. [UI design](../design/tester-simulation/design.md) describes that inventory seam.

## Lifecycle, metrics and errors

`QUEUED` becomes `RUNNING` after durable worker claim. `PAUSE` accepts only RUNNING and produces PAUSED after application; `RESUME` accepts only PAUSED. `CANCEL` accepts QUEUED/RUNNING/PAUSED, enters CANCELLING and then CANCELLED. Natural playback completion becomes COMPLETED; permanent execution error becomes FAILED. Terminal execution cannot restart; replay creates a new run. `STOP_MOVEMENT` keeps the simulation clock and stationary GPS advancing, unlike PAUSE. Speed/reroute/fault controls are applied only at the next acknowledged sampling boundary; conflicts reject `409`. Changes to past offsets or already emitted samples reject `422`. Results may remain PENDING after COMPLETED until the real detector/assignment stage resolves.

Map radius is a proposed pickup-centred geometric placement constraint, not a road-distance rule. Show named distance references and units. Preview and run use the same metric/profile versions. DAVI follows [feature_engineering.py](../../src/services/feature_engineering.py): approach-window distance-weighted directional alignment toward pickup; segments beginning within 20 metres are excluded, insufficient evidence remains null/unavailable, and negative DAVI on legitimate road geometry does not prove intent. Per-point inspection references the segment/window used; it does not invent a standalone DAVI for one fix. Producer samples never fabricate precomputed detector features. `NO_CASE_OBSERVED` requires a persisted completed assessment and observation window; empty lists, timeouts or unavailable detectors are not no-case proof.

| HTTP | Machine code examples | Meaning |
|---|---|---|
| 400 | `INVALID_CURSOR` | Malformed transport input |
| 401 / 403 | `AUTH_REQUIRED`, `TEST_PERMISSION_REQUIRED` | Authentication / explicit permission failure |
| 404 | `RESOURCE_NOT_FOUND` | Scoped resource absent |
| 409 | `REVISION_CONFLICT`, `IDEMPOTENCY_CONFLICT`, `REQUEST_IN_PROGRESS`, `CONTROL_STATE_CONFLICT`, `KEY_EXPIRED` | Revision, state or retry conflict |
| 410 | `CURSOR_EXPIRED` | Retention gap; fetch authorized snapshot then replay |
| 422 | `VALIDATION_ERROR`, `UNSUPPORTED_PROFILE` | Invalid fields or unsupported configured bounds |
| 429 | `RATE_LIMITED` | `Retry-After`; no hidden additional effect |
| 500 / 503 | `INTERNAL_ERROR`, `DEPENDENCY_UNAVAILABLE` | Sanitized internal/dependency error; mutation outcome may be unknown |

All errors use `ApiError`; internal traces/secrets are never returned. Historical unsupported time/coverage is a successful unavailable `TrafficSnapshot`, while transport/provider failure may be `503`. AI draft failure preserves manual inputs. Capabilities expose unsupported notification/assessment seams; UI cannot synthesize READY results for them.

## Idempotency and durable recovery

The client generates one key **per intent**, retained across retries, including JWT refresh. Atomically claim a unique `(organization,principal,method,normalizedPath,key)` record with canonical request hash, resource reference and state in the same transaction as the durable mutation/outbox. Exact replay returns stored original status/body; changed payload rejects `409`; in-flight duplicate rejects `409` with `Retry-After`. Server-created idempotency keys are invalid substitutes for client intent.

Proposed minimum retention is **7 days and never shorter than the longest configured queue/recovery retry window**. Keep key/hash/resource tombstones afterward until the corresponding run is deleted by authorized retention, rejecting old keys with `KEY_EXPIRED` rather than treating them as new. A timeout/worker crash after an external effect yields UNKNOWN and a durable reconciliation task; query/reconcile by event/message identity before retrying. Unique sample/event/command identities and sandbox notification deduplication protect at-least-once delivery. Never infer “failed to send” merely because the response timed out.

## Streaming, pagination and retention

Create run snapshots and their event cursor atomically. Reconnect with last durably applied event sequence; the UI deduplicates by run/event identity, replays before tailing, and never treats transient connection loss as a failed run. Persisted event sequence and sample sequence are separate: explicit GPS dropout leaves an explained sample/time gap without losing event-log ordering.

Expired cursor returns `410 CURSOR_EXPIRED` with the snapshot resource reference. Snapshot recovery preserves full persisted evidence; cursor expiration cannot silently delete required run artifacts. Proposed event-retention baseline is 7 days, with immutable run artifacts retained under separately approved storage policy. Bearer-authenticated fetch streaming permits JWT refresh without credentials in URLs. Authentication expiry closes the stream and triggers fresh token plus cursor resume; authorization revocation stops access. Slow clients are disconnected when the bounded buffer fills, then resume by cursor/poll. Heartbeats are transport keepalives, not durable assessment events. GET `/events` is the polling fallback. Limits, heartbeat interval and reconnect/backoff thresholds are configured, versioned and tested; no unbounded queue or browser memory buffer.

## Sources and test handoff

[Architecture](TESTER_SIMULATION_ARCHITECTURE.md), [isolation ADR](adr-015-isolated-tester-simulation.md), [test strategy](../testing/TESTER_SIMULATION_TEST_STRATEGY.md) and [manual/UAT tests](../testing/MANUAL_TEST_TESTER_SIMULATION.md) define implementation proof. FastAPI supports [router prefixes/dependencies](https://fastapi.tiangolo.com/tutorial/bigger-applications/); its [background task guidance](https://fastapi.tiangolo.com/tutorial/background-tasks/) motivates durable workers for this long-running slice. Next.js [route groups](https://nextjs.org/docs/app/api-reference/file-conventions/route-groups) do not create URL prefixes: use a real `app/test` segment. UI explanations follow [WAI tooltip guidance](https://www.w3.org/WAI/ARIA/apg/patterns/tooltip/) with non-hover alternatives.

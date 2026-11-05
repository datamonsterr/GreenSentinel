# SPEC-0130: Tester Trip Simulation & Evaluation Architecture

## 1. Executive Summary & Objective

The Tester Trip Simulation framework provides a fully isolated, end-to-end sandbox environment that enables Quality Assurance (QA), automated testing suites, and operations analysts to author synthetic trip scenarios, inject controlled telemetry anomalies, stream generated GPS fixes through production-grade ingestion pipelines, and observe dynamic fraud/anomaly detection outputs in real time.

### Core Objective
To establish a high-fidelity testing harness capable of validating telemetry workers, spatio-temporal feature extractors, automated case generation engines, and analyst workflow interfaces without contaminating production datastores or triggering external driver/passenger communications.

```
+-----------------------------------------------------------------------------------+
|                            SIMULATION & EVALUATION LOOP                           |
|                                                                                   |
|  +--------------------+      +--------------------+      +---------------------+  |
|  | Scenario Authoring | ---> |  Telemetry Inject  | ---> | Production Pipeline |  |
|  |  (Routes / Faults) |      | (GPS Engine / Queue)|      | (Assessment Worker) |  |
|  +--------------------+      +--------------------+      +---------------------+  |
|                                                                     |             |
|  +--------------------+      +--------------------+                 v             |
|  | Sandbox Sink Triage| <--- | Real DB Validation | <--- +---------------------+  |
|  | (UI & Intercepts)  |      | (app.cases / trips)|      | Anomaly Detection   |  |
|  +--------------------+      +--------------------+      +---------------------+  |
+-----------------------------------------------------------------------------------+
```

### Absolute Constraints
* **No Backdoor Injection**: Synthetic trips and fraud cases must never be inserted directly into database tables via administrative bypasses. All anomaly flags, risk scores, and case records must be generated organically by standard background processing workers consuming telemetry events.
* **Fail-Closed Isolation**: Absolute partitioning of storage, message routing, and notification delivery mechanisms ensures zero leakages into production operations.

---

## 2. System Architecture & Topology

The simulation framework operates as a modular extension to the core backend monolith and frontend application, maintaining explicit network and storage isolation boundaries.

```
+---------------------------------------------------------------------------------------+
|                                  SYSTEM TOPOLOGY                                      |
|                                                                                       |
|   FRONTEND LAYER                      BACKEND ENGINE               ISOLATION BOUNDARY |
|  +-----------------------+           +-----------------------+     +----------------+ |
|  | /test                 | ------->  | FastAPI Engine        | --> | Isolated DB    | |
|  | Cockpit & Map UI      |  REST/    | /test/api/v1          |     | (PostGIS Test) | |
|  +-----------------------+  SSE      +-----------------------+     +----------------+ |
|  | /test/workplace       |           | Simulation Runner     | --> | Sandbox Queue  | |
|  | Isolated Case Work    |           | Background Daemon     |     | (Redis Namespace)|
|  +-----------------------+           +-----------------------+     +----------------+ |
|                                                                    | Notification   | |
|                                                                    | Interceptor    | |
|                                                                    +----------------+ |
+---------------------------------------------------------------------------------------+
```

### 2.1 Backend Architecture Components
* **API Controller (`src/api/test_routes.py`)**: Exposes management endpoints scoped strictly under the `/test/api/v1` path prefix. Handles definition CRUD, run lifecycle toggles, and Server-Sent Events (SSE) streaming.
* **Service Layer (`src/services/test_simulation_service.py`)**: Encapsulates business logic for interpolating geospatial paths, calculating kinematics, applying fault transformations, and managing transactional execution states.
* **Execution Daemon (`src/services/test_simulation_runner.py`)**: Distributed, lock-aware background worker leasing pending/active simulation runs, stepping the simulation clock, generating synthetic telemetry fixes, and pushing payloads to message queues.
* **Repository Layer (`src/services/test_simulation_repository.py`)**: Data access abstraction providing atomic operations for reading definitions, persisting generated samples, tracking outbox state, and writing audit logs.

### 2.2 Frontend Application Routes
* `/test` (Simulation Cockpit): Interactive visual workspace incorporating MapLibre GL for route drawing and live trip rendering, alongside compact control panels for driver, passenger, and environment state.
* `/test/workplace` (Isolated Case Workspace): Standard analyst investigation interface injected with a scoped API client targeting exclusively the test database tenancy. Allows end-to-end validation of analyst triage workflows.

### 2.3 Boundary Protection & Isolation Rules

| Component | Production Environment | Test Simulation Environment |
| :--- | :--- | :--- |
| **Database** | Primary PostgreSQL Cluster (`db_prod`) | Isolated Test Database (`db_test`) |
| **Cache & Queue** | Redis Default Namespace (`db:0`) | Redis Isolated Namespace (`db:15`, key prefix `test:`) |
| **Notifications** | APNS / FCM / Twilio Gateway Drivers | Sandbox Mock Sink (Logs to `test_notifications`) |
| **API Boundary** | `/api/v1/*` | `/test/api/v1/*` (Requires `X-Test-Context: true`) |

---

## 3. Data Flow & Run Lifecycle

The execution lifecycle of a simulation scenario progresses through seven deterministic stages, executing asynchronously to guarantee realistic system behavior:
```
[Authoring] -> [Submission] -> [Leasing] -> [Ingestion] -> [Assessment] -> [Intercept] -> [Verification]
```

1. **Definition Authoring (`/test`)**:
   The user defines origin, pickup, and destination coordinates on a map UI, setting driver parameters (speed, updates/sec), audio conversation dialogue, and injecting fault profiles (e.g., GPS drift at $t+30s$). The UI POSTs this configuration to `/test/api/v1/definitions`, creating an immutable `test_definition_revisions` record.
2. **Run Submission**:
   The user initiates a run via `/test/api/v1/runs`. The service creates an idempotency claim, inserts an outbox queue record, sets the run status to `QUEUED`, and returns an HTTP 202 Accepted response with the `run_id`.
3. **Simulation Runner Leasing**:
   The background daemon (`test_simulation_runner`) claims the `QUEUED` run using an atomic `SELECT ... FOR UPDATE SKIP LOCKED` lease pattern. It steps the simulation clock forward according to the scenario configuration (default rate: 1 sample per second) and calculates geographic positions along the road network geometry.
4. **Telemetry Ingestion**:
   Generated telemetry fixes are wrapped into standard `TelemetryEventEnvelope` structures and published to the isolated Redis queue (`test:queue:telemetry`).
5. **Assessment & Case Creation**:
   Production-identical background worker processes read from `test:queue:telemetry`. Spatio-temporal algorithms compute speed, trajectory alignment, and DAVI (Device Acceleration Variability Index) metrics. If an injected fault breaches operational thresholds, the engine writes standard domain records (`app.trips`, `app.cases`, `app.assignments`) into the dedicated test database.
6. **Sandbox Notification Interception**:
   Any downstream events generated by case routing (e.g., driver account suspension, passenger notification) are intercepted by the sandbox sink and stored in `test_notifications` without making external API calls.
7. **SSE Streaming & Verification**:
   The simulation backend streams live execution updates over SSE to the `/test` cockpit, while real-time cases appear on the `/test/workplace` queue for analyst triage.

---

## 4. State Machines & Fault Specifications

### 4.1 Run Lifecycle State Machine
```
               +-----------------------------------+
               |                                   |
               v                                   |
[QUEUED] -> [RUNNING] <-----> [PAUSED]     [CANCELLING]
               |               |                   |
               +---------------+--------+          v
               |                        |    [CANCELLED]
               v                        v
          [COMPLETED]               [FAILED]
```
* `QUEUED`: Initial state upon POST submission; awaiting runner allocation.
* `RUNNING`: Active tick loop. Telemetry points are calculated and emitted continuously.
* `PAUSED`: Tick loop suspended. Simulation clock pauses; no telemetry points emitted.
* `STOP_MOVEMENT` (Control State): Simulation clock continues advancing, but vehicle kinematics drops to 0 m/s, sending stationary GPS samples.
* `CANCELLING` / `CANCELLED`: Graceful worker teardown and terminal status.
* `COMPLETED`: Scenario path fully traversed; worker released.
* `FAILED`: Unhandled system error or internal pipeline exception encountered.

### 4.2 Telemetry Fault Injection Mechanics
Faults are mathematical vector transformations applied over a bounded time window $[T_{\text{start}}, T_{\text{end}}]$ relative to the run time.

* **JUMP (Teleportation Anomaly)**:
  $$P_{\text{injected}}(t) = P_{\text{true}}(t) + \text{Vector}(\text{Latitude_Shift}, \text{Longitude_Shift})$$
  Instantly shifts the reported coordinate to a location defined by static offsets. Tests high-speed spatial jump detectors.
* **OFFSET_NOISE (Sensor Drift / Degradation)**:
  $$P_{\text{injected}}(t) = P_{\text{true}}(t) + \text{Gaussian}(\text{mean}=0, \text{stddev}=\sigma)$$
  Applies Gaussian or systematic spatial bias to normal road centerlines over time. Tests map-matching confidence and route deviation thresholds.
* **DROPOUT (Signal Loss)**:
  $$P_{\text{injected}}(t) = \text{NULL}$$
  Suppresses telemetry emission for a defined time window. Verifies worker handling of stale device states and dead-reckoning fallbacks.

---

## 5. Database Schema Specification (Dedicated Test DB)

All tables exist inside the isolated PostGIS database instance under `public` or `app` schemas.

```sql
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "postgis";

-- Test Scenario Container
CREATE TABLE test_plans (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(255) NOT NULL,
    description TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Immutable Scenario Definitions
CREATE TABLE test_definition_revisions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    plan_id UUID NOT NULL REFERENCES test_plans(id) ON DELETE CASCADE,
    revision_number INT NOT NULL DEFAULT 1,
    route_geometry GEOMETRY(LineString, 4326) NOT NULL,
    driver_config JSONB NOT NULL DEFAULT '{}'::jsonb,
    passenger_config JSONB NOT NULL DEFAULT '{}'::jsonb,
    fault_configs JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT unique_plan_revision UNIQUE(plan_id, revision_number)
);

-- Active & Historical Simulation Runs
CREATE TABLE test_runs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    definition_revision_id UUID NOT NULL REFERENCES test_definition_revisions(id),
    status VARCHAR(32) NOT NULL DEFAULT 'QUEUED',
    current_step INT NOT NULL DEFAULT 0,
    total_steps INT NOT NULL DEFAULT 0,
    simulation_clock TIMESTAMPTZ NOT NULL,
    speed_factor FLOAT NOT NULL DEFAULT 1.0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ
);

-- Real-time Control Overrides
CREATE TABLE test_controls (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    run_id UUID NOT NULL REFERENCES test_runs(id) ON DELETE CASCADE,
    command VARCHAR(32) NOT NULL,
    payload JSONB DEFAULT '{}'::jsonb,
    executed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Emitted Telemetry Log
CREATE TABLE test_samples (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    run_id UUID NOT NULL REFERENCES test_runs(id) ON DELETE CASCADE,
    step_index INT NOT NULL,
    location GEOMETRY(Point, 4326) NOT NULL,
    speed_mps FLOAT NOT NULL,
    heading_deg FLOAT NOT NULL,
    is_fault_injected BOOLEAN NOT NULL DEFAULT FALSE,
    fault_type VARCHAR(32),
    emitted_at TIMESTAMPTZ NOT NULL
);

-- Execution Events Stream
CREATE TABLE test_events (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    run_id UUID NOT NULL REFERENCES test_runs(id) ON DELETE CASCADE,
    event_type VARCHAR(64) NOT NULL,
    event_payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Audio Conversation Scripts
CREATE TABLE test_messages (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    run_id UUID NOT NULL REFERENCES test_runs(id) ON DELETE CASCADE,
    sender_role VARCHAR(32) NOT NULL,
    content TEXT NOT NULL,
    offset_seconds INT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Intercepted Sink Notifications
CREATE TABLE test_notifications (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    run_id UUID NOT NULL REFERENCES test_runs(id) ON DELETE CASCADE,
    recipient_type VARCHAR(32) NOT NULL,
    recipient_id VARCHAR(128) NOT NULL,
    channel VARCHAR(32) NOT NULL,
    body TEXT NOT NULL,
    intercepted_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Transactional Outbox Pattern
CREATE TABLE test_outbox (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    aggregate_type VARCHAR(64) NOT NULL,
    aggregate_id VARCHAR(128) NOT NULL,
    payload JSONB NOT NULL,
    processed BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Idempotency Locks
CREATE TABLE test_idempotency_keys (
    key VARCHAR(255) PRIMARY KEY,
    run_id UUID REFERENCES test_runs(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Domain Isolation Tables
CREATE SCHEMA IF NOT EXISTS app;

CREATE TABLE app.trips (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    test_run_id UUID REFERENCES public.test_runs(id),
    driver_id VARCHAR(64) NOT NULL,
    passenger_id VARCHAR(64) NOT NULL,
    status VARCHAR(32) NOT NULL,
    start_time TIMESTAMPTZ NOT NULL,
    end_time TIMESTAMPTZ
);

CREATE TABLE app.cases (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    trip_id UUID REFERENCES app.trips(id),
    risk_score FLOAT NOT NULL,
    anomaly_types TEXT[] NOT NULL,
    status VARCHAR(32) NOT NULL DEFAULT 'OPEN',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE app.assignments (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    case_id UUID REFERENCES app.cases(id),
    assignee_id VARCHAR(64),
    assigned_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

---

## 6. UI Mockup & Visual Layout Specification

### 6.1 Master Viewport & Layout Architecture
The Simulation Cockpit employs a full-bleed viewport desktop dashboard designed for real-time spatial monitoring and continuous user interaction. The interface is organized into four distinct spatial zones:
* **Top Control & Status Bar:** Sticky glassmorphic top header containing global simulation state indicators, active run identifier, speed factor toggles (1x, 2x, 5x, 10x), execution controls, and route quick-actions.
* **Central-Right Map Viewport:** High-performance MapLibre GL spatial canvas rendering vector tiles, route geometry, live vehicle telemetry markers, and fault visualizers.
* **Left Floating Actor Stack:** Overlay stack containing floating glass/card panels for Driver and Passenger states, live dialogue feeds, and telemetry gauges without obscuring key map controls.
* **Floating Tools & Controls Drawer:** Contextual drawer and toolbar overlays providing manual fault injection triggers, audio script controls, and route planning configuration options.

### 6.2 Central Map Area (MapLibre GL)
The central map view serves as the primary visual display for trip progress, geospatial route alignment, and fault detection visualization:
* **Interactive Road Network & Route Layer:** Displays planned route geometry connecting Origin (green marker), Pickup (blue marker), and Destination (red finish line) with semi-transparent directional vectors.
* **Real-Time Vehicle Cursor:** Dynamic marker indicating calculated position with directional heading arrow, velocity vector line, and altitude/accuracy radius circle.
* **Telemetry Trail & Anomaly Highlighting:** Emitted GPS fixes leave a breadcrumb trail. Deliberately injected anomalies (`JUMP`, `OFFSET_NOISE`, `DROPOUT`) are highlighted in distinct warning colors (amber/red) and bypass map-matching snapping routines to accurately reflect raw sensor input.

### 6.3 Driver Actor Panel (Upper-Left)
A translucent card overlay presenting real-time telemetry and state details for the driver actor:
* **Driver Status Indicator:** Badge indicating current driver lifecycle phase (Assigned, En route to Pickup, Arrived, In-trip to Destination).
* **Kinematics & Telemetry Gauges:** Live numerical and radial gauges displaying calculated velocity (m/s, km/h), update frequency (e.g., 1 Hz), heading angle, and DAVI index value.
* **Clock & Step Counter:** Displays current simulation clock timestamp, elapsed time, current step index, and distance to next waypoint.
* **Driver Conversation Script:** Interactive speech bubble widget showing live dialogue audio transcript items synchronized with trip timestamp offsets.

### 6.4 Passenger Actor Panel (Lower-Left)
Positioned symmetrically below the Driver Panel, this card provides passenger context and synchronous dialogue tracking:
* **Passenger Ride Status:** Status indicator showing state flow (Requesting, Waiting for Pick-up, Boarded, Dropped off).
* **Location Details & ETA:** Pickup address, destination address, and estimated time of arrival calculation updated continuously.
* **Passenger Dialogue Bubble:** Synchronous dialogue display showing incoming passenger messages matching the driver transcript timeline.

### 6.5 Simulation Control Toolbar & Tools Panel
The top header bar and floating toolbars provide interactive execution control over the simulation engine:
* **Playback Controls:** Action buttons for Play/Start, Pause (freezes simulation clock and movement), Stop Movement (advances clock with 0 m/s velocity), and Cancel.
* **Speed Multipliers & Scrubbing:** Speed selection buttons (1x, 2x, 5x, 10x) and timeline scrubber for stepping backward or forward through generated samples.
* **Fault Injection Triggers:** Quick-trigger buttons to inject active anomalies (`JUMP`, `OFFSET_NOISE`, `DROPOUT`) or trigger dynamic route recalculation (Reroute) in real time.
* **Accessibility Tooltips:** Hover and focus tooltip overlays explaining all control icon actions and active key bindings.

### 6.6 Test Workplace View (`/test/workplace`)
The Test Workplace mirrors the production Analyst Case Workplace UI layout while operating against isolated test databases:
* **Case Triage Queue:** Filterable queue showing synthetic cases generated organically by background workers processing test telemetry events.
* **Telemetry Analysis Graph:** Multi-axis charts rendering DAVI index, reported speed vs. expected map speed, and spatial trajectory variance over trip duration.
* **Evidence Viewer & Action Toolbar:** Comprehensive audit log panel displaying intercepted mock notifications, audio dialogue transcripts, and triage decision buttons (Investigate, Approve, Sanction).

### 6.7 Detailed Input and Output Contract for `/test/workplace`

This section explicitly defines the precise data input specifications, read queries, analyst session controls, mutation outputs, and operational contract rules governing the Isolated Case Workspace (`/test/workplace`):

#### Inputs to `/test/workplace`

* **Scoped Test API Client Configuration:** Injected API client targeting exclusively `/test/api/v1` utilizing header `X-Test-Context: true` and a Tester bearer token, maintaining complete architectural isolation from global/operational client routines.

* **Read & Query Inputs:**
  * **Case Triage Queries:** Dynamic filter parameters (`risk_score`, `status` [`OPEN`, `UNDER_REVIEW`, `CLOSED`], `anomaly_types`, `run_id`, and `trip_id`) executed directly against the isolated test database tenancy (`app.cases`, `app.assignments`, and `app.trips`).
  * **Case Context & Evidence Load:** Hydrates scenario links (`test_result_links`), GPS sample trace snapshots (`test_samples`), computed feature windows (DAVI index, speed variance, trajectory alignment), and intercepted mock actor communication feeds (`test_messages`, `test_notifications`).
  * **Analyst Session & Lease Input:** Authenticated test analyst identity context, active case lease acquisition locks, and user-submitted triage action rationale notes.

#### Outputs and State Mutations from `/test/workplace`

* **Case Action / Triage Decision API Payload:** Emits `POST /test/api/v1/cases/{case_id}/triage` payloads specifying decision outcome (`INVESTIGATE`, `APPROVE_LEGITIMATE`, `SANCTION_SUSPEND`), attached rationale notes, and lease lock release signals.
* **Domain Mutation Output:** Updates state columns in test tenant tables (`app.cases.status` and `app.assignments`) while appending immutable audit log records to `test_events`.
* **Sandbox Notification Trigger Output:** Emits mock downstream communication triggers (e.g. driver warnings or account sanction notices) directly into the `test_notifications` sink without invoking external gateway drivers.

#### Strict Boundaries & Contract Rules

| Rule | Description |
| :--- | :--- |
| **No Auto-Assignment** | A case link in the simulation does NOT automatically imply assignment or sanction; each action requires separate lease, rationale, and policy verification steps. |
| **No TEST Badge** | No mandatory visible "TEST" badge is forced on the UI to keep the analyst experience completely identical to production. |
| **Production Isolation** | Output mutations must NEVER touch operational storage or production `app.*` schemas. |

#### Shared Logic with Production Workplace

The following production components from `/workplace` are **reused directly** with injected test context — not reimplemented:

| Component | Source (production) | Test injection mechanism |
| :--- | :--- | :--- |
| MapLibre GL map canvas | `src/webapp/components/map/` | Same map component; test SSE stream substituted via `useSimulationSSE` hook |
| Case triage action logic | `src/webapp/components/workplace/` | Wrapped with `X-Test-Context: true` header; routes to `/test/api/v1` |
| DAVI / speed multi-axis graph | `src/webapp/components/telemetry/` | Same chart component; data sourced from `test_samples` |
| Evidence / notification viewer | `src/webapp/components/evidence/` | Sources from `test_notifications` and `test_messages` instead of production tables |
| Analyst auth context | `src/webapp/lib/auth/` | Same Clerk session; test API client created with test-scoped token |


## 7. Implementation Checklist & Instructions for AI Coding Agents

### Backend Tasks
* [x] FastAPI route controller at `src/api/test_routes.py` with endpoints for scenario creation, execution management, control signals, and SSE stream endpoints.
* [x] Pydantic V2 schemas for definition revisions, fault specifications (`JumpFault`, `OffsetNoiseFault`, `DropoutFault`), and run initialization models in `src/models/test_simulation.py`.
* [x] Simulation kinematics engine in `src/services/test_simulation_service.py` supporting linear arc-length interpolation along PostGIS geometries.
* [x] Background execution daemon (`src/services/test_simulation_runner.py`) using `SELECT FOR UPDATE SKIP LOCKED` query patterns to lock and advance active simulation steps.
* [x] Transactional Outbox worker to route test telemetry payloads safely into the isolated Redis queue (`test:queue:telemetry`).
* [x] Worker infrastructure to load the test settings profile (`TEST_MODE=true`, `DATABASE_URL=db_test`) when processing test queues.

### Frontend Tasks
* [x] Full-bleed desktop Simulation Cockpit at `/test` organized into 4 spatial zones: Top Bar, Central-Right Map Viewport, Left Floating Actor Stack (Driver & Passenger panels), and Floating Tools/Controls Drawer.
* [x] MapLibre GL spatial canvas rendering road network, Origin/Pickup/Destination markers, vehicle cursor with heading & velocity vector, and raw sensor anomaly trail (`JUMP`, `OFFSET_NOISE`, `DROPOUT`).
* [x] Upper-Left Driver Actor Panel with lifecycle status, kinematics gauges (speed, heading, DAVI), clock/step counters, and live speech bubble conversation widget.
* [x] Lower-Left Passenger Actor Panel with ride state flow, pickup/destination addresses, dynamic ETA, and synchronous dialogue bubbles.
* [x] Simulation Control Toolbar with Play, Pause, Stop Movement (0 m/s), Cancel, speed multipliers (1x, 2x, 5x, 10x), and real-time fault injection triggers.
* [x] Isolated Case Workplace at `/test/workplace` featuring case triage queue, multi-axis telemetry & DAVI analysis graphs, evidence viewer for intercepted notifications/dialogues, and triage action toolbar.
* [x] `/analyst` route removed; all test workplace functionality consolidated exclusively under `/test/workplace`.

### Shared Logic & Reuse Tasks (6.7)
* [ ] `POST /test/api/v1/cases/{case_id}/triage` endpoint with `INVESTIGATE` / `APPROVE_LEGITIMATE` / `SANCTION_SUSPEND` decision payloads, rationale notes, and lease release.
* [ ] Test API client factory (`src/webapp/lib/testApiClient.ts`) injecting `X-Test-Context: true` header and Tester bearer token — isolated from production API client.
* [ ] Case triage filter UI: `risk_score`, `status` (`OPEN`, `UNDER_REVIEW`, `CLOSED`), `anomaly_types`, `run_id`, `trip_id` query parameters wired to `/test/api/v1/cases`.
* [ ] Reuse production map component (`src/webapp/components/map/`) in `/test/workplace` with `useSimulationSSE` hook substituting the SSE stream source.
* [ ] Reuse production DAVI/speed multi-axis chart component sourcing from `test_samples` instead of production telemetry tables.
* [ ] Reuse production evidence/notification viewer component sourcing from `test_notifications` and `test_messages`.
* [ ] Reuse production analyst auth context (Clerk session); create test-scoped API client from same session without a separate auth flow.
* [ ] Case mutations write to `app.cases`, `app.assignments`, `test_events` in test DB only — production schema must never be touched.
* [ ] Sandbox notification trigger writes to `test_notifications` without invoking APNS/FCM/Twilio gateway drivers.

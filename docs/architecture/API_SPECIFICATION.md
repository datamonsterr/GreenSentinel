# API Architecture Specification: PoC Endpoints, Schemas, and Supabase Integration

> Derived directly from [`POC_DESIGN.md`](POC_DESIGN.md), [`DATA_MODEL.md`](DATA_MODEL.md), [`ADR-002`](adr-002-relational-spatial-event-schema.md), and [`ADR-006`](adr-006-shared-use-cases-for-api-and-agent-tools.md).

T7 road telemetry follows [`ADR-011`](adr-011-versioned-road-telemetry-dataset.md): synthetic pinned OSRM `road-v1`, seed `42`, fixed UTC clock, unchanged trip/assignment/case links, agent graph, authentication, RBAC, and security contracts.

## 1. System Topology & Endpoint Matrix

FastAPI exposes typed REST and SSE endpoints. Business logic is strictly contained in `src/services/` repositories, keeping route handlers thin and transport-focused. Authentication maps Clerk JWTs to `app.principals` with role checks in PostgreSQL. Test adapters (e.g. `x-role`, `x-principal-id`) are strictly scoped to explicit offline test mode (`APP_ENV=test` and `TEST_AUTH_ENABLED=true`), and are never accepted in hosted environments.

| Method | Path | Request Body | Response Body | HTTP Status | Purpose |
|---|---|---|---|---|---|
| `GET` | `/health` | None | `HealthResponse` | 200 | Liveness & readiness check (no secrets exposed) |
| `POST` | `/api/v1/telemetry/ingest` | `TelemetryEventEnvelope` | `IngestResult` | 200 / 201 / 409 | Idempotent producer telemetry ingestion |
| `POST` | `/api/v1/simulations/{scenario}` | `SimulationTriggerRequest` | `SimulationTriggerResponse` | 200 | Trigger named scenario (`intentional_dic`, `traffic_gridlock`, `technical_dropout`) |
| `GET` | `/api/v1/cases` | None (query: `status`, `priority`, `limit`, `offset`) | `CaseListResponse` | 200 | Analyst queue with server-side filters and priority sort |
| `GET` | `/api/v1/cases/{id}` | None | `CaseDetailResponse` | 200 / 404 | Complete case dossier: features, route, evidence, guardrails, forensic brief, case policy |
| `GET` | `/api/v1/cases/{id}/forensic-brief` | None | `ForensicBriefResponse` | 200 / 404 | Objective forensic abnormality summary (no faked data, no verdict) |
| `GET` | `/api/v1/cases/{id}/motivation` | Read roles | `{assessment, persisted, versions}` | 200 / 404 | Latest persisted structured motivation assessment, else unsaved rule draft (`version: 0`) |
| `POST` | `/api/v1/cases/{id}/motivation/generate` | analyst, senior_analyst, admin | `{assessment, persisted}` | 200 / 403 / 404 | Rule-based generation (optional validated LLM rationale), saved as a new draft version |
| `PUT` | `/api/v1/cases/{id}/motivation` | analyst, senior_analyst, admin | `{assessment, persisted}` | 200 / 403 / 409 / 422 | Analyst edit (category, signals, confidence, rationale) saved as a new version; `expected_version` guards races |
| `POST` | `/api/v1/cases/{id}/motivation/confirm` | analyst, senior_analyst, admin | `{assessment, persisted}` | 200 / 404 / 409 | Confirms the latest draft (audit event `motivation_confirmed`); see ADR-033 |
| `GET` | `/api/v1/cases/{id}/policy` | None | `CasePolicyResponse` | 200 / 404 | Applicable policy clauses, guardrails, and precedent rules for a specific case |
| `POST` | `/api/v1/cases/{id}/claim` | `ClaimCaseRequest` | `ClaimCaseResponse` | 200 / 409 | Claim short-lived review lease for analyst |
| `POST` | `/api/v1/cases/{id}/actions` | `CaseActionRequest` | `CaseActionResponse` | 200 / 400 | Non-terminal review actions: `REQUEST_EVIDENCE`, `DEFER` |
| `POST` | `/api/v1/cases/{id}/adjudicate` | `AdjudicationRequest` | `AdjudicationResponse` | 200 / 400 / 409 | HITL terminal adjudication: `AGREE`, `DISAGREE` |
| `GET` | `/api/v1/cases/{id}/stream` | None | `text/event-stream` | 200 | SSE stream for real-time case pipeline progress |
| `POST` | `/api/v1/policy/chat/stream` | `PolicyChatRequest` | `text/event-stream` | 200 | Cited policy RAG streaming via SSE |

---

## 2. Pydantic V2 Schemas (`src/models/schemas.py`)

### 2.1 Ingest & Telemetry
- `TelemetryPosition`: `latitude` (-90..90), `longitude` (-180..180), `accuracy_m` (>= 0 or `null` when the source does not report accuracy). The key remains required so unknown accuracy is explicit; do not substitute a guessed value.
- `TelemetryPayload`: `position`, `speed_mps`, `bearing_deg`, `app_state`, `network_state`, `gps_state`, `mock_location_reported`.
- `TelemetryEventEnvelope`: Strict adherence to `telemetry-event.schema.json` with `schema_version=1`, `event_id`, `event_type`, `occurred_at`, `trip_id`, `assignment_id`, `driver_id`, `sequence`, `payload`.

Road coordinates are WGS84 longitude/latitude even when producer documentation calls the shape `latlon`/`namedlatlon`; persisted geometry is WKT/PostGIS `lon lat`. Time is UTC ISO-8601 with `Z`; distance is metres; speed is metres per second. Both route legs are assignment-linked. Synthetic variants are normal, stall, directed reverse, traffic, and technical dropout. Gaps and unavailable provider/traffic evidence remain explicit; fallback geometry or traffic is invalid. Evaluation labels are excluded recursively from model input.

`POST /api/v1/telemetry/ingest` is idempotent by event identity and payload hash: exact duplicate replay returns the prior result; changed duplicate returns `409 Conflict`. Dataset seeding is additive/preserving and cannot globally delete unrelated records.

### 2.2 Case Queue, Dossier, Forensic Brief & Case Policy
- `FraudCaseSummary`: `id`, `trip_id`, `assignment_id`, `driver_id`, `status`, `priority`, `priority_score`, `category`, `confidence`, `opened_at`, `updated_at`.
- `ForensicAbnormality`: `code`, `field`, `observed_value`, `threshold_or_baseline`, `description`.
- `ForensicBriefResponse`: `case_id`, `trip_id`, `driver_id`, `category`, `abnormalities` (`list[ForensicAbnormality]`), `telemetry_summary`, `trip_context`, `guardrail_observations`, `summary_text`, `generated_at`. Strictly reports measured telemetry and trip abnormalities without fabricating metrics or issuing a verdict.
- `CasePolicyClause`: `clause_id`, `title`, `section`, `violation_code`, `content`, `relevance_reason`, `source_doc`.
- `CasePolicyResponse`: `case_id`, `category`, `violation_code`, `applicable_clauses` (`list[CasePolicyClause]`), `guardrail_clauses` (`list[CasePolicyClause]`), `precedent_rules`, `summary`.
- `CaseDetailResponse`: Full composite object with `case`, `trip`, `telemetry_samples`, `features`, `assessment`, `route_geometry`, `guardrails`, `active_lease`, `forensic_brief`, `case_policy`.

### 2.3 Actions & Adjudication
- `ClaimCaseRequest`: `analyst_id`, `lease_duration_seconds` (default 300).
- `CaseActionRequest`: `action_type` (`REQUEST_EVIDENCE` | `DEFER`), `analyst_id`, `notes`.
- `AdjudicationRequest`: `outcome` (`AGREE` | `DISAGREE`), `analyst_id`, `rationale` ($\ge 10$ non-whitespace characters), `expected_case_version`, `policy_version_id`, `snapshot_hash`.

---

## 3. Persistence & Supabase Integration (`src/services/`)

### 3.1 Supabase Client & Database Service (`src/services/supabase.py`)
- Reads `NEXT_PUBLIC_SUPABASE_PROJECT_ID` (or `NEXT_PUBLIC_SUPABSE_PROJECT_ID`) and `SUPABASE_SECRET_KEY` from configuration / environment.
- Configures PostgREST base endpoint: `https://{project_id}.supabase.co/rest/v1`.
- Provides unified repository access:
  - Connects to Supabase PostgREST or direct PostgreSQL connection pool with fallback to local seeded SQLite / in-memory repository for unit tests.
  - Exposes `CaseRepository`, `TelemetryRepository`, `AdjudicationRepository`, `PolicyRepository`.

### 3.2 Mock Data & Seeder
- Pre-packaged scenario data based on `data/synthetic/seed_data.json` covering:
  - `intentional_dic`: High confidence ERR-02 (intentional route stall/delay).
  - `traffic_gridlock`: Congestion false-alarm with heavy traffic guardrails.
  - `technical_dropout`: Network/GPS loss technical guardrail advisory signal marking Disagree (System Error).
- Ready for automated testing with zero external API dependencies.

## Knowledge base and agent config API (ADR-032)

Prefix `/api/v1`. Roles and lifecycle are in [ADR-032](adr-032-knowledge-base-roles-and-lifecycle.md). `/knowledge/*` needs analyst, fraud_analyst, senior_analyst or admin (formulas are detection logic); `/agent-config` and `/knowledge/registry` also allow `manager`/`reviewer`. Errors: 401 no session, 403 role or four-eyes, 404 unknown/other-org, 409 illegal lifecycle state, 422 validation (`detail` is a string or `{message, errors:[{path, code, message, position?}]}`).

| Method and path | Purpose |
|---|---|
| `GET /knowledge/meta`, `GET /knowledge/parameters` | Types/tools/reject reasons; parameter catalogue (unit, source, owner, latency, kind `case|policy`). |
| `POST /knowledge/formula/validate` `{formula}` | `{ok, errors, warnings, used_params, sample}`: syntax, unknown parameter, unit mismatch, constant division by zero. |
| `GET /knowledge/objects?type&status&q` | All versions (one row per version). |
| `POST /knowledge/objects` `{type, code, name, scope, body}` | Create draft v1 (409 if code exists). |
| `GET|PUT /knowledge/objects/{id}`, `GET /knowledge/objects/{type}/{code}/versions` | Read; edit draft/ready_for_test only. |
| `POST /knowledge/objects/{id}/{clone,submit,trial,publish,retire,rollback,preview}` | Lifecycle. `publish {override_reason?}` needs approver != author; `retire`/`rollback {reason}`; `preview {case_ids?, params?}`. |
| `POST /knowledge/similar` `{text, type?}` | Token-overlap similarity over non-retired objects. |
| `GET /knowledge/registry` | Agents: instruction version, model, tools, memory layers, knowledge types and published counts, kill-switch state. |
| `GET|POST /knowledge/documents` | Policy document metadata + text; `indexing_status`. |
| `GET|POST /knowledge/proposals`, `POST /knowledge/proposals/{id}/{accept,edit,reject}` | Review queue; reject needs `reason_code` in `wrong_source|wrong_motive|duplicate|out_of_scope|other`. |
| `POST /knowledge/seed` | Admin only, idempotent demo content. |
| `GET /agent-config?scope`, `PUT /agent-config/{key}` `{value, reason, scope}` | Values with bounds/owner/`can_edit`; bounded writes. |
| `GET /agent-config/history/list?key`, `POST /agent-config/history/{id}/revert`, `POST /agent-config/kill-switch` `{enabled, reason}` | History, revert, kill switch. |

## Driver explanation agent v2 API (ADR-034)

Prefix `/api/v1`. Driver routes need role `driver` and the driver's own case (otherwise 404). Analyst and help routes need analyst-family or VH roles (403 otherwise). Errors: 409 wrong state (`detail.code` is `not_asking`, `waiting_for_help`, `no_pending_question`, `not_in_summary`, `edit_limit`), 422 `{code:"form_invalid", missing:[fieldId], invalid:[{field, code}]}`.

**Driver session view** (every driver endpoint returns it): `{session_id, case_id, state: draft|investigating|asking|summary|submitted, ui_status: form|checking|chat|summary|submitted, mode: agent|fallback, reason, form: {reason, form_version, has_question_set, fields:[{id, label:{vi,en}, type: text|time|location|choice|amount|photo|ticket, required, options?:[{value,label}]}], answers:{id:value}}, messages:[{seq, role: agent|driver, kind, text, at, is_summary}], current_question:{seq,text}|null, waiting_for_help, can_end, summary|null, edits_left, status_text:{vi,en}|null, submitted_at, last_interaction_at, idle_timeout_minutes}`.

| Method and path | Purpose |
|---|---|
| `POST /driver/cases/{id}/explain/start` `{reason}` | Reason in `NotDone|RealTrip|Tech|Customer|Other`; creates the session or, in `draft`, rebuilds the form. Kill switch off -> `mode: fallback` (no dynamic questions, no agent). |
| `GET /driver/cases/{id}/explain` | Current view; lazily resolves help replies/expiry and the T-minute auto-submit. |
| `PUT /driver/cases/{id}/explain/draft` `{answers}` | Save draft answers (unknown ids ignored). |
| `POST /driver/cases/{id}/explain/submit` `{answers}` | Validate required/typed fields, store statement v1, investigate, assess round 1; `asking` or `submitted`. |
| `POST /driver/cases/{id}/explain/answer` `{text, attachments?, ticket_code?}` | Answer the current question (409 `waiting_for_help` while VH is consulted). |
| `POST /driver/cases/{id}/explain/end` | End early -> `summary`. |
| `POST /driver/cases/{id}/explain/summary/edit` `{text}` / `.../summary/confirm` | Edit (<= `edit_limit`) / confirm -> round 2, `submitted`. |
| `GET /cases/{id}/explain` | Analyst view: `{session, flags{6}, form, statement_versions[], rounds[], transcript[], provenance[{type,code,version,tool,turn_seq,at}], similar_scenarios[<=3], plan, open_points, suggestion{round,state,reason_code,confidence,motive,suggested_questions,turns_used,n_max}, help_requests[], feedback[]}`. |
| `POST /cases/{id}/explain/feedback` `{verdict: agree|disagree, error_types[], comment}` | `disagree` needs >= 1 of `wrong_facts|wrong_reasoning|missing_question|redundant_or_tone|missing_tool_source|wrong_scenario_or_workflow`. |
| `GET /explain/help-requests?status=open,claimed`, `GET .../count` | Queue (oldest first) with `counts{open,claimed,total}`; count is the badge. |
| `GET /explain/help-requests/{id}`, `POST .../{id}/claim`, `POST .../{id}/reply` `{text, facts[]}` | Detail with transcript; exclusive claim (409); reply continues the agent and creates a pending knowledge proposal. |
| `GET /explain/meta` | Error types, assessment states, flag names. |

## Tester API design extension

The proposed canonical Tester namespace is `/test/api/v1`; it is separate from the implemented `/api/v1` contracts above and has no unprefixed alias. See [Tester request/response and event contracts](TESTER_API_SPECIFICATION.md) and [runtime architecture](TESTER_SIMULATION_ARCHITECTURE.md). All operations require authenticated, run-scoped authorization and isolated test infrastructure. These documents specify future implementation, not available endpoints.

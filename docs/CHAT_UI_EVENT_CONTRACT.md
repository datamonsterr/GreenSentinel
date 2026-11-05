# Chat UI Event Contract v1.0 — Lead Handoff

Status: implementation-ready contract for Lead review. This deliverable defines and validates the wire format; it does not implement backend streaming, UI reducers, navigation, or renderers. Lead acceptance has not been recorded.

## Deliverables

- [JSON Schema](CHAT_UI_EVENT.schema.json): Draft 2020-12, strict event payloads.
- [Synthetic sample payloads](CHAT_UI_EVENT_SAMPLES.json): success, tool failure, and empty-result streams.
- [Offline validator](../eval/validate_chat_ui_events.py): schema and cross-event lifecycle checks.
- [Contract tests](../tests/test_chat_ui_contract.py): valid fixtures and invalid-event rejection.

## Step 1: Use one envelope

Every event contains all eight fields:

| Field | Contract |
|---|---|
| `schema_version` | Exactly `1.0`; never silently interpret another version |
| `event_id` | Unique per event; unchanged when replaying the same event |
| `run_id` | One assistant generation; retries start a new run |
| `message_id` | Assistant message receiving the output |
| `sequence` | Zero-based integer, strictly increasing by one within a run |
| `timestamp` | Server emission time, UTC with exactly millisecond precision: `2026-09-24T10:00:00.000Z` |
| `type` | Discriminator selecting exactly one payload shape |
| `payload` | Typed object for that event; no unspecified fields |

IDs are opaque, case-sensitive identifiers, not display names. UUIDs and existing prefixed IDs are supported. Do not infer identity from a driver name or parse links from prose.

## Step 2: Dispatch to renderers

| Renderer | Event type | Required behavior | Sample location |
|---|---|---|---|
| Thinking indicator | `status.thinking` | Show the selected progress label; clear on first text or terminal event | `streams[0].events[0]` |
| Tool activity | `tool.start`, `tool.end` | Match by `tool_call_id`; render pending, success, or failure independently for parallel calls | `streams[0].events[1..2]`, `streams[1]` |
| Driver link | `driver.link` | Show label and resolve `open_driver` with `driver.driver_id` | `streams[0].events[3]` |
| Case list | `case.list` | Render keyed rows, empty state, and cursor-based load-more | `streams[0].events[6]`, `streams[2].events[0]` |
| Route map | `routes` | Replace route snapshot, select matching route ID, fit valid geometry, render empty state | `streams[0].events[7]`, `streams[2].events[1]` |
| Assistant text | `text.delta` | Append delta exactly once, preserving whitespace | `streams[0].events[8]` |
| Run completion/error | `run.completed`, `run.error` | Stop loading; retain partial content; expose retry for retryable errors | Last event in each sample stream |

Five requested renderers plus text and terminal states have concrete fixtures. All sample identities and route data are synthetic.

### Thinking and tools

Thinking labels are restricted to `Reviewing request`, `Looking up records`, and `Preparing response`. Map these to localized strings on the client if needed. Never serialize private reasoning, scratchpads, prompts, raw arguments, credentials, or raw tool responses into these events.

Each started tool gets a distinct call ID, including repeated calls to the same tool. A tool end must match its start's name and ID and can appear only once. `duration_ms` comes from a monotonic execution timer; do not derive it from wall-clock timestamp subtraction. A failed tool end includes a safe error object and may be followed by recovery, another tool, or a terminal run error. Tool success includes a concise summary; rich output uses a separate renderer event.

`status.thinking` must originate when work begins. Existing post-hoc reasoning text cannot be presented as real-time execution evidence. Do not invent tool starts/ends when only a final answer is available.

### Driver and case linking

`driver.link` contains a canonical `driver_id`, display name, label, and allowlisted action `open_driver`. The client resolves that ID through its navigation/controller layer. The event does not supply a URL or assert that a driver page already exists. The receiving view must re-check access; for missing or forbidden records, show an unavailable state rather than falling back to another driver.

Each case row has a case ID, driver reference, category, status, priority, summary, and `updated_at`. Selecting a row dispatches `open_case(case_id)` through the UI controller. Case IDs must be unique within a page. `list_id` identifies a query result across pages; replace when it changes, otherwise append unseen case IDs when the user requests the next cursor. `next_cursor: null` means no more pages; `total_count: null` means unknown. Adapters must explicitly map any additional backend status to this contract or reject it; never silently rename unknown states.

### Routes and timestamps

`routes` contains a full replacement snapshot for one case and driver. Each route uses a GeoJSON-shaped `LineString`, with coordinate pairs in **longitude, latitude** order (WGS84 decimal degrees). At least two positions are required. Distances are meters, durations seconds, and tool execution durations milliseconds. `selected_route_id` is null or references one route in that snapshot. Empty arrays explicitly clear the displayed routes.

`timestamp` means event emission; `observed_at` means route observation; `updated_at` means last case update. Never substitute one for another. Display time with the user's locale and selected time zone (for example, Asia/Bangkok); retain UTC in state and exports. Use `sequence`, not timestamps, for ordering: clock corrections can move timestamps backward. Missing required timestamps must be fixed upstream, not fabricated as the current time.

## Step 3: Implement the stream lifecycle

Topology: user submits chat request; FastAPI owns the run envelope and ordered event writer; agent orchestration invokes service tools; tools return validated domain data; the writer projects authorized data into renderer events; a frontend reducer dispatches by `type`.

Proposed run state: `run_id`, `message_id`, `next_sequence`, pending tool IDs, emitted event IDs, and terminal status. Existing LangGraph node names and edges are not changed by this document. Instrument actual tool invocation boundaries, not model prose; conditional tool failure can recover or end the run according to orchestration policy.

1. Assign run/message IDs before starting the generation; emit a thinking event.
2. Emit tool start before invocation; validate tool inputs using the existing tool schema.
3. Catch execution errors at the tool boundary and emit a safe failed tool end. Do not stream stack traces.
4. Emit successful tool end and relevant driver, case, route, or text events.
5. Emit exactly one terminal event: `run.completed` with completed/cancelled status, or `run.error`.

A successfully completed run cannot leave tools pending. Cancellation or a run error closes pending tool indicators as interrupted. No events may follow a terminal event. A stale event from a cancelled/previous run must never modify the active message.

Transport proposal: opt in with `event_schema_version: "1.0"` in the chat request before returning v1 events. Backend request validation and client support must be implemented together. The existing endpoint does not currently accept this negotiation field. Preserve the existing stream for unnegotiated requests.

SSE framing:

```text
id: evt_mock_000
event: status.thinking
data: {"schema_version":"1.0","event_id":"evt_mock_000","run_id":"run_mock_001","message_id":"msg_mock_001","sequence":0,"timestamp":"2026-09-24T10:00:00.000Z","type":"status.thinking","payload":{"label":"Reviewing request"}}

```

SSE event name and ID must equal JSON `type` and `event_id`. Assemble full frames across network chunks before parsing JSON. Deduplicate replayed event IDs before the reducer. Reject conflicting duplicates or sequence gaps; mark the stream interrupted and offer explicit retry. A closed connection without a terminal event is interrupted, not completed. A terminal callback must fire once. V1 does not promise server replay/resume support: retries create a new run unless a separate replay protocol is implemented. The offline validator checks complete fresh streams; replay deduplication belongs to the transport adapter.

## Step 4: Adapt existing contracts explicitly

The inspected working branch has two incompatible paths: [policy SSE](../src/services/case_service.py) emits `reasoning`, `citation`, `text_delta`, and `done`; [structured chat](../src/models/schemas.py) returns a final `StructuredCockpitResponse`. The [SSE client](../src/webapp/lib/api-client.ts) does not dispatch thinking, tool, driver, route, or case-list events. These are integration gaps, not features delivered by the schema.

| Existing data | Proposed adapter |
|---|---|
| `reasoning.thought`, `thought_process` | Do not forward; emit allowlisted progress from actual lifecycle |
| `text_delta.delta` | Wrap as `text.delta.payload.delta` |
| `done` or network EOF | Map explicit successful done once; EOF alone means interrupted |
| `driver_card` | Project only authorized ID/name into driver link; retain card details in the legacy renderer |
| Queue `{items,total,limit,offset}` | Map `id` to `case_id`; server adapter owns opaque cursor translation, never pretend offset is already a cursor |
| `RouteCandidate` with `id,name,coordinates` | Map to `route_id,label,geometry`; require real provenance and observation time; do not fabricate missing timestamps |

Existing citation, driver-history, and forensic cards are outside this basic v1 contract. Keep their legacy path intact; do not enable v1 for workflows that require those renderers until a reviewed extension preserves them. Existing map metadata such as rank, congestion, and colors is likewise not transmitted by this minimal contract. The new map renderer must derive presentation defaults and not cast the payload to the old `RouteCandidate` type.

## Step 5: Validate and hand off

```powershell
python -m eval.validate_chat_ui_events
python -m unittest tests.test_chat_ui_contract -v
```

Use both JSON Schema validation with format checking and the lifecycle validator. JSON Schema alone cannot ensure paired tools, referential integrity, or terminal ordering. UI tests should exercise all fixtures, stream chunk splits, duplicate replay, interrupted EOF, parallel calls, stale runs, and denied driver navigation.

Lead review checklist:

- [ ] Accept event names, units, timestamp semantics, and identity fields.
- [ ] Assign backend owner for event projection and version negotiation.
- [ ] Assign frontend owner for reducer, navigation resolution, and renderers.
- [ ] Confirm legacy citation/history/forensic behavior remains available during rollout.
- [ ] Accept basic route scope and pagination adapter requirements.
- [ ] Run contract tests in CI; require renderer fixtures before enabling v1.

Decision: strict discriminated payloads with semantic entity IDs. Loose arbitrary tool JSON was rejected because renderers would infer shape, units, and navigation. Breaking changes require a new major version; even additive event types/fields require explicit client negotiation because unknown fields are rejected in v1.0.

Security: authentication and authorization remain server-side on stream and linked entities. Apply existing request limits and rate limiting before streaming. Redact sensitive data before projection, escape text, and never render tool labels as raw HTML. No raw credentials, model reasoning, arbitrary navigation URLs, or automatic adjudication actions are part of this contract.

---

## Step 6: Driver Answer Formatter Block Contract (v1.0)

For GSupport driver-facing interactions (Slice 10 / Issue #484), final responses are structured into natural-language markdown accompanied by typed display blocks rendered by dedicated client components.

### 1. Payload Schema

Every formatted driver response conforms to `{markdown: string, blocks: Block[]}`:

```json
{
  "markdown": "GSupport đã tiếp nhận thông tin và kiểm tra dữ liệu.",
  "blocks": [
    {
      "type": "case_card",
      "case_id": "018f2f4e-b000-7000-8000-000000000001",
      "title": "Kiểm tra lộ trình bất thường",
      "status_key": "under_review"
    },
    {
      "type": "trip_card",
      "trip_id": "trip_001",
      "pickup": "Hồ Gươm",
      "destination": "Cầu Giấy",
      "fare_vnd": 85000
    },
    {
      "type": "table",
      "columns": ["Thời gian", "Sự kiện", "Chi tiết"],
      "rows": [
        ["14:30", "Bắt đầu chuyến", "Đón tại Hồ Gươm"],
        ["14:45", "Ùn tắc Kim Mã", "Vận tốc < 5km/h"]
      ]
    },
    {
      "type": "list",
      "items": [
        {"label": "Hồ sơ vụ việc #018F", "href": "case://018f2f4e-b000-7000-8000-000000000001"},
        {"label": "Chính sách Điều 12.2", "href": "policy://c12_2"},
        {"label": "Cổng hỗ trợ GreenSM", "href": "https://greensm.vn/help"}
      ]
    },
    {
      "type": "link",
      "label": "Hướng dẫn thủ tục khiếu nại",
      "url": "https://greensm.vn/help"
    },
    {
      "type": "status_pill",
      "status_key": "under_review"
    },
    {
      "type": "evidence",
      "items": [
        {
          "kind": "traffic",
          "summary": "Ùn tắc cục bộ Kim Mã, tốc độ trung bình 4km/h",
          "source": "Peer GPS"
        }
      ]
    },
    {
      "type": "next_steps",
      "items": [
        {
          "label": "Gửi giải trình",
          "prompt": "Tôi muốn gửi giải trình về sự cố kẹt xe đường Kim Mã"
        }
      ]
    },
    {
      "type": "confirmation",
      "action": "submit_statement",
      "checklist": [
        {"key": "incident_type", "ok": true},
        {"key": "description", "ok": true},
        {"key": "evidence", "ok": true}
      ],
      "summary": "Ùn tắc đường Kim Mã do tai nạn, đi vòng theo hướng dẫn CSGT"
    }
  ]
}
```

### 2. Block Type Definitions

| Block `type` | Required fields | Optional fields | Invariants / Restrictions |
|---|---|---|---|
| `case_card` | `type`, `case_id`, `title` | `status_key` | `case_id` must be whitelisted (unwhitelisted dropped). `status_key` is optional (omitted when unknown, no default value); when present must match `^[a-z][a-z0-9_]*$` with raw `ERR-0x`/`ERR_0x` codes stripped. |
| `trip_card` | `type`, `trip_id`, `pickup`, `destination` | `fare_vnd` (integer/number) | `trip_id` must be whitelisted (unwhitelisted dropped). `fare_vnd`, `pickup`, and `destination` are deterministically grounded from tool execution outputs. |
| `table` | `type`, `columns` (string[]), `rows` (string[][]) | — | >= 3 items or comparative metrics. Each row length must strictly match column count (`len(row) == len(columns)`). |
| `list` | `type`, `items` (`{label, href}`[]) | — | `href` scheme must be `case://`, `trip://`, `policy://`, or `https://`. Target entity IDs must be whitelisted. Empty lists dropped. |
| `link` | `type`, `label`, `url` | — | Whitelisted `case://`, `trip://`, `policy://`, or `https://` only (`http://` strictly prohibited). |
| `status_pill` | `type`, `status_key` | — | Normalized lowercase snake_case status (`^[a-z][a-z0-9_]*$`). Raw `ERR-0x`/`ERR_0x` codes prohibited and dropped. |
| `evidence` | `type`, `items` (`{kind, summary, source}`[]) | — | `kind` strictly in `weather`, `traffic`, `telemetry`, `policy`. Deterministically generated from tool execution evidence. |
| `next_steps` | `type`, `items` (`{label, prompt}`[]) | — | `label` max 40 chars. Client renders as actionable chips that dispatch `prompt` to chat input. |
| `confirmation` | `type`, `action` (`acknowledge` \| `submit_statement`), `checklist` (`{key, ok[, label]}`[]), `summary` | `label` on checklist items | `action` strictly in `acknowledge`, `submit_statement` (unknown actions dropped). `checklist[].key` strictly in `incident_type`, `description`, `evidence`. Raw internal codes stripped from `summary` and `label`. |

### 3. Critical Invariants

1. **Deterministic Grounding & Tool Provenance**:
   - `case_card`, `trip_card`, and `evidence` blocks are built deterministically from the agent's `ToolMessage` outputs (case context, trip/telemetry, weather/traffic tool results) collected from `final_state` messages.
   - LLM formatter output may only contribute `markdown`, `table`, `list`, `link`, and `next_steps`.
   - Any LLM-emitted `fare_vnd`, `pickup`, `destination`, or `evidence` not traceable to tool output is dropped.
   - `fare_vnd` is optional on `trip_card`; omitted if missing or non-positive in tool data.
   - `status_key` is optional on `case_card`; omitted when unknown (never default to a fake or guessed status).

2. **Entity Whitelisting**:
   - Entities outside the authenticated driver's scope (unwhitelisted `case_id`, `trip_id`, or citation IDs) are strictly dropped.
   - Canonical case aliases (`canonical_id`) are resolved for whitelisting.
   - `policy://` citations returned from `query_driver_policy` tool results are whitelisted.
   - Blocks referencing invalid entities are omitted rather than emitting mock or broken links.

3. **Raw Code & Identifier Sanitization**:
   - Internal error codes (`ERR-01` through `ERR-05`, `ERR_01` through `ERR_05`) are stripped from `markdown`, block titles, and `status_key`.
   - Bare UUIDs in markdown are sanitized to human-readable entity labels with short hash suffixes (e.g. `Tài xế #018F` / `Driver #018F`, `Chuyến đi #018F` / `Trip #018F`, `Vụ việc #018F` / `Case #018F`) respecting the turn's `locale`.
   - `status_key` must match `^[a-z][a-z0-9_]*$` else dropped.

4. **Fallback & Fault Tolerance**:
   - On provider timeout (>15s), provider exception, or unparseable JSON, the formatter gracefully falls back to `{markdown: sanitized_raw_answer, blocks: []}` with raw error codes, bare UUIDs, and unwhitelisted links stripped, without crashing the agent stream or dropping the conversation turn.

5. **Bilingual Locale Support**:
   - Formatter supports `locale` parameter (`"vi"` or `"en"`), using the appropriate system instructions in `src/agents/prompts/answer_formatter_driver.md` and localized entity labels for UUID sanitization.

### 4. Driver Chat SSE Streaming Lifecycle

The driver chat streaming endpoints (`GET /api/v1/driver/cases/{case_id}/chat/stream`,
`POST /api/v1/driver/cases/{case_id}/chat/stream`, and the case-less
`POST /api/v1/driver/chat/stream` — Issue #482) emit sequential SSE events.
The case-less route has no `case_id`; driver identity comes exclusively from the
authenticated principal, and the agent resolves the driver's cases via the
`list_my_cases` tool. Both routes stream the real GSupport agent reply (see
[ADR-029](architecture/adr-029-caseless-driver-chat-and-real-agent-reply.md)):

1. **`tool.start`** event: Emitted before each tool execution as the agent invokes scoped driver tools.
   Labels are natural-language, localized, and i18n-friendly (no raw tool names exposed to drivers).
   ```text
   event: tool.start
   data: {"tool_call_id": "call_123", "name": "corroborate_traffic_conditions", "label": "Đang đối soát tình trạng giao thông"}
   ```

2. **`tool.end`** event: Emitted when tool execution concludes with execution status (`ok` or `error`).
   ```text
   event: tool.end
   data: {"tool_call_id": "call_123", "name": "corroborate_traffic_conditions", "status": "ok"}
   ```

3. **`token`** events: Emitted during streaming generation for real-time markdown text rendering.
   ```text
   event: token
   data: {"token": "Xin ", "delta": "Xin ", "case_id": "018f2f4e-b000-7000-8000-000000000001"}
   ```

4. **`blocks`** event: Emitted after the final text tokens, containing the grounded and sanitized typed display blocks from `run_driver_support_agent`.
   ```text
   event: blocks
   data: {"case_id": "018f2f4e-b000-7000-8000-000000000001", "blocks": [{"type": "case_card", "case_id": "018f2f4e-b000-7000-8000-000000000001", "title": "Kiểm tra lộ trình bất thường"}]}
   ```

5. **`done`** event: Emitted once generation and block production are complete, containing the full response and dispute metadata.
   ```text
   event: done
   data: {"status": "completed", "case_id": "...", "driver_id": "...", "reply": "...", "dispute_status": "under_review", "is_auto_dismissed": false, "exoneration_receipt": null, "needs_analyst_review": true, "blocks": [...]}
   ```

6. **`error`** event: Emitted if the agent pipeline fails, followed by stream closure.
   ```text
   event: error
   data: {"message": "Agent request failed", "status": "error"}
   ```




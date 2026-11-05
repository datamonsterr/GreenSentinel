# Tester simulation workspace design

**Status:** Proposed design for Epic #130 / documentation #131. No runtime delivery claim. The user confirmed isolated test storage and sandbox notifications with the existing Workplace layout on 2026-10-04. [Discovery](../../ba/DISCOVERY_TESTER_TRIP_SIMULATION.md) supplies FR-TST-01–08; the [API contract](../../architecture/TESTER_API_SPECIFICATION.md) owns wire names and server semantics.

## Design intent and preview

A trip is the central object. The largest surface shows its geography and motion; Driver and Passenger remain visible together at the left; tools occupy their own right column. The results area below the map shows only consumed system events. This lets a Tester distinguish what they authored, what the pipeline received, and what the system actually concluded.

Open [preview.html](preview.html) for the self-contained responsive mockup or [preview.svg](preview.svg) for the static composition. Both are illustrative. Locations, dialogue and route marks demonstrate layout only; they are not geographic, routing or pipeline evidence. The preview makes no network calls and runs no simulation. Its layout-state controls and tooltips only demonstrate interaction.

Stitch MCP was absent from the available tool inventory on 2026-10-04. No Stitch screen was generated or inspected. Required follow-up before application coding: generate/query the screen in Stitch when available, attach its screen identifier and visual, compare it with this draft, and obtain user visual confirmation. Draft documentation can be reviewed now. This implements the AGENTS.md design gate, not a claim that the mockup has passed product UAT.

## Layout and routes

- `/test`: plan list and new plan entry; entering a saved plan opens the same simulator surface.
- `/test/plans/{plan_id}`: editor with persistent deep link and unsaved-change indication.
- `/test/runs/{run_id}`: live or historical run with immutable plan revision and actual results.
- `/test/workplace`: existing Workplace layout and assignment flow backed exclusively by the isolated test client. A case link carries `case_id` and `run_id` context. No mandatory TEST badge on each case. The route and workspace heading identify the environment.
- All simulator and test Workplace network operations resolve under `/test/api/v1`; a route prefix alone is not storage isolation.

```text
┌ GreenSM / Trip studio      Isolated workspace      Saved    Run controls ┐
├────────────────┬───────────────────────────────────────┬────────────────┤
│ Driver         │ Map: origin → pickup → destination     │ Trip / Traffic │
│ Notifications  │                                       │ / Faults       │
│ Conversation   │ Route selection + GPS inspection      │                │
│ Reply composer │                                       │ Named fields   │
├────────────────┤                                       │ + units + help │
│ Passenger      ├───────────────────────────────────────┤                │
│ Notifications  │ Playback / selected point metrics     │ Save / Validate│
│ Conversation   ├───────────────────────────────────────┤                │
│ Reply composer │ Actual results / event history        │ Plan summary   │
└────────────────┴───────────────────────────────────────┴────────────────┘
```

Desktop ≥1280px: 264px actor rail, flexible map (`minmax(480px,1fr)`), 300px tools; 12px gutters and 16px outer inset. Map gets remaining width and at least 380px height. Actor windows share equal height and scroll independently; composers stay in their own panel. Results can expand below the map without covering tools. At 1024–1279px: 232px actors plus map; tools move into a labelled disclosure below the map, never overlaying actors. At 768–1023px: actors remain stacked left (224px), map right, tools and results follow in document order. Below 768px: one document column, jump links to Map, Driver, Passenger, Tools and Results; no simultaneous-window promise on small screens. Preserve drafts during responsive changes. Support 200% zoom without lost controls; overflow is local to long event tables, with a list alternative.

## Visual system

Reuse `src/webapp/app/globals.css`, its Inter/system sans stack and existing Tailwind theme. The UI/UX skill's generic transport query suggested a marketing hero; that pattern does not fit this operations surface. A narrower product query had no match. The recommendations here derive from repository tokens and the skill's general accessibility guidance, not a verified transport template.

| Existing primitive | Semantic use | Component use |
|---|---|---|
| `#006948` primary | Committed primary action / selected route | Run button; active tool indicator |
| `#f8f9ff` surface | Workspace background | Simulator shell |
| `#ffffff` surface-container-lowest | Editable/inspectable surface | Actor and tools panels |
| `#0b1c30` on-surface | Primary text | Headings, metric values |
| `#565e74` secondary | Secondary text | Source/time labels and help |
| `#0058be` tertiary | Passenger identity and selection | Passenger icon, point inspector |
| `#ba1a1a` error | Actionable failure | Inline validation and retry panel |

Use semantic aliases in components, no new independent palette. Use 4/8/12/16/24px spacing, 8px panel radius, 6px control radius, 16px body, 14px compact labels and 12px nonessential metadata. Headings 18–22px, weight 600–700. Keep text left aligned. Reserve monospace for coordinates and event IDs. Color is always paired with a label or shape; actor names remain explicit.

Lucide icons use consistent 18–20px strokes: `CarFront` Driver, `UserRound` Passenger, `MapPin` endpoints, `Route` route tool, `TrafficCone` congestion, `Satellite` GPS faults, `Bell` notifications, `MessagesSquare` conversation, `Play`/`Pause`/`Square` controls, `CircleHelp` help, `ExternalLink` Workplace, `RotateCcw` clone/replay. Existing `components/ui/button.tsx`, `card.tsx`, `badge.tsx`, `skeleton.tsx` and `chat-widgets.tsx` are the starting primitives. A shadcn-compatible Tooltip/Popover may be added after checking the dependency graph; the current package does not establish a ready-made tooltip dependency.

## Component ownership and reuse

```text
TestWorkspaceShell (test auth + immutable test client context)
├── TestWorkspaceHeader / RunControls
├── ActorRail
│   ├── ActorWindow(role=driver)
│   │   ├── ActorNotificationInbox
│   │   ├── ActorConversation
│   │   └── ActorReplyComposer
│   └── ActorWindow(role=passenger) (same composition)
├── SimulationMapEditor
│   ├── MapLibreView (existing rendering primitives)
│   ├── MapEditToolbar / AccessibleCoordinateEditor
│   ├── SegmentSelector / PointInspector
│   └── RunTimeline / MetricStrip
├── SimulationToolsPanel
│   ├── TripPlanFields / RouteCandidatePicker
│   ├── TrafficSegmentEditor
│   ├── FaultEditor
│   └── PlanValidationSummary
└── ActualResultsPanel / RunEventLog / WorkplaceCaseLink
```

Existing `MapLibreView` accepts route geometry, breadcrumbs, driver/customer locations, traffic and telemetry props but lacks plan-edit callbacks. Add a focused editor wrapper and additive selection/edit hooks; retain coordinate order `[longitude, latitude]` at MapLibre's seam. Do not overload evidence-rendering props with silently generated coordinates. Reuse `lib/telemetry-playback.ts` and validate road/time semantics before extending it.

Existing `CockpitWorkspaceView` imports functions from the global `lib/api-client.ts`; mounting it beneath a new route does not isolate requests. Introduce an explicit client dependency at the workspace seam, with the existing client as the production default. The test client must cover queue/detail, claims, actions, agent sessions, chat/stream, policy, accounts and delegated Driver flows before reuse can pass isolation acceptance. Do not mutate a module-global base URL when switching tabs. Preserve authentication, abort handling, and `lib/chat-event-stream.ts` parsing patterns.

## Proposed presentation types

These are UI view-model types, not a competing wire schema. Adapt validated API responses once at the test client seam; the API contract owns endpoint and event names. IDs are opaque strings. All times use explicit ISO timestamps at the transport seam; playback seconds are relative to the immutable run origin.

```ts
type ActorRole = "driver" | "passenger";
type RunPhase = "draft" | "validating" | "ready" | "starting" | "running"
  | "pausing" | "paused" | "stopping" | "completed" | "stopped" | "failed";
type RemoteState<T> =
  | { kind: "loading" }
  | { kind: "ready"; value: T; updated_at: string }
  | { kind: "unavailable"; reason: string; retryable: boolean }
  | { kind: "stale"; value: T; last_updated_at: string; reason: string };
type Metric =
  | { kind: "known"; value: number; unit: "m" | "s" | "m/s" | "ratio";
      reference: string; source: string; observed_at: string }
  | { kind: "unknown"; reason: string; reference: string };
type DialogueItem =
  | { kind: "draft"; local_id: string; role: ActorRole; text: string;
      origin: "manual" | "ai_draft"; edited: boolean }
  | { kind: "submitted"; message_id: string; role: ActorRole; text: string;
      submitted_at: string; consumed_event_id: string | null }
  | { kind: "system_notification"; notification_id: string; recipient: ActorRole;
      text: string; occurred_at: string; read_at: string | null };
interface ActorWindowProps {
  role: ActorRole;
  items: RemoteState<readonly DialogueItem[]>;
  draft: string;
  can_reply: boolean;
  reply_disabled_reason?: string;
  on_draft_change(text: string): void;
  on_submit_reply(): Promise<void>;
  on_retry(message_id: string): Promise<void>;
}
type SimulatorUiEvent =
  | { type: "endpoint_selected"; target: "origin" | "pickup" | "destination";
      longitude: number; latitude: number }
  | { type: "segment_selected"; segment_id: string }
  | { type: "sample_selected"; sample_id: string }
  | { type: "playhead_changed"; elapsed_seconds: number }
  | { type: "run_control_requested"; action: "start" | "pause" | "resume" | "stop" }
  | { type: "reply_requested"; role: ActorRole; draft_id: string };
interface MapEditorProps {
  mode: "edit" | "inspect";
  geometry: RemoteState<GeoJSON.LineString | null>;
  selected_sample_id: string | null;
  metrics: readonly Metric[];
  on_event(event: SimulatorUiEvent): void;
}
```

`RunPhase` describes display transitions; server lifecycle states remain authoritative. Map wire `QUEUED` to `starting`, `RUNNING` to `running`, `PAUSED` to `paused`, `CANCELLING` to `stopping`, `CANCELLED` to `stopped`, `COMPLETED` to `completed`, and `FAILED` to `failed`. `draft`, `validating` and `ready` describe editor state before creating a run; `pausing` is a pending command, never a persisted run state. Map wire actor `DRIVER`/`PASSENGER` to presentation role `driver`/`passenger`; render Tester-authored draft provenance separately rather than impersonating an actor in the transport. Reconcile pending phases after reload or timeout from the run endpoint, never infer successful execution from a button click. Action availability derives from server capabilities plus explicit disabled reasons.

## Trip, route, traffic and fault interactions

1. Place origin, pickup and destination with labelled map actions or the keyboard coordinate form. Show nearest-road snapping distance and require confirmation of material changes; keep authored and snapped coordinates in provenance.
2. Select a route candidate by labelled list or map. Show leg, source, calculation time, road distance and ETA. No usable route: keep the plan, explain unavailable routing, block ordinary road-following execution and offer retry; never draw a straight line as a successful road route.
3. Set start time with timezone, speed with unit, sampling cadence (selected baseline: 1 second; selectable slower intervals) and placement radius with its centre. Validate representative movement and explicit dropout exceptions before generator acceptance. Save and validate the complete plan before Start. Required missing fields are inline and collected in a focusable summary.
4. Traffic tool selects segments by list or map, independently sets congestion level/density and effective time. Historical response must show provider, observed time and coverage. Missing historical coverage stays unavailable until the user explicitly chooses a labelled simulated override.
5. Fault tool configures exactly the API catalogue `JUMP`, `OFFSET_NOISE`, and `DROPOUT`. Network and app failures are integration-test injection conditions, not additional approved user-facing controls. Deliberate off-road points and gaps remain visible as authored faults. A displayed injected fault is not evidence that the detector recognized it.
6. During execution, plan revision is read-only. Permitted live controls create timestamped commands; show pending, applied or rejected. Clone to edit/replay with a new run identity. Stop requires a brief confirmation stating the effect on unsent commands; completion of playback and completion of downstream analysis are separate statuses.

## Actor windows and notifications

Driver is upper left; Passenger (User) lower left. Each window has a named header, unread notification count, notification history, conversation, role-labelled composer and submit status. Notifications are persisted inbox items; temporary toast alone is insufficient. New messages use a polite announcement and a “New messages” jump control without stealing focus or forcing scroll when reviewing older content.

Manual or AI-assisted plan dialogue remains editable until submitted/scheduled into a run. AI drafts show “AI draft — review before sending” and never auto-send. After acceptance, preserve immutable submitted text and consumed-event reference; corrections create a new message. “Submitted” is distinct from “Consumed by pipeline”; a timeout is unresolved until the server reconciles the idempotency key. Retry uses the same intent/key. Actor role is fixed by the selected window and validated server-side; a text field cannot select another identity.

System notification receipts distinguish created, delivered to sandbox inbox, failed and unknown. Read/unread is presentation state unless an explicit server receipt contract is added. Sandbox delivery must never display an SMS/push-provider success without provider evidence. Notification click opens its related message/event and keeps an audit link; local read state does not claim provider delivery acknowledgement. Live replies are enabled only when allowed for that run and notification context. Unsent drafts survive temporary disconnect and changing tools.

## Metric and results truthfulness

- Point inspector: timestamp, selected position, accuracy, observed speed, route leg, source, reference and units. Hover and keyboard selection expose the same content; pinning keeps it available.
- Distances: road distance to pickup/destination versus straight-line placement radius are named separately. Every value identifies its start/reference point.
- Remaining distance: derive along the active route; an off-route sample is explicitly uncertain. DAVI reuses `src/services/feature_engineering.py`: distance-weighted cosine of approach movement against the straight-line direction toward pickup, ending at pickup arrival; segment starts within 20m of pickup are excluded by the current feature parameter. It is not a road-distance ratio. Show only with sufficient movement and the reference window; otherwise “Unavailable — insufficient movement.” A negative value is not intent proof. Do not substitute zero.
- ETA: show the calculation source and traffic time; a simulated ETA is visibly simulated. Missing historical traffic never appears as current historical evidence.
- Results: independent detection, notification, dialogue consumption and assignment rows with event IDs and timestamps. States include not started, pending, available, unavailable, failed and stale. “No case generated” is valid if the pipeline says so; it is not a frontend error or an invented successful detection.
- Case action: only render “Open in Workplace” after a returned case ID; assignment pending and assignment failed remain distinct. All links remain under `/test`. Assessments remain suspected/advisory; no automatic fine, suspension or guilt language.
- Playback is UI time. Worker progress is system time. Scrubbing never resubmits telemetry or dialogue, and a marker animation never implies new server events.

## Accessibility and state requirements

| Surface | Required behavior |
|---|---|
| Tooltip/help | Named `CircleHelp` button; show on hover and keyboard focus; Escape dismisses; hoverable and persistent while engaged; click/touch opens the same help. Essential instructions remain inline. |
| Buttons | Visible action label whenever space permits, accessible name for icons, 44×44px touch area, visible 2px focus ring, disabled reason adjacent or in described text. |
| Map | Every drag/place/segment action has keyboard/list/form equivalent; text summary of selected route and coordinates; Escape exits edit mode. |
| Tool tabs | `tablist`/`tab`/`tabpanel`, arrow-key navigation, Home/End, labelled headings; preserve form values. |
| Actor logs | Bounded polite live region for message arrivals; no repeated announcement of the entire history or every GPS tick. |
| Connection loss | Keep last known content labelled stale and timestamps; disable unsafe run controls; reconcile REST snapshot before accepting new commands. |
| Focus | Returning from tools/dialogs restores trigger focus; validation moves focus to error summary; stream updates never move focus. |
| Motion | Respect reduced motion; offer pause for playback; no flashing status; pending is text plus indicator. |
| Empty/loading/error | Skeleton only while loading; distinct “No messages yet”, unavailable and failed states; retry preserves authored data. |

SSE/fetch-stream lifecycle: one subscription per active run, abort on run change/unmount, deduplicate persisted event IDs, resume from acknowledged cursor, and reconcile REST after gaps. Authentication refresh follows the current authenticated fetch approach rather than relying on native EventSource custom headers. Malformed events produce a visible connection warning and telemetry, not a silently fabricated state. The API design must specify retention and cursor-expiry recovery.

## Verification handoff

Component tests cover keyboard tabs/tooltips, disabled reasons, independent actor drafts, unread behavior, errors/unknown metrics and idempotent UI submission. Map tests cover lon/lat conversion, list selection parity, no fabricated fallback, deliberate faults and source labels. Integration tests verify every `/test/workplace` call uses the isolated client and notification roles are server constrained. Browser tests cover compose→save→validate→run, disconnect/reload, actual results→case link and responsive/zoom navigation. Real backend and hosted UAT evidence remain separate from this static preview.

Visual sign-off must cover desktop 1440×1000, tablet 1024×900 and mobile 390×844, keyboard focus, touch help, both actor windows and map prominence. The one-minute goal requires timed UAT from composition to accepted trip submission; this preview measures no runtime latency. See the [test strategy](../../testing/TESTER_SIMULATION_TEST_STRATEGY.md) and [manual tests](../../testing/MANUAL_TEST_TESTER_SIMULATION.md) for complete AC-TST mapping.

## Preview verification evidence

On 2026-10-04 the self-contained HTML was opened with the repository Playwright/Chromium dependency. Desktop (1440px), tablet (1024px) and mobile (390px) checks found no document horizontal overflow. Click and arrow-key tool tabs, focus-triggered help, Escape dismissal and the explicit no-request action guard passed; external request count was zero. Desktop and mobile screenshots were captured in `/tmp/p063-tester-desktop.png` and `/tmp/p063-tester-mobile.png`. This is static-preview interaction evidence, not application or hosted UAT. The committed SVG is an authored snapshot, not a browser screenshot.

## Captured draft browser evidence

The standalone preview was inspected at 1440, 1024 and 390-pixel viewport widths: no horizontal page overflow, working click/keyboard tool tabs, focus explanations and Escape dismissal. The preview made zero network requests. [Desktop capture](preview-desktop.png) and [mobile capture](preview-mobile.png) show this draft only. They do not prove map provider loading, backend integration, actual notifications or product UAT.

**Review scope — 2026-10-04:** The stakeholder approved the draft architecture and UI preview for standalone report assembly. Stitch output and application-coding visual approval remain separate gates; report approval does not satisfy them.

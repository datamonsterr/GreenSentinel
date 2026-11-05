# Geoapify map and test console proposal

**Status: PROPOSED — requires user approval before application coding.** This is a design artifact, not a delivered console or a provider migration. The meaning of “replace our map with timeline currently” remains unresolved. The recommendation retains the evidence map and places its timeline directly beneath it; replacing the map with a timeline is not approved.

## Preview and provenance

Open [the SVG preview](preview.svg) or [its rendered PNG](preview.png). The desktop composition demonstrates a trip authoring workspace, selected playback time, source-aware route inspection, and contextual agent assistance. Every displayed route, location, duration, message and map mark is a design example. The illustration is not Geoapify tiles, geographic evidence, a live application, or a completed test run. The SVG makes no network requests and contains no provider credentials.

**Stitch screen generation unavailable in this session.** The callable tool inventory was inspected on 2026-10-08 and contains no Stitch tool. No Stitch screen identifier, screenshot, generation, or approval is claimed. The existing AGENTS.md requires a Stitch screen and user visual confirmation before application coding. Generate or retrieve the screen when Stitch is available, attach its real identifier, compare it against this proposal, and obtain confirmation. This document does not bypass that gate.

No README exists in `docs/`, `docs/design/`, or `docs/design/geoapify/` at preparation time. This proposal follows repository AGENTS.md, `.agents/rules/ui.md`, and the [existing Tester design](../tester-simulation/design.md). The [PRD](../../ba/PRD.md) supplies FR-TST-01–08, NFR-TST-01–05 and AC-TST-01–08. The [Geoapify assessment](../../architecture/GEOAPIFY_INTEGRATION.md) owns provider findings and integration boundaries. Existing Tester issue scope remains authoritative; this proposal is not a second backlog.

## Design intent

The Tester should compose a basic trip, inspect its geography and timing, then review the saved plan before starting a run. The same source vocabulary should carry into Analyst evidence inspection. The map is the largest work surface, with route editing tools adjacent and playback controls immediately below. Driver stays upper left; Passenger stays lower left. Actual received results occupy a separate strip beneath playback.

The prior Tester design is the starting point. The Geoapify addition is address search, provider route choices and inspection of original versus matched coordinates. It does not imply a change of map renderer. Candidate provider capability, an authored plan and consumed system evidence must remain visually distinguishable.

The `ui-ux-pro-max` design-system search for “operations map console” returned a generic marketing hero and a new palette/typeface. Those suggestions do not fit the existing operations workspace. This proposal retains P-063 tokens and uses the skill's keyboard focus, touch size, contrast and dense-layout guidance. The `frontend-design` direction is a spatial workbench: geography carries the composition, while the two actor windows and tools form stable edges. Decorative KPI cards and a marketing header would compete with the task and are omitted.

## Desktop composition

```text
Trip studio / Geoapify proposal                    Save plan   Review plan
┌──────────────────┬─────────────────────────────────────┬──────────────────┐
│ Driver           │ Map: origin, pickup, destination     │ Trip tools       │
│ Inbox            │ Search + route selection            │ Places / Route / │
│ Dialogue draft   │ Original + matched point selection  │ Traffic / GPS    │
│                  │                                     │                  │
├──────────────────┤                                     │ Named fields     │
│ Passenger        ├─────────────────────────────────────┤ with units       │
│ Inbox            │ Playback + selected sample          │                  │
│ Dialogue draft   ├─────────────────────────────────────┤ Source context   │
│                  │ Results received from this run      │ Review plan      │
└──────────────────┴─────────────────────────────────────┴──────────────────┘
```

At 1440px, use 16px outer padding, 12px gutters, a 256px actor rail, a flexible center of at least 480px, and a 300px tools rail. Keep a map height of at least 400px. Within the center, map, timeline and results share one alignment. Both actor windows remain visible; each has its own scroll area and labelled composer. In the existing Analyst workplace, adopt source indicators and timeline selection without importing the Tester authoring controls.

At 1024–1279px, use a 232px actor rail and move tools into a disclosure below the map. At 768–1023px, use a 224px actor rail, with results after tools. Below 768px, use one document column with jump links to Map, Tools, Driver, Passenger and Results. Preserve the actors' relative order, keep their role labels explicit, and preserve unsent drafts when sections collapse. A static desktop SVG does not prove those layouts; verify them in the subsequent approved implementation.

## Tokens and components

Use the existing primitives from `src/webapp/app/globals.css`, mapped through semantic and component aliases. Do not introduce a second application palette.

| Existing primitive | Semantic role | Application |
|---|---|---|
| Primary `#006948` | Primary action, chosen route | Review plan, selected tool, planned route |
| Tertiary `#0058be` | Passenger, inspected sample | Passenger rail, playback position |
| On-surface `#0b1c30` | Main text | Headings and data |
| Secondary `#565e74` | Supporting text | Source, timestamp and helper text |
| Surface `#f8f9ff` | Workspace | Shell background |
| Surface-container-lowest `#ffffff` | Work surfaces | Actors, tools and timeline |
| Error `#ba1a1a` | Failure | Provider errors and field validation |

Use Inter/system sans, 16px body text, 14px compact controls, and 12px nonessential metadata. Titles are 20–24px at weight 600–700. Use tabular numerals for elapsed time; monospace is reserved for coordinates or technical identifiers inside optional detail. Spacing follows 4/8/12/16/24px, panels use an 8px radius, and controls a 6px radius. Essential values remain readable without tooltips.

After approval, reuse existing Next.js/React, Tailwind and compatible shadcn/ui primitives for buttons, cards, badges, tabs and disclosures. Keep map rendering separate from provider adapters and state hooks. Reuse the existing timeline selection model where possible. No application components are changed by this proposal.

## Core interactions

1. **Place the trip.** Search an address or enter coordinates, review the returned location, then explicitly set origin, pickup or destination. Label address suggestions with their source. Typing alone must never move the saved point. Keyboard entry and a coordinate form provide the same capability as dragging.
2. **Choose a route.** Present provider-returned candidates with distance, duration basis and retrieval time. Selecting one updates the draft preview; saving commits the choice to the plan. Show “Modeled travel time” for provider estimates and identify free-flow or approximated traffic basis where supplied. Do not call an estimate live traffic.
3. **Inspect position and time.** Selecting a route point selects its timeline sample and vice versa. Playback changes view time only. A sample inspector shows original coordinates, optional matched coordinates, time, source and match status. Original points remain available; an unmatched point is neither removed nor silently snapped.
4. **Author a test.** Driver and Passenger have separate drafts and notification inboxes. AI-generated dialogue is labelled “AI draft — review before sending.” Traffic and GPS controls explicitly create synthetic inputs. Saving, reviewing and accepting a run remain separate actions. The one-minute basic-trip target requires timed UAT; this preview does not measure it.
5. **Inspect results.** Run output is shown only after received events provide it. Detection, notifications, responses and assignment have separate pending, failed, unavailable and available states. “No case generated” is a valid result. A case link appears only when a case identifier exists and respects the isolated test workspace.

## Evidence and contextual assistance

| Information | Presentation |
|---|---|
| Base geography | Visible provider/source attribution in the map; verify required attribution before live use. The preview instead says “Illustrative map; no live tiles.” |
| Planned route | “Geoapify route” only after a response identifies that provider; show retrieval time and duration basis. |
| Original telemetry | Point shape and “Original sample” label; identify observed or synthetic origin and sample time. |
| Matched telemetry | Separate outline/line style and “Matched position” label; source and method remain inspectable. Never overwrite the original evidence. |
| Simulated congestion | “Synthetic congestion,” with authored segment, level and time; separate from provider modeling and observation. |
| Observed traffic | Only show when an actual source/time is available. Missing historical coverage shows unavailable. |
| Agent assistance | Read-only contextual actions such as “Explain this route,” “Compare routes” and “Inspect point matching.” Results cite their input and source, remain advisory, and never determine sanctions. |

An agent response panel supports Idle, Working, Complete and Error states, partial streamed text, cancellation and retry. A tool result card identifies its source and request time without dumping credentials or backend configuration into the user flow. Candidate actions must still pass the shared service and tool authorization design. No generic external fetch control, vendor secret form, sanction button or unbounded tool passthrough is proposed.

## Unavailable and failure states

| State | User-facing behavior |
|---|---|
| Provider not configured | “Location service is not configured.” Disable provider actions with an adjacent reason; retain the existing plan and coordinate editor. Configuration belongs outside the trip console. |
| Loading | Keep last known map/plan content, mark the current request pending, and prevent duplicate requests. |
| No address results | “No matching places.” Retain search text and offer coordinate entry. |
| Timeout or provider failure | “Location service is unavailable. Retry.” Preserve authored data; show stale last-known content with its timestamp where appropriate. |
| Rate limit / HTTP 429 | “Location service limit reached.” Show retry time when known, honor it, and avoid automatic request loops. |
| Unmatched sample | “No road match.” Preserve the original marker and coordinates, with a distinct hollow shape and text. |
| No route | “No route found for these points.” Allow point changes; never display a straight line as a returned road route. |
| Unknown traffic | “Traffic observations unavailable for this time.” Keep any modeled ETA explicitly labelled and separate. |
| Stream interruption | Show “Connection interrupted” and the last update time. Preserve drafts and reconcile the received run state before enabling dependent actions. |

## Accessibility and streaming handoff

All controls require accessible names, visible 2px focus rings and 44px touch targets. Map actions need keyboard/list/form equivalents. Timeline uses an accessible slider with elapsed time and a labelled step control; arrow keys move samples, and selecting a sample exposes the same information as hover. Color is paired with names and line/point shapes. Long text wraps; support 200% zoom without losing controls. Tooltips work on focus and touch, dismiss with Escape and never contain the only copy of critical information. Respect reduced motion and never auto-play a historical trip.

Use existing authenticated fetch/SSE handling. Abort requests and subscriptions on run change or unmount; discard stale responses for a previously selected point. Deduplicate event identifiers, preserve stream cursors, and recover gaps through the established snapshot flow. Receiving events must not steal keyboard focus or continuously announce GPS ticks. Use a small polite status region for important arrivals. Scrubbing a timeline must never submit new telemetry or replay commands. The test client must preserve `/test` isolation; route prefixing alone is not sufficient.

## Review and validation boundary

The reviewer should confirm retained map plus companion timeline, actor placement, tools, evidence labels, and unavailable-state copy. The separate open question is whether “replace” means the map provider or the entire map presentation. Provider migration, scope changes and UI coding await that clarification and the required visual approval.

This artifact can be checked for valid SVG structure, local documentation links, accurate status labels and raster readability. It cannot prove geocoding coverage, real map tiles, routing correctness, SSE recovery, responsive browser behavior, keyboard interaction, or end-to-end test isolation. Those require runtime checks against the accepted implementation and the [Geoapify manual verification](../../testing/manual/GEOAPIFY.md).

The preview was rendered locally using `rsvg-convert` on 2026-10-08. Its PNG is a rasterization of the authored SVG, not a screenshot of the application or Stitch output.

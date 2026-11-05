# Manual trip console refresh — approved local candidate

**Status:** accepted local candidate (user approval: 2026-10-15). The earlier preset-dashboard composition is withdrawn. This revision preserves the current console and changes only the requested interactions. No production components, API behavior, or cancellation endpoint are implemented here.

## Review the actual console composition

- [Revised manual console](preview-desktop.png), [collapsed results](preview-collapsed.png).
- [Cancellation dialog](preview-cancellation-dialog.png) and [cancellation event details](preview-cancelled.png).
- [Overview](preview-overview.png), [Presets](preview-presets.png), and [History](preview-history.png).
- [Current page fixture capture](current-fixture-desktop.png) provide the comparison baseline.
- [Interactive preview](preview.html); [verification evidence](verification.md).

The baseline executes the unchanged `src/webapp/app/test/page.tsx` from this checkout through a temporary React/Bun harness. It uses an existing compiled project stylesheet. Authentication, API calls, `next/link`, and the dynamically imported map are replaced with explicit read-only fixture adapters; the map is a captured image. It is evidence of the current JSX composition, not a hosted authenticated screenshot or exact production-map rendering. No current authenticated browser session was available.

Speed is shown in **km/h** (the existing 12 m/s example becomes 43.2 km/h), and the compact **Driver** selector shows an example display name. The internal driver reference belongs in secondary event metadata. Cancellation details distinguish **State before cancellation** from **Resulting state: Cancelled**. A valid reason immediately clears the required-field error. Optional MapLibre branding is omitted while style-supplied map-data attribution remains visible.

The source layout is authoritative: **330px conversation rail on the left, flexible map in the middle, 360px controls on the right**, with the compact 40px header. The revised preview retains Driver and Customer conversation perspectives and the existing Emerald Sentinel visual language. The added top tabs and centered editable title are compact; Manual trips is the default. There are no dashboard hero headings or replacement preset cards in the manual console.

Stitch MCP is unavailable. This is a locally authored fallback, not a generated Stitch screen. User visual confirmation accepted this local candidate on 2026-10-15. The desktop application implementation and runtime verification are tracked in [PR #345 evidence](../../testing/TEST_CONSOLE_PR345_VERIFICATION.md). `docs/README.md` and `docs/design/README.md` are absent in this checkout; existing [Design.md](../Design.md), UI rules, and current JSX guided the revision.

## Exact changes

| Area | Proposed behavior |
| --- | --- |
| Stops | Three compact address rows: **Initial driver position**, **Pickup**, **Destination**, with car, customer, and pin icons. No explanatory text in these rows. |
| Coordinates | Delete GPS X/Y inputs, coordinate editing disclosures, every coordinate-entry button, and map-click-to-add-point mode. No hidden advanced replacement. Internal geographic values remain transport data, never authoring fields. |
| Markers | All three markers are draggable before the run. A moved marker updates its address field and invalidates any prior route. Ordinary address search and keyboard marker movement provide alternatives. Clicking bare map does not create a point. |
| Direction | Delete the entire direction-control feature. Replace it with one small, read-only compass inside the map. |
| Route modes | Delete route-type selection, manual/free driving modes, direction buttons/sliders, custom-turn authoring, and their sidebar controls. |
| Run | One control changes **Run → Pause → Resume** according to acknowledged run state; Resume returns to Pause. It does not create another run. |
| Completion | **Complete trips** is enabled only after the destination is reached. It represents normal completion. No fast-complete or teleport action. |
| Early termination | **Customer cancel** and **Driver cancel** require a non-empty, trimmed reason. They are distinct from normal completion. |
| Results | A collapsible bottom Log/Overview dock fills 40% of the console content viewport when expanded. The three-pane area gets the remaining 60%; collapse restores space to the map. |

A destination state selector lives only in the dark preview banner to demonstrate normal completion without running a trip. It is not a proposed product control. Completion remains disabled in draft, en route, paused, and cancelled states.

The completion assumption follows the latest instruction: early finish is cancellation; normal completion occurs at destination. If a later explicit user decision permits fast completion, it requires a separate design and API contract, not reuse of cancellation.

## Map and address behavior

The interactive preview uses the repository's existing MapLibre package and actual OpenFreeMap Positron tiles. Live basemap rendering is real. Trip execution, address resolution, and messages remain local design interactions. The page says this explicitly.

Marker drag and arrow keys update the corresponding field with `Near <named place> (preview)`, derived from a small local landmark list. Address selection from that list moves the correct marker. This is not reverse-geocoder evidence. The production implementation must resolve the moved location through the existing address service, show pending/unresolved state without an invented address, preserve the last accepted address until resolution is reconciled, and recalculate the route. Route and address responses need request identity to ignore stale results during rapid movement. Do not render a fabricated straight-line route when road routing is unavailable.

The address field is the single-pointer alternative to dragging: users can choose a search result by click or keyboard without dragging. Arrow keys on a focused marker offer finer keyboard adjustment; address search remains the primary accessible alternative. No coordinate-entry UI is introduced. Marker positions become read-only once a run begins unless a future explicit run-edit contract permits changes.

The compass is informational and has an accessible name. It does not accept clicks, rotation commands, headings, or a route mode. The preview removes coordinate telemetry from the map overlay to keep setup visual.

For local file viewing or a missing MapLibre package, `basemap.png` is an explicitly labeled captured-image fallback. It cannot prove live map loading. Network failures and unavailable styles must remain visible in application implementation rather than masquerading as a loaded provider.

## Cancellation and evidence contract

The dialog names the initiating actor and requires a reason. Blank or whitespace-only submission focuses the field and shows an inline error. Keep trip and Escape dismiss without changing the run. Confirmation appends an expandable cancellation event and moves the preview to Cancelled.

| User-facing action | Canonical cancellation actor |
| --- | --- |
| Customer cancel | `passenger` |
| Driver cancel | `driver` |

The existing assignment contract admits `passenger`, `driver`, and `platform`; this UI exposes only the two requested participant actions. The event must retain canonical actor, user-facing actor label, trimmed reason, occurrence timestamp, event identity, organization, run identity, trip identity, and trip state when cancelled. Keep these same references available to later agent inputs and case evidence. A narrative summary alone is insufficient. Model-input projections admit cancellation actor/reason. The desktop submission API and UI wiring are implemented separately from this static preview; see [runtime verification](../../testing/TEST_CONSOLE_PR345_VERIFICATION.md).

The preview demonstrates those fields with clearly prefixed `preview-` identifiers and an actual local interaction timestamp. It does not submit events, classify a driver, create a case, or claim that downstream agents consumed the cancellation. Event processing reads **Not submitted; design preview only**. The log can show sent/consumed/failed states only when actual backend receipts exist.

Production commands require organization membership, ownership checks, idempotency, and error reconciliation. A failed or uncertain cancellation must not display a confirmed Cancelled state. Preserve the reason on failure and offer retry. Client role labels cannot authorize a server command.

## Result dock, data, and streaming

Desktop console content height excludes the 30px design-only banner, 40px app header, and 36px tabs. The dock gets 40% of that remaining area, including its header. Its body scrolls internally; the map and both rails stay within the other 60%. Collapsed height is 38px. In the measured 1600×1000 viewport, content is 894px and the dock is 358px (40.04%, rounded to pixels).

Log shows stage, event, state, and expandable structured details. Cancellation details are visible and copyable. Overview groups actual pipeline input, driver routing, model throughput, and classification counts. This preview intentionally shows unknown values and waiting states rather than fake performance or AI verdicts. Source labels never substitute for model predictions, and a locally composed message never establishes delivery to a real driver.

After approval, preserve authenticated SSE consumption, one subscription per run, event-ID deduplication, cleanup on run/organization change, cursor resume, and REST reconciliation after a gap. Appending an event must not reset expansion, focus, or scroll. Use a bounded polite announcement; offer New events when the user is inspecting older rows. Connection, trip lifecycle, classification, and case creation have separate states.

## Presets, history, and title remain unobtrusive

Presets retains the requested names: Default, All normal trips, and Driver going wrong direction. Primary copy says **Trip library** and **Published example trips with recorded source details**. Provider/repository/release/revision live only under expandable source details. Published metadata reports 40,000 available synthesized trips and 28,000 `no_violation` labels at revision `914a36560727f5892a24fba3a4173cb245c963da`; the full corpus checksum was not verified locally. Actual selection size stays unavailable until supplied by the API. Wrong-direction selection remains unavailable until movement away from pickup is verified; `ERR-03` route deviation alone is insufficient.

History defaults to all members of the current organization. The centered title is editable and must be saved on the backend for plans/runs and reloaded in history. The prototype demonstrates local editing only. All organization members can use `/test`; no analyst/tester role guard is added. Organization changes clear old cached history and streams before loading the next scope.

## Tokens, desktop layout, and implementation handoff

Use the existing `#006948` emerald, `#0b1c30` text, `#565e74` metadata, `#f8f9ff` canvas, white panels, and hairline borders. Inter/system sans, compact 10–12px console copy, 4–12px spacing, 4px controls, and the existing green/blue conversation distinction preserve continuity. The preview separates primitive, semantic, and component aliases. Accessible names and visible focus remain required. The test console is a desktop workstation; mobile layout, mobile preview assets, and mobile acceptance targets are excluded by stakeholder instruction on 2026-10-15.

At narrower desktop widths, rails reduce to 270/300px. The three-column workstation and bounded 40% dock remain the only supported composition. Desktop verification covers 1024px and 1600px. There is no stacked mobile adaptation or mobile screenshot.

UI/UX Pro Max's `dragging movements` guidance requires a single-pointer alternative; address search implements that requirement. Next.js guidance keeps interactive behavior in focused Client Components. Context7 was queried but its monthly quota was exhausted; the [official MapLibre draggable-marker example](https://maplibre.org/maplibre-gl-js/docs/examples/create-a-draggable-marker/) confirmed the marker drag event pattern. The existing page and map component remain the implementation starting points; avoid a broad component redesign or unrelated architecture rewrite.

After visual approval, reuse the current map, conversation panes, authenticated API client, Tailwind tokens, and local shadcn-compatible primitives. Add only focused stop editing, run-action states, reason dialog, result dock, preset/history navigation, and persisted title integration. Tests must prove API semantics and real evidence propagation separately from this static design.

## Run the preview

From this directory, point the server at an existing installation of `maplibre-gl/dist`:

```bash
python3 preview-server.py --port 8766 --maplibre /absolute/path/to/node_modules/maplibre-gl/dist
```

Open `http://127.0.0.1:8766/preview.html`. The server binds only to loopback and serves static preview assets plus that installed MapLibre directory. It provides no trip API or authentication bypass. Actual basemap attribution remains visible.

# GIS Evidence - Gap and Outage Visualization

## Accessibility and interaction handoff

- Normal text requires at least 4.5:1 against its surface; meaningful glyphs/control boundaries require at least 3:1. The proposed role colors are measured against opaque white, not assumed readable against arbitrary map tiles. Use the existing white/light slate carrier plus dark border for isolation.
- Existing interactive map markers and timeline checkpoints remain untouched. A new missing-data band (red hatched) overlays the scrubber. It requires no pointer interaction and is fully non-intercepting (`pointer-events-none`).
- Provide gap context via accessible text and `aria-describedby` on the existing `<input type="range">`. Expose the explanatory time/reason via a compact existing warning/status text region that the native slider references (e.g. `aria-describedby="gap-info"`). Avoid a separate focusable gap wrapper. Focus on the native slider must reveal/read this explanation.
- Supply explicit status strings such as "Chưa có GPS" (No GPS), "Chưa rõ đường · vị trí cuối" (Unknown route · last position), and "Mất kết nối (>30s)".
- The timeline track's missing data band clearly shows the explicit >30-second GPS gap without fabricating a time or position. It anchors to known recorded observations. 
- Do not pulse, bounce, or fabricate routes. Use source-safe visualization: the actual missing telemetry interval stays visually disconnected (drawn as two disconnected path sections on the map). There is no inferred road shape, future position prediction, or fake congestion. The missing road MUST remain unknown.

## States and review boundary

The red hatched band provides a definitive warning for explicit >30-second GPS gaps. It is positioned on the exact time-slice corresponding to the gap. Unknown vehicle/route segments are strictly rendered as unknown, disconnected from the previous known point.

Explicit statuses (e.g. "Traffic: Không khả dụng") replace the default metrics when telemetry is absent, removing ambiguity. Multiple specimens (Healthy, Gap, Missing Data) are provided as vertically stacked specimens in the preview for visual proof. These are abstract design specimens, not actual production evidence.

The HTML samples and SVGs are static illustrations, not functioning map controls. The screenshots verify static appearance only. PNG/SVG review establishes appearance; it does not establish runtime accessibility, SSE connectivity, or database provenance.

Applied guidance: `frontend-design` for source-safe restraint (not filling in blanks); `ui-ux-pro-max` for semantic error states, accessible SVG attributes (role/title/desc), and `aria-describedby` patterns.

## Manual acceptance after approved implementation

1. Compare map and timeline at 1× with the supplied compact screenshots. Verify that the red dashed >30s gap band appears on the scrubber track exactly over the missing interval.
2. Ensure the gap band does not intercept pointer clicks/touches meant for the native range slider scrubber (`pointer-events-none`).
3. Check that focusing the range slider reads the gap text via `aria-describedby` referencing the status string.
4. Verify on the map canvas that an explicit >30-second gap results in a discontinued (disconnected) trajectory rather than an inferred road.
5. Exercise unavailable states: verify that traffic, route, and GPS statuses explicitly state their unavailability.
6. Review at 1440px (desktop) and 375px (mobile). Verify no horizontal page overflow and that the timeline and status ribbon scale safely.

## Local preview checks

Rendered and verified with the installed Playwright Chromium directly from a local `file://` URL; no runtime server was started. The desktop (1440px) and mobile (375px) captures include all three vertically stacked specimens. Verification confirms no horizontal overflow, the explicit "Không khả dụng" text fits the bottom ribbon grid, the timeline gap layer is non-interactive, the range retains `aria-describedby`, and the SVG parses in Chromium.

**Stitch Provenance:**
Stitch MCP generation is available and was successfully called.
- Project ID: `7784297700642891517`
- Screen output recorded. However, Stitch generated an uncompromising tactical avionics HUD rather than a minimalist extension of our existing React MapLibre codebase. Because the requirement enforces "No redesign", the local HTML/SVG fallback (`preview.html`) is used as the primary artifact. The Stitch output is recorded in Project `7784297700642891517` but not applied to the codebase. The user explicitly approved this local HTML/SVG fallback for T3/T4 implementation on 2026-10-01 after independent specification and quality review.

## Approved handoff for T3/T4

Preserve the existing compact analyst map and timeline layout. Do not alter the 2px passive timeline checkpoints, marker sizes, native seek/replay controls, or camera behavior.

Inject a red dashed time-band on the scrubber to represent >30-second GPS gaps. Ensure the visual band is `pointer-events-none`. Tie the gap explanation to the range scrubber via `aria-describedby` pointing to the status ribbon text. Add explicit unavailable states to the kinematic telemetry footer ribbon and active status indicators.

Source safety is absolute: do not invent data. Unknown intervals must look explicitly unknown (disconnected vectors).

This static design artifact establishes visual requirements for issue 61 slice D. The user approved implementation of this visual scope on 2026-10-01. Runtime, database and browser acceptance evidence remains separate from these static artifacts.

# Issue #63: playback checkpoint markers

Status: **local preview implemented following the user instruction to finish all remaining tasks**. Scope: design artifacts for issue #63 / PR #82, based on the supplied brief. GitHub status was not queried. No application code, playback behavior, runtime servers, or GitHub objects are changed by this sidecar.

## Review artifacts and provenance

- [HTML preview](preview.html): native-size map/timeline legend, selected and focused states, overlap specimens, and an expandable original screenshot.
- [SVG legend](marker-legend.svg): portable vector artwork with native-size glyphs.
- [Desktop PNG](preview-desktop.png) and [mobile PNG](preview-mobile.png): browser captures of the local HTML proposal.
- [Existing screenshot](../../testing/assets/issue63/stalled-scrub.png): unmodified reference, 1440 × 1000. Its map is approximately 694 × 256 CSS pixels. Existing synthetic-trip labels belong to that reference, not newly generated evidence.

No callable Stitch tool was exposed in this session. These artifacts are **local HTML/SVG prototypes, not Stitch output**. The older [design specification](../Design.md) references a historical Stitch project; that does not establish current Stitch access or generation for this proposal. The unavailable capability blocks the requested Stitch screen generation. Visual review of this local fallback is still possible.

The local fallback was subsequently accepted under the user's instruction to finish all remaining tasks. The latest explicit correction, “remove the button you add in the timeline, just markit in the timeline”, authorizes passive scrubber marks without another appearance choice or confirmation. Existing previews retain their original provenance; any interactive timeline specimens are historical and are superseded by the current handoff below. No new Stitch generation or revised preview is claimed.

## Design direction

Retain the existing compact analyst cockpit: Inter/system sans, cool light surfaces, emerald driver identity, and purple destination identity. Spend visual emphasis on recognizing marker roles. Use a circle for the starting point, a human silhouette for pickup/customer, a flag for destination, and the actual vehicle silhouette for the moving driver. Avoid a dashboard redesign or enlarged map furniture.

The plan was reviewed against the brief before preview creation. Large location pins and a new icon library were rejected because they obscure the dense map and duplicate existing dependencies. The preview instead uses the installed Lucide outline family (`Circle`, `UserRound`, `Flag`, `Car`, `Motorbike`, `CircleHelp`). Motorbike represents the project's motorized Bike service; the bicycle-shaped `Bike` glyph would communicate the wrong vehicle. The final implementation can reuse these existing assets without adding a package.

Layout is left aligned. The marker legend compares map and timeline sizes at 1×; focus and collision examples sit below it. On narrow preview screens the role label occupies its own row and the samples remain side by side. The screenshot appears only as an unchanged reference. No invented road, location, timestamp, speed, or trajectory is drawn. The overlap example is explicitly a diagram of layout behavior.

## Tokens and dimensions

Use three layers: primitive values, role aliases, then marker tokens. Reuse the application's existing semantic colors wherever possible; the preview's values are a design handoff, not modifications to the app theme.

| Primitive | Semantic role | Component use |
|---|---|---|
| `#ffffff` | Surface | Opaque checkpoint carrier and driver glyph |
| `#f8f9ff` | Background | Preview/cockpit surround |
| `#0b1c30` | On-surface | Start circle, text, outer focus ring |
| `#565e74` | Secondary | Unknown vehicle, secondary text |
| `#006948` | Primary | Pickup stroke, driver carrier, selection ring |
| `#6d28d9` | Destination | Flag stroke and carrier outline; proposal preserving the current purple role |

Spacing follows 4/8/12/16/24px. Marker labels use 12px/18px, weight 500; existing map popover content uses 14px/20px. Use 16px readable text for expanded mobile map details. Preserve the existing application font stack; the standalone preview uses local fallbacks without a font download. Timestamps may use the existing monospace stack with tabular numerals. Do not shrink text below 12px to fit labels. Timeline marks have no details dropdown or popover.

All SVG glyphs have a `0 0 24 24` viewBox, rounded caps/joins and stroke width 2 in viewBox units. That is approximately 1.67 CSS pixels at 20px, 1.33 at 16px and 1.17 at 14px. Apply the same scaling to every glyph; do not give car and motorbike different stroke weights.

| Role | Map glyph | Map carrier | Map anchor | Timeline glyph | Timeline carrier / anchor |
|---|---:|---:|---|---:|---|
| Starting point | 12px circle | 24 × 24px transparent slot | Center `(12,12)` | 10px circle | 20 × 20px / `(10,10)` |
| Pickup/customer | 16 × 16px person | 24 × 24px white circle | Center `(12,12)` | 14 × 14px person | 20 × 20px / `(10,10)` |
| Destination | 16 × 16px flag | 24 × 24px white circle | Center `(12,12)` | 14 × 14px flag | 20 × 20px / `(10,10)` |
| Driver: car | 20 × 20px car | 28 × 28px emerald square, 6px radius | Center `(14,14)` | 14 × 14px car | 20 × 20px / `(10,10)` |
| Driver: motorbike | 20 × 20px motorbike | Same as car | Center `(14,14)` | 14 × 14px motorbike | Same as car |
| Driver: unknown | 20 × 20px question glyph | 28 × 28px white square, 6px radius, dashed secondary border | Center `(14,14)` | 14 × 14px question glyph | 20 × 20px / `(10,10)` |

The timeline columns above describe the historical icon preview. The current timeline uses 2px by 12px passive colored ticks on the scrubber, with no icon carriers or interactive controls. Map glyph and carrier dimensions remain current.

“Glyph size” means the SVG viewport; the painted outline may be inset. Timeline square carriers use a 4px radius. Timeline car/bike/unknown samples describe the playhead only, not extra historical events. Do not add vehicle checkpoint events.

Every location uses a centered outer carrier. The person's feet, flagpole, or vehicle wheels are not separate coordinate anchors. Keep the carrier's screen-space dimensions fixed across map zoom levels and responsive widths. The displayed start ring has a white interior and does not use an anomaly-red fill. A map checkpoint gets a 1px role-colored carrier border; opaque white isolates the glyph from roads. A selected state adds a 2px emerald ring with 2px offset. Keyboard focus adds a 2px on-surface outer ring with 4px offset. Neither changes glyph scale, position, or layout.

## Vehicle source contract

Read the selected trip's actual `vehicle_type`. Keep its raw value available in details. Proposed normalization is trim plus case folding, followed by an **explicit equality allowlist**, not substring matching:

| Normalized actual field value | Representation |
|---|---|
| `car`, `green sm car` | Car |
| `bike`, `motorbike`, `green sm bike` | Motorbike |
| Missing, blank, conflicting, or anything else | Unknown vehicle |

The screenshot shows `car`; repository schema examples use `Green SM Car` and describe Bike service. Fresh isolated API verification also exposed the recorded value `motorbike`, now explicitly supported. These names justify the narrow proposal, not a claim that all deployed values were audited. Confirm any additional aliases against the actual contract before adding them. `Express`, `Delivery`, plates, model names, speed, route geometry, and service names from other fields do not establish vehicle type. Do not infer from them. Do not present a schema-injected default as evidence of a recorded vehicle type; provenance lost upstream needs resolution by the main implementation owner.

Unknown type and missing location are different. With a known recorded coordinate and unknown type, show the neutral vehicle carrier. With no valid position at the current playback time, show a textual unavailable state and omit the moving map marker. Never supply a midpoint or last-known point as if it were current. Keep static checkpoints only when their own coordinates are valid.

## Overlap and anchoring

Map collision detection uses projected carrier bounds expanded by 4px; larger interactive target bounds must also remain non-overlapping. Keep the moving driver exactly at its projected recorded coordinate. When static markers overlap it, displace only their visual callouts to fixed candidate positions: above, right, below, left, starting 32px from the true anchor. Connect each displaced badge with a 1px dashed neutral leader terminating at the true coordinate; retain an anchor dot when not occluded. This leader is a UI connector, never a route segment.

Choose the first in-bounds, collision-free slot, using role priority pickup, destination, start and stable IDs as tie-breakers. Keep an assigned slot until the overlap ends to avoid jitter. Never mutate coordinates. Keep callouts and labels clear of map controls and attribution. If no slot fits, show one count control opening a named list of colocated roles. Keep every role accessible in that list; stacking order alone must not hide a checkpoint. Driver draws above static markers, selected/focused callouts above ordinary callouts, and detail popovers above all markers.

Timeline marks sit directly on the scrubber at their exact recorded timestamp-to-track positions. They are compact, passive information: no count buttons, details dropdowns, checkpoint action buttons, or jump actions. Closely spaced or equal timestamps may visually coincide; keep every checkpoint's role and recorded time available as accessible text in chronological order, with role and stable ID as tie-breakers. Do not shift timestamps, fan marks horizontally, or introduce an interactive collision group.

Preserve the native playhead, replay/pause controls, and range input. The passive mark layer must not intercept pointer gestures or obscure the range thumb or focus indicator. At track edges, preserve the logical anchor and contain the visual mark within the existing track area. Narrow layouts retain compact marks without a new details row, enlarged map icons, or horizontal page scrolling.

## Accessibility and interaction handoff

- Normal text requires at least 4.5:1 against its surface; meaningful glyphs/control boundaries require at least 3:1. The proposed role colors are measured against opaque white, not assumed readable against arbitrary map tiles. The white carrier plus dark border provides isolation. Use shape and accessible names alongside color.
- Existing interactive map markers use 32 × 32px pointer targets and 44 × 44px touch targets without enlarging visible markers. If expanded map targets collide, group them; invisible overlapping hitboxes are not acceptable. Touch map popovers/list items have at least 8px spacing. Passive timeline marks have no hit target or tab stop.
- Supply names such as “Starting point”, “Pickup / customer”, “Destination”, “Driver, car”, “Driver, motorbike”, and “Driver, vehicle type unavailable”. Use the interface's Vietnamese equivalents in the application, for example “Điểm đón khách” and “Chưa rõ loại phương tiện”. Include only real timestamps when available.
- Decorative SVGs beside equivalent text use `aria-hidden="true"`. Existing interactive map markers retain native button semantics. Each passive timeline mark needs an informational label containing its role and real timestamp, for example “Điểm đón khách, <recorded time>”. Use semantic text, visually hidden text, or a named `role="img"` wrapper; do not depend on an `aria-label` on a generic span. Do not rely on SVG `<title>` or pointer hover alone.
- Retain existing keyboard and focus behavior for map controls. Timeline marks have no button role, `tabIndex`, expanded state, click/keyboard handler, or hover-only details. Their labels remain available in screen-reader reading order without adding checkpoint actions.
- Preserve the native scrubber's keyboard operation and accessible name. Use a non-intercepting mark layer such as `pointer-events-none`; pointer, touch, and keyboard seeking remain owned by the existing range input.
- Do not pulse, bounce, rotate to an invented bearing, or animate marker size. With reduced motion, remove decorative transitions; explicit playback can still update truthful positions. Keep pause/seek controls available. No position animation or playback fix is implemented in this prototype.
- Use one restrained status announcement for explicit seeks or unavailable data; do not announce every position/frame. Cosmetic marker updates must not remount case state, replace evidence, or restart SSE consumption.

## States and review boundary

Default map markers have stable dimensions. Existing map hover, selection, and focus states remain unchanged. Timeline marks have no interactive states and never seek. A checkpoint without a valid recorded timestamp cannot be positioned on the scrubber; retain available textual evidence without inventing a time. Missing coordinates do not disable access to valid textual evidence. Unknown vehicle identity stays visibly distinct from the start circle.

The HTML samples are static illustrations, not functioning map controls. Its screenshot disclosure is functional native HTML. PNG/SVG review establishes appearance only. It does not establish runtime accessibility, playback correctness, database provenance, SSE compatibility, or production behavior.

Applied guidance: `frontend-design` for deliberate restraint and review before build; `design-system` and `references/token-architecture.md` for three-layer tokens; `ui-ux-pro-max` for icon semantics, readable contrast, focus, targets, and responsive layout. The focused icons search matched `icon-context-accessibility`. Its suggested new icon libraries were not adopted because Lucide is already installed. Both Next.js accessibility searches returned no verified match; framework-specific guidance was not inferred from those results. Accessibility recommendations use the skill's explicit built-in defaults and quick-reference rules.

## Manual acceptance after approved implementation

1. Compare map and timeline at 1× with the supplied compact screenshot. Confirm circle/person/flag and equal-sized car/motorbike carriers; selection must not scale icons.
2. Exercise the actual allowlisted vehicle types and missing/unsupported values. Verify unknown remains unknown, including when source provenance is absent.
3. Put start, pickup, destination and driver at the same recorded point; verify stable leaders or a named group and unchanged coordinates. Repeat near each map edge and attribution.
4. Check equal and closely spaced checkpoint timestamps and timeline endpoints. Marks retain exact recorded positions and accessible role/time labels. Confirm no timeline count button, details dropdown, checkpoint action button, or extra tab stop exists. Replay/pause and range seeking remain available; passive marks never intercept their gestures.
5. Review at 1440px, 768px and 375px widths, 200% zoom and coarse pointer. Verify readable details, full keyboard access, visible focus, non-overlapping targets and no horizontal page overflow.
6. Inspect accessible names and focus return with a screen reader; test reduced motion. Preserve visible unavailable states when telemetry is missing.
7. During SSE streaming, seek and switch cases using the existing application controls. Confirm no stream restart or lost history caused by marker presentation. This remains main-agent application verification.

## Local preview checks

Rendered with the installed Playwright Chromium, directly from a local `file://` URL; no runtime server was started. Inspected the desktop (1440px) and mobile (375px) PNGs. The final legend has seven direct rows and no nested rows. Neither viewport has horizontal document overflow. The original screenshot loads at 1440 × 1000. The SVG parses in Chromium. The preview produced no page errors.

Measured contrast on opaque white: on-surface **17.17:1**, secondary **6.46:1**, emerald **6.74:1**, destination purple **7.10:1**. White driver glyphs on emerald have the same **6.74:1** ratio. These historical checks validate this local palette and static artifacts only; they do not verify the passive-mark correction. Application verification belongs to the main implementation owner.

## Current accepted handoff: passive scrubber marks

The user's latest correction supersedes the earlier interactive timeline proposal. Place compact passive timestamp marks directly on the existing scrubber. Remove timeline count buttons, details dropdowns, and checkpoint action buttons from the implementation contract. Marks convey checkpoint role and recorded time; the existing native replay/pause and range controls own playback interaction.

Preserve all existing map circle/person/flag/car/motorbike glyph sizes, carrier sizes, anchors, and behavior. Use compact 2px by 12px ticks with the existing semantic colors, font stack, and spacing. Keep timestamp mapping exact, including collisions and endpoints. Preserve readable contrast, informational role/time labels, responsive containment, and uninterrupted range gestures. Do not add packages, configuration, new appearance choices, or SSE lifecycle changes.

Applied targeted guidance: `ui-styling` for existing Tailwind tokens, compact responsive placement, and semantic markup; `ui-ux-pro-max` for meaningful icon text alternatives and contrast. The focused icons query matched `icon-context-accessibility`; retain the existing Lucide family and adopt only its contextual accessibility guidance. Passive marks do not inherit button hit-target or focus requirements.

This correction edits only this design handoff. The main owner handles component changes and regression verification in parallel. Existing local preview artifacts remain the accepted design provenance; no new Stitch generation, preview rendering, or runtime verification is claimed. Runtime evidence belongs in [the verification record](../../testing/ISSUE_63_VERIFICATION.md); historical static preview checks do not prove this correction.

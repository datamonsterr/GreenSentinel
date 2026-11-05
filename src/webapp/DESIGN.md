# Analyst Cockpit center panel: visual rules

These rules are frozen from the approved Stitch previews in `.stitch/previews/`. They apply to the
`/workplace` center panel only. The left case queue and the right Analyst Copilot sidebar keep their
own styles.

Shared building blocks live in `components/cockpit/`. Pure data derivations live in
`lib/cockpit-signals.ts`.

## Tokens

- **Font:** Inter for UI text, JetBrains Mono (`font-mono`) for IDs, plates, codes and timestamps.
- **Primary:** emerald (`emerald-700` `#047857`) for active state, primary buttons and the "Active"
  badge.
- **Surfaces:** white cards on a `slate-50` panel wash, with a 1px `slate-200` border, `rounded-lg`
  (8px) corners and `shadow-xs`. Never stack heavy shadows.
- **Text:** `slate-900` for values and titles, `slate-500` for labels and captions.
- **Severity color:** use it only when a measurement is flagged: `red-700` for danger, `amber-700`
  for warning, `emerald-700` for success. Unflagged values stay `slate-900`.
- **Tile tints** (`toneTile` in `icon-tile.tsx`):

  | Tone | Classes |
  |---|---|
  | neutral | `slate-100/600` |
  | success | `emerald-50/700` |
  | warning | `amber-50/700` |
  | danger | `red-50/700` |
  | info | `sky-50/700` |
  | violet | `violet-50/700` |

## Icon tiles

- **Glyphs:** lucide-react, rendered as a block `svg` inside a flex-centered tile. Never use
  inline-text icon fonts in the center panel, because their baseline offsets the glyph.
- **Sizes:**

  | Size | Tile | Glyph | Used for |
  |---|---|---|---|
  | `md` (default) | 44px | 22px | Metric cards and section headers |
  | `lg` | 48px | 24px | Empty states |
  | `sm` | 36px | 18px | Compact empty states |

- **Shape:** `rounded-xl`.

## Type scale

| Element | Size and weight |
|---|---|
| Metric value | 24px, bold, `tabular-nums`, tight tracking |
| Metric label | 13px, `slate-500`, under the value |
| Section title | 14px, semibold. Subtitle 12px, `slate-500` |
| Body, chat bubble, list | 13px, relaxed line-height |
| Caption, timestamp | 11px. Timestamps use `font-mono` |

## Metric cards and grid

- **MetricCard:** icon tile LEFT; value and label stacked RIGHT. No empty half-cards.
- **Value variants:** numbers use the default large figure (24px bold, truncated). Text values such
  as road segment, provider, source or congestion use `variant="text"`: 15px semibold, wrapping to
  at most 2 lines, with the full value in the tooltip.
- **Explanations:** go in the hover tooltip (`title`) through `hint`. Never add a static label for
  them (progressive disclosure, `.agents/rules/ui.md`).
- **MetricGrid:** 3 cards per row. A trailing row of 2 stretches to halves. A trailing single card
  takes the full width. The driver top stats use `columns={4}`. On mobile, every card is full
  width.

## Trip status row

- **Layout:** one 44px line containing these items, in order:
  1. a ring dot
  2. pickup, `→`, destination (adjacent, each truncated, full text in `title`)
  3. the Active and Automatic badges
  4. the fare, pushed right with `ml-auto`
  5. the trip-ID chip with a copy icon

## Empty state

- **Missing source:** any missing value renders `EmptyState` (icon tile, "No data yet", short hint)
  or the MetricCard empty value.
- **Never** render "Unavailable", "undefined", `NaN` or a placeholder number. This includes the map
  status chips (GPS, estimated route) and the map footer (stall point, DAVI drift, ambient). These
  show measured values when present (stall from the active stall point or the measured stationary
  duration, DAVI from the case score) and the muted "No data yet" text otherwise.

## Charts

- **Library:** shadcn `chart` (Recharts) with `ChartContainer`. Give it a fixed height so the
  responsive container can measure.
- **Series colors:**

  | Series | Color |
  |---|---|
  | Trip | emerald `#047857` |
  | Ambient or provider | slate `#64748b` |
  | Peers | sky `#0284c7` |
  | Stop marker | red `#dc2626` |
  | DAVI deviation marker | amber `#f59e0b` |

- **DAVI gauge:** the score follows the backend contract range of −1 to 1. The arc fills
  `(score + 1) / 2`. The color bands (< 0.3 red, < 0.6 amber, otherwise green) only color the arc.
  They are not a verdict threshold.
- **Short series:** a chart with fewer than 2 points shows its empty state.

## Customer tab layout

- **Statement:** the customer statement spans the full width.
- **Columns:** below it are two equal-height columns. Each scrolls on its own, sized
  `h-[32rem]` with `overflow-y-auto`.
  - Left (2/3): the chat thread. Driver bubbles sit on the left with a car avatar; customer
    bubbles sit on the right with a person avatar. Bubbles are at most 75% of the column width.
  - Right (1/3): the event timeline. Each status's dot and segment takes its tone color, with a
    timestamp and a chip for the time spent until the next status. Cancel events are highlighted
    red.

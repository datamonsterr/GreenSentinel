# Compact center header and tabs

Status: user reviewed the preview and authorized implementation with zero gaps between the header, tab bar, and content. Parent issue: #188. This document and its local preview describe the accepted revision; runtime verification belongs to the implementation owner.

## Review artifacts

- [Local HTML preview](preview.html) shows the proposed header and four-tab strip using explicitly illustrative values.
- The preview uses the existing cool white, slate, and emerald cockpit palette, with no external device frame or remote assets.
- No Stitch MCP tool is callable in this session. Stitch screen generation is unavailable; the HTML is a local fallback, not Stitch output or hosted application evidence.

## Information placement

Remove the entire `aria-label="AI Assessment"` banner, including its background, border, heading, pulsing dot, and negative margins. Retain its information in the existing driver header:

| Existing content | Proposed location | Data contract |
|---|---|---|
| Category and confidence | One compact badge next to the driver name and plate | Preserve assessment, case, then active-case precedence. Preserve fraction/percentage normalization and the existing absent-confidence behavior. Provide an accessible name identifying this as AI advice. |
| Priority | Badge beside category/confidence | Preserve `caseDetail.case.priority || activeCase.severity` and current semantic colors. |
| First three reason codes | Small code badges in the existing wrapping driver-metrics group | Preserve the existing nonempty conditional and first-three limit. Identify the group as assessment signals. Do not invent codes or inferred labels. |
| `AI Assessment:` label and pulsing dot | Remove | They repeat the badge context and do not establish an actual streaming state. |

Category/confidence also appears in the queue, but that is a separate navigation context and may use different precedence. These values are not already present in the upper center header. Reason codes are unique within that header and must survive the row removal. Keep each moved value once in the center header. Use direct priority values such as `P1`, with contextual tooltip and accessible label; omit visible static `Priority:` and `Signals:` labels. Preserve the existing driver information, route, fare, claim/release/archive control, and lock notice. Do not turn AI advice into an adjudication status.

The driver identity group remains left aligned. The claim/release control remains at the right. Identity badges wrap together when necessary; metric and signal badges wrap between items, never inside metadata pills, following master design Rule 10. Truncate exceptional long codes on one line with ellipsis, a full-value title, and the complete code retained as accessible text. Do not replace the source string with an abbreviated value. Header height is content-driven; do not enforce a fixed height or promise equal savings for every case.

```text
[avatar] Driver name  [plate] [category (confidence)] [priority]   [Claim]
         [rating] [acceptance] [cancellation] [vehicle] [signals…]
---------------------------------------------------------------------
Pickup → Destination                              [status] [match] [fare]
[Overview] [Conversation] [Driver Information] [Workflow Synthesis]
[Main content starts immediately below the tab strip]
```

## Dimensions and tokens

Use the current Inter/system sans and existing monospace stack for machine codes. Preserve current header font sizes; this request slightly reduces the tab labels and icons. Reuse existing Tailwind semantic/color classes without changing the global theme.

| Element | Current | Proposed desktop target |
|---|---|---|
| Header outer padding | 12px | 12px |
| Header internal section gap | 10px | 8px |
| Driver identity-to-control gap | 12px | 8px |
| Tab strip outer padding | 6px | 2px |
| Gap between tabs | 6px | 4px |
| Tab button padding | 8px horizontal, 6px vertical | 6px horizontal, 4px vertical |
| Tab strip height | 51px measured in the baseline browser | 33px including bottom border |
| Tab button height | 38px measured in the baseline browser | 28px minimum |
| Tab label | 12px | 11px with explicit 16px line height |
| Tab icon | 24px computed in the baseline browser | 14px computed |
| Tab icon-to-label gap | 6px | 4px |
| Header-to-tabs spacing | 10px inherited workspace spacing | 0px |
| Tabs-to-content spacing | Inherited workspace/component spacing | 0px |

Header, tab bar, and active content form one joined surface. Remove external margins, parent gaps, and first-child top spacing at both tab boundaries. The header has only upper outer corner radii; the content has only lower outer corner radii. Keep one hairline divider at each join, avoiding doubled borders. Preserve normal interior content padding and gaps within evidence widgets. If a guardrail notice is present, it remains immediately below the tabs and within the joined content surface.

The proposed tab strip is 33px including its bottom border at ordinary desktop density. Reserve equal-width slots for all four views. Use a transparent border on inactive tabs so active state does not change dimensions. Preserve the active white surface, emerald icon/text, and thin slate border. Hover changes color only; focus remains clearly visible.

The baseline browser measured 24px tab icons because remote Material Symbols CSS overrides the utility; local `globals.css` also declares an unlayered `.material-symbols-outlined { font-size: 15px; }`. Verify computed icon size after implementation; an ordinary Tailwind `text-[14px]` does not establish the rendered size. Scope any necessary override to this tab icon, not every symbol in the application.

Palette roles: white `#ffffff` for the panel/active tab, slate-50 `#f8fafc` for the tab surround, slate-200 `#e2e8f0` for structural borders, slate-900 `#0f172a` for primary text, slate-600 `#475569` for secondary text, and emerald-700 `#047857` for active emphasis. These mirror current local components rather than replacing the master theme.

## Semantics, responsiveness, and streaming

- Retain all four visible labels, stable tab IDs, active state, and callbacks. Preserve `aria-selected` and tab-to-panel relationships. Decorative icons remain `aria-hidden`.
- Existing roving tab indices lack arrow-key support. Add minimal ArrowLeft/ArrowRight and Home/End navigation with focus transfer and selection, including wraparound. Keep visible focus and verify corresponding panel IDs exist. The preview is an appearance specimen with working native buttons, not proof of application tab accessibility.
- 28px is the compact desktop pointer target, consistent with the authoritative master design's 28px/36px controls and desktop console scope. Compact 11px labels are an explicit exception for short workstation controls; do not shrink body copy to this size.
- Preserve existing responsive behavior. Allow the relocated badge groups to wrap at narrower panel widths and at 200% zoom. Keep all four tab labels accessible when visually truncated; avoid page overflow. Do not introduce a mobile app layout or additional navigation.
- Keep guardrail and lock notices in their existing positions and roles. Do not merge safety notices into advisory badges.
- Moving presentation must not change data subscriptions, hook order, component keys, active tab state, transcript state, or SSE lifecycle. Do not announce each relocated badge as a separate live region.
- No new dependency, generic header abstraction, or global typography change is needed.

## Skill application and checks

Applied `frontend-design` for restrained changes to the existing analyst cockpit; `ui-styling` for Tailwind composition and semantic controls; `design-system` for token roles; and `ui-ux-pro-max` for content-preserving overflow behavior. The focused UX query matched **Compact Label Overflow**; the stack query matched **Compact label layout**. Only recommendations relevant to the present component are used.

After implementation, verify: the banner is absent; category/confidence, priority and first three reason codes remain visible exactly once in the center header; absent confidence/codes and zero confidence retain existing behavior; assessment-versus-queue precedence is preserved; tab selection still reveals the correct content; long names and pill groups wrap without page overflow while individual codes remain single-line; lock and archived states survive; streaming continues across tab switches. Extend the existing tab component tests for click selection, ArrowLeft/ArrowRight wraparound, Home/End selection, and focus movement. Use browser checks for computed 14px icons, 28px buttons, visible focus, header placement, and 200% zoom. Measure both header-bottom/tab-top and tab-bottom/content-top boundaries at 0px external gap for every tab, including the guardrail state. The parent reported a 246-test unit baseline; this is a pre-change result, not verification of the revision. Local preview validation does not establish runtime, hosted, or SSE proof.

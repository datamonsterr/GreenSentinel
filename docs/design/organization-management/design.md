# Organization management visual proposal

**Status:** User approved the corrected preview on 2026-10-14 with the reply “approve”. The approved application UI is implemented in PR #343; current verification evidence is recorded in the [manager runbook](../../testing/manual/ORGANIZATION_MANAGEMENT.md).
**Route:** `/organization`.

The corrected [interactive HTML preview](preview.html) and its local screenshots are the precise proposal for review. They show an organization manager's members, roles, and invitations using illustrative records. The original Stitch screen is design-source evidence, not the final proposal.

## Visual direction

Preserve the centered, capped layout and soft panels from the initial proposal. Use plain manager language, with one green **Invite user** action and the Lucide `UserRoundPlus` icon. Remove `Population bootstrap` and `Link driver entity` from the proposed manager interface; preserve Driver as a role.

| Token | Value / purpose |
| --- | --- |
| Canvas | `#f6f8f7`, neutral light grey |
| Surface | `#ffffff`, white cards and controls |
| Primary | `#006948`; hover `#00553a` |
| Border | `#e0e5e2` |
| Main text | `#17231d` |
| Secondary text | `#49564f` |
| Typeface | Existing Inter/system sans-serif stack; no font download |
| Type scale | 22px page heading, 15px section heading, 13–14px body, 11–12px compact labels; mobile inputs 16px |
| Layout | 1120px maximum container, 24px desktop inset and section gap; 12px inset and 16px gap on mobile |
| Geometry | 12px cards/dialog, 6–8px controls; subtle shadows |

Role badges are neutral grey. Green indicates the primary action, focus, and active/success states. Amber and red are reserved for pending/warning and error/destructive states. Token values remain local to the proposal; no application token system is changed.

The review ribbon clearly labels all data as illustrative and exposes state controls. It is preview tooling, not part of the proposed product page. Product copy contains no API paths, schema labels, raw IDs, pagination parameters, provider-delivery promises, or future-phase notes.

## Members and invitations

**Members:** Member, Role, Status, Change role. Show the supplied display name using normal sans-serif text. Roles remain Admin, Analyst, and Driver, with an accessible inline role selector. Do not invent member email, avatar photographs, dates, or workload statistics.

**Invitations:** Email, Role, Status, Actions. Pending rows offer Resend and Revoke. Revoked rows keep these actions disabled. Invitation IDs remain internal and are not displayed.

Each table has search, role/status filters, reset, sortable headers, and a current-page footer. Search uses member display names or invitation emails. The visible scope statement is exactly:

> Search and filters apply to this page.

Counts describe only filtered records in the loaded page. They are not organization-wide totals. The illustrative dataset contains one page, so Previous/Next controls are disabled. Production pagination requires separate application validation against actual API responses.

At narrow widths, controls wrap and each table scrolls within its own focusable region. The document itself must not scroll horizontally. Search controls have accessible names, sort controls are buttons, and column headers expose `aria-sort`.

## Invite user dialog

The header action opens a white dialog with:

- **Email address:** required native email input, focused on open.
- **Role:** labelled native select containing Admin, Analyst (default), and Driver.
- Helper: “Choose the access this person needs.”
- Cancel and green **Invite user** actions.

Enter submits a valid email. Invalid or empty input uses native browser validation. Tab and Shift+Tab stay within the dialog; Escape closes it and focus returns to the trigger. Background controls are inert while the dialog is open. Reduced-motion preferences disable preview animations.

The preview simulates a 500ms pending state, then adds an illustrative invitation and displays “Invitation added for [email].” No request is sent. Cancel or Escape cancels the pending preview timer.

**Existing backend constraint:** The baseline invitation API records invitations in memory; it does not send Clerk invitation emails. The proposal therefore makes no email-delivery, SSO, or company-domain guarantee. Preview Resend feedback is explicitly illustrative. Persisted invitations and provider delivery are not established by this proposal.

## States

| Review state | Local preview |
| --- | --- |
| Standard | Three illustrative members and two invitations |
| Dialog | Email field, Analyst default, labelled role select |
| No analyst | Fixture with no analyst plus “No analysts yet. Invite an analyst to help review cases.” |
| Empty | Zero results with plain filter guidance |
| Loading | Table-row skeletons; reduced motion supported |
| Access error | Admin-access message; illustrative 403 state |
| Pending / success | Demonstrated by a valid form submission; local state only |

The no-analyst fixture is a visual example, not proof that a loaded page determines organization-wide analyst presence. The implementation must use the existing authoritative warning condition. Missing configuration or provider failures require manager-facing error copy and application tests when implementation is approved; they are not currently demonstrated by the state ribbon.

## Data and implementation boundary

The design uses the existing shapes:

- Member: `id`, `display_name`, `roles`, `status`.
- Invitation: `id`, `email`, `role`, `status`.

IDs remain available for internal action targeting. Current API pagination does not establish global search or global role filtering. Future application work should reuse existing Next.js, Tailwind, and shadcn/ui conventions, preserve auth/bypass behavior and SSE compatibility, and validate actual contracts before wiring actions.

The approved application should use shadcn/ui `Dialog` for the invitation modal, `Input` for email/search, `Select` for role and status controls, `Button` for actions and sortable column headers, and `Table` for the member/invitation grids. Use the existing Lucide `UserRoundPlus` icon. The native HTML controls in this dependency-free preview demonstrate the appearance and behavior; they do not replace the requested application components. References: [shadcn Dialog](https://ui.shadcn.com/docs/components/radix/dialog) and [Data Table](https://ui.shadcn.com/docs/components/radix/data-table).

The initial draft contained documentation and the standalone preview. The approved implementation adds the requested application components and behavioral tests; backend initialization and invitation delivery remain outside this UI redesign.

## Stitch provenance

Stitch MCP generation previously succeeded and was not repeated during refinement:

- Project: `projects/11976853810912444296`, “GreenSentinel Organization Manager Redesign”.
- Tool: `generate_screen_from_text`.
- Screen: `efcd30d8fc2949188dfedad4a66288b7`.
- Design system asset: `assets/613c3635f3e749d589108e83f8741064`.
- [Original Stitch screenshot](screenshots/stitch-source.png): preserved from the conductor's downloaded generated screenshot, separately named from local captures.

The generated source contained synthetic member email/avatar suggestions beyond the current member shape. The authored HTML adapts the visual direction to the existing data contract. It must not be labelled as raw Stitch output.

## Local preview verification

Verified on 2026-10-14 using installed Chromium 1243 through the isolated `agent-browser` session `greensentinel-org-refine-1014`, opening the local HTML directly.

| Check | Observed result |
| --- | --- |
| Open dialog | Email focused; Analyst selected |
| Focus containment | Tab wraps last-to-first; Shift+Tab wraps first-to-last |
| Close dialog | Escape closes; focus returns to Invite user |
| Validation | Invalid email + Enter leaves dialog open; invitation not added |
| Submit | Valid email + Driver + Enter adds illustrative Driver invitation; returns focus; success text appears |
| Members | Name search and Driver filter narrow rows; reset restores records |
| Invitations | Email search and Revoked filter narrow rows; reset restores records |
| Sorting | Keyboard Enter toggles member name ascending/descending; email sorting works |
| Mobile | No document overflow at 320×700 and 390×844; dialog fits at 390×844; tables scroll locally |
| Browser errors | No page errors reported during checks |

Checks apply only to this standalone preview. They do not establish application acceptance, backend mutations, persistence, Clerk delivery, hosted behavior, or screen-reader/device coverage. Existing manual application acceptance remains a separate deliverable.

## Review artifacts

- [Interactive proposal](preview.html): standalone, no dependencies or network requests.
- [Desktop](screenshots/desktop.png): 1440×960 viewport.
- [Invite dialog](screenshots/modal.png): 1440×960 viewport.
- [Mobile page](screenshots/mobile.png): full-page capture from a 390×844 viewport.
- [Mobile dialog](screenshots/mobile-modal.png): 390×844 viewport.
- [No-analyst warning](screenshots/no-analyst-alert.png).
- [Empty results](screenshots/empty-state.png).
- [Loading](screenshots/loading-state.png).
- [Access error](screenshots/error-state.png).
- [Original generated Stitch source](screenshots/stitch-source.png).

Desktop state captures use a 1440×960 viewport. Open the local preview with `#default`, `#modal`, `#no-analyst`, `#empty`, `#loading`, or `#error` for the corresponding initial state.

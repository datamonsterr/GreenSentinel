# ADR-036: Analyst explanation provenance UI and VH help queue

Status: accepted · Scope: analyst part of slice S-D2 of `docs/plans/2026-11-20-prd-features.md` (PRD-A US2-US4). Builds on [ADR-034](adr-034-driver-explanation-session.md) (API), [ADR-031](adr-031-gsm-workflow-roles.md) and [ADR-032](adr-032-knowledge-base-roles-and-lifecycle.md) (roles). No backend change.

## Context

S-D1 exposes the explanation session to staff (`GET /cases/{id}/explain`, feedback, help queue) but the cockpit showed none of it: analysts could not see assessment rounds, which published knowledge the agent used, or answer an agent help request, and VH feedback had no UI.

## Decision

**Presentation tier only** (3-tier layering kept): `lib/explain-client.ts` (typed calls to the existing routes plus pure helpers: latest feedback per author, state/flag tone, line diff of statement versions, role gates) -> `components/adjudication/explain-section.tsx` and `components/explain/help-queue-panel.tsx` -> mounted in the cockpit Overview tab and the portal top bar. `lib/api-client.ts` is untouched; `lib/driver-explain-client.ts` (S-D2a) stays driver-only.

**"Giải trình AI" section** (Overview tab, rendered only when the case has a session; 404 hides it, other errors show a quiet status line): flags as `.gs-tone` chips (`flagTone`), statement versions (expandable; later versions show a line diff against the previous one), assessment rounds with the four states as tone chips (`eligible` green, `not_eligible` red, `needs_driver` amber, `missing_internal` grey), provenance list (type, code, version, tool), suggestion block (state, confidence, suggested questions, turns used / N_max), help-request history, and the structured feedback form (agree, or disagree with at least one of six error types, plus comment). Feedback is append-only server-side; the UI lists only the newest entry per author.

**Help queue** (plan Decision 11, analyst stands in for VH): a top-bar button with a badge from `GET /explain/help-requests/count` polled every 30 s (`total` = open + claimed) opens a right drawer listing open and claimed requests; claim, then reply with text and one fact per line (the reply creates a pending kb proposal and resumes the agent server-side). Replying refreshes the badge.

**Role gating**: feedback form and help queue only for `analyst`, `senior_analyst`, `fraud_analyst`, `admin` (`canGiveFeedback`/`canUseHelpQueue`). `reviewer` and `ops_director` see the section read-only and no queue button, even though the API would accept `reviewer` feedback (UI is stricter on purpose: ADR-031 read-only roles).

**Style**: cyan theme tokens only (`gs-*`, `.t-*`), no Tailwind palette classes; strings are inline vi/en maps like the surrounding cockpit components.

## Consequences

- Tests that stub cockpit fetches must answer `/cases/{id}/explain` (404 = no session).
- The section reads once on case open; it does not poll, so a reply made in the drawer shows after switching case or reload.
- Open: link from the queue item to the exact case in the cockpit queue relies on the existing `caseId` deep link; a timer-driven refresh of the section is not built.

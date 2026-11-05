# Center header and compact tabs

## Scope and evidence

Verify [issue #188](https://github.com/AI20K-Build-Phase-Cohort-4/P-063/issues/188) against the [approved scoped design](../../design/center-header-compact/design.md). Use the rendered cockpit boundary and the existing header/tab component tests. API fixtures are synthetic presentation evidence; they do not prove a migrated database or authenticated hosted behavior.

Fixture case: `11111111-1111-4111-8111-111111111111`. Use a disposable local test server with the repository's explicit E2E authentication configuration and the existing browser API fixture installer. Never enable test authentication on a hosted environment. Use an isolated `agent-browser` session and record its revision, URL, viewport, observations, and screenshots.

## Steps

1. Open `/workplace`, select the fixture case, and inspect the center header. Confirm the complete `AI Assessment` row is absent. Category/confidence, priority, and any supplied first three reason codes appear in the existing upper header. Compare a different assessment category/confidence with the queue to verify assessment precedence. Check zero and absent confidence, absent codes, long codes, and priority values.
2. At 1440 × 900, inspect the joined header, tab strip, and Overview content. Measure the header's bottom against the strip's top, then the strip's bottom against the active panel's top. Both gaps must be zero, with at most 0.5px rounding tolerance. Repeat for Conversation, Driver Information, and Workflow Synthesis. Preserve intentional internal content padding.
3. Measure the computed button height, label font size, and icon font size. Expect 28px, 11px, and 14px respectively. The strip is 33px including its border. Confirm active and inactive buttons retain equal dimensions.
4. Click every tab and verify its associated content. Focus Overview with the keyboard. Use ArrowRight/ArrowLeft, Home, and End; confirm selection, wraparound, focus movement, and a visible focus outline. Verify tab IDs and panel labels remain associated.
5. Repeat the join and overflow checks at 1280 × 900 and at 200% CSS zoom. Metadata pills remain single-line, complete values remain accessible, and wrapping between pills does not create page overflow.
6. Verify read-only lock and archived cases retain their notices and controls. Supply blocking guardrails and confirm their warning remains visible. Switch tabs during an advisory stream and confirm the stream/transcript remain intact.

## Observations

Baseline at `05bb3da`, local fixture cockpit, 1440 × 900: full frontend units passed (34 files, 246 tests). The header measured 155.3125px; the tab strip measured 51px; buttons measured 38px; labels measured 12px; icons measured 24px despite a smaller utility class. The header-to-tabs gap was 10px, and one assessment row was present. [Before screenshot](../assets/center-header-tabs/before-1440.png).

Verified source revision: `aafc554`, rebased onto `b9cc1a2`; upstream additions affect architecture documentation only. These manual observations were made on the same UI source before that documentation-only rebase, on 2026-10-08, using `agent-browser --session p063-ui-review`, `http://localhost:3187/workplace`, local E2E authentication, and the fixture case above.

| Check | Observed result |
|---|---|
| Four tab joins at 1440 × 900 | Both joins measure exactly 0px in all four views. |
| Compact dimensions | All buttons: 28px; strip: 33px; labels: 11px; icons: 14px computed. |
| Metadata | No assessment row. Header shows `ERR-02 (83%)`, `P1`, and exactly the first three full codes. Queue retains its distinct `route_integrity (92%)`, confirming detail precedence. |
| Keyboard | ArrowLeft wraps Overview to Workflow; Home/End and ArrowRight move selection/focus correctly. Focus outline: 2px. |
| State retention | A manually entered draft and collapsed violation widget survive tab switches. No decision was submitted. |
| Stream retention | A synthetic delayed SSE response completes while Workflow is selected; reply remains visible and input becomes enabled again. |
| Dense/zoomed layout | 1280 × 900 and 200% CSS zoom preserve zero joins without page overflow. Native browser zoom was not exercised. |

[After at 1440px](../assets/center-header-tabs/after-1440.png) and [after at 1280px](../assets/center-header-tabs/after-1280.png) show synthetic case data in the runtime interface. Zoom/stream screenshots timed out in browser tooling; rendered DOM observations supplied their evidence. External map font-glyph requests returned 404s; tab and geometry checks remained available. The standalone design preview remains illustrative.

## Automated verification and review

Fresh conductor commands on 2026-10-08:

- `pnpm --dir src/webapp test`: 254 passed in 34 files.
- `pnpm --dir src/webapp test:typecheck`: passed.
- `CI=true PORT=3191 pnpm --dir src/webapp test:browser`: 22 passed, 3 skipped. Skips: two persisted API opt-ins (`ISSUE143_BROWSER_API`) and one live Clerk opt-in (`RUN_LIVE_AUTH_E2E`). All four joins, normal/blocking guardrails, metadata, dimensions, keyboard focus, and CSS zoom are covered.
- `NEXT_PUBLIC_E2E_TEST=true pnpm --dir src/webapp build`: passed after browser tests stopped.
- ESLint over six changed sources: 5 errors, 32 warnings. All errors reproduce on unchanged base source: four cockpit ref/purity errors and one conversation memoization error. No new errors; this command is not claimed as passing.
- Whitespace and staged secret-keyword audit: passed.
- Independent read-only review: no actionable scoped regressions; 32 focused tests and test typecheck passed. Its browser startup was sandbox-blocked; conductor browser execution supplied fresh proof.

TDD evidence includes an observed failure finding the named header and geometry failures (10px content gap normally, 8px with guardrails), followed by focused passing tests after the fixes. Extra preservation scenarios are regression coverage, not separate RED cycles. Exact PR-head CI/deployment results belong in the PR. Fixtures do not establish authenticated hosted, model-quality, or persisted database acceptance.

# Revised manual preview verification

Date: 2026-10-14. Scope: local design preview, Chromium, existing Playwright and MapLibre installations. The earlier preset-dashboard captures are superseded.

The current-source baseline was produced by bundling the unchanged `src/webapp/app/test/page.tsx` with Bun. Fixtures replace Clerk, test API imports, Next.js link/dynamic behavior, and the map renderer. Styling comes from an existing compiled project stylesheet. Baseline screenshots establish source-layout comparison only; they are not hosted authenticated evidence.

The revised preview loads a real OpenFreeMap basemap through MapLibre. Its map canvas, markers, pan/zoom, and visible attribution are real browser rendering. Address resolution uses a named local list. Run state, chat, cancellation, history, and title behavior are explicitly local demonstrations. No trip endpoint is called.

Verification covers:

- 330px left and 360px right rails at 1600px, matching current JSX composition.
- Expanded dock fraction approximately 0.4004 of the bounded console area; collapse increases map height.
- Each of the three markers changes its corresponding address on pointer drag.
- Arrow-key marker movement and named address selection as alternatives.
- Bare map click creates no extra stop.
- Run/Pause/Resume state transitions.
- Completion unavailable before destination, available at destination, unavailable after cancellation.
- Customer/Driver cancellation requires a trimmed reason and retains actor/reason in event details.
- Keyboard tab activation and visible focus styling.
- No horizontal document overflow in all three sections at 1024/1600px desktop widths.
- No trip API requests or browser JavaScript errors.

[Raw result record](verification-results.json) accompanies the screenshots. A failed check must be resolved before this document is represented as passing evidence.

Desktop, cancelled-event, and current-source desktop fixture screenshots were visually reviewed. Captures of dialog and cancellation event show illustrative identifiers and local timestamps; those fields are not proof of persisted event receipts. The blank Overview measurements intentionally represent missing system results.

Not established: authenticated membership, organization isolation, live address resolution, road route calculation, vehicle simulation, command persistence, cancellation API semantics, agent/case evidence propagation, SSE delivery, pipeline throughput, or classification accuracy. User visual approval and later implementation verification remain separate gates.

Mobile preview assets, adaptation CSS, and historical mobile measurements were removed on 2026-10-15 at stakeholder request. This console supports desktop only.

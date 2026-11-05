# Workspace PR #373 verification

## Scope and revision

PR #373 was rebased onto `main` at `fe9be9ca`, including main's `queue:max` Docker concurrency fix and preview seed flag. The exact local recovery head is `2690dfd1` on `pr373-recovery`. This record covers issue #368 and PR #373.

The earlier viewer-test 15-second timeout was CI runner starvation, not a source defect: CI took 604 seconds versus 147 ms locally and neighboring tests were 10–50 times slower. The test passes in CI after the rebase.

## Changes since `e2c26e1b`

- Repeated unavailable states are collapsed; customer typography is compact and `1 turn` is singular.
- Trip facts show one unavailable indicator; the orphan `ROUTE` label is hidden.
- Counterargument delta is localized; unavailable ping/speed chips stay hidden.
- Mobile panels stack without overlap (`center >=70vh`, `shrink-0`); the center Overview Claim is removed, leaving claim/release on the queue card.
- The duplicate bottom queue-card ID is removed; the top ID is the copy chip.
- Five center tabs are polished. Relative scroll containers fix document overflow (previously 4822 px).
- Driver-history labels are inline; the customer card contains customer feedback/rating only.
- The narrow header keeps a compact EN|VI switch. Copilot input placeholders use workspace i18n.

## Local exact-head evidence

The user-supplied exact-head proof at `2690dfd1` records:

| Check | Result |
|---|---|
| Vitest (`CI=1`) | 67 files, 549 tests passed |
| TypeScript | app, test, and browser configs passed |
| Ruff | format and check passed |
| Playwright | active-queue, workspace-completion, and cockpit: 21 passed; 2 pre-existing skips |

The current uncommitted placeholder change is separate from this historical exact-head proof.

## Fresh uncommitted Copilot placeholder repair — 2026-10-16

Focused TDD RED confirmed the Vietnamese placeholder was absent with the expected `TestingLibraryElementError`; GREEN passed one file with 6 tests. `CI=1 npx vitest run` could not start because pnpm reported `ERR_SQLITE_ERROR unable to open database file`; the direct fallback `CI=1 ./node_modules/.bin/vitest run` passed all 67 files and 550 tests in 124.93s. App and test TypeScript checks passed with `./node_modules/.bin/tsc --noEmit -p tsconfig.json` and `./node_modules/.bin/tsc --noEmit -p tsconfig.test.json`. The supplied 2690dfd1 proof remains 549 tests; hosted audit, browser, and Ruff evidence were not rerun for this uncommitted patch.

## Preview seed and hosted audit

[`scripts/seed_preview_enrichment.py`](../../scripts/seed_preview_enrichment.py) is synthetic and idempotent. It never seeds analyst preliminary judgments or adjudications on active cases; coverage is documented in [`docs/data/PREVIEW_SEED_COVERAGE.md`](../data/PREVIEW_SEED_COVERAGE.md). After user approval, it was applied to the shared Dev DB used by PR-preview backends on 2026-10-16:

`vehicles 12`, `drivers 121`, `trips 104`, `fare_quotes 104`, `driver_submissions 104`, `passenger_feedback 104`, `telemetry events 3439`, `historical trips 1200`, `past adjudications 1`. Re-running is idempotent, with zero duplicate feedback or submissions.

The authenticated hosted audit used an analyst account against preview `green-sentinel-f4j3org6v` (`2690dfd1`) and backend `greensentinel-backend-dev`. At 1440×900 and 390×844, all five tabs had no horizontal overflow, document height equaled viewport height, Material Symbols loaded, the center was white, and data was populated: fare `300,000 ₫`; driver VF 5 Plus, 4.86, 97.2%, 1.7%, 1730; history labels, incidents, and customer feedback. EN→VI preserved the Complete tab, selected case, and original-language evidence. AI reveal appeared only where this analyst had their own preliminary judgment.

## Limitations and manual runbook

Traffic corroboration (#365) and willingness (#364) have no persisted contract and remain Unavailable. Existing hardcoded fallbacks in `case_service.py` are listed in [`PREVIEW_SEED_COVERAGE.md`](../data/PREVIEW_SEED_COVERAGE.md). Hosted CI Docker/E2E status is left for the orchestrator to fill.

Manual steps: [workspace runbook](manual/workspace-368.md).

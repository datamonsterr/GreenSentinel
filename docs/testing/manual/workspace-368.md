# Fraud workspace #368 manual checks

1. Open `/workplace` as an authorized analyst and select an available case.
2. Claim the case from its queue card (Overview has no center Claim action) and verify the lease state updates; release it from the same queue card when finished.
3. Visit the five center tabs: Overview, Maps, Customer, Driver, and Complete. In Maps, confirm route, traffic, sensor, telemetry, and kinematic evidence are shown with provenance.
4. In Customer, verify the card contains customer feedback and rating only. Open Driver Relay to submit an inquiry, switch to another case before the response returns, and verify the response cannot appear on the second case.
5. In Driver, verify identity falls back to the real case record when absent from the trip. Confirm rating, acceptance/cancellation rates, trip count, history, benchmark ratio, and tenure use explicit unavailable states when absent. Switch Driver to Complete and back repeatedly; only the selected panel may appear.
6. In Complete (Hoàn tất), verify AI results stay hidden until an independent judgment is saved. Confirm the saved judgment and optional note remain visible after reload and in the read-only archive. Verify decision controls remain lease and authorization gated.
7. Switch EN/VI and confirm tab labels, authored workspace labels, map controls, units, and status text translate without changing case or evidence.
8. Release the case and confirm it becomes available again; inspect the browser console for runtime errors.


## Historical refinement notes — 2026-10-15

- Case cards expose Claim or Release, with no Reject or Dismiss action. Select Complete (Hoàn tất) to review the final decision.
- Without a saved independent judgment, AI output stays hidden and Approve/Dismiss stay disabled. Save an independent judgment, review the evidence, then enter at least 10 rationale characters before explicit Dismiss/Bác bỏ submission.
- Motivation and willingness inputs share a row at workstation widths; shorter notes and reduced padding keep all final actions visible at 1440×900. At 390px width the fields stack without horizontal page overflow.
- Switch English/Vietnamese while editing. The selected tab and original-language rationale must remain intact.

Earlier fixture-browser checks are summarized in [PR #373 verification](../WORKSPACE_PR373_VERIFICATION.md); the dated recovery audit below is the active evidence record.

## PR #373 recovery evidence — 2026-10-16

The branch was rebased onto `main` `fe9be9ca` (Docker `queue:max` concurrency fix and seed flag). A prior viewer-test 15-second timeout was CI runner starvation (604s in CI versus 147ms locally, with neighboring tests 10–50 times slower), not a code defect; it passes in CI after rebase.

Since `e2c26e1b`, the workspace collapsed repeated unavailable states, compacted customer typography and singularized `1 turn`, reduced Trip facts to one unavailable indicator, hid the orphan `ROUTE` label, localized counterargument delta, stacked mobile panels without overlap (`center >=70vh`, `shrink-0`), removed Overview Claim from the center (claim/release remain on the queue card), removed the duplicate bottom queue-card ID (top ID is the copy chip), polished five center tabs, fixed document overflow with relative scroll containers (previously 4822px), added inline driver-history labels, limited the customer card to feedback/rating, compacted the narrow EN|VI header, hid unavailable ping/speed chips, and localized Copilot placeholders.

Local exact-head proof at `2690dfd1`: Vitest `CI=1` 67 files/549 tests passed; app, test, and browser TypeScript configs passed; Ruff format/check passed; active-queue + workspace-completion + cockpit Playwright tests passed 21 with 2 pre-existing skips. The current uncommitted placeholder change is excluded from that historical proof.

[`scripts/seed_preview_enrichment.py`](../../../scripts/seed_preview_enrichment.py) is synthetic, idempotent, and never seeds analyst preliminary judgments or adjudications on active cases; see [`PREVIEW_SEED_COVERAGE.md`](../../data/PREVIEW_SEED_COVERAGE.md). After approval it was applied to shared Dev DB on 2026-10-16: vehicles 12, drivers 121, trips 104, fare quotes 104, driver submissions 104, passenger feedback 104, telemetry events 3439, historical trips 1200, past adjudications 1. Re-run was idempotent with zero duplicate feedback/submissions.

Hosted authenticated audit (analyst account; preview `green-sentinel-f4j3org6v` = `2690dfd1`; backend `greensentinel-backend-dev`) covered five tabs at 1440×900 and 390×844. There was no horizontal overflow, document height equaled viewport, Material Symbols loaded, the center was white, and data populated (fare 300,000 ₫; driver VF 5 Plus 4.86/97.2%/1.7%/1730; history labels, incidents, customer feedback). EN→VI preserved Complete, selected case, and original-language evidence. AI reveal appeared only where this analyst had their own preliminary judgment.

The uncommitted Copilot placeholder repair was validated by focused TDD and local typechecks as detailed in [PR #373 verification](../WORKSPACE_PR373_VERIFICATION.md); the hosted audit was not rerun for this patch.

Traffic corroboration (#365) and willingness (#364) have no persisted contract and remain Unavailable. Existing `case_service.py` hardcoded fallbacks are listed in [`PREVIEW_SEED_COVERAGE.md`](../../data/PREVIEW_SEED_COVERAGE.md). Hosted CI Docker/E2E status remains for the orchestrator.

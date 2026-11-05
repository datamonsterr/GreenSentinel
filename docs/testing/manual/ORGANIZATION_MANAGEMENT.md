# Organization management verification

Scope: the existing `/organization` manager interface, [redesign issue #341](https://github.com/AI20K-Build-Phase-Cohort-4/GreenSentinel/issues/341), and its [design proposal](../../design/organization-management/design.md). Follow the [test guide](../README.md). This document specifies expected behavior; it is not a passed-test record.

Use illustrative data for local preview review. Application verification needs the implementation revision and an Admin session in a disposable organization. Real-account checks follow [authentication guidance](AUTHENTICATION.md); do not record credentials or real member information in screenshots or traces.

## Automated coverage specification

| Boundary | Behavioral coverage |
|---|---|
| Component | Invite button opens a named dialog; labelled email and role fields; initial focus, Escape, focus return, and native form submission by Enter or click. |
| Component | Empty or invalid email never posts; supported role appears in the request; pending submission prevents duplicate requests; failure keeps the form open and preserves values; successful response closes the dialog and refreshes invitations. |
| Component | Member and invitation search, role/status filters, ascending/descending sorting, clear filters, and pagination compose correctly. Verify rows with independently expected names and order, including equal sort values and empty results. |
| Component | Loading differs from an empty roster; list/network failures are visible; failed role changes preserve the authoritative role; resend/revoke show pending and failed states. |
| Component | Changing organization discards the previous roster, filters, and notices; late responses cannot expose another organization's rows. |
| Contract / API | Existing authorization, tenant isolation, supported roles, last-Admin protection, and invitation errors remain unchanged. If query behavior changes, filters and sorting must apply before pagination and preserve organization scoping. |
| Browser | Dialog keyboard flow, search/filter/sort, pagination, row actions, capped desktop width, mobile layout, visible focus, and 200% zoom. |

Place implementation tests in the automatically discovered directories. Use transport mocks only for local component/browser fixtures; they cannot prove Clerk email delivery or hosted authorization. Use RED/GREEN when application work is authorized. Run frontend units, relevant browser checks, lint, type checking, and build; run browser tests and build sequentially in the same checkout.

## Manual scenarios

| ID | Steps | Expected result |
|---|---|---|
| ORG-01 | Open the manager page at 1280px and 1600px viewport widths. | Main content stays centered and capped; green primary action is clear; white surfaces and light grey dividers remain readable. |
| ORG-02 | Open “Invite user” using the keyboard. Press Escape, then reopen. | Named modal opens; email receives focus; Escape closes it; focus returns to the button. |
| ORG-03 | Enter an email, choose Analyst, press Enter. Repeat with the submit button and Driver in a separate trial. | Both controls use the same single submission; selected role is retained; pending feedback prevents duplicate submits. |
| ORG-04 | Submit an empty email and then a malformed email. | Submission is blocked and field feedback explains how to correct it. |
| ORG-05 | Simulate a denied or failed invitation request in the local fixture environment. | Modal stays open; email and role remain editable; error is announced; retry is available. |
| ORG-06 | Search members, choose role/status filters, then sort a column ascending and descending. Clear filters. | Matching rows and order update together; current sort is accessible; clear filters restores results; scope of filtering is accurate. |
| ORG-07 | Repeat filtering and sorting with invitations. Use at least two pages of fixture data. | Filters, sorting, and pagination compose; counts describe actual fetched/results data; no global total is invented. |
| ORG-08 | Change a member role; test a denied last-Admin or privileged update. | Successful response refreshes the authoritative role; denied response explains the failure and preserves the previous role. |
| ORG-09 | Resend a pending invitation, then revoke it. Test a failed request. | Action progress and outcome are visible; revoked invitations cannot be resent; no email-delivery proof is inferred from a local API response. |
| ORG-10 | Review loading, empty organization, no analysts, no filter matches, and list-request failure. | Each state is distinct; manager has a useful next action; failed fetches never masquerade as an empty roster. |
| ORG-11 | Switch active organization while a list request is pending. | Previous organization data and notices disappear; old responses cannot overwrite the new organization. |
| ORG-12 | Review the entire page and network calls. | Manual “Population bootstrap” and “Link driver entity” controls are absent; this page makes no bootstrap or driver-link requests. Driver remains an available membership role. |
| ORG-13 | Repeat at 390px width and at 200% zoom. Tab through filters, tables, and modal. | Controls remain usable; text and actions are not clipped; any table scrolling is contained; keyboard focus is visible and never obscured. |

## Evidence record

Record revision, environment/URL, role, fixture or real-account data class, case IDs, actual observations, and non-sensitive artifact links. The stakeholder approved the final visual proposal on 2026-10-14 with “approve”. Historical implementation result: **verified locally 2026-10-14 — webapp vitest 377/377 (45 files), focused organization suite 46/46, `tsc --noEmit` clean (webapp test + browser configs), ESLint clean, `next build` clean with `/organization` rendered**. Synthetic browser fixtures in `tests/e2e/browser/organization-management.spec.ts` and screenshots in `docs/design/organization-management/application-evidence/` cover the actual app. Preview screenshots verify only the authored proposal.

Baseline limitation: invitation records are in memory and the API does not call Clerk for email delivery. Automatic population initialization was not found in the inspected baseline. The UI redesign alone cannot establish either backend behavior.


### PR #343 repair verification — 2026-10-15

The repair retains the approved application behavior and rebases the original implementation onto `main` at `522b794`. Review identified missing no-analyst and browser pagination coverage. The added component regression distinguishes an actual no-analyst roster from the supported `fraud_analyst` grant. The browser regression exercises two fetched pages, page-scoped filters, exhausted-page navigation, and a second-page invitation refresh, with explicit request-offset assertions.

At unit-test revision `42efc7c`, the full frontend unit suite passes **406 tests in 47 files**; the organization component suite passes **47 tests**. Both test TypeScript configurations pass. The strengthened pagination browser case passes locally at `28e0742`; the authenticated smoke addition passes its browser TypeScript check at `d1e824e`. No application code changes between these verification revisions. The existing real-admin authentication case now opens the actual organization page and checks the invitation dialog, autofocus, Analyst default, Escape, and focus return without transport mocks or invitation mutations. Live execution requires the deployed preview and real role credentials; adding the test is not hosted proof.

Broad `pnpm lint` reports ten existing errors in unrelated workplace, adjudication, driver, cockpit, and Playwright-support files. Changes in this PR do not alter those files. This broad result must remain distinct from the relevant-file ESLint result. Browser-suite, application-typecheck, production-build, and current-head CI results are recorded in the [PR validation section](https://github.com/AI20K-Build-Phase-Cohort-4/GreenSentinel/pull/343). The UI tests use synthetic API records and establish UI behavior only; they do not establish durable invitation storage, email delivery, or automatic population initialization.

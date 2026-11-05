# ADR-028: Workspace reveal and locale boundaries

- Status: Accepted
- Date: 2026-10-15
- Scope: [Workspace #368](https://github.com/AI20K-Build-Phase-Cohort-4/P-063/issues/368), [repair #379](https://github.com/AI20K-Build-Phase-Cohort-4/P-063/issues/379)
- Related: [approved design documentation #371](https://github.com/AI20K-Build-Phase-Cohort-4/P-063/pull/371)

## Context

The six-tab workspace separates source observations from model advice. A persisted independent judgment permits AI reveal in Complete, but must not cause model intent estimates to appear in Overview. The same case can be reviewed in English or Vietnamese without altering source evidence, API enums, or analyst drafts. Trip facts must remain usable on narrow screens.

## Decision

Overview retains the source brief and explicit unassessed motivation and willingness states. Model motivation, its economic incentive and provenance appear in Complete behind the persisted judgment gate. A saved judgment does not authorize model output in other center tabs.

Application-authored labels, accessible region names, role badges and timestamps follow the selected locale. Source statements, raw classifier codes, model narratives and analyst drafts retain their recorded content. Classification `reason_codes` are labeled Reason codes / Mã lý do; they are not runtime errors.

The trip summary stays compact on workstation widths and wraps status, matching and fare below the route on small screens. Its accessible name continues to contain all trip facts and its action still navigates to Trip.

## Consequences and verification

This changes the presentation tier only. Existing API/service/model ownership, authorization, lease checks, persisted judgment and decision submission contracts remain intact. Component regressions cover saved-judgment leakage, bilingual draft and evidence retention, and relocated model narrative/reward. Browser checks cover both locale layouts and reason-code labels. Existing relay tests retain stale-response, deduplication, retry and outbound payload assertions with current locale labels.

Unavailable model/data outcomes remain tracked in #364–#367; these display changes do not establish model validity or database readiness. Validation records distinguish local fixtures, persisted integration and hosted preview evidence.

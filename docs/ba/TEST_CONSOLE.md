# Test Console Product Specification

**Type:** Reference specification. **Audience:** Product, frontend, API, QA. **Goal:** define the approved manual test-console behavior and evidence boundary. This document records product intent; it does not close implementation issues or claim delivery.

## Authority and scope

The baseline is [PRD §11](PRD.md#11-tester-trip-simulation-extension), [MVP §8](MVP.md#8-tester-trip-simulation-extension), and the [approved local design](../design/test-console-refresh/design.md) (user approval: 2026-10-15; no Stitch generation claimed).

Implementation context: [#346](https://github.com/AI20K-Build-Phase-Cohort-4/GreenSentinel/issues/346), [#348](https://github.com/AI20K-Build-Phase-Cohort-4/GreenSentinel/issues/348), and [#288](https://github.com/AI20K-Build-Phase-Cohort-4/GreenSentinel/issues/288). Broader dependencies remain blocked or unresolved in [#291](https://github.com/AI20K-Build-Phase-Cohort-4/GreenSentinel/issues/291), [#294](https://github.com/AI20K-Build-Phase-Cohort-4/GreenSentinel/issues/294), [#300](https://github.com/AI20K-Build-Phase-Cohort-4/GreenSentinel/issues/300), and [#302](https://github.com/AI20K-Build-Phase-Cohort-4/GreenSentinel/issues/302). GitHub Issues retain ownership, DoD, blockers, and status.

The test console supports desktop only (1024px and wider). Mobile layouts, mobile previews, and mobile acceptance targets are excluded. The three-pane workstation remains the supported interface.

## Product rules

### Trip composition

- Exactly three immutable stops define a plan: **Initial driver position**, **Pickup**, and **Destination**. Stops are editable before execution; once a run starts, they are immutable.
- Members of the current organization may use `/test`. Access depends on valid membership and session; no analyst/tester role gate is assumed.
- Selected Passenger and Driver actors are tenant-owned records. The client cannot authorize a foreign actor or substitute a caller-supplied tenant.
- Address search, marker drag, and keyboard marker movement are authoring paths. Coordinates remain transport data, never user-facing GPS X/Y fields. A move invalidates the prior route and requires reconciliation.

### Run lifecycle and authority

- The run control follows acknowledged state: **Run → Pause → Resume**. Resume continues the same run.
- **Complete trips** is enabled only after the destination is reached. It records normal completion.
- **Customer cancel** and **Driver cancel** are early termination actions. Each requires a trimmed, non-empty reason and records the canonical actor, reason, timestamp, event and run/trip/tenant references.
- Completion and cancellation are distinct authoritative outcomes. A client label, local preview interaction, model output, or failed/uncertain request cannot confirm either outcome. Failed commands retain input and expose retry/reconciliation state.

### Evidence and streaming

- Logs, overview metrics, classifications, notifications, and case state show recorded backend evidence or explicit unknown/waiting/error states. No fake metrics, verdicts, delivery claims, or fabricated routes.
- Consume authentic SSE for the run with one subscription, event-ID deduplication, cursor resume, cleanup on scope change, and REST reconciliation after gaps. Connection, lifecycle, classification, and case-creation states remain separately observable.
- The Log/Overview dock expands to 40% of the bounded desktop console viewport. Expansion must preserve focus, scroll, and row state while new events arrive.

### Presets, history, and titles

- Presets expose metadata provenance. A preset may identify provider, repository, release, revision, labels, and availability; it cannot imply replayability when the replay API is blocked or unavailable.
- Preset availability and selected count are explicit API states. Do not present metadata as a successful replay or invent selection results.
- Plan/run titles persist through the backend and reload in history. History is organization-scoped and clears stale cached scope on tenant change.

## Delivery boundary

The design and this specification are accepted product inputs. They do not prove implementation, migrated storage, hosted authentication, SSE behavior, model quality, or UAT. Verification cases are in [TEST_CONSOLE_AUTH.md](../testing/manual/TEST_CONSOLE_AUTH.md). Do not mark these outcomes complete until executable evidence exists.

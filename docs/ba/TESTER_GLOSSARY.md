# Tester Simulation Glossary

These terms describe the Tester extension in [PRD §11](PRD.md#11-tester-trip-simulation-extension). They do not add implementation or adjudication authority.

## Language

**Tester**: A signed-in member of the active organization who composes trips and operates simulated actors to observe the system. The 2026-10-14 request makes this an activity, not a separate console access role. A Tester is not automatically an analyst.

**Customer cancellation**: A passenger ends the simulated trip before its destination and supplies a reason. The interface uses “Customer cancel”; the stored actor is `passenger`.

**Driver cancellation**: The driver ends the simulated trip before its destination and supplies a reason. The stored actor is `driver`.

**Passenger**: The ride-hailing user represented in the lower-left actor window. Use Passenger in contracts and documents; the UI may introduce it as “Passenger (user)”.
_Avoid_: Customer, analyst.

**Driver**: The simulated vehicle operator represented in the upper-left actor window. Their role-play replies are evidence, not analyst decisions.

**Trip definition**: The editable description of an intended trip, including locations, movement, conversation and context.
_Avoid_: Run, detection scenario.

**Definition revision**: A saved version of a trip definition. Inputs already consumed by a run remain attributable to their original revision.

**Run**: One execution of a definition revision and its ordered runtime inputs, observations and system results.
_Avoid_: Case, preset scenario.

**Simulated position**: The vehicle position prescribed by the motion plan. It may differ from reported GPS when the Tester introduces a fault.

**Reported GPS**: The location evidence actually emitted to the system. Missing or intentionally corrupted fixes must remain observable.

**Sandbox notification**: A system notification delivered only to the simulated actor inbox within an isolated test environment.
_Avoid_: Live Passenger message, production push.

**Assessment**: The system’s advisory interpretation of received evidence, including uncertainty and conflicting context. It does not confirm guilt.

**Workplace**: The existing analyst application and assignment flow. Reusing its layout does not imply using operational production data.

**No-case observation**: A verified assessment outcome with no case during a stated observation window. An unfinished or failed stage is not a no-case observation.

**Trip preset (published example)**: A recorded example trip from the published synthesized-trips release, offered in the console’s Trip library so a Tester can start from real evidence instead of authoring coordinates. A preset’s source label describes the recording, never a model prediction; a preset whose detection rule is not yet verified is listed as unavailable.
_Avoid_: Scenario template, ground truth case.

**Processing dock**: The collapsible Log/Overview panel at the bottom of the manual console. It reports recorded pipeline stages and observed classification counts, and never fabricates throughput, verdicts or Driver delivery.

# Geoapify Verification Runbook

**Status:** Proposed runbook. Future integration checks are **NOT EXECUTED** unless an entry below says otherwise.

## Preconditions

- Use a disposable local environment or the exact deployed revision.
- Keep Geoapify keys in server-side environment configuration. Never paste a key into a browser bundle, test artifact, issue, or PR.
- Confirm quota, licence, attribution, and provider plan before any hosted or tile check.
- Run automated suites first using the [test guide](../README.md).
- Record revision, environment, request class, case/run ID, observed result, and trace/screenshot links.

## Executed capability evidence

The sanitized probe record is [capabilities-2026-10-08.json](../artifacts/geoapify/capabilities-2026-10-08.json). On 2026-10-08, six authenticated public-Hanoi probes returned HTTP 200 for geocoding, reverse geocoding, routing, map matching, map style, and MCP tool discovery. This is provider capability evidence only. It is not national coverage, quota/licence acceptance, browser proof, production proof, valid past traffic, or UAT.

Observed details include a route `MultiLineString` of 1,317 m and 87.581 s with `free_flow` traffic, map-matching results containing two matched points and one unmatched point, and an MCP response listing 11 tools. The six request latencies are recorded individually; total investigation time and application performance were not measured.

## Future checks — NOT EXECUTED

### Provider service contract

1. Configure a server-side test key in the disposable environment.
2. Invoke the proposed shared routing/geocoding service through its typed contract.
3. Verify geometry, distance, duration, provider, and provenance fields.
4. Verify `MultiLineString` leg boundaries survive normalization.
5. Force timeout, rate-limit, malformed input, provider error, and unmatched-point responses.
6. Verify explicit unavailable/unknown states and no straight-line fallback.

### Agent-tool boundary

1. Invoke only the registered, case-scoped read-only tool through the normal agent runtime.
2. Verify trusted actor and organization scope are injected by runtime context.
3. Verify model-supplied identity, scope, arbitrary URL, secret, sanction, and adjudication fields are rejected or unavailable.
4. Verify tool timeout, provider failure, and provenance are represented in the structured result and audit trace.

### Tester console and timeline/map presentation

1. Use the approved `/test` contracts and isolated test storage; do not invent a parallel console.
2. Create or load a test run with route and telemetry evidence.
3. Verify map geometry and ordered timeline milestones can be inspected together.
4. Verify unmatched or missing points render as unknown and retain provenance.
5. Verify interrupted and duplicate runs remain isolated and replayable.
6. Capture a screenshot or trace only after visual approval of the proposed layout.

### Hosted and attribution checks

1. Verify the canonical deployed revision and authenticated analyst session.
2. Verify tile/style attribution is visible and compliant.
3. Verify browser network requests contain no unrestricted provider key.
4. Verify quotas, rate limits, and provider errors are observable without exposing secrets.

## Evidence classification

| Evidence | Classification | Supports |
|---|---|---|
| Sanitized six-probe JSON | Authenticated live provider probe | Capability shape and sample Hanoi responses |
| Unit/contract tests | Mocked or isolated software proof | Normalization, authorization, and failure handling |
| Local browser run | Local visual proof | `/test` map/timeline behavior in that revision |
| Hosted authenticated browser run | Hosted/UAT proof | Deployed configuration, auth, attribution, and runtime behavior |

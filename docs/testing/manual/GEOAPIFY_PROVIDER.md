# Geoapify provider manual runbook

Issue #227 scope: provider port, OSRM/Geoapify adapters, narrow caller compatibility, and the bounded capability probe. This runbook records local/fixture evidence separately from live-provider evidence.

## Preconditions and safety

- Use the issue branch and a disposable local environment.
- Keep `GEOAPIFY_API_KEY` server-side. Read an ignored `.env` only inside the probe script; never print the value, full environment, request URL, raw response, headers, or provider exception.
- Use public Hanoi coordinates only. The live probe is opt-in, sequential, capped at six requests, timeout 10 seconds, and has no retries or paid/synthetic invalid-key requests. Planning assumptions are at most 5 requests/second and 3,000 credits/day; the account plan is unverified.
- Evidence labels must say `local/fixture`, `live blocked`, `database`, or `hosted authenticated`. A fixture or health check cannot be presented as hosted acceptance.

## Automated checks

Run the focused provider tests, then Ruff and the repository check script from the issue branch. Record exact commands and counts in the PR evidence. Failure cases must use deterministic fixture transports: malformed JSON, HTTP 401/403/429/503, timeout, unsupported profile/traffic option, impossible swapped Hanoi coordinates, non-finite/out-of-range coordinates, and malformed geometry.

Expected behavior:

- Valid OSRM behavior remains compatible with existing tests and consumers.
- Geoapify requests send waypoints as `lat,lon` while the public port accepts `lon,lat`.
- A typed adapter failure becomes `None` only at the legacy compatibility seam.
- `MultiLineString` legs remain disjoint. Invalid vertices split runs; dropping an invalid point must never create a connector.
- No provider failure creates straight-line or waypoint geometry.
- Secret-bearing URL, header, body, exception, or log content is absent from captured output.

## Six bounded live capabilities

With explicit operator opt-in and a valid server-side key, run the existing six-capability probe against public Hanoi examples: geocoding, reverse geocoding, routing, map matching, map style, and MCP discovery. Keep requests sequential, no more than six total, and sanitize output to the allowlisted summary shape used by [`capabilities-2026-10-08.json`](../artifacts/geoapify/capabilities-2026-10-08.json). Redact style URLs and all error/provider response content. A DNS/network failure should be recorded as `live blocked`; do not retry or infer capability success.

## Manual review

1. Inspect the sanitized artifact and confirm it contains no key, query-string credential, raw URL, raw header, response body, exception text, or MCP content.
2. Confirm the provider selector defaults to OSRM and Geoapify is explicit server-side configuration.
3. Exercise a valid route, a disjoint `MultiLineString`, and malformed vertices through fixtures; verify gaps remain visible and no connector is added.
4. Exercise invalid coordinate order/ranges and each deterministic provider failure; verify the caller receives the compatibility `None` result and no fabricated route.
5. Confirm browser bundles and API responses contain no Geoapify key. Browser/authenticated hosted proof is outside this local runbook and remains pending.

## Observed verification — 2026-10-09

| Check | Observed result | Proof class |
|---|---|---|
| `bash scripts/check.sh` | Ruff, formatting and mypy passed; 805 unit tests passed (10 existing warnings). | Local/fixture |
| `.venv/bin/python -m pytest tests/integration/api/test_simulation_api.py tests/integration/services/test_routing_provider_contract.py -q` | 12 passed; one existing deprecation warning. | Local ASGI/API and provider transport fixtures |
| Existing map layer/timeline helper suites | 2 files, 9 tests passed through the installed Vitest CLI. No frontend source changes. | Local/fixture |
| Focused probe suite | 99 passed; malformed geometry/style/MCP, portable credentials, exception redaction and failing live exit codes covered. | Local/fixture; included in the unit total |
| Six bounded CLI capabilities | All six HTTP 200; style v8/111 layers, MCP discovery 11 tools, matching retains one unmatched point. | [Live provider summary](../artifacts/geoapify/live-2026-10-09.json) |
| Runtime motorcycle adapter | Both free_flow and approximated returned valid disjoint-capable geometry; estimates remain advisory. | [Live runtime summary](../artifacts/geoapify/routing-motorcycle-2026-10-09.json) |
| Failure console | Six deterministic denied/malformed/timeout/unavailable outcomes; no synthetic invalid-key requests. | [Offline fixture summary](../artifacts/geoapify/failures-2026-10-09.json) |

The implementation worker initially lacked Git/network permissions. The conductor preserved its source, completed publication checks, and reran the live console from the authorized host. The unchanged baseline also had two mypy fault-assignment errors; a single union annotation fixed the static gate without changing behavior. A legacy API test assumed flattened mock legs; the corrected assertion verifies two disjoint legs.

Rerun from the repository root with an ignored credential file (or an existing server environment variable):

```bash
.venv/bin/python scripts/probe_geoapify.py --live --env-file .env --output docs/testing/artifacts/geoapify/live-2026-10-09.json
.venv/bin/python scripts/probe_geoapify.py --offline-failures --output docs/testing/artifacts/geoapify/failures-2026-10-09.json
```

The live CLI exits nonzero on any failed capability. Each JSON artifact records the implementation source revision; raw provider responses and credentials are omitted. Do not treat a successful fixture failure console as live-provider success.

## Evidence limits

No case-storage migration, Geoapify map/UI rollout, database acceptance, authenticated hosted proof, account-plan entitlement, observed traffic truth, national coverage, or production readiness is claimed. MapLibre and the stored in-app timeline remain; weather stays on Open-Meteo. CI/review acceptance belongs to the issue-linked PR.

# Cockpit manual checks

Use the exact revision and a disposable seeded API/database. Point the webapp at that API; use its own available port. Never reuse or stop another developer's server.

1. Select a queue case by ID. Compare driver, trip, route and telemetry fields with `GET /api/v1/cases/{id}`; unavailable evidence must remain explicit.
2. Seek to a recorded timestamp and compare coordinates/speed. Seek between fixes, replay, then pan/zoom; recorded observations and estimates must remain distinct, and replay must retain the camera.
3. Select a dropout case. Confirm last-known position, unavailable speed and disconnected measured trail; do not accept an invented road or future GPS fix.
4. Navigate with keyboard and at 375 px. Replay/range controls must remain usable; passive checkpoint marks add no controls or tab stops.
5. Try an unauthorized identity and an unavailable API. Confirm authorization/error states without fabricated case data.
6. Claim/release a disposable case. Reviewer actions require explicit input; AI text or traffic claims alone must not dismiss or sanction a driver.

Record actual results and screenshots separately from expected outcomes. Known product mismatches belong in bug issues (#61/#73 as applicable), not silently changed test expectations. The [archived POC v2 runbook](../archive/POC_V2_LEGACY_MANUAL.md) is historical only.

## Request evidence recovery

Use an analyst-owned, nonterminal disposable case. Record the revision and whether the API is a local fault-injection fixture or a real authenticated environment.

1. Open `/workplace`, select **Complete**, enter a rationale of at least ten characters, and choose **Request evidence**. Repeat through any review-request shortcut. Confirm a successful response ends saving and clears the rationale.
2. Delay the action POST beyond 15 seconds. Confirm saving ends, a localized timeout alert appears, and the rationale remains. Check the case's action history before choosing **Retry** because the server may have committed before the response was lost. Confirm retry submits the original rationale once.
3. Return HTTP 404, 409, or 500 for the POST. Confirm the error is visible and saving ends. For 409, refresh ownership; retry must remain disabled if another analyst owns the case.
4. Let the POST succeed but stall subsequent queue/detail GETs. Confirm saving still ends immediately and no mutation retry appears.
5. Fail a request, switch cases, then return. Confirm its retry does not appear on the other case or survive reselection. Resolve an old delayed response and confirm it cannot overwrite the current case or hide a timeout.
6. Double-click submit while pending. Confirm the network panel shows one POST. Check English and Vietnamese timeout/retry labels.

These are expected manual outcomes; automated Vitest tests use mocked HTTP transport and do not establish hosted authentication proof.

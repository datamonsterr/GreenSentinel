# Issue 61 manual GIS verification

Use a migrated disposable `issue61_*` database and the explicit local API URL. Start with `scripts/test_gis_persisted.sh`; retain its report and measurement attachments. Local test authentication does not verify the hosted identity provider.

1. Open `/workplace`, select the canonical case, and compare origin, pickup, destination and both expected route legs with `GET /api/v1/cases/{id}`. Expected routes and orange observed GPS must remain distinct.
2. Seek to an exact recorded GPS timestamp. Compare coordinates and speed with the API; seek between fixes and confirm estimates are labeled. Pan/zoom manually and replay; the camera must remain stable during the same session and equivalent data updates. Reload and reselect the case to confirm routes/GPS are restored from the same API; a full reload starts a new replay session.
3. Select the seeded GPS-unavailable case. Seek into its recorded gap; retain the last known position, show unavailable speed, and verify the orange trail does not bridge the interval. The red time band must align with source timestamps.
4. Tab through the native replay/range controls. Gap descriptions and checkpoint ticks must introduce no extra keyboard stops. The range must expose its persistent gap explanation and remain draggable.
5. Select the no-GPS case. GPS and traffic absence must be explicit; no driver/origin or speed is invented. Known pickup/destination and cached routes remain visible.
6. Select the missing-route-leg case. Keep the available route; label the missing leg and verify no fallback line or congestion claim appears.
7. Repeat at 375 px and desktop width, including 200% desktop layout zoom and reduced motion. Vertical scrolling at 200% is expected. Check readable status text, unobstructed controls, and no horizontal overflow.
8. Compare cancelled and completed backend cases. Cancelled/unknown trips must not acquire inferred completion or fabricated arrival. Any pickup milestone must have a recorded arrival; completed milestones must use recorded lifecycle values, never penultimate sample guesses.

For hosted review, repeat on the exact deployed PR revision with real analyst authentication and record environment/revision/case IDs/screenshots separately. Local tests and preview workflow success must not be relabeled as hosted acceptance.


## Observed local execution — 2026-10-02

Steps 1–7 were exercised through the real migrated database/API and browser, including native pointer and keyboard events, pan/wheel zoom, 375 px layout, reduced motion, page reload and reachable controls at 200% desktop layout zoom. Step 8 was compared through the SQL-backed case service against persisted cancelled/completed lifecycle rows. Screenshots, browser logs and source comparisons are linked in [the verification audit](ISSUE_61_AUDIT.md). This records agent-executed local browser checks; authenticated hosted and human reviewer acceptance remain separate.

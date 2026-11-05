# ADR-027: Ghost-Trip Lifecycle Fallback Rule (ERR-04)

## Status
Accepted

## Context
`_calibrated_heuristic` step 6 only matched "ảo"/"ghost" in `cancellation_reason`, so ERR-04 bundles with a completed lifecycle, `arrived_at=None`, `started_at=None`, no cancellation, and normal geometry fell through to `no_violation`. Honest completed trips always carry arrival timestamps; cancelled trips never reach step 6.

## Decision
Fire ERR-04 (confidence 0.91, P1, tier 1, score 90) on the conjunction:

1. `lifecycle_state == "completed"`, AND
2. `arrived_at`/`started_at` keys present **and** both `None` (known never-arrived), AND
3. passenger completion-denial text (case-insensitive substring over an inline pattern list derived from keyword + `err04_phantom.yaml` customer paraphrases; bare/affirmative-risk substrings excluded) in any of `customer_reports` / `trip_conversation` / `driver_reason_and_agent_conversation`.

Fail-closed: missing arrival keys = unknown, arrived trips, missing denial, or cancelled lifecycle never fire via this rule. ERR-05 keeps precedence (step 2 runs first). Output is advisory only: P1 analyst review, never auto-action; `forensic_brief` cites Điều 15.1.

## Rationale & Alternatives Considered
| Option | Pros | Cons | Decision |
|---|---|---|---|
| Lifecycle + never-arrived + denial conjunction | High precision; honest arrivals excluded structurally | Misses silent (no-denial) ghosts | Selected |
| Denial text alone | Higher recall | False positives on waiting complaints | Rejected |
| Arrival absence alone | Simple | Flags silent/technical non-pickups | Rejected |

## Consequences
- Data flows: `run_10k.py::bundle_to_input` and `telemetry_queue_worker::assess` pass `arrived_at`/`started_at` through only when the source key is present (unknown-vs-None preserved for enum-blind mode); `model_input_projection` allowlists both keys.
- Topology/state/graph/tools/security: unchanged (FastAPI → LangGraph → Jev heuristic path untouched; no new tools, state fields, or key handling).
- Evidence boundary: generator metadata `trip.ghost_no_pickup` must NEVER be consumed by the detector; `audit_bundle` projection stays clean.
- 10k rerun: `python scripts/benchmark/run_10k.py --in data/benchmark-10k/v1/trips.jsonl --out data/benchmark-10k/v1/predictions.jsonl` (orchestrator runs; do NOT rebuild the corpus here).

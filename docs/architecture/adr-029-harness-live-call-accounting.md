# ADR-029: Record-derived live-call accounting in the research harness

## Status
Accepted for PR #527; references [issue #525](https://github.com/AI20K-Build-Phase-Cohort-4/GreenSentinel/issues/525) and [epic #494](https://github.com/AI20K-Build-Phase-Cohort-4/GreenSentinel/issues/494).

## Context
Soft guardrails can cap a successful provider response or a heuristic fallback. Their metadata cannot prove that a request bypassed the provider. Excluding such records hides live failures. Accepting an arbitrary caller-supplied denominator also allows a failed experiment to appear valid.

## Decision
Only the explicit `guardrail_short_circuit` model sentinel marks a prediction as having no live call. All other live prediction records contribute one call to the denominator. Heuristic fallbacks and missing or malformed model attribution count as failures. The metrics suite derives the denominator from records and shares it with cost metrics. A zero-call live experiment is invalid.

**Topology and boundaries:** The research CLI invokes variant adapters, which use the existing assessment service. Accounting stays in the benchmark harness; provider transport remains in `src/services/`. API handlers, shared schemas, and LangGraph nodes keep their existing responsibilities.

**State and lifecycle:** Worker records retain `model_used`, `fallback_reason`, `http_status`, and guardrail metadata. The worker normalizes model attribution before recording results. No LangGraph state fields, nodes, or conditional edges change.

**Contracts and data flow:** Input bundles pass through the selected variant, then normalized predictions are written to JSONL. The evaluator computes calls, failures, causes, costs, and validity from those records before writing `metrics.json`. Early abort still stops after 20 consecutive HTTP 402/429 failures. Paired comparator checks remain downstream. The CLI does not emit streamed tokens.

**Security and boundaries:** Unit tests inject provider outcomes and make no provider calls. Credential handling and service rate controls remain at their existing boundary. This accounting change does not authorize external export or live corpus execution.

## Rationale & Alternatives Considered

| Option | Benefit | Risk | Decision |
|---|---|---|---|
| Explicit sentinel and record-derived denominator | Auditable agreement between worker and evaluator | Depends on truthful variant attribution | Selected |
| Exclude all guardrail metadata | Simple flag check | Hides provider calls and fallbacks after soft guards | Rejected |
| Trust caller-supplied positive call count | Accepts external counters | Can dilute failures and diverge from persisted evidence | Rejected |

## Consequences
Tests cover soft-guardrail successes and failures, malformed attribution, arbitrary denominators, true short circuits, and zero-call invalidity. Historical runs require re-evaluation before model-quality claims. Missing matplotlib raises its dependency error; the plotting path never fabricates a placeholder chart or empty PNG.

Implementation: [metrics](../../scripts/benchmark/experiments/metrics.py), [worker](../../scripts/benchmark/experiments/run_experiment.py). Evidence: [integrity review](../data/HARNESS_INTEGRITY_REVIEW.md), [regressions](../../tests/unit/benchmark/test_harness_metric_integrity.py).

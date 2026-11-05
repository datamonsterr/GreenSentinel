# ADR-025: Benchmark evidence boundaries and reproducible comparisons

## Status

Accepted for local implementation under issue #259. Hosted acceptance remains separate.

## Context

The original benchmark uses reported speed as a fake-GPS signal, blocks entire windows for isolated offline pings, and omits dialogue and route context from its fallback input. Generator-only driver provenance can reach the live decision request. These mechanisms require regression proof before comparing detector scores.

## Decision

- Recursively remove evaluation labels and generator-only profile provenance at the actual model request boundary. Preserve operational evidence and the original artifact.
- Keep point-level technical failures visible. At the window boundary, allow a short offline interval only when timestamps and recovery bound it to at most 30 seconds. Longer gaps, unknown duration, invalid positions, crashes, and explicit incidents retain blocking outcomes.
- Derive speed from timestamped positions. Reported speed alone cannot establish fake GPS. Mock-provider observations remain advisory evidence, without fabricated tamper reason codes.
- Attribute dialogue to its speaker. Ghost-trip review requires completed lifecycle, measured absence of pickup arrival, and explicit passenger denial. Missing facts and driver-only or negated statements cannot supply those facts.
- Treat DAVI and tortuosity as geometry measurements. Route deviation requires an independently identified planned-route reference; neither a simulation label nor a sampled class-dependent tortuosity is a route reference.
- Preserve v1 generation and its immutable artifacts. Compare changed detectors on the same v1 inputs, then measure an explicitly versioned generator profile separately. Runtime latency is excluded from semantic prediction identity.
- Keep corpus profiles distinct from batch names. The default builder uses frozen v1 priors and random draws; opt-in `feedback` uses upstream dialogue/ratings priors. The evidence profile writes under `profiles/evidence-v2`, preserving the recorded feedback batch under `v2` and excluding profiles from named-batch merges.
- Further upstream G1/G2 variants use the explicit `g1g2` profile and retain their recorded v3 namespace. Additive scenario helpers must not change earlier profiles' random draws or artifact schemas.
- Keep fraud ground truth separate from evidence sufficiency. A technically unjudgeable fraud fixture remains fraud ground truth and carries a separate sufficiency outcome. Report both, without relabeling to improve accuracy.
- Keep future dataset splits disjoint by driver. A driver's analytical history may include only earlier operational records, never future trips or evaluation labels.
- Decouple ground truth from detector-visible enums (issue #281). Cancellation reason/actor are operational facts drawn from overlapping pools shared by every cancelled class; `label` + `label_provenance` are the only ground-truth carriers. A committed classifier fit on `(status, actor, reason)` must stay under 0.5 recall on cancelled trips.
- Keep locale and fare honest (issue #281). Telemetry/pickup/dropoff bboxes must agree with the declared city and its provenance; cancelled trips carry no completed fare, and completed fares respect a realistic per-km band. Dialogue banks are paraphrased for surface uniqueness and partitioned so train/validation/test never share templates.

## Rationale and alternatives

| Option | Benefit | Limitation | Decision |
|---|---|---|---|
| Shared operational evidence with explicit unknown states | Auditable production and benchmark inputs | Unsupported historical fixtures may remain unjudgeable | Selected |
| Read simulation labels or class-dependent route metadata | Improves apparent benchmark scores | Leaks ground truth and supplies unavailable evidence | Rejected |
| Replace fraud labels with abstention labels | Simplifies one score | Hides the difference between truth and observability | Rejected |

## Consequences

This change preserves analyst authority and adds no sanction action. Constant heuristic confidence remains `uncalibrated_model_confidence`. Synthetic payment prevalence, simulated gridlock measurements, and approximate city fixtures must retain their source limitations. Scratch migration proof does not establish Railway data integrity or hosted acceptance.

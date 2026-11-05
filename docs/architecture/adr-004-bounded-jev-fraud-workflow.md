# ADR-004: Bounded Jev Fraud Workflow

## Status

Proposed

## Context

The MVP requires a LangGraph forensic brief and confidence score. The requested PoC extends the original synthetic dossier flow: telemetry must pass through real preprocessing and a Jev model before a suspected-fraud case reaches an analyst. The workflow must remain deterministic enough for TDD and must never authorize a penalty.

The authoritative PRD taxonomy defines `ERR-02` as route deviation and driver-induced cancellation and `ERR-05` as technological manipulation or fake GPS. A single pickup episode does not provide enough evidence to establish `ERR-01`, `ERR-03`, or `ERR-04`. App crashes and network loss are technical guardrails, not fraud classes.

## Decision

Use Python, FastAPI, Pydantic V2, LangChain, and a bounded LangGraph workflow. Call Jev through an OpenRouter-compatible provider adapter. Request strict structured output and validate it with Pydantic before persistence.

The graph contains deterministic stages: load frozen evidence, validate minimum evidence, classify with Jev, validate output, retrieve cited policy, produce a neutral two-to-three-sentence brief, and persist the assessment. It has no open-ended ReAct loop and no adjudication or sanction tool.

The PoC detector supports `ERR-02`, `ERR-05`, `no_violation`, and `insufficient_evidence`. It may preserve unsupported candidate classes in raw output, but it must route them to insufficient evidence instead of asserting unsupported fraud.

Store Jev's returned score with `score_semantics`. Display it as **model confidence** unless provider documentation and held-out calibration prove it is a probability. Compute accuracy, precision, recall, F1, and calibration only over a labeled evaluation run. Never use the word accuracy for a single case.

Priority uses deterministic policy rules and a versioned score. A recommended PoC rule is:

1. Set `P0` only for supported `ERR-02` or `ERR-05` cases with confidence at least `0.85`, evidence quality at least `0.80`, and no blocking technical guardrail.
2. Set `P1` for supported cases with confidence at least `0.65` and evidence quality at least `0.60`.
3. Set `P2` for all other cases, including technical ambiguity and insufficient evidence.
4. Within a tier, rank by `round(1000 × confidence) + min(case_age_minutes, 180)`, then creation time and case ID.

These thresholds are demo configuration, not an approved enforcement policy. Priority orders analyst work and never determines guilt or outcome.

## Rationale and alternatives considered

| Option | Benefits | Costs | Decision |
|---|---|---|---|
| Python + bounded LangGraph + Jev | Fits existing code and preferred stack; typed states; deterministic edges; easy unit tests | Two application languages with Next.js | Selected |
| TypeScript AI SDK for all model work | One language and strong streaming primitives | Conflicts with current FastAPI/LangGraph requirement and duplicates Python analytics | Rejected for PoC |
| Free-form multi-agent workflow | Flexible investigation | Unbounded latency, harder tests, broader permissions, weaker reproducibility | Rejected |
| Deterministic rules only | Cheap and fully explainable | Does not satisfy Jev/forensic synthesis requirement; weak text synthesis | Retained as fallback and priority engine |
| Jev chooses priority and action | Simple prompt | Opaque, unstable, and incompatible with human-control invariant | Rejected |

## Required architecture questions

| Question | Answer |
|---|---|
| System topology | Worker loads a committed snapshot, calls Jev through OpenRouter, traces redacted metadata to LangSmith, and persists validated output. |
| State and graph lifecycle | Typed state carries case, snapshot, feature set, result, brief, errors, and attempt count. Invalid structure retries once; failures become explicit persisted states. |
| Tool contracts | Route, policy, assessment, and persistence tools use Pydantic input/output. Tools return explicit unavailable/error states and have timeouts. |
| Data flow | Telemetry becomes versioned features; Jev receives only allowed evidence; output references supplied evidence IDs; Pydantic validates; priority rules execute afterward. |
| Trade-offs | Bounded orchestration gives up autonomous exploration for predictable latency, safety, and testability. |
| Security boundaries | Prompts exclude unnecessary PII. Model and worker credentials remain server-side. Graph tools cannot write adjudications or sanctions. LangSmith payloads are redacted. |

## Consequences

Provider failures, invalid JSON, and missing evidence stay visible and retryable. They cannot silently become clean cases or sanctions. Versioned prompts, schemas, preprocessing, model IDs, and traces make assessments reproducible.

The first evaluation can measure performance on synthetic A/B/C plus fake-GPS and jitter counterexamples, but those results do not establish real-world accuracy. Real deployment requires labeled historical data, calibration, bias analysis, and approved thresholds.

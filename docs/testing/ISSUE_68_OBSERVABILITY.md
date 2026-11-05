# Issue #68: Agent Observability

## Runtime behavior

The existing analyst chat endpoint and legacy cockpit agent remain the active path. Each completed agent run records a bounded operational sample and can emit an opt-in LangSmith trace. Tool calls and human decisions are traced as child activities; saved decisions link to an agent turn only when the submitted turn belongs to the same case and organization.

LangSmith tracing is enabled only when `LANGSMITH_TRACING=true` (or the legacy `LANGCHAIN_TRACING_V2=true`) and an API key is configured. Trace inputs and outputs are hidden, and only allowlisted correlation, model, prompt-version, environment, and workflow metadata are sent. Trace failures are logged and do not change the agent or adjudication result.

The analyst analytics view reads `/api/v1/observability/summary`. Access is restricted to analyst, senior analyst, and admin roles. The summary contains aggregate metrics and version information only; it does not expose case content, driver identifiers, trace IDs, or run IDs.

## Provider choice

Keep the existing LangSmith integration for this delivery rather than introducing Langfuse self-hosting. This reuses the provider already present in the PR #40 baseline and avoids adding a separately operated database, storage, upgrades, and access-control surface before staging traffic and retention needs are measured. This is a provisional engineering trade-off, not a measured cost comparison; the issue's operating-cost evidence remains pending.

## Metrics and limitations

- Run count, errors, timeouts, latency p50/p95, tool success, token usage, grounding/guardrail samples, and estimated model cost are shown with their sample counts.
- Estimated cost is unavailable unless both `GEMINI_INPUT_COST_USD_PER_MILLION` and `GEMINI_OUTPUT_COST_USD_PER_MILLION` are configured with finite, non-negative rates. It is an estimate from Gemini token counts, not provider billing.
- Benchmark data links to the checked-in dataset and result artifact. Their current content hashes are shown. Existing artifacts that do not record dataset, model, or prompt versions are explicitly identified as missing that provenance.
- Runtime metrics are process-local, bounded to the latest 1000 runs, and reset on process restart. They are not durable or aggregated across multiple workers; the dashboard must not be treated as a production SLO or billing source.
- LangSmith retention and access remain governed by the configured provider account/project. Do not enable tracing without reviewing that account's access and retention settings.

## Verification status

Automated tests cover metric aggregation, cost configuration validation, API authentication/role restrictions, and rendering of observability sample counts. A deployed staging run, external LangSmith access/retention review, and verified provider cost comparison are operational checks and must be recorded separately before claiming those checks complete.

# ADR-006: Shared Use Cases for API and Agent Tools

## Status

Proposed

## Context

FastAPI routes and LangChain tools can both retrieve case evidence, routes, policy, and analysis results. Implementing each operation independently creates duplicated authorization, validation, idempotency, database, and error-handling logic. Exposing every HTTP command as an LLM tool also gives the model capabilities it does not need, including possible access to adjudication or sanctions.

## Decision

Place each business operation in one typed application service under `src/services/`. FastAPI routes, deterministic LangGraph nodes, and model-selectable `@tool` functions are thin adapters around the same service method.

Keep separate registries for HTTP routes and agent tools. Registration is explicit. HTTP availability does not imply tool availability.

Use three adapter rules:

1. FastAPI owns authentication, request parsing, HTTP status mapping, rate limits, and human command idempotency.
2. Deterministic graph nodes call application services directly. They do not wrap mandatory pipeline stages as tools.
3. `@tool` adapters exist only for safe operations the model may choose to invoke. Initial tools are read-only evidence, route, and published-policy retrieval. They receive identity, organization, permissions, snapshot, and trace context from trusted runtime injection, not model-generated arguments.

Never register analyst adjudication, fine, suspension, role management, arbitrary SQL, secret access, raw object-store access, or unrestricted HTTP fetch as an agent tool. Only an authenticated human-facing API command may create `adjudications` and `sanctions`.

## Rationale and alternatives considered

| Option | Benefits | Costs | Decision |
|---|---|---|---|
| Shared application services with thin adapters | One rule implementation; consistent errors; independently evolvable API/tool schemas | Requires disciplined dependency direction and mapping code | Selected |
| Tools call HTTP API | Reuses HTTP surface | Adds network hop, service credentials, HTTP error translation, and circular deployment dependency | Rejected for same-process graph |
| HTTP routes call tools | One callable function | Couples stable public API to model-facing descriptions and exception contracts | Rejected |
| Separate route and tool implementations | Simple initially | Duplicated security/business rules drift quickly | Rejected |
| Expose OpenAPI operations as tools automatically | Minimal registration work | Grants excessive capability and unstable tool surface | Rejected |

## Required architecture questions

| Question | Answer |
|---|---|
| System topology | Browser calls FastAPI; FastAPI and LangGraph adapters call shared application services; services call repository/provider ports. |
| State and graph lifecycle | Graph state carries frozen snapshot and trusted runtime context. Deterministic nodes call services; optional model choices use small registered tool set. |
| Tool contracts | Every tool has strict Pydantic input/output, explicit side-effect classification, timeout, owner, and error union. Authority fields are runtime-injected. |
| Data flow | Adapter validates transport; service enforces use-case invariants; port calls infrastructure; result maps back to HTTP or graph state. |
| Trade-offs | Mapping adds small boilerplate but prevents duplicated authorization and business logic. Separate registries reduce convenience while limiting capability. |
| Security boundaries | Model cannot choose identity, scope, role, snapshot, database query, or sanction. Worker database role cannot write adjudications or sanctions. |

## Consequences

Tests target application services once, then add small adapter contract tests. Route and tool names can differ while using the same canonical commands and results. Model tool descriptions can evolve without breaking public HTTP contracts.

Code review must reject business rules in route handlers and `@tool` functions. Tool-registry tests must assert forbidden capabilities are absent. Deployment can place API and worker in separate processes because both depend on the same versioned Python package.

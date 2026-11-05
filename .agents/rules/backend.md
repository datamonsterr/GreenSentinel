---
description: "Backend standards for FastAPI, LangGraph orchestrator, Pydantic V2 schemas, and testing"
activation: model_decision
---

# Backend Engineering Guidelines

## 1. FastAPI Route Architecture
- All API routes reside in `src/api/routes.py`.
- Use async route handlers (`async def`) for I/O and agent invocations.
- Enforce request validation and response models via Pydantic V2 (`src/models/schemas.py`).
- Implement `/health` endpoint for readiness/liveness checks.
- Support SSE streaming for real-time agent token generation via `StreamingResponse`.

## 2. LangGraph Orchestration
- State schemas defined using `TypedDict` in `src/agents/state.py`.
- Use `Annotated[list, add_messages]` for message history.
- Decorate custom tools with `@tool` from `langchain_core.tools`.
- Isolate node logic in `src/agents/nodes/` and tool definitions in `src/agents/tools/`.
- Compile the graph in `src/agents/graph.py` with deterministic conditional edges checking `tool_calls`.

## 3. Services & External Integrations
- Centralize model provider clients in `src/services/llm.py`.
- Read configuration via `src/config.py` using Pydantic `BaseSettings`.
- Do not make external HTTP requests without explicit timeouts.
- **Forensic Brief & Case Policy Invariant**: `CaseService.get_forensic_brief` (`/api/v1/cases/{id}/forensic-brief`, `get_forensic_brief` tool) must only report measured telemetry, trip, and guardrail abnormalities without fabricating metrics or making a judgment/verdict. `CaseService.get_case_policy` (`/api/v1/cases/{id}/policy`, `get_case_policy` tool) resolves case-specific policy clauses, guardrail exemptions, and precedent rules.

## 4. Testing & Verification
- Follow `docs/testing/README.md` for suite placement and stable commands.
- Isolate units in `tests/unit/`; put API/service seams in `tests/integration/` and workflows in `tests/e2e/backend/`.
- Use `.venv/bin/python`, TDD and fresh behavioral proof. Required integration setup must fail clearly; live providers are opt-in.

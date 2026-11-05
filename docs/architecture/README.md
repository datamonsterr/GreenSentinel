# Architecture Documentation Guide & Specifications

> **MANDATORY RULE**: Any AI agent or developer updating documents in `docs/architecture/` **MUST** read this `README.md` first before creating or modifying entries.

## 1. Purpose & Scope
The architecture directory maintains the system design, component boundaries, data flow diagrams, and Architecture Decision Records (ADRs) for Demo Day deliverable #3.

## 2. Filename Conventions
- Primary system architecture specification: `ARCHITECTURE.md` (maintained in this folder).
- Discrete Architecture Decision Records: `adr-NNN-<kebab-case-topic>.md` (e.g., `adr-001-langgraph-orchestrator.md`).

## 3. Required Questions to Answer
Every architecture update or ADR **MUST** answer these 6 architectural questions:
1. **System Topology**: How do client, backend (FastAPI), agent (LangGraph), and external services interact?
2. **State & Graph Lifecycle**: What is the TypedDict state schema, what nodes exist, and how are conditional edges evaluated?
3. **Tool Contracts**: What tools are exposed to the agent, how are inputs validated, and how are execution failures trapped?
4. **Data Flows**: What is the step-by-step sequence of requests from client ingestion to final token streaming?
5. **Architectural Trade-offs (ADRs)**: What decision was made, what alternatives were considered, and why was this choice preferred?
6. **Security & Boundary Protection**: How are API keys, input sanitization, and rate limits enforced?

## 4. Standard ADR Template (for adr-*.md)

```markdown
# ADR-NNN: [Title of Decision]

## Status
[Proposed | Accepted | Superseded by ADR-XXX]

## Context
[What problem or architectural requirement are we addressing?]

## Decision
[What choice did we make?]

## Rationale & Alternatives Considered
| Option | Pros | Cons | Decision |
|---|---|---|---|
| [Option A] | [Pros] | [Cons] | Selected |
| [Option B] | [Pros] | [Cons] | Rejected |

## Consequences
[Impact on performance, maintainability, dependencies, and testing]
```

## 5. Required Skills
- `write-a-doc`: Orchestrates document drafting and template compliance.
- `ai-agent-guide`: Provides LangGraph and FastAPI architectural patterns.
- `rtk`: Ensures diagrams and tables remain dense, accurate, and fluff-free.

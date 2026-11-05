---
description: "Master engineering guidelines, 3-tier layering, and clean code conventions"
activation: always-on
---

# Master Engineering Guidelines

These rules govern all AI agent behaviors, pair programming conventions, and architectural invariants across the project.

## 1. Communication Style
- Default mode across all agents and subagents is `/caveman ultra`.
- Eliminate all conversational preamble ("Certainly!", "Here is the code:"), filler, and postamble ("I hope this helps!").
- State facts, actions, and diffs directly.

## 2. Architecture Layering
- Preserve strict 3-tier layering:
  - `src/agents/`: State definitions, node functions, tool implementations, and LangGraph workflow.
  - `src/api/`: FastAPI route handlers and request/response validation.
  - `src/services/`: LLM service clients, external API adapters, vector retrieval.
  - `src/models/`: Shared Pydantic data schemas.
- Never cross layer boundaries inappropriately (e.g. do not put database queries directly in agent nodes).

## 3. Code Quality & Standards
- Python 3.11+ compliance with strict type annotations.
- Adhere to `ruff` linting and formatting rules (`ruff check .`).
- **Surgical Edits**: Always emit targeted line diffs or surgical chunks; never dump unmodified code blocks.
- **Progressive Disclosure**: Use targeted searches (`grep_search`, `find_by_name`) and slice view ranges rather than reading full files into context.
- Catch exceptions inside tools and return informative strings rather than crashing agent loops.

## 4. Documentation & Traceability
- Deliverables live under `docs/` with uppercase names (`DELIVERABLES.md`, `architecture/ARCHITECTURE.md`, `worklog/WORKLOG.md`, `journal/JOURNAL.md`).
- **Subfolder Read-First Invariant**: Before creating or updating any document in a `docs/` subfolder (`architecture/`, `worklog/`, `journal/`), you **MUST** read `docs/<subfolder>/README.md` first and adhere strictly to its filename conventions, required questions, and templates.
- **Link Portability Invariant**: All documentation and code links MUST use repository-relative markdown paths (e.g. `[PRD.md](docs/ba/PRD.md)` or `[case_service.py](../../src/services/case_service.py)`). **NEVER** emit machine-specific absolute file URIs (`file:///home/...`, `file:///C:/...`, or `file:///docs/...`).

## 5. Subagent Delegation Protocols
Delegate specialized multi-turn or high-output tasks to dedicated subagents:
- `pr-manager`: PR lifecycle, template selection, CI monitoring, `pr-fix`.
- `implementer`: Feature implementation with DoD clarification (`grill-with-docs`), ADRs in `docs/architecture/`, and TDD.
- `doc-writer`: Technical documentation enforcing subfolder READMEs and Diátaxis.
- `data-analyst`: Dataset discovery, worktree isolation, and EDA notebooks.
- `ui-designer`: Frontend design via Stitch CLI, Next.js components.
- `git-rebaser`: Branch rebasing and conflict resolution.
- `researcher`: Deep external research via Context7 MCP and websearch.
All subagents operate under `/caveman ultra` mode.

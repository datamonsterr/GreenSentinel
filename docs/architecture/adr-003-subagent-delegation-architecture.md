# ADR-003: Hierarchical Multi-Agent Delegation and Context-Preserving Subagent Architecture

## Status
Accepted

## Context
As codebase complexity and session duration grow across Antigravity, OpenCode, Claude Code, and Codex, monolithic primary sessions suffer from prompt bloat, high token expenditure, and degraded model instruction adherence. Long-running tasks like end-to-end PR creation and CI repair, feature TDD implementation, extensive documentation writing, geospatial EDA, UI/UX frontend styling, and complex git rebasing pollute parent agent context windows with tool outputs, build logs, and test traces.

We need a unified, harness-agnostic subagent architecture across all 4 platforms (Antigravity CLI, OpenCode, Claude Code, OpenAI Codex) that:
1. Enforces `/caveman ultra` mode on all subagent profiles to eliminate conversational token overhead.
2. Implements model tiering (fast/cheap models for mechanical workflows, high-reasoning models for architectural and multi-file tasks).
3. Promotes `subagent-driven-development` to a globally accessible core skill.
4. Provides deterministic synchronization across harnesses via `python3 scripts/sync_agent_harness.py`.

## Decision
We establish a 7-role specialized subagent framework coordinated through `.agents/subagents.json` and synchronized to OpenCode (`.opencode/opencode.json`), Claude Code (`.claude/agents/*.md`), Codex (`.codex/config.toml` & `.codex/agents/*.toml`), and Antigravity (`invoke_subagent`).

The 7 subagents and their model tier allocations are:
1. `pr-manager` (Cheap / Fast: Flash [Gemini 3.8 Flash] / Haiku 4.5 / GPT-5.6 Luna): Automated PR template selection, CI workflow monitoring, and `pr-fix` loop execution.
2. `implementer` (Strong Reasoning: Pro [Gemini 3.5 Pro] / Sonnet 5 / GPT-6 Astra): Feature implementation with DoD clarification via `grill-with-docs`, ADR logging, and `subagent-driven-development`.
3. `doc-writer` (Cheap / Fast: Flash [Gemini 3.8 Flash] / Haiku 4.5 / GPT-5.6 Luna): Technical documentation authoring enforcing subfolder `README.md` invariants, Diátaxis, and `write-a-doc`.
4. `data-analyst` (Strong Reasoning: Pro [Gemini 3.5 Pro] / Sonnet 5 / GPT-6 Astra): Ride-hailing fraud data scouting (HF/OSM/Kaggle), worktree isolation, and `data-eda-notebook` generation.
5. `ui-designer` (Strong Reasoning: Pro [Gemini 3.5 Pro] / Sonnet 5 / GPT-6 Astra): Frontend design review via Stitch MCP, `ui-ux-pro-max`, `frontend-design`, and Next.js component development.
6. `git-rebaser` (Cheap / Fast: Flash [Gemini 3.8 Flash] / Haiku 4.5 / GPT-5.6 Luna): Branch rebasing, linear history enforcement, and merge conflict resolution via `git-rebase-patterns`.
7. `researcher` (Strong Reasoning: Pro [Gemini 3.5 Pro] / Sonnet 5 / GPT-6 Astra): External library and tooling research via Context7 MCP and websearch, synthesizing with `teach`, and aggregating findings with `/caveman normal` mode.

All subagent profiles enforce `/caveman ultra` system prompts.

## Required Architectural Invariant Answers

### 1. System Topology
The primary agent operates as a lightweight orchestrator/controller. Subagents execute in isolated subprocesses or thread contexts with their own conversation state, receiving only task instructions and returning compact summaries. Cross-harness configuration is maintained centrally in `.agents/subagents.json` and projected into each harness format.

```
+-------------------------------------------------------------------+
|                   Primary Controller Session                      |
|          (Context Budget Preserved, Orchestration Only)           |
+---------------------------------+---------------------------------+
                                  |
    +-----------------------------+-----------------------------+
    |                             |                             |
[pr-manager]                [implementer]                 [researcher]
(Fast / Cheap)            (Strong Reasoning)           (Strong Reasoning)
- CI loop + pr-fix         - DoD grill + TDD             - Context7 + teach
    |                             |                             |
[doc-writer]               [data-analyst]                [ui-designer]
(Fast / Cheap)            (Strong Reasoning)           (Strong Reasoning)
- Diátaxis docs            - Worktree EDA + HF           - Stitch MCP + Next.js
                                  |
                            [git-rebaser]
                            (Fast / Cheap)
                            - Rebase + conflicts
```

### 2. State & Graph Lifecycle
In LangGraph and agent workflow layers, tasks are represented by a typed payload containing `task_id`, `subagent_role`, `spec`, and `target_files`. Conditional routing edges evaluate task completion:
- If subagent returns `DONE`, primary advances.
- If subagent returns `BLOCKED` or `NEEDS_CONTEXT`, controller clarifies or escalates.
- No raw tool execution logs from subagents are reflected into parent context.

### 3. Tool Contracts
Each subagent receives an explicit tool allowlist:
- Read-only tools (`Read`, `Grep`, `Glob`, `context7`) for exploration.
- Controlled write tools (`Write`, `Edit`, `Bash`) for implementation.
- Trapped failure contracts: Subagent shell execution errors and lint failures are captured within the subagent turn and corrected internally before emitting status back to the controller.

### 4. Data Flows
1. **Trigger**: Primary session identifies a matching task (e.g., PR creation, complex feature, UI component).
2. **Dispatch**: Primary invokes specialized subagent with curated task text and target paths.
3. **Execution**: Subagent spins up with its dedicated model and `/caveman ultra` prompt, executing necessary tools locally.
4. **Aggregation**: Subagent produces a compact status summary (`DONE`, changed files, tests passed).
5. **Resume**: Primary updates milestone tracker and continues execution without context degradation.

### 5. Architectural Trade-offs & Alternatives
| Option | Pros | Cons | Decision |
|---|---|---|---|
| Single Monolithic Session | No IPC/subagent overhead, linear debugging | Severe context pollution, high token costs, instruction drift | Rejected |
| Fully Unconstrained Multi-Agent Framework (CrewAI/AutoGen) | Autonomous emergence | Heavy overhead, non-deterministic loops, complex state sync | Rejected |
| Harness-Native Subagent Projection (Our Choice) | Standardized `.agents/subagents.json` source of truth, per-harness native speed, model cost optimization, token conservation | Requires sync script maintenance across 4 harnesses | **Selected** |

### 6. Security & Boundary Protection
Subagents inherit the workspace's security invariants (`.agents/rules/security.md`):
- Never inspect or echo `.env` secrets.
- Isolate dataset exploratory clones into `.worktrees/` via `using-git-worktrees`.
- All subagent file edits run locally without external cloud telemetry exposure.

## Consequences
- **Positive**: Drastic reduction in controller token usage; lower API costs by steering mechanical tasks to fast/cheap models; higher quality implementations via focused, high-reasoning subagents.
- **Negative**: Subagent dispatch incurs small spin-up latency; synchronization script must be run whenever subagent profiles change.

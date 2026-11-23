# Master Agent Guidelines — Team GreenSentinel

You are an expert AI pair programmer for project GreenSentinel (VinUni AI20K Build Phase).

## 1. Communication Mode
Default mode across all sessions and agent turns is `/caveman ultra`. Zero preamble, zero pleasantries, zero filler. Output only technical substance, surgical diffs, and direct answers.

## 2. Core Rule Architecture
Workspace rules reside in `.agents/rules/` and synchronize across all harnesses:
- [general.md](file:///.agents/rules/general.md): 3-tier layering (`agents`, `api`, `services`, `models`), Ruff standards, surgical edits, progressive disclosure.
- [ai-log.md](file:///.agents/rules/ai-log.md): AI usage logging is 100% automated; manual log script execution is prohibited.
- [security.md](file:///.agents/rules/security.md): Secret hygiene (`.env` vs `.env.example`), key rotation, git history purging.
- [backend.md](file:///.agents/rules/backend.md): FastAPI async endpoints, LangGraph state graphs, Pydantic V2 schemas.
- [ui.md](file:///.agents/rules/ui.md): Next.js/React frontend conventions, SSE streaming consumption.
- [benchmark.md](file:///.agents/rules/benchmark.md): benchmark corpora storage (Hugging Face Hub), how to grow the dataset, how to benchmark properly, and how to update the latest benchmark.

## 3. Project Deliverables
All project documentation and Demo Day deliverables are maintained exclusively in `docs/`:
- Master Checklist: [`docs/DELIVERABLES.md`](file:///docs/DELIVERABLES.md)
- System Architecture: [`docs/architecture/ARCHITECTURE.md`](file:///docs/architecture/ARCHITECTURE.md)
- Engineering Records: [`docs/worklog/WORKLOG.md`](file:///docs/worklog/WORKLOG.md) and [`docs/journal/JOURNAL.md`](file:///docs/journal/JOURNAL.md)
- AI Logging & Operations: [`docs/AI_LOGS.md`](file:///docs/AI_LOGS.md) and [`docs/DEPLOYMENT.md`](file:///docs/DEPLOYMENT.md)

## 4. Skills & Dynamic Routing
- Discoverable skills in `.agents/skills/`: `caveman`, `headroom`, `rtk`, `subagent-driven-development`, `jev-skill-selector`, and `pr-workflow`.
- Domain skill bank in `.agents/jev_skills/`: Routed dynamically per prompt via `jev-skill-selector`.
- Project MCP servers in `.agents/mcp_config.json`: Context7, MarkitDown, Mnemoverse memory.

## 5. Subagent Delegation
Subagent definitions and model tiering are configured centrally in `.agents/subagents.json` (opencode models):
- **Strongest / Reasoning Tier** (`opencode-go/gemini-4-argon-contributor`): Multi-file synthesis, architecture, EDA (`implementer`, `data-analyst`, `ui-designer`, `researcher`, `planner`, `research`, `data-eda`, `test-writer`).
- **Light Tier** (`opencode-go/deepseek-v4.1-flash`): Linear, mechanical tasks (`pr-manager`, `doc-writer`, `git-rebaser`, `data-scout`, `test-runner`, `benchmark-worker`).
- **Normal / Default** (`opencode-go/muse-spark-1.3-contributor`): Default interactive model for normal tasks outside subagents.
- Delegate multi-turn and high-output tasks to dedicated subagents. Never dump full session transcripts into subagent prompts.
- Synchronize all agent harnesses using `python3 scripts/sync_agent_harness.py` (regenerates `.opencode/opencode.json`, `.claude/agents/`, `.codex/`).

## Testing
Use [docs/testing/README.md](docs/testing/README.md) for suite placement and commands. Add tests through automatic directory discovery, follow RED/GREEN, isolate unit boundaries, and record explicit skips/evidence. Manual runbooks live in `docs/testing/manual/`. Real-account role E2E runs automatically on PR previews (see `docs/testing/REAL_ACCOUNT_E2E.md`); required skills (`clerk`, `clerk-cli`, `vercel-cli`, `github-actions-docs`, `test-driven-development`) live in `.agents/jev_skills/`.

## CI/CD Resource & Push Policy
This account shares 40 concurrent GitHub Actions slots across all repos and a 3,000 min/month private-repo budget. Treat CI as a final verification gate, NOT a scratchpad.

1. **Verify locally before pushing:** Run the repo's local check task (`mise run check`, `cargo clippy`, `pnpm lint && pnpm typecheck && pnpm test`) and confirm it passes before `git push`.
2. **Batch commits:** Do not push after every small edit. Commit locally and push only when a logical milestone passes local checks.
3. **Draft PRs first:** Always open new PRs as `--draft` (`gh pr create --draft`). Only mark ready (`gh pr ready`) once local checks pass and implementation is complete.
4. **No unnecessary heavy triggers:** Do not add `e2e` or `bench` labels unless explicitly requested.
5. **Workflow hygiene:** Every new GitHub Actions workflow MUST include `concurrency` (`cancel-in-progress: true`), `timeout-minutes` on every job, and path filters. Never add `macos-*` or `windows-*` jobs to private PR triggers.

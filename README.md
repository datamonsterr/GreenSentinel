# AI20K Agent Project — Team P-063 · GreenSentinel

**GreenSentinel** is a system that helps ride-hailing platforms detect fraud earlier, process it more efficiently, and improve over time — via the Workplace (fraud analyst cockpit), the Driver Support Agent, and automatic post-trip fraud detection.

Official repository for VinUni AI20K Build Phase: modular AI Agent architecture, production-ready code foundation, and technical deliverables tracking — covering system design, automated testing, containerized deployment, and Demo Day submissions.

Technical Guidebook & Platform: <https://phoenix.note.transformerlabs.ai/technical-book>

---

## Key Features

- **Decoupled 3-Tier Layering**: Clean separation of concerns with `src/agents/`, `src/api/`, `src/services/`, and `src/models/`.
- **Executable Agent Architecture**: LangGraph cyclic state graph with TypedDict state, nodes, and `@tool` integrations.
- **FastAPI Backend**: Asynchronous endpoints, Pydantic V2 validation, health probes, and SSE streaming.
- **Docker foundation**: Multi-stage backend Dockerfile and local Compose scaffold. Full PoC services and CI remain implementation work tracked in [`docs/DEPLOYMENT.md`](./docs/DEPLOYMENT.md).
- **Railway Infrastructure as Code**: Project resources (backend, Postgres, Redis, benchmark DB) owned by [`.railway/railway.ts`](./.railway/railway.ts); CI redeploys persistent envs via saved plans (`config plan --out` + `apply --plan`) with drift and test-auth guards.
- **Comprehensive Deliverables**: All 10 Demo Day deliverables consolidated under [`docs/`](./docs/).
- **Automated AI Usage Logging**: Active hooks for Antigravity CLI, OpenCode, Claude Code, OpenAI Codex, Cursor, and Gemini CLI, with automatic submissions during `git push`.
- **Project-Wise MCP Servers**: Integrated Context7, MarkitDown, and Mnemoverse online memory.
- **Standardized Agent Skills**: Packaged skills adhering to the open agent format (`caveman`, `rtk`, `headroom`, `mnemoverse`, `security`, `ai-agent-guide`, `config-agent-harness`).

---

## Classification Model

The core violation detection engine uses the **R3D Stacker**, an ensemble combining clean LightGBM kinematics and 1D-CNN trajectory sequences with a LightGBM meta-learner (0.8680 test macro-F1, 2.7% false positive rate, 35ms latency), backed by `inception/mercury-decide:free` for advisory narrative adjudication.
- **System Overview & Architecture**: [`docs/CLASSIFICATION_MODEL.md`](./docs/CLASSIFICATION_MODEL.md)
- **Experimental Staircase & AutoResearch Loop**: [`docs/data/AUTORESEARCH.md`](./docs/data/AUTORESEARCH.md)
- **Chronological Benchmark Suite**: [`docs/data/BENCHMARK.md`](./docs/data/BENCHMARK.md)
- **Current Dataset Card (`releases_v2.1`)**: [`docs/data/DATASET.md`](./docs/data/DATASET.md)

---

## Requirements

- **Tool & Environment Manager**: [mise-en-place](https://mise.jdx.dev/) (`mise`)
- **Python Manager**: [uv](https://github.com/astral-sh/uv) (automatically provisioned via mise)
- **Token Reducer**: [rtk](https://github.com/rtk-ai/rtk) (automatically provisioned via mise)
- **Python**: 3.11+ (CPython 3.11 managed in `.venv`)
- **Git**: 2.30+
- **Docker**: (Optional) for containerized local execution
- **Node.js**: 20.9+ (required by Next.js 16; also used by MCP servers and skill tooling)

---

## Getting Started

### 1. Setup Environment (via mise & uv)

```bash
# Install tools (Python 3.11, uv, rtk) and dependencies
mise install
mise run setup    # or: bash scripts/setup.sh
```

### 2. Environment Configuration

```bash
cp .env.example .env
```

Edit `.env` and provide your credentials:
- `OPENROUTER_API_KEY`: Your server-side OpenRouter key for Jev and policy-chat model calls.
- `DATABASE_URL`: PostgreSQL runtime connection; use Supabase in hosted environments.
- `LANGSMITH_API_KEY`: LangSmith tracing/evaluation key.
- `AI_LOG_API_KEY`: Your team-specific key from the [Phoenix Dashboard](https://phoenix.note.transformerlabs.ai/api-keys).
- `MNEMOVERSE_API_KEY`: Your Mnemoverse key; keep it only in local or hosted secret stores.

### 3. Install AI Logging Hooks & Sync Agent Harnesses

Run once after cloning:

```bash
# Install git pre-push hook and verify all agent hooks
bash scripts/setup_hooks.sh

# Synchronize skills, rules, MCP configs, and subagents across all tools
mise run sync     # or: python3 scripts/sync_agent_harness.py
```

### 4. Development & Operation Tasks (via mise)

Tasks are defined in [`mise.toml`](./mise.toml) and executed through modular [`scripts/`](./scripts/):

| Task | Command | Description |
|---|---|---|
| **Run Server** | `mise run run` | Starts FastAPI with auto-reload at `http://localhost:8000` |
| **Run Tests** | `mise run test` | Executes pytest suite with `rtk` token filtering |
| **Lint Code** | `mise run lint` | Runs ruff linter with `rtk` filtering |
| **Format Code** | `mise run format` | Auto-formats code with ruff |
| **Type Check** | `mise run typecheck` | Type checks `src/` with mypy and `rtk` filtering |
| **Full Check** | `mise run check` | Sequential gate: lint + format-check + typecheck + test |
| **Clean Cache** | `mise run clean` | Clears `__pycache__`, `.pytest_cache`, `.ruff_cache`, `.mypy_cache` |
| **Sync Harness** | `mise run sync` | Synchronizes all agent harnesses and MCP configs |

- Interactive API documentation: <http://localhost:8000/docs>
- Health probe: <http://localhost:8000/health>


---

## Directory Structure

```
├── src/
│   ├── agents/          # LangGraph agent definitions
│   │   ├── graph.py     # State graph (nodes + conditional edges)
│   │   ├── state.py     # State schema (TypedDict)
│   │   ├── nodes/       # Node functions
│   │   └── tools/       # Tool definitions (@tool)
│   ├── api/             # FastAPI routes & endpoints
│   │   └── routes.py
│   ├── models/          # Shared Pydantic data schemas
│   │   └── schemas.py
│   ├── services/        # Service clients (LLM, RAG)
│   │   └── llm.py
│   ├── config.py        # Pydantic BaseSettings
│   └── main.py          # Application entrypoint
├── tests/               # Pytest automated test suite
├── docs/                # All deliverables & architecture documents
│   ├── CLASSIFICATION_MODEL.md # Classification model architecture & evaluation narrative
│   ├── DELIVERABLES.md  # Master deliverables checklist
│   ├── AI_LOGS.md       # AI logging audit guidelines
│   ├── DEPLOYMENT.md    # Docker & cloud deployment runbook
│   ├── EVALUATION.md    # Benchmarks & evaluation framework
│   ├── PRESENTATION.md  # Pitch deck & video demo guide
│   ├── architecture/    # Architecture documents & ADRs
│   │   ├── README.md
│   │   └── ARCHITECTURE.md
│   ├── data/            # Benchmark datasets, cards & experiments
│   │   ├── README.md    # Data directory index
│   │   ├── DATASET.md   # Current releases_v2.1 dataset card
│   │   ├── DATASET_CARDS.md # Reference dataset cards
│   │   ├── AUTORESEARCH.md # Autonomous research loop & progression
│   │   ├── BENCHMARK.md # Consolidated chronological benchmark index
│   │   └── benchmark/   # Benchmark archives & history
│   ├── worklog/         # Engineering worklog
│   │   ├── README.md
│   │   ├── WORKLOG.md
│   │   └── 2026-09-12.md
│   └── journal/         # Engineering journal
│       ├── README.md
│       ├── JOURNAL.md
│       └── week-01.md
├── eval/                # Evaluation reports & evidence
├── presentation/        # Slide deck & demo materials
├── scripts/             # Hook handlers, sync scripts, loggers
├── .agents/             # Single source of truth for agent customizations
│   ├── skills/          # Modular agent skills
│   ├── rules/           # Directory rules
│   ├── hooks.json       # Antigravity CLI lifecycle hooks
│   └── mcp_config.json  # Canonical MCP server configuration
├── .claude/ .codex/ .cursor/ .opencode/
│   └── (Harness configurations synchronized via symlinks)
├── Dockerfile           # Multi-stage backend container scaffold
└── docker-compose.yml   # Backend-only scaffold; target stack documented in DEPLOYMENT.md
```

---

## 10 Deliverables for Demo Day

All deliverables are organized under [`docs/`](./docs/) and tracked in [`docs/DELIVERABLES.md`](./docs/DELIVERABLES.md):

| # | Deliverable | Location | Status |
|---|---|---|---|
| 1 | Source code | [`src/`](./src/) | Ready |
| 2 | Project README | [`README.md`](./README.md) | Ready |
| 3 | Architecture diagram | [`docs/architecture/ARCHITECTURE.md`](./docs/architecture/ARCHITECTURE.md) | Ready |
| 4 | AI usage logs | [`.ai-log/`](./.ai-log/), [`docs/AI_LOGS.md`](./docs/AI_LOGS.md) | Active |
| 5 | Live URL / Deploy | [`docs/DEPLOYMENT.md`](./docs/DEPLOYMENT.md) | Staged |
| 6 | Video demo | [`presentation/`](./presentation/), [`docs/PRESENTATION.md`](./docs/PRESENTATION.md) | Staged |
| 7 | Pitch deck | [`presentation/`](./presentation/), [`docs/PRESENTATION.md`](./docs/PRESENTATION.md) | Staged |
| 8 | Development journal | [`docs/journal/JOURNAL.md`](./docs/journal/JOURNAL.md) | Active |
| 9 | Worklog | [`docs/worklog/WORKLOG.md`](./docs/worklog/WORKLOG.md) | Active |
| 10 | Evaluation evidence | [`eval/results/report.md`](./eval/results/report.md), [`docs/EVALUATION.md`](./docs/EVALUATION.md) | Staged |

---

## AI Usage Logging

Prompts from all AI coding assistants are captured in `.ai-log/session.jsonl` and submitted automatically to the grading server on `git push`:

| Tool | Hook Configuration | Capture Point |
|---|---|---|
| **Antigravity CLI** | `.agents/hooks.json` | Every user prompt (`PreInvocation`) + pre-push transcript sweep |
| **OpenCode** | `.opencode/plugins/ai-log.js` | Every message (`chat.message`) |
| **Claude Code** | `.claude/settings.json` | Every prompt (`UserPromptSubmit`) |
| **OpenAI Codex** | `.codex/hooks.json` | Every prompt (`UserPromptSubmit`) & `Stop` |
| **Cursor** | `.cursor/hooks.json` | Each turn and session stop |

For browser-based sessions (ChatGPT, Claude web), log manually:

```bash
bash scripts/_pyrun.sh scripts/log_manual.py --tool chatgpt --prompt "Your prompt query"
```

---

## Model Context Protocol (MCP)

Project-wide MCP servers configured in [`.agents/mcp_config.json`](./.agents/mcp_config.json) (single source of truth) and synchronized to [`.opencode/opencode.json`](./.opencode/opencode.json), [`.cursor/mcp.json`](./.cursor/mcp.json), and [`.mcp.json`](./.mcp.json):


1. **Context7** (`https://mcp.context7.com/mcp`): Up-to-date framework and library documentation.
2. **MarkitDown**: Document to markdown converter (`~/.local/share/mcp-servers/markitdown-server.py`).
3. **Mnemoverse** (`@mnemoverse/mcp-memory-server`): Online persistent associative memory layer.

---

## Installed Skills

The Jev selector is discoverable in `.agents/skills/`. Its routed skill bank is kept separately in `.agents/jev_skills/` so coding harnesses do not preload every skill:

- **`caveman`**: Terse, high-speed execution mode for minimal token overhead.
- **`rtk`**: Reduced Token Kit with hard instructions enforcing zero fluff and surgical diffs.
- **`headroom`**: Proactive token budgeting and context headroom management.
- **`mnemoverse`**: Online memory recall and outcome-feedback discipline.
- **`security`**: Credential protection, leak response, and git history purging.
- **`ai-agent-guide`**: Technical handbook for LangGraph, FastAPI, and BMAD methodology.
- **`config-agent-harness`**: One-command synchronizer for all agent environments.

---

## License

[MIT](LICENSE) — Free for educational and open development use.

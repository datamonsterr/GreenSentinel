---
description: "Initialize project environment: system checks, tools installation, harness synchronization, test validation, and development guidance."
---

# Initialize Project (`/init-project`)

Run this workflow whenever onboarding, setting up a new machine, or verifying that all developer tools, dependencies, and multi-agent harnesses are operational.

## Automated Execution

Run via `mise` or the standalone script:

```bash
mise run init-project
# or directly:
bash scripts/init_project.sh
```

## Workflow Steps (Skipped if already satisfied)

1. **Prerequisites Check**: Verifies `git`, `python3` (3.11+), `node`, `docker`, and `mise`.
2. **Tools Provisioning**: Ensures `python@3.11`, `uv`, and `rtk` are installed via `mise install`.
3. **Virtual Environment**: Verifies `.venv` exists; creates via `uv venv --python 3.11` and installs locked packages via `uv sync` if needed.
4. **Environment Secrets**: Verifies `.env` exists; copies `.env.example` if missing. Ensures `DATABASE_URL` and `REDIS_URL` are defined.
5. **Container Infrastructure**: Starts local PostgreSQL (PostGIS 16), Redis 7, and Qdrant via `docker compose up -d postgres redis qdrant`.
6. **Database Migration & Seeding**: Applies migrations and seeds demo data via `uv run python scripts/migrate_postgres.py`.
7. **Multi-Agent Sync**: Runs `scripts/setup_hooks.sh` and `scripts/sync_agent_harness.py` to activate logging hooks and symlink skills/rules across Antigravity, OpenCode, Claude Code, and Codex.
8. **Quality Gate**: Runs `scripts/check.sh` (`lint`, `format --check`, `typecheck`, `test`).

## Simple Guidance for Developing Project (Caveman Mode)

- **Start infra containers**: `docker compose up -d postgres redis qdrant`
- **Run DB migration**: `uv run python scripts/migrate_postgres.py`
- **Configure Railway**: `bun scripts/railway-config.ts`
- **Start server**: `mise run run` (FastAPI with auto-reload at `http://localhost:8000`)
- **Start telemetry worker**: `uv run python -m src.services.telemetry_queue_worker`
- **Run tests**: `mise run test` (pytest filtered via `rtk`)
- **Run linter**: `mise run lint` (ruff check filtered via `rtk`)
- **Run typecheck**: `mise run typecheck` (mypy filtered via `rtk`)
- **Full verification**: `mise run check` (gate before commit)
- **Harness sync**: `mise run sync` (syncs `.agents/` across harnesses)
- **Add agent node**: create in `src/agents/nodes/` -> wire in `src/agents/graph.py`
- **Add agent tool**: define `@tool` in `src/agents/tools/` -> attach to node
- **Add API route**: add endpoint in `src/api/routes.py`
- **Documentation**: read target `docs/<subfolder>/README.md` first -> write uppercase deliverables

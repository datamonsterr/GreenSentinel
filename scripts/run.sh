#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [ -f "$ROOT_DIR/.venv/bin/activate" ]; then
    # shellcheck disable=SC1091
    source "$ROOT_DIR/.venv/bin/activate"
fi

exec uvicorn src.main:app --reload --reload-dir src/api --reload-dir src/services --reload-dir src/models --reload-dir src/rag --reload-dir src/agents --reload-include "src/main.py" --reload-include "src/config.py" --host 0.0.0.0 --port 8000 --loop asyncio "$@"

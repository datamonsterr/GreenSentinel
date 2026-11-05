#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [ -f "$ROOT_DIR/.venv/bin/activate" ]; then
    # shellcheck disable=SC1091
    source "$ROOT_DIR/.venv/bin/activate"
fi

if command -v rtk >/dev/null 2>&1; then
    exec rtk ruff check src/ tests/ "$@"
else
    exec ruff check src/ tests/ "$@"
fi

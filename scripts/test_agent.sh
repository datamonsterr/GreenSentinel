#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

PYTHON="$ROOT_DIR/.venv/bin/python"
if [ ! -x "$PYTHON" ]; then
    echo "Missing required interpreter: $PYTHON" >&2
    exit 1
fi

export APP_ENV="${APP_ENV:-test}"
export DATABASE_URL=""
export OPENAI_API_KEY="${OPENAI_API_KEY:-test-key}"
export OPENROUTER_API_KEY="${OPENROUTER_API_KEY:-test-key}"

echo "=== [Agent] Running Agent LLM and Evaluation Tests ==="
exec "$PYTHON" -m pytest tests/unit/agents tests/unit/rag tests/integration/agents tests/integration/rag \
    -v --tb=short "$@"

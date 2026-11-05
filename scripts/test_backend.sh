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
exec "$PYTHON" -m pytest tests/unit tests/integration tests/e2e/backend -v --tb=short "$@"

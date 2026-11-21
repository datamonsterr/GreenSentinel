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

PYTEST_OPTS=()
if [ -n "${CI:-}" ] || [ "${PYTEST_XDIST:-}" = "true" ]; then
    PYTEST_OPTS+=("-n" "auto")
fi

exec "$PYTHON" -m pytest tests/unit/ -v "${PYTEST_OPTS[@]}" "$@"

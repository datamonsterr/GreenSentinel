#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

echo "=== [1/4] Running Ruff Linter ==="
"$ROOT_DIR/scripts/lint.sh"

echo "=== [2/4] Checking Code Formatting ==="
if [ -f "$ROOT_DIR/.venv/bin/activate" ]; then
    # shellcheck disable=SC1091
    source "$ROOT_DIR/.venv/bin/activate"
fi
ruff format --check src/ tests/

echo "=== [3/4] Running Type Checker (Mypy) ==="
"$ROOT_DIR/scripts/typecheck.sh"

echo "=== [4/4] Running Test Suite (Pytest) ==="
"$ROOT_DIR/scripts/test.sh"

echo "=== All checks passed successfully! ==="

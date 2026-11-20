#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

echo "Cleaning temporary caches and bytecode..."
find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true
find . -type d -name .ruff_cache -exec rm -rf {} + 2>/dev/null || true
find . -type d -name .mypy_cache -exec rm -rf {} + 2>/dev/null || true
echo "Clean complete."

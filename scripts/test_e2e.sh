#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WEBAPP_DIR="$ROOT_DIR/src/webapp"

echo "=== [E2E] Running Local Playwright E2E Tests ==="
cd "$WEBAPP_DIR"
pnpm test:e2e "$@"

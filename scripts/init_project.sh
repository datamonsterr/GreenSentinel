#!/usr/bin/env bash
# init-project — Full system diagnostics, installation, harness sync, and developer guidance
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

echo "===================================================="
echo "⚡ AI20K Project Initialization & System Verification"
echo "===================================================="

# 1. System Requirements Check
echo "[1/5] Checking system prerequisites..."
MISSING_DEPS=()
for bin in git python3 node; do
    if command -v "$bin" >/dev/null 2>&1; then
        echo "  ✔ $bin found: $(command -v "$bin")"
    else
        echo "  ✖ $bin missing"
        MISSING_DEPS+=("$bin")
    fi
done

if [ ${#MISSING_DEPS[@]} -gt 0 ]; then
    echo "  [ERROR] Missing required system binaries: ${MISSING_DEPS[*]}"
    exit 1
fi

# Check mise
if command -v mise >/dev/null 2>&1; then
    echo "  ✔ mise found: $(mise --version | head -n 1)"
else
    echo "  ✖ mise missing. Install via: curl https://mise.run | sh"
    exit 1
fi

# 2. Mise Tools & Dependencies Installation
echo "[2/5] Provisioning mise tools (Python 3.11, uv, rtk)..."
mise install

# 3. Python uv Environment Setup
echo "[3/5] Setting up Python virtual environment..."
if [ -d ".venv" ] && [ -f ".venv/bin/python" ]; then
    echo "  ✔ .venv already exists (skipping venv creation)"
    mise exec -- uv sync
else
    echo "  ⚡ Initializing .venv via uv..."
    mise exec -- uv venv --python 3.11 .venv
    mise exec -- uv sync
fi

# Environment file check
if [ ! -f .env ]; then
    cp .env.example .env
    echo "  ✔ Created .env from .env.example"
else
    echo "  ✔ .env already present (skipping)"
fi

# Ensure data directories
mkdir -p data/qdrant_storage

# 4. Agent Harness & Logging Hook Synchronization
echo "[4/5] Synchronizing multi-agent harness & hooks..."
bash scripts/setup_hooks.sh
python3 scripts/sync_agent_harness.py

# 5. Full Quality Verification Gate
echo "[5/5] Executing full quality check..."
scripts/check.sh

echo "===================================================="
echo "🚀 INITIALIZATION COMPLETE — ALL SYSTEMS READY"
echo "===================================================="
echo ""
echo "=== Simple Development Guidance (Caveman Mode) ==="
echo "• Start dev server:    mise run run          (http://localhost:8000)"
echo "• Run test suite:      mise run test         (pytest with rtk)"
echo "• Run linter:          mise run lint         (ruff check with rtk)"
echo "• Run type checker:    mise run typecheck    (mypy with rtk)"
echo "• Full check gate:     mise run check        (lint + format + mypy + pytest)"
echo "• Sync agent harness:  mise run sync         (Antigravity, OpenCode, Claude, Codex)"
echo "• Add agent node:      edit src/agents/nodes/ -> wire in src/agents/graph.py"
echo "• Add agent tool:      @tool in src/agents/tools/ -> register in graph"
echo "• Add API route:       src/api/routes.py"
echo "• Update docs:         READ docs/<subfolder>/README.md first -> write uppercase"
echo "===================================================="

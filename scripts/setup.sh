#!/usr/bin/env bash
# Setup script for AI20K project using uv
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

echo "=== AI20K Project Setup (uv + mise) ==="

# Check Python requirement
if command -v uv >/dev/null 2>&1; then
    echo "[1/4] Setting up Python virtual environment via uv..."
    uv venv --python 3.11 .venv
    echo "[2/4] Installing dependencies via uv sync..."
    uv sync
else
    echo "[1/4] Setting up Python virtual environment via python3..."
    python3 -m venv .venv
    source .venv/bin/activate
    echo "[2/4] Installing dependencies via pip..."
    pip install -r requirements.txt
fi

# Create .env if not exists
echo "[3/4] Checking environment configuration..."
if [ ! -f .env ]; then
    cp .env.example .env
    echo "  Created .env from .env.example — please configure your API keys"
else
    echo "  .env already exists"
fi

# Create data directories
echo "[4/4] Creating data directories..."
mkdir -p data/qdrant_storage

echo "=== Setup complete! ==="
echo "Run server: mise run run (or ./scripts/run.sh)"
echo "Run tests:  mise run test (or ./scripts/test.sh)"

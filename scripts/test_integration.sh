#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [ -f "$ROOT_DIR/.venv/bin/activate" ]; then
    # shellcheck disable=SC1091
    source "$ROOT_DIR/.venv/bin/activate"
fi

echo "=== [Integration] Ensuring Docker services are up ==="
"$ROOT_DIR/scripts/docker_up.sh"

echo "=== [Integration] Running Database Migration & Seed ==="
export DATABASE_URL="${DATABASE_URL:-postgresql://postgres:postgrespassword@localhost:5432/postgres}"
export REDIS_URL="${REDIS_URL:-redis://localhost:6379/0}"
export QDRANT_URL="${QDRANT_URL:-http://localhost:6333}"
export APP_ENV="test"

python3 "$ROOT_DIR/scripts/migrate_postgres.py" --target-url "$DATABASE_URL" --seed

echo "=== [Integration] Running Integration Test Suite ==="
exec pytest tests/integration -m docker -v --tb=short "$@"


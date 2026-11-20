#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [[ -z "${ISSUE61_DATABASE_URL:-}" ]]; then
    echo "ERROR: ISSUE61_DATABASE_URL must be set and isolated for this test runner."
    exit 1
fi

if ! .venv/bin/python -c 'from scripts.gis_test_setup import validate_database_url; validate_database_url(__import__("os").environ.get("ISSUE61_DATABASE_URL"))'; then
    echo "ERROR: ISSUE61_DATABASE_URL must be an explicit loopback issue61_* database URL."
    exit 1
fi

GIS_BACKEND_PORT="${GIS_BACKEND_PORT:-18662}"
GIS_FRONTEND_PORT="${GIS_FRONTEND_PORT:-3162}"
API_BASE_URL="http://127.0.0.1:${GIS_BACKEND_PORT}"
NEXT_PUBLIC_API_URL="$API_BASE_URL"
if [[ -z "${REDIS_URL:-}" || -z "${QDRANT_URL:-}" ]]; then
    echo "ERROR: REDIS_URL and QDRANT_URL must be explicitly configured."
    exit 1
fi
if ! .venv/bin/python -c 'import os; from scripts.gis_test_setup import validate_local_service_url; validate_local_service_url(os.environ.get("QDRANT_URL"), "QDRANT_URL")'; then
    echo "ERROR: QDRANT_URL must be an explicit loopback HTTP URL."
    exit 1
fi
if ! .venv/bin/python -c 'import os; from scripts.gis_test_setup import validate_local_redis_url; validate_local_redis_url(os.environ.get("REDIS_URL"))'; then
    echo "ERROR: REDIS_URL must be an explicit loopback Redis URL."
    exit 1
fi

# Missing route legs must stay unavailable instead of being silently repaired by a live provider.
export OSRM_BASE_URL="${OSRM_BASE_URL:-http://127.0.0.1:9}"

if ! command -v lsof >/dev/null 2>&1; then
    echo "ERROR: lsof is required to prove persisted-test port isolation."
    exit 1
fi
if lsof -i :"$GIS_BACKEND_PORT" >/dev/null 2>&1; then
    echo "ERROR: Port $GIS_BACKEND_PORT is already in use!"
    exit 1
fi
if lsof -i :"$GIS_FRONTEND_PORT" >/dev/null 2>&1; then
    echo "ERROR: Port $GIS_FRONTEND_PORT is already in use!"
    exit 1
fi

if .venv/bin/python -c 'import os; from scripts.gis_test_setup import gis_schema_ready; raise SystemExit(0 if gis_schema_ready(os.environ["ISSUE61_DATABASE_URL"]) else 1)'; then
    echo "Using initialized isolated GIS schema; preserving recorded rows."
else
    echo "Running compatible migrations on fresh isolated database..."
    .venv/bin/python scripts/migrate_postgres.py --target-url "$ISSUE61_DATABASE_URL" --skip-seed
fi

export DATABASE_URL="$ISSUE61_DATABASE_URL"
export API_BASE_URL NEXT_PUBLIC_API_URL
export APP_ENV="test"
export TEST_AUTH_ENABLED="true"

echo "Starting backend..."
.venv/bin/python -m uvicorn src.main:app --port "$GIS_BACKEND_PORT" --host 127.0.0.1 > .temp-backend.log 2>&1 &
BACKEND_PID=$!

cleanup() {
    echo "Cleaning up backend (PID: $BACKEND_PID)..."
    kill $BACKEND_PID || true
    wait $BACKEND_PID || true
}
trap cleanup EXIT

echo "Waiting for backend to be healthy..."
deadline=$((SECONDS + 30))
while :; do
    health="$(curl --silent --show-error --fail --connect-timeout 1 --max-time 2 "$API_BASE_URL/health" || true)"
    if .venv/bin/python -c 'import sys; from scripts.gis_test_setup import parse_health_response; raise SystemExit(0 if parse_health_response(sys.stdin.read()) else 1)' <<<"$health"; then
        break
    fi
    if [ "$SECONDS" -ge "$deadline" ]; then
        echo "Backend failed to become healthy. Logs:"
        cat .temp-backend.log
        exit 1
    fi
    sleep 0.5
done

if [[ "$health" != *'"database":"connected"'* && "$health" != *'"database": "connected"'* ]]; then
        echo "Backend reports database is not connected!"
        curl --silent --connect-timeout 1 --max-time 2 "$API_BASE_URL/health" || true
        exit 1
fi
echo "Backend is healthy and database is connected."

echo "Seeding test setup..."
PYTHONPATH=. .venv/bin/python scripts/gis_test_setup.py
echo "Verifying repeat setup preserves isolated database content..."
PYTHONPATH=. .venv/bin/python scripts/gis_test_setup.py --verify-repeat

echo "Running Playwright persisted tests..."
cd "$ROOT_DIR/src/webapp"
GIS_BACKEND_PORT="$GIS_BACKEND_PORT" GIS_FRONTEND_PORT="$GIS_FRONTEND_PORT" E2E_TEST=true NEXT_PUBLIC_E2E_TEST=true \
  ./node_modules/.bin/playwright test -c playwright.persisted.config.ts

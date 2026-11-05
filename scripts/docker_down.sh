#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

# Remove ONLY our own per-run containers and eligible empty Compose networks.
# Never `docker compose down`: it could stop sibling runs' containers.
PG_NAME="${PG_NAME:-greensentinel-postgres}"
REDIS_NAME="${REDIS_NAME:-greensentinel-redis}"
QDRANT_NAME="${QDRANT_NAME:-greensentinel-qdrant}"

echo "=== [Docker] Stopping own backing services (${PG_NAME}, ${REDIS_NAME}, ${QDRANT_NAME}) ==="
docker rm -f "${PG_NAME}" "${REDIS_NAME}" "${QDRANT_NAME}" 2>/dev/null || true
bash "${ROOT_DIR}/scripts/docker_cleanup_stale_networks.sh"

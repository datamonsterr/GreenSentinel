#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

POSTGRES_PORT="${POSTGRES_PORT:-5432}"
REDIS_PORT="${REDIS_PORT:-6379}"
QDRANT_PORT="${QDRANT_PORT:-6333}"
QDRANT_GRPC_PORT="${QDRANT_GRPC_PORT:-6334}"
export POSTGRES_PORT REDIS_PORT QDRANT_PORT QDRANT_GRPC_PORT

PG_NAME="${PG_NAME:-p063-postgres}"
REDIS_NAME="${REDIS_NAME:-p063-redis}"
QDRANT_NAME="${QDRANT_NAME:-p063-qdrant}"
export PG_NAME REDIS_NAME QDRANT_NAME

# Unique compose project per run: same dir basename means same default project,
# so a second `up` with different container_name would RECREATE (kill) the
# first run's containers. CI exports COMPOSE_PROJECT_NAME per run.
COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-p063-local}"
export COMPOSE_PROJECT_NAME

P063_PG_MEMORY="${P063_PG_MEMORY:-}"
P063_REDIS_MEMORY="${P063_REDIS_MEMORY:-}"
P063_QDRANT_MEMORY="${P063_QDRANT_MEMORY:-}"
P063_QDRANT_IMAGE="${P063_QDRANT_IMAGE:-qdrant/qdrant:v1.19.1}"
export P063_PG_MEMORY P063_REDIS_MEMORY P063_QDRANT_MEMORY P063_QDRANT_IMAGE

DOCKER_NETWORK_MODE="${P063_DOCKER_NETWORK_MODE:-compose}"

echo "=== [Docker] Starting ${PG_NAME} (${POSTGRES_PORT}), ${REDIS_NAME} (${REDIS_PORT}), ${QDRANT_NAME} (${QDRANT_PORT}) (net ${P063_NETWORK_SUBNET:-auto}) ==="

# Runner hardening: default-address-pool IPAM leaks surface as
# "all predefined address pools have been fully subnetted"; an explicit
# P063_NETWORK_SUBNET (set per-run in CI) bypasses pool allocation. Stale
# per-run default networks from crashed runs are pruned before they can
# overlap a fresh subnet.
compose_up() {
    docker network rm "${COMPOSE_PROJECT_NAME}_default" >/dev/null 2>&1 || true
    if docker compose up -d "$@"; then
        return 0
    fi
    echo "[Docker] compose up failed; pruning unused networks and stale run bridges, retrying once"
    docker network prune -f >/dev/null 2>&1 || true
    for n in $(docker network ls --filter 'name=p063-' --format '{{.ID}}' 2>/dev/null); do
        docker network rm "$n" >/dev/null 2>&1 || true
    done
    docker compose up -d "$@"
}

# Reuse only OUR OWN healthy containers (same names). Never touch other runs':
# names are unique per CI run via PG_NAME/REDIS_NAME/QDRANT_NAME, and ports are
# allocated per run, so the port-grep killer below can only match our own.
if docker exec "${PG_NAME}" pg_isready -U postgres -d postgres >/dev/null 2>&1 && \
   docker exec "${REDIS_NAME}" redis-cli ping >/dev/null 2>&1; then
    echo "Own Postgres and Redis are already running and healthy. Reusing."
else
    # Remove only our own stale containers or anything squatting OUR ports.
    # With per-run ports this cannot match a sibling run's containers.
    if [ "$DOCKER_NETWORK_MODE" != "bridge" ]; then
        for cid in $(docker ps --format '{{.ID}} {{.Ports}}' | grep ":${POSTGRES_PORT}->" | awk '{print $1}' 2>/dev/null); do
            echo "Stopping conflicting container on port ${POSTGRES_PORT}: $cid"
            docker rm -f "$cid" 2>/dev/null || true
        done
        for cid in $(docker ps --format '{{.ID}} {{.Ports}}' | grep ":${REDIS_PORT}->" | awk '{print $1}' 2>/dev/null); do
            echo "Stopping conflicting container on port ${REDIS_PORT}: $cid"
            docker rm -f "$cid" 2>/dev/null || true
        done
        for cid in $(docker ps --format '{{.ID}} {{.Ports}}' | grep ":${QDRANT_PORT}->" | awk '{print $1}' 2>/dev/null); do
            echo "Stopping conflicting container on port ${QDRANT_PORT}: $cid"
            docker rm -f "$cid" 2>/dev/null || true
        done
    fi

    docker rm -f "${PG_NAME}" "${REDIS_NAME}" "${QDRANT_NAME}" 2>/dev/null || true
    if [ "$DOCKER_NETWORK_MODE" = "bridge" ]; then
        docker run -d --name "${PG_NAME}" --network bridge ${P063_PG_MEMORY:+--memory="${P063_PG_MEMORY}"} -p "127.0.0.1:${POSTGRES_PORT}:5432" \
            -e POSTGRES_USER=postgres -e POSTGRES_PASSWORD=postgrespassword -e POSTGRES_DB=postgres \
            -v "${PGDATA:-./data/postgres_data}:/var/lib/postgresql/data" \
            -v "${ROOT_DIR}/db/migrations:/docker-entrypoint-initdb.d:ro" postgis/postgis:16-3.4-alpine
        docker run -d --name "${REDIS_NAME}" --network bridge ${P063_REDIS_MEMORY:+--memory="${P063_REDIS_MEMORY}"} -p "127.0.0.1:${REDIS_PORT}:6379" \
            redis:7-alpine redis-server --appendonly yes
        docker run -d --name "${QDRANT_NAME}" --network bridge ${P063_QDRANT_MEMORY:+--memory="${P063_QDRANT_MEMORY}"} \
            -p "127.0.0.1:${QDRANT_PORT}:6333" -p "127.0.0.1:${QDRANT_GRPC_PORT}:6334" \
            -v "${QDRANT_DATA:-./data/qdrant_storage}:/qdrant/storage" "${P063_QDRANT_IMAGE:-qdrant/qdrant:v1.19.1}"
    else
        bash "${ROOT_DIR}/scripts/docker_cleanup_stale_networks.sh"
        compose_up redis postgres qdrant
    fi
fi

# Qdrant may already run under our name from the compose call above.
if ! docker exec "${QDRANT_NAME}" true >/dev/null 2>&1; then
    if [ "$DOCKER_NETWORK_MODE" = "bridge" ]; then
        docker run -d --name "${QDRANT_NAME}" --network bridge ${P063_QDRANT_MEMORY:+--memory="${P063_QDRANT_MEMORY}"} \
            -p "127.0.0.1:${QDRANT_PORT}:6333" -p "127.0.0.1:${QDRANT_GRPC_PORT}:6334" \
            -v "${QDRANT_DATA:-./data/qdrant_storage}:/qdrant/storage" "${P063_QDRANT_IMAGE:-qdrant/qdrant:v1.19.1}"
    else
        compose_up qdrant
    fi
fi

echo "=== [Docker] Verifying backing services connectivity ==="
for attempt in {1..30}; do
    pg_ok=0
    redis_ok=0
    qdrant_ok=0

    if docker exec "${PG_NAME}" pg_isready -U postgres -d postgres >/dev/null 2>&1; then
        pg_ok=1
    fi
    if docker exec "${REDIS_NAME}" redis-cli ping >/dev/null 2>&1; then
        redis_ok=1
    fi
    if curl -fsS --connect-timeout 2 --max-time 5 "http://localhost:${QDRANT_PORT}/readyz" >/dev/null 2>&1; then
        qdrant_ok=1
    fi

    if [ "$pg_ok" -eq 1 ] && [ "$redis_ok" -eq 1 ] && [ "$qdrant_ok" -eq 1 ]; then
        echo "Postgres (${POSTGRES_PORT}), Redis (${REDIS_PORT}), and Qdrant (${QDRANT_PORT}) are healthy!"
        sleep 2
        break
    fi
    sleep 1
done

if [ "$pg_ok" -ne 1 ] || [ "$redis_ok" -ne 1 ] || [ "$qdrant_ok" -ne 1 ]; then
    echo "Docker backing services did not become healthy after 30 attempts" >&2
    exit 1
fi

echo "=== [Docker] Backing services are fully operational ==="

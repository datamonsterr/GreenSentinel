#!/usr/bin/env bash
set -euo pipefail

# Remove only abandoned, empty CI Compose bridges. This avoids global
# `docker network prune`, which could affect another job or developer.
CURRENT_PROJECT="${COMPOSE_PROJECT_NAME:-}"
STALE_AFTER_SECONDS="${P063_DOCKER_NETWORK_STALE_AFTER_SECONDS:-3600}"
NOW_EPOCH="${P063_DOCKER_NETWORK_NOW_EPOCH:-$(date +%s)}"
[[ "$STALE_AFTER_SECONDS" =~ ^[0-9]+$ ]] || exit 0
[[ "$NOW_EPOCH" =~ ^[0-9]+$ ]] || exit 0

network_ids="$(docker network ls --filter label=com.docker.compose.project --format '{{.ID}}' 2>/dev/null || true)"
while IFS= read -r network_id; do
  [[ -n "$network_id" ]] || continue
  # Go templates do not turn the two characters '\\t' into a tab. Build the
  # separator with ANSI-C quoting so inspect emits fields the parser can split.
  inspect_format=$'{{.Name}}\t{{.Created}}\t{{len .Containers}}\t{{.Driver}}\t{{index .Labels "com.docker.compose.project"}}\t{{index .Labels "com.docker.compose.network"}}'
  details="$(docker network inspect "$network_id" --format "$inspect_format" 2>/dev/null || true)"
  [[ -n "$details" ]] || continue
  IFS=$'\t' read -r network_name created container_count driver project network_label <<<"$details"
  [[ "$project" =~ ^p063-[0-9]+_[0-9]+$ ]] || continue
  [[ "$network_name" == "${project}_default" ]] || continue
  [[ "$driver" == "bridge" && "$network_label" == "default" ]] || continue
  [[ "$container_count" == "0" ]] || continue
  is_current=false
  [[ "$project" == "$CURRENT_PROJECT" ]] && is_current=true
  created_epoch="$(date -d "$created" +%s 2>/dev/null || true)"
  [[ "$created_epoch" =~ ^[0-9]+$ ]] || continue
  if [[ "$is_current" != true ]]; then
    (( NOW_EPOCH - created_epoch >= STALE_AFTER_SECONDS )) || continue
  fi
  echo "=== [Docker] Removing stale empty CI network ${network_name} (${project}) ==="
  docker network rm "$network_id" >/dev/null 2>&1 || true
done <<< "$network_ids"

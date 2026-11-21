#!/usr/bin/env bash
# Only emit a deployment URL after submission and completion both succeed.
set -euo pipefail
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
: "${VERCEL_TOKEN:?VERCEL_TOKEN is required}"
python3 "$script_dir/vercel_project.py" check >&2
output="$(mktemp)"
errors="$(mktemp)"
trap 'rm -f "$output" "$errors"' EXIT
deploy_args=(--prebuilt --no-wait --archive=tgz)
if [ -n "${API_BASE_URL:-}" ]; then
  deploy_args+=(--env "API_BASE_URL=${API_BASE_URL}")
fi
if [ -n "${NEXT_PUBLIC_API_URL:-}" ]; then
  deploy_args+=(--env "NEXT_PUBLIC_API_URL=${NEXT_PUBLIC_API_URL}")
fi
for attempt in 1 2 3; do
  if vercel deploy "${deploy_args[@]}" "$@" >"$output" 2>"$errors"; then
    cat "$errors" >&2
    break
  else
    status=$?
  fi
  cat "$errors" >&2
  if [ "$attempt" -eq 3 ] || ! grep -Eq 'fetch failed|ECONNRESET|EAI_AGAIN|ETIMEDOUT|UND_ERR_CONNECT_TIMEOUT|UND_ERR_SOCKET|socket hang up' "$errors"; then
    exit "$status"
  fi
  echo "Retrying Vercel submission after a transport error (attempt $attempt of 3)." >&2
  sleep "$((attempt * 5))"
done
deploy_url="$(tail -n 1 "$output")"
if [[ ! "$deploy_url" =~ ^https://[a-zA-Z0-9.-]+\.vercel\.app$ ]]; then
  echo 'Vercel did not return a valid deployment URL.' >&2
  exit 1
fi
python3 "$script_dir/vercel_project.py" wait "$deploy_url" >&2
printf '%s\n' "$deploy_url"

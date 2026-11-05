#!/usr/bin/env bash
# Ship the checked-out tree to a Railway service and wait for the deployment to
# reach SUCCESS. `railway config apply` writes configuration only, so a job that
# applies a plan and stops can report success while the service keeps running an
# older build (staging, 2026-10-15: frontend shipped, backend left on 2026-10-12).
set -euo pipefail

SERVICE=""
PROJECT=""
ENVIRONMENT=""
MESSAGE="CI/CD: Railway code deploy"
ATTEMPTS="${RAILWAY_DEPLOY_ATTEMPTS:-120}"
SLEEP_SECONDS="${RAILWAY_DEPLOY_SLEEP:-5}"

while [ $# -gt 0 ]; do
  case "$1" in
    --service) SERVICE="${2:?--service requires a value}"; shift 2 ;;
    --project) PROJECT="${2:?--project requires a value}"; shift 2 ;;
    --environment) ENVIRONMENT="${2:?--environment requires a value}"; shift 2 ;;
    --message) MESSAGE="${2:?--message requires a value}"; shift 2 ;;
    --attempts) ATTEMPTS="${2:?--attempts requires a value}"; shift 2 ;;
    --sleep) SLEEP_SECONDS="${2:?--sleep requires a value}"; shift 2 ;;
    *) echo "Unknown argument: $1" >&2; exit 2 ;;
  esac
done

if [ -z "$SERVICE" ] || [ -z "$PROJECT" ] || [ -z "$ENVIRONMENT" ]; then
  echo "Usage: $0 --service <id> --project <id> --environment <id> [--message <text>]" >&2
  exit 2
fi

deploy_output="$(mktemp)"
status_output="$(mktemp)"
trap 'rm -f "$deploy_output" "$status_output"' EXIT

# RAILWAY_API_TOKEN is account/workspace scoped; RAILWAY_TOKEN is project scoped.
# The CLI prefers project tokens. Prefer the account token consistently for upload
# and polling when present, while retaining project-only authentication.
auth_env=()
if [ -n "${RAILWAY_API_TOKEN:-}" ]; then
  auth_env=(env -u RAILWAY_TOKEN)
fi
if ! "${auth_env[@]}" timeout --signal=TERM 15m railway up \
  --service "$SERVICE" \
  --project "$PROJECT" \
  --environment "$ENVIRONMENT" \
  --detach --json \
  -m "$MESSAGE" >"$deploy_output"; then
  echo "Railway code deployment submission failed. CLI output:" >&2
  cat "$deploy_output" >&2
  exit 1
fi

deployment_id="$(python3 - "$deploy_output" <<'PY'
import json
import sys


def find_id(value):
    if isinstance(value, dict):
        if value.get("deploymentId"):
            return value["deploymentId"]
        for child in value.values():
            found = find_id(child)
            if found:
                return found
    elif isinstance(value, list):
        for child in value:
            found = find_id(child)
            if found:
                return found
    return ""


for line in open(sys.argv[1]):
    try:
        found = find_id(json.loads(line))
    except json.JSONDecodeError:
        continue
    if found:
        print(found)
        break
PY
)"

if [ -z "$deployment_id" ]; then
  echo "Railway upload returned no deployment ID; refusing to treat an unstarted deployment as success." >&2
  exit 1
fi

echo "Deployed $deployment_id from the checkout; waiting for SUCCESS."

deployment_status=""
attempt=1
while [ "$attempt" -le "$ATTEMPTS" ]; do
  if "${auth_env[@]}" timeout --signal=TERM 30s railway deployment list --service "$SERVICE" --project "$PROJECT" --environment "$ENVIRONMENT" --json >"$status_output" 2>/dev/null; then
    deployment_status="$(python3 - "$status_output" "$deployment_id" <<'PY'
import json
import sys

try:
    payload = json.load(open(sys.argv[1]))
except json.JSONDecodeError:
    # Treat an empty or malformed response like an unavailable status and retry.
    payload = None
target = sys.argv[2]


def find_status(value):
    if isinstance(value, dict):
        if value.get("id") == target or value.get("deploymentId") == target:
            return value.get("status", "")
        for child in value.values():
            found = find_status(child)
            if found:
                return found
    elif isinstance(value, list):
        for child in value:
            found = find_status(child)
            if found:
                return found
    return ""


print(find_status(payload))
PY
)"
  fi
  case "$deployment_status" in
    SUCCESS)
      echo "Deployment $deployment_id reached SUCCESS."
      exit 0
      ;;
    FAILED|CRASHED|REMOVED|SKIPPED)
      echo "Deployment $deployment_id ended in $deployment_status." >&2
      exit 1
      ;;
  esac
  sleep "$SLEEP_SECONDS"
  attempt=$((attempt + 1))
done

echo "Deployment $deployment_id did not reach SUCCESS within $ATTEMPTS attempts (last status: ${deployment_status:-unknown})." >&2
exit 1

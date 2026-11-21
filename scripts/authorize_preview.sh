#!/usr/bin/env bash
set -euo pipefail

TARGET_ENV="${TARGET_ENV:-${AUTH_ENV:-}}"
AUTH_ENV="${AUTH_ENV:-${TARGET_ENV:-}}"

if [ -z "$TARGET_ENV" ] || [ -z "$AUTH_ENV" ]; then
  echo "TARGET_ENV and AUTH_ENV are required" >&2
  exit 1
fi

# Self-hosted jobs share $HOME. Railway CLI rewrites ~/.railway/config.json,
# so concurrent jobs can leave partial JSON and make every poll regenerate it.
railway_home="$(mktemp -d)"
deploy_output="$(mktemp)"
status_output="$(mktemp)"
trap 'rm -rf "$railway_home"; rm -f "$deploy_output" "$status_output"' EXIT
export HOME="$railway_home"

# Railway CLI prefers project tokens when both token types exist. Keep every
# command on the account token supplied by this workflow.
auth_env=()
if [ -n "${RAILWAY_API_TOKEN:-}" ]; then
  auth_env=(env -u RAILWAY_TOKEN)
fi

if [ "$AUTH_ENV" = "dev" ] || [ "${REUSE_DEPLOYMENT:-false}" = "true" ] || [ "$TARGET_ENV" != "$AUTH_ENV" ]; then
  authorized="$("${auth_env[@]}" python3 scripts/auth_config.py "$AUTH_ENV" --extra-origin "$PREVIEW_URL" --merge-railway --project "$RAILWAY_PROJECT_ID" --service "$RAILWAY_SERVICE_ID" --target "$TARGET_ENV")"
else
  authorized="$(python3 scripts/auth_config.py "$AUTH_ENV" --extra-origin "$PREVIEW_URL")"
fi

"${auth_env[@]}" railway variable set --service "$RAILWAY_SERVICE_ID" --project "$RAILWAY_PROJECT_ID" --environment "$TARGET_ENV" --skip-deploys "CLERK_AUTHORIZED_PARTIES=${authorized}" >/dev/null

# Railway variable writes are eventually consistent. Do not start the rollout
# until the scoped environment exposes the exact origin we are authorizing;
# otherwise the new deployment can capture the previous allow-list.
for attempt in {1..30}; do
  authorized_state="$("${auth_env[@]}" railway variable list --service "$RAILWAY_SERVICE_ID" --project "$RAILWAY_PROJECT_ID" --environment "$TARGET_ENV" --json 2>/dev/null || true)"
  if PREVIEW_URL="$PREVIEW_URL" AUTHORIZED_STATE="$authorized_state" python3 - <<'PY'
import json
import os

payload = json.loads(os.environ["AUTHORIZED_STATE"])
value = payload.get("CLERK_AUTHORIZED_PARTIES", "") if isinstance(payload, dict) else ""
if isinstance(value, dict):
    value = value.get("value", "")
if os.environ["PREVIEW_URL"] in {part.strip() for part in str(value).split(",") if part.strip()}:
    raise SystemExit(0)
raise SystemExit(1)
PY
  then
    break
  fi
  if [ "$attempt" = 30 ]; then
    echo "Railway did not expose the exact preview origin after authorization write." >&2
    exit 1
  fi
  sleep 2
done

if ! "${auth_env[@]}" timeout --signal=TERM 15m railway up --service "$RAILWAY_SERVICE_ID" --project "$RAILWAY_PROJECT_ID" --environment "$TARGET_ENV" --detach --json -m "CI/CD: authorize exact Vercel preview origin" >"$deploy_output"; then
  echo "Railway authorization deployment submission failed; CLI output:" >&2
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
  echo "Railway upload did not return a deployment ID; refusing to treat a skipped deployment as success." >&2
  exit 1
fi

deployment_status=""
for attempt in {1..60}; do
  "${auth_env[@]}" railway deployment list --service "$RAILWAY_SERVICE_ID" --project "$RAILWAY_PROJECT_ID" --environment "$TARGET_ENV" --json >"$status_output"
  deployment_status="$(python3 - "$status_output" "$deployment_id" <<'PY'
import json
import sys

payload = json.load(open(sys.argv[1]))
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
  case "$deployment_status" in
    SUCCESS) break ;;
    FAILED|CRASHED|REMOVED|SKIPPED)
      echo "Railway authorization deployment $deployment_id ended in $deployment_status." >&2
      exit 1
      ;;
  esac
  sleep 5
done

if [ "$deployment_status" != "SUCCESS" ]; then
  echo "Railway authorization deployment $deployment_id did not reach SUCCESS within 5 minutes." >&2
  exit 1
fi

for attempt in {1..60}; do
  if curl --silent --fail --max-time 2 "${BACKEND_URL%/}/health" >/dev/null; then
    echo "Scoped Railway preview is healthy after authorization rollout."
    exit 0
  fi
  sleep 3
done

echo "Scoped Railway preview did not become healthy after authorization rollout." >&2
exit 1

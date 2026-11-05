#!/usr/bin/env bash
set -euo pipefail
script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "$script_dir/../oci-common/setup.sh"
python3 "$script_dir/../oci-common/archive.py" pack "$archive" "$OCI_PATH"
# Missing/filtered-out files follow if-no-files-found; no empty artifact is uploaded.
[[ -f "$archive" ]] || exit 0
bootstrap_aws
aws s3 cp "$archive" "s3://${OCI_BUCKET}/${key}" --endpoint-url "$OCI_ENDPOINT" --no-progress
echo "OCI artifact uploaded: s3://${OCI_BUCKET}/${key}"
echo "OCI artifact: s3://${OCI_BUCKET}/${key}" >> "${GITHUB_STEP_SUMMARY:-/dev/null}"

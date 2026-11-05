#!/usr/bin/env bash
set -euo pipefail
echo 'downloaded=false' >> "${GITHUB_OUTPUT:-/dev/null}"
script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
source "$script_dir/../oci-common/setup.sh"
bootstrap_aws
# Required consumer failures must fail the job; only unavailable credentials skip.
aws s3 cp "s3://${OCI_BUCKET}/${key}" "$archive" --endpoint-url "$OCI_ENDPOINT" --no-progress
python3 "$script_dir/../oci-common/archive.py" extract "$archive" "$OCI_PATH"
echo 'downloaded=true' >> "${GITHUB_OUTPUT:-/dev/null}"
echo "OCI artifact downloaded: s3://${OCI_BUCKET}/${key}"
echo "OCI artifact: s3://${OCI_BUCKET}/${key}" >> "${GITHUB_STEP_SUMMARY:-/dev/null}"

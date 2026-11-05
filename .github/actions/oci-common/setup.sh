#!/usr/bin/env bash
# Sourced by the upload/download scripts; each invocation owns one temp directory.
set -euo pipefail
if [[ -z "${OCI_ACCESS_KEY:-}" || -z "${OCI_SECRET_KEY:-}" || -z "${OCI_REGION:-}" || -z "${OCI_ENDPOINT:-}" || -z "${OCI_BUCKET:-}" ]]; then
  echo "OCI artifact transfer skipped: credentials/configuration unavailable (fork or Dependabot run)."
  exit 0
fi
if [[ ! "${OCI_NAME:-}" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ ]]; then
  echo "Invalid OCI artifact name" >&2
  exit 1
fi
transfer_dir="$(mktemp -d "${RUNNER_TEMP:-/tmp}/oci-transfer.XXXXXX")"
trap 'rm -rf "$transfer_dir"' EXIT
archive="$transfer_dir/artifact.tar.gz"
# Stable across run attempts: retrying a consumer can reuse a successful producer.
key="${GITHUB_REPOSITORY:-local}/${GITHUB_RUN_ID:-local}/${OCI_NAME}.tar.gz"
# Ignore ambient AWS sessions/profiles on shared runners; OCI uses its own static key pair.
unset AWS_SESSION_TOKEN AWS_SECURITY_TOKEN AWS_PROFILE AWS_DEFAULT_PROFILE
export AWS_SHARED_CREDENTIALS_FILE=/dev/null
export AWS_CONFIG_FILE="$transfer_dir/aws-config"
printf '[default]\ns3 =\n    addressing_style = path\n' > "$AWS_CONFIG_FILE"
export AWS_ACCESS_KEY_ID="$OCI_ACCESS_KEY" AWS_SECRET_ACCESS_KEY="$OCI_SECRET_KEY"
export AWS_DEFAULT_REGION="$OCI_REGION"
export AWS_REQUEST_CHECKSUM_CALCULATION=WHEN_REQUIRED AWS_RESPONSE_CHECKSUM_VALIDATION=WHEN_REQUIRED
bootstrap_aws() {
  if [[ "${OCI_FORCE_INSTALL:-false}" != true ]] && command -v aws >/dev/null; then
    return
  fi
  local platform architecture version
  platform="$(uname -s)"
  architecture="$(uname -m)"
  version=2.34.56
  case "$platform/$architecture" in
    Linux/x86_64|Linux/aarch64) ;;
    *) echo "Unsupported AWS CLI bootstrap platform: $platform/$architecture" >&2; exit 1 ;;
  esac
  echo "Bootstrapping AWS CLI $version for $platform/$architecture in temporary storage"
  curl --fail --silent --show-error --location --retry 3 --connect-timeout 20 --max-time 180 \
    "https://awscli.amazonaws.com/awscli-exe-linux-${architecture}-${version}.zip" \
    --output "$transfer_dir/awscli.zip"
  python3 "$script_dir/../oci-common/extract_installer.py" "$transfer_dir/awscli.zip" "$transfer_dir/installer"
  "$transfer_dir/installer/aws/install" --install-dir "$transfer_dir/awscli" --bin-dir "$transfer_dir/bin"
  export PATH="$transfer_dir/bin:$PATH"
  aws --version
}

#!/usr/bin/env bash
set -euo pipefail

# ==============================================================================
# Ensure Docker and build tools are installed on Linux CI runners (Ubuntu/Debian)
# ==============================================================================

detect_docker_distro() {
  local os_release="${1:-${OS_RELEASE_PATH:-/etc/os-release}}"
  if [[ ! -f "$os_release" ]]; then
    echo "ubuntu"
    return 0
  fi

  local id="" id_like=""
  id="$( ( . "$os_release" && echo "${ID:-}" ) 2>/dev/null || true )"
  id_like="$( ( . "$os_release" && echo "${ID_LIKE:-}" ) 2>/dev/null || true )"

  case "$id" in
    ubuntu|debian)
      echo "$id"
      return 0
      ;;
  esac

  for like in $id_like; do
    case "$like" in
      ubuntu|debian)
        echo "$like"
        return 0
        ;;
    esac
  done

  echo "ubuntu"
}

detect_docker_codename() {
  local os_release="${1:-${OS_RELEASE_PATH:-/etc/os-release}}"
  local distro="${2:-}"

  # Allow passing (distro, os_release) or (os_release, distro)
  if [[ "$os_release" == "ubuntu" || "$os_release" == "debian" ]]; then
    distro="$1"
    os_release="${2:-${OS_RELEASE_PATH:-/etc/os-release}}"
  fi

  if [[ ! -f "$os_release" ]]; then
    echo ""
    return 0
  fi

  if [[ -z "$distro" ]]; then
    distro="$(detect_docker_distro "$os_release")"
  fi

  if [[ "$distro" == "debian" ]]; then
    ( . "$os_release" && echo "${VERSION_CODENAME:-}" ) 2>/dev/null || true
  else
    ( . "$os_release" && echo "${UBUNTU_CODENAME:-${VERSION_CODENAME:-}}" ) 2>/dev/null || true
  fi
}

ensure_docker() {
  if ! command -v docker >/dev/null 2>&1; then
    sudo rm -f /etc/apt/sources.list.d/docker.list /etc/apt/sources.list.d/docker.sources
    sudo apt-get update -y
    sudo apt-get install -y ca-certificates curl gnupg
    sudo install -m 0755 -d /etc/apt/keyrings

    local os_release="${OS_RELEASE_PATH:-/etc/os-release}"
    local distro codename arch
    distro="$(detect_docker_distro "$os_release")"
    codename="$(detect_docker_codename "$distro" "$os_release")"
    arch="$(dpkg --print-architecture)"

    curl -fsSL "https://download.docker.com/linux/${distro}/gpg" | sudo gpg --dearmor --yes -o /etc/apt/keyrings/docker.gpg
    echo "deb [arch=${arch} signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/${distro} ${codename} stable" | sudo tee /etc/apt/sources.list.d/docker.list >/dev/null
    sudo apt-get update -y
    sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin build-essential
    sudo systemctl enable --now docker || sudo service docker start || true
  elif ! command -v cc >/dev/null 2>&1; then
    sudo apt-get update -y
    sudo apt-get install -y build-essential
  fi

  docker --version
  docker compose version
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  case "${1:-}" in
    --detect-distro)
      detect_docker_distro "${2:-}"
      ;;
    --detect-codename)
      detect_docker_codename "${2:-}" "${3:-}"
      ;;
    *)
      ensure_docker
      ;;
  esac
fi

"""Safety tests for stale Compose network cleanup."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts" / "docker_cleanup_stale_networks.sh"


def _bash() -> str:
    candidates = [r"C:\Program Files\Git\bin\bash.exe", shutil.which("bash")]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return candidate
    raise RuntimeError("bash is required for Docker lifecycle script tests")


def _posix_path(path: Path) -> str:
    result = subprocess.run([_bash(), "-lc", f"cygpath -u '{path}'"], capture_output=True, text=True, check=True)
    return result.stdout.strip()


def _run_script(env: dict[str, str], fake_bin: Path) -> subprocess.CompletedProcess[str]:
    if os.name != "nt":
        return subprocess.run([_bash(), str(SCRIPT)], env=env, text=True, capture_output=True)
    posix_env = {**env, "PATH": f"{_posix_path(fake_bin)}:/usr/bin:/bin"}
    return subprocess.run([_bash(), _posix_path(SCRIPT)], env=posix_env, text=True, capture_output=True)


def test_cleanup_removes_only_old_empty_ci_networks(tmp_path: Path) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    docker = fake_bin / "docker"
    docker.write_text(
        """#!/usr/bin/env bash
set -euo pipefail
if [[ $1 == network && $2 == ls ]]; then
  printf '%s\\n' stale current attached fresh local foreign custom overlay mislabeled missing
elif [[ $1 == network && $2 == inspect ]]; then
  [[ $4 == --format ]]
  [[ $5 != *'\\t'* ]]
  [[ $5 == *$'\t'*$'\t'*$'\t'*$'\t'*$'\t'* ]]
  case $3 in
    stale) printf 'greensentinel-100_1_default\\t2026-10-12T00:00:00Z\\t0\\tbridge\\tgreensentinel-100_1\\tdefault\\n' ;;
    current) printf 'greensentinel-999_1_default\\t2026-10-13T00:59:30Z\\t0\\tbridge\\tgreensentinel-999_1\\tdefault\\n' ;;
    attached) printf 'greensentinel-300_1_default\\t2026-10-12T00:00:00Z\\t1\\tbridge\\tgreensentinel-300_1\\tdefault\\n' ;;
    fresh) printf 'greensentinel-400_1_default\\t2026-10-13T00:59:30Z\\t0\\tbridge\\tgreensentinel-400_1\\tdefault\\n' ;;
    local) printf 'greensentinel-local_default\\t2026-10-12T00:00:00Z\\t0\\tbridge\\tgreensentinel-local\\tdefault\\n' ;;
    foreign) printf 'other-500_1_default\\t2026-10-12T00:00:00Z\\t0\\tbridge\\tother-500_1\\tdefault\\n' ;;
    custom) printf 'greensentinel-500_1_custom\\t2026-10-12T00:00:00Z\\t0\\tbridge\\tgreensentinel-500_1\\tcustom\\n' ;;
    overlay) printf 'greensentinel-600_1_default\\t2026-10-12T00:00:00Z\\t0\\toverlay\\tgreensentinel-600_1\\tdefault\\n' ;;
    mislabeled) printf 'greensentinel-700_1_default\\t2026-10-12T00:00:00Z\\t0\\tbridge\\tgreensentinel-800_1\\tdefault\\n' ;;
    missing) exit 1 ;;
  esac
elif [[ $1 == network && $2 == rm ]]; then
  printf 'removed:%s\\n' "$3" >> "${FAKE_DOCKER_REMOVED}"
fi
""",
        encoding="utf-8",
    )
    docker.chmod(0o755)
    removed = tmp_path / "removed"
    env = {
        **os.environ,
        "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
        "COMPOSE_PROJECT_NAME": "greensentinel-999_1",
        "GREENSENTINEL_DOCKER_NETWORK_NOW_EPOCH": "1791853200",
        "GREENSENTINEL_DOCKER_NETWORK_STALE_AFTER_SECONDS": "3600",
        "FAKE_DOCKER_REMOVED": str(removed),
    }
    result = _run_script(env, fake_bin)
    assert result.returncode == 0, result.stderr
    assert removed.read_text(encoding="utf-8").splitlines() == ["removed:stale", "removed:current"]
    assert all(
        name not in result.stdout
        for name in ("attached", "fresh", "local", "foreign", "custom", "overlay", "mislabeled")
    )


def test_cleanup_is_noop_when_docker_network_listing_fails(tmp_path: Path) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    docker = fake_bin / "docker"
    docker.write_text("#!/usr/bin/env bash\nexit 1\n", encoding="utf-8")
    docker.chmod(0o755)
    env = {**os.environ, "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}"}
    result = _run_script(env, fake_bin)
    assert result.returncode == 0

"""Unit tests for CI Docker setup script distro and codename selection logic."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts" / "ci" / "ensure_docker.sh"


def _bash() -> str:
    candidates = [r"C:\Program Files\Git\bin\bash.exe", shutil.which("bash")]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return candidate
    raise RuntimeError("bash is required to run ensure_docker.sh tests")


def _run_script(args: list[str], env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    cmd = [_bash(), str(SCRIPT), *args]
    run_env = os.environ.copy()
    if env:
        run_env.update(env)
    return subprocess.run(cmd, cwd=ROOT, env=run_env, text=True, capture_output=True, check=True)


def test_distro_selection_ubuntu_noble(tmp_path: Path) -> None:
    fake_os_release = tmp_path / "os-release"
    fake_os_release.write_text(
        'NAME="Ubuntu"\n'
        'VERSION="24.04 LTS (Noble Numbat)"\n'
        "ID=ubuntu\n"
        "ID_LIKE=debian\n"
        "VERSION_CODENAME=noble\n"
        "UBUNTU_CODENAME=noble\n",
        encoding="utf-8",
    )

    res_distro = _run_script(["--detect-distro", str(fake_os_release)])
    assert res_distro.stdout.strip() == "ubuntu"

    res_codename = _run_script(["--detect-codename", str(fake_os_release)])
    assert res_codename.stdout.strip() == "noble"

    # Also test via OS_RELEASE_PATH env var
    res_env = _run_script(["--detect-distro"], env={"OS_RELEASE_PATH": str(fake_os_release)})
    assert res_env.stdout.strip() == "ubuntu"


def test_distro_selection_debian_trixie(tmp_path: Path) -> None:
    fake_os_release = tmp_path / "os-release"
    fake_os_release.write_text(
        'PRETTY_NAME="Debian GNU/Linux trixie/sid"\nNAME="Debian GNU/Linux"\nVERSION_CODENAME=trixie\nID=debian\n',
        encoding="utf-8",
    )

    res_distro = _run_script(["--detect-distro", str(fake_os_release)])
    assert res_distro.stdout.strip() == "debian"

    res_codename = _run_script(["--detect-codename", str(fake_os_release)])
    assert res_codename.stdout.strip() == "trixie"

    res_env = _run_script(["--detect-distro"], env={"OS_RELEASE_PATH": str(fake_os_release)})
    assert res_env.stdout.strip() == "debian"


@pytest.mark.parametrize(
    ("content", "expected_distro"),
    [
        (
            'ID=pop\nID_LIKE="ubuntu debian"\nVERSION_CODENAME=noble\n',
            "ubuntu",
        ),
        (
            "ID=raspbian\nID_LIKE=debian\nVERSION_CODENAME=bookworm\n",
            "debian",
        ),
        (
            "ID=unknown_custom\nID_LIKE=arch\n",
            "ubuntu",
        ),
    ],
)
def test_distro_fallback_id_like(tmp_path: Path, content: str, expected_distro: str) -> None:
    fake_os_release = tmp_path / "os-release"
    fake_os_release.write_text(content, encoding="utf-8")

    res = _run_script(["--detect-distro", str(fake_os_release)])
    assert res.stdout.strip() == expected_distro


def test_distro_fallback_missing_file(tmp_path: Path) -> None:
    missing_file = tmp_path / "nonexistent"
    res = _run_script(["--detect-distro", str(missing_file)])
    assert res.stdout.strip() == "ubuntu"


def test_distro_selection_linuxmint_noble(tmp_path: Path) -> None:
    fake_os_release = tmp_path / "os-release"
    fake_os_release.write_text(
        'NAME="Linux Mint"\n'
        'VERSION="22 (Wilma)"\n'
        "ID=linuxmint\n"
        'ID_LIKE="ubuntu debian"\n'
        "VERSION_CODENAME=wilma\n"
        "UBUNTU_CODENAME=noble\n",
        encoding="utf-8",
    )

    res_distro = _run_script(["--detect-distro", str(fake_os_release)])
    assert res_distro.stdout.strip() == "ubuntu"

    # When distro is ubuntu, UBUNTU_CODENAME (noble) is preferred over VERSION_CODENAME (wilma)
    res_codename = _run_script(["--detect-codename", str(fake_os_release)])
    assert res_codename.stdout.strip() == "noble"

    # Passing distro explicitly to --detect-codename
    res_codename_explicit = _run_script(["--detect-codename", str(fake_os_release), "ubuntu"])
    assert res_codename_explicit.stdout.strip() == "noble"

    res_codename_swapped = _run_script(["--detect-codename", "ubuntu", str(fake_os_release)])
    assert res_codename_swapped.stdout.strip() == "noble"

    # For debian distro, VERSION_CODENAME is used
    res_codename_debian = _run_script(["--detect-codename", str(fake_os_release), "debian"])
    assert res_codename_debian.stdout.strip() == "wilma"


def test_ensure_docker_removes_stale_docker_sources_before_first_update() -> None:
    content = SCRIPT.read_text(encoding="utf-8")
    rm_idx = content.find("rm -f /etc/apt/sources.list.d/docker.list /etc/apt/sources.list.d/docker.sources")
    update_idx = content.find("apt-get update -y")
    assert rm_idx != -1
    assert update_idx != -1
    assert rm_idx < update_idx

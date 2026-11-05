"""Exercise OCI action scripts with a filesystem-backed AWS transport."""

import io
import os
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def transport(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    aws = bin_dir / "aws"
    aws.write_text(
        "#!/usr/bin/env python3\n"
        "import os, pathlib, shutil, sys\n"
        "if sys.argv[1:] == ['--version']: print('aws-cli/2.34.56 fixture'); sys.exit(0)\n"
        "assert os.environ['AWS_REQUEST_CHECKSUM_CALCULATION'] == 'WHEN_REQUIRED'\n"
        "assert os.environ['AWS_RESPONSE_CHECKSUM_VALIDATION'] == 'WHEN_REQUIRED'\n"
        "assert 'addressing_style = path' in pathlib.Path(os.environ['AWS_CONFIG_FILE']).read_text()\n"
        "assert '--endpoint-url' in sys.argv\n"
        "assert not any(os.environ.get(key) for key in ('AWS_SESSION_TOKEN', 'AWS_SECURITY_TOKEN', 'AWS_PROFILE', 'AWS_DEFAULT_PROFILE'))\n"
        "assert os.environ['AWS_SHARED_CREDENTIALS_FILE'] == '/dev/null'\n"
        "source, target = sys.argv[3:5]\n"
        "def local(value):\n"
        "    return pathlib.Path(os.environ['FAKE_STORE']) / value[5:] if value.startswith('s3://') else pathlib.Path(value)\n"
        "source, target = local(source), local(target)\n"
        "if not source.exists(): sys.exit(1)\n"
        "target.parent.mkdir(parents=True, exist_ok=True)\n"
        "shutil.copyfile(source, target)\n"
    )
    aws.chmod(0o755)
    temp = tmp_path / "temp"
    temp.mkdir()
    env = dict(
        os.environ,
        PATH=f"{bin_dir}:{os.environ['PATH']}",
        FAKE_STORE=str(tmp_path / "store"),
        RUNNER_TEMP=str(temp),
        AWS_SESSION_TOKEN="ambient-session",
        AWS_SECURITY_TOKEN="ambient-security",
        AWS_PROFILE="ambient-profile",
        AWS_DEFAULT_PROFILE="ambient-default",
        AWS_SHARED_CREDENTIALS_FILE="/missing/ambient-credentials",
        OCI_ACCESS_KEY="fixture-access",
        OCI_SECRET_KEY="fixture-secret",
        OCI_REGION="ap-singapore-1",
        OCI_ENDPOINT="https://example.invalid",
        OCI_BUCKET="test-bucket",
        OCI_NAME="bundle",
        OCI_MISSING="error",
        OCI_INCLUDE_HIDDEN="false",
        GITHUB_REPOSITORY="owner/repo",
        GITHUB_RUN_ID="123",
        GITHUB_RUN_ATTEMPT="1",
        GITHUB_STEP_SUMMARY=str(tmp_path / "summary"),
        GITHUB_OUTPUT=str(tmp_path / "output"),
    )
    return env


def run_action(kind, env, path, **overrides):
    return subprocess.run(
        ["bash", str(ROOT / f".github/actions/oci-{kind}/{kind}.sh")],
        cwd=ROOT,
        env=dict(env, OCI_PATH=str(path), **overrides),
        capture_output=True,
        text=True,
        check=False,
    )


def object_path(env):
    return Path(env["FAKE_STORE"]) / "test-bucket/owner/repo/123/bundle.tar.gz"


def test_directory_round_trip_preserves_hidden_bundle_and_excludes_cache(transport, tmp_path):
    source = tmp_path / ".next-gis"
    (source / "cache").mkdir(parents=True)
    (source / "cache/ignored").write_text("cache")
    (source / ".hidden").write_text("hidden")
    (source / "manifest").write_text("bundle")
    result = run_action("upload", transport, source, OCI_INCLUDE_HIDDEN="true", OCI_EXCLUDE="cache")
    assert result.returncode == 0, result.stderr
    result = run_action("download", transport, tmp_path / "restored", GITHUB_RUN_ATTEMPT="2")
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "restored/manifest").read_text() == "bundle"
    assert (tmp_path / "restored/.hidden").read_text() == "hidden"
    assert not (tmp_path / "restored/cache").exists()
    assert not list(Path(transport["RUNNER_TEMP"]).iterdir())
    assert "downloaded=true" in Path(transport["GITHUB_OUTPUT"]).read_text()


def test_multiline_common_root_prevents_duplicate_basename_overwrite(transport, tmp_path):
    for directory, content in (("a", "first"), ("b", "second")):
        (tmp_path / directory).mkdir()
        (tmp_path / directory / "report.txt").write_text(content)
    source = f"{tmp_path}/a/report.txt\n{tmp_path}/b/report.txt\n"
    assert run_action("upload", transport, source).returncode == 0
    with tarfile.open(object_path(transport)) as archive:
        assert archive.extractfile("a/report.txt").read() == b"first"
        assert archive.extractfile("b/report.txt").read() == b"second"


def test_hidden_files_are_opt_in(transport, tmp_path):
    source = tmp_path / "input"
    source.mkdir()
    (source / "visible").write_text("yes")
    (source / ".secret").write_text("no")
    assert run_action("upload", transport, source).returncode == 0
    with tarfile.open(object_path(transport)) as archive:
        assert archive.getnames() == ["visible"]


@pytest.mark.parametrize("policy,returncode", [("warn", 0), ("ignore", 0), ("error", 1)])
def test_all_missing_multiline_obeys_policy(transport, tmp_path, policy, returncode):
    result = run_action("upload", transport, f"{tmp_path}/missing\n{tmp_path}/absent", OCI_MISSING=policy)
    assert result.returncode == returncode
    assert not object_path(transport).exists()
    assert not list(Path(transport["RUNNER_TEMP"]).iterdir())


def test_partial_multiline_uploads_existing_files(transport, tmp_path):
    report = tmp_path / "report.md"
    report.write_text("partial")
    result = run_action("upload", transport, f"{report}\n{tmp_path}/missing.json", OCI_MISSING="warn")
    assert result.returncode == 0, result.stderr
    with tarfile.open(object_path(transport)) as archive:
        assert archive.extractfile("report.md").read() == b"partial"


@pytest.mark.parametrize("kind", ["upload", "download"])
def test_secretless_runs_skip_without_transport(transport, tmp_path, kind):
    result = run_action(kind, transport, tmp_path / "absent", OCI_ACCESS_KEY="")
    assert result.returncode == 0
    assert not Path(transport["FAKE_STORE"]).exists()
    if kind == "download":
        assert "downloaded=false" in Path(transport["GITHUB_OUTPUT"]).read_text()


@pytest.mark.parametrize("member_name,link", [("../escape", False), ("/absolute", False), ("link", True)])
def test_download_rejects_unsafe_archive(transport, tmp_path, member_name, link):
    artifact = object_path(transport)
    artifact.parent.mkdir(parents=True)
    with tarfile.open(artifact, "w:gz") as archive:
        member = tarfile.TarInfo(member_name)
        if link:
            member.type = tarfile.SYMTYPE
            member.linkname = "../escape"
        else:
            member.size = 3
        archive.addfile(member, None if link else io.BytesIO(b"bad"))
    result = run_action("download", transport, tmp_path / "restored")
    assert result.returncode != 0
    assert "unsafe OCI artifact member" in result.stderr
    assert not (tmp_path / "escape").exists()
    assert not list(Path(transport["RUNNER_TEMP"]).iterdir())


def test_missing_required_download_fails(transport, tmp_path):
    result = run_action("download", transport, tmp_path / "restored")
    assert result.returncode != 0
    assert not list(Path(transport["RUNNER_TEMP"]).iterdir())


def test_upload_transport_failure_is_fatal_and_cleans_temp(transport, tmp_path):
    report = tmp_path / "report.md"
    report.write_text("report")
    aws = tmp_path / "bin/aws"
    aws.write_text("#!/usr/bin/env bash\nexit 7\n")
    result = run_action("upload", transport, report)
    assert result.returncode == 7
    assert not list(Path(transport["RUNNER_TEMP"]).iterdir())


@pytest.fixture
def bootstrap_transport(transport, tmp_path):
    """An AWS-free runner with Python but deliberately no working venv/ensurepip."""
    isolated_bin = tmp_path / "isolated-bin"
    isolated_bin.mkdir()
    for name in ("bash", "dirname", "mktemp", "rm"):
        (isolated_bin / name).symlink_to(Path("/usr/bin") / name)
    python = isolated_bin / "python3"
    python.write_text(
        "#!/usr/bin/bash\n"
        'if [[ "$1" == "-m" && "$2" == "venv" ]]; then\n'
        "  echo 'The virtual environment was not created successfully because ensurepip is not available.' >&2\n"
        "  exit 42\n"
        "fi\n"
        f'exec "{sys.executable}" "$@"\n'
    )
    python.chmod(0o755)
    uname = isolated_bin / "uname"
    uname.write_text('#!/usr/bin/bash\nif [[ "$1" == "-s" ]]; then echo Linux; else echo "${FAKE_ARCH:-x86_64}"; fi\n')
    uname.chmod(0o755)
    curl = isolated_bin / "curl"
    curl.write_text(
        "#!/usr/bin/env python3\n"
        "import os, pathlib, shutil, sys\n"
        "pathlib.Path(os.environ['FAKE_DOWNLOAD_LOG']).write_text(' '.join(sys.argv[1:]))\n"
        "if os.environ.get('FAKE_NETWORK_FAILURE'): sys.exit(22)\n"
        "shutil.copyfile(os.environ['FAKE_INSTALLER_ZIP'], sys.argv[sys.argv.index('--output') + 1])\n"
    )
    curl.chmod(0o755)
    package = tmp_path / "installer.zip"
    installer = zipfile.ZipInfo("aws/install")
    installer.external_attr = 0o100755 << 16
    installer.create_system = 3
    with zipfile.ZipFile(package, "w") as archive:
        archive.writestr(
            installer,
            "#!/usr/bin/env python3\n"
            "import os, pathlib, shutil, sys\n"
            "if os.environ.get('FAKE_INSTALL_FAILURE'): sys.exit(23)\n"
            "install = pathlib.Path(sys.argv[sys.argv.index('--install-dir') + 1])\n"
            "binary = pathlib.Path(sys.argv[sys.argv.index('--bin-dir') + 1])\n"
            "assert install.is_relative_to(pathlib.Path(os.environ['RUNNER_TEMP']))\n"
            "assert binary.is_relative_to(pathlib.Path(os.environ['RUNNER_TEMP']))\n"
            "install.mkdir(parents=True)\n"
            "binary.mkdir(parents=True)\n"
            "shutil.copyfile(os.environ['FAKE_AWS_BINARY'], binary / 'aws')\n"
            "(binary / 'aws').chmod(0o755)\n",
        )
    return dict(
        transport,
        PATH=str(isolated_bin),
        FAKE_INSTALLER_ZIP=str(package),
        FAKE_AWS_BINARY=str(tmp_path / "bin/aws"),
        FAKE_DOWNLOAD_LOG=str(tmp_path / "download.log"),
    )


@pytest.mark.parametrize("arch", ["x86_64", "aarch64"])
def test_bootstrap_without_ensurepip_round_trips(bootstrap_transport, tmp_path, arch):
    source = tmp_path / "report.md"
    source.write_text("bootstrap report")
    result = run_action("upload", bootstrap_transport, source, FAKE_ARCH=arch)
    assert result.returncode == 0, result.stderr
    assert "Bootstrapping AWS CLI 2.34.56" in result.stdout
    assert (
        f"https://awscli.amazonaws.com/awscli-exe-linux-{arch}-2.34.56.zip"
        in Path(bootstrap_transport["FAKE_DOWNLOAD_LOG"]).read_text()
    )
    result = run_action("download", bootstrap_transport, tmp_path / "restored", FAKE_ARCH=arch)
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "restored/report.md").read_text() == "bootstrap report"
    assert not list(Path(bootstrap_transport["RUNNER_TEMP"]).iterdir())


def test_forced_bootstrap_ignores_existing_aws(bootstrap_transport, tmp_path):
    source = tmp_path / "report.md"
    source.write_text("forced")
    result = run_action(
        "upload",
        bootstrap_transport,
        source,
        PATH=f"{bootstrap_transport['PATH']}:{tmp_path / 'bin'}",
        OCI_FORCE_INSTALL="true",
    )
    assert result.returncode == 0, result.stderr
    assert Path(bootstrap_transport["FAKE_DOWNLOAD_LOG"]).exists()
    assert "Bootstrapping AWS CLI 2.34.56" in result.stdout
    assert not list(Path(bootstrap_transport["RUNNER_TEMP"]).iterdir())


def test_bootstrap_rejects_unsupported_architecture(bootstrap_transport, tmp_path):
    result = run_action("download", bootstrap_transport, tmp_path / "restored", FAKE_ARCH="riscv64")
    assert result.returncode != 0
    assert "Unsupported AWS CLI bootstrap platform" in result.stderr
    assert not Path(bootstrap_transport["FAKE_DOWNLOAD_LOG"]).exists()
    assert not list(Path(bootstrap_transport["RUNNER_TEMP"]).iterdir())


@pytest.mark.parametrize("failure,code", [("FAKE_NETWORK_FAILURE", 22), ("FAKE_INSTALL_FAILURE", 23)])
def test_bootstrap_failure_is_fatal_and_cleans_temp(bootstrap_transport, tmp_path, failure, code):
    result = run_action("download", bootstrap_transport, tmp_path / "restored", **{failure: "true"})
    assert result.returncode == code
    assert not object_path(bootstrap_transport).exists()
    assert not list(Path(bootstrap_transport["RUNNER_TEMP"]).iterdir())


@pytest.mark.parametrize("member_name,mode", [("../escape", 0o100755), ("/absolute", 0o100755), ("aws/link", 0o120777)])
def test_bootstrap_rejects_unsafe_installer_zip(bootstrap_transport, tmp_path, member_name, mode):
    member = zipfile.ZipInfo(member_name)
    member.external_attr = mode << 16
    member.create_system = 3
    with zipfile.ZipFile(bootstrap_transport["FAKE_INSTALLER_ZIP"], "w") as package:
        package.writestr(member, "../../escape")
    result = run_action("download", bootstrap_transport, tmp_path / "restored")
    assert result.returncode != 0
    assert "unsafe AWS CLI installer member" in result.stderr
    assert not (tmp_path / "escape").exists()
    assert not list(Path(bootstrap_transport["RUNNER_TEMP"]).iterdir())


def test_secretless_forced_bootstrap_does_not_download(bootstrap_transport, tmp_path):
    result = run_action(
        "download", bootstrap_transport, tmp_path / "restored", OCI_FORCE_INSTALL="true", OCI_ACCESS_KEY=""
    )
    assert result.returncode == 0
    assert not Path(bootstrap_transport["FAKE_DOWNLOAD_LOG"]).exists()
    assert not list(Path(bootstrap_transport["RUNNER_TEMP"]).iterdir())

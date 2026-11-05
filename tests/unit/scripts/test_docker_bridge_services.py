"""Behavioral checks for the subnet-free Docker bridge mode."""

import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts" / "docker_up.sh"


def _run(tmp_path: Path, *, curl_ok: bool = True, extra_env: dict[str, str] | None = None):
    log = tmp_path / "calls.log"
    bindir = tmp_path / "bin"
    bindir.mkdir()
    docker = bindir / "docker"
    docker.write_text(
        "#!/bin/sh\n"
        'echo docker:$* >> "$CALL_LOG"\n'
        'if [ "$1" = run ]; then : > "$CALL_LOG.ready"; exit 0; fi\n'
        'if [ "$1" = exec ]; then test -f "$CALL_LOG.ready"; exit $?; fi\n'
        "exit 0\n"
    )
    curl = bindir / "curl"
    curl.write_text(f"#!/bin/sh\nexit {0 if curl_ok else 1}\n")
    sleep = bindir / "sleep"
    sleep.write_text("#!/bin/sh\nexit 0\n")
    for path in (docker, curl, sleep):
        path.chmod(0o755)
    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{bindir}{os.pathsep}{env['PATH']}{os.pathsep}/usr/bin:/bin",
            "CALL_LOG": str(log),
            "GREENSENTINEL_DOCKER_NETWORK_MODE": "bridge",
            "PG_NAME": "greensentinel-pg-test",
            "REDIS_NAME": "greensentinel-redis-test",
            "QDRANT_NAME": "greensentinel-qdrant-test",
            "POSTGRES_PORT": "15432",
            "REDIS_PORT": "16379",
            "QDRANT_PORT": "16333",
            "QDRANT_GRPC_PORT": "16334",
        }
    )
    if extra_env:
        env.update(extra_env)
    bash = Path(r"C:\Program Files\Git\usr\bin\bash.exe")
    if not bash.exists():
        bash = Path("/usr/bin/bash")

    def posix(path: Path) -> str:
        return subprocess.check_output([str(bash.parent / "cygpath.exe"), "-u", str(path)], text=True).strip()

    script_path = str(SCRIPT)
    if os.name == "nt":
        env["PATH"] = f"{posix(bindir)}:/usr/bin:/bin"
        env["CALL_LOG"] = posix(log)
        script_path = posix(SCRIPT)
    result = subprocess.run([str(bash), script_path], cwd=ROOT, env=env, text=True, capture_output=True, timeout=30)
    return result, log.read_text() if log.exists() else ""


def test_bridge_mode_uses_builtin_network_and_scoped_containers(tmp_path):
    result, calls = _run(tmp_path)

    assert result.returncode == 0, result.stderr
    assert "docker network create" not in calls
    assert "docker compose" not in calls
    assert "docker:rm -f greensentinel-pg-test greensentinel-redis-test greensentinel-qdrant-test" in calls
    assert "docker:ps" not in calls
    assert "docker:network" not in calls
    runs = [line for line in calls.splitlines() if line.startswith("docker:run ")]
    assert len(runs) == 3
    assert all("--network bridge" in line for line in runs)
    assert "/db/migrations:/docker-entrypoint-initdb.d:ro" in calls
    assert "--name greensentinel-pg-test" in runs[0]
    assert "--name greensentinel-redis-test" in runs[1]
    assert "--name greensentinel-qdrant-test" in runs[2]
    assert "-p 127.0.0.1:15432:5432" in calls
    assert "-p 127.0.0.1:16379:6379" in calls
    assert "-p 127.0.0.1:16333:6333" in calls
    assert "-p 127.0.0.1:16334:6334" in calls


def test_bridge_mode_applies_memory_caps(tmp_path):
    result, calls = _run(
        tmp_path,
        extra_env={
            "GREENSENTINEL_PG_MEMORY": "768m",
            "GREENSENTINEL_REDIS_MEMORY": "256m",
            "GREENSENTINEL_QDRANT_MEMORY": "768m",
        },
    )

    assert result.returncode == 0, result.stderr
    runs = [line for line in calls.splitlines() if line.startswith("docker:run ")]
    assert len(runs) == 3
    assert "--memory=768m" in runs[0]
    assert "--memory=256m" in runs[1]
    assert "--memory=768m" in runs[2]


def test_bridge_mode_fails_when_readiness_never_succeeds(tmp_path):
    result, _ = _run(tmp_path, curl_ok=False)

    assert result.returncode != 0
    assert "did not become healthy" in result.stderr

import os
import subprocess
from pathlib import Path

import pytest


def test_prepare_preview_schema_rejects_wrong_scope_before_ssh(monkeypatch):
    from scripts import railway_pr

    monkeypatch.setattr(railway_pr.subprocess, "run", pytest.fail)
    with pytest.raises(RuntimeError, match=r"matching pr-\* environment"):
        railway_pr.prepare_preview_schema("svc", "project", "dev", 340, "sha")
    with pytest.raises(RuntimeError, match=r"matching pr-\* environment"):
        railway_pr.prepare_preview_schema("svc", "project", "pr-340", 340, "")


def test_prepare_preview_schema_uses_ephemeral_key_and_scoped_ssh_command(monkeypatch, capsys):
    from scripts import railway_pr

    calls = []

    def run(args, **kwargs):
        calls.append((args, kwargs))
        if "--identity-file" in args:
            home = Path(kwargs["env"]["HOME"])
            assert kwargs["env"]["PATH"].split(os.pathsep)[0] == str(home / "bin")
            wrapper = (home / "bin" / "ssh").read_text(encoding="utf-8")
            assert " -F " in wrapper
            assert '"$@"' in wrapper
            config = (home / ".ssh" / "config").read_text(encoding="utf-8")
            assert "StrictHostKeyChecking accept-new" in config
            assert "StrictHostKeyChecking no" not in config
            assert str(home / ".ssh" / "known_hosts") in config
        if args[:2] == ["ssh-keygen", "-lf"]:
            return subprocess.CompletedProcess(args, 0, "256 SHA256:test-fingerprint comment", "")
        return subprocess.CompletedProcess(args, 0, "schema ready", "")

    monkeypatch.setattr(railway_pr.subprocess, "run", run)
    monkeypatch.setattr(railway_pr.shutil, "which", lambda _: "/usr/bin/ssh")
    railway_pr.prepare_preview_schema("svc", "project", "pr-340", 340, "sha")

    assert calls[0][0][:5] == ["ssh-keygen", "-q", "-t", "ed25519", "-N"]
    assert calls[0][1] == {"check": True, "capture_output": True, "text": True, "timeout": 30}
    assert calls[1][0][:3] == ["ssh-keygen", "-lf", calls[0][0][-1] + ".pub"]
    assert calls[2][0][:-1] == ["railway", "ssh", "keys", "add", "--key", calls[0][0][-1] + ".pub", "--name"]
    assert calls[2][0][-1].startswith("p063-pr-340-")
    assert calls[3][0] == [
        "railway",
        "ssh",
        "--identity-file",
        calls[0][0][-1],
        "--project",
        "project",
        "--service",
        "svc",
        "--environment",
        "pr-340",
        "--",
        "python",
        "-m",
        "scripts.prepare_preview_database",
        "--pr",
        "340",
        "--head-sha",
        "sha",
    ]
    assert calls[3][1]["capture_output"] is True
    assert calls[3][1]["text"] is True
    assert calls[3][1]["timeout"] == 180
    assert os.path.basename(calls[3][1]["env"]["HOME"]).startswith("p063-railway-ssh-")
    assert calls[4][0] == ["railway", "ssh", "keys", "remove", "SHA256:test-fingerprint"]
    assert "schema ready" in capsys.readouterr().out


def test_prepare_preview_schema_sanitizes_failure(monkeypatch):
    from scripts import railway_pr

    monkeypatch.setenv("DATABASE_URL", "postgresql://user:secret@db.example/app")
    calls = []

    def run(args, **kwargs):
        calls.append(args)
        if args[:2] == ["ssh-keygen", "-lf"]:
            return subprocess.CompletedProcess(args, 0, "256 SHA256:abc key", "")
        if "--identity-file" in args:
            return subprocess.CompletedProcess(args, 1, "", "DATABASE_URL=postgresql://user:secret@db.example/app")
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(railway_pr.subprocess, "run", run)

    with pytest.raises(RuntimeError) as exc:
        railway_pr.prepare_preview_schema("svc", "project", "pr-340", 340, "sha")
    assert "secret" not in str(exc.value)
    assert calls[-1] == ["railway", "ssh", "keys", "remove", "SHA256:abc"]


def test_prepare_preview_schema_sanitizes_timeout(monkeypatch):
    from scripts import railway_pr

    def run(args, **kwargs):
        if args[:3] == ["ssh-keygen", "-q", "-t"]:
            return subprocess.CompletedProcess(args, 0, "", "")
        if args[:2] == ["ssh-keygen", "-lf"]:
            return subprocess.CompletedProcess(args, 0, "256 SHA256:abc key comment", "")
        if "--identity-file" not in args:
            return subprocess.CompletedProcess(args, 0, "", "")
        raise subprocess.TimeoutExpired(args, 180)

    monkeypatch.setattr(railway_pr.subprocess, "run", run)
    with pytest.raises(RuntimeError, match="TimeoutExpired"):
        railway_pr.prepare_preview_schema("svc", "project", "pr-340", 340, "sha")

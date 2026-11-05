from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from src.services.fraud_classifier.artifacts import (
    load_and_verify_artifacts,
    resolve_artifact_dir,
    verify_artifact_sha256,
)
from src.services.fraud_classifier.model import ClassifierUnavailableError


def test_verify_artifact_sha256(tmp_path: Path):
    f = tmp_path / "test.txt"
    content = b"hello fraud classifier"
    f.write_bytes(content)
    expected_sha = hashlib.sha256(content).hexdigest()

    assert verify_artifact_sha256(f, expected_sha)
    assert not verify_artifact_sha256(f, "bad_sha256")


def test_manifest_missing_raises(tmp_path: Path):
    with pytest.raises(ClassifierUnavailableError, match="Manifest not found"):
        load_and_verify_artifacts(artifact_dir=tmp_path)


def test_sha256_mismatch_raises(tmp_path: Path):
    r3c_file = tmp_path / "r3c.txt"
    r3c_file.write_text("dummy r3c")
    manifest = {
        "model_version": "r3d-2026.10.18",
        "artifacts": {
            "r3c": {
                "file": "r3c.txt",
                "sha256": "0000000000000000000000000000000000000000000000000000000000000000",
                "size_bytes": 10,
            }
        },
    }
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))

    with pytest.raises(ClassifierUnavailableError, match="SHA256 mismatch"):
        load_and_verify_artifacts(artifact_dir=tmp_path)


def test_missing_artifact_file_raises(tmp_path: Path):
    manifest = {
        "model_version": "r3d-2026.10.18",
        "artifacts": {
            "r3c": {
                "file": "nonexistent.txt",
                "sha256": "abc",
                "size_bytes": 10,
            }
        },
    }
    (tmp_path / "manifest.json").write_text(json.dumps(manifest))

    with pytest.raises(ClassifierUnavailableError, match="Artifact file missing"):
        load_and_verify_artifacts(artifact_dir=tmp_path, allow_download=False)


def test_resolve_artifact_dir_env(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("FRAUD_CLASSIFIER_ARTIFACT_DIR", str(tmp_path))
    assert resolve_artifact_dir() == tmp_path


REPO_ROOT = Path(__file__).resolve().parents[4]
MANIFEST_PATH = REPO_ROOT / "models" / "r3d" / "manifest.json"


def _iter_manifest_values(node):
    if isinstance(node, dict):
        for value in node.values():
            yield from _iter_manifest_values(value)
    elif isinstance(node, list):
        for value in node:
            yield from _iter_manifest_values(value)
    else:
        yield node


def test_manifest_has_no_machine_specific_paths():
    manifest = json.loads(MANIFEST_PATH.read_text())

    offending = [
        value
        for value in _iter_manifest_values(manifest)
        if isinstance(value, str) and (value.startswith("/") or "/home/" in value)
    ]

    assert offending == [], f"manifest contains machine-specific paths: {offending}"

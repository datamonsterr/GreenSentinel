"""Artifact manifest resolution, downloading, and integrity verification.

Resolution order:
1. Environment variable FRAUD_CLASSIFIER_ARTIFACT_DIR
2. Production container path /app/models/r3d
3. Repository local models directory (models/r3d)
4. Hugging Face Hub download (repo: datamonsterr/p-063-r3d-classifier @ hf_revision)

Fails closed by raising ClassifierUnavailableError on any missing file or SHA256 mismatch.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from huggingface_hub import hf_hub_download

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_REPO_LOCAL_DIR = REPO_ROOT / "models" / "r3d"
DEFAULT_CONTAINER_DIR = Path("/app/models/r3d")
DEFAULT_CACHE_DIR = Path.home() / ".cache" / "greensentinel" / "models" / "r3d"

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LoadedArtifacts:
    """Verified production model artifact bundle paths and manifest."""

    manifest: dict[str, Any]
    r3c_path: Path
    r3f_path: Path
    stacker_path: Path
    artifact_dir: Path
    short_sha: str


def compute_file_sha256(path: Path) -> str:
    """Compute hex SHA256 digest of a file."""
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(1024 * 1024):
            h.update(chunk)
    return h.hexdigest()


def verify_artifact_sha256(path: Path, expected_sha: str) -> bool:
    """Check if file matches expected SHA256 checksum."""
    if not path.is_file():
        return False
    return compute_file_sha256(path).lower() == expected_sha.lower()


def resolve_artifact_dir() -> Path:
    """Resolve candidate artifact directory by precedence order."""
    env_dir = os.environ.get("FRAUD_CLASSIFIER_ARTIFACT_DIR")
    if env_dir:
        return Path(env_dir)

    if DEFAULT_CONTAINER_DIR.exists() and (DEFAULT_CONTAINER_DIR / "manifest.json").exists():
        return DEFAULT_CONTAINER_DIR

    if DEFAULT_REPO_LOCAL_DIR.exists() and (DEFAULT_REPO_LOCAL_DIR / "manifest.json").exists():
        return DEFAULT_REPO_LOCAL_DIR

    return DEFAULT_CONTAINER_DIR


def download_artifacts_from_hf(
    manifest_path: Path,
    target_dir: Path,
) -> Path:
    """Download required artifacts from Hugging Face Hub at pinned revision."""
    with manifest_path.open() as f:
        manifest = json.load(f)

    repo_id = manifest.get("hf_repo_id", "datamonsterr/p-063-r3d-classifier")
    revision = manifest.get("hf_revision")
    artifacts = manifest.get("artifacts", {})

    target_dir.mkdir(parents=True, exist_ok=True)

    logger.info(
        "Downloading %d artifacts from %s at revision %s to %s...", len(artifacts), repo_id, revision, target_dir
    )
    for name, info in artifacts.items():
        filename = info["file"]
        dest = target_dir / filename
        if dest.exists() and verify_artifact_sha256(dest, info["sha256"]):
            continue

        downloaded_path = hf_hub_download(
            repo_id=repo_id,
            filename=filename,
            revision=revision,
            local_dir=str(target_dir),
        )
        dest_path = Path(downloaded_path)
        if not verify_artifact_sha256(dest_path, info["sha256"]):
            raise RuntimeError(f"Downloaded artifact {name} ({filename}) failed SHA256 verification")

    return target_dir


def load_and_verify_artifacts(
    artifact_dir: str | Path | None = None,
    allow_download: bool = True,
) -> LoadedArtifacts:
    """Load, resolve, download (if needed), and strictly verify all artifact checksums.

    Raises:
        ClassifierUnavailableError: if manifest is missing, download fails,
            or SHA256 checksum mismatches.
    """
    from src.services.fraud_classifier.model import ClassifierUnavailableError

    target_dir = Path(artifact_dir) if artifact_dir else resolve_artifact_dir()
    manifest_file = target_dir / "manifest.json"

    if not manifest_file.exists():
        raise ClassifierUnavailableError(f"Manifest not found at {manifest_file}")

    try:
        with manifest_file.open() as f:
            manifest = json.load(f)
    except Exception as e:
        raise ClassifierUnavailableError(f"Failed to parse manifest at {manifest_file}: {e}") from e

    artifacts_dict = manifest.get("artifacts", {})
    if not artifacts_dict:
        raise ClassifierUnavailableError(f"No artifacts defined in manifest {manifest_file}")

    # Check if files exist locally; if missing, attempt Hugging Face download
    needs_download = False
    missing_names = []
    for name, info in artifacts_dict.items():
        file_path = target_dir / info["file"]
        if not file_path.exists():
            needs_download = True
            missing_names.append((name, file_path))

    if needs_download:
        if not allow_download or not manifest.get("hf_repo_id"):
            raise ClassifierUnavailableError(f"Artifact file missing: {missing_names[0][1]}")
        try:
            download_dir = DEFAULT_CACHE_DIR if target_dir == DEFAULT_CONTAINER_DIR else target_dir
            download_artifacts_from_hf(manifest_file, download_dir)
            target_dir = download_dir
        except Exception as e:
            raise ClassifierUnavailableError(f"Artifact file missing or download failed: {e}") from e

    # Strict SHA256 verification
    verified_paths: dict[str, Path] = {}
    for name, info in artifacts_dict.items():
        file_path = target_dir / info["file"]
        if not file_path.is_file():
            raise ClassifierUnavailableError(f"Artifact file missing: {file_path}")

        expected_sha = info.get("sha256")
        if not expected_sha:
            raise ClassifierUnavailableError(f"Missing expected SHA256 for artifact {name}")

        actual_sha = compute_file_sha256(file_path)
        if actual_sha.lower() != expected_sha.lower():
            raise ClassifierUnavailableError(
                f"SHA256 mismatch for artifact {name} ({file_path}): expected {expected_sha}, got {actual_sha}"
            )
        verified_paths[name] = file_path

    # Extract short sha from stacker or first artifact
    stacker_sha = artifacts_dict.get("stacker", {}).get("sha256") or next(iter(artifacts_dict.values()))["sha256"]
    short_sha = stacker_sha[:12]

    return LoadedArtifacts(
        manifest=manifest,
        r3c_path=verified_paths["r3c"],
        r3f_path=verified_paths["r3f"],
        stacker_path=verified_paths["stacker"],
        artifact_dir=target_dir,
        short_sha=short_sha,
    )

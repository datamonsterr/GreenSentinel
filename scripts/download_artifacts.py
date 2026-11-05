"""Download and verify fraud classifier artifacts from Hugging Face Hub.

Standalone script suitable for Docker build stage or CI setup.
Reads models/r3d/manifest.json and downloads pinned artifacts to target directory,
strictly verifying SHA256 hashes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import sys
from pathlib import Path

from huggingface_hub import hf_hub_download

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("download_artifacts")


def compute_sha256(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()


def download_and_verify(manifest_path: Path, out_dir: Path) -> None:
    if not manifest_path.is_file():
        logger.error("Manifest file not found: %s", manifest_path)
        sys.exit(1)

    with manifest_path.open() as f:
        manifest = json.load(f)

    repo_id = manifest.get("hf_repo_id", "datamonsterr/p-063-r3d-classifier")
    revision = manifest.get("hf_revision")
    artifacts = manifest.get("artifacts", {})

    if not revision:
        logger.error("Manifest missing 'hf_revision'")
        sys.exit(1)

    out_dir.mkdir(parents=True, exist_ok=True)
    logger.info("Downloading %d artifacts from %s @ %s to %s", len(artifacts), repo_id, revision, out_dir)

    for name, info in artifacts.items():
        filename = info["file"]
        expected_sha = info["sha256"]
        dest = out_dir / filename

        if dest.exists():
            actual_sha = compute_sha256(dest)
            if actual_sha.lower() == expected_sha.lower():
                logger.info("Artifact '%s' (%s) already exists with valid SHA256", name, filename)
                continue
            logger.warning("Artifact '%s' exists but SHA256 mismatch, re-downloading...", name)

        logger.info("Fetching '%s' (%s)...", name, filename)
        downloaded = hf_hub_download(
            repo_id=repo_id,
            filename=filename,
            revision=revision,
            local_dir=str(out_dir),
        )
        downloaded_path = Path(downloaded)
        actual_sha = compute_sha256(downloaded_path)
        if actual_sha.lower() != expected_sha.lower():
            logger.error(
                "SHA256 mismatch for '%s': expected %s, got %s",
                name,
                expected_sha,
                actual_sha,
            )
            sys.exit(1)
        logger.info("Verified '%s' (%s) SHA256: %s", name, filename, actual_sha[:12])

    # Also copy manifest.json into out_dir if different location
    dest_manifest = out_dir / "manifest.json"
    if dest_manifest.resolve() != manifest_path.resolve():
        dest_manifest.write_text(manifest_path.read_text())
        logger.info("Copied manifest.json to %s", dest_manifest)

    logger.info("All %d artifacts verified successfully.", len(artifacts))


def main() -> None:
    parser = argparse.ArgumentParser(description="Download and verify fraud classifier artifacts")
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path("models/r3d/manifest.json"),
        help="Path to manifest.json (default: models/r3d/manifest.json)",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path("/app/models/r3d"),
        help="Target output directory (default: /app/models/r3d)",
    )
    args = parser.parse_args()

    download_and_verify(args.manifest, args.out_dir)


if __name__ == "__main__":
    main()

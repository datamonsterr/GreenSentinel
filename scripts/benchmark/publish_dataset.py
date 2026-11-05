"""Publish the GreenSentinel benchmark release to a public Hugging Face dataset repo.

Uploads a release directory (produced by ``merge_releases.py``) under
``<release_name>/`` together with the dataset card as ``README.md``. Streams
files; no large staging copy.

Usage::

    HF_TOKEN=... python scripts/benchmark/publish_dataset.py \
        --repo <owner>/green-sentinel-synthesized-trips \
        --release-dir <dir-with-trips.jsonl> \
        --release-name releases_v1
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from scripts.benchmark.fetch_dataset import sha256_file  # noqa: E402

CARD_DEFAULT = REPO_ROOT / "docs" / "data" / "HF_DATASET_CARD.md"
REQUIRED = ("trips.jsonl", "manifest.json", "labels.csv")


def _list_release(release_dir: Path) -> list[Path]:
    """Return every file under the release dir, sorted, after required-file checks."""
    for name in REQUIRED:
        if not (release_dir / name).exists():
            raise FileNotFoundError(f"{release_dir / name} not found; build the release first")
    return sorted(p for p in release_dir.rglob("*") if p.is_file())


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repo", required=True, help="dataset repo id, e.g. <owner>/green-sentinel-synthesized-trips")
    ap.add_argument("--release-dir", type=Path, required=True)
    ap.add_argument("--release-name", default="releases_v1")
    ap.add_argument("--card", type=Path, default=CARD_DEFAULT)
    ap.add_argument("--token", default=None)
    ap.add_argument("--private", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    files = _list_release(args.release_dir)
    trips = args.release_dir / "trips.jsonl"
    print(f"release {args.release_name}: {len(files)} files, trips.jsonl sha256 {sha256_file(trips)}")
    for p in files:
        print(f"  {args.release_name}/{p.relative_to(args.release_dir)}")

    if args.dry_run:
        print("dry-run: nothing uploaded")
        return 0

    try:
        from huggingface_hub import HfApi
    except ImportError as exc:  # pragma: no cover
        raise SystemExit("huggingface_hub not installed; run: uv pip install '.[benchmark]'") from exc

    api = HfApi(token=args.token)
    api.create_repo(repo_id=args.repo, repo_type="dataset", private=args.private, exist_ok=True)
    if args.card.exists():
        api.upload_file(
            path_or_fileobj=str(args.card), path_in_repo="README.md", repo_id=args.repo, repo_type="dataset"
        )
    commit_info = api.upload_folder(
        repo_id=args.repo,
        repo_type="dataset",
        folder_path=str(args.release_dir),
        path_in_repo=args.release_name,
        commit_message=f"Publish {args.release_name}",
    )
    print(f"uploaded {args.release_name} -> https://huggingface.co/datasets/{args.repo}")
    print(f"commit_oid: {commit_info.oid}")
    print(f"commit_url: {commit_info.commit_url}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

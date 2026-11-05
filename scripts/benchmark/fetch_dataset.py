"""Fetch the P-063 benchmark corpus from the Hugging Face Hub and verify integrity.

The bulk corpus is intentionally out of Git (it is large). It lives in a public
Hugging Face dataset repo and is pulled on demand, then checked against the
recorded checksum so a fetch is reproducible and tamper-evident.

Repo layout (dataset repo)::

    releases_v1/   trips.jsonl (40,000), labels.csv, manifest.json, checksums.json,
                   merged_sample_100.parquet, samples/*

Usage::

    python scripts/benchmark/fetch_dataset.py --profile releases_v1 \
        --out data/benchmark-10k

Environment:
    P063_BENCHMARK_HF_REPO  override the default dataset repo id
    HF_TOKEN                token (optional for a public repo)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

DEFAULT_REPO = os.environ.get("P063_BENCHMARK_HF_REPO", "datamonsterr/p-063-synthesized-trips")
PROFILES = ("releases_v1", "synthesized_vietnam_trip")


def sha256_file(path: Path, chunk: int = 1 << 20) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(chunk), b""):
            digest.update(block)
    return digest.hexdigest()


def _expected(trips: Path, profile_dir: Path) -> str | None:
    """Recorded trips.jsonl sha, from manifest.json or checksums.json."""
    manifest = profile_dir / "manifest.json"
    if manifest.exists():
        value = json.loads(manifest.read_text(encoding="utf-8")).get("trips_sha256")
        if value:
            return value
    checksums = profile_dir / "checksums.json"
    if checksums.exists():
        return json.loads(checksums.read_text(encoding="utf-8")).get("trips.jsonl")
    return None


def verify(profile_dir: Path, expected: str | None = None) -> str:
    trips = profile_dir / "trips.jsonl"
    if not trips.exists():
        raise FileNotFoundError(f"missing {trips}")
    got = sha256_file(trips)
    want = expected or _expected(trips, profile_dir)
    if want and got != want:
        raise ValueError(f"checksum mismatch for {trips}\n  expected {want}\n  got      {got}")
    return got


def fetch(repo: str, profile: str, out: Path, *, revision: str | None = None, token: str | None = None) -> Path:
    if profile not in PROFILES:
        raise ValueError(f"unknown profile {profile!r}; expected one of {list(PROFILES)}")
    try:
        from huggingface_hub import snapshot_download
    except ImportError as exc:  # pragma: no cover - dependency declared in benchmark extra
        raise SystemExit("huggingface_hub not installed; run: uv pip install '.[benchmark]'") from exc

    out.mkdir(parents=True, exist_ok=True)
    snapshot_download(
        repo_id=repo,
        repo_type="dataset",
        revision=revision,
        token=token or os.environ.get("HF_TOKEN"),
        allow_patterns=[f"{profile}/*"],
        local_dir=str(out),
    )
    return out / profile


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--profile", required=True, choices=PROFILES)
    ap.add_argument("--out", type=Path, required=True, help="destination root (profile subdir is written inside)")
    ap.add_argument("--repo", default=DEFAULT_REPO)
    ap.add_argument("--revision", default=None)
    ap.add_argument("--token", default=None)
    ap.add_argument("--no-verify", action="store_true")
    args = ap.parse_args(argv)

    dest = fetch(args.repo, args.profile, args.out, revision=args.revision, token=args.token)
    if args.no_verify:
        print(f"fetched {dest} (verification skipped)")
        return 0
    digest = verify(dest)
    print(f"fetched and verified {dest}\n  trips.jsonl sha256 {digest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

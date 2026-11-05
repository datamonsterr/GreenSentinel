"""Unit tests for benchmark corpus object-storage fetch/publish helpers (Issue #281)."""

from __future__ import annotations

import pytest

from scripts.benchmark.fetch_dataset import sha256_file, verify
from scripts.benchmark.publish_dataset import _list_release


def _profile(tmp_path, body: str = "a\n", sha=None):
    d = tmp_path / "p"
    d.mkdir()
    (d / "trips.jsonl").write_text(body, encoding="utf-8")
    digest = sha if sha else sha256_file(d / "trips.jsonl")
    (d / "manifest.json").write_text(f'{{"trips_sha256": "{digest}"}}', encoding="utf-8")
    return d


def test_verify_passes_on_match(tmp_path) -> None:
    d = _profile(tmp_path)
    assert verify(d) == sha256_file(d / "trips.jsonl")


def test_verify_raises_on_mismatch(tmp_path) -> None:
    d = _profile(tmp_path, sha="deadbeef")
    with pytest.raises(ValueError):
        verify(d)


def test_verify_reads_checksums_json(tmp_path) -> None:
    d = tmp_path / "c"
    d.mkdir()
    (d / "trips.jsonl").write_text("b\n", encoding="utf-8")
    (d / "checksums.json").write_text('{"trips.jsonl": "nope"}', encoding="utf-8")
    with pytest.raises(ValueError):
        verify(d)


def test_list_release_requires_core_files(tmp_path) -> None:
    with pytest.raises(FileNotFoundError):
        _list_release(tmp_path)


def test_list_release_lists_all_files(tmp_path) -> None:
    (tmp_path / "releases_v1").mkdir()
    for name in ("trips.jsonl", "manifest.json", "labels.csv"):
        (tmp_path / name).write_text("x\n", encoding="utf-8")
    (tmp_path / "samples").mkdir()
    (tmp_path / "samples" / "porto_sample_100.parquet").write_text("p", encoding="utf-8")
    files = _list_release(tmp_path)
    names = {p.name for p in files}
    assert {"trips.jsonl", "manifest.json", "labels.csv", "porto_sample_100.parquet"} <= names

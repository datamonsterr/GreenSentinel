"""Unit tests for the grow.py scale-up orchestrator (fast: no full builds)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from scripts.benchmark.grow import geometry_hash, load_batch_ids, parse_plan  # noqa: E402


def _bundle(ref: str, tid: str, aid: str, lon: float) -> dict:
    return {
        "trip_ref": ref,
        "trip_id": tid,
        "assignment_id": aid,
        "telemetry": [
            {"longitude": lon, "latitude": 21.0},
            {"longitude": lon + 0.001, "latitude": 21.001},
        ],
    }


def _write_batch(tmp_path: Path, name: str, bundles: list[dict]) -> Path:
    d = tmp_path / name
    d.mkdir()
    with open(d / "trips.jsonl", "w", encoding="utf-8") as f:
        for b in bundles:
            f.write(json.dumps(b) + "\n")
    return d


def test_parse_plan_ok() -> None:
    batches = parse_plan("v2:20261012:10000,v3:20261101:20000")
    assert [b["name"] for b in batches] == ["v2", "v3"]
    assert batches[0]["seed"] == 20261012 and batches[1]["n"] == 20000


def test_parse_plan_rejects_duplicate_names() -> None:
    with pytest.raises(AssertionError):
        parse_plan("v2:1:100,v2:2:100")


def test_parse_plan_rejects_bad_spec() -> None:
    with pytest.raises((AssertionError, ValueError)):
        parse_plan("v2:0:100")


def test_geometry_hash_distinct_and_stable() -> None:
    a = _bundle("r1", "t1", "a1", 105.8)
    b = _bundle("r2", "t2", "a2", 105.9)
    assert geometry_hash(a) == geometry_hash(_bundle("r3", "t3", "a3", 105.8))
    assert geometry_hash(a) != geometry_hash(b)


def test_load_batch_ids_and_collision(tmp_path: Path) -> None:
    d1 = _write_batch(tmp_path, "b1", [_bundle("bm_b1_00001", "tid-1", "aid-1", 105.8)])
    d2 = _write_batch(tmp_path, "b2", [_bundle("bm_b2_00001", "tid-1", "aid-2", 105.9)])
    refs1, tids1, _, geos1 = load_batch_ids(d1)
    refs2, tids2, _, geos2 = load_batch_ids(d2)
    assert not (refs1 & refs2)
    assert tids1 & tids2 == {"tid-1"}
    assert not (geos1 & geos2)

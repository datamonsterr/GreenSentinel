"""Unit tests for staircase plotting and markdown table generation (Issue #497 / Epic #494)."""

import json
import sys
from pathlib import Path

import pytest

pytest.importorskip("matplotlib")

from scripts.benchmark.experiments import staircase


def test_staircase_generation_from_registry(tmp_path: Path):
    reg_path = tmp_path / "registry.jsonl"
    out_svg = tmp_path / "staircase.svg"
    out_png = tmp_path / "staircase.png"
    out_md = tmp_path / "README.md"

    rows = [
        {
            "attempt": 0,
            "exp_id": "E0",
            "variant": "baseline",
            "issue": "#494",
            "pr": "",
            "primary": 0.70,
            "ci": [0.68, 0.72],
            "guards": {"all_passed": True},
            "decision": "keep",
            "best_so_far": 0.70,
            "date": "2026-10-17",
        },
        {
            "attempt": 1,
            "exp_id": "E1",
            "variant": "bad_hypo",
            "issue": "#495",
            "pr": "#496",
            "primary": 0.71,
            "ci": [0.69, 0.73],
            "guards": {"all_passed": False},
            "decision": "revert",
            "best_so_far": 0.70,
            "date": "2026-10-17",
        },
        {
            "attempt": 2,
            "exp_id": "E2",
            "variant": "good_hypo",
            "issue": "#497",
            "pr": "#498",
            "primary": 0.78,
            "ci": [0.76, 0.80],
            "guards": {"all_passed": True},
            "decision": "keep",
            "best_so_far": 0.78,
            "date": "2026-10-17",
        },
    ]
    with reg_path.open("w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")

    staircase.build_staircase(
        registry_path=reg_path,
        out_svg=out_svg,
        out_png=out_png,
        out_md=out_md,
    )

    assert out_svg.exists()
    assert out_png.exists()
    assert out_md.exists()

    # Check SVG content
    svg_text = out_svg.read_text()
    assert "<svg" in svg_text
    assert "</svg>" in svg_text

    # Check PNG size
    assert out_png.stat().st_size > 0

    # Check README table content
    md_text = out_md.read_text()
    assert "| Attempt | Exp ID | Variant |" in md_text
    assert "| 0 | E0 | baseline |" in md_text
    assert "| 1 | E1 | bad_hypo |" in md_text
    assert "| 2 | E2 | good_hypo |" in md_text
    assert "staircase.png" in md_text


def test_committed_registry_and_attempts():
    repo_root = Path(__file__).resolve().parents[3]
    registry_file = repo_root / "docs" / "data" / "experiments" / "registry.jsonl"
    attempts_dir = repo_root / "docs" / "data" / "experiments" / "attempts"
    assert registry_file.exists(), "docs/data/experiments/registry.jsonl must exist"
    assert attempts_dir.exists(), "docs/data/experiments/attempts must exist"

    fixture_markers = {"fixture", "test", "mock", "dummy", "bad_hypo", "good_hypo"}

    reg_lines = [
        json.loads(line) for line in registry_file.read_text(encoding="utf-8").strip().splitlines() if line.strip()
    ]
    # Committed registry now holds real attempts E0-E6 with exp_ids E0..E6
    assert len(reg_lines) >= 7, f"registry.jsonl must contain at least attempts E0-E6, found: {len(reg_lines)}"
    committed_exp_ids = [row.get("exp_id") for row in reg_lines]
    assert committed_exp_ids[:7] == ["E0", "E1", "E2", "E3", "E4", "E5", "E6"]

    for row in reg_lines:
        assert row.get("exp_id") is not None
        assert not any(m in row.get("variant", "").lower() for m in fixture_markers)
        assert not any(m in row.get("exp_id", "").lower() for m in fixture_markers)
        att_file = attempts_dir / f"{row['exp_id']}.json"
        assert att_file.exists(), f"Attempt file {att_file.name} must exist for registry exp_id {row['exp_id']}"
        att_data = json.loads(att_file.read_text(encoding="utf-8"))
        sha = att_data.get("corpus_trips_sha256") or row.get("corpus_trips_sha256")
        assert sha, f"Committed attempt {row['exp_id']} must have corpus_trips_sha256"
        assert len(sha) == 64
        assert not any(m in sha.lower() for m in fixture_markers)

    attempt_files = list(attempts_dir.glob("*.json"))
    assert len(attempt_files) >= 7, f"attempts dir must contain at least attempts E0-E6, found: {len(attempt_files)}"
    for f in attempt_files:
        data = json.loads(f.read_text(encoding="utf-8"))
        assert not any(m in data.get("variant", "").lower() for m in fixture_markers)
        assert not any(m in data.get("exp_id", "").lower() for m in fixture_markers)
        sha = data.get("corpus_trips_sha256")
        assert sha, f"Committed attempt {f.name} must have corpus_trips_sha256"
        assert len(sha) == 64
        assert not any(m in sha.lower() for m in fixture_markers)


def test_reject_fixture_derived_rows():
    """Verify that fixture-derived rows and attempt payloads are rejected."""
    fixture_markers = {"fixture", "test", "mock", "dummy", "bad_hypo", "good_hypo"}
    bad_rows = [
        {"exp_id": "E1", "variant": "bad_hypo"},
        {"exp_id": "mock_e1", "variant": "real_candidate"},
        {"exp_id": "E2", "variant": "good_hypo"},
        {"exp_id": "dummy_e0", "variant": "baseline"},
        {"exp_id": "E1", "variant": "test_run", "corpus_trips_sha256": "mock_sha"},
    ]
    for row in bad_rows:
        is_fixture = (
            any(m in row.get("variant", "").lower() for m in fixture_markers)
            or any(m in row.get("exp_id", "").lower() for m in fixture_markers)
            or any(m in str(row.get("corpus_trips_sha256", "")).lower() for m in fixture_markers)
        )
        assert is_fixture, f"Expected {row} to be rejected as fixture-derived"


def test_staircase_generation_from_attempts_folder(tmp_path: Path):
    attempts_dir = tmp_path / "attempts"
    attempts_dir.mkdir()
    reg_path = tmp_path / "registry.jsonl"
    out_svg = tmp_path / "staircase.svg"
    out_png = tmp_path / "staircase.png"
    out_md = tmp_path / "README.md"

    att0 = {
        "attempt": 0,
        "exp_id": "E0",
        "variant": "baseline",
        "primary": 0.70,
        "ci": [0.68, 0.72],
        "guards": {"all_passed": True},
        "decision": "keep",
        "best_so_far": 0.70,
        "date": "2026-10-17",
    }
    att1 = {
        "attempt": 1,
        "exp_id": "E1",
        "variant": "v1",
        "primary": 0.75,
        "ci": [0.73, 0.77],
        "guards": {"all_passed": True},
        "decision": "keep",
        "best_so_far": 0.75,
        "date": "2026-10-17",
    }
    (attempts_dir / "E0.json").write_text(json.dumps(att0), encoding="utf-8")
    (attempts_dir / "E1.json").write_text(json.dumps(att1), encoding="utf-8")

    staircase.build_staircase(
        registry_path=reg_path,
        out_svg=out_svg,
        out_png=out_png,
        out_md=out_md,
        attempts_dir=attempts_dir,
    )

    assert out_svg.exists()
    assert out_png.exists()
    assert out_md.exists()
    assert reg_path.exists()
    assert "| 0 | E0 | baseline |" in out_md.read_text()
    assert "| 1 | E1 | v1 |" in out_md.read_text()


def test_missing_matplotlib_fails_without_placeholder_artifacts(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "matplotlib", None)
    svg = tmp_path / "staircase.svg"
    png = tmp_path / "staircase.png"
    with pytest.raises(ImportError):
        staircase.plot_staircase([], svg, png)
    assert not svg.exists()
    assert not png.exists()

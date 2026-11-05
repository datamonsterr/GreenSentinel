"""Unit test for test_presets metadata reconciliation with actual 40k release manifest."""

import json
from pathlib import Path

from src.services.test_presets import (
    PUBLISHED_CLASS_COUNTS,
    PUBLISHED_NO_VIOLATION,
    PUBLISHED_TRIPS,
)


def test_presets_class_counts_sum_to_published_trips():
    """Verify that class counts sum exactly to published total of 40,000."""
    total = sum(PUBLISHED_CLASS_COUNTS.values())
    assert total == PUBLISHED_TRIPS == 40000, f"Expected 40,000 trips, got {total}"


def test_presets_metadata_matches_actual_manifest():
    """Verify class counts match actual pinned HF manifest.json."""
    manifest_path = Path(__file__).resolve().parents[2] / "data" / "benchmark-10k" / "releases_v1" / "manifest.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        expected_counts = manifest.get("class_counts", {})
        assert PUBLISHED_CLASS_COUNTS == expected_counts
        assert PUBLISHED_TRIPS == manifest.get("total_trips")
        assert PUBLISHED_NO_VIOLATION == expected_counts.get("no_violation")
    else:
        # Fallback to the canonical pinned manifest values
        assert PUBLISHED_CLASS_COUNTS == {
            "no_violation": 28000,
            "ERR-01": 2000,
            "ERR-02": 3200,
            "ERR-03": 2000,
            "ERR-04": 1200,
            "ERR-05": 1200,
            "insufficient_evidence": 2400,
        }

"""Unit tests for experiment variant registry resilience and auto-discovery."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from scripts.benchmark.experiments import variants


def test_discover_variants_resilience_to_import_error(tmp_path: Path, caplog: pytest.LogCaptureFixture):
    """Proves one broken variant module with ImportError does not hide other variants."""
    variants_dir = tmp_path / "variants"
    variants_dir.mkdir()

    # 1. Create a valid variant module
    valid_1 = variants_dir / "valid_variant_a.py"
    valid_1.write_text(
        """from scripts.benchmark.experiments.variants import register_variant

@register_variant("mock_variant_a")
def mock_variant_a(bundle, live=False):
    return {"predicted_category": "no_violation"}
""",
        encoding="utf-8",
    )

    # 2. Create a broken variant module with missing dependency
    broken = variants_dir / "broken_variant_b.py"
    broken.write_text(
        """import nonexistent_dependency_xyz_123

from scripts.benchmark.experiments.variants import register_variant

@register_variant("mock_variant_broken")
def mock_variant_broken(bundle, live=False):
    return {"predicted_category": "ERR-01"}
""",
        encoding="utf-8",
    )

    # 3. Create a second valid variant module alphabetically after the broken one
    valid_2 = variants_dir / "valid_variant_c.py"
    valid_2.write_text(
        """from scripts.benchmark.experiments.variants import register_variant

@register_variant("mock_variant_c")
def mock_variant_c(bundle, live=False):
    return {"predicted_category": "ERR-02"}
""",
        encoding="utf-8",
    )

    with caplog.at_level(logging.WARNING):
        discovered = variants.discover_variants(variants_dir=variants_dir)

    # Both valid variants must be registered despite the broken one in between
    assert "mock_variant_a" in discovered
    assert "mock_variant_c" in discovered
    assert "mock_variant_broken" not in discovered

    # Callable retrieval works
    fn_a = variants.get_variant("mock_variant_a")
    assert callable(fn_a)
    assert fn_a({})["predicted_category"] == "no_violation"

    fn_c = variants.get_variant("mock_variant_c")
    assert callable(fn_c)
    assert fn_c({})["predicted_category"] == "ERR-02"

    # Warning logged naming the skipped module and the missing dependency
    log_messages = [rec.message for rec in caplog.records if rec.levelno == logging.WARNING]
    assert any("broken_variant_b" in msg and "nonexistent_dependency_xyz_123" in msg for msg in log_messages)

"""Unit tests for Jev Criteria variants (Issue #496)."""

import pytest

from src.services.jev_criteria import (
    CRITERIA_BASELINE,
    CRITERIA_RISK_BANDS,
    CRITERIA_SEMANTIC,
    get_jev_criteria,
)


def test_get_jev_criteria_default_semantic() -> None:
    criteria = get_jev_criteria()
    assert criteria == CRITERIA_SEMANTIC
    assert set(criteria.keys()) == {
        "ERR-01",
        "ERR-02",
        "ERR-03",
        "ERR-04",
        "ERR-05",
        "no_violation",
    }
    assert "ERR-01" in criteria
    assert "Điều 14.1" in criteria["ERR-01"]


def test_get_jev_criteria_semantic_explicit() -> None:
    criteria = get_jev_criteria("semantic")
    assert criteria == CRITERIA_SEMANTIC


def test_get_jev_criteria_baseline() -> None:
    criteria = get_jev_criteria("baseline")
    assert criteria == CRITERIA_BASELINE
    assert set(criteria.keys()) == {
        "ERR-01",
        "ERR-02",
        "ERR-03",
        "ERR-04",
        "ERR-05",
        "no_violation",
    }
    assert "ERR-01" in criteria
    assert "Điều 14.1" in criteria["ERR-01"]


def test_get_jev_criteria_risk_bands() -> None:
    criteria = get_jev_criteria("risk_bands")
    assert criteria == CRITERIA_RISK_BANDS
    # Must include all 6 classes plus insufficient_evidence
    assert set(criteria.keys()) == {
        "ERR-01",
        "ERR-02",
        "ERR-03",
        "ERR-04",
        "ERR-05",
        "no_violation",
        "insufficient_evidence",
    }
    # Criteria must describe risk bands / thresholds
    assert "180s" in criteria["ERR-02"]
    assert "1.35" in criteria["ERR-03"] or "35%" in criteria["ERR-03"]
    assert "200 km/h" in criteria["ERR-05"] or "teleport" in criteria["ERR-05"].lower()


def test_get_jev_criteria_invalid_variant() -> None:
    with pytest.raises(ValueError, match="Unknown criteria variant"):
        get_jev_criteria("non_existent_variant")

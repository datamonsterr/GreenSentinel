"""Feedback bank coverage and passenger_feedback migration parse test (Issue #270)."""

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
BANK_PATH = REPO_ROOT / "data" / "conversation_bank" / "feedback_bank.yaml"
MIGRATION = REPO_ROOT / "db" / "migrations" / "20261008090000_passenger_feedback_rating.sql"
ROLLBACK = REPO_ROOT / "db" / "rollbacks" / "20261008090000_passenger_feedback_rating.down.sql"

EXPECTED = {
    "complaint": ["late_pickup", "rude_driver", "unsafe_driving", "overcharge_dispute", "no_show_ghost"],
    "praise": ["polite", "clean_car", "fast_pickup", "safe_driving"],
    "neutral": ["general"],
}


def _bank() -> dict:
    with open(BANK_PATH, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def test_feedback_bank_coverage_per_category():
    bank = _bank()
    assert set(bank) == set(EXPECTED)
    for polarity, categories in EXPECTED.items():
        group = bank[polarity]
        assert set(group) == set(categories), polarity
        for category in categories:
            entries = group[category]
            assert len(entries) >= 15, f"{polarity}/{category}: {len(entries)} variants"
            texts = [e["text"] for e in entries]
            assert len(set(texts)) >= 15, f"{polarity}/{category}: variants not distinct"
            langs = {e.get("lang") for e in entries}
            assert {"vi", "en"} <= langs, f"{polarity}/{category}: missing lang {langs}"
            for text in texts:
                assert text and "{" not in text and "}" not in text


def test_migration_adds_rating_column():
    sql = MIGRATION.read_text(encoding="utf-8")
    assert "alter table app.passenger_feedback" in sql.lower()
    assert "add column rating_smallint" in sql.lower()
    assert "smallint" in sql.lower()
    assert "between 1 and 5" in sql.lower()
    assert sql.count("(") == sql.count(")")


def test_rollback_drops_rating_column():
    sql = ROLLBACK.read_text(encoding="utf-8")
    assert "alter table app.passenger_feedback" in sql.lower()
    assert "drop column" in sql.lower() and "rating_smallint" in sql.lower()

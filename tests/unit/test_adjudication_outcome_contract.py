"""Adjudication outcomes written by the API must satisfy the DB check constraint (prod bug: 'agree' was rejected)."""

import re
from pathlib import Path

import pytest

from src.services.case_service import api_outcome, db_outcome

MIGRATIONS = sorted(Path("db/migrations").glob("*.sql"))


def _allowed_outcomes() -> set[str]:
    allowed: set[str] = set()
    for m in MIGRATIONS:  # last definition wins
        for hit in re.finditer(
            r"adjudications_outcome_check\s+check\s*\(outcome in \(([^)]*)\)\)", m.read_text(), re.I | re.S
        ):
            allowed = set(re.findall(r"'([^']+)'", hit.group(1)))
        for hit in re.finditer(r"outcome text not null check \(outcome in \(([^)]*)\)\)", m.read_text(), re.I):
            allowed = set(re.findall(r"'([^']+)'", hit.group(1)))
    return allowed


@pytest.mark.parametrize("api", ["AGREE", "DISAGREE", "agree"])
def test_db_outcome_satisfies_latest_migration_constraint(api):
    assert db_outcome(api) in _allowed_outcomes()


@pytest.mark.parametrize("api", ["AGREE", "DISAGREE"])
def test_outcome_round_trips(api):
    assert api_outcome(db_outcome(api)) == api


def test_legacy_db_values_pass_through():
    assert api_outcome("fine") == "fine"

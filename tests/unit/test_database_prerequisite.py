"""Required integration setup cannot be mistaken for an optional skip."""

from unittest.mock import MagicMock

import psycopg
import pytest

from tests.support.database import require_database


@pytest.mark.parametrize("required", [False, True])
def test_unavailable_database_uses_explicit_proof_mode(monkeypatch, required):
    def unavailable(*_args, **_kwargs):
        raise psycopg.OperationalError("sensitive-connection-marker")

    monkeypatch.setattr("tests.support.database.psycopg.connect", unavailable)
    expected = pytest.fail.Exception if required else pytest.skip.Exception
    with pytest.raises(expected) as failure:
        require_database("postgresql://synthetic-test", required=required)
    assert "sensitive-connection-marker" not in str(failure.value)


def test_connected_but_missing_schema_does_not_pass(monkeypatch):
    connection = MagicMock()
    connection.__enter__.return_value = connection
    connection.cursor.return_value.__enter__.return_value.fetchone.return_value = (None,)
    monkeypatch.setattr("tests.support.database.psycopg.connect", lambda *_a, **_kw: connection)
    with pytest.raises(pytest.fail.Exception):
        require_database("postgresql://synthetic-test", required=True)

"""The required seed proof honors its explicit target and reports safe failures."""

from pathlib import Path

import pytest

from tests.integration import test_database_seed as seed_tests

ROOT = Path(__file__).resolve().parents[2]


class SeedConnection:
    def cursor(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, _query):
        return None

    def fetchone(self):
        return (1,)

    def close(self):
        return None


def test_required_seed_proof_prefers_explicit_target(monkeypatch):
    monkeypatch.setenv("ISSUE63_DATABASE_URL", "postgresql://127.0.0.1/required_test")
    monkeypatch.setenv("DATABASE_URL", "postgresql://127.0.0.1/ordinary_test")
    monkeypatch.setenv("MIGRATION_DATABASE_URL", "postgresql://127.0.0.1/other_test")
    monkeypatch.setattr(seed_tests, "load_dotenv", lambda: None)
    selected = []

    def connect(url):
        selected.append(url)
        return SeedConnection()

    monkeypatch.setattr(seed_tests.psycopg, "connect", connect)
    fixture = seed_tests.db_conn.__wrapped__()
    next(fixture)
    fixture.close()
    assert selected == ["postgresql://127.0.0.1/required_test"]


def test_required_seed_proof_fails_without_exposing_connection_secrets(monkeypatch):
    monkeypatch.setenv("ISSUE63_DATABASE_URL", "postgresql://user:sensitive-marker@127.0.0.1/required_test")
    monkeypatch.setattr(seed_tests, "load_dotenv", lambda: None)
    monkeypatch.setattr("time.sleep", lambda _seconds: None)

    def unavailable(_url):
        raise RuntimeError("connection failed with sensitive-marker")

    monkeypatch.setattr(seed_tests.psycopg, "connect", unavailable)
    try:
        next(seed_tests.db_conn.__wrapped__())
    except pytest.skip.Exception:
        pytest.fail("Required proof was silently skipped")
    except pytest.fail.Exception as failure:
        assert "sensitive-marker" not in str(failure)
    else:
        pytest.fail("Required unavailable database did not fail")


def test_browser_specs_and_issue60_manual_are_canonicalized():
    assert not (ROOT / "src/webapp/e2e").exists()
    assert (ROOT / "docs/testing/MANUAL_TEST_ISSUE_60.md").is_file()
    assert (ROOT / "tests/e2e/browser").is_dir()
    assert (ROOT / "docs/testing/manual/ISSUE_60.md").is_file()

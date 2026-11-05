"""Configured storage must never degrade into a successful memory response."""

from unittest.mock import Mock

import pytest

from src.config import Settings
from src.models.test_simulation import TestPlanCreate
from src.services import test_simulation_repository as storage


@pytest.mark.parametrize("environment", ["production", "staging"])
def test_hosted_requires_isolated_storage(environment):
    with pytest.raises(RuntimeError, match="TEST_DATABASE_URL"):
        storage.TestSimulationRepository(Settings(app_env=environment, test_database_url=""))


def test_configured_storage_requires_driver(monkeypatch):
    monkeypatch.setattr(storage, "psycopg", None)
    repository = storage.TestSimulationRepository(
        Settings(app_env="test", test_database_url="postgresql://unavailable/isolated")
    )
    with pytest.raises(RuntimeError, match="psycopg"):
        repository.create_plan(TestPlanCreate(name="must not exist"), "org-a")
    assert repository._plans == {}


def test_database_outage_never_creates_memory_state(monkeypatch):
    driver = Mock()
    driver.connect.side_effect = OSError("unavailable")
    monkeypatch.setattr(storage, "psycopg", driver)
    repository = storage.TestSimulationRepository(
        Settings(app_env="development", test_database_url="postgresql://unavailable/isolated")
    )
    with pytest.raises(RuntimeError, match="unavailable"):
        repository.create_plan(TestPlanCreate(name="must not exist"), "org-a")
    assert repository._plans == {}


def test_notifications_do_not_hide_query_errors(monkeypatch):
    repository = storage.TestSimulationRepository(Settings(app_env="test", test_database_url=""))
    conn = Mock()
    conn.transaction.side_effect = RuntimeError("schema missing")
    monkeypatch.setattr(repository, "_get_db", lambda: conn)
    from uuid import uuid4

    with pytest.raises(RuntimeError, match="schema missing"):
        repository.get_notifications(uuid4())

import pytest

from src.config import get_settings
from src.services.case_service import CaseService
from tests.support.runtime_reset import reset_runtime_state


@pytest.fixture(autouse=True)
def isolate_unit_backends(monkeypatch):
    """Make unit tests fail closed instead of reaching backing services."""
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("DATABASE_URL", "")
    monkeypatch.setenv("REDIS_URL", "")
    monkeypatch.setenv("QDRANT_URL", "")
    monkeypatch.setenv("OPENAI_API_KEY", "mock")
    monkeypatch.setenv("OPENROUTER_API_KEY", "mock")
    monkeypatch.setenv("GEMINI_API_KEY", "mock")
    monkeypatch.setenv("GOOGLE_API_KEY", "mock")
    monkeypatch.setattr(CaseService, "_get_db_connection", lambda self: None)
    monkeypatch.setattr(CaseService, "get_redis_client", lambda self: None)
    get_settings.cache_clear()
    reset_runtime_state()
    yield
    get_settings.cache_clear()
    reset_runtime_state()

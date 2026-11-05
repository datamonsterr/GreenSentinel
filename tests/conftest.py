import os
from unittest.mock import AsyncMock

if "APP_ENV" not in os.environ:
    os.environ["APP_ENV"] = "test"

os.environ.setdefault("TEST_AUTH_ENABLED", "true")

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from src.main import app


@pytest_asyncio.fixture
async def client():
    """Async HTTP client for testing API endpoints."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
def mock_llm():
    """Mock LLM to avoid calling OpenAI during tests.

    Usage in test:
        def test_something(mock_llm):
            # LLM calls will return mock response instead of hitting OpenAI
            ...
    """
    mock = AsyncMock()
    mock.ainvoke.return_value = AsyncMock(content="Mocked LLM response")
    return mock


@pytest.fixture(autouse=True)
def mock_gemini_key(monkeypatch):
    """Ensure tests run deterministically offline without network calls or rate limits."""
    import os

    if os.getenv("TEST_LIVE_GEMINI") != "1":
        monkeypatch.setenv("GEMINI_API_KEY", "mock")
        monkeypatch.setenv("GOOGLE_API_KEY", "mock")
    if os.getenv("TEST_LIVE_JEV") != "1":
        monkeypatch.setenv("project_jev_api_key", "mock")
        monkeypatch.setenv("PROJECT_JEV_API_KEY", "mock")
        monkeypatch.setenv("JEV_ALLOW_HEURISTIC_FALLBACK", "true")
        monkeypatch.setenv("jev_allow_heuristic_fallback", "true")
    if os.getenv("TEST_LIVE_CLERK") != "1":
        monkeypatch.setenv("CLERK_SECRET_KEY", "")
        monkeypatch.setenv("CLERK_JWT_KEY", "")
    if os.getenv("TEST_LIVE_QDRANT") != "1":
        monkeypatch.setenv("QDRANT_CLUSTER_URL", "")
        monkeypatch.setenv("QDRANT_API_KEY", "")
    if "APP_ENV" not in os.environ:
        monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.delenv("LLM_MODEL", raising=False)
    monkeypatch.delenv("llm_model", raising=False)
    from src.config import get_settings

    get_settings.cache_clear()

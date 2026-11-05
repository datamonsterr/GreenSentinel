import pytest

from src.config import Settings
from src.rag.agent import PolicyRAGAgent
from src.services.content_adapter import ContentAdapter


class FakeStore:
    def search(self, *, query: str, top_k: int, where=None):
        return [{"id": "policy-1", "metadata": {"title": "Safety policy"}, "content": "Wear a helmet."}]


@pytest.mark.parametrize("provider", ["gemini", "openai", "openrouter"])
@pytest.mark.parametrize("credential", ["", "placeholder", "test-key", "your-api-key"])
def test_missing_or_placeholder_credentials_return_source_fallback(monkeypatch, provider, credential):
    settings = Settings(_env_file=None, llm_model=provider, **{f"{provider}_api_key": credential})
    monkeypatch.setattr("src.rag.agent.get_settings", lambda: settings)

    result = PolicyRAGAgent(store=FakeStore()).answer_with_rag("What is required?")

    assert result["answer"] == "Wear a helmet."
    assert result["retrieved_chunks"][0]["id"] == "policy-1"


@pytest.mark.parametrize("provider", ["gemini", "openai", "openrouter"])
def test_configured_provider_keeps_content_adapter_client(monkeypatch, provider):
    settings = Settings(_env_file=None, llm_model=provider, **{f"{provider}_api_key": "synthetic-key"})
    monkeypatch.setattr("src.rag.agent.get_settings", lambda: settings)
    if provider == "gemini":
        monkeypatch.setattr("src.services.content_adapter.genai.Client", lambda **_: object())

    agent = PolicyRAGAgent(store=FakeStore())

    assert agent.client is not None
    if provider == "gemini":
        assert agent.client.__class__ is object
    else:
        assert isinstance(agent.client, ContentAdapter)

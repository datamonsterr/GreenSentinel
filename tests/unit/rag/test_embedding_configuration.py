"""Provider migration uses separate vector spaces without overriding explicit targets."""

import pytest

from src.config import Settings


@pytest.mark.parametrize(
    "environment,prefix", [("development", "dev"), ("test", "test"), ("staging", "test"), ("production", "prod")]
)
def test_openai_defaults_never_select_legacy_gemini_collection(environment, prefix):
    settings = Settings(_env_file=None, app_env=environment, qdrant_collection="", rag_embedding_provider="openai")
    assert settings.effective_qdrant_collection == f"{prefix}-policies-openai-text-embedding-3-small-1536"


def test_explicit_collection_and_legacy_opt_in_are_preserved():
    explicit = Settings(_env_file=None, qdrant_collection="disposable-openai-index", rag_embedding_provider="openai")
    legacy = Settings(_env_file=None, app_env="test", qdrant_collection="", rag_embedding_provider="gemini")
    assert explicit.effective_qdrant_collection == "disposable-openai-index"
    assert legacy.effective_qdrant_collection == "test-policies"

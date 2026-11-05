"""Migration checks stop at mocked provider and vector-store boundaries."""

import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from qdrant_client.models import Distance, VectorParams

from src.rag.embedder import OpenAIEmbedder
from src.rag.store import QdrantPolicyStore


def test_incompatible_existing_collection_fails_before_any_write(monkeypatch):
    client = Mock()
    client.collection_exists.return_value = True
    client.get_collection.return_value = SimpleNamespace(
        config=SimpleNamespace(params=SimpleNamespace(vectors=VectorParams(size=3072, distance=Distance.COSINE)))
    )
    monkeypatch.setattr(QdrantPolicyStore, "_init_client", lambda _self: client)
    with pytest.raises(ValueError, match="vector size 3072"):
        QdrantPolicyStore(collection_name="old-provider-index", embedder=OpenAIEmbedder(api_key="mock"))
    client.create_collection.assert_not_called()
    client.upsert.assert_not_called()
    client.delete_collection.assert_not_called()


def test_legacy_name_is_redirected_without_deleting_old_vectors(monkeypatch):
    client = Mock()
    client.collection_exists.return_value = True
    client.get_collection.return_value = SimpleNamespace(
        config=SimpleNamespace(params=SimpleNamespace(vectors=VectorParams(size=1536, distance=Distance.COSINE)))
    )
    monkeypatch.setattr(QdrantPolicyStore, "_init_client", lambda _self: client)
    store = QdrantPolicyStore(collection_name="test-policies", embedder=OpenAIEmbedder(api_key="mock"))
    assert store.collection_name == "test-policies-openai-text-embedding-3-small-1536"
    client.get_collection.assert_called_with(store.collection_name)
    client.delete_collection.assert_not_called()


def test_failed_provider_preflight_never_constructs_store(monkeypatch, tmp_path):
    from src.rag import ingest

    (tmp_path / "manifest.json").write_text(
        json.dumps(
            [
                {
                    "slug": "policy",
                    "id": "policy",
                    "title": "Policy",
                    "category": "car",
                    "source_url": "https://example.test/policy",
                }
            ]
        ),
        encoding="utf-8",
    )
    (tmp_path / "policy.md").write_text("Recorded policy content.", encoding="utf-8")
    provider = Mock()
    provider.embed_batch.side_effect = RuntimeError("provider credentials rejected")
    store = Mock()
    monkeypatch.setattr(ingest, "create_embedder", lambda: provider)
    monkeypatch.setattr(ingest, "QdrantPolicyStore", store)
    with pytest.raises(RuntimeError, match="credentials rejected"):
        ingest.ingest_policies_to_qdrant(processed_dir=tmp_path)
    store.assert_not_called()

"""S4-TENANT #294 P1a: Qdrant vector enrichment is tenant-scoped, fail closed."""

from types import SimpleNamespace
from unittest.mock import patch

from src.config import Settings
from src.models.schemas import CasePolicyResponse
from src.services.case_service import CaseService

ORG_A = "11111111-1111-4111-8111-111111111111"
ORG_B = "22222222-2222-4222-8222-222222222222"


def _production_settings(**kwargs):
    return Settings(app_env="production", database_url="", clerk_secret_key="sk_test_unit", **kwargs)


def _store_with_fake_client(monkeypatch, points, fail_filtered=False):
    """Build a QdrantPolicyStore without touching the network."""
    from src.rag import store as store_module

    calls = []

    class FakeClient:
        def count(self, collection_name, exact=True):
            return SimpleNamespace(count=5)

        def collection_exists(self, name):
            return True

        def get_collection(self, name):
            return SimpleNamespace(config=SimpleNamespace(params=SimpleNamespace(vectors=SimpleNamespace(size=8))))

        def query_points(self, **kwargs):
            calls.append(kwargs)
            if fail_filtered and "query_filter" in kwargs:
                raise RuntimeError("filtered query boom")
            return SimpleNamespace(points=list(points))

    fake_embedder = SimpleNamespace(dimensions=8, embed_text=lambda q: [0.1] * 8)
    monkeypatch.setattr(store_module.QdrantPolicyStore, "_init_client", lambda self: FakeClient())
    monkeypatch.setattr(store_module.QdrantPolicyStore, "_ensure_collection", lambda self: None)
    monkeypatch.setattr(store_module, "create_embedder", lambda: fake_embedder)
    return store_module.QdrantPolicyStore(), calls


def _point(payload):
    return SimpleNamespace(payload=payload, id="p1", score=0.9)


def test_org_scoped_search_sends_filter_and_never_retries_unfiltered(monkeypatch):
    store, calls = _store_with_fake_client(monkeypatch, points=[])
    results = store.search("stopped too long", top_k=4, where={"organization_id": ORG_A})
    assert results == []
    assert len(calls) == 1, "org-scoped miss must not retry unfiltered"
    query_filter = calls[0].get("query_filter")
    assert query_filter is not None
    conditions = query_filter.must
    assert any(getattr(c, "key", "") == "organization_id" for c in conditions)


def test_org_scoped_query_error_fails_closed_without_unfiltered_retry(monkeypatch):
    store, calls = _store_with_fake_client(monkeypatch, points=[], fail_filtered=True)
    assert store.search("query", top_k=4, where={"organization_id": ORG_A}) == []
    assert len(calls) == 1


def test_org_scoped_fallback_local_search_returns_nothing(monkeypatch):
    store, _ = _store_with_fake_client(monkeypatch, points=[])
    monkeypatch.setattr(store, "count", lambda: 0)
    assert store.search("query", top_k=4, where={"organization_id": ORG_A}) == []


async def test_enrichment_skipped_without_org_in_production():
    """Fail closed: no org means no Qdrant call, no cross-org clauses."""
    service = CaseService(settings=_production_settings())
    policy = CasePolicyResponse(case_id="case-1", suspected_category="ERR-02")
    created = []

    class ExplodingStore:
        def __init__(self, *args, **kwargs):
            created.append(True)
            raise AssertionError("enrichment store must not be built without org")

    with (
        patch.object(service, "_get_case_policy_sync", return_value=policy),
        patch("src.rag.store.QdrantPolicyStore", ExplodingStore),
    ):
        result = await service.get_case_policy("case-1", query="dừng đỗ", organization_id=None)
    assert created == []
    assert result.clauses == []


async def test_enrichment_passes_org_filter_and_drops_foreign_chunks():
    service = CaseService(settings=_production_settings())
    policy = CasePolicyResponse(case_id="case-1", suspected_category="ERR-02")
    seen = {}

    class FakeStore:
        def __init__(self, *args, **kwargs):
            pass

        def search(self, query, top_k=4, where=None):
            seen["where"] = where
            return [
                {"id": "own", "content": "own clause", "metadata": {"organization_id": ORG_A}},
                {"id": "foreign", "content": "foreign clause", "metadata": {"organization_id": ORG_B}},
                {"id": "global", "content": "global clause", "metadata": {}},
            ]

    with (
        patch.object(service, "_get_case_policy_sync", return_value=policy),
        patch("src.rag.store.QdrantPolicyStore", FakeStore),
    ):
        result = await service.get_case_policy("case-1", query="dừng đỗ", organization_id=ORG_A)
    assert seen["where"] == {"organization_id": ORG_A}
    ids = {c.id for c in result.clauses}
    assert "own" in ids and "global" in ids
    assert "foreign" not in ids

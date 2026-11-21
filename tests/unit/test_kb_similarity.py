from src.services.kb_similarity import (
    TokenOverlapScorer,
    embeddings_configured,
    indexing_status_for_new_document,
    tokenize,
)


def test_tokenize_lowercases_and_drops_punct():
    assert tokenize("Thưởng MỐC, chuyến!") == ["thưởng", "mốc", "chuyến"]


def test_identical_and_disjoint():
    s = TokenOverlapScorer()
    assert s.score("thưởng mốc chuyến", "thưởng mốc chuyến") == 1.0
    assert s.score("abc", "xyz") == 0.0
    assert s.score("", "xyz") == 0.0


def test_partial_overlap_is_jaccard():
    assert TokenOverlapScorer().score("a b c", "b c d") == 0.5


def test_rank_orders_by_score_and_limits():
    s = TokenOverlapScorer()
    out = s.rank(
        "milestone bonus trips",
        [("1", "milestone bonus"), ("2", "unrelated words"), ("3", "milestone bonus trips")],
        limit=2,
    )
    assert [k for k, _ in out] == ["3", "1"]


def test_indexing_status_without_key(monkeypatch):
    monkeypatch.delenv("EMBEDDINGS_API_KEY", raising=False)
    assert embeddings_configured() is False
    assert indexing_status_for_new_document() == "embeddings_not_configured"


def test_indexing_status_with_key(monkeypatch):
    monkeypatch.setenv("EMBEDDINGS_API_KEY", "k")
    assert indexing_status_for_new_document() == "not_indexed"


def test_embedding_scorer_with_mock_embedder():
    from src.services.kb_similarity import EmbeddingScorer

    class Mock:
        def embed(self, texts):
            return [[1.0, 0.0] if "a" in t else [0.0, 1.0] for t in texts]

    s = EmbeddingScorer(Mock())
    assert s.score("a", "aa") == 1.0
    assert s.score("a", "z") == 0.0
    assert s.rank("a", [("x", "aa"), ("y", "z")]) == [("x", 1.0)]

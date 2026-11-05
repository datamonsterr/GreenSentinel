from types import SimpleNamespace

import pytest

from src.rag.embedder import OPENAI_EMBED_DIMENSIONS, OpenAIEmbedder


def response(texts, indexes=None, dimensions=OPENAI_EMBED_DIMENSIONS):
    indexes = list(range(len(texts))) if indexes is None else indexes
    return SimpleNamespace(data=[SimpleNamespace(index=i, embedding=[float(i)] * dimensions) for i in indexes])


class FakeEmbeddings:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        value = next(self.responses)
        if isinstance(value, Exception):
            raise value
        return value


def client(fake):
    return SimpleNamespace(embeddings=fake)


def test_openai_batch_splits_at_64_and_restores_response_order():
    first = response(range(64), indexes=list(reversed(range(64))))
    second = response(range(1), indexes=[0])
    fake = FakeEmbeddings([first, second])
    embedder = OpenAIEmbedder(api_key="unit-provider-key", client=client(fake))

    vectors = embedder.embed_batch([str(i) for i in range(65)])

    assert len(fake.calls) == 2
    assert [len(call["input"]) for call in fake.calls] == [64, 1]
    assert len(vectors) == 65
    assert [vector[0] for vector in vectors] == [float(i) for i in range(64)] + [0.0]
    assert fake.calls[0]["model"] == "text-embedding-3-small"
    assert fake.calls[0]["dimensions"] == 1536


@pytest.mark.parametrize(
    "bad_response,match",
    [
        (response(["a"], indexes=[1]), "indexes"),
        (SimpleNamespace(data=[]), "count"),
        (response(["a"], dimensions=OPENAI_EMBED_DIMENSIONS - 1), "dimension"),
        (
            SimpleNamespace(data=[SimpleNamespace(index=0, embedding=[float("nan")] * OPENAI_EMBED_DIMENSIONS)]),
            "finite",
        ),
    ],
)
def test_openai_rejects_malformed_vectors(bad_response, match):
    fake = FakeEmbeddings([bad_response])
    embedder = OpenAIEmbedder(api_key="real-test-key", client=client(fake))

    with pytest.raises(ValueError, match=match):
        embedder.embed_batch(["text"])


def test_missing_or_mock_key_fails_without_constructing_sdk(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert OpenAIEmbedder().client is None
    with pytest.raises(RuntimeError, match="not configured"):
        OpenAIEmbedder().embed_text("text")

    with pytest.raises(RuntimeError, match="not configured"):
        OpenAIEmbedder(api_key="mock").embed_text("text")


def test_unauthorized_is_not_retried(monkeypatch):
    error = RuntimeError("unauthorized")
    error.status_code = 401
    fake = FakeEmbeddings([error])
    sleeps = []
    monkeypatch.setattr("src.rag.embedder.time.sleep", sleeps.append)

    with pytest.raises(RuntimeError, match="unauthorized"):
        OpenAIEmbedder(api_key="real-test-key", client=client(fake)).embed_text("text")
    assert len(fake.calls) == 1
    assert sleeps == []


def test_rate_limit_retries_with_bound(monkeypatch):
    error = RuntimeError("rate limited")
    error.status_code = 429
    fake = FakeEmbeddings([error, error, response(["a"])])
    sleeps = []
    monkeypatch.setattr("src.rag.embedder.time.sleep", sleeps.append)

    result = OpenAIEmbedder(api_key="real-test-key", client=client(fake), max_retries=2).embed_text("text")

    assert len(result) == OPENAI_EMBED_DIMENSIONS
    assert len(fake.calls) == 3
    assert sleeps == [0.25, 0.5]

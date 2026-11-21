"""Similarity scoring for knowledge mapping (ADR-032 / plan Decision 5).

No live embeddings exist locally. `SimilarityScorer` is the interface; `TokenOverlapScorer`
(Jaccard on word tokens) is the deterministic default. `EmbeddingScorer` wraps any `Embedder`
(cosine) and is exercised in tests with a mock embedder.
"""

from __future__ import annotations

import math
import os
import re
from collections.abc import Sequence
from typing import Protocol

_WORD = re.compile(r"[^\W_]+", re.UNICODE)


def tokenize(text: str) -> list[str]:
    return [t.lower() for t in _WORD.findall(text or "")]


class SimilarityScorer(Protocol):
    def score(self, a: str, b: str) -> float: ...

    def rank(self, query: str, items: Sequence[tuple[str, str]], limit: int = 5) -> list[tuple[str, float]]: ...


class _RankMixin:
    def score(self, a: str, b: str) -> float:  # pragma: no cover - overridden
        raise NotImplementedError

    def rank(self, query: str, items: Sequence[tuple[str, str]], limit: int = 5) -> list[tuple[str, float]]:
        scored = [(key, round(self.score(query, text), 4)) for key, text in items]
        scored = [s for s in scored if s[1] > 0]
        scored.sort(key=lambda kv: (-kv[1], kv[0]))
        return scored[:limit]


class TokenOverlapScorer(_RankMixin):
    def score(self, a: str, b: str) -> float:
        ta, tb = set(tokenize(a)), set(tokenize(b))
        if not ta or not tb:
            return 0.0
        return len(ta & tb) / len(ta | tb)


class Embedder(Protocol):
    def embed(self, texts: Sequence[str]) -> list[list[float]]: ...


class EmbeddingScorer(_RankMixin):
    def __init__(self, embedder: Embedder):
        self.embedder = embedder

    def score(self, a: str, b: str) -> float:
        va, vb = self.embedder.embed([a, b])
        na, nb = math.sqrt(sum(x * x for x in va)), math.sqrt(sum(x * x for x in vb))
        if not na or not nb:
            return 0.0
        return max(0.0, sum(x * y for x, y in zip(va, vb, strict=False)) / (na * nb))


def embeddings_configured() -> bool:
    return bool(os.environ.get("EMBEDDINGS_API_KEY", "").strip())


def indexing_status_for_new_document() -> str:
    """`embeddings_not_configured` while no embeddings key exists; otherwise awaiting indexing."""
    return "not_indexed" if embeddings_configured() else "embeddings_not_configured"


def default_scorer() -> SimilarityScorer:
    return TokenOverlapScorer()

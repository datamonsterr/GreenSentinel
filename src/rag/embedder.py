"""Embedding providers used by the policy RAG pipeline."""

from __future__ import annotations

import logging
import math
import os
import time
from collections.abc import Sequence
from typing import Any

from dotenv import load_dotenv
from google import genai
from openai import OpenAI

load_dotenv()

logger = logging.getLogger(__name__)

DEFAULT_EMBED_MODEL = "gemini-embedding-2"
OPENAI_EMBED_MODEL = "text-embedding-3-small"
OPENAI_EMBED_DIMENSIONS = 1536
OPENAI_MAX_BATCH_SIZE = 64
_MOCK_KEYS = {"mock", "test-key", "test"}


class OpenAIEmbedder:
    """OpenAI embeddings with one API request per input batch."""

    provider = "openai"
    dimensions = OPENAI_EMBED_DIMENSIONS

    def __init__(
        self,
        api_key: str | None = None,
        model_name: str = OPENAI_EMBED_MODEL,
        dimensions: int = OPENAI_EMBED_DIMENSIONS,
        timeout: float = 20.0,
        max_retries: int = 2,
        batch_size: int = OPENAI_MAX_BATCH_SIZE,
        client: Any | None = None,
    ) -> None:
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        if model_name != OPENAI_EMBED_MODEL:
            raise ValueError(f"OpenAI RAG requires model={OPENAI_EMBED_MODEL}")
        self.model_name = model_name
        self.dimensions = dimensions
        self.timeout = timeout
        self.max_retries = max_retries
        if batch_size < 1 or batch_size > OPENAI_MAX_BATCH_SIZE:
            raise ValueError(f"batch_size must be between 1 and {OPENAI_MAX_BATCH_SIZE}")
        if dimensions != OPENAI_EMBED_DIMENSIONS:
            raise ValueError(f"{OPENAI_EMBED_MODEL} must use dimensions={OPENAI_EMBED_DIMENSIONS}")
        self.batch_size = batch_size
        self.client = client
        if self.client is None:
            if self.api_key and self.api_key not in _MOCK_KEYS:
                self.client = OpenAI(api_key=self.api_key, timeout=timeout, max_retries=0)

    def embed_batch(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        if self.client is None or self.api_key in _MOCK_KEYS:
            raise RuntimeError("OpenAI embedding service is not configured")
        vectors: list[list[float]] = []
        for start in range(0, len(texts), self.batch_size):
            vectors.extend(self._embed_one_batch(texts[start : start + self.batch_size]))
        return vectors

    def _embed_one_batch(self, texts: Sequence[str]) -> list[list[float]]:
        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                client = self.client
                if client is None:
                    raise RuntimeError("OpenAI embedding service is not configured")
                response = client.embeddings.create(
                    model=self.model_name,
                    input=list(texts),
                    dimensions=self.dimensions,
                )
                data = sorted(response.data, key=lambda item: item.index)
                if len(data) != len(texts):
                    raise ValueError("OpenAI returned an unexpected embedding count")
                if [item.index for item in data] != list(range(len(texts))):
                    raise ValueError("OpenAI returned invalid embedding indexes")
                vectors = [[float(value) for value in item.embedding] for item in data]
                if any(len(vector) != self.dimensions for vector in vectors):
                    raise ValueError("OpenAI returned an unexpected embedding dimension")
                if any(not math.isfinite(value) for vector in vectors for value in vector):
                    raise ValueError("OpenAI returned a non-finite embedding value")
                return vectors
            except Exception as exc:
                last_error = exc
                if isinstance(exc, ValueError):
                    raise
                status = getattr(exc, "status_code", None)
                if status is not None and status < 500 and status != 429:
                    raise
                if attempt >= self.max_retries:
                    raise
                time.sleep(0.25 * (2**attempt))
        raise last_error or RuntimeError("OpenAI embedding failed")

    def embed_text(self, text: str) -> list[float]:
        return self.embed_batch([text])[0]

    def __call__(self, text_or_texts: str | list[str]) -> list[float] | list[list[float]]:
        return self.embed_text(text_or_texts) if isinstance(text_or_texts, str) else self.embed_batch(text_or_texts)


def create_embedder(provider: str | None = None) -> OpenAIEmbedder | GeminiEmbedder:
    selected = (provider or os.getenv("RAG_EMBEDDING_PROVIDER") or "openai").strip().lower()
    if selected == "openai":
        return OpenAIEmbedder()
    if selected == "gemini":
        return GeminiEmbedder()
    raise ValueError(f"Unsupported RAG_EMBEDDING_PROVIDER: {selected}")


class GeminiEmbedder:
    """Embedder using Google Gemini Embedding 2 via google-genai SDK."""

    def __init__(
        self,
        api_key: str | None = None,
        model_name: str = DEFAULT_EMBED_MODEL,
        batch_size: int = 10,
    ) -> None:
        self.api_key = api_key or os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        self.model_name = model_name
        self.batch_size = batch_size
        self.client: genai.Client | None = None
        if self.api_key and self.api_key not in ("mock", "test-key", "test"):
            try:
                self.client = genai.Client(api_key=self.api_key)
            except Exception:
                self.client = None
        else:
            self.client = None

    def embed_text(self, text: str, max_retries: int = 4) -> list[float]:
        """Embed a single text string with exponential backoff retry on transient errors."""
        if not self.client or self.api_key in ("mock", "test-key", "test"):
            raise RuntimeError("Gemini embedding service is not configured")

        last_err: Exception | None = None
        for attempt in range(max_retries):
            try:
                response = self.client.models.embed_content(
                    model=self.model_name,
                    contents=text,
                )
                embeddings = response.embeddings
                values = embeddings[0].values if embeddings else None
                if values is None:
                    raise ValueError("Gemini returned no embedding vector")
                return [float(v) for v in values]
            except Exception as exc:
                last_err = exc
                if attempt == max_retries - 1:
                    logger.warning("Gemini embedding failed after %d attempts", max_retries)
                    raise
                backoff = 1.5**attempt
                time.sleep(backoff)
        if last_err:
            raise last_err
        return []

    def embed_batch(self, texts: Sequence[str]) -> list[list[float]]:
        """Embed a batch of texts with rate-limiting backoff."""
        results: list[list[float]] = []
        for i in range(0, len(texts), self.batch_size):
            batch = texts[i : i + self.batch_size]
            for text in batch:
                try:
                    res = self.embed_text(text)
                    results.append(res)
                except Exception as e:
                    logger.warning("Error embedding text, retrying after backoff: %s", e)
                    time.sleep(1.0)
                    res = self.embed_text(text)
                    results.append(res)
            time.sleep(0.1)
        return results

    def __call__(self, text_or_texts: str | list[str]) -> list[float] | list[list[float]]:
        if isinstance(text_or_texts, str):
            return self.embed_text(text_or_texts)
        return self.embed_batch(text_or_texts)

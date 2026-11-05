"""Qdrant Vector Store client connecting to Qdrant Docker or Qdrant Cloud."""

from __future__ import annotations

import json
import logging
import os
import re
import uuid
from pathlib import Path
from typing import Any

import qdrant_client
from qdrant_client.http.exceptions import UnexpectedResponse
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    FilterSelector,
    MatchValue,
    PayloadSchemaType,
    PointStruct,
    VectorParams,
)

from src.config import get_settings
from src.rag.chunker import Document
from src.rag.embedder import OpenAIEmbedder, create_embedder

logger = logging.getLogger(__name__)

DEFAULT_COLLECTION_NAME = "dev-policies"
DEFAULT_VECTOR_SIZE = 3072
QUERY_STOPWORDS = {
    "what",
    "is",
    "the",
    "to",
    "use",
    "for",
    "and",
    "or",
    "in",
    "on",
    "of",
    "a",
    "an",
    "green",
    "sm",
    "with",
    "by",
    "at",
    "this",
    "that",
    "from",
    "you",
    "your",
    "are",
    "can",
    "how",
    "does",
    "will",
    "should",
    "any",
}


def doc_id_to_point_id(doc_id: str) -> str:
    """Generate a deterministic UUID string from a chunk document ID."""
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, doc_id))


class QdrantPolicyStore:
    """Qdrant Vector Store client for GreenSM policy retrieval.

    Supports Qdrant Cloud, local Docker container, and disk/in-memory fallback.
    """

    def __init__(
        self,
        url: str | None = None,
        api_key: str | None = None,
        host: str | None = None,
        port: int | None = None,
        collection_name: str | None = None,
        embedder: Any | None = None,
        vector_size: int | None = None,
    ) -> None:
        settings = get_settings()
        self.url = url or os.getenv("QDRANT_CLUSTER_URL") or os.getenv("QDRANT_URL") or settings.effective_qdrant_url
        self.api_key = api_key or os.getenv("QDRANT_API_KEY") or settings.effective_qdrant_api_key
        self.host = host or os.getenv("QDRANT_HOST")
        port_env = os.getenv("QDRANT_PORT")
        self.port: int | None = port or (int(port_env) if port_env else None)
        self.collection_name: str = (
            collection_name
            or os.getenv("QDRANT_COLLECTION")
            or settings.effective_qdrant_collection
            or DEFAULT_COLLECTION_NAME
        )
        self.embedder = embedder or create_embedder()
        if isinstance(self.embedder, OpenAIEmbedder) and self.collection_name in {
            "dev-policies",
            "test-policies",
            "prod-policies",
        }:
            # Keep legacy Gemini vectors isolated even when a stale environment
            # variable still names the old collection.
            self.collection_name = f"{self.collection_name}-openai-text-embedding-3-small-1536"
        self.vector_size = vector_size or int(getattr(self.embedder, "dimensions", DEFAULT_VECTOR_SIZE))
        if isinstance(self.embedder, OpenAIEmbedder) and self.vector_size != self.embedder.dimensions:
            raise ValueError("Explicit vector_size must match the OpenAI embedding dimensions")

        self.client = self._init_client()
        self._ensure_collection()
        self.last_search_error: str | None = None

    def _init_client(self) -> qdrant_client.QdrantClient:
        """Initialize Qdrant client with prioritized failover."""
        # 1. Try URL (Docker or Cloud)
        if self.url:
            try:
                logger.info("Attempting connection to Qdrant at %s", self.url)
                # Avoid passing API key over plaintext HTTP localhost to prevent warning
                use_api_key = (
                    self.api_key
                    if (
                        self.api_key
                        and not self.url.startswith("http://localhost")
                        and not self.url.startswith("http://127.0.0.1")
                        and not self.url.startswith("http://qdrant")
                    )
                    else None
                )
                client = qdrant_client.QdrantClient(
                    url=self.url,
                    api_key=use_api_key,
                    timeout=5,
                    check_compatibility=False,
                )
                client.get_collections()
                logger.info("Successfully connected to Qdrant at %s", self.url)
                return client
            except Exception as e:
                logger.warning("Could not connect to Qdrant at %s: %s", self.url, e)

        # 2. Try Host:Port
        if self.host:
            port = self.port or 6333
            try:
                logger.info("Attempting connection to Qdrant at %s:%d", self.host, port)
                client = qdrant_client.QdrantClient(
                    host=self.host,
                    port=port,
                    api_key=self.api_key or None,
                    timeout=5,
                    check_compatibility=False,
                )
                client.get_collections()
                logger.info("Successfully connected to Qdrant at %s:%d", self.host, port)
                return client
            except Exception as e:
                logger.warning("Could not connect to Qdrant at %s:%d: %s", self.host, port, e)

        # 3. Try Local Persistent Storage
        local_path = os.getenv("QDRANT_STORAGE_DIR", "./data/qdrant_storage")
        try:
            os.makedirs(local_path, exist_ok=True)
            logger.info("Falling back to local embedded Qdrant at %s", local_path)
            client = qdrant_client.QdrantClient(path=local_path, check_compatibility=False)
            client.get_collections()
            return client
        except Exception as e:
            logger.warning("Could not initialize local Qdrant at %s: %s", local_path, e)

        # 4. In-Memory Ephemeral Fallback
        logger.warning("Falling back to in-memory ephemeral Qdrant instance")
        return qdrant_client.QdrantClient(":memory:", check_compatibility=False)

    def _get_vector_name(self) -> str | None:
        """Return the named vector key if the collection uses named vectors."""
        try:
            col = self.client.get_collection(self.collection_name)
            vcfg = col.config.params.vectors
            if isinstance(vcfg, dict) and vcfg:
                return next(iter(vcfg.keys()))
        except Exception:
            pass
        return None

    def _ensure_collection(self) -> None:
        """Create collection if it does not already exist with retry."""
        import time

        for attempt in range(5):
            try:
                if not self.client.collection_exists(self.collection_name):
                    logger.info("Creating Qdrant collection '%s' (dim: %d)", self.collection_name, self.vector_size)
                    self.client.create_collection(
                        collection_name=self.collection_name,
                        vectors_config=VectorParams(size=self.vector_size, distance=Distance.COSINE),
                    )
                if self.client.collection_exists(self.collection_name):
                    config = self.client.get_collection(self.collection_name).config.params.vectors
                    configured = getattr(config, "size", None) if config is not None else None
                    if configured is None and isinstance(config, dict):
                        configured = next(iter(config.values())).size if config else None
                    if configured is not None and int(configured) != self.vector_size:
                        raise ValueError(
                            f"Qdrant collection '{self.collection_name}' has vector size {configured}, "
                            f"but embedder requires {self.vector_size}; choose a provider-specific collection or migrate it."
                        )
                    try:
                        import warnings

                        with warnings.catch_warnings():
                            warnings.simplefilter("ignore", UserWarning)
                            self.client.create_payload_index(
                                collection_name=self.collection_name,
                                field_name="category",
                                field_schema=PayloadSchemaType.KEYWORD,
                            )
                    except Exception:
                        pass
                    return
            except ValueError:
                raise
            except Exception as e:
                logger.warning(
                    "Error verifying/creating collection '%s' (attempt %d/5): %s",
                    self.collection_name,
                    attempt + 1,
                    e,
                )
            time.sleep(0.5)
        raise RuntimeError(f"Unable to verify Qdrant collection '{self.collection_name}'")

    def reset_collection(self) -> None:
        """Clear existing collection and recreate fresh."""
        import time

        try:
            if self.client.collection_exists(self.collection_name):
                try:
                    self.client.delete_collection(self.collection_name)
                    for _ in range(10):
                        if not self.client.collection_exists(self.collection_name):
                            break
                        time.sleep(0.3)
                    self._ensure_collection()
                except Exception:
                    # Scoped RBAC API keys cannot delete collection; truncate points instead
                    self.client.delete(
                        collection_name=self.collection_name,
                        points_selector=FilterSelector(filter=Filter()),
                    )
        except Exception as e:
            logger.warning("Error clearing collection during reset: %s", e)
        logger.info("Reset collection '%s'", self.collection_name)

    def add_documents(self, documents: list[Document], batch_size: int = 15) -> int:
        """Add documents and their embeddings to Qdrant in batches."""
        if not documents:
            return self.count()

        self._ensure_collection()
        vec_name = self._get_vector_name()
        total = len(documents)
        logger.info("Ingesting %d documents into Qdrant collection '%s'", total, self.collection_name)

        for i in range(0, total, batch_size):
            batch = documents[i : i + batch_size]
            contents = [doc.content for doc in batch]
            embeddings = self.embedder.embed_batch(contents)
            if len(embeddings) != len(batch):
                raise ValueError(f"Embedder returned {len(embeddings)} vectors for {len(batch)} documents")
            if any(len(vector) != self.vector_size for vector in embeddings):
                raise ValueError(f"Embedder returned a vector with dimension != {self.vector_size}")

            points: list[PointStruct] = []
            for doc, emb in zip(batch, embeddings):
                payload = {
                    "doc_id": doc.id,
                    "content": doc.content,
                    **(doc.metadata or {}),
                }
                points.append(
                    PointStruct(
                        id=doc_id_to_point_id(doc.id),
                        vector={vec_name: emb} if vec_name else emb,
                        payload=payload,
                    )
                )

            try:
                self.client.upsert(collection_name=self.collection_name, points=points)
            except Exception as exc:
                logger.warning(
                    "Upsert batch %d-%d failed, ensuring collection and retrying: %s",
                    i + 1,
                    min(i + batch_size, total),
                    exc,
                )
                self._ensure_collection()
                self.client.upsert(collection_name=self.collection_name, points=points)
            logger.info("Added batch %d-%d / %d to Qdrant", i + 1, min(i + batch_size, total), total)

        return self.count()

    def search(
        self,
        query: str,
        top_k: int = 4,
        where: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Search Qdrant for top_k relevant policy chunks with optional filtering."""
        self.last_search_error = None
        total_count = self.count()
        if total_count == 0:
            if self.collection_name.startswith("test_"):
                return []
            return self._fallback_local_search(query=query, top_k=top_k, where=where)
        try:
            query_embedding = self.embedder.embed_text(query)
        except Exception as exc:
            logger.warning("Policy query embedding unavailable: %s", exc)
            self.last_search_error = "embedding_unavailable"
            if self.collection_name.startswith("test_"):
                return []
            return self._fallback_local_search(query=query, top_k=top_k, where=where)
        fetch_k = min(total_count, max(top_k * 10, 200)) if total_count > 0 else top_k

        query_filter: Filter | None = None
        # S4-TENANT #294 P1a: an organization_id filter is tenant scope, never
        # a hint. Filtered misses fail closed (no unfiltered retry below).
        org_scoped = bool(where and "organization_id" in where)
        if where:
            conditions: list[Any] = []
            for k, v in where.items():
                if isinstance(v, dict) and "$eq" in v:
                    v = v["$eq"]
                conditions.append(FieldCondition(key=k, match=MatchValue(value=v)))
            if conditions:
                query_filter = Filter(must=conditions)

        vec_name = self._get_vector_name()
        query_kwargs: dict[str, Any] = {
            "collection_name": self.collection_name,
            "query": query_embedding,
            "limit": fetch_k,
            "with_payload": True,
        }
        if vec_name:
            query_kwargs["using"] = vec_name
        if query_filter:
            query_kwargs["query_filter"] = query_filter

        try:
            response = self.client.query_points(**query_kwargs)
            points = response.points
        except (UnexpectedResponse, Exception) as exc:
            if org_scoped:
                # S4-TENANT #294 P1a: never retry org-scoped misses unfiltered.
                logger.warning("Qdrant org-scoped query failed (%s), failing closed", exc)
                self.last_search_error = "org_scoped_query_failed"
                return []
            logger.warning("Qdrant query failed with filter (%s), retrying without filter", exc)
            points = []

        if query_filter and not points and not org_scoped:
            # Fallback to unfiltered query if filtered query yielded 0 matches
            try:
                unfiltered_kwargs = dict(query_kwargs)
                unfiltered_kwargs.pop("query_filter", None)
                response = self.client.query_points(**unfiltered_kwargs)
                points = response.points
            except Exception as e:
                logger.error("Qdrant unfiltered query also failed: %s", e)
                points = []

        matches: list[dict[str, Any]] = []
        for rank, p in enumerate(points):
            payload = p.payload or {}
            doc_id = payload.get("doc_id", str(p.id))
            content = payload.get("content", "")
            metadata = {k: v for k, v in payload.items() if k not in ("doc_id", "content")}
            score = float(p.score) if p.score is not None else 0.0
            distance = round(max(0.0, 1.0 - score), 4)

            matches.append(
                {
                    "rank": rank + 1,
                    "id": doc_id,
                    "content": content,
                    "metadata": metadata,
                    "distance": distance,
                    "similarity": round(score, 4),
                }
            )

        # Keyword relevance re-ranking to boost exact keyword matches
        q_tokens = [
            w
            for w in re.findall(r"[a-zA-Z0-9_\u00C0-\u024F\u1EA0-\u1EF9]+", query.lower())
            if len(w) > 1 and w not in QUERY_STOPWORDS
        ]
        if q_tokens:

            def match_score(item: dict[str, Any]) -> int:
                c = (item.get("content", "") + " " + str(item.get("metadata", ""))).lower()
                s = 0
                for tok in q_tokens:
                    if re.search(r"\b" + re.escape(tok) + r"\b", c):
                        s += 10
                    elif tok in c:
                        s += 1
                return s

            matches.sort(key=lambda item: (-match_score(item), item.get("distance", 0.0)))
            for r, m in enumerate(matches):
                m["rank"] = r + 1

        if not matches:
            matches = self._fallback_local_search(query=query, top_k=top_k, where=where)

        return matches[:top_k]

    def _fallback_local_search(
        self,
        query: str,
        top_k: int = 4,
        where: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Fallback keyword search over data/processed markdown files when Qdrant is empty or unavailable."""
        if where and "organization_id" in where:
            # S4-TENANT #294 P1a: the local manifest carries no org payload, so
            # org-scoped searches fail closed instead of leaking shared docs.
            return []
        manifest_paths = [
            Path("data/processed/manifest.json"),
            Path("/home/dat/dev/vinuni_aia/GreenSentinel/data/processed/manifest.json"),
        ]
        manifest_file = next((p for p in manifest_paths if p.is_file()), None)
        if not manifest_file:
            return []

        try:
            items = json.loads(manifest_file.read_text(encoding="utf-8"))
        except Exception:
            return []

        base_dir = manifest_file.parent
        q_tokens = [
            w
            for w in re.findall(r"[a-zA-Z0-9_\u00C0-\u024F\u1EA0-\u1EF9]+", query.lower())
            if len(w) > 1 and w not in QUERY_STOPWORDS
        ]
        # Compile once per request; avoid repeating regex construction for each
        # paragraph while preserving exact word-boundary matching.
        token_patterns = [(tok, re.compile(r"\b" + re.escape(tok) + r"\b")) for tok in q_tokens]

        cat_filter = None
        if where and "category" in where:
            cat_filter = str(where["category"]).lower()

        candidates: list[tuple[int, dict[str, Any]]] = []
        for item in items:
            item_cat = str(item.get("category", "")).lower()
            if cat_filter and cat_filter != "all" and cat_filter != item_cat:
                continue

            slug = item.get("slug")
            doc_file = base_dir / f"{slug}.md"
            if not doc_file.is_file():
                continue

            try:
                content = doc_file.read_text(encoding="utf-8")
            except Exception:
                continue

            paragraphs = [p.strip() for p in re.split(r"\n\s*\n", content) if len(p.strip()) > 30]
            for idx, para in enumerate(paragraphs):
                para_lower = para.lower()
                score = 0
                for tok, token_pattern in token_patterns:
                    if token_pattern.search(para_lower):
                        score += 10
                    elif tok in para_lower:
                        score += 2

                title_lower = str(item.get("title", "")).lower()
                for tok in q_tokens:
                    if tok in title_lower:
                        score += 5

                if score > 0 or not q_tokens:
                    candidates.append(
                        (
                            score,
                            {
                                "id": f"{item.get('id', slug)}#sec_{idx}",
                                "content": para[:1000],
                                "metadata": {
                                    "title": item.get("title", slug),
                                    "category": item.get("category", "general"),
                                    "source_url": item.get("source_url", ""),
                                    "doc_id": item.get("id", slug),
                                },
                                "distance": round(max(0.01, 1.0 - (score / 100.0)), 4),
                                "similarity": round(min(0.99, score / 100.0), 4),
                            },
                        )
                    )

        candidates.sort(key=lambda x: -x[0])
        results = [c[1] for c in candidates[:top_k]]
        for r, res in enumerate(results):
            res["rank"] = r + 1
        return results

    def count(self) -> int:
        """Get number of items in collection."""
        try:
            res = self.client.count(collection_name=self.collection_name, exact=True)
            return int(res.count)
        except Exception as exc:
            logger.warning("Error getting collection count: %s", exc)
            return 0


# Backwards compatibility alias
ChromaPolicyStore = QdrantPolicyStore

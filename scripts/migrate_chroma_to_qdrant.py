#!/usr/bin/env python3
"""Reusable script to migrate vector collections and documents from ChromaDB to Qdrant.

Usage:
    # Migrate using defaults (local Chroma -> local Qdrant)
    python scripts/migrate_chroma_to_qdrant.py

    # Migrate to Qdrant Cloud
    python scripts/migrate_chroma_to_qdrant.py \
        --qdrant-url "https://<cluster-id>.<region>.cloud.qdrant.io:6333" \
        --qdrant-api-key "eyJhbG..." \
        --collection "greensm_policies"
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import uuid
from typing import Any

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("chroma_to_qdrant")


def doc_id_to_point_id(doc_id: str) -> str:
    """Deterministically convert string ID into UUIDv5."""
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, doc_id))


def migrate_collection(
    chroma_host: str = "localhost",
    chroma_port: int = 8001,
    chroma_persist_dir: str | None = None,
    qdrant_url: str = "http://localhost:6333",
    qdrant_api_key: str | None = None,
    collection_name: str = "greensm_policies",
    batch_size: int = 50,
    recreate_qdrant_collection: bool = False,
) -> int:
    """Migrate documents and vectors from ChromaDB to Qdrant."""
    try:
        import chromadb
    except ImportError:
        logger.error("chromadb is not installed. Run 'pip install chromadb' first.")
        sys.exit(1)

    try:
        import qdrant_client
        from qdrant_client.models import Distance, PointStruct, VectorParams
    except ImportError:
        logger.error("qdrant-client is not installed. Run 'pip install qdrant-client' first.")
        sys.exit(1)

    # 1. Connect to ChromaDB
    logger.info(
        "Connecting to source ChromaDB (host=%s, port=%s, persist_dir=%s)...",
        chroma_host,
        chroma_port,
        chroma_persist_dir,
    )
    chroma_client = None
    chroma_col = None

    try:
        chroma_client = chromadb.HttpClient(host=chroma_host, port=chroma_port)
        chroma_col = chroma_client.get_collection(collection_name)
        total_chroma = chroma_col.count()
        logger.info(
            "Connected to ChromaDB HttpClient: found collection '%s' with %d items.", collection_name, total_chroma
        )
    except Exception as exc:
        logger.warning("HttpClient connection failed (%s), attempting PersistentClient...", exc)
        if chroma_persist_dir and os.path.isdir(chroma_persist_dir):
            try:
                chroma_client = chromadb.PersistentClient(path=chroma_persist_dir)
                chroma_col = chroma_client.get_collection(collection_name)
                total_chroma = chroma_col.count()
                logger.info("Connected to ChromaDB PersistentClient: found %d items.", total_chroma)
            except Exception as e2:
                logger.error("Failed to read from Chroma PersistentClient: %s", e2)

    if not chroma_col or chroma_col.count() == 0:
        logger.warning(
            "No records found in ChromaDB collection '%s'. Checking if RAG ingest can seed directly.", collection_name
        )
        from src.rag.ingest import ingest_policies_to_qdrant

        return ingest_policies_to_qdrant()

    # 2. Connect to Qdrant
    use_api_key = (
        qdrant_api_key
        if (
            qdrant_api_key
            and not qdrant_url.startswith("http://localhost")
            and not qdrant_url.startswith("http://127.0.0.1")
        )
        else None
    )

    logger.info("Connecting to destination Qdrant at %s...", qdrant_url)
    qdrant = qdrant_client.QdrantClient(
        url=qdrant_url,
        api_key=use_api_key,
        timeout=10,
        check_compatibility=False,
    )

    # 3. Read data from Chroma
    logger.info("Fetching data from Chroma collection '%s'...", collection_name)
    chroma_data = chroma_col.get(include=["documents", "metadatas", "embeddings"])

    ids: list[str] = chroma_data.get("ids", [])
    documents: list[str] = chroma_data.get("documents", [])
    metadatas: list[dict[str, Any]] = chroma_data.get("metadatas", [])
    embeddings: list[list[float]] = chroma_data.get("embeddings", [])

    total = len(ids)
    if total == 0:
        logger.warning("Chroma collection '%s' is empty. Nothing to migrate.", collection_name)
        return 0

    vector_dim = len(embeddings[0]) if (embeddings is not None and len(embeddings) > 0) else 3072
    logger.info("Retrieved %d items from Chroma. Detected vector dimension: %d", total, vector_dim)

    # 4. Prepare Qdrant Collection
    if recreate_qdrant_collection:
        try:
            qdrant.delete_collection(collection_name)
            logger.info("Deleted existing Qdrant collection '%s'.", collection_name)
        except Exception:
            pass

    if not qdrant.collection_exists(collection_name):
        logger.info("Creating Qdrant collection '%s' (dim=%d, distance=COSINE)...", collection_name, vector_dim)
        qdrant.create_collection(
            collection_name=collection_name,
            vectors_config=VectorParams(size=vector_dim, distance=Distance.COSINE),
        )

    # 5. Batch upsert into Qdrant
    logger.info("Migrating %d vectors into Qdrant in batches of %d...", total, batch_size)
    migrated_count = 0

    for i in range(0, total, batch_size):
        b_ids = ids[i : i + batch_size]
        b_docs = documents[i : i + batch_size]
        b_meta = metadatas[i : i + batch_size]
        b_embs = embeddings[i : i + batch_size]

        points: list[PointStruct] = []
        for d_id, doc_text, meta, emb in zip(b_ids, b_docs, b_meta, b_embs):
            payload = {
                "doc_id": d_id,
                "content": doc_text,
                **(meta or {}),
            }
            points.append(
                PointStruct(
                    id=doc_id_to_point_id(d_id),
                    vector=emb,
                    payload=payload,
                )
            )

        qdrant.upsert(collection_name=collection_name, points=points)
        migrated_count += len(points)
        logger.info("Migrated batch %d-%d / %d to Qdrant", i + 1, min(i + batch_size, total), total)

    final_count = qdrant.count(collection_name=collection_name, exact=True).count
    logger.info("Migration successful! Qdrant collection '%s' points count: %d", collection_name, final_count)
    return final_count


def main() -> None:
    parser = argparse.ArgumentParser(description="Migrate embeddings and documents from ChromaDB to Qdrant.")
    parser.add_argument("--chroma-host", default=os.getenv("CHROMA_HOST", "localhost"), help="ChromaDB host")
    parser.add_argument("--chroma-port", type=int, default=int(os.getenv("CHROMA_PORT", "8001")), help="ChromaDB port")
    parser.add_argument(
        "--chroma-dir", default=os.getenv("CHROMA_PERSIST_DIR", "./data/chroma"), help="Chroma persist dir"
    )
    parser.add_argument("--qdrant-url", default=os.getenv("QDRANT_URL", "http://localhost:6333"), help="Qdrant URL")
    parser.add_argument("--qdrant-api-key", default=os.getenv("QDRANT_API_KEY", ""), help="Qdrant API Key")
    parser.add_argument(
        "--collection", default=os.getenv("QDRANT_COLLECTION", "greensm_policies"), help="Collection name"
    )
    parser.add_argument("--batch-size", type=int, default=50, help="Batch size for upserts")
    parser.add_argument(
        "--recreate",
        action="store_true",
        default=False,
        help="Explicitly drop and recreate Qdrant collection before migrating (default: False, safe incremental upsert)",
    )

    args = parser.parse_args()

    count = migrate_collection(
        chroma_host=args.chroma_host,
        chroma_port=args.chroma_port,
        chroma_persist_dir=args.chroma_dir,
        qdrant_url=args.qdrant_url,
        qdrant_api_key=args.qdrant_api_key or None,
        collection_name=args.collection,
        batch_size=args.batch_size,
        recreate_qdrant_collection=args.recreate,
    )
    print(f"\n[DONE] Successfully migrated {count} points to Qdrant collection '{args.collection}'.")


if __name__ == "__main__":
    main()

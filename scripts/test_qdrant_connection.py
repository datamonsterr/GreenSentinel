#!/usr/bin/env python3
"""Reusable script to verify Qdrant connectivity, inspect collections, and test vector search.

Usage:
    # Test local Docker instance
    python scripts/test_qdrant_connection.py

    # Test Qdrant Cloud cluster
    python scripts/test_qdrant_connection.py \
        --url "https://<cluster-id>.<region>.cloud.qdrant.io:6333" \
        --api-key "eyJhbG..."
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("qdrant_test")


def test_qdrant(
    url: str | None = None,
    api_key: str | None = None,
    collection_name: str = "greensm_policies",
) -> bool:
    try:
        import qdrant_client
    except ImportError:
        logger.error("qdrant-client not installed. Run 'pip install qdrant-client'.")
        return False

    target_url = url or os.getenv("QDRANT_URL", "http://localhost:6333")
    target_api_key = api_key or os.getenv("QDRANT_API_KEY", "")

    use_api_key = (
        target_api_key
        if (
            target_api_key
            and not target_url.startswith("http://localhost")
            and not target_url.startswith("http://127.0.0.1")
        )
        else None
    )

    logger.info("Connecting to Qdrant at %s...", target_url)
    start_t = time.perf_counter()

    try:
        client = qdrant_client.QdrantClient(
            url=target_url,
            api_key=use_api_key,
            timeout=10,
            check_compatibility=False,
        )
        cols = client.get_collections().collections
        latency_ms = (time.perf_counter() - start_t) * 1000
        logger.info("Connected successfully in %.2f ms!", latency_ms)
        logger.info("Available collections (%d): %s", len(cols), [c.name for c in cols])

        if client.collection_exists(collection_name):
            col_info = client.get_collection(collection_name)
            points_count = client.count(collection_name, exact=True).count
            logger.info("Collection '%s' info:", collection_name)
            logger.info(" - Points count: %d", points_count)
            logger.info(" - Vectors count: %s", getattr(col_info, "vectors_count", "N/A"))
            logger.info(" - Status: %s", getattr(col_info, "status", "N/A"))

            # Test search using QdrantPolicyStore
            from src.rag.store import QdrantPolicyStore

            store = QdrantPolicyStore(
                url=target_url,
                api_key=target_api_key,
                collection_name=collection_name,
            )
            sample_query = "VAT invoice bồi thường"
            logger.info("Executing sample search query: '%s'...", sample_query)
            results = store.search(sample_query, top_k=2)
            logger.info("Search returned %d results:", len(results))
            for r in results:
                logger.info(
                    " [Rank %d] (Sim: %.4f) ID: %s | Content: %s...",
                    r["rank"],
                    r["similarity"],
                    r["id"],
                    r["content"][:80],
                )

        else:
            logger.warning("Collection '%s' does not exist yet. Run ingest to populate.", collection_name)

        return True

    except Exception as exc:
        logger.error("Failed to connect or query Qdrant at %s: %s", target_url, exc)
        return False


def main() -> None:
    parser = argparse.ArgumentParser(description="Test connection to Qdrant Docker or Qdrant Cloud.")
    parser.add_argument("--url", default=os.getenv("QDRANT_URL"), help="Qdrant endpoint URL")
    parser.add_argument("--api-key", default=os.getenv("QDRANT_API_KEY"), help="Qdrant API Key")
    parser.add_argument(
        "--collection", default=os.getenv("QDRANT_COLLECTION", "greensm_policies"), help="Collection name"
    )

    args = parser.parse_args()
    success = test_qdrant(
        url=args.url,
        api_key=args.api_key,
        collection_name=args.collection,
    )
    if not success:
        sys.exit(1)


if __name__ == "__main__":
    main()

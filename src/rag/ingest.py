"""Pipeline to chunk crawled GreenSM policies and index them into Qdrant."""

import json
import logging
import sys
from pathlib import Path

from dotenv import load_dotenv

# Ensure repository root is in sys.path
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from src.rag.chunker import Document, RecursiveChunker  # noqa: E402
from src.rag.embedder import create_embedder  # noqa: E402
from src.rag.store import QdrantPolicyStore  # noqa: E402

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


def ingest_policies_to_qdrant(
    processed_dir: Path = Path("data/processed"),
    chunk_size: int = 700,
    chunk_overlap: int = 100,
) -> int:
    """Read processed policy markdown files, chunk recursively, and index to Qdrant."""
    manifest_file = processed_dir / "manifest.json"
    if not manifest_file.exists():
        raise FileNotFoundError(f"Manifest not found at {manifest_file}. Run crawler first.")

    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    chunker = RecursiveChunker(chunk_size=chunk_size, chunk_overlap=chunk_overlap)
    all_chunks: list[Document] = []

    logger.info("Starting chunking for %d policy documents...", len(manifest))

    for item in manifest:
        slug = item["slug"]
        md_file = processed_dir / f"{slug}.md"
        if not md_file.exists():
            continue

        raw_text = md_file.read_text(encoding="utf-8")
        # Remove frontmatter if present
        if raw_text.startswith("---"):
            parts = raw_text.split("---", 2)
            if len(parts) >= 3:
                raw_text = parts[2].strip()

        base_meta = {
            "policy_id": item["id"],
            "title": item["title"],
            "category": item["category"],
            "slug": item["slug"],
            "source_url": item["source_url"],
        }

        chunks = chunker.split_document(
            doc_id=item["id"],
            content=raw_text,
            base_metadata=base_meta,
        )
        logger.info("Document '%s' produced %d chunks", item["slug"], len(chunks))
        all_chunks.extend(chunks)

    logger.info("Total chunks across all policies: %d", len(all_chunks))

    # Ingest into Qdrant
    embedder = create_embedder()
    # Fail before touching Qdrant. A missing/invalid provider key must never
    # wipe an existing shared collection.
    embedder.embed_batch(["embedding provider preflight"])
    store = QdrantPolicyStore(embedder=embedder)
    count = store.add_documents(all_chunks, batch_size=64)
    logger.info("Ingestion completed! Total vectors in Qdrant: %d", count)
    return count


if __name__ == "__main__":
    count = ingest_policies_to_qdrant()
    print(f"Successfully ingested {count} chunks into Qdrant.")

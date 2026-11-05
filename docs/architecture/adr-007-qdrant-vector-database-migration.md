# ADR-007: Migration from ChromaDB to Qdrant Vector Search Engine

## Status

Accepted

## Context

The GreenSM Cockpit RAG pipeline initially used ChromaDB for local vector storage of terms of service, passenger ride policies, and driver sanction rules. While ChromaDB offered minimal setup for early prototyping, scaling into production environments, CI/CD evaluation suites, and multi-tenant cloud deployments revealed several operational constraints:

1. **Deployment Flexibility**: ChromaDB's client/server protocol and persistence model had synchronization challenges across ephemeral CI runner environments and cloud container clusters.
2. **Production Scalability**: Qdrant provides native gRPC/REST APIs, memory-mapped vector indexes (HNSW with scalar quantization), high-performance payload indexing, and first-class managed cloud hosting (Qdrant Cloud).
3. **Multi-Environment Unified SDK**: Need a unified Python vector store interface that seamlessly operates across:
   - Local Docker container (`http://localhost:6333` / `http://qdrant:6333` in Docker Compose).
   - Qdrant Cloud managed clusters (TLS + API key authentication).
   - Embedded local storage (`./data/qdrant_storage`) or in-memory (`:memory:`) for offline testing and CI runners without network overhead.

## Decision

Migrate the policy vector store layer (`src/rag/store.py`, `src/rag/agent.py`, `src/rag/cockpit_agent.py`, `src/rag/ingest.py`) from ChromaDB to **Qdrant** (`qdrant-client` SDK).

### Core Components

1. **`QdrantPolicyStore`**:
   - Replaces `ChromaPolicyStore` as primary retrieval store.
   - Retains backward compatibility alias `ChromaPolicyStore = QdrantPolicyStore`.
   - Supports 4-tier connection fallback: `url` -> `host:port` -> local embedded disk (`./data/qdrant_storage`) -> `:memory:`.
   - Integrates Gemini Embedding 2 (`gemini-embedding-2`, 3072 dimensions, Cosine distance).
   - Preserves hybrid search behavior with metadata payload filtering (`category`, `source_url`, `doc_id`) and BM25-style keyword boosting.

2. **Docker Compose & Container Topology**:
   - Added `qdrant` service (`image: qdrant/qdrant:latest`) exposing port `6333` (HTTP) and `6334` (gRPC).
   - Persistent volume mounted at `./data/qdrant_storage:/qdrant/storage`.
   - Healthcheck: TCP ping on port 6333.
   - Updated `backend` and `agent` services to depend on healthy `qdrant`.

3. **Reusable Automation Scripts**:
   - `scripts/migrate_chroma_to_qdrant.py`: Batched migration tool reading points, metadata, and embeddings from ChromaDB and ingesting into Qdrant.
   - `scripts/test_qdrant_connection.py`: CLI connectivity diagnostic, latency measurement, collection inspector, and sample search verifier.
   - `src/rag/ingest.py`: Chunking and direct indexing pipeline for 380+ policy chunks.

4. **CI/CD Integration**:
   - Updated `.github/workflows/ci.yml` and `.github/workflows/ci_rag.yml` with Qdrant service containerization, dependencies (`qdrant-client`), and environment variables (`QDRANT_URL`, `QDRANT_API_KEY`, `QDRANT_COLLECTION`).

5. **Agent Skills Installation**:
   - Installed 13 official Qdrant skills into `.agents/jev_skills/` (`qdrant-clients-sdk`, `qdrant-deployment-options`, `qdrant-search-quality`, etc.) and synchronized across agent harnesses.

## Consequences

- Full compatibility with both local Docker development and Qdrant Cloud production clusters.
- Zero breaking changes to existing agent tools or API consumers (`search_policy_documents` returns identical payload structure).
- 100% test passing rate across integration and unit suites.

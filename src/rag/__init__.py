"""RAG module for policy search, document retrieval, and read-only database tools."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.rag.agent import PolicyRAGAgent
    from src.rag.chunker import RecursiveChunker
    from src.rag.cockpit_agent import CockpitRAGAgent
    from src.rag.db_tools import (
        get_audit_log,
        get_case_information,
        get_case_list_priority,
        get_driver_profile,
        get_telemetry,
    )
    from src.rag.embedder import GeminiEmbedder, OpenAIEmbedder, create_embedder
    from src.rag.store import QdrantPolicyStore
    from src.rag.store import QdrantPolicyStore as ChromaPolicyStore

__all__ = [
    "PolicyRAGAgent",
    "CockpitRAGAgent",
    "QdrantPolicyStore",
    "ChromaPolicyStore",
    "GeminiEmbedder",
    "OpenAIEmbedder",
    "create_embedder",
    "RecursiveChunker",
    "get_case_information",
    "get_driver_profile",
    "get_telemetry",
    "get_case_list_priority",
    "get_audit_log",
]


def __getattr__(name: str):
    if name == "PolicyRAGAgent":
        from src.rag.agent import PolicyRAGAgent

        return PolicyRAGAgent
    if name == "CockpitRAGAgent":
        from src.rag.cockpit_agent import CockpitRAGAgent

        return CockpitRAGAgent
    if name in ("QdrantPolicyStore", "ChromaPolicyStore"):
        from src.rag.store import QdrantPolicyStore

        return QdrantPolicyStore
    if name == "GeminiEmbedder":
        from src.rag.embedder import GeminiEmbedder

        return GeminiEmbedder
    if name in ("OpenAIEmbedder", "create_embedder"):
        from src.rag.embedder import OpenAIEmbedder, create_embedder

        return OpenAIEmbedder if name == "OpenAIEmbedder" else create_embedder
    if name == "RecursiveChunker":
        from src.rag.chunker import RecursiveChunker

        return RecursiveChunker
    if name in (
        "get_case_information",
        "get_driver_profile",
        "get_telemetry",
        "get_case_list_priority",
        "get_audit_log",
    ):
        import src.rag.db_tools as db_tools

        return getattr(db_tools, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

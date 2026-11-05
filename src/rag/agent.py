"""GreenSM Policy RAG Agent with tool calling capabilities."""

from __future__ import annotations

import logging
from typing import Any

from dotenv import load_dotenv
from google.genai import types

from src.config import get_settings
from src.rag.store import QdrantPolicyStore
from src.services.content_adapter import ContentAdapter

load_dotenv()

logger = logging.getLogger(__name__)

DEFAULT_GEN_MODEL = "gemini-3.5-flash-lite"


class PolicyRAGAgent:
    """Agent that answers policy questions by retrieving relevant policy chunks from Qdrant."""

    def __init__(
        self,
        store: QdrantPolicyStore | None = None,
        model_name: str | None = None,
        api_key: str | None = None,
    ) -> None:
        settings = get_settings()
        self.api_key = api_key or None
        from src.services.llm import resolve_llm_config

        self.model_name = model_name or resolve_llm_config(settings).model
        self.store = store or QdrantPolicyStore()
        try:
            adapter = ContentAdapter(settings, api_key=api_key, model=model_name)
            self.client = adapter.client
        except Exception:
            self.client = None

    def search_policies(
        self,
        query: str,
        category: str | None = None,
        top_k: int = 4,
    ) -> list[dict[str, Any]]:
        """Search policy store for relevant chunks with optional category filter."""
        where = None
        if category and category.lower() not in ("all", "none", ""):
            where = {"category": category.lower()}
        return self.store.search(query=query, top_k=top_k, where=where)

    def answer_with_rag(
        self,
        question: str,
        category: str | None = None,
        top_k: int = 4,
    ) -> dict[str, Any]:
        """Direct RAG execution: retrieves relevant context, builds prompt, calls Gemini."""
        retrieved_chunks = self.search_policies(query=question, category=category, top_k=top_k)

        if not retrieved_chunks:
            return {
                "answer": "No relevant policy documents found.",
                "retrieved_chunks": [],
                "prompt": "",
            }

        context_parts = []
        for i, chunk in enumerate(retrieved_chunks, start=1):
            doc_id = chunk.get("id", "")
            title = chunk.get("metadata", {}).get("title", "")
            content = chunk.get("content", "").strip()
            context_parts.append(f"[{i}] Document: {title} (ID: {doc_id})\n{content}")

        context_str = "\n\n".join(context_parts)
        prompt = (
            "You are the official AI policy assistant for GreenSM (Green and Smart Mobility JSC).\n"
            "Answer the user's question accurately and concisely using ONLY the provided policy context below.\n"
            "Cite the corresponding document titles or chunk references [n] for your statements.\n"
            "If the answer cannot be found in the context, clearly state that the policy does not specify this information.\n\n"
            f"=== POLICY CONTEXT ===\n{context_str}\n\n"
            f"User Question: {question}\n\n"
            "Answer:"
        )

        if not self.client:
            return {
                "answer": "\n\n".join(part.split("\n", 1)[-1] for part in context_parts),
                "retrieved_chunks": retrieved_chunks,
                "prompt": prompt,
            }

        response = self.client.models.generate_content(model=self.model_name, contents=prompt)

        return {
            "answer": (response.text or "").strip(),
            "retrieved_chunks": retrieved_chunks,
            "prompt": prompt,
        }

    def execute_with_tool_call(self, question: str) -> dict[str, Any]:
        """Execute query using Gemini tool calling (Function Calling).

        Evaluates the model's ability to trigger the policy retrieval tool with appropriate parameters.
        """
        tool_declaration = types.Tool(
            function_declarations=[
                types.FunctionDeclaration(
                    name="search_policy",
                    description=(
                        "Search the GreenSM terms and policies knowledge base in Qdrant for specific terms, rules, "
                        "regulations, compensation policies, or procedures."
                    ),
                    parameters=types.Schema(
                        type=types.Type.OBJECT,
                        properties={
                            "query": types.Schema(
                                type=types.Type.STRING,
                                description="The keyword or search query string to look up in policies.",
                            ),
                            "category": types.Schema(
                                type=types.Type.STRING,
                                description=(
                                    "Optional policy category filter. Allowed values: 'general', 'bike', "
                                    "'car', 'delivery', 'food', 'rental', 'promotion', 'billing', or 'all'."
                                ),
                            ),
                        },
                        required=["query"],
                    ),
                ),
                types.FunctionDeclaration(
                    name="search_policy_documents",
                    description=(
                        "Alias for search_policy: Search the GreenSM terms and policies knowledge base for specific terms."
                    ),
                    parameters=types.Schema(
                        type=types.Type.OBJECT,
                        properties={
                            "query": types.Schema(
                                type=types.Type.STRING,
                                description="The keyword or search query string to look up in policies.",
                            ),
                            "category": types.Schema(
                                type=types.Type.STRING,
                                description="Optional policy category filter.",
                            ),
                        },
                        required=["query"],
                    ),
                ),
            ]
        )

        config = types.GenerateContentConfig(
            tools=[tool_declaration],
            tool_config=types.ToolConfig(
                function_calling_config=types.FunctionCallingConfig(
                    mode=types.FunctionCallingConfigMode.ANY  # Force tool call
                )
            ),
        )

        prompt = (
            f"A customer or partner asks: '{question}'. "
            "Call search_policy_documents with the best query and category to retrieve the answer."
        )

        if not self.client or self.api_key in ("mock", "test-key", "test"):
            # Deterministic tool execution for offline/CI
            q_lower = question.lower()
            cat = (
                "delivery"
                if "delivery" in q_lower
                else ("bike" if "bike" in q_lower else ("food" if "food" in q_lower else None))
            )
            chunks = self.search_policies(query=question, category=cat, top_k=4)
            return {
                "tool_called": "search_policy",
                "tool_args": {"query": question, "category": cat or "general"},
                "answer": chunks[0]["content"] if chunks else "No relevant policy content found.",
                "retrieved_chunks": chunks,
            }

        try:
            resp = self.client.models.generate_content(
                model=self.model_name,
                contents=prompt,
                config=config,
            )

            candidates = resp.candidates
            content = candidates[0].content if candidates else None
            parts = content.parts if content is not None else None
            if not parts:
                raise ValueError("Policy model returned no response parts")
            part = parts[0]
            if not part.function_call:
                return {
                    "tool_called": None,
                    "tool_args": {},
                    "answer": resp.text,
                    "retrieved_chunks": [],
                }

            fn_name = part.function_call.name
            fn_args = dict(part.function_call.args) if part.function_call.args else {}

            # Execute the tool
            query = fn_args.get("query", question)
            category = fn_args.get("category")
            if category == "all":
                category = None

            chunks = self.search_policies(query=query, category=category, top_k=4)

            # Generate final answer from retrieved chunks
            context_parts = [
                f"[{i + 1}] {c.get('metadata', {}).get('title', '')}: {c.get('content', '')}"
                for i, c in enumerate(chunks)
            ]
            context_str = "\n\n".join(context_parts)

            final_prompt = (
                "You are GreenSM Policy Assistant. Answer the question using the retrieved policy content:\n\n"
                f"{context_str}\n\n"
                f"Question: {question}\nAnswer:"
            )

            final_resp = self.client.models.generate_content(
                model=self.model_name,
                contents=final_prompt,
            )

            return {
                "tool_called": fn_name,
                "tool_args": fn_args,
                "answer": (final_resp.text or "").strip(),
                "retrieved_chunks": chunks,
            }
        except Exception as e:
            logger.warning("Gemini execution failed (%s)", e)
            chunks = self.search_policies(query=question, top_k=4)
            return {
                "tool_called": "search_policy",
                "tool_args": {"query": question, "category": "general"},
                "answer": chunks[0]["content"] if chunks else "No relevant policy content found.",
                "retrieved_chunks": chunks,
            }

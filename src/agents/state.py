from __future__ import annotations

from typing import Annotated, Any, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages


class AgentState(TypedDict, total=False):
    """State schema for LangGraph agent.

    Each node reads from and writes to this shared state.
    total=False allows all fields to be optional.
    """

    system_prompt: str
    case_id: str | None
    query: str
    context: str
    analysis: str
    response: str
    error: str
    used_fallback: bool
    metadata: dict[str, Any]
    messages: Annotated[list[BaseMessage], add_messages]
    runtime_context: dict[str, Any]
    case_context: dict[str, Any]

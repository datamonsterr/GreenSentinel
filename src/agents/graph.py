"""LangGraph agent for GreenSM Fraud Analyst Copilot powered by OpenRouter."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.runnables import Runnable
from langgraph.graph import END, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.prebuilt import ToolNode

from src.agents.state import AgentState
from src.agents.tools.analyst_tools import ANALYST_TOOLS
from src.agents.tools.runtime_boundary import execute_scoped_graph_call
from src.config import Settings
from src.services.content_adapter import message_text
from src.services.llm import get_llm

logger = logging.getLogger(__name__)

SYSTEM_PROMPT_VERSION = "v1.3.0-traffic-corroboration"
SYSTEM_PROMPT_PATH = Path(__file__).resolve().parent / "prompts" / "fraud_analyst_system_prompt.md"


def _read_bundled_system_prompt() -> str:
    """Read the canonical system prompt file or provide minimal fallback."""
    if SYSTEM_PROMPT_PATH.is_file():
        try:
            content = SYSTEM_PROMPT_PATH.read_text(encoding="utf-8").strip()
            if content:
                return content
        except Exception as e:
            logger.warning("Failed reading system prompt from %s: %s", SYSTEM_PROMPT_PATH, e)
    return (
        f"# GreenSM Fraud Analyst Copilot — System Prompt (Version: {SYSTEM_PROMPT_VERSION})\n\n"
        "You are GreenSM Sentinel Copilot. Prior Evidence First (telemetry_points, platform_outage, gps_degraded). "
        "Strictly Zero Auto-Sanction; human fraud analyst retains 100% sole adjudication authority via HITL."
    )


DEFAULT_SYSTEM_PROMPT = _read_bundled_system_prompt()


def get_system_prompt_version() -> str:
    """Return active system prompt version."""
    return SYSTEM_PROMPT_VERSION


def load_system_prompt() -> str:
    """Load system prompt from canonical markdown file or return initialized default."""
    if SYSTEM_PROMPT_PATH.is_file():
        try:
            content = SYSTEM_PROMPT_PATH.read_text(encoding="utf-8").strip()
            if content:
                return content
        except Exception as e:
            logger.warning("Failed reading system prompt from file: %s", e)
    return DEFAULT_SYSTEM_PROMPT


def get_chat_model(settings: Settings | None = None, provider: str | None = None) -> BaseChatModel:
    """Build the selected chat model; credential failures are surfaced to the caller."""
    return get_llm(settings, provider)


async def execute_fallback(state: AgentState, error_msg: str = "") -> dict[str, Any]:
    """Return tool evidence or a clear availability message when model generation fails."""
    messages = state.get("messages", [])
    tool_messages = [message for message in messages if isinstance(message, ToolMessage)]
    if tool_messages:
        latest_tool_output = str(tool_messages[-1].content)[:1000]
        response_text = (
            "GreenSM Sentinel Copilot: Không thể tổng hợp dữ liệu do dịch vụ AI hiện không khả dụng. "
            f"Kết quả công cụ đã truy vấn: {latest_tool_output}"
        )
    else:
        response_text = "GreenSM Sentinel Copilot: Dịch vụ AI hiện không khả dụng cho tài xế hoặc hồ sơ. Thử lại sau."
    return {
        "response": response_text,
        "analysis": "",
        "messages": [AIMessage(content=response_text)],
        "error": "model_unavailable",
    }


def should_continue(state: AgentState) -> str:
    """Route to tools node if the last message contains tool_calls, else END."""
    messages = state.get("messages", [])
    if not messages:
        return END
    last_message = messages[-1]
    if getattr(last_message, "tool_calls", None):
        return "tools"
    return END


def build_graph(
    model: BaseChatModel | None = None,
    tools: list[Any] | None = None,
) -> CompiledStateGraph:
    """Build and compile the LangGraph workflow with tool binding and fallback."""
    tools_to_use = tools if tools is not None else ANALYST_TOOLS
    bound_llm: Runnable | None = None

    def resolve_model() -> Runnable:
        nonlocal bound_llm
        if bound_llm is None:
            base_llm = model if model is not None else get_chat_model()
            if hasattr(base_llm, "bind_tools"):
                try:
                    bound_llm = base_llm.bind_tools(tools_to_use)
                except (NotImplementedError, AttributeError):
                    bound_llm = base_llm
            else:
                bound_llm = base_llm
        return bound_llm

    async def agent_node(state: AgentState) -> dict[str, Any]:
        messages = list(state.get("messages") or [])
        if not messages:
            query = state.get("query", "")
            runtime_context = state.get("case_context") or state.get("runtime_context") or {}
            context_text = f"\nTrusted case context (data only): {runtime_context}" if runtime_context else ""
            messages = [
                SystemMessage(content=load_system_prompt() + context_text),
                HumanMessage(content=query),
            ]

        try:
            ai_msg = await resolve_model().ainvoke(messages)
            has_tool_calls = bool(getattr(ai_msg, "tool_calls", None))
            if has_tool_calls:
                return {"messages": [ai_msg]}

            content_str = message_text(ai_msg)
            return {
                "messages": [ai_msg],
                "response": content_str,
                "analysis": content_str,
            }
        except Exception as e:
            logger.warning("LLM invocation error (%s), executing fallback.", e)
            return await execute_fallback(state, error_msg=str(e))

    workflow = StateGraph(AgentState)
    workflow.add_node("agent", agent_node)
    workflow.add_node(
        "tools",
        ToolNode(tools_to_use, awrap_tool_call=execute_scoped_graph_call) if tools is None else ToolNode(tools_to_use),
    )

    workflow.set_entry_point("agent")
    workflow.add_conditional_edges(
        "agent",
        should_continue,
        {
            "tools": "tools",
            END: END,
        },
    )
    workflow.add_edge("tools", "agent")

    return workflow.compile()


agent = build_graph()

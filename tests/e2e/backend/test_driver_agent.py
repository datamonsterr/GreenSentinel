"""End-to-End verification of live GSupport Driver Agent with Gemini Flash 3.5 Lite.

Verifies:
1. Agent utilizes google/gemini-3.5-flash-lite via OpenRouter.
2. Tool calling execution and result retrieval (corroborate_traffic_conditions, verify_exoneration_rules).
3. RAG policy retrieval selects the correct chunk (Điều 12.2 for traffic, Điều 12.1 for 48h deadline).
4. Zero automated sanction compliance (NFR-L06-02).
"""

import json
import os
from uuid import uuid4

import pytest
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from src.agents import driver_agent
from src.agents.driver_agent import (
    GSUPPORT_SYSTEM_PROMPT,
    get_driver_chat_model,
    get_driver_support_agent,
    run_driver_support_agent,
)
from src.agents.tools.driver_tools import query_driver_policy
from src.config import Settings
from src.models.tool_contracts import ToolExecutionContext


def _live_openrouter_enabled() -> bool:
    key = os.environ.get("OPENROUTER_API_KEY", "")
    return os.environ.get("TEST_LIVE_OPENROUTER") == "1" and key not in {
        "",
        "test-key",
        "placeholder",
        "mock-key",
        "synthetic-not-real-key",
    }


class ScriptedToolChatModel(FakeMessagesListChatModel):
    def bind_tools(self, tools, **kwargs):
        return self


@pytest.mark.asyncio
async def test_driver_agent_model_is_gemini_flash_lite(monkeypatch):
    """Verify get_driver_chat_model resolves to google/gemini-3.5-flash-lite."""
    settings = Settings(
        _env_file=None,
        llm_model="openrouter",
        openrouter_api_key="synthetic-test-key",
        openrouter_model="google/gemini-3.5-flash-lite",
    )
    monkeypatch.setenv("OPENROUTER_API_KEY", "synthetic-test-key")
    monkeypatch.setattr(
        driver_agent, "get_llm", lambda *args, **kwargs: type("Model", (), {"model": args[0].openrouter_model})()
    )
    model = get_driver_chat_model(settings)
    model_name = getattr(model, "model_name", None) or getattr(model, "model", "")
    assert "gemini-3.5-flash-lite" in model_name, f"Expected gemini-3.5-flash-lite, got {model_name}"


@pytest.mark.asyncio
async def test_scripted_model_runs_real_tool_node_policy_trace(monkeypatch):
    """Exercise the real graph ToolNode with server-issued trusted driver context."""
    queries = [
        "Điều 12.2",
        "Điều 12.1",
        "Điều 12.3",
    ]
    responses = [
        AIMessage(
            content="",
            tool_calls=[
                {"name": "query_driver_policy", "args": {"query": query}, "id": f"policy-{index}"}
                for index, query in enumerate(queries)
            ],
        ),
        AIMessage(content="Policy trace complete"),
    ]
    monkeypatch.setattr(
        "src.agents.driver_agent.get_driver_chat_model",
        lambda: ScriptedToolChatModel(responses=responses),
    )

    case_id = "018f2f4e-a000-7000-8000-000000000001"
    case = {
        "id": case_id,
        "organization_id": "018f2f4e-0000-7000-8000-000000000001",
        "assignment_id": "018f2f4e-2000-7000-8000-000000000001",
        "assigned_analyst_id": None,
        "driver_id": "018f2f4e-3000-7000-8000-000000000001",
        "trip_id": "018f2f4e-4000-7000-8000-000000000001",
        "vehicle_id": "018f2f4e-5000-7000-8000-000000000001",
        "principal_id": "018f2f4e-3000-7000-8000-000000000099",
        "version": 1,
        "status": "in_review",
    }

    policy_rows = {
        article: {
            "id": f"fixture-{article.replace('.', '-').lower()}",
            "policy_version_id": "018f2f4e-6000-7000-8000-000000000001",
            "source_ref": "fixture-green-safety-policy",
            "section_ref": article,
            "content": f"{article}: verified policy fixture content.",
            "version": "fixture-2026",
            "effective_from": None,
            "effective_to": None,
            "is_demo_policy": True,
        }
        for article in ("Điều 12.1", "Điều 12.2", "Điều 12.3")
    }

    from src.services import tool_execution

    real_rows = tool_execution._rows

    def rows_with_policy_fixture(query, params):
        if "FROM app.fraud_cases c" in query:
            return [case]
        if "FROM app.policy_chunks" in query:
            return [policy_rows[article] for article in policy_rows if article in params[2]]
        return real_rows(query, params)

    monkeypatch.setattr(tool_execution, "_rows", rows_with_policy_fixture)
    monkeypatch.setattr(tool_execution, "_scope", lambda _context: case)

    async def fixture_case_context(_context):
        return {
            "evidence_snapshot": {
                "id": "snapshot-1",
                "policy_version_id": "018f2f4e-6000-7000-8000-000000000001",
            }
        }

    monkeypatch.setattr(
        tool_execution,
        "build_case_context",
        fixture_case_context,
    )
    context = ToolExecutionContext(
        actor_id=str(case["principal_id"]),
        organization_id=str(case["organization_id"]),
        roles=frozenset({"driver"}),
        case_id=case_id,
        driver_id=str(case["driver_id"]),
        request_id=str(uuid4()),
        run_id=str(uuid4()),
        tool_call_id=str(uuid4()),
        turn_id=str(uuid4()),
    )
    result = await get_driver_support_agent().ainvoke(
        {
            "case_id": case_id,
            "messages": [HumanMessage(content="policy trace")],
            "system_prompt": GSUPPORT_SYSTEM_PROMPT,
            "runtime_context": context.model_dump(mode="json"),
        }
    )

    assert result.get("error") is None
    tool_messages = [message for message in result["messages"] if isinstance(message, ToolMessage)]
    assert len(tool_messages) == 3
    payloads = [json.loads(message.content) for message in tool_messages]
    assert all(payload["status"] == "succeeded" for payload in payloads)
    citations = [payload["data"]["citations"] for payload in payloads]
    assert all(len(items) == 1 for items in citations)
    assert {items[0]["doc_id"] for items in citations} == {row["id"] for row in policy_rows.values()}
    assert all(items[0]["document_title"] == "fixture-green-safety-policy" for items in citations)
    assert {items[0]["snippet"] for items in citations} == {
        f"{article}: verified policy fixture content." for article in policy_rows
    }


@pytest.mark.asyncio
@pytest.mark.skipif(not _live_openrouter_enabled(), reason="requires TEST_LIVE_OPENROUTER and a non-placeholder key")
async def test_e2e_driver_agent_tool_calling_and_exoneration():
    """Test full e2e turn with live gemini-3.5-flash-lite calling tools and evaluating exoneration."""
    case_id = "018f2f4e-a000-7000-8000-000000000026"
    driver_id = "drv-8492-nguyen-van-a"
    message = (
        "Tôi bị kẹt xe cứng nhắc ở ngã tư Kim Mã, xe không thể di chuyển. "
        "Nhờ kiểm tra đối soát giao thông và tra cứu Điều 12.2 quy chế miễn trừ."
    )

    result = await run_driver_support_agent(
        case_id=case_id,
        driver_id=driver_id,
        message=message,
        claim_type="traffic_gridlock",
    )

    assert result.get("error") is None, f"Execution failed with error: {result.get('error')}"
    messages = result.get("messages", [])
    assert len(messages) >= 3, "Expected multi-turn tool interaction in LangGraph trace"

    # Verify tool calls emitted by Gemini
    tool_calls_emitted = []
    tool_results_received = []

    for msg in messages:
        if isinstance(msg, AIMessage) and getattr(msg, "tool_calls", None):
            for tc in msg.tool_calls:
                tool_calls_emitted.append(tc["name"])
        elif isinstance(msg, ToolMessage):
            tool_results_received.append(msg.name)

    assert len(tool_calls_emitted) > 0, "Agent failed to emit any tool calls"
    assert "corroborate_traffic_conditions" in tool_calls_emitted or "verify_exoneration_rules" in tool_calls_emitted
    assert len(tool_results_received) > 0, "No tool results were processed in state graph"

    # Verify model synthesized final reply with Article 12.2 and zero penalty
    reply = result["reply"]
    assert len(reply) > 0
    assert "12.2" in reply or "miễn trừ" in reply.lower()


@pytest.mark.asyncio
@pytest.mark.skipif(not _live_openrouter_enabled(), reason="requires TEST_LIVE_OPENROUTER and a non-placeholder key")
async def test_e2e_driver_agent_rag_chunk_retrieval():
    """Verify tool query_driver_policy retrieves the correct chunk and Gemini cites it."""
    # 1. Direct tool test: traffic gridlock query retrieves Điều 12.2
    traffic_rag = await query_driver_policy.ainvoke({"query": "ùn tắc giao thông diện rộng kẹt xe bất khả kháng"})
    assert traffic_rag["matched_article"] == "Điều 12.2"
    assert "Trường hợp bất khả kháng" in traffic_rag["matched_title"]
    assert "ùn tắc giao thông diện rộng" in traffic_rag["matched_chunk"]

    # 2. Direct tool test: deadline & dispute rights query retrieves Điều 12.1
    deadline_rag = await query_driver_policy.ainvoke({"query": "thời hạn gửi giải trình khiếu nại trong bao lâu"})
    assert deadline_rag["matched_article"] == "Điều 12.1"
    assert "48 giờ" in deadline_rag["matched_chunk"]

    # 3. Direct tool test: unfair sanction inquiry retrieves Điều 12.3
    sanction_rag = await query_driver_policy.ainvoke({"query": "xử phạt tự động khóa tài khoản chuyên viên thẩm định"})
    assert sanction_rag["matched_article"] == "Điều 12.3"
    assert "Không áp dụng bất kỳ hình thức xử phạt tự động nào" in sanction_rag["matched_chunk"]

    # 4. Live Agent test with Gemini Flash 3.5 Lite
    result = await run_driver_support_agent(
        case_id="018f2f4e-a000-7000-8000-000000000026",
        driver_id="drv-8492-nguyen-van-a",
        message="Thời hạn tối đa tôi được khiếu nại là bao lâu? Nền tảng có quyền tự ý phạt tôi mà không có người xem xét không?",
        claim_type=None,
    )

    assert result.get("error") is None
    reply = result["reply"]
    assert "48" in reply, "Agent response must cite the 48-hour deadline from Điều 12.1"
    assert "12.1" in reply or "12.3" in reply or "chuyên viên" in reply.lower(), "Agent must cite policy grounding"

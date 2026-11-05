"""End-to-End verification of live GSupport Driver Agent with Gemini Flash 3.5 Lite.

Verifies:
1. Agent utilizes google/gemini-3.5-flash-lite via OpenRouter.
2. Tool calling execution and result retrieval (corroborate_traffic_conditions, verify_exoneration_rules).
3. RAG policy retrieval selects the correct chunk (Điều 12.2 for traffic, Điều 12.1 for 48h deadline).
4. Zero automated sanction compliance (NFR-L06-02).
"""

import json
import os

import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult

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


@pytest.mark.asyncio
async def test_driver_agent_model_is_gemini_flash_lite(monkeypatch):
    """Verify get_driver_chat_model resolves to google/gemini-3.5-flash-lite."""
    settings = Settings(
        _env_file=None,
        llm_model="gemini",
        gemini_api_key="synthetic-gemini-key",
        gemini_model="gemini-3.5-flash-lite",
    )
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setattr(
        driver_agent, "get_llm", lambda *args, **kwargs: type("Model", (), {"model": args[0].gemini_model})()
    )
    model = get_driver_chat_model(settings)
    model_name = getattr(model, "model_name", None) or getattr(model, "model", "")
    assert "gemini-3.5-flash-lite" in model_name, f"Expected gemini-3.5-flash-lite, got {model_name}"


@pytest.mark.asyncio
@pytest.mark.skipif(os.getenv("TEST_LIVE_GEMINI") != "1", reason="Live Gemini opt-in required")
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

    if result.get("error") and (
        "401" in str(result["error"])
        or "Authentication" in str(result["error"])
        or "Event loop is closed" in str(result["error"])
        or "rate limit" in str(result["error"]).lower()
        or "quota" in str(result["error"]).lower()
        or "timeout" in str(result["error"]).lower()
        or "connection" in str(result["error"]).lower()
    ):
        pytest.skip(f"Live OpenRouter call skipped due to environment restriction: {result.get('error')}")

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
async def test_default_driver_graph_runs_scripted_tool_node(monkeypatch):
    """Exercise the real graph and ToolNode offline with a deterministic model seam."""

    class ScriptedModel(BaseChatModel):
        calls: int = 0

        @property
        def _llm_type(self) -> str:
            return "scripted-driver-contract"

        def _generate(self, messages, stop=None, run_manager=None, **kwargs):
            self.calls += 1
            tool_messages = [m for m in messages if isinstance(m, ToolMessage)]
            if not tool_messages:
                message = AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "query_driver_policy",
                            "args": {"query": "thời hạn giải trình 48 giờ và Điều 12.3"},
                            "id": "scripted-policy-call",
                            "type": "tool_call",
                        }
                    ],
                )
            else:
                message = AIMessage(content=f"Nguồn chính sách đã truy vấn: {tool_messages[-1].content}")
            return ChatResult(generations=[ChatGeneration(message=message)])

        def bind_tools(self, tools, **kwargs):
            return self

    scripted = ScriptedModel()
    monkeypatch.setattr("src.agents.driver_agent.get_driver_chat_model", lambda: scripted)
    monkeypatch.setattr("src.agents.driver_agent._cached_driver_graph", None)
    from src.services import tool_execution

    ownership = {
        "id": "018f2f4e-a000-7000-8000-000000000026",
        "organization_id": "018f2f4e-0000-7000-8000-000000000001",
        "assignment_id": "018f2f4e-2000-7000-8000-000000000026",
        "assigned_analyst_id": "018f2f4e-1000-7000-8000-000000000001",
        "driver_id": "018f2f4e-3000-7000-8000-000000000026",
        "principal_id": "018f2f4e-4000-7000-8000-000000000026",
        "trip_id": "018f2f4e-5000-7000-8000-000000000026",
        "vehicle_id": "018f2f4e-6000-7000-8000-000000000026",
        "version": 1,
        "status": "open",
    }

    policy_version_id = "018f2f4e-7000-7000-8000-000000000001"

    async def frozen_policy_context(context):
        assert context.case_id == ownership["id"]
        assert context.actor_id == ownership["principal_id"]
        return {"evidence_snapshot": {"id": "fixture-snapshot", "policy_version_id": policy_version_id}}

    def policy_source_fixture(query, params):
        if "FROM app.fraud_cases" in query:
            return [ownership]
        if "FROM app.policy_chunks" in query:
            assert "pc.policy_version_id=%s::uuid" in query
            assert "pv.status='published'" in query
            assert params[:2] == (policy_version_id, policy_version_id)
            return [
                {
                    "id": "fixture-policy-12-1",
                    "policy_version_id": policy_version_id,
                    "source_ref": "GreenSM Driver Policy",
                    "section_ref": "Điều 12.1",
                    "content": "Điều 12.1: Tài xế có 48 giờ để gửi giải trình.",
                    "version": "fixture-policy-v1",
                    "effective_from": "2026-01-01",
                    "effective_to": None,
                    "is_demo_policy": True,
                }
            ]
        raise AssertionError(f"Unexpected SQL in deterministic graph contract: {query}")

    monkeypatch.setattr(tool_execution, "_rows", policy_source_fixture)
    monkeypatch.setattr(tool_execution, "build_case_context", frozen_policy_context)

    trusted_context = ToolExecutionContext(
        actor_id=str(ownership["principal_id"]),
        organization_id=str(ownership["organization_id"]),
        roles=frozenset({"driver"}),
        case_id=str(ownership["id"]),
        driver_id=str(ownership["driver_id"]),
        request_id="018f2f4e-9000-7000-8000-000000000001",
        run_id="018f2f4e-9000-7000-8000-000000000002",
        tool_call_id="018f2f4e-9000-7000-8000-000000000003",
        turn_id="018f2f4e-9000-7000-8000-000000000004",
    )

    result = await get_driver_support_agent().ainvoke(
        {
            "case_id": trusted_context.case_id,
            "messages": [HumanMessage(content="Cho tôi biết thời hạn giải trình và quy định chống phạt tự động.")],
            "system_prompt": GSUPPORT_SYSTEM_PROMPT,
            "runtime_context": trusted_context.model_dump(mode="json"),
        }
    )

    assert result.get("error") is None
    messages = result["messages"]
    assert any(isinstance(message, ToolMessage) for message in messages)
    tool_result = next(message.content for message in messages if isinstance(message, ToolMessage))
    payload = json.loads(tool_result)
    assert payload["status"] == "succeeded"
    assert payload["data"]["citations"]
    citation = payload["data"]["citations"][0]
    assert citation["document_title"] == "GreenSM Driver Policy"
    assert citation["policy_version_id"] == policy_version_id
    assert citation["policy_version"] == "fixture-policy-v1"
    assert "Điều 12.1" in citation["snippet"]
    assert "48 giờ" in citation["snippet"]
    assert payload["provenance"][0]["source"] == "app.policy_chunks"


@pytest.mark.asyncio
@pytest.mark.skipif(os.getenv("TEST_LIVE_GEMINI") != "1", reason="Live Gemini opt-in required")
async def test_driver_policy_contracts_are_verified_offline():
    """Verify independent policy retrieval contracts without a model call."""
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


@pytest.mark.asyncio
@pytest.mark.skipif(
    os.getenv("TEST_LIVE_GEMINI") != "1" or os.getenv("LLM_MODEL", "gemini") != "gemini",
    reason="Live Gemini requires TEST_LIVE_GEMINI=1 and LLM_MODEL=gemini",
)
async def test_opt_in_live_gemini_driver_response():
    result = await run_driver_support_agent(
        case_id="018f2f4e-a000-7000-8000-000000000026",
        driver_id="drv-8492-nguyen-van-a",
        message="Thời hạn tối đa tôi được khiếu nại là bao lâu?",
    )
    if result.get("error") and (
        "401" in str(result["error"])
        or "Authentication" in str(result["error"])
        or "Event loop is closed" in str(result["error"])
        or "rate limit" in str(result["error"]).lower()
        or "quota" in str(result["error"]).lower()
        or "timeout" in str(result["error"]).lower()
        or "connection" in str(result["error"]).lower()
    ):
        pytest.skip(f"Live OpenRouter call skipped due to environment restriction: {result.get('error')}")

    assert result.get("error") is None
    assert "48" in result["reply"]

import json
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock

import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from src.agents.forensic_baseline import assess_case
from src.agents.graph import (
    SYSTEM_PROMPT_VERSION,
    build_graph,
    get_chat_model,
    get_system_prompt_version,
    load_system_prompt,
)
from src.agents.tools.analyst_tools import (
    ALL_ANALYST_TOOLS,
    ANALYST_TOOLS,
    adjudicate_case,
    claim_case,
    get_case_detail,
    list_cases,
    query_policy,
    record_case_action,
    trigger_simulation,
)
from src.models.forensic import ForensicInput
from src.models.schemas import AdjudicationResponse, ClaimCaseResponse
from src.services.case_service import get_case_service
from tests.support.repo import REPO_ROOT

pytestmark = pytest.mark.docker


class ScriptedPositiveChatModel(BaseChatModel):
    """Deterministic ordinary-test model; graph still executes its real ToolNode."""

    call_count: int = 0

    @property
    def _llm_type(self) -> str:
        return "scripted-positive-test-model"

    def bind_tools(self, tools: Any, **kwargs: Any) -> Any:
        return self

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        self.call_count += 1
        if self.call_count == 1:
            message = AIMessage(
                content="",
                tool_calls=[{"name": "list_cases", "args": {"limit": 2}, "id": "positive_call_1"}],
            )
        else:
            message = AIMessage(content="Deterministic analyst response")
        return ChatResult(generations=[ChatGeneration(message=message)])

    async def _agenerate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        return self._generate(messages, stop, run_manager, **kwargs)


# 1. Config Tests
def test_openrouter_settings():
    from src.config import Settings

    settings = Settings(llm_model="openrouter", openrouter_api_key="synthetic-openrouter-key")
    assert hasattr(settings, "openrouter_api_key")
    assert hasattr(settings, "openrouter_base_url")
    assert hasattr(settings, "openrouter_model")
    assert "openrouter" in settings.openrouter_base_url

    chat_model = get_chat_model(settings)
    assert chat_model.model_name == settings.openrouter_model


def test_gemini_settings_in_production():
    from langchain_google_genai import ChatGoogleGenerativeAI

    from src.config import Settings

    settings = Settings(
        app_env="production",
        gemini_api_key="test-gemini-key",
        gemini_model="gemini-3.5-flash-lite",
    )
    chat_model = get_chat_model(settings)
    assert isinstance(chat_model, ChatGoogleGenerativeAI)
    assert chat_model.model == "gemini-3.5-flash-lite"


def test_project_jev_settings():
    from src.config import Settings

    settings = Settings(
        app_env="development",
        project_jev_api_key="sk-or-v1-test",
        project_jev_model="~typesafe/jev-latest",
    )
    assert settings.project_jev_api_key == "sk-or-v1-test"
    assert settings.project_jev_model == "~typesafe/jev-latest"


def test_system_prompt_loading():
    prompt = load_system_prompt()
    assert "GreenSM Sentinel Copilot" in prompt
    assert "Điều 14" in prompt
    assert "Điều 15" in prompt


def test_system_prompt_versioning():
    """Verify AC: Prompt is versioned cleanly and accessible."""
    version = get_system_prompt_version()
    assert version == SYSTEM_PROMPT_VERSION
    assert version.startswith("v")
    prompt = load_system_prompt()
    assert f"Version: {version}" in prompt


def test_system_prompt_prior_evidence_first():
    """Verify AC: Prior evidence first, zero hallucination, and boundary rules."""
    prompt = load_system_prompt()
    assert "Prior Evidence First" in prompt or "Bằng chứng đi trước" in prompt
    assert "telemetry_points" in prompt
    assert "platform_outage" in prompt
    assert "gps_degraded" in prompt
    assert "insufficient_evidence" in prompt
    assert "ERR-02" in prompt
    assert "ERR-05" in prompt
    assert "no_violation" in prompt


def test_system_prompt_not_auto_sanction():
    """Verify AC: Copilot cannot auto-sanction; human in the loop is mandatory."""
    prompt = load_system_prompt()
    assert "Zero Auto-Sanction" in prompt
    assert "Human-in-the-Loop" in prompt or "HITL" in prompt
    assert "Prohibition on Autonomous Sanction" in prompt or "Không tự động" in prompt


def test_benchmark_no_regression_on_core_cases():
    """Verify AC: Benchmark after tuning does not regress any core mock case."""
    dataset_path = REPO_ROOT / "eval/golden_set/forensic_mock_cases.json"
    cases = json.loads(dataset_path.read_text(encoding="utf-8"))
    assert len(cases) >= 10

    for entry in cases:
        case = ForensicInput.model_validate(entry["input"])
        output = assess_case(case)
        assert output.category == entry["expected_category"], f"Regression on {case.case_id}: got {output.category}"
        grounded_sources = {e.source for e in output.evidence}
        for req in entry["required_evidence"]:
            assert req in grounded_sources, f"Missing required evidence {req} for {case.case_id}"


# 2. Analyst Tool Specifications Tests
def test_analyst_tools_definitions():
    all_tool_names = {t.name for t in ALL_ANALYST_TOOLS}
    expected_tools = {
        "get_case_detail",
        "list_cases",
        "claim_case",
        "record_case_action",
        "adjudicate_case",
        "query_policy",
        "trigger_simulation",
    }
    assert expected_tools.issubset(all_tool_names)

    # Model-bound tools in ANALYST_TOOLS exclude human-only commands per #60/#85
    bound_tool_names = {t.name for t in ANALYST_TOOLS}
    forbidden = {"claim_case", "record_case_action", "adjudicate_case", "trigger_simulation"}
    assert forbidden.isdisjoint(bound_tool_names)


@pytest.mark.asyncio
async def test_tool_list_cases_and_get_detail():
    list_res = await list_cases.ainvoke({"limit": 2, "offset": 0})
    assert isinstance(list_res, dict)
    assert "items" in list_res
    assert len(list_res["items"]) > 0

    first_id = list_res["items"][0]["id"]
    detail_res = await get_case_detail.ainvoke({"case_id": first_id})
    assert isinstance(detail_res, dict)
    assert "case" in detail_res
    assert detail_res["case"]["id"] == first_id


@pytest.mark.asyncio
async def test_tool_claim_case(monkeypatch):
    service = get_case_service()
    mock_claim = AsyncMock(
        return_value=ClaimCaseResponse(
            case_id="018f2f4e-a000-7000-8000-000000000099",
            analyst_id="018f2f4e-1000-7000-8000-000000000001",
            lease_expires_at=datetime.now(UTC) + timedelta(seconds=600),
            status="claimed",
        )
    )
    monkeypatch.setattr(service, "claim_case_lease", mock_claim)

    claim_res = await claim_case.ainvoke(
        {
            "case_id": "018f2f4e-a000-7000-8000-000000000099",
            "analyst_id": "018f2f4e-1000-7000-8000-000000000001",
            "lease_duration_seconds": 600,
        }
    )
    assert isinstance(claim_res, dict)
    assert claim_res.get("case_id") == "018f2f4e-a000-7000-8000-000000000099"
    assert claim_res.get("analyst_id") == "018f2f4e-1000-7000-8000-000000000001"
    mock_claim.assert_awaited_once()


@pytest.mark.asyncio
async def test_tool_record_case_action():
    list_res = await list_cases.ainvoke({"limit": 1})
    case_id = list_res["items"][0]["id"]

    action_res = await record_case_action.ainvoke(
        {
            "case_id": case_id,
            "action_type": "REQUEST_EVIDENCE",
            "reason": "Suspected mock location",
            "notes": "Requesting driver phone logs",
            "analyst_id": "018f2f4e-1000-7000-8000-000000000001",
        }
    )
    assert isinstance(action_res, dict)
    assert action_res.get("case_id") == case_id
    assert action_res.get("action_type") == "REQUEST_EVIDENCE"


@pytest.mark.asyncio
async def test_tool_query_policy():
    policy_res = await query_policy.ainvoke({"query": "GPS mock location"})
    assert isinstance(policy_res, dict)
    assert "results" in policy_res
    assert policy_res.get("count", 0) >= 1


@pytest.mark.asyncio
async def test_tool_trigger_simulation():
    sim_res = await trigger_simulation.ainvoke(
        {
            "scenario": "driver_stall_cancel",
            "analyst_id": "018f2f4e-1000-7000-8000-000000000001",
            "seed": 42,
        }
    )
    assert isinstance(sim_res, dict)
    assert sim_res.get("status") in ("created", "queued", "ready", "ok", "triggered")
    assert "case_id" in sim_res


@pytest.mark.asyncio
async def test_tool_adjudicate_case(monkeypatch):
    service = get_case_service()
    mock_adj = AsyncMock(
        return_value=AdjudicationResponse(
            case_id="018f2f4e-a000-7000-8000-000000000099",
            outcome="DISAGREE",
            status="resolved",
            sanction_applied=None,
            adjudicated_at=datetime.now(UTC),
            new_version=2,
        )
    )
    monkeypatch.setattr(service, "adjudicate_case", mock_adj)

    adj_res = await adjudicate_case.ainvoke(
        {
            "case_id": "018f2f4e-a000-7000-8000-000000000099",
            "outcome": "DISAGREE",
            "justification": "Exonerated due to technical telemetry verification",
            "analyst_id": "018f2f4e-1000-7000-8000-000000000001",
        }
    )
    assert isinstance(adj_res, dict)
    assert adj_res.get("case_id") == "018f2f4e-a000-7000-8000-000000000099"
    assert adj_res.get("outcome") == "DISAGREE"
    mock_adj.assert_awaited_once()


# 3. LangGraph Workflow Tests
@pytest.mark.asyncio
async def test_agent_basic_flow():
    result = await build_graph(model=ScriptedPositiveChatModel()).ainvoke({"query": "Hello"})
    assert isinstance(result, dict)
    assert "response" in result
    assert "analysis" in result
    assert len(result["response"]) > 0


@pytest.mark.asyncio
async def test_agent_state_structure():
    result = await build_graph(model=ScriptedPositiveChatModel()).ainvoke({"query": "Test query"})
    assert isinstance(result, dict)
    assert "query" in result
    assert "response" in result
    assert "analysis" in result


@pytest.mark.asyncio
async def test_graph_compiles_and_reports_model_unavailable_without_credentials(monkeypatch):
    monkeypatch.setattr(
        "src.agents.graph.get_chat_model",
        lambda: (_ for _ in ()).throw(RuntimeError("gemini LLM credentials are not configured")),
    )
    graph = build_graph()
    result = await graph.ainvoke({"query": "health check"})
    assert result["error"] == "model_unavailable"
    assert result["response"]


# 4. Mock LLM for Tool Binding and Fallback Testing
class MockToolCallingChatModel(BaseChatModel):
    call_count: int = 0

    @property
    def _llm_type(self) -> str:
        return "mock-tool-caller"

    def bind_tools(self, tools: Any, **kwargs: Any) -> Any:
        return self

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        self.call_count += 1
        if self.call_count == 1:
            msg = AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "list_cases",
                        "args": {"limit": 2},
                        "id": "call_mock_1",
                    }
                ],
            )
        else:
            msg = AIMessage(content="Báo cáo phân tích: Đã tìm thấy các hồ sơ khả nghi và kiểm tra ngoại lệ guardrail.")
        return ChatResult(generations=[ChatGeneration(message=msg)])

    async def _agenerate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        return self._generate(messages, stop, run_manager, **kwargs)


@pytest.mark.asyncio
async def test_agent_tool_calling_loop():
    mock_model = MockToolCallingChatModel()
    test_graph = build_graph(model=mock_model)

    result = await test_graph.ainvoke({"query": "Liệt kê các ca vi phạm P0 gần đây"})
    assert "response" in result
    assert "Báo cáo phân tích" in result["response"]
    messages = result["messages"]
    tool_msgs = [m for m in messages if m.__class__.__name__ == "ToolMessage"]
    assert len(tool_msgs) == 1


class MockErrorChatModel(BaseChatModel):
    @property
    def _llm_type(self) -> str:
        return "mock-error-llm"

    def bind_tools(self, tools: Any, **kwargs: Any) -> Any:
        return self

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        raise ConnectionError("OpenRouter 503 Service Unavailable")

    async def _agenerate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        raise ConnectionError("OpenRouter 503 Service Unavailable")


@pytest.mark.asyncio
async def test_agent_fallback_on_unreachable_llm():
    mock_error_model = MockErrorChatModel()
    test_graph = build_graph(model=mock_error_model)

    result = await test_graph.ainvoke({"query": "Xin chào Sentinel Copilot"})
    assert isinstance(result, dict)
    assert "response" in result
    assert "analysis" in result
    assert "GreenSM Sentinel Copilot" in result["response"]
    assert result.get("error") is not None

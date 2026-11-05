import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, ToolMessage

from src.agents.driver_agent import run_driver_support_agent
from src.config import Settings
from src.services.answer_formatter import FormattedAnswer


@pytest.mark.asyncio
async def test_run_driver_support_agent_wires_answer_formatter():
    mock_service = MagicMock()
    # Test canonical_id resolution: alias case_alias -> canonical_123
    mock_service._find_case.return_value = ("canonical_123", {"trip_id": "trip_456"})
    mock_service._get_case_driver_id.return_value = "drv_789"

    mock_agent = MagicMock()
    mock_agent.ainvoke = AsyncMock(
        return_value={
            "response": "Vụ việc đã được tiếp nhận và xử lý theo quy chế Điều 12.2.",
            "messages": [AIMessage(content="Raw agent response text")],
            "error": None,
        }
    )

    expected_llm_blocks = [
        {"type": "table", "columns": ["A", "B"], "rows": [["1", "2"]]},
        {"type": "next_steps", "items": [{"label": "Gửi giải trình", "prompt": "Chi tiết"}]},
    ]
    mock_formatted = FormattedAnswer(
        markdown="Vụ việc đã được tiếp nhận.",
        blocks=expected_llm_blocks,
        suggestions=[{"label": "Gửi giải trình", "prompt": "Chi tiết"}],
    )

    with (
        patch("src.services.driver_dispute_service.get_driver_dispute_service", return_value=mock_service),
        patch("src.agents.driver_agent.get_driver_support_agent", return_value=mock_agent),
        patch("src.services.answer_formatter.format_answer", new_callable=AsyncMock) as mock_formatter,
    ):
        mock_formatter.return_value = mock_formatted

        result = await run_driver_support_agent(
            case_id="case_alias",
            driver_id="drv_789",
            message="Xin hỗ trợ kiểm tra kẹt xe",
            claim_type="traffic_gridlock",
            locale="vi",
        )

        assert result["reply"] == "Vụ việc đã được tiếp nhận."
        # Requirement 7: formatted_answer must be to_dict(), not FormattedAnswer dataclass
        assert result["formatted_answer"] == mock_formatted.to_dict()
        assert isinstance(result["formatted_answer"], dict)
        assert result["error"] is None

        # Requirement 3: Use canonical_id for the whitelist in driver_agent.py
        mock_formatter.assert_called_once()
        _, kwargs = mock_formatter.call_args
        assert kwargs["profile"] == "driver"
        assert kwargs["locale"] == "vi"
        whitelist = kwargs["entities"]
        assert "canonical_123" in whitelist.case_ids
        assert "drv_789" in whitelist.driver_ids
        assert "trip_456" in whitelist.trip_ids


@pytest.mark.asyncio
async def test_run_driver_support_agent_grounding_from_tool_messages():
    """Requirement 2: Build case_card, trip_card, and evidence blocks deterministically
    from ToolMessage outputs collected from final_state messages.
    Drop any LLM-emitted fare/pickup/destination/evidence not traceable to tool output.
    No default status_key (omit when unknown).
    Requirement 6: whitelist policy:// from query_driver_policy citation ids.
    """
    mock_service = MagicMock()
    mock_service._find_case.return_value = (
        "canonical_case_999",
        {"id": "canonical_case_999", "trip_id": "trip_real_100", "violation_title": "Nghi vấn vi phạm"},
    )
    mock_service._get_case_driver_id.return_value = "drv_actual_1"

    # Tool messages from agent run
    tool_messages = [
        ToolMessage(
            tool_call_id="call_ctx",
            name="get_driver_dispute_context",
            content=json.dumps(
                {
                    "case_id": "canonical_case_999",
                    "violation_title": "Nghi vấn vi phạm cước",
                    "dispute_status": "under_review",
                    "trip_id": "trip_real_100",
                    "pickup_address": "Điểm Đón Thật",
                    "dropoff_address": "Điểm Đến Thật",
                    "fare_vnd": 120000,
                }
            ),
        ),
        ToolMessage(
            tool_call_id="call_traffic",
            name="corroborate_traffic_conditions",
            content=json.dumps(
                {
                    "case_id": "canonical_case_999",
                    "corroborated": True,
                    "ratio": 2.5,
                    "observed_speed": 3.2,
                    "congestion_level": "heavy",
                    "details": "Ùn tắc cục bộ tại trục đường chính",
                }
            ),
        ),
        ToolMessage(
            tool_call_id="call_policy",
            name="query_driver_policy",
            content=json.dumps(
                {
                    "matched_article": "Điều 12.2",
                    "summary": "Miễn trừ trách nhiệm bất khả kháng",
                    "citation_ids": ["c12_2", "Điều 12.2"],
                }
            ),
        ),
    ]

    mock_agent = MagicMock()
    mock_agent.ainvoke = AsyncMock(
        return_value={
            "response": "Đã ghi nhận giải trình của bạn.",
            "messages": tool_messages + [AIMessage(content="Đã ghi nhận giải trình của bạn.")],
            "error": None,
        }
    )

    # LLM formatter emits blocks, including hallucinated cards that should NOT override deterministic grounding
    llm_blocks = [
        # Hallucinated case_card with fake case_id
        {"type": "case_card", "case_id": "fake_case", "title": "Fake"},
        # Table and list (allowed from LLM)
        {"type": "table", "columns": ["Chỉ số", "Giá trị"], "rows": [["Vận tốc", "3.2 km/h"]]},
        {"type": "list", "items": [{"label": "Chính sách", "href": "policy://c12_2"}]},
        {"type": "next_steps", "items": [{"label": "Đồng ý", "prompt": "Đồng ý"}]},
    ]
    mock_formatted = FormattedAnswer(
        markdown="Đã ghi nhận giải trình.",
        blocks=llm_blocks,
        suggestions=[],
    )

    with (
        patch("src.services.driver_dispute_service.get_driver_dispute_service", return_value=mock_service),
        patch("src.agents.driver_agent.get_driver_support_agent", return_value=mock_agent),
        patch("src.services.answer_formatter.format_answer", new_callable=AsyncMock) as mock_formatter,
    ):
        mock_formatter.return_value = mock_formatted

        result = await run_driver_support_agent(
            case_id="canonical_case_999",
            driver_id="drv_actual_1",
            message="Kẹt xe đường Kim Mã",
            claim_type="traffic_gridlock",
            locale="vi",
        )

        blocks = result["blocks"]
        block_types = [b["type"] for b in blocks]

        # Deterministic cards MUST be present and grounded in tool output
        assert "case_card" in block_types
        case_card = next(b for b in blocks if b["type"] == "case_card")
        assert case_card["case_id"] == "canonical_case_999"
        assert case_card["status_key"] == "under_review"

        assert "trip_card" in block_types
        trip_card = next(b for b in blocks if b["type"] == "trip_card")
        assert trip_card["trip_id"] == "trip_real_100"
        assert trip_card["pickup"] == "Điểm Đón Thật"
        assert trip_card["destination"] == "Điểm Đến Thật"
        assert trip_card["fare_vnd"] == 120000

        assert "evidence" in block_types
        evidence_block = next(b for b in blocks if b["type"] == "evidence")
        assert any(it["kind"] == "traffic" for it in evidence_block["items"])

        # LLM allowed blocks preserved
        assert "table" in block_types
        assert "list" in block_types
        assert "next_steps" in block_types

        # Requirement 6: policy:// from query_driver_policy was whitelisted
        _, kwargs = mock_formatter.call_args
        whitelist = kwargs["entities"]
        assert "c12_2" in whitelist.citation_ids


@pytest.mark.asyncio
async def test_run_driver_support_agent_formatter_disabled_gate():
    """Requirement 8: Gate the extra formatter LLM call behind setting driver_formatter_enabled."""
    mock_service = MagicMock()
    mock_service._find_case.return_value = ("case_1", {"trip_id": "trip_1"})
    mock_service._get_case_driver_id.return_value = "drv_1"

    mock_agent = MagicMock()
    mock_agent.ainvoke = AsyncMock(
        return_value={
            "response": "Vụ việc đã được xử lý.",
            "messages": [AIMessage(content="Vụ việc đã được xử lý.")],
            "error": None,
        }
    )

    with (
        patch("src.services.driver_dispute_service.get_driver_dispute_service", return_value=mock_service),
        patch("src.agents.driver_agent.get_driver_support_agent", return_value=mock_agent),
        patch("src.agents.driver_agent.get_settings", return_value=Settings(driver_formatter_enabled=False)),
        patch("src.services.answer_formatter.format_answer", new_callable=AsyncMock) as mock_formatter,
    ):
        result = await run_driver_support_agent(
            case_id="case_1",
            driver_id="drv_1",
            message="Xin hỗ trợ",
        )

        # Formatter LLM call must NOT be made when driver_formatter_enabled is False
        mock_formatter.assert_not_called()
        assert "Vụ việc đã được xử lý." in result["reply"]
        assert isinstance(result["formatted_answer"], dict)


@pytest.mark.asyncio
async def test_run_driver_support_agent_logs_failed_tool_messages(caplog):
    """Observability (Railway preview, PR #603 follow-up): a failed ToolMessage

    must be logged as `driver_tool_error` with the tool name, call id, and a
    truncated content preview, so Railway logs show *why* a tool failed
    instead of only the generic SSE `tool.end` status=error event.
    """
    mock_service = MagicMock()
    mock_service._find_case.return_value = ("case_1", {"trip_id": "trip_1"})
    mock_service._get_case_driver_id.return_value = "drv_1"

    error_tool_message = ToolMessage(
        content='{"status": "failed", "error": {"code": "FORBIDDEN", "message": "boom"}}',
        tool_call_id="call-err-1",
        name="list_my_cases",
        status="error",
    )

    mock_agent = MagicMock()
    mock_agent.ainvoke = AsyncMock(
        return_value={
            "response": "Đã xảy ra lỗi khi tra cứu.",
            "messages": [
                AIMessage(content="", tool_calls=[{"id": "call-err-1", "name": "list_my_cases", "args": {}}]),
                error_tool_message,
                AIMessage(content="Đã xảy ra lỗi khi tra cứu."),
            ],
            "error": None,
        }
    )

    with (
        patch("src.services.driver_dispute_service.get_driver_dispute_service", return_value=mock_service),
        patch("src.agents.driver_agent.get_driver_support_agent", return_value=mock_agent),
        caplog.at_level("WARNING", logger="src.agents.driver_agent"),
    ):
        await run_driver_support_agent(
            case_id="case_1",
            driver_id="drv_1",
            message="Tôi có vụ việc nào đang mở không?",
        )

    warnings = [r for r in caplog.records if r.message.startswith("driver_tool_error")]
    assert len(warnings) == 1, caplog.text
    assert "list_my_cases" in warnings[0].message
    assert "call-err-1" in warnings[0].message

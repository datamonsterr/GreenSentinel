"""TDD RED: run_driver_support_agent must support case-less invocation (Issue #482).

Case-less GSupport chat has no case_id yet; the agent resolves open cases via the
`list_my_cases` tool. The graph call must not crash when case_id is None and must
omit case_card/trip_card blocks that require a resolved case/trip id.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import AIMessage

from src.agents.driver_agent import run_driver_support_agent


@pytest.mark.asyncio
async def test_run_driver_support_agent_supports_caseless_chat():
    mock_agent = MagicMock()
    mock_agent.ainvoke = AsyncMock(
        return_value={
            "response": "Bạn hiện có 2 vụ việc đang mở.",
            "messages": [AIMessage(content="Bạn hiện có 2 vụ việc đang mở.")],
            "error": None,
        }
    )

    with patch("src.agents.driver_agent.get_driver_support_agent", return_value=mock_agent):
        result = await run_driver_support_agent(
            case_id=None,
            driver_id="drv_789",
            message="Tôi có vụ việc nào đang mở không?",
            claim_type=None,
            locale="vi",
        )

    assert result["error"] is None
    assert result["reply"]
    assert isinstance(result["blocks"], list)
    # No case resolved yet -> no case_card/trip_card fabricated.
    assert all(b.get("type") not in ("case_card", "trip_card") for b in result["blocks"])

    # The graph must have been invoked with case_id=None, not crash on lookup.
    mock_agent.ainvoke.assert_called_once()
    call_args = mock_agent.ainvoke.call_args
    initial_state = call_args.args[0] if call_args.args else call_args.kwargs.get("input")
    assert initial_state["case_id"] is None
    assert initial_state["runtime_context"]["case_id"] is None
    assert initial_state["runtime_context"]["driver_id"] == "drv_789"

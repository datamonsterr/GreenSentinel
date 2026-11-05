"""TDD RED: PR #603 Railway preview bug — caseless driver chat still fails after f9a86a07.

`run_driver_support_agent` (src/agents/driver_agent.py) builds the LangGraph
`runtime_context` dict with extra keys (`locale`, `on_tool_event`) that
`ToolExecutionContext` (`extra="forbid"`) rejects. The rejection happens in
`execute_scoped_graph_call`'s `except ValidationError` branch, entirely
*before* `execute_tool`/`_failed` ever runs -- so `tool_execution_failed`
never logs, matching the Railway symptom (ToolMessage status=="error" for
`query_driver_policy`/`list_my_cases`, question "Điều 12.2 quy định gì về
kẹt xe?", driver with zero cases).

Existing unit coverage (test_driver_caseless_tool_boundary.py) only exercises
`ToolExecutionContext.model_dump(mode="json")` runtime_context shapes, which
have no extra keys and never reproduce this. This suite drives the real
`run_driver_support_agent` entrypoint end to end against a real disposable
Postgres database under production-like settings (APP_ENV=production,
TEST_AUTH_ENABLED=false) with a scripted fake chat model emitting the exact
tool calls a real model emits.
"""

from __future__ import annotations

import json
from uuid import uuid4

import pytest
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, ToolMessage

from tests.integration.conftest import is_postgres_available

pytestmark = [
    pytest.mark.docker,
    pytest.mark.integration,
    pytest.mark.skipif(
        not is_postgres_available(),
        reason="PostgreSQL engine not reachable on loopback; set DATABASE_URL to run this suite",
    ),
]

ORG_ID = "018f2f4e-0000-7000-8000-000000000001"
DRIVER_ID = "018f2f4e-3000-7000-8000-000000000099"


class ScriptedToolChatModel(FakeMessagesListChatModel):
    def bind_tools(self, tools, **kwargs):
        return self


@pytest.fixture
def production_like_db(monkeypatch, disposable_database_dsn):
    """Point settings at the disposable DB under production-like flags."""
    monkeypatch.setenv("DATABASE_URL", disposable_database_dsn)
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("TEST_AUTH_ENABLED", "false")
    from src.config import get_settings

    get_settings.cache_clear()
    yield disposable_database_dsn
    get_settings.cache_clear()


def _collect_tool_messages(messages) -> list[ToolMessage]:
    return [m for m in messages if isinstance(m, ToolMessage)]


@pytest.mark.asyncio
async def test_caseless_driver_policy_and_list_cases_do_not_error(monkeypatch, production_like_db):
    """Điều 12.2 policy FAQ + list_my_cases (zero-case org) must both succeed.

    Reproduces the exact Railway symptom: model calls the policy tool and
    `list_my_cases` for a caseless driver in a zero-case org; neither
    ToolMessage may come back with status=="error".
    """
    responses = [
        AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "query_driver_policy",
                    "args": {"query": "Điều 12.2 kẹt xe"},
                    "id": f"policy-{uuid4()}",
                },
                {
                    "name": "list_my_cases",
                    "args": {"status": None},
                    "id": f"cases-{uuid4()}",
                },
            ],
        ),
        AIMessage(content="Theo Điều 12.2, trường hợp kẹt xe diện rộng được xem xét miễn trừ."),
    ]
    monkeypatch.setattr(
        "src.agents.driver_agent.get_driver_chat_model",
        lambda: ScriptedToolChatModel(responses=responses),
    )

    from src.agents.driver_agent import run_driver_support_agent

    result = await run_driver_support_agent(
        case_id=None,
        driver_id=DRIVER_ID,
        message="Điều 12.2 quy định gì về kẹt xe?",
        claim_type=None,
        locale="vi",
        organization_id=ORG_ID,
    )

    assert result.get("error") is None, result.get("error")
    tool_messages = _collect_tool_messages(result.get("messages", []))
    assert len(tool_messages) == 2, [m.name for m in tool_messages]
    for tm in tool_messages:
        payload = json.loads(tm.content) if isinstance(tm.content, str) else tm.content
        assert getattr(tm, "status", None) != "error", (tm.name, payload)


@pytest.mark.asyncio
async def test_caseless_driver_list_cases_tolerates_bare_empty_args(monkeypatch, production_like_db):
    """A model calling `list_my_cases` with `{}` (no args at all) must also succeed."""
    responses = [
        AIMessage(
            content="",
            tool_calls=[
                {"name": "list_my_cases", "args": {}, "id": f"cases-{uuid4()}"},
            ],
        ),
        AIMessage(content="Bạn hiện không có vụ việc nào đang mở."),
    ]
    monkeypatch.setattr(
        "src.agents.driver_agent.get_driver_chat_model",
        lambda: ScriptedToolChatModel(responses=responses),
    )

    from src.agents.driver_agent import run_driver_support_agent

    result = await run_driver_support_agent(
        case_id=None,
        driver_id=DRIVER_ID,
        message="Tôi có vụ việc nào đang mở không?",
        claim_type=None,
        locale="vi",
        organization_id=ORG_ID,
    )

    assert result.get("error") is None, result.get("error")
    tool_messages = _collect_tool_messages(result.get("messages", []))
    assert len(tool_messages) == 1
    assert getattr(tool_messages[0], "status", None) != "error"

import logging

import pytest
from langchain_core.messages import HumanMessage

from src.agents import driver_agent
from src.config import Settings


def test_missing_driver_key_raises_before_client_factory(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setattr(
        driver_agent, "get_llm", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("client constructed"))
    )
    settings = Settings(_env_file=None, app_env="test", llm_model="openrouter", openrouter_api_key="")
    with pytest.raises(ValueError, match="OPENROUTER_API_KEY is required"):
        driver_agent.get_driver_chat_model(settings)


def test_placeholder_driver_key_raises_before_client_factory(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    constructed = False

    def fake_client(*args, **kwargs):
        nonlocal constructed
        constructed = True
        return object()

    monkeypatch.setattr(driver_agent, "get_llm", fake_client)
    settings = Settings(_env_file=None, app_env="test", llm_model="openrouter", openrouter_api_key="placeholder")
    with pytest.raises(ValueError, match="OPENROUTER_API_KEY is required"):
        driver_agent.get_driver_chat_model(settings)
    assert constructed is False


def test_configured_synthetic_key_constructs_model_without_network(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "synthetic-test-key")
    captured = {}

    def fake_client(*args, **kwargs):
        captured["args"] = args
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(driver_agent, "get_llm", fake_client)
    settings = Settings(
        _env_file=None,
        app_env="test",
        openrouter_api_key="synthetic-test-key",
        driver_agent_model="synthetic-driver-model",
    )
    driver_agent.get_driver_chat_model(settings)
    assert captured["args"][0].openrouter_api_key == "synthetic-test-key"
    assert captured["args"][1] == settings.llm_model
    assert captured["model"] == "synthetic-driver-model"


def test_configured_synthetic_key_uses_driver_model_default(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "synthetic-test-key")
    captured = {}
    monkeypatch.setattr(driver_agent, "get_llm", lambda *args, **kwargs: captured.update(kwargs) or object())

    driver_agent.get_driver_chat_model(
        Settings(_env_file=None, app_env="test", openrouter_api_key="synthetic-test-key")
    )

    assert captured["model"] is None


class _ExplodingBoundModel:
    async def ainvoke(self, *_args, **_kwargs):
        raise RuntimeError("provider unreachable on this deployment")


class _ExplodingChatModel:
    def bind_tools(self, _tools):
        return _ExplodingBoundModel()


@pytest.mark.asyncio
async def test_call_driver_model_logs_exception_with_case_id_instead_of_swallowing(monkeypatch, caplog):
    """R1: a model-invocation failure must be logged with the exception
    (logger.exception) and the case id, never silently swallowed at warning
    level without context."""
    monkeypatch.setattr(driver_agent, "get_driver_chat_model", lambda *a, **k: _ExplodingChatModel())

    state = {
        "case_id": "case-exploding-001",
        "messages": [HumanMessage(content="hello")],
    }
    with caplog.at_level(logging.ERROR, logger="src.agents.driver_agent"):
        result = await driver_agent.call_driver_model(state, config={})

    assert "case-exploding-001" in result.get("response", "") or result.get("used_fallback") is True
    assert result.get("error")
    assert any("case-exploding-001" in rec.message and rec.levelno >= logging.ERROR for rec in caplog.records)


@pytest.mark.asyncio
async def test_call_driver_model_fallback_never_fabricates_metrics(monkeypatch):
    """R2: the LLM-failure fallback text must not state any unmeasured/
    fabricated metric (percentages, speeds) — it is a generic apology only."""
    monkeypatch.setattr(driver_agent, "get_driver_chat_model", lambda *a, **k: _ExplodingChatModel())

    state = {"case_id": "case-exploding-002", "messages": [HumanMessage(content="hello")]}
    result = await driver_agent.call_driver_model(state, config={})

    reply_text = result.get("response", "")
    assert "%" not in reply_text
    assert result.get("used_fallback") is True

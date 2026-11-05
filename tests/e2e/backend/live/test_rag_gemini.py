"""Opt-in live Gemini routing coverage."""

import os

import pytest
from dotenv import load_dotenv

from src.rag.cockpit_agent import CockpitRAGAgent


def _live_gemini_enabled() -> bool:
    key = os.environ.get("GEMINI_API_KEY", "")
    return os.environ.get("TEST_LIVE_GEMINI") == "1" and key not in {"", "mock", "test-key", "test"}


@pytest.mark.skipif(not _live_gemini_enabled(), reason="requires TEST_LIVE_GEMINI=1 and a valid GEMINI_API_KEY")
def test_live_gemini_tool_calling_routing():
    load_dotenv()
    api_key = os.environ["GEMINI_API_KEY"]
    live_agent = CockpitRAGAgent(api_key=api_key)
    assert live_agent.client is not None

    res = live_agent.execute_turn("Check driver suspension status for driver drv-6643-vu-duc-thanh")
    assert res.raw_tool_data.get("tool_called") is not None
    assert res.answer

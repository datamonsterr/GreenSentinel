"""Judge provider and score gates must reflect actual external model results."""

import json
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from eval import bench
from src.config import get_settings


def test_openai_judge_selection_never_constructs_gemini_client(monkeypatch):
    monkeypatch.setenv("LLM_MODEL", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "configured-unit-provider-key")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-4o-mini")
    get_settings.cache_clear()
    judge = bench._build_judge_client()
    assert judge.config.provider == "openai"
    assert judge.model_name == "gpt-4o-mini"
    assert judge.client is judge


@pytest.mark.parametrize("score", [0, 6, True, None])
def test_invalid_judge_score_cannot_pass_gate(score):
    generate = Mock(return_value=SimpleNamespace(text=json.dumps({"score": score})))
    judge = SimpleNamespace(model_name="gpt-4o-mini", models=SimpleNamespace(generate_content=generate))
    with pytest.raises(ValueError):
        bench._score_with_judge(judge, "Evaluate retrieved evidence")


def test_judge_uses_configured_model_and_actual_score():
    generate = Mock(return_value=SimpleNamespace(text='```json\n{"score":3,"justification":"Grounded"}\n```'))
    judge = SimpleNamespace(model_name="gpt-4o-mini", models=SimpleNamespace(generate_content=generate))
    assert bench._score_with_judge(judge, "Evaluate") == (3, "Grounded")
    generate.assert_called_once_with(model="gpt-4o-mini", contents="Evaluate")


def test_required_judge_missing_key_fails_before_retrieval(monkeypatch, tmp_path):
    monkeypatch.setenv("LLM_MODEL", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "")
    get_settings.cache_clear()
    cases = tmp_path / "cases.json"
    cases.write_text("[]", encoding="utf-8")
    agent = Mock()
    monkeypatch.setattr(bench, "CockpitRAGAgent", agent)
    with pytest.raises(RuntimeError, match="judge.*configured"):
        bench.evaluate_rag(cases, tmp_path / "output", enable_langsmith=False, require_live_judge=True)
    agent.assert_not_called()

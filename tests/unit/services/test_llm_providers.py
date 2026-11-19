from unittest.mock import patch

import pytest
from google.genai import types
from langchain_core.language_models.chat_models import BaseChatModel

from src.config import Settings
from src.services.llm import get_llm, resolve_llm_config


def test_provider_defaults_to_gemini_and_has_separate_model_ids(monkeypatch):
    monkeypatch.delenv("LLM_MODEL", raising=False)
    monkeypatch.delenv("llm_model", raising=False)
    config = resolve_llm_config(Settings(_env_file=None))
    assert config.provider == "gemini"
    assert config.model == Settings(_env_file=None).gemini_model


@pytest.mark.parametrize("provider", ["gemini", "openai", "openrouter"])
def test_factory_selects_provider_without_cross_provider_fallback(provider, monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    settings = Settings(
        llm_model=provider,
        gemini_api_key="gemini-test-key",
        openai_api_key="openai-test-key",
        openrouter_api_key="openrouter-test-key",
    )
    model = get_llm(settings)
    assert isinstance(model, BaseChatModel)


def test_missing_selected_provider_key_fails_safely():
    with pytest.raises(RuntimeError, match="gemini"):
        get_llm(Settings(llm_model="gemini"))


def test_canonical_openrouter_key_precedes_legacy_alias(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "canonical")
    monkeypatch.setenv("JEV_API_KEY", "legacy")
    settings = Settings(llm_model="openrouter")
    assert resolve_llm_config(settings).api_key == "canonical"


@pytest.mark.parametrize(
    "provider,key_field",
    [("gemini", "gemini_api_key"), ("openai", "openai_api_key"), ("openrouter", "openrouter_api_key")],
)
@pytest.mark.parametrize("placeholder", ["test-key", "mock-key", ".env.example", "your-api-key", "YOUR_OPENAI_API_KEY"])
def test_placeholder_credentials_are_rejected_before_sdk_construction(provider, key_field, placeholder):
    settings = Settings(llm_model=provider, **{key_field: placeholder})
    with patch("src.services.llm.ChatOpenAI") as chat, pytest.raises(RuntimeError) as exc:
        get_llm(settings)
    chat.assert_not_called()
    assert placeholder not in str(exc.value)


def test_explicit_openrouter_setting_precedes_environment(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "environment-key")
    settings = Settings(llm_model="openrouter", openrouter_api_key="explicit-key")
    assert resolve_llm_config(settings).api_key == "explicit-key"


def test_config_repr_does_not_expose_key():
    config = resolve_llm_config(Settings(llm_model="openai", openai_api_key="synthetic-secret"))
    assert "synthetic-secret" not in repr(config)


def test_unknown_and_case_variant_provider_rejected():
    with pytest.raises(ValueError):
        resolve_llm_config(Settings.model_construct(llm_model="Anthropic"))


def test_jev_model_does_not_select_generic_openrouter_model(monkeypatch):
    monkeypatch.setenv("JEV_MODEL", "~typesafe/jev-latest")
    monkeypatch.setenv("OPENROUTER_MODEL", "google/gemini-3.5-flash-lite")
    settings = Settings(llm_model="openrouter", openrouter_api_key="explicit-key")
    config = resolve_llm_config(settings)
    assert config.model == "google/gemini-3.5-flash-lite"


def test_gemini_factory_forces_google_api_backend(monkeypatch):
    monkeypatch.setenv("GOOGLE_GENAI_USE_VERTEXAI", "true")
    settings = Settings(llm_model="gemini", gemini_api_key="synthetic-key")
    with patch("langchain_google_genai.ChatGoogleGenerativeAI") as ctor:
        get_llm(settings)
    assert ctor.call_args.kwargs["vertexai"] is False


def test_native_gemini_client_forces_google_api_backend(monkeypatch):
    from src.services.content_adapter import ContentAdapter

    monkeypatch.setenv("GOOGLE_GENAI_USE_VERTEXAI", "true")
    with patch("src.services.content_adapter.genai.Client") as ctor:
        ContentAdapter(Settings(_env_file=None, llm_model="gemini", gemini_api_key="synthetic-key"))
    assert ctor.call_args.kwargs["vertexai"] is False


def test_google_api_key_is_legacy_gemini_alias_and_gemini_wins(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.setenv("GOOGLE_API_KEY", "google-only")
    settings = Settings(_env_file=None, llm_model="gemini")
    assert resolve_llm_config(settings).api_key == "google-only"
    monkeypatch.setenv("GEMINI_API_KEY", "gemini")
    both = Settings(_env_file=None, llm_model="gemini")
    assert resolve_llm_config(both).api_key == "gemini"


def test_openai_model_alias_precedence_and_legacy_compatibility(monkeypatch):
    # Isolate from ambient env: src.rag imports call load_dotenv(), so a
    # developer .env (or exported shell vars) can otherwise leak in.
    monkeypatch.delenv("MODEL_NAME", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    monkeypatch.setenv("MODEL_NAME", "legacy-model")
    legacy = Settings(_env_file=None, llm_model="openai")
    assert resolve_llm_config(legacy).model == "legacy-model"
    monkeypatch.setenv("OPENAI_MODEL", "canonical")
    canonical = Settings(_env_file=None, llm_model="openai")
    assert resolve_llm_config(canonical).model == "canonical"


def test_mixed_case_selector_environment_is_supported(monkeypatch):
    monkeypatch.setenv("LLM_model", "openai")
    monkeypatch.delenv("LLM_MODEL", raising=False)
    settings = Settings(_env_file=None, openai_api_key="synthetic")
    assert settings.llm_model == "openai"


@pytest.mark.parametrize("placeholder", ["sk-or-v1-your-example", "unconfigured-openrouter-key"])
def test_known_openrouter_placeholder_is_rejected(placeholder):
    settings = Settings(_env_file=None, llm_model="openrouter", openrouter_api_key=placeholder)
    with pytest.raises(RuntimeError):
        get_llm(settings)


def test_openai_factory_sets_official_openai_base_url(monkeypatch):
    monkeypatch.setenv("OPENAI_BASE_URL", "https://openrouter.ai/api/v1")
    settings = Settings(llm_model="openai", openai_api_key="synthetic-key")
    with patch("src.services.llm.ChatOpenAI") as ctor:
        get_llm(settings)
    assert ctor.call_args.kwargs["base_url"] == "https://api.openai.com/v1"


def test_adapter_converts_nested_tool_args_and_text():
    from langchain_core.messages import AIMessage

    from src.services.content_adapter import ContentAdapter

    adapter = ContentAdapter(Settings(llm_model="openai", openai_api_key="synthetic-key"))
    response = adapter._to_google_response(
        AIMessage(
            content="answer",
            tool_calls=[{"name": "lookup", "args": {"outer": {"inner": True}}, "id": "call-1", "type": "tool_call"}],
        )
    )
    parts = response.candidates[0].content.parts
    assert parts[0].function_call.name == "lookup"
    assert parts[0].function_call.args == {"outer": {"inner": True}}
    assert parts[1].text == "answer"


def test_text_normalizer_keeps_public_text_and_discards_reasoning_blocks():
    from langchain_core.messages import AIMessage

    from src.services.content_adapter import message_text

    message = AIMessage(
        content=[
            {"type": "text", "text": "public answer"},
            {"type": "reasoning", "reasoning": "private chain of thought"},
        ]
    )
    assert message_text(message) == "public answer"
    assert "reasoning" not in message_text(message)


def test_schema_conversion_preserves_camel_case_property_names():
    from src.services.content_adapter import _lower_schema

    schema = {"type": "OBJECT", "properties": {"driverId": {"type": "STRING"}}, "additionalProperties": False}
    assert _lower_schema(schema) == {
        "type": "object",
        "properties": {"driverId": {"type": "string"}},
        "additionalProperties": False,
    }


def test_adapter_forwards_system_instruction_and_tool_mode(monkeypatch):
    from src.services.content_adapter import ContentAdapter

    seen = {}

    class FakeModel:
        def bind_tools(self, tools, tool_choice=None):
            seen["tools"] = tools
            seen["choice"] = tool_choice
            return self

        def invoke(self, messages):
            seen["messages"] = messages
            from langchain_core.messages import AIMessage

            return AIMessage(content="ok")

    monkeypatch.setattr("src.services.content_adapter.get_llm", lambda *args, **kwargs: FakeModel())
    adapter = ContentAdapter(Settings(llm_model="openai", openai_api_key="synthetic-key"))
    config = types.GenerateContentConfig(
        system_instruction="safety policy",
        tools=[types.Tool(function_declarations=[types.FunctionDeclaration(name="lookup")])],
        tool_config=types.ToolConfig(function_calling_config=types.FunctionCallingConfig(mode="ANY")),
    )
    adapter.generate_content(model="gpt", contents="question", config=config)
    assert seen["messages"][0].type == "system"
    assert seen["messages"][0].content == "safety policy"
    assert seen["choice"] == "required"


def test_adapter_handles_empty_and_malformed_multiple_tool_calls():
    from types import SimpleNamespace

    from src.services.content_adapter import ContentAdapter

    adapter = ContentAdapter(Settings(llm_model="openai", openai_api_key="synthetic-key"))
    response = adapter._to_google_response(
        SimpleNamespace(
            content=[{"type": "reasoning", "reasoning": "private"}],
            tool_calls=[
                {"name": "first", "args": {"caseId": "1"}, "id": "1", "type": "tool_call"},
                {"name": "second", "args": None, "id": "2", "type": "tool_call"},
            ],
        )
    )
    parts = response.candidates[0].content.parts
    assert [part.function_call.name for part in parts] == ["first", "second"]
    assert parts[0].function_call.args == {"caseId": "1"}
    assert parts[1].function_call.args == {}


def test_adapter_preserves_case_sensitive_tool_argument_values():
    from types import SimpleNamespace

    from src.services.content_adapter import ContentAdapter

    adapter = ContentAdapter(Settings(llm_model="openai", openai_api_key="synthetic-key"))
    response = adapter._to_google_response(
        SimpleNamespace(
            content="",
            tool_calls=[
                {
                    "name": "lookup",
                    "args": {"type": "VIP", "nested": {"type": "CAR", "driverId": "DRV-A"}},
                }
            ],
        )
    )
    assert response.candidates[0].content.parts[0].function_call.args == {
        "type": "VIP",
        "nested": {"type": "CAR", "driverId": "DRV-A"},
    }


def test_openrouter_defaults_to_glm_flash_with_low_reasoning(monkeypatch):
    monkeypatch.delenv("OPENROUTER_MODEL", raising=False)
    monkeypatch.delenv("OPENROUTER_REASONING_EFFORT", raising=False)
    settings = Settings(_env_file=None, llm_model="openrouter", openrouter_api_key="openrouter-test-key")
    assert resolve_llm_config(settings).model == "z-ai/glm-5.3-flash"
    model = get_llm(settings)
    assert model.extra_body == {"reasoning": {"effort": "low"}}


def test_openrouter_model_and_effort_configurable_via_env(monkeypatch):
    monkeypatch.setenv("OPENROUTER_MODEL", "z-ai/other")
    monkeypatch.setenv("OPENROUTER_REASONING_EFFORT", "high")
    settings = Settings(_env_file=None, llm_model="openrouter", openrouter_api_key="openrouter-test-key")
    assert resolve_llm_config(settings).model == "z-ai/other"
    assert get_llm(settings).extra_body == {"reasoning": {"effort": "high"}}


def test_reasoning_blocks_never_reach_user_text():
    from langchain_core.messages import AIMessage

    from src.agents.driver_agent import _extract_text_content
    from src.services.content_adapter import message_text

    blocks = [
        {"type": "reasoning", "text": "secret chain of thought"},
        {"type": "thinking", "thinking": "more secret", "text": "more secret"},
        {"type": "text", "text": "Xin chào"},
    ]
    assert _extract_text_content(blocks) == "Xin chào"
    assert message_text(AIMessage(content=blocks)) == "Xin chào"

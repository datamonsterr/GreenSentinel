from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from google.genai import types
from langchain_core.messages import AIMessage

from src.config import Settings
from src.services.content_adapter import ContentAdapter


def _config():
    return types.GenerateContentConfig(
        system_instruction="policy",
        tools=[
            types.Tool(
                function_declarations=[
                    types.FunctionDeclaration(name="lookup", description="Find record", parameters={"type": "object"})
                ]
            )
        ],
    )


def test_adapter_binds_canonical_tools_and_preserves_call_id():
    adapter = ContentAdapter(Settings(_env_file=None, llm_model="openai", openai_api_key="synthetic"))
    seen = {}

    class Model:
        def bind_tools(self, tools, tool_choice):
            seen["tools"] = tools
            return self

        async def ainvoke(self, messages):
            seen["messages"] = messages
            return AIMessage(
                content="", tool_calls=[{"name": "lookup", "args": {}, "id": "call-7", "type": "tool_call"}]
            )

    with patch("src.services.content_adapter.get_llm", return_value=Model()):
        result = pytest.importorskip("asyncio").run(
            adapter.agenerate_content(
                model="x",
                contents=[types.Content(role="user", parts=[types.Part.from_text(text="hi")])],
                config=_config(),
            )
        )
    assert seen["tools"][0]["function"]["name"] == "lookup"
    assert result.candidates[0].content.parts[0].function_call.id == "call-7"


@pytest.mark.asyncio
async def test_adapter_async_path_awaits_model_and_replays_fifo_tool_results():
    adapter = ContentAdapter(Settings(_env_file=None, llm_model="openai", openai_api_key="synthetic"))
    model = MagicMock()
    model.ainvoke = AsyncMock(return_value=AIMessage(content="done"))
    calls = [
        types.Part(function_call=types.FunctionCall(id="a", name="lookup", args={})),
        types.Part(function_call=types.FunctionCall(id="b", name="lookup", args={})),
    ]
    contents = [
        types.Content(role="user", parts=[types.Part.from_text(text="hi")]),
        types.Content(role="model", parts=calls),
        SimpleNamespace(
            role="user",
            parts=[
                SimpleNamespace(function_response=SimpleNamespace(name="lookup", response={"n": 1})),
                SimpleNamespace(function_response=SimpleNamespace(name="lookup", response={"n": 2})),
            ],
        ),
    ]
    with patch("src.services.content_adapter.get_llm", return_value=model):
        await adapter.agenerate_content(model="x", contents=contents, config=None)
    replay = model.ainvoke.await_args.args[0]
    assert [m.tool_call_id for m in replay if getattr(m, "type", "") == "tool"] == ["a", "b"]


@pytest.mark.asyncio
async def test_runtime_selects_openai_without_constructing_gemini():
    import src.services.agent_runtime as runtime

    settings = Settings(_env_file=None, llm_model="openai", openai_api_key="synthetic")
    response = SimpleNamespace(
        candidates=[SimpleNamespace(content=types.Content(role="model", parts=[types.Part.from_text(text="ok")]))]
    )
    with (
        patch.object(runtime, "get_settings", return_value=settings),
        patch("google.genai.Client", side_effect=AssertionError("Gemini used")),
        patch.object(ContentAdapter, "agenerate_content", new=AsyncMock(return_value=response)) as call,
    ):
        result = await runtime._provider_once([], [], "policy")
    call.assert_awaited_once()
    assert result is response


def test_unusable_selected_credentials_fail_closed():
    adapter = ContentAdapter(Settings(_env_file=None, llm_model="openai", openai_api_key="test-key"))
    assert adapter.client is None


def test_plain_string_content_replays_exact_text_and_private_reasoning_is_dropped():
    adapter = ContentAdapter(Settings(_env_file=None, llm_model="openai", openai_api_key="synthetic"))
    messages = adapter._messages("plain question", None)
    assert messages[0].content == "plain question"
    content = SimpleNamespace(
        role="model",
        parts=[SimpleNamespace(text="secret", thought=True), SimpleNamespace(text="public", thought=False)],
    )
    assert adapter._messages([content], None)[0].content == "public"


def test_runtime_schema_uses_parameters_json_schema_and_missing_id_fails_closed():
    adapter = ContentAdapter(Settings(_env_file=None, llm_model="openai", openai_api_key="synthetic"))
    declaration = {
        "name": "lookup",
        "description": "x",
        "parameters_json_schema": {"type": "object", "properties": {"start": {"type": "string"}}},
    }
    config = types.GenerateContentConfig(
        tools=[types.Tool(function_declarations=[types.FunctionDeclaration.model_validate(declaration)])]
    )
    model = MagicMock()
    adapter._bind_tools(model, config)
    assert model.bind_tools.call_args.args[0][0]["function"]["parameters"]["properties"]["start"]
    response = SimpleNamespace(name="lookup", response={})
    with pytest.raises(ValueError):
        adapter._messages([SimpleNamespace(role="user", parts=[SimpleNamespace(function_response=response)])], None)


def test_explicit_response_id_matches_pending_call_out_of_order():
    adapter = ContentAdapter(Settings(_env_file=None, llm_model="openai", openai_api_key="synthetic"))
    contents = [
        SimpleNamespace(
            role="model",
            parts=[
                SimpleNamespace(function_call=SimpleNamespace(id="a", name="lookup", args={})),
                SimpleNamespace(function_call=SimpleNamespace(id="b", name="lookup", args={})),
            ],
        ),
        SimpleNamespace(
            role="user",
            parts=[
                SimpleNamespace(function_response=SimpleNamespace(id="b", name="lookup", response={"n": 2})),
                SimpleNamespace(function_response=SimpleNamespace(id="a", name="lookup", response={"n": 1})),
            ],
        ),
    ]
    replay = adapter._messages(contents, None)
    assert [m.tool_call_id for m in replay if getattr(m, "type", "") == "tool"] == ["b", "a"]


def test_synthetic_call_ids_unique_across_model_messages():
    adapter = ContentAdapter(Settings(_env_file=None, llm_model="openai", openai_api_key="synthetic"))
    contents = [
        SimpleNamespace(role="model", parts=[SimpleNamespace(function_call=SimpleNamespace(name="a", args={}))]),
        SimpleNamespace(role="model", parts=[SimpleNamespace(function_call=SimpleNamespace(name="b", args={}))]),
    ]
    messages = adapter._messages(contents, None)
    assert [m.tool_calls[0]["id"] for m in messages] == ["call_0", "call_1"]


def test_unknown_explicit_response_id_fails_closed():
    adapter = ContentAdapter(Settings(_env_file=None, llm_model="openai", openai_api_key="synthetic"))
    contents = [
        SimpleNamespace(
            role="model", parts=[SimpleNamespace(function_call=SimpleNamespace(id="a", name="lookup", args={}))]
        ),
        SimpleNamespace(
            role="user",
            parts=[SimpleNamespace(function_response=SimpleNamespace(id="unknown", name="lookup", response={}))],
        ),
    ]
    with pytest.raises(ValueError, match="does not match"):
        adapter._messages(contents, None)

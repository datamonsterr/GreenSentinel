"""Offline contracts for the real provider SDK/LangChain integrations.

These tests replace only the SDK transport boundary.  They deliberately keep
the factory-created LangChain model and provider parser real.
"""

from __future__ import annotations

import json
from collections.abc import Callable

import httpx
import pytest
from google import genai
from google.genai import types
from jsonschema import Draft202012Validator
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import HumanMessage
from langchain_core.tools import StructuredTool

from src.config import Settings
from src.services.llm import get_llm, resolve_llm_config


def _tool() -> StructuredTool:
    return StructuredTool.from_function(
        lambda case_id: {"case_id": case_id},
        name="lookup_case",
        description="Look up one case.",
    )


def _settings(provider: str) -> Settings:
    key_field = {
        "gemini": "gemini_api_key",
        "openai": "openai_api_key",
        "openrouter": "openrouter_api_key",
    }[provider]
    return Settings(_env_file=None, llm_model=provider, **{key_field: "synthetic-contract-key"})


def test_factory_default_selector_and_all_real_models_are_base_chat_models():
    assert resolve_llm_config(Settings(_env_file=None)).provider == "gemini"
    for provider in ("gemini", "openai", "openrouter"):
        assert isinstance(get_llm(_settings(provider)), BaseChatModel)


def test_native_adapter_uses_google_client_only_for_selected_gemini():
    from src.services.content_adapter import ContentAdapter

    gemini = ContentAdapter(_settings("gemini"))
    openai = ContentAdapter(_settings("openai"))
    assert isinstance(gemini.client, genai.Client)
    assert openai.client is openai


def _openai_payload(tool_call: bool = False) -> dict:
    message = {"role": "assistant", "content": None if tool_call else "contract answer"}
    if tool_call:
        message["tool_calls"] = [
            {
                "id": "call_contract",
                "type": "function",
                "function": {"name": "lookup_case", "arguments": '{"case_id":"C-61"}'},
            }
        ]
    return {
        "id": "chatcmpl-contract",
        "object": "chat.completion",
        "created": 1,
        "model": "contract-model",
        "choices": [{"index": 0, "message": message, "finish_reason": "tool_calls" if tool_call else "stop"}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    }


def _openai_sse() -> bytes:
    chunks = [
        {
            "id": "chatcmpl-stream",
            "object": "chat.completion.chunk",
            "created": 1,
            "model": "contract-model",
            "choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}],
        },
        {
            "id": "chatcmpl-stream",
            "object": "chat.completion.chunk",
            "created": 1,
            "model": "contract-model",
            "choices": [{"index": 0, "delta": {"content": "streamed"}, "finish_reason": None}],
        },
        {
            "id": "chatcmpl-stream",
            "object": "chat.completion.chunk",
            "created": 1,
            "model": "contract-model",
            "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
        },
    ]
    return b"".join(b"data: " + json.dumps(chunk).encode() + b"\n\n" for chunk in chunks) + b"data: [DONE]\n\n"


def _openai_model(provider: str, handler: Callable[[httpx.Request], httpx.Response]):
    model = get_llm(_settings(provider))
    transport = httpx.MockTransport(handler)
    client = __import__("openai").OpenAI(
        api_key="synthetic-contract-key",
        base_url=model.openai_api_base,
        http_client=httpx.Client(transport=transport),
    )
    model.client = client.chat.completions
    model.root_client = client
    return model


@pytest.mark.parametrize("provider", ["openai", "openrouter"])
def test_openai_family_real_sdk_invoke_and_bind_tools_contract(provider: str):
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=_openai_payload(tool_call=True))

    model = _openai_model(provider, handler)
    result = model.bind_tools([_tool()]).invoke([HumanMessage(content="find C-61")])

    assert isinstance(model, BaseChatModel)
    assert result.tool_calls[0]["name"] == "lookup_case"
    assert result.tool_calls[0]["args"] == {"case_id": "C-61"}
    body = json.loads(seen[0].content)
    assert seen[0].url.host == ("openrouter.ai" if provider == "openrouter" else "api.openai.com")
    assert seen[0].headers["authorization"] == "Bearer synthetic-contract-key"
    expected_model = model.model_name
    assert body["model"] == expected_model
    assert body["messages"][-1]["content"] == "find C-61"
    assert body["tools"][0]["function"]["name"] == "lookup_case"
    assert body["tools"][0]["function"]["parameters"]


@pytest.mark.parametrize("provider", ["openai", "openrouter"])
def test_content_adapter_serializes_google_tool_schema_for_openai_family(provider: str, monkeypatch):
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=_openai_payload())

    model = _openai_model(provider, handler)
    monkeypatch.setattr("src.services.content_adapter.get_llm", lambda *args, **kwargs: model)

    from src.services.content_adapter import ContentAdapter

    adapter = ContentAdapter(_settings(provider))
    schema = types.Schema(
        type="OBJECT",
        properties={
            "driverId": types.Schema(type="STRING"),
            "vehicle": types.Schema(
                type="OBJECT",
                properties={"kind": types.Schema(type="STRING", enum=["VIP", "CAR"])},
                additional_properties=False,
            ),
        },
        required=["driverId"],
        additional_properties=False,
    )
    config = types.GenerateContentConfig(
        tools=[types.Tool(function_declarations=[types.FunctionDeclaration(name="lookup", parameters=schema)])]
    )

    adapter.generate_content(model="contract-model", contents="find C-61", config=config)

    body = json.loads(seen[0].content)
    parameters = body["tools"][0]["function"]["parameters"]
    Draft202012Validator.check_schema(parameters)
    assert parameters["required"] == ["driverId"]
    assert parameters["type"] == "object"
    assert parameters["properties"]["driverId"]["type"] == "string"
    assert parameters["properties"]["vehicle"]["type"] == "object"
    assert parameters["properties"]["vehicle"]["properties"]["kind"]["type"] == "string"
    assert parameters["properties"]["vehicle"]["properties"]["kind"]["enum"] == ["VIP", "CAR"]
    assert parameters["additionalProperties"] is False


@pytest.mark.parametrize("provider", ["openai", "openrouter"])
def test_openai_family_real_langchain_stream_parser_contract(provider: str):
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=_openai_sse())

    model = _openai_model(provider, handler)
    chunks = list(model.stream([HumanMessage(content="stream")]))

    assert "".join(chunk.text for chunk in chunks) == "streamed"
    assert json.loads(seen[0].content)["stream"] is True


def _gemini_model(handler: Callable[[httpx.Request], httpx.Response]):
    model = get_llm(_settings("gemini"))
    client = genai.Client(
        api_key="synthetic-contract-key",
        vertexai=getattr(model, "vertexai", False),
        http_options=types.HttpOptions(client_args={"transport": httpx.MockTransport(handler)}),
    )
    model.client = client
    return model


def _gemini_payload(tool_call: bool = False) -> dict:
    parts = [{"text": "contract answer"}]
    if tool_call:
        parts = [{"functionCall": {"name": "lookup_case", "args": {"case_id": "C-61"}}}]
    return {
        "candidates": [{"content": {"role": "model", "parts": parts}, "finishReason": "STOP"}],
        "usageMetadata": {"promptTokenCount": 1, "candidatesTokenCount": 1, "totalTokenCount": 2},
    }


def test_gemini_real_sdk_invoke_and_bind_tools_contract():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=_gemini_payload(tool_call=True))

    model = _gemini_model(handler)
    result = model.bind_tools([_tool()]).invoke([HumanMessage(content="find C-61")])

    assert isinstance(model, BaseChatModel)
    assert result.tool_calls[0]["name"] == "lookup_case"
    assert result.tool_calls[0]["args"] == {"case_id": "C-61"}
    body = json.loads(seen[0].content)
    assert seen[0].url.host == "generativelanguage.googleapis.com"
    assert seen[0].headers["x-goog-api-key"] == "synthetic-contract-key"
    assert body["contents"][0]["parts"][0]["text"] == "find C-61"
    assert body["tools"][0]["functionDeclarations"][0]["name"] == "lookup_case"
    declaration = body["tools"][0]["functionDeclarations"][0]
    assert declaration.get("parametersJsonSchema") or declaration.get("parameters")


def test_gemini_real_sdk_stream_parser_contract():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        chunks = [
            {"candidates": [{"content": {"role": "model", "parts": [{"text": "stream"}]}}]},
            {"candidates": [{"content": {"role": "model", "parts": [{"text": "ed"}]}}]},
        ]
        body = b"".join(b"data: " + json.dumps(chunk).encode() + b"\n\n" for chunk in chunks)
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=body)

    model = _gemini_model(handler)
    chunks = list(model.stream([HumanMessage(content="stream")]))
    assert "".join(chunk.text for chunk in chunks) == "streamed"
    assert seen[0].url.path.endswith(":streamGenerateContent")
    assert seen[0].url.params["alt"] == "sse"


def _graph_tool() -> StructuredTool:
    def echo(value: str) -> str:
        return f"echoed:{value}"

    return StructuredTool.from_function(echo, name="echo", description="Echo a value.")


def _graph_openai_model(provider: str, handler: Callable[[httpx.Request], httpx.Response]):
    model = get_llm(_settings(provider))
    import openai

    base_url = model.openai_api_base
    sync_client = openai.OpenAI(
        api_key="synthetic-contract-key",
        base_url=base_url,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    async_client = openai.AsyncOpenAI(
        api_key="synthetic-contract-key",
        base_url=base_url,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    model.client = sync_client.chat.completions
    model.root_client = sync_client
    model.async_client = async_client.chat.completions
    model.root_async_client = async_client
    return model


def _graph_gemini_model(handler: Callable[[httpx.Request], httpx.Response]):
    model = get_llm(_settings("gemini"))
    client = genai.Client(
        api_key="synthetic-contract-key",
        vertexai=getattr(model, "vertexai", False),
        http_options=types.HttpOptions(
            client_args={"transport": httpx.MockTransport(handler)},
            async_client_args={"transport": httpx.MockTransport(handler)},
        ),
    )
    model.client = client
    return model


def _graph_response(provider: str, tool: bool) -> dict:
    if provider == "gemini":
        parts = (
            [{"functionCall": {"name": "echo", "args": {"value": "contract"}}}]
            if tool
            else [{"text": "final public answer"}]
        )
        return {"candidates": [{"content": {"role": "model", "parts": parts}, "finishReason": "STOP"}]}
    message = {"role": "assistant", "content": None if tool else "final public answer"}
    if tool:
        message["tool_calls"] = [
            {"id": "call_echo", "type": "function", "function": {"name": "echo", "arguments": '{"value":"contract"}'}}
        ]
    return {
        "id": "graph-contract",
        "object": "chat.completion",
        "created": 1,
        "model": "contract-model",
        "choices": [{"index": 0, "message": message, "finish_reason": "tool_calls" if tool else "stop"}],
    }


@pytest.mark.parametrize("provider", ["gemini", "openai", "openrouter"])
@pytest.mark.asyncio
async def test_real_sdk_async_graph_toolnode_roundtrip(provider: str):
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=_graph_response(provider, len(requests) == 1))

    model = _graph_gemini_model(handler) if provider == "gemini" else _graph_openai_model(provider, handler)
    from src.agents.graph import build_graph

    graph = build_graph(model=model, tools=[_graph_tool()])
    result = await graph.ainvoke({"query": "echo contract"})

    assert len(requests) == 2
    tool_messages = [message for message in result["messages"] if message.type == "tool"]
    assert tool_messages and tool_messages[0].name == "echo"
    assert tool_messages[0].content == "echoed:contract"
    assert result["response"] == "final public answer"
    assert "reasoning" not in str(result)
    assert not result.get("error")

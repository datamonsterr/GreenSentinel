"""Small bridge from LangChain chat models to the native Google content seam."""

from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from typing import Any

from google import genai
from google.genai import types
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.runnables import Runnable

from src.config import Settings
from src.services.llm import _usable_key, get_llm, resolve_llm_config


def message_text(message: Any) -> str:
    """Return public text blocks only; reasoning blocks never enter user responses."""
    content = getattr(message, "content", message)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            str(block.get("text", "")) for block in content if isinstance(block, dict) and block.get("type") == "text"
        )
    return ""


def _lower_schema(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            k: (str(v).lower() if k == "type" and isinstance(v, str) else _lower_schema(v)) for k, v in value.items()
        }
    if isinstance(value, list):
        return [_lower_schema(v) for v in value]
    return value


class _ModelProxy:
    def __init__(self, adapter: ContentAdapter) -> None:
        self._adapter = adapter

    def generate_content(self, *, model: str, contents: Any, config: Any = None) -> Any:
        return self._adapter.generate_content(model=model, contents=contents, config=config)


class ContentAdapter:
    """Expose ``client.models.generate_content`` for native RAG callers."""

    def __init__(
        self,
        settings: Settings,
        api_key: str | None = None,
        model: str | None = None,
        temperature: float | None = None,
        seed: int | None = None,
    ) -> None:
        self._settings = settings
        self.config = resolve_llm_config(settings)
        if api_key is not None:
            self.config = replace(self.config, api_key=api_key)
        self.model_name = model or self.config.model
        self.temperature = temperature
        self.seed = seed
        self.client: genai.Client | ContentAdapter | None = None
        self.models = _ModelProxy(self)
        usable = _usable_key(self.config.api_key)
        if self.config.provider == "gemini" and usable:
            self.client = genai.Client(api_key=api_key or self.config.api_key, vertexai=False)
        elif self.config.provider != "gemini" and usable:
            self.client = self

    def generate_content(self, *, model: str, contents: Any, config: Any = None) -> Any:
        if self.config.provider == "gemini":
            if self.client is None:
                raise RuntimeError("gemini LLM credentials are not configured")
            effective_config = config
            if self.temperature is not None and effective_config is None:
                effective_config = types.GenerateContentConfig(temperature=self.temperature, seed=self.seed)
            return self.client.models.generate_content(model=model, contents=contents, config=effective_config)
        base_llm = get_llm(
            self._settings,
            provider=self.config.provider,
            api_key=self.config.api_key,
            model=model or self.model_name,
            temperature=self.temperature,
            seed=self.seed,
        )
        llm: Runnable = self._bind_tools(base_llm, config)
        messages = self._messages(contents, config)
        result = llm.invoke(messages)
        return self._to_google_response(result)

    async def agenerate_content(self, *, model: str, contents: Any, config: Any = None) -> Any:
        if self.config.provider == "gemini":
            return await asyncio.to_thread(self.generate_content, model=model, contents=contents, config=config)
        base_llm = get_llm(
            self._settings,
            provider=self.config.provider,
            api_key=self.config.api_key,
            model=model or self.model_name,
            temperature=self.temperature,
            seed=self.seed,
        )
        llm = self._bind_tools(base_llm, config)
        result = await llm.ainvoke(self._messages(contents, config))
        return self._to_google_response(result)

    def _bind_tools(self, llm: BaseChatModel, config: Any) -> Runnable:
        declarations = []
        for tool in getattr(config, "tools", []) or []:
            for declaration in getattr(tool, "function_declarations", []) or []:
                schema = getattr(declaration, "parameters_json_schema", None) or getattr(
                    declaration, "parameters", None
                )
                if schema is not None and hasattr(schema, "model_dump"):
                    schema = schema.model_dump(exclude_none=True, by_alias=True, mode="json")
                declarations.append(
                    {
                        "type": "function",
                        "function": {
                            "name": declaration.name,
                            "description": declaration.description or "",
                            "parameters": _lower_schema(schema or {}),
                        },
                    }
                )
        if declarations:
            mode = getattr(getattr(config, "tool_config", None), "function_calling_config", None)
            options = {"max_tokens": config.max_output_tokens} if getattr(config, "max_output_tokens", None) else {}
            return llm.bind_tools(
                declarations, tool_choice="required" if getattr(mode, "mode", "") == "ANY" else "auto", **options
            )
        if getattr(config, "max_output_tokens", None):
            return llm.bind(max_tokens=config.max_output_tokens)
        return llm

    def _messages(self, contents: Any, config: Any = None) -> list[BaseMessage]:
        messages: list[BaseMessage] = []
        system = getattr(config, "system_instruction", None) if config is not None else None
        if system:
            messages.append(SystemMessage(content=system))
        pending: dict[str, list[str]] = {}
        if isinstance(contents, str):
            return messages + [HumanMessage(content=contents)]
        call_ordinal = 0
        for content in contents if isinstance(contents, list) else [contents]:
            role = getattr(content, "role", "user")
            parts = getattr(content, "parts", None) or []
            text = "".join(getattr(part, "text", "") or "" for part in parts if not getattr(part, "thought", False))
            calls = []
            responses = []
            for part in parts:
                call = getattr(part, "function_call", None)
                if call:
                    call_id = getattr(call, "id", None) or f"call_{call_ordinal}"
                    call_ordinal += 1
                    calls.append({"name": call.name, "args": dict(call.args or {}), "id": call_id, "type": "tool_call"})
                    pending.setdefault(call.name, []).append(call_id)
                response = getattr(part, "function_response", None)
                if response:
                    queue = pending.get(getattr(response, "name", ""), [])
                    explicit_id = getattr(response, "id", None)
                    if explicit_id:
                        if explicit_id not in queue:
                            raise ValueError("Tool response ID does not match call")
                        queue.remove(explicit_id)
                        queue_id = explicit_id
                    elif queue:
                        queue_id = queue.pop(0)
                    else:
                        raise ValueError("Tool response has no matching call")
                    responses.append((queue_id, response.response or {}))
            if calls:
                messages.append(AIMessage(content=text, tool_calls=calls))
            elif responses:
                for rid, value in responses:
                    messages.append(
                        ToolMessage(content=json.dumps(value, ensure_ascii=False, default=str), tool_call_id=rid)
                    )
            elif text or role == "user":
                messages.append(HumanMessage(content=text) if role == "user" else AIMessage(content=text))
        return messages

    @property
    def config_settings(self) -> Settings:
        return self._settings

    def _to_google_response(self, message: AIMessage) -> types.GenerateContentResponse:
        parts = []
        for call in getattr(message, "tool_calls", []) or []:
            name = call.get("name") if isinstance(call, dict) else None
            if not name:
                continue
            parts.append(
                types.Part(function_call=types.FunctionCall(id=call.get("id"), name=name, args=call.get("args") or {}))
            )
        text = message_text(message)
        if text:
            parts.append(types.Part(text=text))
        return types.GenerateContentResponse(candidates=[types.Candidate(content=types.Content(parts=parts))])

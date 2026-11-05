"""Actual chat-completion payloads must suit the configured GPT-6 model."""

import json

import httpx
import pytest
from openai import OpenAI

from src.config import Settings
from src.services.llm import get_llm


@pytest.mark.parametrize("with_tools", [False, True])
def test_gpt6_tool_payload_omits_sampling_and_selects_supported_reasoning(with_tools):
    def provider(request):
        payload = json.loads(request.content)
        assert payload["model"] == "gpt-6-luna"
        assert request.url.path == "/v1/chat/completions"
        assert "temperature" not in payload
        assert payload["reasoning_effort"] == "none"
        if with_tools:
            assert payload["tools"][0]["function"]["name"] == "check_evidence"
        return httpx.Response(
            200,
            json={
                "id": "completion",
                "object": "chat.completion",
                "created": 0,
                "model": "gpt-6-luna",
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": "Recorded evidence"},
                    }
                ],
            },
        )

    with httpx.Client(transport=httpx.MockTransport(provider)) as transport:
        sdk = OpenAI(api_key="synthetic-unit-key", http_client=transport, max_retries=0)
        settings = Settings(
            _env_file=None,
            llm_model="openai",
            openai_api_key="synthetic-unit-key",
            openai_model="gpt-6-luna",
            llm_temperature=0.7,
        )
        model = get_llm(settings).model_copy(update={"client": sdk.chat.completions, "root_client": sdk})
        bound = (
            model.bind_tools(
                [
                    {
                        "type": "function",
                        "function": {
                            "name": "check_evidence",
                            "description": "Check case",
                            "parameters": {"type": "object", "properties": {}},
                        },
                    }
                ]
            )
            if with_tools
            else model
        )
        response = bound.invoke("Check this case")
    assert response.content == "Recorded evidence"


def test_gpt4_keeps_configured_sampling():
    settings = Settings(
        _env_file=None,
        llm_model="openai",
        openai_api_key="synthetic-unit-key",
        openai_model="gpt-4o-mini",
        llm_temperature=0.7,
    )
    assert get_llm(settings).temperature == 0.7

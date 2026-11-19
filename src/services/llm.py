import re
from dataclasses import dataclass, field
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_openai import ChatOpenAI
from pydantic import SecretStr

from src.config import Settings, get_settings


@dataclass(frozen=True)
class LLMConfig:
    provider: str
    model: str
    api_key: str = field(repr=False)
    base_url: str | None = None


def _usable_key(value: str | None) -> bool:
    if not value:
        return False
    normalized = value.strip().lower()
    return bool(
        normalized
        and not re.fullmatch(r"(?:test(?:-key)?|mock(?:-key)?|placeholder|none)", normalized)
        and not normalized.startswith(("your-", "your_"))
        and "api-key" not in normalized
        and "sk-or-v1-your-" not in normalized
        and normalized != "unconfigured-openrouter-key"
        and not normalized.endswith(".env.example")
    )


def resolve_llm_config(settings: Settings | None = None, provider: str | None = None) -> LLMConfig:
    s = settings or get_settings()
    selected = provider or s.llm_model
    if selected not in {"gemini", "openai", "openrouter"}:
        raise ValueError(f"Unsupported LLM provider: {selected}")
    if selected == "gemini":
        return LLMConfig(selected, s.gemini_model, s.gemini_api_key)
    if selected == "openai":
        return LLMConfig(selected, s.openai_model, s.openai_api_key)
    return LLMConfig(selected, s.openrouter_model, s.openrouter_api_key, s.openrouter_base_url)


def get_llm(
    settings: Settings | None = None,
    provider: str | None = None,
    api_key: str | None = None,
    model: str | None = None,
    temperature: float | None = None,
    seed: int | None = None,
) -> BaseChatModel:
    s = settings or get_settings()
    config = resolve_llm_config(s, provider)
    if api_key is not None:
        config = LLMConfig(config.provider, config.model, api_key, config.base_url)
    if model is not None:
        config = LLMConfig(config.provider, model, config.api_key, config.base_url)
    if not _usable_key(config.api_key):
        raise RuntimeError(f"{config.provider} LLM credentials are not configured")
    temp = temperature if temperature is not None else s.llm_temperature
    if config.provider == "gemini":
        from langchain_google_genai import ChatGoogleGenerativeAI

        return ChatGoogleGenerativeAI(
            model=config.model,
            google_api_key=config.api_key,
            temperature=temp,
            max_retries=1,
            timeout=35,
            vertexai=False,
        )
    options: dict[str, Any] = {"temperature": temp}
    if config.provider == "openai" and config.model.startswith("gpt-6-luna"):
        # Luna's Chat Completions tool calls require non-reasoning mode.
        # Omit sampling parameters rather than sending a legacy temperature.
        options = {"reasoning_effort": "none", "use_responses_api": False}
    if config.provider == "openrouter":
        # Reasoning is mandatory on some models (GLM 5.3 Flash); cap effort for chat latency.
        options["extra_body"] = {"reasoning": {"effort": s.openrouter_reasoning_effort}}
    if seed is not None:
        options["seed"] = seed
    return ChatOpenAI(
        model=config.model,
        api_key=SecretStr(config.api_key),
        base_url="https://api.openai.com/v1" if config.provider == "openai" else config.base_url,
        timeout=35.0,
        max_retries=2,
        **options,
    )

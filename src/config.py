from functools import lru_cache
from typing import Any, Literal

from pydantic import AliasChoices, Field, field_validator

try:
    from pydantic_settings import BaseSettings, SettingsConfigDict
except ImportError:
    from pydantic import BaseModel as BaseSettings  # type: ignore[assignment,no-redef]
    from pydantic import ConfigDict as SettingsConfigDict  # type: ignore[assignment,no-redef]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    def __init__(self, **values):
        explicit = {
            key: values[key]
            for key in ("llm_model", "openai_api_key", "openrouter_api_key", "gemini_api_key", "openai_model")
            if key in values
        }
        super().__init__(**values)
        for key, value in explicit.items():
            object.__setattr__(self, key, value)

    # App
    app_name: str = "AI20K Agent"
    app_env: Literal["development", "production", "staging", "test"] = "development"
    test_auth_enabled: bool = False
    app_port: int = Field(default=8000, ge=1, le=65535)
    app_host: str = "0.0.0.0"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    # Normalized external traffic gateway; unset means evidence is unavailable.
    traffic_incidents_url: str = ""
    traffic_api_key: str = ""
    traffic_timeout_seconds: float = Field(default=3.0, gt=0, le=8.0)
    cors_origins: str = Field(
        default="http://localhost:3000,http://127.0.0.1:3000,http://localhost:3100,http://127.0.0.1:3100,https://green-sentinel.vercel.app,https://greensentinel.vercel.app,https://staging.green-sentinel.vercel.app,https://staging-green-sentinel.vercel.app,https://green-sentinel-dev.vercel.app,https://dev.green-sentinel.vercel.app,https://dev-green-sentinel.vercel.app",
        validation_alias=AliasChoices("cors_origins", "CORS_ORIGINS"),
    )

    # Clerk verifies browser sessions; authorization remains in app.principal_roles.
    clerk_secret_key: str = Field(
        default="",
        validation_alias=AliasChoices("clerk_secret_key", "CLERK_SECRET_KEY"),
    )
    clerk_jwt_key: str = Field(
        default="",
        validation_alias=AliasChoices("clerk_jwt_key", "CLERK_JWT_KEY"),
    )
    clerk_jwks_url: str = Field(
        default="https://clever-turtle-156.clerk.accounts.dev/.well-known/jwks.json",
        validation_alias=AliasChoices("clerk_jwks_url", "CLERK_JWKS_URL"),
    )
    clerk_issuer: str = Field(
        default="https://clever-turtle-156.clerk.accounts.dev",
        validation_alias=AliasChoices("clerk_issuer", "CLERK_ISSUER"),
    )
    clerk_publishable_key: str = Field(
        default="",
        validation_alias=AliasChoices(
            "clerk_publishable_key",
            "CLERK_PUBLISHABLE_KEY",
            "NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY",
        ),
    )
    clerk_authorized_parties: str = Field(
        default="http://localhost:3000,http://127.0.0.1:3000,http://localhost:3100,http://127.0.0.1:3100,https://green-sentinel.vercel.app,https://greensentinel.vercel.app,https://staging.green-sentinel.vercel.app,https://staging-green-sentinel.vercel.app,https://green-sentinel-dev.vercel.app,https://dev.green-sentinel.vercel.app,https://dev-green-sentinel.vercel.app",
        validation_alias=AliasChoices("clerk_authorized_parties", "CLERK_AUTHORIZED_PARTIES"),
    )
    clerk_audience: str = Field(
        default="",
        validation_alias=AliasChoices("clerk_audience", "CLERK_AUDIENCE"),
    )

    # LLM & Gemini
    llm_model: Literal["openai", "gemini", "openrouter"] = Field(
        default="gemini", validation_alias=AliasChoices("llm_model", "LLM_MODEL")
    )
    openai_api_key: str = Field(default="", validation_alias=AliasChoices("openai_api_key", "OPENAI_API_KEY"))
    openai_model: str = Field(
        default="gpt-4o-mini",
        validation_alias=AliasChoices("openai_model", "OPENAI_MODEL", "MODEL_NAME", "model_name"),
    )
    model_name: str = "gpt-4o-mini"
    llm_temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    gemini_api_key: str = Field(
        default="",
        validation_alias=AliasChoices("gemini_api_key", "GEMINI_API_KEY", "GOOGLE_API_KEY"),
    )
    gemini_model: str = Field(
        default="gemini-3.5-flash-lite",
        validation_alias=AliasChoices("gemini_model", "GEMINI_MODEL"),
    )

    # Evaluation LLM Judge Configuration (Pinned Determinism)
    eval_judge_model: str = Field(
        default="gpt-4o-mini",
        validation_alias=AliasChoices("eval_judge_model", "EVAL_JUDGE_MODEL"),
    )
    eval_judge_temperature: float = Field(
        default=0.0,
        ge=0.0,
        le=2.0,
        validation_alias=AliasChoices("eval_judge_temperature", "EVAL_JUDGE_TEMPERATURE"),
    )
    eval_judge_seed: int = Field(
        default=42,
        validation_alias=AliasChoices("eval_judge_seed", "EVAL_JUDGE_SEED"),
    )

    # Project Jev & OpenRouter
    project_jev_api_key: str = Field(
        default="",
        validation_alias=AliasChoices(
            "project_jev_api_key",
            "PROJECT_JEV_API_KEY",
            "PROJECT_JEV_TEST_API_KEY",
            "OPENROUTER_API_KEY",
            "JEV_API_KEY",
        ),
    )
    project_jev_model: str = Field(
        default="inception/mercury-decide:free",
        validation_alias=AliasChoices(
            "project_jev_model",
            "PROJECT_JEV_MODEL",
        ),
    )
    jev_fallback_models: list[str] | str = Field(
        default_factory=lambda: ["perplexity/pplx-decider-flash-v1.2"],
        validation_alias=AliasChoices(
            "jev_fallback_models",
            "JEV_FALLBACK_MODELS",
        ),
    )
    jev_allow_heuristic_fallback: bool = Field(
        default=False,
        validation_alias=AliasChoices(
            "jev_allow_heuristic_fallback",
            "JEV_ALLOW_HEURISTIC_FALLBACK",
        ),
    )
    project_jev_base_url: str = Field(
        default="https://openrouter.ai/api/v1",
        validation_alias=AliasChoices(
            "project_jev_base_url",
            "PROJECT_JEV_BASE_URL",
            "OPENROUTER_BASE_URL",
        ),
    )
    openrouter_api_key: str = Field(
        default="",
        validation_alias=AliasChoices(
            "openrouter_api_key",
            "OPENROUTER_API_KEY",
        ),
    )
    openrouter_base_url: str = Field(
        default="https://openrouter.ai/api/v1",
        validation_alias=AliasChoices(
            "openrouter_base_url",
            "OPENROUTER_BASE_URL",
        ),
    )
    openrouter_model: str = Field(
        default="google/gemini-3.5-flash-lite",
        validation_alias=AliasChoices(
            "openrouter_model",
            "OPENROUTER_MODEL",
        ),
    )

    @field_validator("jev_fallback_models", mode="before")
    @classmethod
    def _parse_jev_fallback_models(cls, v: Any) -> list[str]:
        if v is None:
            return ["perplexity/pplx-decider-flash-v1.2"]
        if isinstance(v, str):
            v_str = v.strip()
            if not v_str:
                return []
            if v_str.startswith("[") and v_str.endswith("]"):
                try:
                    import json

                    parsed = json.loads(v_str)
                    if isinstance(parsed, list):
                        return [str(m).strip() for m in parsed if str(m).strip()]
                except Exception:
                    pass
            return [m.strip() for m in v_str.split(",") if m.strip()]
        if isinstance(v, (list, tuple, set)):
            return [str(m).strip() for m in v if str(m).strip()]
        return [str(v)]

    driver_agent_model: str = Field(
        default="",
        validation_alias=AliasChoices(
            "driver_agent_model",
            "DRIVER_AGENT_MODEL",
        ),
    )
    driver_formatter_enabled: bool = Field(
        default=True,
        validation_alias=AliasChoices(
            "driver_formatter_enabled",
            "DRIVER_FORMATTER_ENABLED",
        ),
    )
    driver_agent_timeout_seconds: float = Field(
        default=45.0,
        validation_alias=AliasChoices(
            "driver_agent_timeout_seconds",
            "DRIVER_AGENT_TIMEOUT_SECONDS",
        ),
    )
    jev_model: str = Field(
        default="inception/mercury-decide:free",
        validation_alias=AliasChoices(
            "jev_model",
            "JEV_MODEL",
        ),
    )
    agent_context_window: int = Field(
        default=1_048_576,
        validation_alias=AliasChoices(
            "agent_context_window",
            "AGENT_CONTEXT_WINDOW",
        ),
    )

    # Production Fraud Classifier (Slice W2)
    fraud_classifier_enabled: bool = Field(
        default=True,
        validation_alias=AliasChoices(
            "fraud_classifier_enabled",
            "FRAUD_CLASSIFIER_ENABLED",
        ),
    )
    classifier_llm_advisory: bool = Field(
        default=True,
        validation_alias=AliasChoices(
            "classifier_llm_advisory",
            "CLASSIFIER_LLM_ADVISORY",
        ),
    )
    classifier_advisory_timeout_s: float = Field(
        default=8.0,
        gt=0.0,
        validation_alias=AliasChoices(
            "classifier_advisory_timeout_s",
            "CLASSIFIER_ADVISORY_TIMEOUT_S",
        ),
    )
    classifier_batch_max: int = Field(
        default=64,
        ge=1,
        validation_alias=AliasChoices(
            "classifier_batch_max",
            "CLASSIFIER_BATCH_MAX",
        ),
    )

    # Database
    database_url: str = Field(
        default="postgresql://postgres:postgrespassword@localhost:5432/postgres",
        validation_alias=AliasChoices("database_url", "DATABASE_URL"),
    )
    test_database_url: str = Field(
        default="",
        validation_alias=AliasChoices("test_database_url", "TEST_DATABASE_URL"),
    )

    # Redis
    redis_url: str = Field(
        default="redis://localhost:6379/0",
        validation_alias=AliasChoices("redis_url", "REDIS_URL"),
    )

    # Supabase PostgREST
    supabase_project_id: str = Field(
        default="",
        validation_alias=AliasChoices(
            "supabase_project_id",
            "NEXT_PUBLIC_SUPABASE_PROJECT_ID",
            "NEXT_PUBLIC_SUPABSE_PROJECT_ID",
        ),
    )
    supabase_secret_key: str = Field(
        default="",
        validation_alias=AliasChoices("supabase_secret_key", "SUPABASE_SECRET_KEY"),
    )
    next_public_supabse_project_id: str = Field(
        default="",
        validation_alias=AliasChoices(
            "next_public_supabse_project_id",
            "NEXT_PUBLIC_SUPABSE_PROJECT_ID",
            "NEXT_PUBLIC_SUPABASE_PROJECT_ID",
        ),
    )

    # Vector Store (Qdrant)
    qdrant_url: str = Field(
        default="http://localhost:6333",
        validation_alias=AliasChoices("qdrant_url", "QDRANT_URL"),
    )
    qdrant_cluster_url: str = Field(
        default="",
        validation_alias=AliasChoices("qdrant_cluster_url", "QDRANT_CLUSTER_URL"),
    )
    qdrant_api_key: str = Field(
        default="",
        validation_alias=AliasChoices("qdrant_api_key", "QDRANT_API_KEY"),
    )
    qdrant_dev_api_key: str = Field(
        default="",
        validation_alias=AliasChoices("qdrant_dev_api_key", "QDRANT_DEV_API_KEY"),
    )
    qdrant_test_api_key: str = Field(
        default="",
        validation_alias=AliasChoices("qdrant_test_api_key", "QDRANT_TEST_API_KEY", "QDRANT_STAGING_API_KEY"),
    )
    qdrant_prod_api_key: str = Field(
        default="",
        validation_alias=AliasChoices("qdrant_prod_api_key", "QDRANT_PROD_API_KEY"),
    )
    qdrant_collection: str = Field(
        default="",
        validation_alias=AliasChoices("qdrant_collection", "QDRANT_COLLECTION"),
    )
    rag_embedding_provider: Literal["openai", "gemini"] = Field(
        default="openai",
        validation_alias=AliasChoices("rag_embedding_provider", "RAG_EMBEDDING_PROVIDER"),
    )
    geoapify_api_key: str = Field(
        default="",
        validation_alias=AliasChoices("geoapify_api_key", "GEOAPIFY_API_KEY"),
    )

    @property
    def effective_qdrant_collection(self) -> str:
        if self.qdrant_collection:
            return self.qdrant_collection
        prefix = "prod" if self.app_env == "production" else "test" if self.app_env in ("staging", "test") else "dev"
        collection = f"{prefix}-policies"
        if self.rag_embedding_provider == "openai":
            return f"{collection}-openai-text-embedding-3-small-1536"
        return collection

    @property
    def effective_qdrant_api_key(self) -> str:
        if self.qdrant_api_key:
            return self.qdrant_api_key
        if self.app_env == "production":
            return self.qdrant_prod_api_key
        if self.app_env in ("staging", "test"):
            return self.qdrant_test_api_key
        return self.qdrant_dev_api_key

    @property
    def effective_qdrant_url(self) -> str:
        if self.qdrant_cluster_url:
            return self.qdrant_cluster_url
        return self.qdrant_url

    @property
    def supabase_rest_url(self) -> str:
        project_id = self.supabase_project_id or self.next_public_supabse_project_id
        if project_id:
            return f"https://{project_id}.supabase.co/rest/v1"
        return "http://localhost:54321/rest/v1"


@lru_cache
def get_settings() -> Settings:
    return Settings()

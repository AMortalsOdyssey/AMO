import json

from pydantic import field_validator
from pydantic_settings import BaseSettings

DEBUG_TRUE_VALUES = {"1", "true", "t", "yes", "y", "on", "debug", "dev", "development"}
DEBUG_FALSE_VALUES = {"0", "false", "f", "no", "n", "off", "release", "prod", "production"}


class Settings(BaseSettings):
    # PostgreSQL
    pg_dsn: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/amo_canon"
    pg_schema: str = "amo"
    pg_pool_size: int = 10

    # Neo4j
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "neo4j"

    # Zilliz
    zilliz_uri: str = "http://localhost:19530"
    zilliz_token: str = ""
    zilliz_db: str = "ai_social_memory"
    zilliz_event_collection: str = "event_embeddings"
    zilliz_persona_collection: str = "persona_embeddings"
    zilliz_technique_collection: str = "technique_embeddings"
    zilliz_text_chunk_collection: str = "text_chunks"

    # LLM
    llm_base_url: str = "http://localhost:8001/v1"
    llm_api_key: str = ""
    llm_model: str = "qwen3.5-plus"

    # Embedding
    embedding_provider: str = "openai_compatible"
    embedding_base_url: str = "http://localhost:8002/v1"
    embedding_api_key: str = ""  # falls back to llm_api_key if empty
    embedding_model: str = "qwen3_embedding_8b_20250716_V1"
    embedding_output_dim: int = 1536
    vertex_ai_project: str = ""
    vertex_ai_location: str = "us-central1"

    # App
    cors_origins: list[str] = ["*"]
    debug: bool = False
    feedback_form_url: str | None = None
    posthog_public_key: str | None = None
    posthog_host: str = "https://us.i.posthog.com"
    public_app_url: str = "http://localhost:3000"
    support_email: str = "support@8xd.io"
    app_code: str = "amo"

    # Auth
    auth_enabled: bool = True
    auth_require_verified_email: bool = True
    auth_session_secret: str = "dev-only-change-me"
    auth_session_cookie_name: str = "amo_session"
    auth_session_ttl_days: int = 30
    auth_session_cookie_secure: bool = False
    auth_session_cookie_domain: str | None = None
    identity_platform_project_id: str | None = None
    identity_platform_service_account_path: str | None = None
    identity_platform_service_account_json: str | None = None

    # Billing
    billing_enabled: bool = True
    billing_admin_key: str | None = None
    billing_free_credits: int = 100
    billing_pack_product_key: str = "chat-pack-100"
    billing_pack_display_name: str = "100 extra dialogue credits"
    billing_pack_description: str = "Top up 100 extra AMO dialogue credits for one-time purchase."
    billing_pack_price_cents: int = 100
    billing_pack_currency: str = "USD"
    billing_pack_credit_amount: int = 100

    # Creem
    creem_mode: str = "local_mock"
    creem_api_key: str | None = None
    creem_product_id: str | None = None
    creem_webhook_secret: str | None = None
    creem_timeout_seconds: float = 20.0

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, v):
        """支持多种格式: '["*"]' / '*' / '*,http://localhost'"""
        if isinstance(v, list):
            return v
        if isinstance(v, str):
            v = v.strip()
            if v.startswith("["):
                return json.loads(v)
            return [x.strip() for x in v.split(",")]
        return v

    @field_validator("debug", mode="before")
    @classmethod
    def parse_debug(cls, v):
        if isinstance(v, bool):
            return v
        if isinstance(v, str):
            normalized = v.strip().lower()
            if normalized in DEBUG_TRUE_VALUES:
                return True
            if normalized in DEBUG_FALSE_VALUES:
                return False
        return v

    @property
    def creem_base_url(self) -> str:
        if self.creem_mode == "test":
            return "https://test-api.creem.io/v1"
        return "https://api.creem.io/v1"

    @property
    def billing_checkout_mode(self) -> str:
        if (
            self.creem_mode in {"test", "prod"}
            and self.creem_api_key
            and self.creem_product_id
        ):
            return self.creem_mode
        return "local_mock"

    @property
    def auth_cookie_max_age_seconds(self) -> int:
        return max(self.auth_session_ttl_days, 1) * 24 * 60 * 60

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()

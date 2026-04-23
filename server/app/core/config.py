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

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()

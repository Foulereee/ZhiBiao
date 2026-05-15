from __future__ import annotations

from pydantic_settings import BaseSettings
from pathlib import Path


class Settings(BaseSettings):
    app_name: str = "BidMaster Pro"
    debug: bool = True
    host: str = "0.0.0.0"
    port: int = 8000

    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/bidmaster"
    redis_url: str = "redis://localhost:6379/0"
    chroma_dir: str = "./chroma_db"
    minio_endpoint: str = "localhost:9000"
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin"
    minio_bucket: str = "bidmaster"
    projects_root: str = "./projects"

    llm_default_model: str = "deepseek/deepseek-chat"
    llm_api_key: str = ""
    llm_api_base: str = "https://api.deepseek.com"
    llm_fallback_models: str = "ollama/qwen2.5"
    llm_max_retries: int = 3

    embedding_mode: str = "api"
    embedding_model: str = "text-embedding-v3"
    embedding_api_key: str = ""
    embedding_api_base: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"

    model_config = {"env_file": ".env", "env_prefix": "BMP_"}


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings

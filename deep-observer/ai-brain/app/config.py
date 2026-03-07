from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


def load_flexible_env(env_path: str = ".env") -> None:
    path = Path(env_path)
    if path.exists():
        load_dotenv(path, override=False)
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if ":" in line and "=" not in line:
                key, value = line.split(":", 1)
                os.environ.setdefault(key.strip().upper(), value.strip().strip("\"'"))


@dataclass(frozen=True)
class Settings:
    project_id: str
    cluster_id: str
    namespace_filter: str
    service_filter: str
    postgres_host: str
    postgres_port: int
    postgres_db: str
    postgres_user: str
    postgres_password: str
    clickhouse_host: str
    clickhouse_port: int
    clickhouse_http_port: int
    clickhouse_database: str
    clickhouse_username: str
    clickhouse_password: str
    poll_interval_seconds: int
    llm_provider: str
    llm_auto_large_context_chars: int
    ollama_base_url: str
    ollama_api_key: str
    ollama_model: str
    openai_base_url: str
    openai_api_key: str
    openai_model: str
    llm_timeout_seconds: int
    llm_max_retries: int


def get_settings() -> Settings:
    load_flexible_env()
    settings = Settings(
        project_id=os.getenv("PROJECT_ID", "default-project"),
        cluster_id=os.getenv("CLUSTER_ID", ""),
        namespace_filter=os.getenv("NAMESPACE_FILTER", ""),
        service_filter=os.getenv("SERVICE_FILTER", ""),
        postgres_host=os.getenv("POSTGRES_HOST", "localhost"),
        postgres_port=int(os.getenv("POSTGRES_PORT", "5432")),
        postgres_db=os.getenv("POSTGRES_DB", "deep_observer"),
        postgres_user=os.getenv("POSTGRES_USER", "deep_observer"),
        postgres_password=os.getenv("POSTGRES_PASSWORD", "deep_observer"),
        clickhouse_host=os.getenv("CLICKHOUSE_HOST", "localhost"),
        clickhouse_port=int(os.getenv("CLICKHOUSE_PORT", "9000")),
        clickhouse_http_port=int(os.getenv("CLICKHOUSE_HTTP_PORT", "8123")),
        clickhouse_database=os.getenv("CLICKHOUSE_DATABASE", "default"),
        clickhouse_username=os.getenv("CLICKHOUSE_USER", os.getenv("CLICKHOUSE_USERNAME", "default")),
        clickhouse_password=os.getenv("CLICKHOUSE_PASSWORD", ""),
        poll_interval_seconds=int(os.getenv("POLL_INTERVAL_SECONDS", "30")),
        llm_provider=os.getenv("LLM_PROVIDER", "ollama_cloud"),
        llm_auto_large_context_chars=int(os.getenv("LLM_AUTO_LARGE_CONTEXT_CHARS", "24000")),
        ollama_base_url=os.getenv("OLLAMA_BASE_URL", "https://api.ollama.com"),
        ollama_api_key=os.getenv("OLLAMA_API_KEY", os.getenv("OLLAMA_API_KEY".lower(), "")),
        ollama_model=os.getenv("OLLAMA_MODEL", "llama3.1:8b"),
        openai_base_url=os.getenv("OPENAI_BASE_URL", "https://api.openai.com"),
        openai_api_key=os.getenv("OPENAI_API_KEY", os.getenv("OPENAI_CLOUD_API_KEY", "")),
        openai_model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
        llm_timeout_seconds=int(os.getenv("LLM_TIMEOUT_SECONDS", "120")),
        llm_max_retries=int(os.getenv("LLM_MAX_RETRIES", "3")),
    )
    validate_settings(settings)
    return settings


def validate_settings(settings: Settings) -> None:
    provider = settings.llm_provider.lower()
    if provider in {"ollama", "ollama_cloud", "auto", "multi"} and not settings.ollama_api_key:
        raise RuntimeError("OLLAMA_API_KEY is required when using Ollama-based reasoning")
    if provider in {"openai", "openai_api"} and not settings.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY is required when using OpenAI-based reasoning")

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Literal


LlmProvider = Literal["ollama", "openai"]


@dataclass(frozen=True)
class HttpSettings:
    timeout_seconds: int = 30
    attempts: int = 3


@dataclass(frozen=True)
class TelemetrySettings:
    default_namespace: str = "dev"
    default_service: str = "all"
    default_severity: str = "warning"
    default_window_minutes: int = 30


@dataclass(frozen=True)
class LlmSettings:
    provider: LlmProvider = "ollama"
    model: str = "gpt-oss:20b"
    ollama_url: str = "https://ollama.com"
    openai_base_url: str = "https://api.openai.com/v1"
    ollama_api_key: str = ""
    openai_api_key: str = ""


@dataclass(frozen=True)
class ObservabilitySettings:
    prometheus_url: str = "http://prometheus:9090"
    loki_url: str = "http://loki-gateway:80"
    jaeger_url: str = "http://jaeger-query:16686"


@dataclass(frozen=True)
class DatabaseSettings:
    url: str = "postgresql+psycopg://postgres:postgres@postgres:5432/ai_observer"
    echo_sql: bool = False


@dataclass(frozen=True)
class AppSettings:
    telemetry: TelemetrySettings
    llm: LlmSettings
    observability: ObservabilitySettings
    http: HttpSettings
    database: DatabaseSettings


def _to_int(value: str | None, default: int, min_value: int, max_value: int) -> int:
    if value is None:
        return default
    try:
        parsed = int(value)
    except ValueError:
        return default
    return max(min_value, min(max_value, parsed))


def load_settings() -> AppSettings:
    provider = os.getenv("LLM_PROVIDER", "ollama").strip().lower()
    if provider not in {"ollama", "openai"}:
        provider = "ollama"

    openai_api_key = os.getenv("OPENAI_API_KEY", "").strip()
    ollama_api_key = os.getenv("OLLAMA_API_KEY", openai_api_key).strip()

    telemetry = TelemetrySettings(
        default_namespace=os.getenv("DEFAULT_NAMESPACE", "dev").strip() or "dev",
        default_service=os.getenv("DEFAULT_SERVICE", "all").strip() or "all",
        default_severity=os.getenv("DEFAULT_SEVERITY", "warning").strip() or "warning",
        default_window_minutes=_to_int(os.getenv("DEFAULT_WINDOW_MINUTES"), 30, 5, 360),
    )

    llm = LlmSettings(
        provider=provider,  # type: ignore[arg-type]
        model=os.getenv("LLM_MODEL", "gpt-oss:20b").strip() or "gpt-oss:20b",
        ollama_url=os.getenv("OLLAMA_URL", "https://ollama.com").strip().rstrip("/"),
        openai_base_url=os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").strip().rstrip("/"),
        ollama_api_key=ollama_api_key,
        openai_api_key=openai_api_key,
    )

    observability = ObservabilitySettings(
        prometheus_url=os.getenv("PROMETHEUS_URL", "http://prometheus:9090").strip().rstrip("/"),
        loki_url=os.getenv("LOKI_URL", "http://loki-gateway:80").strip().rstrip("/"),
        jaeger_url=os.getenv("JAEGER_URL", "http://jaeger-query:16686").strip().rstrip("/"),
    )

    http = HttpSettings(
        timeout_seconds=_to_int(
            os.getenv("HTTP_TIMEOUT_SECONDS", os.getenv("LLM_TIMEOUT_SECONDS", "30")),
            default=30,
            min_value=2,
            max_value=600,
        ),
        attempts=_to_int(os.getenv("HTTP_ATTEMPTS", os.getenv("LLM_ATTEMPTS", "3")), default=3, min_value=1, max_value=10),
    )

    database = DatabaseSettings(
        url=os.getenv("DATABASE_URL", "postgresql+psycopg://postgres:postgres@postgres:5432/ai_observer").strip(),
        echo_sql=(os.getenv("DB_ECHO_SQL", "false").strip().lower() in {"1", "true", "yes", "on"}),
    )

    return AppSettings(telemetry=telemetry, llm=llm, observability=observability, http=http, database=database)

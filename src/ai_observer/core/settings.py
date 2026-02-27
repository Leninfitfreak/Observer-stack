from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Literal

from dotenv import load_dotenv


LlmProvider = Literal["ollama", "openai"]


@dataclass(frozen=True)
class HttpSettings:
    timeout_seconds: int = 30
    attempts: int = 3


@dataclass(frozen=True)
class TelemetrySettings:
    default_namespace: str = "default"
    default_service: str = "all"
    default_severity: str = "warning"
    default_window_minutes: int = 30
    default_cluster_id: str = ""


@dataclass(frozen=True)
class LlmSettings:
    provider: LlmProvider = "ollama"
    model: str = ""
    ollama_url: str = ""
    openai_base_url: str = ""
    ollama_api_key: str = ""
    openai_api_key: str = ""


@dataclass(frozen=True)
class ObservabilitySettings:
    prometheus_url: str = ""
    loki_url: str = ""
    jaeger_url: str = ""


@dataclass(frozen=True)
class DatabaseSettings:
    url: str = ""
    echo_sql: bool = False


@dataclass(frozen=True)
class AppSettings:
    telemetry: TelemetrySettings
    llm: LlmSettings
    observability: ObservabilitySettings
    http: HttpSettings
    database: DatabaseSettings
    agent_token: str


def _to_int(value: str | None, default: int, min_value: int, max_value: int) -> int:
    if value is None:
        return default
    try:
        parsed = int(value)
    except ValueError:
        return default
    return max(min_value, min(max_value, parsed))


def load_settings() -> AppSettings:
    load_dotenv()
    provider = os.getenv("LLM_PROVIDER", "ollama").strip().lower()
    if provider not in {"ollama", "openai"}:
        provider = "ollama"

    openai_api_key = os.getenv("OPENAI_API_KEY", "").strip()
    ollama_api_key = os.getenv("OLLAMA_API_KEY", openai_api_key).strip()

    telemetry = TelemetrySettings(
        default_namespace=os.getenv("DEFAULT_NAMESPACE", "default").strip() or "default",
        default_service=os.getenv("DEFAULT_SERVICE", "all").strip() or "all",
        default_severity=os.getenv("DEFAULT_SEVERITY", "warning").strip() or "warning",
        default_window_minutes=_to_int(os.getenv("DEFAULT_WINDOW_MINUTES"), 30, 5, 360),
        default_cluster_id=os.getenv("CLUSTER_ID", "").strip(),
    )

    llm = LlmSettings(
        provider=provider,  # type: ignore[arg-type]
        model=os.getenv("LLM_MODEL", "").strip(),
        ollama_url=os.getenv("OLLAMA_URL", "").strip().rstrip("/"),
        openai_base_url=os.getenv("OPENAI_BASE_URL", "").strip().rstrip("/"),
        ollama_api_key=ollama_api_key,
        openai_api_key=openai_api_key,
    )

    observability = ObservabilitySettings(
        prometheus_url=os.getenv("PROMETHEUS_URL", "").strip().rstrip("/"),
        loki_url=os.getenv("LOKI_URL", "").strip().rstrip("/"),
        jaeger_url=os.getenv("JAEGER_URL", "").strip().rstrip("/"),
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
        url=os.getenv("DATABASE_URL", "").strip(),
        echo_sql=(os.getenv("DB_ECHO_SQL", "false").strip().lower() in {"1", "true", "yes", "on"}),
    )

    return AppSettings(
        telemetry=telemetry,
        llm=llm,
        observability=observability,
        http=http,
        database=database,
        agent_token=os.getenv("AGENT_TOKEN", "").strip(),
    )

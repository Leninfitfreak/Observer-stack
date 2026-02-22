from __future__ import annotations

from ai_observer.core.settings import LlmSettings
from ai_observer.domain.interfaces import LlmProvider
from ai_observer.infra.http_client import HttpClient
from ai_observer.providers.llm.ollama_cloud import OllamaCloudProvider
from ai_observer.providers.llm.openai_provider import OpenAIProvider


def create_llm_provider(settings: LlmSettings, http: HttpClient) -> LlmProvider:
    if settings.provider == "openai":
        return OpenAIProvider(
            base_url=settings.openai_base_url,
            model=settings.model,
            api_key=settings.openai_api_key,
            http=http,
        )

    return OllamaCloudProvider(
        base_url=settings.ollama_url,
        model=settings.model,
        api_key=settings.ollama_api_key,
        http=http,
    )

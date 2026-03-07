from __future__ import annotations

from ..config import Settings
from .openai_compatible import OpenAICompatibleProvider
from .ollama_cloud import OllamaCloudProvider
from .provider import LLMProvider


class MultiProviderClient(LLMProvider):
    def __init__(self, settings: Settings, ollama: LLMProvider, openai: LLMProvider | None) -> None:
        self.settings = settings
        self.ollama = ollama
        self.openai = openai

    def generate_reasoning(self, prompt: str) -> str:
        if self.settings.llm_provider in {"openai", "openai_api"} and self.openai is not None:
            return self.openai.generate_reasoning(prompt)
        if self.settings.llm_provider in {"ollama", "ollama_cloud"}:
            return self.ollama.generate_reasoning(prompt)
        if self.settings.llm_provider in {"auto", "multi"} and self.openai is not None:
            if len(prompt) >= self.settings.llm_auto_large_context_chars:
                return self.openai.generate_reasoning(prompt)
            return self.ollama.generate_reasoning(prompt)
        return self.ollama.generate_reasoning(prompt)


def build_llm_client(settings: Settings) -> LLMProvider:
    ollama = OllamaCloudProvider(settings)
    openai = OpenAICompatibleProvider(settings) if settings.openai_api_key else None
    return MultiProviderClient(settings, ollama, openai)

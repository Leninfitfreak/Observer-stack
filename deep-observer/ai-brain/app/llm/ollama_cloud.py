from __future__ import annotations

import requests
import time

from ..config import Settings
from .provider import LLMProvider


class OllamaCloudProvider(LLMProvider):
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def generate_reasoning(self, prompt: str) -> str:
        last_error: Exception | None = None
        for attempt in range(max(1, self.settings.llm_max_retries)):
            try:
                response = requests.post(
                    f"{self.settings.ollama_base_url.rstrip('/')}/api/generate",
                    headers={
                        "Authorization": f"Bearer {self.settings.ollama_api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": self.settings.ollama_model,
                        "prompt": prompt,
                        "stream": False,
                        "format": "json",
                    },
                    timeout=self.settings.llm_timeout_seconds,
                )
                response.raise_for_status()
                data = response.json()
                return data.get("response", "{}")
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                if attempt < self.settings.llm_max_retries - 1:
                    time.sleep(1.2 * (attempt + 1))
        if last_error is not None:
            raise last_error
        return "{}"

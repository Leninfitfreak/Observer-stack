from __future__ import annotations

import requests
import time

from ..config import Settings
from .provider import LLMProvider


class OpenAICompatibleProvider(LLMProvider):
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def generate_reasoning(self, prompt: str) -> str:
        last_error: Exception | None = None
        for attempt in range(max(1, self.settings.llm_max_retries)):
            try:
                response = requests.post(
                    f"{self.settings.openai_base_url.rstrip('/')}/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {self.settings.openai_api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": self.settings.openai_model,
                        "messages": [
                            {"role": "system", "content": "Respond only with valid JSON."},
                            {"role": "user", "content": prompt},
                        ],
                        "temperature": 0.1,
                        "response_format": {"type": "json_object"},
                    },
                    timeout=self.settings.llm_timeout_seconds,
                )
                response.raise_for_status()
                data = response.json()
                choices = data.get("choices") or []
                if not choices:
                    return "{}"
                message = choices[0].get("message") or {}
                return message.get("content") or "{}"
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                if attempt < self.settings.llm_max_retries - 1:
                    time.sleep(1.2 * (attempt + 1))
        if last_error is not None:
            raise last_error
        return "{}"

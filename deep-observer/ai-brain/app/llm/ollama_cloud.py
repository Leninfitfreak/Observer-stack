from __future__ import annotations

import logging
import requests
import time

from ..config import Settings
from .provider import LLMProvider


class ModelInvocationError(RuntimeError):
    def __init__(self, message: str, *, retriable: bool = False, status_code: int | None = None, response_body: str = "") -> None:
        super().__init__(message)
        self.retriable = retriable
        self.status_code = status_code
        self.response_body = response_body


class OllamaCloudProvider(LLMProvider):
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def generate_reasoning(self, prompt: str) -> str:
        last_error: Exception | None = None
        max_attempts = max(1, self.settings.llm_max_retries)
        for attempt in range(max(1, self.settings.llm_max_retries)):
            try:
                logging.info(
                    "reasoning_event=model_invocation_start provider=ollama_cloud model=%s attempt=%s/%s prompt_chars=%s",
                    self.settings.ollama_model,
                    attempt + 1,
                    max_attempts,
                    len(prompt),
                )
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
                if response.status_code >= 400:
                    body = (response.text or "").strip()
                    message = f"Ollama returned HTTP {response.status_code}"
                    if body:
                        message = f"{message}: {body}"
                    raise ModelInvocationError(
                        message,
                        retriable=response.status_code >= 500,
                        status_code=response.status_code,
                        response_body=body,
                    )
                data = response.json()
                logging.info(
                    "reasoning_event=model_invocation_success provider=ollama_cloud model=%s attempt=%s/%s",
                    self.settings.ollama_model,
                    attempt + 1,
                    max_attempts,
                )
                return data.get("response", "{}")
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                retriable = getattr(exc, "retriable", False) or isinstance(exc, requests.RequestException)
                logging.warning(
                    "reasoning_event=model_invocation_failure provider=ollama_cloud model=%s attempt=%s/%s retriable=%s error=%s",
                    self.settings.ollama_model,
                    attempt + 1,
                    max_attempts,
                    retriable,
                    exc,
                )
                if retriable and attempt < max_attempts - 1:
                    backoff_seconds = round(1.5 * (attempt + 1), 2)
                    logging.info(
                        "reasoning_event=model_invocation_retry provider=ollama_cloud model=%s next_attempt=%s/%s backoff_seconds=%s",
                        self.settings.ollama_model,
                        attempt + 2,
                        max_attempts,
                        backoff_seconds,
                    )
                    time.sleep(backoff_seconds)
        if last_error is not None:
            raise last_error
        return "{}"

from __future__ import annotations

from typing import Any

from ai_observer.infra.http_client import HttpClient
from ai_observer.providers.llm.ollama_cloud import PROMPT


class OpenAIProvider:
    def __init__(self, base_url: str, model: str, api_key: str, http: HttpClient):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key.strip()
        self.http = http

    def analyze(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not self.api_key:
            raise RuntimeError("OPENAI_API_KEY is required when LLM_PROVIDER=openai")

        req = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": "You are a senior SRE reliability model. Return JSON only."},
                {"role": "user", "content": f"{PROMPT}\n\nContext:\n{payload}"},
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.2,
        }
        resp = self.http.request(
            "POST",
            f"{self.base_url}/chat/completions",
            json=req,
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {self.api_key}"},
        )
        body = resp.json()
        content = (((body.get("choices") or [{}])[0]).get("message") or {}).get("content", "{}")
        import json

        try:
            return json.loads(content)
        except json.JSONDecodeError:
            return {}

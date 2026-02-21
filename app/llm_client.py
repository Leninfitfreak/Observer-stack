import json
import os
from typing import Any

from utils import parse_json_safe, request_with_retry


PROMPT_HEADER = (
    "You are an expert SRE AI assistant.\n"
    "Analyze the provided metrics, logs, and traces.\n"
    "Provide strictly JSON with keys:\n"
    "probable_root_cause, impact_level, recommended_remediation, confidence_score.\n"
    "confidence_score must include % sign.\n"
)


class LlmClient:
    def __init__(
        self,
        base_url: str,
        model: str = "llama3:8b",
        timeout_seconds: int | None = None,
        attempts: int | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.model = model
        # CPU-backed local models can take >60s for structured prompts.
        self.timeout_seconds = timeout_seconds if timeout_seconds is not None else int(
            os.getenv("OLLAMA_TIMEOUT_SECONDS", "180")
        )
        # Keep retries low to avoid very long webhook response times.
        self.attempts = attempts if attempts is not None else int(os.getenv("OLLAMA_ATTEMPTS", "1"))

    def analyze(self, context: dict[str, Any]) -> dict[str, Any]:
        prompt = f"{PROMPT_HEADER}\nContext:\n{json.dumps(context, indent=2)}"
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "format": "json",
        }
        resp = request_with_retry(
            "POST",
            f"{self.base_url}/api/generate",
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=self.timeout_seconds,
            attempts=self.attempts,
        )
        body = resp.json()
        raw = body.get("response", "")
        parsed = parse_json_safe(raw)

        if parsed:
            return parsed

        return {
            "probable_root_cause": "Unable to parse model response",
            "impact_level": "Medium",
            "recommended_remediation": "Review datasource summaries manually and inspect affected service health.",
            "confidence_score": "40%",
        }

import json
import os
from typing import Any

from utils import parse_json_safe, request_with_retry


PROMPT_HEADER = (
    "ROLE: Platform Reliability & SRE Execution Agent.\n"
    "Objective: detect instability, correlate observability signals, identify probable root cause, "
    "predict risk, propose corrective actions and preventive hardening.\n"
    "Reasoning rules:\n"
    "- Correlate metrics + traces + logs.\n"
    "- Explain causality (not only correlation).\n"
    "- Assign confidence score between 0.0 and 1.0.\n"
    "- Avoid premature rollback recommendation.\n"
    "- Flag missing observability when data is insufficient.\n"
    "- Never auto-apply changes without explicit approval.\n"
    "Return STRICT JSON only with keys:\n"
    "probable_root_cause, impact_level, recommended_remediation, confidence, "
    "causal_chain, corrective_actions, preventive_hardening, risk_forecast, "
    "deployment_correlation, error_log_prediction, missing_observability, human_summary.\n"
)


class LlmClient:
    def __init__(
        self,
        base_url: str,
        model: str = "llama3:8b",
        timeout_seconds: int | None = None,
        attempts: int | None = None,
    ):
        self.provider = os.getenv("LLM_PROVIDER", "openai").lower()
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_seconds = timeout_seconds if timeout_seconds is not None else int(
            os.getenv("LLM_TIMEOUT_SECONDS", os.getenv("OLLAMA_TIMEOUT_SECONDS", "180"))
        )
        self.attempts = attempts if attempts is not None else int(os.getenv("LLM_ATTEMPTS", os.getenv("OLLAMA_ATTEMPTS", "1")))
        self.openai_base_url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
        self.openai_api_key = os.getenv("OPENAI_API_KEY", "")

    def analyze(self, context: dict[str, Any]) -> dict[str, Any]:
        prompt = f"{PROMPT_HEADER}\nContext:\n{json.dumps(context, indent=2)}"
        if self.provider == "openai":
            return self._analyze_openai(prompt)
        return self._analyze_ollama(prompt)

    def _analyze_ollama(self, prompt: str) -> dict[str, Any]:
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

        return {"human_summary": "LLM response parsing failed"}

    def _analyze_openai(self, prompt: str) -> dict[str, Any]:
        if not self.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY is required when LLM_PROVIDER=openai")
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": "You are a senior SRE reliability reasoning model. Return valid JSON only."},
                {"role": "user", "content": prompt},
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.2,
        }
        resp = request_with_retry(
            "POST",
            f"{self.openai_base_url}/chat/completions",
            json=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.openai_api_key}",
            },
            timeout=self.timeout_seconds,
            attempts=self.attempts,
        )
        body = resp.json()
        content = (((body.get("choices") or [{}])[0]).get("message") or {}).get("content", "")
        parsed = parse_json_safe(content)
        if parsed:
            return parsed
        return {"human_summary": "Cloud LLM response parsing failed"}

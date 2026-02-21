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
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_seconds = timeout_seconds if timeout_seconds is not None else int(
            os.getenv("OLLAMA_TIMEOUT_SECONDS", "180")
        )
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

        return {"human_summary": "LLM response parsing failed"}

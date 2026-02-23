from __future__ import annotations

import json
from typing import Any

from ai_observer.infra.http_client import HttpClient


PROMPT = (
    "You are an expert SRE AI assistant. "
    "Analyze metrics, logs and traces and return strict JSON with keys: "
    "probable_root_cause, impact_level, recommended_remediation, confidence, "
    "causal_chain, corrective_actions, preventive_hardening, risk_forecast, "
    "deployment_correlation, error_log_prediction, missing_observability, human_summary."
)


class OllamaCloudProvider:
    def __init__(self, base_url: str, model: str, api_key: str, http: HttpClient):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key.strip()
        self.http = http

    def analyze(self, payload: dict[str, Any]) -> dict[str, Any]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        req = {
            "model": self.model,
            "prompt": f"{PROMPT}\n\nContext:\n{json.dumps(payload, indent=2)}",
            "stream": False,
            "format": "json",
        }
        resp = self.http.request("POST", f"{self.base_url}/api/generate", json=req, headers=headers)
        data = resp.json()
        raw = data.get("response", "{}")
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {"_llm_partial": True}

import json
import time
from typing import Any

import requests

from app.config import settings


def call_ollama(payload: dict[str, Any]) -> dict[str, Any]:
    url = settings.ollama_base_url.rstrip('/') + '/api/chat'
    headers = {
        'Authorization': f'Bearer {settings.ollama_api_key}',
        'Content-Type': 'application/json',
    }
    schema_prompt = (
        'Return valid JSON only with keys: '
        'root_cause, confidence, causal_chain, correlated_signals, '
        'impact_assessment, recommended_actions, severity, '
        'root_cause_entity, impacted_entities.'
    )
    prompt = {
        'model': settings.ollama_model,
        'messages': [
            {
                'role': 'system',
                'content': (
                    'You are an SRE reasoning engine. '
                    + schema_prompt +
                    ' Use only provided telemetry. Be specific, concise, and non-generic.'
                ),
            },
            {
                'role': 'user',
                'content': (
                    schema_prompt +
                    '\nTelemetry context:\n' +
                    json.dumps(payload)
                ),
            },
        ],
        'stream': False,
        'format': 'json',
    }
    last_error = None
    for _ in range(settings.llm_max_retries):
        try:
            response = requests.post(url, headers=headers, json=prompt, timeout=settings.llm_timeout_seconds)
            response.raise_for_status()
            content = response.json()['message']['content']
            return json.loads(content)
        except Exception as exc:
            last_error = exc
            time.sleep(1)
    raise RuntimeError(f'OLLAMA_CLOUD_CALL_FAILED: {last_error}')

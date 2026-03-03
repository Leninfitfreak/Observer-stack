from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from app.ollama_client import call_ollama


class ReasonRequest(BaseModel):
    project_id: str
    cluster: str
    namespace: str
    service: str
    metrics_summary: dict[str, Any]
    logs_summary: dict[str, Any]
    trace_summary: dict[str, Any]
    anomaly_signals: list[str]
    z_scores: dict[str, float]
    baseline: dict[str, float]


app = FastAPI(title='AI Observer Brain')


@app.get('/healthz')
def healthz():
    return {'status': 'ok'}


@app.post('/reason')
def reason(req: ReasonRequest):
    try:
        result = call_ollama(req.model_dump())
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    return {
        'root_cause': result.get('root_cause', f"Anomaly detected in {req.service}"),
        'confidence': float(result.get('confidence', 0.7)),
        'causal_chain': result.get('causal_chain', [req.service]),
        'correlated_signals': result.get('correlated_signals', req.anomaly_signals),
        'impact_assessment': result.get('impact_assessment', f"Potential degradation in {req.service}"),
        'recommended_actions': result.get('recommended_actions', ['Inspect current telemetry and recent deployments.']),
        'severity': result.get('severity', 'warning'),
        'root_cause_entity': result.get('root_cause_entity', req.service),
        'impacted_entities': result.get('impacted_entities', [req.service]),
    }

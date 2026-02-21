import os
from typing import Any

from fastapi import FastAPI, HTTPException

from jaeger_client import JaegerClient
from llm_client import LlmClient
from loki_client import LokiClient
from models import AlertAnalysisResponse, AlertmanagerWebhook, HealthResponse
from prometheus_client import PrometheusClient
from utils import LOGGER, setup_logging

setup_logging()

PROMETHEUS_URL = os.getenv("PROMETHEUS_URL", "http://prometheus:9090")
LOKI_URL = os.getenv("LOKI_URL", "http://loki-gateway:80")
JAEGER_URL = os.getenv("JAEGER_URL", "http://jaeger-query:16686")
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://host.minikube.internal:11434")
DEFAULT_NAMESPACE = os.getenv("DEFAULT_NAMESPACE", "dev")
DEFAULT_SERVICE = os.getenv("DEFAULT_SERVICE", "unknown-service")

prom = PrometheusClient(PROMETHEUS_URL)
loki = LokiClient(LOKI_URL)
jaeger = JaegerClient(JAEGER_URL)
llm = LlmClient(OLLAMA_URL, model="llama3:8b")

app = FastAPI(title="AI Observer Agent", version="1.0.0")


def _extract_alert_fields(payload: AlertmanagerWebhook) -> dict[str, str]:
    if not payload.alerts:
        raise HTTPException(status_code=400, detail="alert payload has no alerts")

    first = payload.alerts[0]
    labels = dict(payload.commonLabels)
    labels.update(first.labels)

    alertname = labels.get("alertname", "UnknownAlert")
    namespace = labels.get("namespace", DEFAULT_NAMESPACE)
    service = labels.get("service") or labels.get("app") or labels.get("job") or DEFAULT_SERVICE
    severity = labels.get("severity", "unknown")

    return {
        "alertname": alertname,
        "namespace": namespace,
        "service": service,
        "severity": severity,
        "status": first.status,
    }


@app.get("/healthz", response_model=HealthResponse)
def healthz() -> HealthResponse:
    return HealthResponse(status="ok")


@app.post("/webhook/alertmanager", response_model=AlertAnalysisResponse)
def analyze_alert(payload: AlertmanagerWebhook) -> dict[str, Any]:
    alert = _extract_alert_fields(payload)
    namespace = alert["namespace"]
    service = alert["service"]

    datasource_errors: dict[str, str] = {}
    metrics: dict[str, Any] = {}
    logs_data: dict[str, Any] = {"summary": "logs datasource unavailable", "lines": []}
    traces_data: dict[str, Any] = {"summary": "tracing datasource unavailable", "slow_traces": []}

    try:
        metrics = prom.collect_metrics(namespace=namespace, service=service)
    except Exception as err:
        datasource_errors["prometheus"] = str(err)
        metrics = {
            "error_rate_5xx_5m": None,
            "latency_p95_seconds_5m": None,
            "cpu_usage_cores_5m": None,
            "memory_usage_bytes": None,
        }
        LOGGER.error("prometheus query failed service=%s namespace=%s error=%s", service, namespace, err)

    try:
        logs_data = loki.query_errors(namespace=namespace, service=service, minutes=5, limit=20)
    except Exception as err:
        datasource_errors["loki"] = str(err)
        LOGGER.error("loki query failed service=%s namespace=%s error=%s", service, namespace, err)

    try:
        traces_data = jaeger.query_slow_traces(service=service, limit=5, min_duration_ms=500)
    except Exception as err:
        datasource_errors["jaeger"] = str(err)
        LOGGER.error("jaeger query failed service=%s error=%s", service, err)

    context = {
        "alert": alert,
        "metrics": metrics,
        "logs_summary": logs_data.get("summary", ""),
        "trace_summary": traces_data.get("summary", ""),
        "datasource_errors": datasource_errors,
    }

    try:
        llm_result = llm.analyze(context)
    except Exception as err:
        datasource_errors["ollama"] = str(err)
        LOGGER.error("ollama request failed error=%s", err)
        llm_result = {
            "probable_root_cause": "LLM analysis unavailable",
            "impact_level": "Medium",
            "recommended_remediation": "Use metrics/logs/traces context for manual triage while Ollama is unavailable.",
            "confidence_score": "35%",
        }
        context["datasource_errors"] = datasource_errors

    return {"context": context, "analysis": llm_result}

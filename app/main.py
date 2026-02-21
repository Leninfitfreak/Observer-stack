import os
from typing import Any

from fastapi import FastAPI, HTTPException

from jaeger_client import JaegerClient
from llm_client import LlmClient
from loki_client import LokiClient
from models import AlertAnalysisResponse, AlertmanagerWebhook, HealthResponse
from prometheus_client import PrometheusClient
from sre_reasoner import build_rule_based_analysis
from utils import LOGGER, setup_logging

setup_logging()

PROMETHEUS_URL = os.getenv("PROMETHEUS_URL", "http://prometheus:9090")
LOKI_URL = os.getenv("LOKI_URL", "http://loki-gateway:80")
JAEGER_URL = os.getenv("JAEGER_URL", "http://jaeger-query:16686")
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://host.minikube.internal:11434")
DEFAULT_NAMESPACE = os.getenv("DEFAULT_NAMESPACE", "dev")
DEFAULT_SERVICE = os.getenv("DEFAULT_SERVICE", "unknown-service")
SLO_TARGET = float(os.getenv("SLO_TARGET", "0.995"))

prom = PrometheusClient(PROMETHEUS_URL)
loki = LokiClient(LOKI_URL)
jaeger = JaegerClient(JAEGER_URL)
llm = LlmClient(OLLAMA_URL, model="llama3:8b")

app = FastAPI(title="AI Observer Agent", version="2.0.0")


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
    kubernetes_signals: dict[str, Any] = {}
    deployment_signals: dict[str, Any] = {}
    slo_signals: dict[str, Any] = {}

    try:
        metrics = prom.collect_service_metrics(namespace=namespace, service=service)
    except Exception as err:
        datasource_errors["prometheus_metrics"] = str(err)
        LOGGER.error("prometheus service metrics failed service=%s namespace=%s error=%s", service, namespace, err)
        metrics = {}

    try:
        kubernetes_signals = prom.collect_kubernetes_signals(namespace=namespace, service=service)
    except Exception as err:
        datasource_errors["prometheus_kubernetes"] = str(err)
        LOGGER.error("prometheus kubernetes signals failed service=%s namespace=%s error=%s", service, namespace, err)
        kubernetes_signals = {}

    try:
        deployment_signals = prom.collect_deployment_signals(namespace=namespace, service=service)
    except Exception as err:
        datasource_errors["prometheus_deployment"] = str(err)
        LOGGER.error("prometheus deployment signals failed service=%s namespace=%s error=%s", service, namespace, err)
        deployment_signals = {}

    try:
        slo_signals = prom.collect_slo_error_budget(
            namespace=namespace,
            error_rate_5xx=metrics.get("error_rate_5xx_5m"),
            slo_target=SLO_TARGET,
        )
    except Exception as err:
        datasource_errors["prometheus_slo"] = str(err)
        LOGGER.error("prometheus slo signals failed namespace=%s error=%s", namespace, err)
        slo_signals = {}

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
        "traces": traces_data,
        "logs": logs_data,
        "kubernetes": kubernetes_signals,
        "deployment": deployment_signals,
        "slo": slo_signals,
        "datasource_errors": datasource_errors,
    }

    baseline_analysis = build_rule_based_analysis(context)
    if "human_summary" not in baseline_analysis:
        baseline_analysis["human_summary"] = (
            f"Probable root cause: {baseline_analysis['probable_root_cause']}. "
            f"Impact: {baseline_analysis['impact_level']}. "
            "Corrective actions and preventive hardening included in machine fields."
        )
    baseline_analysis["confidence_score"] = baseline_analysis.get(
        "confidence_score", f"{round((baseline_analysis.get('confidence', 0.4)) * 100)}%"
    )

    try:
        llm_input = {"telemetry": context, "baseline_reasoning": baseline_analysis}
        llm_result = llm.analyze(llm_input)
        merged = dict(baseline_analysis)
        merged.update({k: v for k, v in llm_result.items() if v is not None and v != ""})
        if "confidence_score" not in merged and merged.get("confidence") is not None:
            merged["confidence_score"] = f"{round(float(merged['confidence']) * 100)}%"
        analysis = merged
    except Exception as err:
        datasource_errors["ollama"] = str(err)
        LOGGER.error("ollama request failed error=%s", err)
        context["datasource_errors"] = datasource_errors
        analysis = baseline_analysis

    analysis["policy_note"] = "No auto-remediation was applied. Explicit approval required before any changes."
    return {"context": context, "analysis": analysis}

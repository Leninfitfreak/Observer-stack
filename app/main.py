import os
import json
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

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
LLM_MODEL = os.getenv("LLM_MODEL", "gpt-4o-mini")
DEFAULT_NAMESPACE = os.getenv("DEFAULT_NAMESPACE", "dev")
DEFAULT_SERVICE = os.getenv("DEFAULT_SERVICE", "all")
ALL_SERVICES = [s.strip() for s in os.getenv("ALL_SERVICES", "product-service,order-service").split(",") if s.strip()]
SLO_TARGET = float(os.getenv("SLO_TARGET", "0.995"))

prom = PrometheusClient(PROMETHEUS_URL)
loki = LokiClient(LOKI_URL)
jaeger = JaegerClient(JAEGER_URL)
llm = LlmClient(OLLAMA_URL, model=LLM_MODEL)

app = FastAPI(title="AI Observer Agent", version="2.1.0")
STATIC_DIR = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


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


def _parse_time_window_to_minutes(value: str) -> int:
    raw = (value or "30m").strip().lower()
    if raw.endswith("m"):
        try:
            return max(5, min(360, int(raw[:-1])))
        except Exception:
            return 30
    if raw.endswith("h"):
        try:
            return max(5, min(360, int(raw[:-1]) * 60))
        except Exception:
            return 60
    if raw.endswith("d"):
        try:
            return max(5, min(360, int(raw[:-1]) * 24 * 60))
        except Exception:
            return 360
    try:
        return max(5, min(360, int(raw)))
    except Exception:
        return 30


def _normalize_service_scope(namespace: str, service_value: str) -> tuple[str, list[str]]:
    raw = (service_value or "").strip()
    if not raw or raw.lower() in {"all", "*"}:
        discovered = prom.discover_services(namespace)
        if discovered:
            return "all", discovered
        if ALL_SERVICES:
            return "all", ALL_SERVICES
        fallback = DEFAULT_SERVICE if DEFAULT_SERVICE not in {"all", "*"} else "order-service"
        return "single", [fallback]

    services = [s.strip() for s in raw.split(",") if s.strip()]
    if not services:
        return "single", [DEFAULT_SERVICE]
    if len(services) > 1:
        return "multi", services
    return "single", services


def _component_status(
    service: str,
    metrics: dict[str, Any],
    kubernetes_signals: dict[str, Any],
    deployment_signals: dict[str, Any],
    datasource_errors: dict[str, str],
) -> dict[str, Any]:
    reasons: list[str] = []
    level = "healthy"

    if datasource_errors:
        level = "warning"
        reasons.append("datasource query issues")

    if (metrics.get("error_rate_5xx_5m") or 0) > 0.05:
        level = "critical"
        reasons.append("5xx error rate > 5%")
    if (metrics.get("latency_p95_s_5m") or 0) > 0.75:
        level = "critical"
        reasons.append("p95 latency > 750ms")
    if (kubernetes_signals.get("crashloop_pods") or 0) > 0:
        level = "critical"
        reasons.append("CrashLoopBackOff detected")
    if (kubernetes_signals.get("oom_killed_10m") or 0) > 0:
        level = "critical"
        reasons.append("OOMKilled detected")
    if (kubernetes_signals.get("pod_restarts_10m") or 0) > 0 and level != "critical":
        level = "warning"
        reasons.append("pod restarts observed")
    if deployment_signals.get("deployment_changed_last_10m") and level != "critical":
        level = "warning"
        reasons.append("recent deployment activity")

    if not reasons:
        reasons.append("no strong degradation signal")

    return {"service": service, "status": level, "reasons": reasons[:4]}


def _collect_component_snapshot(
    namespace: str,
    service: str,
    alert_base: dict[str, str],
    window_minutes: int,
) -> dict[str, Any]:
    datasource_errors: dict[str, str] = {}
    metrics: dict[str, Any] = {}
    logs_data: dict[str, Any] = {"summary": "logs datasource unavailable", "lines": []}
    traces_data: dict[str, Any] = {"summary": "tracing datasource unavailable", "slow_traces": []}
    kubernetes_signals: dict[str, Any] = {}
    deployment_signals: dict[str, Any] = {}
    slo_signals: dict[str, Any] = {}

    comp_alert = dict(alert_base)
    comp_alert["service"] = service

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
        logs_data = loki.query_errors(namespace=namespace, service=service, minutes=window_minutes, limit=20)
    except Exception as err:
        datasource_errors["loki"] = str(err)
        LOGGER.error("loki query failed service=%s namespace=%s error=%s", service, namespace, err)

    try:
        traces_data = jaeger.query_slow_traces(
            service=service,
            limit=5,
            min_duration_ms=500,
            lookback_minutes=window_minutes,
        )
    except Exception as err:
        datasource_errors["jaeger"] = str(err)
        LOGGER.error("jaeger query failed service=%s error=%s", service, err)
    return {
        "alert": comp_alert,
        "metrics": metrics,
        "traces": traces_data,
        "logs": logs_data,
        "kubernetes": kubernetes_signals,
        "deployment": deployment_signals,
        "slo": slo_signals,
        "status": _component_status(service, metrics, kubernetes_signals, deployment_signals, datasource_errors),
        "datasource_errors": datasource_errors,
    }


def _aggregate_snapshots(scope: str, alert: dict[str, str], snapshots: list[dict[str, Any]]) -> dict[str, Any]:
    if len(snapshots) == 1:
        base = dict(snapshots[0])
        base["components"] = [{"service": base["alert"]["service"], "status": base["status"]["status"], "reasons": base["status"]["reasons"]}]
        base["component_summary"] = {"scope": "single", "total": 1, "healthy": 1 if base["status"]["status"] == "healthy" else 0, "warning": 1 if base["status"]["status"] == "warning" else 0, "critical": 1 if base["status"]["status"] == "critical" else 0}
        base.pop("status", None)
        return base

    components = [snap["status"] for snap in snapshots]
    healthy = sum(1 for c in components if c["status"] == "healthy")
    warning = sum(1 for c in components if c["status"] == "warning")
    critical = sum(1 for c in components if c["status"] == "critical")
    overall = "critical" if critical else ("warning" if warning else "healthy")

    metrics = {
        "request_rate_rps_5m": sum((snap["metrics"].get("request_rate_rps_5m") or 0) for snap in snapshots),
        "latency_p95_s_5m": max((snap["metrics"].get("latency_p95_s_5m") or 0) for snap in snapshots),
        "error_rate_5xx_5m": max((snap["metrics"].get("error_rate_5xx_5m") or 0) for snap in snapshots),
        "cpu_usage_cores_5m": sum((snap["metrics"].get("cpu_usage_cores_5m") or 0) for snap in snapshots),
        "memory_usage_bytes": sum((snap["metrics"].get("memory_usage_bytes") or 0) for snap in snapshots),
        "anomalies": sorted({a for snap in snapshots for a in (snap["metrics"].get("anomalies") or [])}),
    }
    traces = {
        "slow_traces": [t for snap in snapshots for t in (snap["traces"].get("slow_traces") or [])][:5],
        "error_span_count": sum((snap["traces"].get("error_span_count") or 0) for snap in snapshots),
        "longest_critical_path": next((snap["traces"].get("longest_critical_path") for snap in snapshots if snap["traces"].get("longest_critical_path")), None),
        "summary": f"Aggregated traces across {len(snapshots)} components.",
    }
    logs = {
        "count": sum((snap["logs"].get("count") or 0) for snap in snapshots),
        "lines": [line for snap in snapshots for line in (snap["logs"].get("lines") or [])][:20],
        "top_signatures": [sig for snap in snapshots for sig in (snap["logs"].get("top_signatures") or [])][:10],
        "new_signatures": sorted({sig for snap in snapshots for sig in (snap["logs"].get("new_signatures") or [])})[:10],
        "summary": f"Aggregated logs across {len(snapshots)} components.",
    }
    kubernetes = {
        "pod_restarts_10m": sum((snap["kubernetes"].get("pod_restarts_10m") or 0) for snap in snapshots),
        "crashloop_pods": sum((snap["kubernetes"].get("crashloop_pods") or 0) for snap in snapshots),
        "oom_killed_10m": sum((snap["kubernetes"].get("oom_killed_10m") or 0) for snap in snapshots),
        "cpu_throttled_rate_5m": sum((snap["kubernetes"].get("cpu_throttled_rate_5m") or 0) for snap in snapshots),
    }
    deployment = {
        "deployment_changed_last_10m": any(bool(snap["deployment"].get("deployment_changed_last_10m")) for snap in snapshots),
        "deployment_generation_changes_10m": sum((snap["deployment"].get("deployment_generation_changes_10m") or 0) for snap in snapshots),
        "updated_replicas_changes_10m": sum((snap["deployment"].get("updated_replicas_changes_10m") or 0) for snap in snapshots),
        "argocd_deployment_history": "aggregated_multi_component",
        "cicd_pipeline_signals": "aggregated_multi_component",
    }
    slo = {
        "availability_pct": None,
        "slo_target_pct": round(SLO_TARGET * 100, 4),
        "error_budget_burn_rate_1h": None,
        "error_budget_burn_rate_24h": None,
        "predicted_breach_window": "likely_breach_within_1h" if critical else ("likely_breach_within_24h" if warning else "low_risk"),
    }
    datasource_errors: dict[str, str] = {}
    for snap in snapshots:
        for key, value in snap["datasource_errors"].items():
            datasource_errors[f'{snap["alert"]["service"]}:{key}'] = value

    return {
        "alert": {**alert, "service": "all" if scope != "single" else alert["service"]},
        "metrics": metrics,
        "traces": traces,
        "logs": logs,
        "kubernetes": kubernetes,
        "deployment": deployment,
        "slo": slo,
        "components": components,
        "component_summary": {
            "scope": scope,
            "overall_status": overall,
            "total": len(components),
            "healthy": healthy,
            "warning": warning,
            "critical": critical,
        },
        "datasource_errors": datasource_errors,
    }


def _run_reasoning(alert: dict[str, str], window_minutes: int = 30) -> dict[str, Any]:
    namespace = alert["namespace"]
    scope, services = _normalize_service_scope(namespace, alert["service"])
    snapshots = [_collect_component_snapshot(namespace, service, alert, window_minutes) for service in services]
    context = _aggregate_snapshots(scope, alert, snapshots)
    context["time_window_minutes"] = window_minutes

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
        datasource_errors = dict(context.get("datasource_errors", {}))
        datasource_errors["llm"] = str(err)
        LOGGER.error("llm request failed error=%s", err)
        context["datasource_errors"] = datasource_errors
        analysis = baseline_analysis

    analysis["policy_note"] = "No auto-remediation was applied. Explicit approval required before any changes."
    try:
        LOGGER.info(
            "ai_observer_summary %s",
            json.dumps(
                {
                    "alertname": alert.get("alertname"),
                    "namespace": alert.get("namespace"),
                    "service_scope": context.get("alert", {}).get("service"),
                    "component_summary": context.get("component_summary", {}),
                    "impact_level": analysis.get("impact_level"),
                    "confidence_score": analysis.get("confidence_score"),
                },
                separators=(",", ":"),
            ),
        )
    except Exception:
        pass
    return {"context": context, "analysis": analysis}


@app.get("/healthz", response_model=HealthResponse)
def healthz() -> HealthResponse:
    return HealthResponse(status="ok")


@app.get("/dashboard")
def dashboard() -> FileResponse:
    return FileResponse(STATIC_DIR / "dashboard.html")


@app.get("/api/reasoning/live", response_model=AlertAnalysisResponse)
def live_reasoning(
    namespace: str = Query(default=DEFAULT_NAMESPACE),
    service: str = Query(default=DEFAULT_SERVICE),
    severity: str = Query(default="warning"),
    time_window: str = Query(default="30m"),
) -> dict[str, Any]:
    alert = {
        "alertname": "LiveObservabilitySnapshot",
        "namespace": namespace,
        "service": service,
        "severity": severity,
        "status": "firing",
    }
    window_minutes = _parse_time_window_to_minutes(time_window)
    return _run_reasoning(alert, window_minutes=window_minutes)


@app.post("/webhook/alertmanager", response_model=AlertAnalysisResponse)
def analyze_alert(payload: AlertmanagerWebhook) -> dict[str, Any]:
    alert = _extract_alert_fields(payload)
    return _run_reasoning(alert, window_minutes=30)

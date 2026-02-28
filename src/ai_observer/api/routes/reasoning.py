from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from ai_observer.api.routes.schemas import AlertmanagerWebhook
from ai_observer.backend.models.incident import Incident
from ai_observer.backend.services import IncidentsService
from ai_observer.domain.models import AlertSignal, LiveReasoningResponse
from ai_observer.incident_analysis.database import get_db_session
from ai_observer.services.reasoning_service import ReasoningService

router = APIRouter()
logger = logging.getLogger(__name__)


def get_reasoning_service(request: Request) -> ReasoningService:
    return request.app.state.container.reasoning_service


def _persist_analysis_snapshot(db: Session, alert: AlertSignal, response: LiveReasoningResponse) -> None:
    IncidentsService(db).persist_from_reasoning(alert, response)


def _has_metric_signal(metrics: dict[str, Any] | None) -> bool:
    if not isinstance(metrics, dict):
        return False
    keys = (
        "request_rate_rps_5m",
        "cpu_usage_cores_5m",
        "memory_usage_bytes",
        "pod_restarts_10m",
        "error_rate_5xx_5m",
    )
    return any(float(metrics.get(k, 0) or 0) > 0 for k in keys)


def _as_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _hydrate_metrics_from_recent_incidents(db: Session, cluster_id: str) -> tuple[dict[str, float], dict[str, dict[str, float]]]:
    query = db.query(Incident).filter(Incident.incident_id.ilike("agent-%")).order_by(Incident.created_at.desc())
    if cluster_id:
        rows = query.filter(Incident.cluster_id == cluster_id).limit(100).all()
        if not rows:
            rows = query.limit(100).all()
    else:
        rows = query.limit(100).all()
    component_metrics: dict[str, dict[str, float]] = {}

    for row in rows:
        payload = row.raw_payload if isinstance(row.raw_payload, dict) else {}
        raw = payload.get("metrics") if isinstance(payload, dict) else {}
        if not isinstance(raw, dict):
            continue
        cpu = _as_float(raw.get("cpu_usage", 0.0))
        mem = _as_float(raw.get("memory_usage", 0.0))
        rps = _as_float(raw.get("request_rate", 0.0))
        restarts = _as_float(raw.get("pod_restarts", 0.0))
        err = _as_float(raw.get("error_rate", 0.0))
        if cpu <= 0 and mem <= 0 and rps <= 0 and restarts <= 0 and err <= 0:
            continue

        service = (row.affected_services or "observer-agent").split(",")[0].strip() or "observer-agent"
        if service not in component_metrics:
            component_metrics[service] = {
                "cpu_usage_cores_5m": cpu,
                "memory_usage_bytes": mem,
                "request_rate_rps_5m": rps,
                "pod_restarts_10m": restarts,
                "error_rate_5xx_5m": err,
            }

    if not component_metrics:
        return {}, {}

    aggregated = {
        "cpu_usage_cores_5m": max(v.get("cpu_usage_cores_5m", 0.0) for v in component_metrics.values()),
        "memory_usage_bytes": sum(v.get("memory_usage_bytes", 0.0) for v in component_metrics.values()),
        "request_rate_rps_5m": sum(v.get("request_rate_rps_5m", 0.0) for v in component_metrics.values()),
        "pod_restarts_10m": sum(v.get("pod_restarts_10m", 0.0) for v in component_metrics.values()),
        "error_rate_5xx_5m": sum(v.get("error_rate_5xx_5m", 0.0) for v in component_metrics.values()),
    }
    return aggregated, component_metrics


def _refresh_analysis_from_metrics(response: LiveReasoningResponse) -> None:
    metrics = response.context.metrics or {}
    cpu = _as_float(metrics.get("cpu_usage_cores_5m", 0.0))
    mem_mb = _as_float(metrics.get("memory_usage_bytes", 0.0)) / (1024 * 1024)
    rps = _as_float(metrics.get("request_rate_rps_5m", 0.0))
    restarts = _as_float(metrics.get("pod_restarts_10m", 0.0))
    err = _as_float(metrics.get("error_rate_5xx_5m", 0.0))

    if err > 0.05:
        response.analysis.probable_root_cause = "error_rate_threshold_breached"
        response.analysis.incident_classification = "Performance Degradation"
    elif cpu > 0.8:
        response.analysis.probable_root_cause = "cpu_usage_threshold_breached"
        response.analysis.incident_classification = "Performance Degradation"
    else:
        response.analysis.probable_root_cause = "metrics_within_expected_range"
        response.analysis.incident_classification = "Healthy"

    response.analysis.executive_summary = (
        f"Telemetry from observer-agent indicates CPU {cpu*100:.2f}%, "
        f"Memory {mem_mb:.0f}MB, Request rate {rps:.3f} rps, Restarts {restarts:.0f}, Error rate {err*100:.2f}%."
    )
    response.analysis.human_summary = response.analysis.executive_summary
    response.analysis.assessment = "Analysis refreshed from recent persisted agent telemetry."


def _parse_time_window(value: str) -> int:
    raw = (value or "30m").strip().lower()
    if raw.endswith("m"):
        raw = raw[:-1]
    elif raw.endswith("h"):
        raw = str(int(raw[:-1]) * 60) if raw[:-1].isdigit() else "60"
    elif raw.endswith("d"):
        raw = str(int(raw[:-1]) * 24 * 60) if raw[:-1].isdigit() else "360"
    try:
        minutes = int(raw)
    except ValueError:
        minutes = 30
    return max(5, min(360, minutes))


def _extract_alert(payload: AlertmanagerWebhook, default_namespace: str, default_service: str, default_cluster: str) -> AlertSignal:
    if not payload.alerts:
        raise HTTPException(status_code=400, detail="alert payload has no alerts")

    first = payload.alerts[0]
    labels = dict(payload.commonLabels)
    labels.update(first.labels)

    return AlertSignal(
        alertname=labels.get("alertname", "UnknownAlert"),
        namespace=labels.get("namespace", default_namespace),
        service=labels.get("service") or labels.get("app") or default_service,
        cluster_id=labels.get("cluster_id") or labels.get("cluster") or default_cluster,
        severity=labels.get("severity", "warning"),
        status=first.status,
    )


@router.get("/api/reasoning/live", response_model=LiveReasoningResponse)
def live_reasoning(
    request: Request,
    namespace: str = Query(default="dev"),
    service: str = Query(default="all"),
    cluster: str | None = Query(default=None),
    severity: str = Query(default="warning"),
    time_window: str = Query(default="30m"),
    reasoner: ReasoningService = Depends(get_reasoning_service),
    db: Session = Depends(get_db_session),
) -> LiveReasoningResponse:
    default_cluster = request.app.state.container.settings.telemetry.default_cluster_id
    alert = AlertSignal(
        alertname="LiveObservabilitySnapshot",
        namespace=namespace,
        service=service,
        cluster_id=cluster or default_cluster,
        severity=severity,
        status="firing",
    )
    result = reasoner.analyze(alert, window_minutes=_parse_time_window(time_window))
    if not _has_metric_signal(result.context.metrics):
        logger.info("Live reasoning metrics missing; attempting incident telemetry fallback cluster=%s", alert.cluster_id or "")
        fallback_metrics, fallback_components = _hydrate_metrics_from_recent_incidents(db, alert.cluster_id or "")
        if _has_metric_signal(fallback_metrics):
            logger.info("Applying incident telemetry fallback metrics=%s", fallback_metrics)
            result.context.metrics.update(fallback_metrics)
            for service_name, service_metrics in fallback_components.items():
                result.context.component_metrics[service_name] = service_metrics
            _refresh_analysis_from_metrics(result)
        else:
            logger.info("No fallback telemetry available from incidents for cluster=%s", alert.cluster_id or "")
    try:
        _persist_analysis_snapshot(db, alert, result)
    except Exception:
        # Persistence is best-effort and must not break live reasoning response path.
        pass
    return result


@router.post("/webhook/alertmanager", response_model=LiveReasoningResponse)
def alertmanager_webhook(
    request: Request,
    payload: AlertmanagerWebhook,
    reasoner: ReasoningService = Depends(get_reasoning_service),
    db: Session = Depends(get_db_session),
) -> LiveReasoningResponse:
    settings = request.app.state.container.settings
    alert = _extract_alert(
        payload,
        settings.telemetry.default_namespace,
        settings.telemetry.default_service,
        settings.telemetry.default_cluster_id,
    )
    result = reasoner.analyze(alert, window_minutes=settings.telemetry.default_window_minutes)
    try:
        _persist_analysis_snapshot(db, alert, result)
    except Exception:
        # Persistence is best-effort and must not break webhook response path.
        pass
    return result

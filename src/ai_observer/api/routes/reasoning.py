from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from ai_observer.api.routes.schemas import AlertmanagerWebhook
from ai_observer.backend.services import IncidentsService
from ai_observer.domain.models import AlertSignal, LiveReasoningResponse
from ai_observer.incident_analysis.database import get_db_session
from ai_observer.services.reasoning_service import ReasoningService

router = APIRouter()


def get_reasoning_service(request: Request) -> ReasoningService:
    return request.app.state.container.reasoning_service


def _persist_analysis_snapshot(db: Session, alert: AlertSignal, response: LiveReasoningResponse) -> None:
    IncidentsService(db).persist_from_reasoning(alert, response)


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


def _extract_alert(payload: AlertmanagerWebhook, default_namespace: str, default_service: str) -> AlertSignal:
    if not payload.alerts:
        raise HTTPException(status_code=400, detail="alert payload has no alerts")

    first = payload.alerts[0]
    labels = dict(payload.commonLabels)
    labels.update(first.labels)

    return AlertSignal(
        alertname=labels.get("alertname", "UnknownAlert"),
        namespace=labels.get("namespace", default_namespace),
        service=labels.get("service") or labels.get("app") or default_service,
        severity=labels.get("severity", "warning"),
        status=first.status,
    )


@router.get("/api/reasoning/live", response_model=LiveReasoningResponse)
def live_reasoning(
    request: Request,
    namespace: str = Query(default="dev"),
    service: str = Query(default="all"),
    severity: str = Query(default="warning"),
    time_window: str = Query(default="30m"),
    reasoner: ReasoningService = Depends(get_reasoning_service),
    db: Session = Depends(get_db_session),
) -> LiveReasoningResponse:
    alert = AlertSignal(
        alertname="LiveObservabilitySnapshot",
        namespace=namespace,
        service=service,
        severity=severity,
        status="firing",
    )
    result = reasoner.analyze(alert, window_minutes=_parse_time_window(time_window))
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
    alert = _extract_alert(payload, settings.telemetry.default_namespace, settings.telemetry.default_service)
    result = reasoner.analyze(alert, window_minutes=settings.telemetry.default_window_minutes)
    try:
        _persist_analysis_snapshot(db, alert, result)
    except Exception:
        # Persistence is best-effort and must not break webhook response path.
        pass
    return result

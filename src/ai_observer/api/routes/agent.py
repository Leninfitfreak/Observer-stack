from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ai_observer.backend.models.incident import Incident, IncidentStatusHistory
from ai_observer.incident_analysis.database import get_db_session
from ai_observer.incident_analysis.service_layer import IncidentAnalysisService

router = APIRouter(prefix="/api/agent", tags=["agent"])


class AgentIncident(BaseModel):
    incident_id: str | None = None
    service_name: str
    anomaly_score: float = Field(ge=0.0, le=1.0, default=0.0)
    confidence_score: float = Field(ge=0.0, le=1.0, default=0.0)
    classification: str = "Unknown"
    root_cause: str = ""
    mitigation: dict[str, Any] = Field(default_factory=dict)
    risk_forecast: float = Field(ge=0.0, le=1.0, default=0.0)
    mitigation_success: bool | None = None


class AgentPushPayload(BaseModel):
    cluster_id: str
    environment: str | None = None
    incidents: list[AgentIncident] = Field(default_factory=list)


class AgentPushResponse(BaseModel):
    accepted: bool
    cluster_id: str
    inserted: int


@router.post("/push", response_model=AgentPushResponse)
def push_from_agent(
    request: Request,
    payload: AgentPushPayload,
    db: Session = Depends(get_db_session),
    x_agent_token: str | None = Header(default=None, alias="X-Agent-Token"),
) -> AgentPushResponse:
    expected = request.app.state.container.settings.agent_token
    if not expected or x_agent_token != expected:
        raise HTTPException(status_code=401, detail="invalid_agent_token")

    svc = IncidentAnalysisService(
        db=db,
        default_cluster_id=request.app.state.container.settings.telemetry.default_cluster_id,
    )

    inserted = 0
    for row in payload.incidents:
        now = datetime.now(timezone.utc)
        generated_incident_id = row.incident_id or f"agent-{payload.cluster_id}-{row.service_name}-{now.strftime('%Y%m%d%H%M%S%f')}"

        if db.query(Incident).filter(Incident.incident_id == generated_incident_id).first() is None:
            db.add(
                Incident(
                    incident_id=generated_incident_id,
                    cluster_id=payload.cluster_id,
                    status="OPEN",
                    severity="WARNING",
                    impact_level="Low",
                    slo_breach_risk=row.risk_forecast * 100.0,
                    error_budget_remaining=100.0,
                    affected_services=row.service_name,
                    start_time=now,
                    duration="00:00:00",
                    created_at=now,
                )
            )
            db.add(
                IncidentStatusHistory(
                    incident_id=generated_incident_id,
                    from_status="OPEN",
                    to_status="OPEN",
                    changed_at=now,
                )
            )

        svc.save_incident_analysis(
            {
                "incident_id": generated_incident_id,
                "service_name": row.service_name,
                "cluster_id": payload.cluster_id,
                "anomaly_score": row.anomaly_score,
                "confidence_score": row.confidence_score,
                "classification": row.classification,
                "root_cause": row.root_cause or "unspecified",
                "mitigation": row.mitigation,
                "risk_forecast": row.risk_forecast,
                "mitigation_success": row.mitigation_success,
            }
        )
        inserted += 1

    return AgentPushResponse(accepted=True, cluster_id=payload.cluster_id, inserted=inserted)

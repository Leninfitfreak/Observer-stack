from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from ai_observer.incident_analysis.database import get_db_session
from ai_observer.incident_analysis.schemas import (
    IncidentAnalysisCreatedResponse,
    IncidentAnalysisCreate,
    IncidentAnalysisListResponse,
    IncidentAnalysisOut,
    IncidentAnalysisQuery,
    IncidentAnalysisSummaryResponse,
    MitigationPatchResponse,
    MitigationResultPatch,
)
from ai_observer.incident_analysis.service_layer import IncidentAnalysisService

router = APIRouter(prefix="/incident-analysis", tags=["incident-analysis"])


def get_service(db: Session = Depends(get_db_session)) -> IncidentAnalysisService:
    return IncidentAnalysisService(db=db)


@router.post("", response_model=IncidentAnalysisCreatedResponse)
def create_incident_analysis(
    payload: IncidentAnalysisCreate,
    service: IncidentAnalysisService = Depends(get_service),
) -> IncidentAnalysisCreatedResponse:
    try:
        incident = service.save_incident_analysis(payload.model_dump())
        historical = service.calculate_historical_similarity(payload.service_name, payload.anomaly_score)
        action_name = ""
        actions = payload.mitigation.get("actions")
        if isinstance(actions, list) and actions:
            action_name = str(actions[0])
        mitigation_rate = service.calculate_mitigation_success_rate(action_name) if action_name else {
            "action_name": "",
            "total_records": 0,
            "successful_records": 0,
            "success_rate_pct": 0.0,
        }
        return IncidentAnalysisCreatedResponse(
            incident=IncidentAnalysisOut.model_validate(incident),
            historical_similarity=historical,
            mitigation_success_rate=mitigation_rate,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"failed to save incident analysis: {exc}") from exc


@router.get("", response_model=IncidentAnalysisListResponse)
def get_incident_analysis(
    start_date: date = Query(...),
    end_date: date = Query(...),
    service_name: str | None = Query(default=None),
    classification: str | None = Query(default=None),
    min_confidence: float | None = Query(default=None, ge=0.0, le=100.0),
    anomaly_score_min: float | None = Query(default=None, ge=0.0, le=1.0),
    anomaly_score_max: float | None = Query(default=None, ge=0.0, le=1.0),
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    service: IncidentAnalysisService = Depends(get_service),
) -> IncidentAnalysisListResponse:
    query = IncidentAnalysisQuery(
        start_date=start_date,
        end_date=end_date,
        service_name=service_name,
        classification=classification,
        min_confidence=(min_confidence / 100.0) if min_confidence is not None else None,
        anomaly_score_min=anomaly_score_min,
        anomaly_score_max=anomaly_score_max,
        limit=limit,
        offset=offset,
    )
    total, rows = service.list_incidents(query)
    return IncidentAnalysisListResponse(
        total=total,
        limit=limit,
        offset=offset,
        items=[IncidentAnalysisOut.model_validate(row) for row in rows],
    )


@router.get("/summary", response_model=IncidentAnalysisSummaryResponse)
def get_incident_analysis_summary(
    start_date: date = Query(...),
    end_date: date = Query(...),
    service_name: str | None = Query(default=None),
    classification: str | None = Query(default=None),
    min_confidence: float | None = Query(default=None, ge=0.0, le=100.0),
    service: IncidentAnalysisService = Depends(get_service),
) -> IncidentAnalysisSummaryResponse:
    query = IncidentAnalysisQuery(
        start_date=start_date,
        end_date=end_date,
        service_name=service_name,
        classification=classification,
        min_confidence=(min_confidence / 100.0) if min_confidence is not None else None,
    )
    summary = service.summary(query)
    return IncidentAnalysisSummaryResponse(**summary)


@router.patch("/{incident_id}/mitigation-result", response_model=MitigationPatchResponse)
def patch_mitigation_result(
    incident_id: str,
    payload: MitigationResultPatch,
    service: IncidentAnalysisService = Depends(get_service),
) -> MitigationPatchResponse:
    updated = service.update_mitigation_result(incident_id=incident_id, mitigation_success=payload.mitigation_success)
    if updated == 0:
        raise HTTPException(status_code=404, detail=f"incident_id '{incident_id}' not found")
    return MitigationPatchResponse(incident_id=incident_id, updated=updated, mitigation_success=payload.mitigation_success)

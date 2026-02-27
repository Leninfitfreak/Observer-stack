from __future__ import annotations

import io
from datetime import date

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
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


def get_service(request: Request, db: Session = Depends(get_db_session)) -> IncidentAnalysisService:
    default_cluster_id = request.app.state.container.settings.telemetry.default_cluster_id
    return IncidentAnalysisService(db=db, default_cluster_id=default_cluster_id)


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
    cluster: str | None = Query(default=None),
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
        cluster=cluster,
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
    cluster: str | None = Query(default=None),
    classification: str | None = Query(default=None),
    min_confidence: float | None = Query(default=None, ge=0.0, le=100.0),
    service: IncidentAnalysisService = Depends(get_service),
) -> IncidentAnalysisSummaryResponse:
    query = IncidentAnalysisQuery(
        start_date=start_date,
        end_date=end_date,
        service_name=service_name,
        cluster=cluster,
        classification=classification,
        min_confidence=(min_confidence / 100.0) if min_confidence is not None else None,
    )
    summary = service.summary(query)
    return IncidentAnalysisSummaryResponse(**summary)


@router.get("/report")
def get_incident_analysis_report(
    start_date: date = Query(...),
    end_date: date = Query(...),
    service_name: str | None = Query(default=None),
    cluster: str | None = Query(default=None),
    classification: str | None = Query(default=None),
    min_confidence: float | None = Query(default=None, ge=0.0, le=100.0),
    service: IncidentAnalysisService = Depends(get_service),
) -> StreamingResponse:
    query = IncidentAnalysisQuery(
        start_date=start_date,
        end_date=end_date,
        service_name=service_name,
        cluster=cluster,
        classification=classification,
        min_confidence=(min_confidence / 100.0) if min_confidence is not None else None,
        limit=500,
        offset=0,
    )
    rows = service.report_rows(query)

    def mitigation_suggested(mitigation: dict) -> str:
        actions = mitigation.get("actions") if isinstance(mitigation, dict) else None
        if isinstance(actions, list) and actions:
            return str(actions[0])
        return ""

    records = [
        {
            "timestamp": row.created_at.isoformat(),
            "service_name": row.service_name,
            "cluster_id": row.cluster_id,
            "classification": row.classification,
            "anomaly_score": row.anomaly_score,
            "confidence_score": row.confidence_score,
            "risk_forecast": row.risk_forecast,
            "mitigation_suggested": mitigation_suggested(row.mitigation or {}),
            "mitigation_success": row.mitigation_success,
        }
        for row in rows
    ]
    df = pd.DataFrame(
        records,
        columns=[
            "timestamp",
            "service_name",
            "cluster_id",
            "classification",
            "anomaly_score",
            "confidence_score",
            "risk_forecast",
            "mitigation_suggested",
            "mitigation_success",
        ],
    )

    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="incident_history")
    output.seek(0)

    filename = f"incident_report_{date.today().strftime('%Y%m%d')}.xlsx"
    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers=headers,
    )


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

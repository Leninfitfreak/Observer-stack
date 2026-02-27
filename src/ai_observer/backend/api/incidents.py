from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from ai_observer.backend.schemas import IncidentDetailsResponse, IncidentExportRequest, IncidentFilterQuery, IncidentListResponse
from ai_observer.backend.services import IncidentsService
from ai_observer.incident_analysis.database import get_db_session

router = APIRouter(prefix="/api/incidents", tags=["incidents"])


def get_service(db: Session = Depends(get_db_session)) -> IncidentsService:
    return IncidentsService(db)


@router.get("", response_model=IncidentListResponse)
def list_incidents(
    start_date: date = Query(...),
    end_date: date = Query(...),
    classification: str | None = Query(default=None),
    min_confidence: float | None = Query(default=None, ge=0.0, le=100.0),
    service: str | None = Query(default=None),
    cluster: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    svc: IncidentsService = Depends(get_service),
) -> IncidentListResponse:
    query = IncidentFilterQuery(
        start_date=start_date,
        end_date=end_date,
        classification=classification,
        min_confidence=(min_confidence / 100.0) if min_confidence is not None else None,
        service=service,
        cluster=cluster,
        limit=limit,
        offset=offset,
    )
    total, data = svc.list(query)
    return IncidentListResponse(data=data, total_count=total, limit=limit, offset=offset)


@router.post("/export")
def export_incidents(payload: IncidentExportRequest, svc: IncidentsService = Depends(get_service)) -> StreamingResponse:
    query = IncidentFilterQuery(
        start_date=payload.start_date,
        end_date=payload.end_date,
        classification=payload.classification,
        min_confidence=(payload.min_confidence / 100.0) if payload.min_confidence is not None else None,
        service=payload.service,
        cluster=payload.cluster,
        limit=500,
        offset=0,
    )
    data = svc.export_excel(query)
    filename = f"incident_report_{date.today().strftime('%Y%m%d')}.xlsx"
    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
    return StreamingResponse(
        iter([data]),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers=headers,
    )


@router.get("/export")
def export_incidents_get(
    start_date: date = Query(...),
    end_date: date = Query(...),
    classification: str | None = Query(default=None),
    min_confidence: float | None = Query(default=None, ge=0.0, le=100.0),
    service: str | None = Query(default=None),
    cluster: str | None = Query(default=None),
    svc: IncidentsService = Depends(get_service),
) -> StreamingResponse:
    query = IncidentFilterQuery(
        start_date=start_date,
        end_date=end_date,
        classification=classification,
        min_confidence=(min_confidence / 100.0) if min_confidence is not None else None,
        service=service,
        cluster=cluster,
        limit=500,
        offset=0,
    )
    data = svc.export_excel(query)
    filename = f"incident_report_{date.today().strftime('%Y%m%d')}.xlsx"
    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
    return StreamingResponse(
        iter([data]),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers=headers,
    )


@router.get("/{incident_id}", response_model=IncidentDetailsResponse)
def get_incident(incident_id: str, svc: IncidentsService = Depends(get_service)) -> IncidentDetailsResponse:
    details = svc.details(incident_id)
    if details is None:
        raise HTTPException(status_code=404, detail=f"incident '{incident_id}' not found")
    return IncidentDetailsResponse(**details)

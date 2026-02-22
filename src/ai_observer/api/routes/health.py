from __future__ import annotations

from fastapi import APIRouter

from ai_observer.domain.models import HealthResponse

router = APIRouter()


@router.get("/healthz", response_model=HealthResponse)
def healthz() -> HealthResponse:
    return HealthResponse(status="ok")

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, Field, model_validator


class IncidentFilterQuery(BaseModel):
    start_date: date
    end_date: date
    severity: str | None = None
    classification: str | None = None
    min_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    service: str | None = None
    cluster: str | None = None
    namespace: str | None = None
    limit: int = Field(default=20, ge=1, le=500)
    offset: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def validate_range(self) -> "IncidentFilterQuery":
        if self.end_date < self.start_date:
            raise ValueError("end_date must be >= start_date")
        return self


class IncidentListItem(BaseModel):
    incident_id: str
    cluster_id: str
    status: str
    severity: str
    impact_level: str
    slo_breach_risk: float
    error_budget_remaining: float
    affected_services: str
    start_time: datetime
    duration: str
    created_at: datetime
    executive_summary: str | None = None
    root_cause: str | None = None
    confidence_score: float | None = None
    classification: str | None = None
    risk_forecast: float | None = None
    cpu_usage: float | None = None
    memory_usage: float | None = None
    request_rate: float | None = None
    pod_restarts: float | None = None
    error_rate: float | None = None
    origin_service: str | None = None
    topology_insights: dict[str, Any] | None = None
    causal_chain: list[str] | None = None


class IncidentListResponse(BaseModel):
    data: list[IncidentListItem]
    total_count: int
    limit: int
    offset: int


class IncidentDetailsResponse(BaseModel):
    incident: dict[str, Any]
    analysis: list[dict[str, Any]]
    metrics_snapshot: list[dict[str, Any]]
    status_history: list[dict[str, Any]]


class IncidentExportRequest(BaseModel):
    start_date: date
    end_date: date
    severity: str | None = None
    classification: str | None = None
    min_confidence: float | None = Field(default=None, ge=0.0, le=100.0)
    service: str | None = None
    cluster: str | None = None
    namespace: str | None = None


class IncidentFilterOptionsResponse(BaseModel):
    clusters: list[str]
    namespaces: list[str]
    services: list[str]

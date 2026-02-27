from __future__ import annotations

from datetime import date, datetime, time, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def _to_utc_start(value: date) -> datetime:
    return datetime.combine(value, time.min).replace(tzinfo=timezone.utc)


def _to_utc_end_exclusive(value: date) -> datetime:
    return datetime.combine(value, time.max).replace(tzinfo=timezone.utc)


class IncidentAnalysisCreate(BaseModel):
    incident_id: str = Field(min_length=1, max_length=128)
    service_name: str = Field(min_length=1, max_length=128)
    cluster_id: str | None = Field(default=None, max_length=128)
    anomaly_score: float = Field(ge=0.0, le=1.0)
    confidence_score: float = Field(ge=0.0, le=1.0)
    classification: str = Field(min_length=1, max_length=64)
    root_cause: str = Field(min_length=1)
    mitigation: dict[str, Any] = Field(default_factory=dict)
    risk_forecast: float = Field(ge=0.0, le=1.0)
    mitigation_success: bool | None = None


class IncidentAnalysisOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    incident_id: str
    service_name: str
    cluster_id: str
    anomaly_score: float
    confidence_score: float
    classification: str
    root_cause: str
    mitigation: dict[str, Any]
    risk_forecast: float
    mitigation_success: bool | None
    created_at: datetime


class IncidentAnalysisCreatedResponse(BaseModel):
    incident: IncidentAnalysisOut
    historical_similarity: dict[str, Any]
    mitigation_success_rate: dict[str, Any]


class IncidentAnalysisQuery(BaseModel):
    start_date: date
    end_date: date
    service_name: str | None = None
    cluster: str | None = None
    classification: str | None = None
    min_confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    anomaly_score_min: float | None = Field(default=None, ge=0.0, le=1.0)
    anomaly_score_max: float | None = Field(default=None, ge=0.0, le=1.0)
    limit: int = Field(default=50, ge=1, le=500)
    offset: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def validate_date_range(self) -> "IncidentAnalysisQuery":
        if self.end_date < self.start_date:
            raise ValueError("end_date must be greater than or equal to start_date")
        if self.anomaly_score_min is not None and self.anomaly_score_max is not None:
            if self.anomaly_score_max < self.anomaly_score_min:
                raise ValueError("anomaly_score_max must be >= anomaly_score_min")
        return self

    @property
    def start_dt_utc(self) -> datetime:
        return _to_utc_start(self.start_date)

    @property
    def end_dt_utc(self) -> datetime:
        return _to_utc_end_exclusive(self.end_date)


class IncidentAnalysisListResponse(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[IncidentAnalysisOut]


class IncidentAnalysisSummaryResponse(BaseModel):
    total_incidents: int
    avg_anomaly_score: float
    avg_confidence_score: float
    classification_distribution: dict[str, int]
    top_mitigation: str


class MitigationResultPatch(BaseModel):
    mitigation_success: bool


class MitigationPatchResponse(BaseModel):
    incident_id: str
    updated: int
    mitigation_success: bool

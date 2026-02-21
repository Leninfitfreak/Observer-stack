from typing import Any

from pydantic import BaseModel, Field


class AlertLabels(BaseModel):
    alertname: str = "UnknownAlert"
    severity: str = "unknown"
    namespace: str | None = None
    service: str | None = None
    app: str | None = None


class AlertItem(BaseModel):
    status: str = "firing"
    labels: dict[str, str] = Field(default_factory=dict)
    annotations: dict[str, str] = Field(default_factory=dict)
    startsAt: str | None = None
    endsAt: str | None = None
    generatorURL: str | None = None


class AlertmanagerWebhook(BaseModel):
    version: str | None = None
    groupKey: str | None = None
    status: str | None = None
    receiver: str | None = None
    groupLabels: dict[str, str] = Field(default_factory=dict)
    commonLabels: dict[str, str] = Field(default_factory=dict)
    commonAnnotations: dict[str, str] = Field(default_factory=dict)
    externalURL: str | None = None
    alerts: list[AlertItem] = Field(default_factory=list)


class AnalysisContext(BaseModel):
    alert: dict[str, Any]
    metrics: dict[str, Any]
    logs_summary: str
    trace_summary: str
    datasource_errors: dict[str, str] = Field(default_factory=dict)


class LlmAnalysis(BaseModel):
    probable_root_cause: str
    impact_level: str
    recommended_remediation: str
    confidence_score: str


class AlertAnalysisResponse(BaseModel):
    context: AnalysisContext
    analysis: LlmAnalysis


class HealthResponse(BaseModel):
    status: str

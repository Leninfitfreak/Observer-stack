from typing import Any

from pydantic import BaseModel, Field


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
    traces: dict[str, Any]
    logs: dict[str, Any]
    kubernetes: dict[str, Any]
    deployment: dict[str, Any]
    slo: dict[str, Any]
    datasource_errors: dict[str, str] = Field(default_factory=dict)


class LlmAnalysis(BaseModel):
    probable_root_cause: str
    impact_level: str
    recommended_remediation: str
    confidence_score: str
    confidence: float | None = None
    causal_chain: list[str] = Field(default_factory=list)
    corrective_actions: list[str] = Field(default_factory=list)
    preventive_hardening: list[str] = Field(default_factory=list)
    risk_forecast: dict[str, Any] = Field(default_factory=dict)
    deployment_correlation: dict[str, Any] = Field(default_factory=dict)
    error_log_prediction: dict[str, Any] = Field(default_factory=dict)
    missing_observability: list[str] = Field(default_factory=list)
    human_summary: str | None = None
    policy_note: str | None = None


class AlertAnalysisResponse(BaseModel):
    context: AnalysisContext
    analysis: LlmAnalysis


class HealthResponse(BaseModel):
    status: str

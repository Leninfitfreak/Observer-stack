from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class AlertSignal(BaseModel):
    alertname: str
    namespace: str
    service: str
    severity: str
    status: str = "firing"


class ObservabilityContext(BaseModel):
    alert: dict[str, Any]
    time_window_minutes: int
    metrics: dict[str, Any] = Field(default_factory=dict)
    logs: dict[str, Any] = Field(default_factory=dict)
    traces: dict[str, Any] = Field(default_factory=dict)
    kubernetes: dict[str, Any] = Field(default_factory=dict)
    deployment: dict[str, Any] = Field(default_factory=dict)
    components: list[dict[str, Any]] = Field(default_factory=list)
    component_metrics: dict[str, dict[str, Any]] = Field(default_factory=dict)
    component_summary: dict[str, Any] = Field(default_factory=dict)
    cluster_wiring: dict[str, Any] = Field(default_factory=dict)
    datasource_errors: dict[str, str] = Field(default_factory=dict)


class ReasoningResult(BaseModel):
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
    executive_summary: str | None = None
    assessment: str | None = None
    most_likely_scenario: str | None = None
    why_not_resource_saturation: list[str] = Field(default_factory=list)
    incident_classification: str | None = None
    confidence_details: dict[str, Any] = Field(default_factory=dict)
    ai_response_status: str | None = None
    change_detection_context: list[str] = Field(default_factory=list)


class LiveReasoningResponse(BaseModel):
    context: ObservabilityContext
    analysis: ReasoningResult


class HealthResponse(BaseModel):
    status: str = "ok"

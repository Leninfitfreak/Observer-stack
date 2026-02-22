from __future__ import annotations

from pydantic import BaseModel, Field


class AlertItem(BaseModel):
    status: str = "firing"
    labels: dict[str, str] = Field(default_factory=dict)
    annotations: dict[str, str] = Field(default_factory=dict)


class AlertmanagerWebhook(BaseModel):
    commonLabels: dict[str, str] = Field(default_factory=dict)
    alerts: list[AlertItem] = Field(default_factory=list)

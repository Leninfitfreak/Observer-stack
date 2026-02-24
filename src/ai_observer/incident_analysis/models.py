from datetime import datetime, timezone
from typing import Any

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import JSON


class Base(DeclarativeBase):
    pass


JsonType = JSON().with_variant(JSONB, "postgresql")


class IncidentAnalysis(Base):
    __tablename__ = "incident_analysis"
    __table_args__ = (
        Index("ix_incident_analysis_created_at", "created_at"),
        Index("ix_incident_analysis_service_name", "service_name"),
        Index("ix_incident_analysis_incident_id", "incident_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    incident_id: Mapped[str] = mapped_column(
        String(128),
        ForeignKey("incidents.incident_id", ondelete="CASCADE"),
        nullable=False,
    )
    service_name: Mapped[str] = mapped_column(String(128), nullable=False)
    anomaly_score: Mapped[float] = mapped_column(Float, nullable=False)
    confidence_score: Mapped[float] = mapped_column(Float, nullable=False)
    classification: Mapped[str] = mapped_column(String(64), nullable=False)
    root_cause: Mapped[str] = mapped_column(Text, nullable=False)
    mitigation: Mapped[dict] = mapped_column(JsonType, nullable=False, default=dict)
    risk_forecast: Mapped[float] = mapped_column(Float, nullable=False)
    mitigation_success: Mapped[bool] = mapped_column(Boolean, nullable=True)
    executive_summary: Mapped[str] = mapped_column(Text, nullable=True)
    supporting_signals: Mapped[dict] = mapped_column(JsonType, nullable=False, default=dict)
    suggested_actions: Mapped[dict] = mapped_column(JsonType, nullable=False, default=dict)
    confidence_breakdown: Mapped[dict] = mapped_column(JsonType, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
    )

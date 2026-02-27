from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from ai_observer.incident_analysis.models import Base

JsonType = JSON().with_variant(JSONB, "postgresql")


class Incident(Base):
    __tablename__ = "incidents"
    __table_args__ = (
        Index("ix_incidents_incident_id", "incident_id", unique=True),
        Index("ix_incidents_created_at", "created_at"),
        Index("ix_incidents_start_time", "start_time"),
        Index("ix_incidents_cluster_id", "cluster_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    incident_id: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    cluster_id: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    severity: Mapped[str] = mapped_column(String(32), nullable=False)
    impact_level: Mapped[str] = mapped_column(String(32), nullable=False, default="Low")
    slo_breach_risk: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    error_budget_remaining: Mapped[float] = mapped_column(Float, nullable=False, default=100.0)
    affected_services: Mapped[str] = mapped_column(Text, nullable=False, default="")
    start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc))
    duration: Mapped[str] = mapped_column(String(32), nullable=False, default="00:00:00")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
    )


class IncidentMetricsSnapshot(Base):
    __tablename__ = "incident_metrics_snapshot"
    __table_args__ = (
        Index("ix_metrics_snapshot_incident_id", "incident_id"),
        Index("ix_metrics_snapshot_captured_at", "captured_at"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    incident_id: Mapped[str] = mapped_column(String(128), ForeignKey("incidents.incident_id", ondelete="CASCADE"), nullable=False)
    cpu_usage: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    memory_usage: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    latency_p95: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    error_rate: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    thread_pool_saturation: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    raw_metrics_json: Mapped[dict] = mapped_column(JsonType, nullable=False, default=dict)
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
    )


class IncidentStatusHistory(Base):
    __tablename__ = "incident_status_history"
    __table_args__ = (Index("ix_status_history_incident_id", "incident_id"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    incident_id: Mapped[str] = mapped_column(String(128), ForeignKey("incidents.incident_id", ondelete="CASCADE"), nullable=False)
    from_status: Mapped[str] = mapped_column(String(32), nullable=False)
    to_status: Mapped[str] = mapped_column(String(32), nullable=False)
    changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
    )

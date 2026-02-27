from __future__ import annotations

from datetime import datetime, time, timezone
from typing import Any

from sqlalchemy import and_, desc, func, select
from sqlalchemy.orm import Session

from ai_observer.backend.models.incident import Incident, IncidentMetricsSnapshot, IncidentStatusHistory
from ai_observer.backend.schemas.incidents import IncidentFilterQuery
from ai_observer.incident_analysis.models import IncidentAnalysis


class IncidentsRepository:
    def __init__(self, db: Session):
        self.db = db

    @staticmethod
    def _start_dt(value) -> datetime:
        return datetime.combine(value, time.min).replace(tzinfo=timezone.utc)

    @staticmethod
    def _end_dt(value) -> datetime:
        return datetime.combine(value, time.max).replace(tzinfo=timezone.utc)

    def _base_conditions(self, query: IncidentFilterQuery) -> list[Any]:
        conditions: list[Any] = [
            Incident.created_at >= self._start_dt(query.start_date),
            Incident.created_at <= self._end_dt(query.end_date),
        ]
        if query.service:
            conditions.append(Incident.affected_services.ilike(f"%{query.service}%"))
        if query.cluster:
            conditions.append(Incident.cluster_id == query.cluster)
        return conditions

    def list_incidents(self, query: IncidentFilterQuery) -> tuple[int, list[tuple[Incident, IncidentAnalysis | None]]]:
        conditions = self._base_conditions(query)
        stmt = (
            select(Incident, IncidentAnalysis)
            .outerjoin(IncidentAnalysis, IncidentAnalysis.incident_id == Incident.incident_id)
            .where(and_(*conditions))
        )
        if query.classification:
            stmt = stmt.where(IncidentAnalysis.classification == query.classification)
        if query.min_confidence is not None:
            stmt = stmt.where(IncidentAnalysis.confidence_score >= query.min_confidence)

        total_stmt = select(func.count()).select_from(stmt.subquery())
        total = int(self.db.execute(total_stmt).scalar_one() or 0)

        rows_stmt = stmt.order_by(desc(Incident.created_at)).offset(query.offset).limit(query.limit)
        rows = list(self.db.execute(rows_stmt).all())
        return total, rows

    def get_incident_details(self, incident_id: str) -> dict[str, Any] | None:
        incident = self.db.execute(select(Incident).where(Incident.incident_id == incident_id)).scalar_one_or_none()
        if incident is None:
            return None

        analyses = list(
            self.db.execute(
                select(IncidentAnalysis).where(IncidentAnalysis.incident_id == incident_id).order_by(desc(IncidentAnalysis.created_at))
            ).scalars()
        )
        metrics = list(
            self.db.execute(
                select(IncidentMetricsSnapshot)
                .where(IncidentMetricsSnapshot.incident_id == incident_id)
                .order_by(desc(IncidentMetricsSnapshot.captured_at))
            ).scalars()
        )
        history = list(
            self.db.execute(
                select(IncidentStatusHistory)
                .where(IncidentStatusHistory.incident_id == incident_id)
                .order_by(desc(IncidentStatusHistory.changed_at))
            ).scalars()
        )
        return {
            "incident": incident,
            "analysis": analyses,
            "metrics_snapshot": metrics,
            "status_history": history,
        }

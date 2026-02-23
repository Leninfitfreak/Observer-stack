from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import and_, desc, func, select, update
from sqlalchemy.orm import Session

from ai_observer.incident_analysis.models import IncidentAnalysis
from ai_observer.incident_analysis.schemas import IncidentAnalysisCreate, IncidentAnalysisQuery


class IncidentAnalysisService:
    def __init__(self, db: Session):
        self.db = db

    def save_incident_analysis(self, data: dict[str, Any]) -> IncidentAnalysis:
        payload = IncidentAnalysisCreate.model_validate(data)
        entity = IncidentAnalysis(**payload.model_dump())
        self.db.add(entity)
        self.db.commit()
        self.db.refresh(entity)
        return entity

    def list_incidents(self, query: IncidentAnalysisQuery) -> tuple[int, list[IncidentAnalysis]]:
        conditions = [
            func.date(IncidentAnalysis.created_at) >= query.start_date.isoformat(),
            func.date(IncidentAnalysis.created_at) <= query.end_date.isoformat(),
        ]
        if query.service_name:
            conditions.append(IncidentAnalysis.service_name == query.service_name)

        where_clause = and_(*conditions)
        total_stmt = select(func.count(IncidentAnalysis.id)).where(where_clause)
        total = int(self.db.execute(total_stmt).scalar_one() or 0)

        rows_stmt = (
            select(IncidentAnalysis)
            .where(where_clause)
            .order_by(desc(IncidentAnalysis.created_at))
            .offset(query.offset)
            .limit(query.limit)
        )
        rows = list(self.db.execute(rows_stmt).scalars().all())
        return total, rows

    def summary(self, query: IncidentAnalysisQuery) -> dict[str, Any]:
        conditions = [
            func.date(IncidentAnalysis.created_at) >= query.start_date.isoformat(),
            func.date(IncidentAnalysis.created_at) <= query.end_date.isoformat(),
        ]
        if query.service_name:
            conditions.append(IncidentAnalysis.service_name == query.service_name)
        where_clause = and_(*conditions)

        agg_stmt = select(
            func.count(IncidentAnalysis.id),
            func.avg(IncidentAnalysis.anomaly_score),
            func.avg(IncidentAnalysis.confidence_score),
        ).where(where_clause)
        total, avg_anomaly, avg_conf = self.db.execute(agg_stmt).one()

        class_stmt = (
            select(IncidentAnalysis.classification, func.count(IncidentAnalysis.id))
            .where(where_clause)
            .group_by(IncidentAnalysis.classification)
        )
        distribution = {row[0]: int(row[1]) for row in self.db.execute(class_stmt).all()}

        return {
            "total_incidents": int(total or 0),
            "avg_anomaly_score": float(avg_anomaly or 0.0),
            "avg_confidence_score": float(avg_conf or 0.0),
            "classification_distribution": distribution,
        }

    def update_mitigation_result(self, incident_id: str, mitigation_success: bool) -> int:
        latest_stmt = (
            select(IncidentAnalysis.id)
            .where(IncidentAnalysis.incident_id == incident_id)
            .order_by(desc(IncidentAnalysis.created_at))
            .limit(1)
        )
        latest_id = self.db.execute(latest_stmt).scalar_one_or_none()
        if latest_id is None:
            return 0

        update_stmt = (
            update(IncidentAnalysis)
            .where(IncidentAnalysis.id == latest_id)
            .values(mitigation_success=mitigation_success)
        )
        result = self.db.execute(update_stmt)
        self.db.commit()
        return int(result.rowcount or 0)

    def calculate_historical_similarity(self, service_name: str, anomaly_score: float, tolerance: float = 0.12) -> dict[str, Any]:
        low = max(0.0, anomaly_score - tolerance)
        high = min(1.0, anomaly_score + tolerance)
        stmt = select(func.count(IncidentAnalysis.id)).where(
            and_(
                IncidentAnalysis.service_name == service_name,
                IncidentAnalysis.anomaly_score >= low,
                IncidentAnalysis.anomaly_score <= high,
            )
        )
        count = int(self.db.execute(stmt).scalar_one() or 0)
        return {
            "service_name": service_name,
            "target_anomaly_score": anomaly_score,
            "tolerance": tolerance,
            "similar_incident_count": count,
        }

    def calculate_mitigation_success_rate(self, action_name: str) -> dict[str, Any]:
        normalized_action = (action_name or "").strip().lower()
        all_rows = self.db.execute(select(IncidentAnalysis)).scalars().all()
        matched = []
        for row in all_rows:
            mitigation = row.mitigation or {}
            actions = mitigation.get("actions", [])
            if isinstance(actions, list) and any(normalized_action in str(item).lower() for item in actions):
                matched.append(row)

        total = len(matched)
        success = sum(1 for item in matched if item.mitigation_success is True)
        rate = (success / total * 100.0) if total > 0 else 0.0
        return {
            "action_name": action_name,
            "total_records": total,
            "successful_records": success,
            "success_rate_pct": rate,
        }

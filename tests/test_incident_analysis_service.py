from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from ai_observer.incident_analysis.models import Base
from ai_observer.incident_analysis.schemas import IncidentAnalysisQuery
from ai_observer.incident_analysis.service_layer import IncidentAnalysisService


def _build_service() -> IncidentAnalysisService:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    session: Session = factory()
    return IncidentAnalysisService(db=session)


def test_insert_and_similarity() -> None:
    service = _build_service()
    row = service.save_incident_analysis(
        {
            "incident_id": "INC-1",
            "service_name": "product-service",
            "anomaly_score": 0.21,
            "confidence_score": 0.71,
            "classification": "Performance Degradation",
            "root_cause": "db latency spike",
            "mitigation": {"actions": ["Restart Pod"]},
            "risk_forecast": 0.33,
            "mitigation_success": True,
        }
    )
    assert row.id > 0
    sim = service.calculate_historical_similarity("product-service", 0.20)
    assert sim["similar_incident_count"] >= 1


def test_date_filtering() -> None:
    service = _build_service()
    row = service.save_incident_analysis(
        {
            "incident_id": "INC-2",
            "service_name": "order-service",
            "anomaly_score": 0.18,
            "confidence_score": 0.66,
            "classification": "False Positive",
            "root_cause": "transient",
            "mitigation": {"actions": ["Observe"]},
            "risk_forecast": 0.11,
            "mitigation_success": None,
        }
    )
    created_date = row.created_at.date()
    q = IncidentAnalysisQuery(start_date=created_date, end_date=created_date, service_name="order-service", limit=10, offset=0)
    total, rows = service.list_incidents(q)
    assert total == 1
    assert len(rows) == 1
    assert rows[0].service_name == "order-service"


def test_mitigation_update() -> None:
    service = _build_service()
    row = service.save_incident_analysis(
        {
            "incident_id": "INC-3",
            "service_name": "order-service",
            "anomaly_score": 0.42,
            "confidence_score": 0.52,
            "classification": "Observability Gap",
            "root_cause": "missing metric",
            "mitigation": {"actions": ["Restart Pod"]},
            "risk_forecast": 0.18,
            "mitigation_success": None,
        }
    )
    updated = service.update_mitigation_result("INC-3", True)
    assert updated == 1
    created_date = row.created_at.date()
    q = IncidentAnalysisQuery(start_date=created_date, end_date=created_date, limit=10, offset=0)
    _total, rows = service.list_incidents(q)
    assert rows[0].mitigation_success is True

from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from ai_observer.backend.models.incident import Incident
from ai_observer.backend.schemas.incidents import IncidentFilterQuery
from ai_observer.backend.services.incidents_service import IncidentsService
from ai_observer.incident_analysis.models import Base


def _build_service() -> tuple[IncidentsService, Session]:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(bind=engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    session: Session = factory()
    return IncidentsService(db=session), session


def _seed(session: Session) -> None:
    now = datetime.now(timezone.utc)
    session.add(
        Incident(
            incident_id="INC-FLT-1",
            cluster_id="minikube-dev",
            status="OPEN",
            severity="WARNING",
            impact_level="Low",
            slo_breach_risk=12.5,
            error_budget_remaining=98.0,
            affected_services="leninkart-product-service",
            start_time=now,
            duration="00:01:00",
            created_at=now,
            raw_payload={
                "namespace": "dev",
                "topology": {
                    "namespace_segmentation": {"dev": {"pods": 4, "services": 3}},
                    "relations": {
                        "service_to_pod": [
                            {"service": "dev/leninkart-product-service", "pod": "dev/product-service-abc"}
                        ]
                    },
                },
            },
        )
    )
    session.add(
        Incident(
            incident_id="INC-FLT-2",
            cluster_id="default-cluster",
            status="OPEN",
            severity="INFO",
            impact_level="Low",
            slo_breach_risk=8.0,
            error_budget_remaining=99.0,
            affected_services="all",
            start_time=now,
            duration="00:01:00",
            created_at=now,
            raw_payload={},
        )
    )
    session.commit()


def test_filter_options_are_backend_driven_and_no_placeholder_clusters() -> None:
    service, session = _build_service()
    _seed(session)

    query = IncidentFilterQuery(start_date=date(2026, 1, 1), end_date=date(2026, 12, 31), limit=20, offset=0)
    options = service.filter_options(query)

    assert options["clusters"] == ["minikube-dev"]
    assert options["namespaces"] == ["dev"]
    assert "leninkart-product-service" in options["services"]


def test_list_supports_cluster_namespace_service_backend_filtering() -> None:
    service, session = _build_service()
    _seed(session)

    query = IncidentFilterQuery(
        start_date=date(2026, 1, 1),
        end_date=date(2026, 12, 31),
        cluster="minikube-dev",
        namespace="dev",
        service="leninkart-product-service",
        limit=20,
        offset=0,
    )
    total, rows = service.list(query)

    assert total == 1
    assert len(rows) == 1
    assert rows[0]["incident_id"] == "INC-FLT-1"


def test_list_supports_severity_filter_backend() -> None:
    service, session = _build_service()
    _seed(session)

    query = IncidentFilterQuery(
        start_date=date(2026, 1, 1),
        end_date=date(2026, 12, 31),
        severity="warning",
        limit=20,
        offset=0,
    )
    total, rows = service.list(query)

    assert total == 1
    assert len(rows) == 1
    assert rows[0]["incident_id"] == "INC-FLT-1"

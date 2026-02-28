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
        if query.cluster:
            conditions.append(Incident.cluster_id == query.cluster)
        if query.severity:
            conditions.append(func.lower(Incident.severity) == query.severity.lower())
        return conditions

    @staticmethod
    def _normalize_token(value: str | None) -> str:
        return str(value or "").strip()

    @classmethod
    def _is_placeholder(cls, value: str | None) -> bool:
        token = cls._normalize_token(value).lower()
        return token in {"", "all", "unknown", "default", "default-cluster", "*"}

    @classmethod
    def _service_aliases(cls, service_name: str) -> set[str]:
        name = cls._normalize_token(service_name)
        if not name:
            return set()
        aliases = {name}
        if "/" in name:
            aliases.add(name.split("/", 1)[1])
        return {a for a in aliases if not cls._is_placeholder(a)}

    @classmethod
    def _extract_namespaces_services(cls, incident: Incident, analysis: IncidentAnalysis | None) -> tuple[set[str], set[str]]:
        namespaces: set[str] = set()
        services: set[str] = set()

        cluster = cls._normalize_token(incident.cluster_id)
        if cluster and not cls._is_placeholder(cluster):
            # cluster intentionally not included in namespace/service sets.
            pass

        for svc in [s.strip() for s in str(incident.affected_services or "").split(",") if s.strip()]:
            for alias in cls._service_aliases(svc):
                services.add(alias)

        raw = incident.raw_payload if isinstance(incident.raw_payload, dict) else {}
        namespace_candidate = cls._normalize_token(raw.get("namespace"))
        if namespace_candidate and not cls._is_placeholder(namespace_candidate):
            namespaces.add(namespace_candidate)
        environment_candidate = cls._normalize_token(raw.get("environment"))
        if environment_candidate and not cls._is_placeholder(environment_candidate):
            namespaces.add(environment_candidate)

        topology = raw.get("topology") if isinstance(raw.get("topology"), dict) else {}
        ns_seg = topology.get("namespace_segmentation") if isinstance(topology.get("namespace_segmentation"), dict) else {}
        for ns in ns_seg.keys():
            ns_name = cls._normalize_token(ns)
            if ns_name and not cls._is_placeholder(ns_name):
                namespaces.add(ns_name)

        relations = topology.get("relations") if isinstance(topology.get("relations"), dict) else {}
        service_to_pod = relations.get("service_to_pod") if isinstance(relations.get("service_to_pod"), list) else []
        for rel in service_to_pod:
            if not isinstance(rel, dict):
                continue
            svc = cls._normalize_token(rel.get("service"))
            if svc:
                for alias in cls._service_aliases(svc):
                    services.add(alias)
                if "/" in svc:
                    ns = svc.split("/", 1)[0]
                    if ns and not cls._is_placeholder(ns):
                        namespaces.add(ns)
            pod = cls._normalize_token(rel.get("pod"))
            if "/" in pod:
                pod_ns = pod.split("/", 1)[0]
                if pod_ns and not cls._is_placeholder(pod_ns):
                    namespaces.add(pod_ns)

        service_to_service = relations.get("service_to_service") if isinstance(relations.get("service_to_service"), list) else []
        for rel in service_to_service:
            if not isinstance(rel, dict):
                continue
            for key in ("from_service", "to_service"):
                svc = cls._normalize_token(rel.get(key))
                for alias in cls._service_aliases(svc):
                    services.add(alias)
                if "/" in svc:
                    ns = svc.split("/", 1)[0]
                    if ns and not cls._is_placeholder(ns):
                        namespaces.add(ns)

        observability_services = topology.get("observability_services") if isinstance(topology.get("observability_services"), dict) else {}
        for svc in observability_services.values():
            svc_name = cls._normalize_token(svc)
            for alias in cls._service_aliases(svc_name):
                services.add(alias)
            if "/" in svc_name:
                ns = svc_name.split("/", 1)[0]
                if ns and not cls._is_placeholder(ns):
                    namespaces.add(ns)

        if analysis:
            svc = cls._normalize_token(getattr(analysis, "service_name", ""))
            for alias in cls._service_aliases(svc):
                services.add(alias)
            mitigation = analysis.mitigation if isinstance(analysis.mitigation, dict) else {}
            top = mitigation.get("topology_insights") if isinstance(mitigation.get("topology_insights"), dict) else {}
            origin = cls._normalize_token(top.get("likely_origin_service") or mitigation.get("origin_service"))
            for alias in cls._service_aliases(origin):
                services.add(alias)
            impacted = top.get("impacted_services") if isinstance(top.get("impacted_services"), list) else []
            for svc_name in impacted:
                for alias in cls._service_aliases(str(svc_name)):
                    services.add(alias)

        return namespaces, services

    @classmethod
    def _row_matches_scope(cls, incident: Incident, analysis: IncidentAnalysis | None, namespace: str | None, service: str | None) -> bool:
        namespaces, services = cls._extract_namespaces_services(incident, analysis)
        query_ns = cls._normalize_token(namespace)
        query_svc = cls._normalize_token(service)
        if query_ns and not cls._is_placeholder(query_ns):
            if query_ns not in namespaces:
                return False
        if query_svc and not cls._is_placeholder(query_svc):
            svc_aliases = cls._service_aliases(query_svc)
            if not svc_aliases:
                return False
            filterable_services: set[str] = set()
            for svc in [s.strip() for s in str(incident.affected_services or "").split(",") if s.strip()]:
                filterable_services.update(cls._service_aliases(svc))
            if analysis:
                filterable_services.update(cls._service_aliases(getattr(analysis, "service_name", "")))
                mitigation = analysis.mitigation if isinstance(analysis.mitigation, dict) else {}
                top = mitigation.get("topology_insights") if isinstance(mitigation.get("topology_insights"), dict) else {}
                filterable_services.update(cls._service_aliases(top.get("likely_origin_service")))
                filterable_services.update(cls._service_aliases(mitigation.get("origin_service")))
            raw = incident.raw_payload if isinstance(incident.raw_payload, dict) else {}
            incidents_payload = raw.get("incidents") if isinstance(raw.get("incidents"), list) else []
            for item in incidents_payload:
                if not isinstance(item, dict):
                    continue
                filterable_services.update(cls._service_aliases(item.get("service_name")))
            if not filterable_services:
                filterable_services = services
            if not (svc_aliases & filterable_services):
                return False
        return True

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

        rows_stmt = stmt.order_by(desc(Incident.created_at))
        rows = list(self.db.execute(rows_stmt).all())
        if query.namespace or query.service:
            rows = [
                (incident, analysis)
                for incident, analysis in rows
                if self._row_matches_scope(incident, analysis, query.namespace, query.service)
            ]
        total = len(rows)
        rows = rows[query.offset : query.offset + query.limit]
        return total, rows

    def list_filter_options(self, query: IncidentFilterQuery) -> dict[str, list[str]]:
        conditions = [
            Incident.created_at >= self._start_dt(query.start_date),
            Incident.created_at <= self._end_dt(query.end_date),
        ]
        stmt = (
            select(Incident, IncidentAnalysis)
            .outerjoin(IncidentAnalysis, IncidentAnalysis.incident_id == Incident.incident_id)
            .where(and_(*conditions))
            .order_by(desc(Incident.created_at))
        )
        if query.classification:
            stmt = stmt.where(IncidentAnalysis.classification == query.classification)
        if query.min_confidence is not None:
            stmt = stmt.where(IncidentAnalysis.confidence_score >= query.min_confidence)

        rows = list(self.db.execute(stmt).all())
        clusters = sorted(
            {
                cluster
                for cluster in (self._normalize_token(incident.cluster_id) for incident, _ in rows)
                if cluster and not self._is_placeholder(cluster)
            }
        )

        cluster_rows = rows
        if query.cluster and not self._is_placeholder(query.cluster):
            cluster_rows = [(incident, analysis) for incident, analysis in rows if self._normalize_token(incident.cluster_id) == query.cluster]

        namespaces_set: set[str] = set()
        for incident, analysis in cluster_rows:
            namespaces, _ = self._extract_namespaces_services(incident, analysis)
            namespaces_set.update(namespaces)
        namespaces = sorted(ns for ns in namespaces_set if ns and not self._is_placeholder(ns))

        namespace_rows = cluster_rows
        if query.namespace and not self._is_placeholder(query.namespace):
            namespace_rows = [
                (incident, analysis)
                for incident, analysis in cluster_rows
                if self._row_matches_scope(incident, analysis, query.namespace, None)
            ]

        services_set: set[str] = set()
        for incident, analysis in namespace_rows:
            _, services = self._extract_namespaces_services(incident, analysis)
            services_set.update(services)
        services = sorted(s for s in services_set if s and not self._is_placeholder(s))
        return {"clusters": clusters, "namespaces": namespaces, "services": services}

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

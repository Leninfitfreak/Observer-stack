from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from statistics import mean

import clickhouse_connect

from .config import Settings


TRACES_TABLE = "signoz_traces.distributed_signoz_index_v3"
TRACE_RESOURCES_TABLE = "signoz_traces.distributed_traces_v3_resource"
LOGS_TABLE = "signoz_logs.distributed_logs_v2"
LOG_RESOURCES_TABLE = "signoz_logs.distributed_logs_v2_resource"
METRICS_TABLE = "signoz_metrics.distributed_time_series_v4"
SAMPLES_TABLE = "signoz_metrics.distributed_samples_v4"
logger = logging.getLogger(__name__)


@dataclass
class TelemetryContext:
    metrics_summary: dict
    logs_summary: dict
    trace_summary: dict
    db_summary: dict
    messaging_summary: dict
    exception_summary: dict
    infra_summary: dict
    service_context: dict
    namespace_context: dict
    cluster_context: dict
    topology: dict
    timeline: list[dict]
    telemetry_coverage: dict
    deployment_correlation: dict


class TelemetryReader:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.client = None

    def close(self) -> None:
        if self.client is not None:
            self.client.close()
            self.client = None

    def _client(self):
        if self.client is None:
            self.client = clickhouse_connect.get_client(
                host=self.settings.clickhouse_host,
                port=self.settings.clickhouse_http_port,
                username=self.settings.clickhouse_username,
                password=self.settings.clickhouse_password,
                database=self.settings.clickhouse_database,
            )
        return self.client

    def fetch_context(self, incident: dict) -> TelemetryContext:
        try:
            client = self._client()
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "telemetry client initialization failed for incident=%s service=%s namespace=%s cluster=%s: %s",
                incident.get("incident_id", ""),
                incident.get("service", ""),
                incident.get("namespace", ""),
                incident.get("cluster", ""),
                exc,
            )
            return self._empty_context(incident, ["telemetry client unavailable", "topology unavailable"])
        incident_time = incident["timestamp"]
        if incident_time.tzinfo is None:
            incident_time = incident_time.replace(tzinfo=timezone.utc)
        incident_time = incident_time.astimezone(timezone.utc)
        end = incident_time + timedelta(minutes=5)
        start = incident_time - timedelta(minutes=30)
        service = self._canonicalize_name(incident["service"]).replace("'", "''")
        namespace = incident["namespace"].replace("'", "''")
        cluster = incident["cluster"].replace("'", "''")
        warnings: list[str] = []

        trace_summary = self._safe_context_fetch(
            "trace summary",
            incident,
            lambda: self._fetch_trace_summary(client, service, namespace, cluster, start, end),
            (),
            warnings,
        )

        logs_summary = self._safe_context_fetch(
            "logs summary",
            incident,
            lambda: self._fetch_logs_summary(client, service, namespace, cluster, start, end),
            (),
            warnings,
        )

        metrics_rows = self._safe_context_fetch(
            "metrics summary",
            incident,
            lambda: client.query(
                f"""
                SELECT
                    ts.metric_name,
                    argMax(samples.value, samples.unix_milli) AS latest_value,
                    max(samples.unix_milli) AS latest_unix_milli
                FROM {SAMPLES_TABLE} AS samples
                INNER JOIN {METRICS_TABLE} AS ts USING fingerprint
                WHERE samples.unix_milli >= {int(start.timestamp() * 1000)}
                  AND samples.unix_milli < {int(end.timestamp() * 1000)}
                  AND {self._metric_service_expr('ts')} = '{service}'
                  AND {self._eq_or_any("ts.resource_attrs['k8s.namespace.name']", namespace)}
                  AND {self._eq_or_any("ts.resource_attrs['k8s.cluster.name']", cluster)}
                  AND (
                    positionCaseInsensitive(ts.metric_name, 'cpu') > 0 OR
                    positionCaseInsensitive(ts.metric_name, 'memory') > 0 OR
                    positionCaseInsensitive(ts.metric_name, 'latency') > 0 OR
                    positionCaseInsensitive(ts.metric_name, 'error') > 0 OR
                    positionCaseInsensitive(ts.metric_name, 'request') > 0 OR
                    positionCaseInsensitive(ts.metric_name, 'messag') > 0 OR
                    positionCaseInsensitive(ts.metric_name, 'queue') > 0 OR
                    positionCaseInsensitive(ts.metric_name, 'topic') > 0 OR
                    positionCaseInsensitive(ts.metric_name, 'db') > 0 OR
                    positionCaseInsensitive(ts.metric_name, 'database') > 0 OR
                    positionCaseInsensitive(ts.metric_name, 'jvm') > 0
                  )
                GROUP BY ts.metric_name
                LIMIT 40
                """
            ).result_rows,
            [],
            warnings,
        )
        db_summary = self._safe_context_fetch(
            "database evidence",
            incident,
            lambda: self._fetch_database_evidence(client, service, namespace, cluster, start, end),
            {"dependencies": [], "systems": [], "total_calls": 0, "query_examples": []},
            warnings,
        )
        messaging_summary = self._safe_context_fetch(
            "messaging evidence",
            incident,
            lambda: self._fetch_messaging_evidence(client, service, namespace, cluster, start, end),
            {"flows": [], "systems": [], "destinations": [], "total_calls": 0},
            warnings,
        )
        exception_summary = self._safe_context_fetch(
            "exception evidence",
            incident,
            lambda: self._fetch_exception_evidence(client, service, namespace, cluster, start, end),
            {"exception_count": 0, "error_span_count": 0, "examples": [], "types": []},
            warnings,
        )
        infra_summary = self._safe_context_fetch(
            "infrastructure evidence",
            incident,
            lambda: self._fetch_infra_evidence(client, service, namespace, cluster, start, end),
            {"pods": [], "containers": [], "nodes": [], "hosts": [], "environments": []},
            warnings,
        )

        topology = self._safe_context_fetch(
            "topology",
            incident,
            lambda: self._fetch_topology(client, service, namespace, cluster, start, end),
            {"nodes": [], "edges": []},
            warnings,
        )
        timeline = self._safe_context_fetch(
            "timeline",
            incident,
            lambda: self._fetch_timeline(client, service, namespace, cluster, incident_time),
            [],
            warnings,
        )
        deployment_correlation = self._safe_context_fetch(
            "deployments",
            incident,
            lambda: self._fetch_deployments(client, service, namespace, cluster, incident_time),
            {"events": []},
            warnings,
        )
        telemetry_coverage = self._build_coverage(
            service,
            metrics_rows,
            trace_summary,
            logs_summary,
            db_summary,
            messaging_summary,
            exception_summary,
            infra_summary,
            topology,
            warnings,
        )

        return TelemetryContext(
            metrics_summary={
                "highlights": {name: value for name, value, _observed_at in metrics_rows},
                "detector_snapshot": incident["telemetry_snapshot"],
            },
            logs_summary={
                "log_count": logs_summary[0] if logs_summary else 0,
                "context_log_count": logs_summary[1] if logs_summary else 0,
                "examples": self._normalize_array(logs_summary[2]) if logs_summary else [],
            },
            trace_summary={
                "request_count": trace_summary[0] if trace_summary else 0,
                "avg_latency_ms": trace_summary[1] if trace_summary else 0,
                "p95_latency_ms": trace_summary[2] if trace_summary else 0,
                "error_rate": trace_summary[3] if trace_summary else 0,
            },
            db_summary=db_summary,
            messaging_summary=messaging_summary,
            exception_summary=exception_summary,
            infra_summary=infra_summary,
            service_context={
                "service": incident["service"],
                "detector_signals": incident["detector_signals"],
                "incident_severity": incident["severity"],
                "anomaly_score": incident["anomaly_score"],
            },
            namespace_context={"namespace": incident["namespace"]},
            cluster_context={"cluster": incident["cluster"]},
            topology=topology,
            timeline=timeline,
            telemetry_coverage=telemetry_coverage,
            deployment_correlation=deployment_correlation,
        )

    def _empty_context(self, incident: dict, warnings: list[str]) -> TelemetryContext:
        service = incident.get("service", "")
        coverage = self._build_coverage(
            service,
            [],
            (),
            (),
            {"dependencies": [], "systems": [], "total_calls": 0, "query_examples": []},
            {"flows": [], "systems": [], "destinations": [], "total_calls": 0},
            {"exception_count": 0, "error_span_count": 0, "examples": [], "types": []},
            {"pods": [], "containers": [], "nodes": [], "hosts": [], "environments": []},
            {"nodes": [], "edges": []},
            warnings,
        )
        return TelemetryContext(
            metrics_summary={
                "highlights": {},
                "detector_snapshot": incident.get("telemetry_snapshot", {}),
            },
            logs_summary={
                "log_count": 0,
                "context_log_count": 0,
                "examples": [],
            },
            trace_summary={
                "request_count": 0,
                "avg_latency_ms": 0,
                "p95_latency_ms": 0,
                "error_rate": 0,
            },
            db_summary={"dependencies": [], "systems": [], "total_calls": 0, "query_examples": []},
            messaging_summary={"flows": [], "systems": [], "destinations": [], "total_calls": 0},
            exception_summary={"exception_count": 0, "error_span_count": 0, "examples": [], "types": []},
            infra_summary={"pods": [], "containers": [], "nodes": [], "hosts": [], "environments": []},
            service_context={
                "service": service,
                "detector_signals": incident.get("detector_signals", []),
                "incident_severity": incident.get("severity", ""),
                "anomaly_score": incident.get("anomaly_score", 0),
            },
            namespace_context={"namespace": incident.get("namespace", "")},
            cluster_context={"cluster": incident.get("cluster", "")},
            topology={"nodes": [], "edges": []},
            timeline=[],
            telemetry_coverage=coverage,
            deployment_correlation={"events": []},
        )

    def _safe_context_fetch(self, section: str, incident: dict, operation, default, warnings: list[str]):
        try:
            return operation()
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "telemetry %s fetch failed for incident=%s service=%s namespace=%s cluster=%s: %s",
                section,
                incident.get("incident_id", ""),
                incident.get("service", ""),
                incident.get("namespace", ""),
                incident.get("cluster", ""),
                exc,
            )
            warnings.append(f"{section} unavailable")
            return default

    def detect_predictive_anomalies(self) -> list[dict]:
        try:
            client = self._client()
        except Exception as exc:  # noqa: BLE001
            logger.warning("predictive anomaly detection unavailable: %s", exc)
            return []
        rows = client.query(
            f"""
            SELECT
                {self._trace_service_expr()} AS service,
                ifNull(nullIf(resources_string['k8s.namespace.name'], ''), '') AS namespace,
                ifNull(nullIf(resources_string['k8s.cluster.name'], ''), '') AS cluster,
                toStartOfMinute(timestamp) AS bucket,
                avg(durationNano) / 1000000 AS avg_latency_ms,
                avg(toFloat64(hasError)) AS error_rate
            FROM {TRACES_TABLE}
            WHERE timestamp >= now() - INTERVAL 45 MINUTE
              AND {self._trace_service_expr()} != ''
              AND {self._trace_noise_filter()}
              AND {self._eq_or_any("resources_string['k8s.cluster.name']", self.settings.cluster_id)}
              AND {self._eq_or_any("resources_string['k8s.namespace.name']", self.settings.namespace_filter)}
              AND {self._eq_or_any(self._trace_service_expr(), self._canonicalize_name(self.settings.service_filter))}
            GROUP BY service, namespace, cluster, bucket
            ORDER BY service, bucket
            """
        ).result_rows
        by_service: dict[tuple[str, str, str], dict[str, list[float]]] = {}
        for service, namespace, cluster, _bucket, latency, error_rate in rows:
            key = (service, namespace, cluster)
            if key not in by_service:
                by_service[key] = {"latency": [], "error": []}
            by_service[key]["latency"].append(float(latency or 0.0))
            by_service[key]["error"].append(float(error_rate or 0.0))

        predictions: list[dict] = []
        for (service, namespace, cluster), series in by_service.items():
            if len(series["latency"]) < 8:
                continue
            predicted_latency = self._forecast(series["latency"])
            predicted_error = self._forecast(series["error"])
            baseline_latency = mean(series["latency"][:-3]) if len(series["latency"]) > 3 else mean(series["latency"])
            baseline_error = mean(series["error"][:-3]) if len(series["error"]) > 3 else mean(series["error"])

            signals: list[str] = []
            if predicted_latency >= 80 or (baseline_latency > 0 and predicted_latency >= baseline_latency * 1.5):
                signals.append("predictive_latency_risk")
            if predicted_error >= 0.05 or (baseline_error > 0 and predicted_error >= baseline_error * 2):
                signals.append("predictive_error_rate_risk")
            if not signals:
                continue

            score = min(95.0, max(25.0, (predicted_latency / max(1.0, baseline_latency + 1)) * 15 + predicted_error * 100))
            confidence = min(0.95, 0.55 + (len(series["latency"]) / 60.0))
            severity = "high" if score >= 60 else "medium"
            predictions.append(
                {
                    "cluster": cluster,
                    "namespace": namespace,
                    "service": service,
                    "problem_id": f"{cluster}:{namespace}:predictive",
                    "signals": signals,
                    "predicted_latency_ms": round(predicted_latency, 2),
                    "predicted_error_rate": round(predicted_error, 4),
                    "recent_latency_series": [round(item, 3) for item in series["latency"][-12:]],
                    "recent_error_series": [round(item, 6) for item in series["error"][-12:]],
                    "anomaly_score": round(score, 2),
                    "confidence": round(confidence, 2),
                    "severity": severity,
                    "horizon_minutes": 10,
                }
            )
        return predictions

    def _fetch_trace_summary(self, client, service: str, namespace: str, cluster: str, start: datetime, end: datetime):
        canonical = client.query(
            f"""
            SELECT
                count() AS request_count,
                avg(durationNano) / 1000000 AS avg_latency_ms,
                quantile(0.95)(durationNano) / 1000000 AS p95_latency_ms,
                avg(toFloat64(hasError)) AS error_rate
            FROM {TRACES_TABLE}
            WHERE {self._trace_scope_clause(start, end, service, namespace, cluster, use_resource_scope=True)}
            """
        ).first_row
        if canonical and int(canonical[0] or 0) > 0:
            return canonical
        return client.query(
            f"""
            SELECT
                count() AS request_count,
                avg(durationNano) / 1000000 AS avg_latency_ms,
                quantile(0.95)(durationNano) / 1000000 AS p95_latency_ms,
                avg(toFloat64(hasError)) AS error_rate
            FROM {TRACES_TABLE}
            WHERE {self._trace_scope_clause(start, end, service, namespace, cluster, use_resource_scope=False)}
            """
        ).first_row

    def _fetch_logs_summary(self, client, service: str, namespace: str, cluster: str, start: datetime, end: datetime):
        signal_filter = self._log_signal_filter()
        canonical = client.query(
            f"""
            SELECT
                count() AS log_count,
                countIf(trace_id != '' AND span_id != '') AS context_log_count,
                groupArray(8)(substring(toString(body), 1, 240)) AS examples
            FROM {LOGS_TABLE}
            WHERE {self._log_scope_clause(start, end, service, namespace, cluster, use_resource_scope=True)}
              AND ({signal_filter})
            """
        ).first_row
        if canonical and int(canonical[0] or 0) > 0:
            return canonical
        return client.query(
            f"""
            SELECT
                count() AS log_count,
                countIf(trace_id != '' AND span_id != '') AS context_log_count,
                groupArray(8)(substring(toString(body), 1, 240)) AS examples
            FROM {LOGS_TABLE}
            WHERE {self._log_scope_clause(start, end, service, namespace, cluster, use_resource_scope=False)}
              AND ({signal_filter})
            """
        ).first_row

    def _fetch_database_evidence(self, client, service: str, namespace: str, cluster: str, start: datetime, end: datetime) -> dict:
        rows = client.query(
            f"""
            SELECT
                lowerUTF8(coalesce(nullIf(attributes_string['db.system'], ''), 'database')) AS db_system,
                lowerUTF8(coalesce(
                    nullIf(attributes_string['db.name'], ''),
                    nullIf(attributes_string['db.namespace'], ''),
                    nullIf(attributes_string['server.address'], ''),
                    nullIf(attributes_string['net.peer.name'], ''),
                    'database'
                )) AS db_name,
                count() AS calls,
                avg(durationNano) / 1000000 AS avg_latency_ms,
                avg(toFloat64(hasError)) AS error_rate,
                groupArray(3)(substring(toString(attributes_string['db.statement']), 1, 180)) AS examples
            FROM {TRACES_TABLE}
            WHERE {self._trace_scope_clause(start, end, service, namespace, cluster, use_resource_scope=True)}
              AND attributes_string['db.system'] != ''
            GROUP BY db_system, db_name
            ORDER BY calls DESC
            LIMIT 10
            """
        ).result_rows
        dependencies = []
        systems: set[str] = set()
        total_calls = 0
        examples: list[str] = []
        for db_system, db_name, calls, avg_latency_ms, error_rate, sample_queries in rows:
            systems.add(str(db_system))
            total_calls += int(calls or 0)
            examples.extend([item for item in self._normalize_array(sample_queries) if item])
            dependencies.append(
                {
                    "node_id": self._canonical_database_node(str(db_system), str(db_name)),
                    "system": str(db_system),
                    "name": str(db_name),
                    "call_count": int(calls or 0),
                    "avg_latency_ms": round(float(avg_latency_ms or 0), 3),
                    "error_rate": round(float(error_rate or 0), 6),
                }
            )
        return {
            "dependencies": dependencies,
            "systems": sorted(systems),
            "total_calls": total_calls,
            "query_examples": examples[:5],
        }

    def _fetch_messaging_evidence(self, client, service: str, namespace: str, cluster: str, start: datetime, end: datetime) -> dict:
        rows = client.query(
            f"""
            SELECT
                lowerUTF8(attributes_string['messaging.system']) AS messaging_system,
                coalesce(
                    nullIf(attributes_string['messaging.destination.name'], ''),
                    nullIf(attributes_string['messaging.destination'], ''),
                    nullIf(attributes_string['messaging.destination_name'], '')
                ) AS destination,
                lowerUTF8(coalesce(attributes_string['messaging.operation'], attributes_string['messaging.operation.type'], '')) AS operation,
                coalesce(nullIf(attributes_string['messaging.kafka.consumer.group'], ''), '') AS consumer_group,
                count() AS calls,
                avg(durationNano) / 1000000 AS avg_latency_ms,
                avg(toFloat64(hasError)) AS error_rate
            FROM {TRACES_TABLE}
            WHERE {self._trace_scope_clause(start, end, service, namespace, cluster, use_resource_scope=True)}
              AND attributes_string['messaging.system'] != ''
              AND coalesce(
                    nullIf(attributes_string['messaging.destination.name'], ''),
                    nullIf(attributes_string['messaging.destination'], ''),
                    nullIf(attributes_string['messaging.destination_name'], '')
                  ) != ''
            GROUP BY messaging_system, destination, operation, consumer_group
            ORDER BY calls DESC
            LIMIT 20
            """
        ).result_rows
        flows = []
        systems: set[str] = set()
        destinations: set[str] = set()
        total_calls = 0
        for messaging_system, destination, operation, consumer_group, calls, avg_latency_ms, error_rate in rows:
            systems.add(str(messaging_system))
            destinations.add(str(destination))
            total_calls += int(calls or 0)
            flows.append(
                {
                    "node_id": self._canonical_messaging_node(str(messaging_system), str(destination)),
                    "system": str(messaging_system),
                    "destination": str(destination),
                    "operation": str(operation),
                    "consumer_group": str(consumer_group),
                    "call_count": int(calls or 0),
                    "avg_latency_ms": round(float(avg_latency_ms or 0), 3),
                    "error_rate": round(float(error_rate or 0), 6),
                }
            )
        return {
            "flows": flows,
            "systems": sorted(systems),
            "destinations": sorted(destinations),
            "total_calls": total_calls,
        }

    def _fetch_exception_evidence(self, client, service: str, namespace: str, cluster: str, start: datetime, end: datetime) -> dict:
        log_rows = client.query(
            f"""
            SELECT
                count() AS exception_count,
                groupArray(6)(substring(toString(body), 1, 240)) AS examples,
                groupUniqArray(6)(coalesce(
                    nullIf(attributes_string['exception.type'], ''),
                    nullIf(attributes_string['exception_type'], ''),
                    nullIf(attributes_string['error.type'], ''),
                    nullIf(attributes_string['error_type'], '')
                )) AS exception_types
            FROM {LOGS_TABLE}
            WHERE {self._log_scope_clause(start, end, service, namespace, cluster, use_resource_scope=True)}
              AND (
                positionCaseInsensitive(body, 'exception') > 0 OR
                positionCaseInsensitive(body, 'stacktrace') > 0 OR
                positionCaseInsensitive(body, 'traceback') > 0 OR
                attributes_string['exception.type'] != '' OR
                attributes_string['exception_type'] != '' OR
                attributes_string['error.type'] != '' OR
                attributes_string['error_type'] != ''
              )
            """
        ).first_row
        trace_rows = client.query(
            f"""
            SELECT count()
            FROM {TRACES_TABLE}
            WHERE {self._trace_scope_clause(start, end, service, namespace, cluster, use_resource_scope=True)}
              AND (
                hasError = 1 OR
                attributes_string['exception.type'] != '' OR
                attributes_string['error.type'] != ''
              )
            """
        ).first_row
        return {
            "exception_count": int(log_rows[0] or 0) if log_rows else 0,
            "error_span_count": int(trace_rows[0] or 0) if trace_rows else 0,
            "examples": [item for item in self._normalize_array(log_rows[1]) if item] if log_rows else [],
            "types": [item for item in self._normalize_array(log_rows[2]) if item] if log_rows else [],
        }

    def _fetch_infra_evidence(self, client, service: str, namespace: str, cluster: str, start: datetime, end: datetime) -> dict:
        trace_rows = client.query(
            f"""
            SELECT
                groupUniqArray(6)(nullIf(resources_string['k8s.pod.name'], '')) AS pods,
                groupUniqArray(6)(coalesce(nullIf(resources_string['k8s.container.name'], ''), nullIf(resources_string['container.name'], ''))) AS containers,
                groupUniqArray(6)(nullIf(resources_string['k8s.node.name'], '')) AS nodes,
                groupUniqArray(6)(coalesce(nullIf(resources_string['host.name'], ''), nullIf(resources_string['host.id'], ''))) AS hosts,
                groupUniqArray(4)(nullIf(resources_string['deployment.environment'], '')) AS environments
            FROM {TRACES_TABLE}
            WHERE {self._trace_scope_clause(start, end, service, namespace, cluster, use_resource_scope=True)}
            """
        ).first_row
        if trace_rows and any(self._normalize_array(value) for value in trace_rows):
            return {
                "pods": [item for item in self._normalize_array(trace_rows[0]) if item],
                "containers": [item for item in self._normalize_array(trace_rows[1]) if item],
                "nodes": [item for item in self._normalize_array(trace_rows[2]) if item],
                "hosts": [item for item in self._normalize_array(trace_rows[3]) if item],
                "environments": [item for item in self._normalize_array(trace_rows[4]) if item],
            }
        metric_rows = client.query(
            f"""
            SELECT
                groupUniqArray(6)(nullIf(ts.resource_attrs['k8s.pod.name'], '')) AS pods,
                groupUniqArray(6)(coalesce(nullIf(ts.resource_attrs['k8s.container.name'], ''), nullIf(ts.resource_attrs['container.name'], ''))) AS containers,
                groupUniqArray(6)(nullIf(ts.resource_attrs['k8s.node.name'], '')) AS nodes,
                groupUniqArray(6)(coalesce(nullIf(ts.resource_attrs['host.name'], ''), nullIf(ts.resource_attrs['host.id'], ''))) AS hosts,
                groupUniqArray(4)(nullIf(ts.resource_attrs['deployment.environment'], '')) AS environments
            FROM {SAMPLES_TABLE} AS samples
            INNER JOIN {METRICS_TABLE} AS ts USING fingerprint
            WHERE samples.unix_milli >= {int(start.timestamp() * 1000)}
              AND samples.unix_milli < {int(end.timestamp() * 1000)}
              AND {self._metric_service_expr('ts')} = '{service}'
              AND {self._eq_or_any("ts.resource_attrs['k8s.namespace.name']", namespace)}
              AND {self._eq_or_any("ts.resource_attrs['k8s.cluster.name']", cluster)}
            """
        ).first_row
        return {
            "pods": [item for item in self._normalize_array(metric_rows[0]) if item] if metric_rows else [],
            "containers": [item for item in self._normalize_array(metric_rows[1]) if item] if metric_rows else [],
            "nodes": [item for item in self._normalize_array(metric_rows[2]) if item] if metric_rows else [],
            "hosts": [item for item in self._normalize_array(metric_rows[3]) if item] if metric_rows else [],
            "environments": [item for item in self._normalize_array(metric_rows[4]) if item] if metric_rows else [],
        }

    def _fetch_topology(self, client, service: str, namespace: str, cluster: str, start: datetime, end: datetime) -> dict:
        rows = client.query(
            f"""
            SELECT
                parent.source_service AS source,
                child.target_service AS target,
                count() AS calls
            FROM (
                SELECT
                    trace_id,
                    parent_span_id,
                    {self._trace_service_expr()} AS target_service
                FROM {TRACES_TABLE}
                WHERE {self._trace_scope_clause(start, end, "", namespace, cluster, use_resource_scope=True)}
            ) AS child
            INNER JOIN (
                SELECT
                    trace_id,
                    span_id,
                    {self._trace_service_expr()} AS source_service
                FROM {TRACES_TABLE}
                WHERE {self._trace_scope_clause(start, end, "", namespace, cluster, use_resource_scope=True)}
            ) AS parent
                ON child.trace_id = parent.trace_id
                AND child.parent_span_id = parent.span_id
            WHERE child.target_service != ''
              AND parent.source_service != ''
              AND child.target_service != parent.source_service
            GROUP BY source, target
            ORDER BY calls DESC
            LIMIT 30
            """
        ).result_rows
        messaging_rows = client.query(
            f"""
            WITH publish AS (
                SELECT
                    {self._trace_service_expr()} AS source,
                    lowerUTF8(attributes_string['messaging.system']) AS messaging_system,
                    coalesce(
                      nullIf(attributes_string['messaging.destination.name'], ''),
                      nullIf(attributes_string['messaging.destination'], ''),
                      nullIf(attributes_string['messaging.destination_name'], '')
                    ) AS destination,
                    count() AS publish_count
                FROM {TRACES_TABLE}
                WHERE {self._trace_scope_clause(start, end, "", namespace, cluster, use_resource_scope=True)}
                  AND attributes_string['messaging.system'] != ''
                  AND coalesce(nullIf(attributes_string['messaging.destination.name'], ''), nullIf(attributes_string['messaging.destination'], ''), nullIf(attributes_string['messaging.destination_name'], '')) != ''
                  AND lowerUTF8(coalesce(attributes_string['messaging.operation'], attributes_string['messaging.operation.type'], '')) IN ('publish', 'send')
                GROUP BY source, messaging_system, destination
            ),
            consume AS (
                SELECT
                    {self._trace_service_expr()} AS target,
                    lowerUTF8(attributes_string['messaging.system']) AS messaging_system,
                    coalesce(
                      nullIf(attributes_string['messaging.destination.name'], ''),
                      nullIf(attributes_string['messaging.destination'], ''),
                      nullIf(attributes_string['messaging.destination_name'], '')
                    ) AS destination,
                    count() AS process_count
                FROM {TRACES_TABLE}
                WHERE {self._trace_scope_clause(start, end, "", namespace, cluster, use_resource_scope=True)}
                  AND attributes_string['messaging.system'] != ''
                  AND coalesce(nullIf(attributes_string['messaging.destination.name'], ''), nullIf(attributes_string['messaging.destination'], ''), nullIf(attributes_string['messaging.destination_name'], '')) != ''
                  AND lowerUTF8(coalesce(attributes_string['messaging.operation'], attributes_string['messaging.operation.type'], '')) IN ('process', 'receive')
                GROUP BY target, messaging_system, destination
            )
            SELECT publish.source, publish.messaging_system, publish.destination, consume.target, least(publish.publish_count, consume.process_count) AS calls
            FROM publish
            INNER JOIN consume ON publish.destination = consume.destination AND publish.messaging_system = consume.messaging_system
            WHERE publish.source != ''
            ORDER BY calls DESC
            LIMIT 30
            """
        ).result_rows
        db_rows = client.query(
            f"""
            SELECT
                {self._trace_service_expr()} AS source,
                lowerUTF8(coalesce(nullIf(attributes_string['db.system'], ''), 'database')) AS db_system,
                lowerUTF8(coalesce(nullIf(attributes_string['db.name'], ''), nullIf(attributes_string['db.namespace'], ''), nullIf(attributes_string['server.address'], ''), 'database')) AS db_name,
                count() AS calls
            FROM {TRACES_TABLE}
            WHERE {self._trace_scope_clause(start, end, "", namespace, cluster, use_resource_scope=True)}
              AND attributes_string['db.system'] != ''
            GROUP BY source, db_system, db_name
            ORDER BY calls DESC
            LIMIT 30
            """
        ).result_rows
        nodes = sorted(
            {
                service,
                *(source for source, _, _ in rows),
                *(target for _, target, _ in rows),
                *(source for source, _system, _destination, _consumer, _calls in messaging_rows),
                *(self._canonical_messaging_node(system, destination) for _source, system, destination, _consumer, _calls in messaging_rows),
                *(consumer for _source, _system, _destination, consumer, _calls in messaging_rows),
                *(source for source, _system, _name, _calls in db_rows),
                *(self._canonical_database_node(system, name) for _source, system, name, _calls in db_rows),
            }
        )
        return {
            "nodes": [{"id": node, "label": node} for node in nodes],
            "edges": [
                {"source": source, "target": target, "call_count": calls, "dependency_type": "trace_http"}
                for source, target, calls in rows
            ]
            + [
                {
                    "source": source,
                    "target": self._canonical_messaging_node(system, destination),
                    "call_count": calls,
                    "dependency_type": "messaging",
                    "destination": destination,
                }
                for source, system, destination, _consumer, calls in messaging_rows
            ]
            + [
                {
                    "source": self._canonical_messaging_node(system, destination),
                    "target": consumer,
                    "call_count": calls,
                    "dependency_type": "messaging",
                    "destination": destination,
                }
                for _source, system, destination, consumer, calls in messaging_rows
                if consumer
            ]
            + [
                {
                    "source": source,
                    "target": self._canonical_database_node(db_system, db_name),
                    "call_count": calls,
                    "dependency_type": "database",
                }
                for source, db_system, db_name, calls in db_rows
            ],
        }

    def _fetch_timeline(self, client, service: str, namespace: str, cluster: str, center: datetime) -> list[dict]:
        start = center - timedelta(minutes=5)
        end = center + timedelta(minutes=5)
        timeline: list[dict] = []

        trace_rows = client.query(
            f"""
            SELECT timestamp, {self._trace_service_expr()} AS service, name, durationNano / 1000000 AS duration_ms, hasError
            FROM {TRACES_TABLE}
            WHERE {self._trace_scope_clause(start, end, service, namespace, cluster, use_resource_scope=True)}
            ORDER BY duration_ms DESC
            LIMIT 10
            """
        ).result_rows
        for ts, svc, name, duration_ms, has_error in trace_rows:
            timeline.append(
                {
                    "timestamp": ts.isoformat(),
                    "kind": "trace",
                    "entity": svc,
                    "title": name,
                    "details": f"Span latency {duration_ms:.2f} ms",
                    "severity": "high" if has_error else "info",
                    "value": float(duration_ms),
                }
            )

        log_rows = client.query(
            f"""
            SELECT timestamp, {self._log_service_expr()} AS service, substring(toString(body), 1, 240), severity_number
            FROM {LOGS_TABLE}
            WHERE {self._log_scope_clause(start, end, service, namespace, cluster, use_resource_scope=True)}
            ORDER BY timestamp DESC
            LIMIT 12
            """
        ).result_rows
        for ts, svc, body, severity_number in log_rows:
            timeline.append(
                {
                    "timestamp": datetime.fromtimestamp(ts / 1_000_000_000, tz=timezone.utc).isoformat(),
                    "kind": "log",
                    "entity": svc,
                    "title": "Log event",
                    "details": body,
                    "severity": "high" if severity_number >= 17 else "medium" if severity_number >= 13 else "info",
                    "value": float(severity_number),
                }
            )

        metric_rows = client.query(
            f"""
            SELECT toDateTime(samples.unix_milli / 1000) AS bucket, count() AS datapoints
            FROM {SAMPLES_TABLE} AS samples
            INNER JOIN {METRICS_TABLE} AS ts USING fingerprint
            WHERE samples.unix_milli >= {int(start.timestamp() * 1000)}
              AND samples.unix_milli < {int(end.timestamp() * 1000)}
              AND {self._metric_service_expr('ts')} = '{service}'
              AND {self._eq_or_any("ts.resource_attrs['k8s.namespace.name']", namespace)}
              AND {self._eq_or_any("ts.resource_attrs['k8s.cluster.name']", cluster)}
            GROUP BY bucket
            ORDER BY bucket
            LIMIT 20
            """
        ).result_rows
        for bucket, datapoints in metric_rows:
            timeline.append(
                {
                    "timestamp": bucket.replace(tzinfo=timezone.utc).isoformat(),
                    "kind": "metric",
                    "entity": service,
                    "title": "Metric activity",
                    "details": f"{datapoints} datapoints collected",
                    "severity": "info",
                    "value": float(datapoints),
                }
            )

        timeline.sort(key=lambda item: item["timestamp"])
        return timeline

    def _fetch_deployments(self, client, service: str, namespace: str, cluster: str, center: datetime) -> dict:
        start = center - timedelta(minutes=10)
        end = center + timedelta(minutes=10)
        rows = client.query(
            f"""
            SELECT
                timestamp,
                {self._log_service_expr()} AS service,
                substring(toString(body), 1, 240) AS body
            FROM {LOGS_TABLE}
            WHERE {self._log_scope_clause(start, end, service, namespace, cluster, use_resource_scope=True)}
              AND (
                positionCaseInsensitive(body, 'deploy') > 0 OR
                positionCaseInsensitive(body, 'rollout') > 0 OR
                positionCaseInsensitive(body, 'image') > 0 OR
                positionCaseInsensitive(body, 'scaled') > 0
              )
            ORDER BY timestamp DESC
            LIMIT 5
            """
        ).result_rows
        events = [
                {
                    "timestamp": datetime.fromtimestamp(ts / 1_000_000_000, tz=timezone.utc).isoformat(),
                    "service": service,
                    "details": body,
                }
                for ts, service, body in rows
            ]
        events.sort(key=lambda item: item.get("timestamp", ""), reverse=True)
        return {"events": events[:10]}

    def _build_coverage(self, service: str, metrics_rows, trace_summary, logs_summary, db_summary: dict, messaging_summary: dict, exception_summary: dict, infra_summary: dict, topology: dict, warnings: list[str]) -> dict:
        missing_signals: list[str] = []
        metrics_count = len(metrics_rows)
        tracing_count = int(trace_summary[0] or 0) if trace_summary else 0
        log_count = int(logs_summary[0] or 0) if logs_summary else 0
        context_log_count = int(logs_summary[1] or 0) if logs_summary else 0
        logs_structured = context_log_count > 0
        metric_values = [float(value or 0) for _name, value, _observed_at in metrics_rows]
        db_calls = int(db_summary.get("total_calls", 0) or 0)
        messaging_calls = int(messaging_summary.get("total_calls", 0) or 0)
        exception_count = int(exception_summary.get("exception_count", 0) or 0) + int(exception_summary.get("error_span_count", 0) or 0)
        infra_entities = sum(len(infra_summary.get(key, []) or []) for key in ("pods", "containers", "nodes", "hosts"))
        quality_by_signal = {
            "traces": self._quality_state(tracing_count, tracing_count == 0, False),
            "logs": self._quality_state(log_count, log_count == 0, False),
            "metrics": self._quality_state(metrics_count, all(value == 0 for value in metric_values) if metric_values else False, False),
            "database": self._quality_state(db_calls, db_calls == 0, False),
            "messaging": self._quality_state(messaging_calls, messaging_calls == 0, False),
            "exceptions": self._quality_state(exception_count, exception_count == 0, False),
            "infra": self._quality_state(infra_entities, infra_entities == 0, False),
            "topology": "present" if topology["edges"] else "missing",
        }

        if tracing_count == 0:
            missing_signals.append(f"No distributed tracing for {service}")
        if metrics_count == 0:
            missing_signals.append(f"No service-level metrics available for {service}")
        elif quality_by_signal["metrics"] == "zero":
            missing_signals.append(f"Metrics are present for {service}, but current values are zero across the incident window")
        if not logs_structured:
            missing_signals.append(f"Logs missing structured fields for {service}")
        if db_calls == 0:
            missing_signals.append(f"No database spans detected for {service} in the incident window")
        if messaging_calls == 0:
            missing_signals.append(f"No messaging spans detected for {service} in the incident window")
        if exception_count == 0:
            missing_signals.append(f"No exception evidence captured for {service} in the incident window")
        if infra_entities == 0:
            missing_signals.append(f"No runtime host/container evidence correlated for {service}")
        if "topology unavailable" in warnings:
            missing_signals.append(f"Dependency topology unavailable for {service}")
        for warning in warnings:
            if warning == "topology unavailable":
                continue
            missing_signals.append(warning)

        metrics_score = 100 if metrics_count > 0 else 30
        tracing_score = 100 if tracing_count > 0 else 20
        logs_score = 100 if logs_structured else 45 if log_count > 0 else 20
        correlation_score = 100 if topology["edges"] else 55
        runtime_score = 100 if infra_entities > 0 else 45
        dependency_score = 100 if db_calls > 0 or messaging_calls > 0 else 40
        observability_score = round((metrics_score + tracing_score + logs_score + correlation_score + runtime_score + dependency_score) / 6, 2)

        return {
            "observability_score": f"{observability_score}",
            "metrics_coverage": "good" if metrics_count > 0 else "poor",
            "tracing_coverage": "good" if tracing_count > 0 else "partial",
            "logs_structure": "good" if logs_structured else "poor",
            "alert_correlation": "good" if topology["edges"] else "partial",
            "database_coverage": quality_by_signal["database"],
            "messaging_coverage": quality_by_signal["messaging"],
            "exception_coverage": quality_by_signal["exceptions"],
            "infra_coverage": quality_by_signal["infra"],
            "missing_signals": missing_signals,
            "quality_by_signal": json.dumps(quality_by_signal),
        }

    def _trace_scope_clause(
        self,
        start: datetime,
        end: datetime,
        service: str,
        namespace: str,
        cluster: str,
        *,
        use_resource_scope: bool,
    ) -> str:
        parts = [
            f"timestamp >= toDateTime64({int(start.timestamp() * 1000)} / 1000.0, 3)",
            f"timestamp < toDateTime64({int(end.timestamp() * 1000)} / 1000.0, 3)",
            self._trace_noise_filter(),
        ]
        if service:
            parts.append(f"{self._trace_service_expr()} = '{service}'")
        if not use_resource_scope:
            parts.append(self._eq_or_any("resources_string['k8s.namespace.name']", namespace))
            parts.append(self._eq_or_any("resources_string['k8s.cluster.name']", cluster))
        else:
            resource_filter = self._trace_resource_filter(start, end, service, namespace, cluster)
            if resource_filter:
                parts.append(resource_filter)
        return " AND ".join(parts)

    def _log_scope_clause(
        self,
        start: datetime,
        end: datetime,
        service: str,
        namespace: str,
        cluster: str,
        *,
        use_resource_scope: bool,
    ) -> str:
        parts = [
            f"timestamp >= {int(start.timestamp() * 1_000_000_000)}",
            f"timestamp < {int(end.timestamp() * 1_000_000_000)}",
        ]
        if service:
            parts.append(f"{self._log_service_expr()} = '{service}'")
        if not use_resource_scope:
            parts.append(self._eq_or_any("resources_string['k8s.namespace.name']", namespace))
            parts.append(self._eq_or_any("resources_string['k8s.cluster.name']", cluster))
        else:
            resource_filter = self._log_resource_filter(start, end, service, namespace, cluster)
            if resource_filter:
                parts.append(resource_filter)
        return " AND ".join(parts)

    def _trace_resource_filter(self, start: datetime, end: datetime, service: str, namespace: str, cluster: str) -> str:
        subquery = self._resource_subquery(TRACE_RESOURCES_TABLE, start, end, service, namespace, cluster)
        if not subquery:
            return ""
        return f"resource_fingerprint GLOBAL IN ({subquery})"

    def _log_resource_filter(self, start: datetime, end: datetime, service: str, namespace: str, cluster: str) -> str:
        subquery = self._resource_subquery(LOG_RESOURCES_TABLE, start, end, service, namespace, cluster)
        if not subquery:
            return ""
        return f"resource_fingerprint GLOBAL IN ({subquery})"

    def _resource_subquery(self, table: str, start: datetime, end: datetime, service: str, namespace: str, cluster: str) -> str:
        if not any([service, namespace, cluster]):
            return ""
        conditions = [
            f"seen_at_ts_bucket_start >= {int(start.timestamp())}",
            f"seen_at_ts_bucket_start <= {int(end.timestamp())}",
        ]
        if service:
            conditions.append(
                "("
                + " OR ".join(
                    [
                        self._resource_label_match("service.name", service),
                        self._resource_label_match("k8s.service.name", service),
                        self._resource_label_match("k8s.deployment.name", service),
                    ]
                )
                + ")"
            )
        if namespace:
            conditions.append(self._resource_label_match("k8s.namespace.name", namespace))
        if cluster:
            conditions.append(self._resource_label_match("k8s.cluster.name", cluster))
        return f"SELECT fingerprint FROM {table} WHERE {' AND '.join(conditions)}"

    def _resource_label_match(self, key: str, value: str) -> str:
        safe = value.replace("'", "''")
        escaped = safe.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_").replace('"', '\\"')
        return f"(simpleJSONExtractString(labels, '{key}') = '{safe}' AND labels LIKE '%\\\"{key}\\\":\\\"{escaped}%')"

    @staticmethod
    def _log_signal_filter() -> str:
        return (
            "lowerUTF8(severity_text) IN ('error', 'fatal', 'warn', 'warning') OR "
            "severity_number >= 13 OR "
            "positionCaseInsensitive(body, 'error') > 0 OR "
            "positionCaseInsensitive(body, 'exception') > 0 OR "
            "positionCaseInsensitive(body, 'backoff') > 0 OR "
            "positionCaseInsensitive(body, 'failed') > 0"
        )

    @staticmethod
    def _normalize_array(value):
        if value is None:
            return []
        if isinstance(value, str):
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                return [value]
        return list(value)

    @staticmethod
    def _eq_or_any(column: str, value: str) -> str:
        if not value:
            return "1 = 1"
        safe = value.replace("'", "''")
        return f"{column} = '{safe}'"

    @staticmethod
    def _canonical_infra_token(value: str) -> str:
        token = (value or "").strip().lower()
        token = token.replace(".svc.cluster.local", "").replace(".svc", "").replace(".cluster.local", "").replace(".local", "")
        token = re.sub(r"[^a-z0-9]+", "-", token)
        return token.strip("-._/")

    @classmethod
    def _canonical_messaging_node(cls, system: str, destination: str) -> str:
        normalized_system = cls._canonical_infra_token(system) or "broker"
        normalized_destination = cls._canonical_infra_token(destination)
        return f"messaging:{normalized_system}/{normalized_destination}" if normalized_destination else f"messaging:{normalized_system}"

    @classmethod
    def _canonical_database_node(cls, system: str, name: str) -> str:
        normalized_system = cls._canonical_infra_token(system) or "database"
        normalized_name = cls._canonical_infra_token(name)
        return f"db:{normalized_system}/{normalized_name}" if normalized_name else f"db:{normalized_system}"

    @staticmethod
    def _quality_state(count: int, zero_values: bool, stale: bool) -> str:
        if stale:
            return "stale"
        if count == 0:
            return "missing"
        if zero_values:
            return "zero"
        if count < 3:
            return "sparse"
        return "present"

    @staticmethod
    def _canonicalize_name(value: str) -> str:
        if not value:
            return ""
        lowered = value.strip().lower()
        for suffix in (".svc.cluster.local", ".svc", ".cluster.local", ".local"):
            if lowered.endswith(suffix):
                lowered = lowered[: -len(suffix)]
        lowered = re.sub(r"-[a-f0-9]{8,10}-[a-z0-9]{5}$", "", lowered)
        lowered = re.sub(r"-[a-f0-9]{8,10}$", "", lowered)
        return lowered.strip("-._")

    @staticmethod
    def _trace_service_expr() -> str:
        return (
            "replaceRegexpOne(replaceRegexpOne(lowerUTF8(coalesce("
            "nullIf(serviceName, ''),"
            "nullIf(resources_string['service.name'], ''),"
            "nullIf(resources_string['k8s.service.name'], ''),"
            "nullIf(resources_string['k8s.deployment.name'], ''),"
            "nullIf(resources_string['k8s.container.name'], ''),"
            "nullIf(resources_string['k8s.pod.name'], '')"
            ")), '-[a-f0-9]{8,10}-[a-z0-9]{5}$', ''), '-[a-f0-9]{8,10}$', '')"
        )

    @staticmethod
    def _log_service_expr() -> str:
        return (
            "replaceRegexpOne(replaceRegexpOne(lowerUTF8(coalesce("
            "nullIf(resources_string['service.name'], ''),"
            "nullIf(resources_string['k8s.service.name'], ''),"
            "nullIf(resources_string['k8s.deployment.name'], ''),"
            "nullIf(resources_string['k8s.container.name'], ''),"
            "nullIf(resources_string['k8s.pod.name'], '')"
            ")), '-[a-f0-9]{8,10}-[a-z0-9]{5}$', ''), '-[a-f0-9]{8,10}$', '')"
        )

    @staticmethod
    def _metric_service_expr(alias: str = "") -> str:
        prefix = f"{alias}." if alias else ""
        return (
            "replaceRegexpOne(replaceRegexpOne(lowerUTF8(coalesce("
            f"nullIf({prefix}resource_attrs['service.name'], ''),"
            f"nullIf({prefix}resource_attrs['k8s.service.name'], ''),"
            f"nullIf({prefix}resource_attrs['k8s.deployment.name'], ''),"
            f"nullIf({prefix}resource_attrs['k8s.container.name'], ''),"
            f"nullIf({prefix}resource_attrs['k8s.pod.name'], '')"
            ")), '-[a-f0-9]{8,10}-[a-z0-9]{5}$', ''), '-[a-f0-9]{8,10}$', '')"
        )

    @staticmethod
    def _trace_noise_filter() -> str:
        return (
            "positionCaseInsensitive(name, '/actuator/prometheus') = 0 "
            "AND positionCaseInsensitive(name, '/actuator/health') = 0 "
            "AND positionCaseInsensitive(attributes_string['http.route'], '/actuator/prometheus') = 0 "
            "AND positionCaseInsensitive(attributes_string['http.route'], '/actuator/health') = 0"
        )

    @staticmethod
    def _forecast(series: list[float], alpha: float = 0.45) -> float:
        if not series:
            return 0.0
        level = series[0]
        trend = 0.0
        for value in series[1:]:
            prev_level = level
            level = alpha * value + (1 - alpha) * (level + trend)
            trend = alpha * (level - prev_level) + (1 - alpha) * trend
        return max(0.0, level + trend)

    @staticmethod
    def _kubernetes_rollout_events(center: datetime, namespace: str) -> list[dict]:
        try:
            output = subprocess.check_output(
                ["kubectl", "get", "events", "-A", "-o", "json"],
                stderr=subprocess.DEVNULL,
                text=True,
                timeout=10,
            )
        except Exception:  # noqa: BLE001
            return []
        try:
            payload = json.loads(output)
        except json.JSONDecodeError:
            return []
        events: list[dict] = []
        for item in payload.get("items", []):
            ns = item.get("metadata", {}).get("namespace", "")
            if namespace and ns not in {"", namespace}:
                continue
            reason = str(item.get("reason", "")).lower()
            message = str(item.get("message", ""))
            combined = f"{reason} {message}".lower()
            if "deploy" not in combined and "rollout" not in combined and "scaled" not in combined:
                continue
            ts = (
                item.get("eventTime")
                or item.get("lastTimestamp")
                or item.get("firstTimestamp")
                or item.get("metadata", {}).get("creationTimestamp")
            )
            if not ts:
                continue
            try:
                event_time = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            except ValueError:
                continue
            if abs((event_time - center).total_seconds()) > 3600:
                continue
            involved = item.get("involvedObject", {})
            events.append(
                {
                    "timestamp": event_time.astimezone(timezone.utc).isoformat(),
                    "service": involved.get("name", ""),
                    "details": message or str(item.get("reason", "")),
                    "deployment_name": involved.get("name", ""),
                    "deployment_version": item.get("metadata", {}).get("resourceVersion", ""),
                    "deployment_time": event_time.astimezone(timezone.utc).isoformat(),
                }
            )
        return events

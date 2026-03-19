from __future__ import annotations

import json
import uuid
from contextlib import contextmanager

import psycopg

from .config import Settings


@contextmanager
def postgres_connection(settings: Settings):
    conn = psycopg.connect(
        host=settings.postgres_host,
        port=settings.postgres_port,
        dbname=settings.postgres_db,
        user=settings.postgres_user,
        password=settings.postgres_password,
        autocommit=True,
    )
    try:
        ensure_schema(conn)
        yield conn
    finally:
        conn.close()


def ensure_schema(conn: psycopg.Connection) -> None:
    statements = [
        """
        ALTER TABLE incidents
            ADD COLUMN IF NOT EXISTS project_id TEXT NOT NULL DEFAULT 'default-project',
            ADD COLUMN IF NOT EXISTS problem_id TEXT NOT NULL DEFAULT '',
            ADD COLUMN IF NOT EXISTS incident_type TEXT NOT NULL DEFAULT 'observed',
            ADD COLUMN IF NOT EXISTS predictive_confidence DOUBLE PRECISION NOT NULL DEFAULT 0,
            ADD COLUMN IF NOT EXISTS root_cause_entity TEXT NOT NULL DEFAULT '',
            ADD COLUMN IF NOT EXISTS dependency_chain JSONB NOT NULL DEFAULT '[]'::jsonb,
            ADD COLUMN IF NOT EXISTS remediation_suggestions JSONB NOT NULL DEFAULT '[]'::jsonb,
            ADD COLUMN IF NOT EXISTS timeline_summary JSONB NOT NULL DEFAULT '[]'::jsonb
        """,
        """
        ALTER TABLE reasoning
            ADD COLUMN IF NOT EXISTS root_cause_service TEXT NOT NULL DEFAULT '',
            ADD COLUMN IF NOT EXISTS root_cause_signal TEXT NOT NULL DEFAULT '',
            ADD COLUMN IF NOT EXISTS confidence_explanation JSONB NOT NULL DEFAULT '{}'::jsonb,
            ADD COLUMN IF NOT EXISTS propagation_path JSONB NOT NULL DEFAULT '[]'::jsonb,
            ADD COLUMN IF NOT EXISTS customer_impact TEXT NOT NULL DEFAULT '',
            ADD COLUMN IF NOT EXISTS missing_telemetry_signals JSONB NOT NULL DEFAULT '[]'::jsonb,
            ADD COLUMN IF NOT EXISTS observability_score DOUBLE PRECISION NOT NULL DEFAULT 0,
            ADD COLUMN IF NOT EXISTS observability_summary JSONB NOT NULL DEFAULT '{}'::jsonb,
            ADD COLUMN IF NOT EXISTS deployment_correlation TEXT NOT NULL DEFAULT '',
            ADD COLUMN IF NOT EXISTS historical_matches JSONB NOT NULL DEFAULT '[]'::jsonb
        """,
        """
        CREATE TABLE IF NOT EXISTS incident_knowledge_base (
            incident_id TEXT PRIMARY KEY REFERENCES incidents(incident_id) ON DELETE CASCADE,
            fingerprint TEXT NOT NULL,
            root_cause_service TEXT NOT NULL DEFAULT '',
            root_cause_signal TEXT NOT NULL DEFAULT '',
            summary TEXT NOT NULL DEFAULT '',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS runbooks (
            runbook_id TEXT PRIMARY KEY,
            incident_type TEXT NOT NULL,
            root_cause_signal TEXT NOT NULL,
            steps JSONB NOT NULL DEFAULT '[]'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS reasoning_validations (
            incident_id TEXT PRIMARY KEY REFERENCES incidents(incident_id) ON DELETE CASCADE,
            reasoning_statements JSONB NOT NULL DEFAULT '[]'::jsonb,
            supporting_signals JSONB NOT NULL DEFAULT '[]'::jsonb,
            unsupported_statements JSONB NOT NULL DEFAULT '[]'::jsonb,
            validation_result TEXT NOT NULL DEFAULT 'partial',
            confidence_score DOUBLE PRECISION NOT NULL DEFAULT 0,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS reasoning_requests (
            incident_id TEXT PRIMARY KEY REFERENCES incidents(incident_id) ON DELETE CASCADE,
            status TEXT NOT NULL DEFAULT 'pending',
            last_error TEXT NOT NULL DEFAULT '',
            attempts INTEGER NOT NULL DEFAULT 0,
            trigger_type TEXT NOT NULL DEFAULT 'manual',
            requested_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            started_at TIMESTAMPTZ,
            completed_at TIMESTAMPTZ,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """,
        "ALTER TABLE reasoning_requests ADD COLUMN IF NOT EXISTS trigger_type TEXT NOT NULL DEFAULT 'manual'",
        """
        CREATE TABLE IF NOT EXISTS reasoning_runs (
            reasoning_run_id TEXT PRIMARY KEY,
            incident_id TEXT NOT NULL REFERENCES incidents(incident_id) ON DELETE CASCADE,
            status TEXT NOT NULL,
            provider TEXT NOT NULL,
            model TEXT NOT NULL,
            trigger_type TEXT NOT NULL,
            error_message TEXT NOT NULL DEFAULT '',
            summary TEXT NOT NULL DEFAULT '',
            root_cause_service TEXT NOT NULL DEFAULT '',
            root_cause_signal TEXT NOT NULL DEFAULT '',
            root_cause_confidence DOUBLE PRECISION NOT NULL DEFAULT 0,
            suggested_actions JSONB NOT NULL DEFAULT '[]'::jsonb,
            propagation_path JSONB NOT NULL DEFAULT '[]'::jsonb,
            evidence_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
            confidence_explanation JSONB NOT NULL DEFAULT '{}'::jsonb,
            correlation_summary TEXT NOT NULL DEFAULT '',
            started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            completed_at TIMESTAMPTZ
        )
        """,
    ]
    with conn.cursor() as cur:
        for statement in statements:
            cur.execute(statement)


def fetch_pending_incidents(conn: psycopg.Connection, settings: Settings) -> list[dict]:
    where_parts = ["r.incident_id IS NULL", "i.project_id = %s"]
    params: list[object] = [settings.project_id]
    if settings.cluster_id:
        where_parts.append("i.cluster = %s")
        params.append(settings.cluster_id)
    if settings.namespace_filter:
        where_parts.append("i.namespace = %s")
        params.append(settings.namespace_filter)
    if settings.service_filter:
        where_parts.append("i.service = %s")
        params.append(settings.service_filter)
    with conn.cursor(row_factory=psycopg.rows.dict_row) as cur:
        cur.execute(
            f"""
            SELECT
                i.incident_id,
                i.project_id,
                i.problem_id,
                i.cluster,
                i.namespace,
                i.service,
                i.timestamp,
                i.severity,
                i.anomaly_score,
                i.telemetry_snapshot,
                i.detector_signals,
                i.timeline_summary,
                i.incident_type,
                i.predictive_confidence
            FROM incidents i
            LEFT JOIN reasoning r ON r.incident_id = i.incident_id
            WHERE {" AND ".join(where_parts)}
            ORDER BY i.timestamp ASC
            LIMIT 20
            """,
            params,
        )
        rows = cur.fetchall()
    for row in rows:
        for key in ("telemetry_snapshot", "detector_signals", "timeline_summary"):
            if isinstance(row[key], str):
                row[key] = json.loads(row[key])
    return rows


def fetch_reasoning_requests(conn: psycopg.Connection, settings: Settings, limit: int = 20) -> list[dict]:
    where_parts = ["rr.status = 'pending'", "i.project_id = %s"]
    params: list[object] = [settings.project_id]
    if settings.cluster_id:
        where_parts.append("i.cluster = %s")
        params.append(settings.cluster_id)
    if settings.namespace_filter:
        where_parts.append("i.namespace = %s")
        params.append(settings.namespace_filter)
    if settings.service_filter:
        where_parts.append("i.service = %s")
        params.append(settings.service_filter)
    with conn.cursor(row_factory=psycopg.rows.dict_row) as cur:
        cur.execute(
            f"""
            SELECT
                i.incident_id,
                i.project_id,
                i.problem_id,
                i.cluster,
                i.namespace,
                i.service,
                i.timestamp,
                i.severity,
                i.anomaly_score,
                i.telemetry_snapshot,
                i.detector_signals,
                i.timeline_summary,
                i.incident_type,
                i.predictive_confidence,
                rr.trigger_type
            FROM reasoning_requests rr
            INNER JOIN incidents i ON i.incident_id = rr.incident_id
            WHERE {" AND ".join(where_parts)}
            ORDER BY rr.requested_at ASC
            LIMIT %s
            """,
            (*params, limit),
        )
        rows = cur.fetchall()
    for row in rows:
        for key in ("telemetry_snapshot", "detector_signals", "timeline_summary"):
            if isinstance(row[key], str):
                row[key] = json.loads(row[key])
    return rows


def claim_reasoning_request(conn: psycopg.Connection, incident_id: str) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE reasoning_requests
            SET status = 'running',
                started_at = COALESCE(started_at, NOW()),
                updated_at = NOW(),
                attempts = attempts + 1
            WHERE incident_id = %s
              AND status = 'pending'
            RETURNING incident_id
            """,
            (incident_id,),
        )
        return cur.fetchone() is not None


def update_reasoning_request_status(conn: psycopg.Connection, incident_id: str, status: str, error: str = "") -> None:
    completed_at = "NOW()" if status in {"completed", "failed"} else "NULL"
    with conn.cursor() as cur:
        cur.execute(
            f"""
            UPDATE reasoning_requests
            SET status = %s,
                last_error = %s,
                completed_at = {completed_at},
                updated_at = NOW()
            WHERE incident_id = %s
            """,
            (status, error or "", incident_id),
        )


def predictive_incident_exists(conn: psycopg.Connection, cluster: str, namespace: str, service: str, within_minutes: int = 20) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT count(*)
            FROM incidents
            WHERE cluster = %s
              AND namespace = %s
              AND service = %s
              AND incident_type = 'predictive'
              AND timestamp >= NOW() - (%s || ' minutes')::interval
            """,
            (cluster, namespace, service, within_minutes),
        )
        count = cur.fetchone()[0]
        return count > 0


def create_predictive_incident(conn: psycopg.Connection, settings: Settings, prediction: dict) -> str:
    incident_id = str(uuid.uuid4())
    telemetry_snapshot = {
        "forecast_horizon_minutes": prediction.get("horizon_minutes", 10),
        "predicted_latency_ms": prediction.get("predicted_latency_ms", 0),
        "predicted_error_rate": prediction.get("predicted_error_rate", 0),
        "recent_latency_series": prediction.get("recent_latency_series", []),
        "recent_error_series": prediction.get("recent_error_series", []),
        "model": "exponential_smoothing",
    }
    anomaly_score = float(prediction.get("anomaly_score", 0))
    severity = prediction.get("severity", "medium")
    detector_signals = prediction.get("signals", ["predictive_risk"])
    confidence = float(prediction.get("confidence", 0.0))

    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO incidents (
                incident_id,
                project_id,
                problem_id,
                cluster,
                namespace,
                service,
                timestamp,
                severity,
                anomaly_score,
                telemetry_snapshot,
                detector_signals,
                incident_type,
                predictive_confidence,
                root_cause_entity,
                dependency_chain,
                remediation_suggestions,
                timeline_summary
            ) VALUES (
                %s, %s, %s, %s, %s, %s, NOW(), %s, %s, %s::jsonb, %s::jsonb, 'predictive', %s, %s, '[]'::jsonb, '[]'::jsonb, '[]'::jsonb
            )
            ON CONFLICT (incident_id) DO NOTHING
            """,
            (
                incident_id,
                settings.project_id,
                prediction.get("problem_id", ""),
                prediction.get("cluster", ""),
                prediction.get("namespace", ""),
                prediction.get("service", ""),
                severity,
                anomaly_score,
                json.dumps(telemetry_snapshot, default=str),
                json.dumps(detector_signals, default=str),
                confidence,
                prediction.get("service", ""),
            ),
        )
    return incident_id


def fetch_historical_matches(conn: psycopg.Connection, incident: dict) -> list[dict]:
    with conn.cursor(row_factory=psycopg.rows.dict_row) as cur:
        cur.execute(
            """
            SELECT
                i.incident_id,
                i.problem_id,
                i.service,
                i.namespace,
                i.cluster,
                i.severity,
                i.anomaly_score,
                i.timestamp,
                r.root_cause_service,
                r.root_cause_signal,
                r.root_cause
            FROM incidents i
            LEFT JOIN reasoning r ON r.incident_id = i.incident_id
            WHERE i.incident_id <> %s
              AND (i.service = %s OR i.problem_id = %s OR i.namespace = %s)
              AND r.incident_id IS NOT NULL
            ORDER BY i.timestamp DESC
            LIMIT 5
            """,
            (
                incident["incident_id"],
                incident["service"],
                incident.get("problem_id", ""),
                incident["namespace"],
            ),
        )
        return cur.fetchall()


def store_reasoning(conn: psycopg.Connection, incident: dict, reasoning: dict) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO reasoning (
                incident_id,
                root_cause,
                root_cause_service,
                root_cause_signal,
                confidence_score,
                confidence_explanation,
                causal_chain,
                correlated_signals,
                propagation_path,
                impact_assessment,
                customer_impact,
                recommended_actions,
                missing_telemetry_signals,
                observability_score,
                observability_summary,
                deployment_correlation,
                historical_matches,
                severity
            ) VALUES (
                %s,%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s::jsonb,%s::jsonb,%s,%s,%s::jsonb,%s::jsonb,%s,%s::jsonb,%s,%s::jsonb,%s
            )
            ON CONFLICT (incident_id) DO NOTHING
            """,
            (
                incident["incident_id"],
                reasoning["root_cause"],
                reasoning["root_cause_service"],
                reasoning["root_cause_signal"],
                reasoning["confidence_score"],
                json.dumps(reasoning.get("confidence_explanation", {}), default=str),
                json.dumps(reasoning["causal_chain"], default=str),
                json.dumps(reasoning["correlated_signals"], default=str),
                json.dumps(reasoning["propagation_path"], default=str),
                reasoning["impact_assessment"],
                reasoning["customer_impact"],
                json.dumps(reasoning["recommended_actions"], default=str),
                json.dumps(reasoning["missing_telemetry_signals"], default=str),
                reasoning["observability_score"],
                json.dumps(reasoning["observability_summary"], default=str),
                reasoning["deployment_correlation"],
                json.dumps(reasoning["historical_matches"], default=str),
                reasoning["severity"],
            ),
        )
        cur.execute(
            """
            UPDATE incidents
            SET
                root_cause_entity = %s,
                dependency_chain = %s::jsonb,
                remediation_suggestions = %s::jsonb
            WHERE incident_id = %s
            """,
            (
                reasoning["root_cause_service"],
                json.dumps(reasoning["propagation_path"], default=str),
                json.dumps(reasoning["recommended_actions"], default=str),
                incident["incident_id"],
            ),
        )
        cur.execute(
            """
            INSERT INTO incident_knowledge_base (
                incident_id,
                fingerprint,
                root_cause_service,
                root_cause_signal,
                summary
            ) VALUES (%s,%s,%s,%s,%s)
            ON CONFLICT (incident_id) DO UPDATE SET
                fingerprint = EXCLUDED.fingerprint,
                root_cause_service = EXCLUDED.root_cause_service,
                root_cause_signal = EXCLUDED.root_cause_signal,
                summary = EXCLUDED.summary,
                created_at = NOW()
            """,
            (
                incident["incident_id"],
                build_fingerprint(incident),
                reasoning["root_cause_service"],
                reasoning["root_cause_signal"],
                reasoning["root_cause"],
            ),
        )


def build_fingerprint(incident: dict) -> str:
    return "|".join(
        [
            incident.get("project_id", ""),
            incident.get("cluster", ""),
            incident.get("namespace", ""),
            incident.get("service", ""),
            ",".join(sorted(incident.get("detector_signals", []))),
        ]
    )


def store_runbook(conn: psycopg.Connection, runbook: dict) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO runbooks (runbook_id, incident_type, root_cause_signal, steps, created_at)
            VALUES (%s,%s,%s,%s::jsonb,NOW())
            ON CONFLICT (runbook_id) DO UPDATE SET
                steps = EXCLUDED.steps,
                created_at = NOW()
            """,
            (
                runbook["runbook_id"],
                runbook["incident_type"],
                runbook["root_cause_signal"],
                json.dumps(runbook["steps"], default=str),
            ),
        )


def fetch_reasoned_incidents_without_runbook(conn: psycopg.Connection, limit: int = 10) -> list[dict]:
    with conn.cursor(row_factory=psycopg.rows.dict_row) as cur:
        cur.execute(
            """
            SELECT
                i.incident_id,
                i.incident_type,
                i.namespace,
                i.service,
                i.detector_signals,
                r.root_cause_signal,
                r.recommended_actions
            FROM incidents i
            INNER JOIN reasoning r ON r.incident_id = i.incident_id
            LEFT JOIN runbooks rb
              ON rb.incident_type = i.incident_type
             AND rb.root_cause_signal = r.root_cause_signal
            WHERE rb.runbook_id IS NULL
            ORDER BY i.timestamp DESC
            LIMIT %s
            """,
            (limit,),
        )
        rows = cur.fetchall()
    for row in rows:
        for key in ("detector_signals", "recommended_actions"):
            if isinstance(row.get(key), str):
                try:
                    row[key] = json.loads(row[key])
                except json.JSONDecodeError:
                    row[key] = [row[key]]
    return rows


def fetch_known_services(conn: psycopg.Connection) -> set[str]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT DISTINCT service_name
            FROM services_registry
            WHERE service_name IS NOT NULL
              AND service_name <> ''
            """
        )
        return {row[0] for row in cur.fetchall()}


def store_reasoning_validation(conn: psycopg.Connection, report) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO reasoning_validations (
                incident_id,
                reasoning_statements,
                supporting_signals,
                unsupported_statements,
                validation_result,
                confidence_score,
                created_at
            ) VALUES (%s,%s::jsonb,%s::jsonb,%s::jsonb,%s,%s,NOW())
            ON CONFLICT (incident_id) DO UPDATE SET
                reasoning_statements = EXCLUDED.reasoning_statements,
                supporting_signals = EXCLUDED.supporting_signals,
                unsupported_statements = EXCLUDED.unsupported_statements,
                validation_result = EXCLUDED.validation_result,
                confidence_score = EXCLUDED.confidence_score,
                created_at = NOW()
            """,
            (
                report.incident_id,
                json.dumps(report.reasoning_statements, default=str),
                json.dumps(report.supporting_signals, default=str),
                json.dumps(report.unsupported_statements, default=str),
                report.validation_result,
                report.confidence_score,
            ),
        )


def create_reasoning_run(conn: psycopg.Connection, run: dict) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO reasoning_runs (
                reasoning_run_id,
                incident_id,
                status,
                provider,
                model,
                trigger_type,
                error_message,
                summary,
                root_cause_service,
                root_cause_signal,
                root_cause_confidence,
                suggested_actions,
                propagation_path,
                evidence_snapshot,
                confidence_explanation,
                correlation_summary,
                started_at,
                completed_at
            ) VALUES (
                %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s::jsonb,%s::jsonb,%s,%s,%s
            )
            """,
            (
                run["reasoning_run_id"],
                run["incident_id"],
                run["status"],
                run["provider"],
                run["model"],
                run["trigger_type"],
                run.get("error_message", ""),
                run.get("summary", ""),
                run.get("root_cause_service", ""),
                run.get("root_cause_signal", ""),
                run.get("root_cause_confidence", 0.0),
                json.dumps(run.get("suggested_actions", []), default=str),
                json.dumps(run.get("propagation_path", []), default=str),
                json.dumps(run.get("evidence_snapshot", {}), default=str),
                json.dumps(run.get("confidence_explanation", {}), default=str),
                run.get("correlation_summary", ""),
                run.get("started_at"),
                run.get("completed_at"),
            ),
        )


def update_reasoning_run(conn: psycopg.Connection, run_id: str, updates: dict) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE reasoning_runs
            SET
                status = %s,
                error_message = %s,
                summary = %s,
                root_cause_service = %s,
                root_cause_signal = %s,
                root_cause_confidence = %s,
                suggested_actions = %s::jsonb,
                propagation_path = %s::jsonb,
                evidence_snapshot = %s::jsonb,
                confidence_explanation = %s::jsonb,
                correlation_summary = %s,
                completed_at = %s
            WHERE reasoning_run_id = %s
            """,
            (
                updates.get("status", ""),
                updates.get("error_message", ""),
                updates.get("summary", ""),
                updates.get("root_cause_service", ""),
                updates.get("root_cause_signal", ""),
                updates.get("root_cause_confidence", 0.0),
                json.dumps(updates.get("suggested_actions", []), default=str),
                json.dumps(updates.get("propagation_path", []), default=str),
                json.dumps(updates.get("evidence_snapshot", {}), default=str),
                json.dumps(updates.get("confidence_explanation", {}), default=str),
                updates.get("correlation_summary", ""),
                updates.get("completed_at"),
                run_id,
            ),
        )

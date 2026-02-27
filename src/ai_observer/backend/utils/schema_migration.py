from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.engine import Engine


def ensure_enterprise_schema(engine: Engine) -> None:
    """Best-effort runtime schema alignment for existing deployments."""
    with engine.begin() as conn:
        dialect = conn.dialect.name
        if dialect == "postgresql":
            conn.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS incidents (
                      id SERIAL PRIMARY KEY,
                      incident_id VARCHAR(128) UNIQUE NOT NULL,
                      cluster_id VARCHAR(128) NOT NULL DEFAULT '',
                      status VARCHAR(32) NOT NULL,
                      severity VARCHAR(32) NOT NULL,
                      impact_level VARCHAR(32) NOT NULL,
                      slo_breach_risk DOUBLE PRECISION NOT NULL,
                      error_budget_remaining DOUBLE PRECISION NOT NULL,
                      affected_services TEXT NOT NULL,
                      start_time TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                      duration VARCHAR(32) NOT NULL DEFAULT '00:00:00',
                      created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    );
                    CREATE INDEX IF NOT EXISTS ix_incidents_created_at ON incidents(created_at);
                    CREATE INDEX IF NOT EXISTS ix_incidents_start_time ON incidents(start_time);
                    """
                )
            )
            conn.execute(text("ALTER TABLE incidents ADD COLUMN IF NOT EXISTS cluster_id VARCHAR(128) NOT NULL DEFAULT ''"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_incidents_cluster_id ON incidents(cluster_id)"))
            conn.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS incident_metrics_snapshot (
                      id SERIAL PRIMARY KEY,
                      incident_id VARCHAR(128) NOT NULL REFERENCES incidents(incident_id) ON DELETE CASCADE,
                      cpu_usage DOUBLE PRECISION NOT NULL DEFAULT 0,
                      memory_usage DOUBLE PRECISION NOT NULL DEFAULT 0,
                      latency_p95 DOUBLE PRECISION NOT NULL DEFAULT 0,
                      error_rate DOUBLE PRECISION NOT NULL DEFAULT 0,
                      thread_pool_saturation DOUBLE PRECISION NOT NULL DEFAULT 0,
                      raw_metrics_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                      captured_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    );
                    CREATE INDEX IF NOT EXISTS ix_metrics_snapshot_incident_id ON incident_metrics_snapshot(incident_id);
                    CREATE INDEX IF NOT EXISTS ix_metrics_snapshot_captured_at ON incident_metrics_snapshot(captured_at);
                    """
                )
            )
            conn.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS incident_status_history (
                      id SERIAL PRIMARY KEY,
                      incident_id VARCHAR(128) NOT NULL REFERENCES incidents(incident_id) ON DELETE CASCADE,
                      from_status VARCHAR(32) NOT NULL,
                      to_status VARCHAR(32) NOT NULL,
                      changed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    );
                    CREATE INDEX IF NOT EXISTS ix_status_history_incident_id ON incident_status_history(incident_id);
                    """
                )
            )
            conn.execute(text("ALTER TABLE incident_analysis ADD COLUMN IF NOT EXISTS executive_summary TEXT"))
            conn.execute(text("ALTER TABLE incident_analysis ADD COLUMN IF NOT EXISTS cluster_id VARCHAR(128) NOT NULL DEFAULT ''"))
            conn.execute(text("ALTER TABLE incident_analysis ADD COLUMN IF NOT EXISTS supporting_signals JSONB NOT NULL DEFAULT '{}'::jsonb"))
            conn.execute(text("ALTER TABLE incident_analysis ADD COLUMN IF NOT EXISTS suggested_actions JSONB NOT NULL DEFAULT '{}'::jsonb"))
            conn.execute(text("ALTER TABLE incident_analysis ADD COLUMN IF NOT EXISTS confidence_breakdown JSONB NOT NULL DEFAULT '{}'::jsonb"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS ix_incident_analysis_cluster_id ON incident_analysis(cluster_id)"))
            # Backfill parent incident rows for legacy incident_analysis data before adding FK.
            conn.execute(
                text(
                    """
                    INSERT INTO incidents (
                      incident_id,
                      status,
                      severity,
                      impact_level,
                      slo_breach_risk,
                      error_budget_remaining,
                      affected_services,
                      start_time,
                      duration,
                      created_at
                    )
                    SELECT
                      ia.incident_id,
                      'OPEN',
                      'WARNING',
                      'Low',
                      COALESCE(ia.risk_forecast, 0) * 100.0,
                      100.0,
                      COALESCE(NULLIF(ia.service_name, ''), 'unknown'),
                      COALESCE(ia.created_at, NOW()),
                      '00:00:00',
                      COALESCE(ia.created_at, NOW())
                    FROM incident_analysis ia
                    LEFT JOIN incidents i ON i.incident_id = ia.incident_id
                    WHERE ia.incident_id IS NOT NULL
                      AND ia.incident_id <> ''
                      AND i.incident_id IS NULL;
                    """
                )
            )
            conn.execute(
                text(
                    """
                    DO $$
                    BEGIN
                        IF NOT EXISTS (
                            SELECT 1
                            FROM pg_constraint
                            WHERE conname = 'fk_incident_analysis_incident_id'
                        ) THEN
                            ALTER TABLE incident_analysis
                            ADD CONSTRAINT fk_incident_analysis_incident_id
                            FOREIGN KEY (incident_id) REFERENCES incidents(incident_id) ON DELETE CASCADE;
                        END IF;
                    END $$;
                    """
                )
            )
        else:
            # SQLite/dev fallback for local tests.
            conn.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS incidents (
                      id INTEGER PRIMARY KEY AUTOINCREMENT,
                      incident_id TEXT UNIQUE NOT NULL,
                      cluster_id TEXT NOT NULL DEFAULT '',
                      status TEXT NOT NULL,
                      severity TEXT NOT NULL,
                      impact_level TEXT NOT NULL,
                      slo_breach_risk REAL NOT NULL,
                      error_budget_remaining REAL NOT NULL,
                      affected_services TEXT NOT NULL,
                      start_time TEXT NOT NULL,
                      duration TEXT NOT NULL,
                      created_at TEXT NOT NULL
                    )
                    """
                )
            )
            conn.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS incident_metrics_snapshot (
                      id INTEGER PRIMARY KEY AUTOINCREMENT,
                      incident_id TEXT NOT NULL,
                      cpu_usage REAL NOT NULL,
                      memory_usage REAL NOT NULL,
                      latency_p95 REAL NOT NULL,
                      error_rate REAL NOT NULL,
                      thread_pool_saturation REAL NOT NULL,
                      raw_metrics_json TEXT NOT NULL,
                      captured_at TEXT NOT NULL
                    )
                    """
                )
            )
            conn.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS incident_status_history (
                      id INTEGER PRIMARY KEY AUTOINCREMENT,
                      incident_id TEXT NOT NULL,
                      from_status TEXT NOT NULL,
                      to_status TEXT NOT NULL,
                      changed_at TEXT NOT NULL
                    )
                    """
                )
            )
            for column, col_type, default_sql in [
                ("executive_summary", "TEXT", "NULL"),
                ("cluster_id", "TEXT", "''"),
                ("supporting_signals", "TEXT", "'{}'"),
                ("suggested_actions", "TEXT", "'{}'"),
                ("confidence_breakdown", "TEXT", "'{}'"),
            ]:
                try:
                    conn.execute(text(f"ALTER TABLE incident_analysis ADD COLUMN {column} {col_type} DEFAULT {default_sql}"))
                except Exception:
                    pass

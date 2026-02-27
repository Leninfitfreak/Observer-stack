CREATE TABLE IF NOT EXISTS incident_analysis (
    id BIGSERIAL PRIMARY KEY,
    incident_id VARCHAR(128) NOT NULL,
    service_name VARCHAR(128) NOT NULL,
    cluster_id VARCHAR(128) NOT NULL DEFAULT '',
    anomaly_score DOUBLE PRECISION NOT NULL,
    confidence_score DOUBLE PRECISION NOT NULL,
    classification VARCHAR(64) NOT NULL,
    root_cause TEXT NOT NULL,
    mitigation JSONB NOT NULL DEFAULT '{}'::jsonb,
    risk_forecast DOUBLE PRECISION NOT NULL,
    mitigation_success BOOLEAN NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_incident_analysis_created_at ON incident_analysis (created_at);
CREATE INDEX IF NOT EXISTS ix_incident_analysis_service_name ON incident_analysis (service_name);
CREATE INDEX IF NOT EXISTS ix_incident_analysis_incident_id ON incident_analysis (incident_id);
CREATE INDEX IF NOT EXISTS ix_incident_analysis_cluster_id ON incident_analysis (cluster_id);

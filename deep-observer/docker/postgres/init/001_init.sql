CREATE TABLE IF NOT EXISTS incidents (
    incident_id TEXT PRIMARY KEY,
    problem_id TEXT NOT NULL DEFAULT '',
    incident_type TEXT NOT NULL DEFAULT 'observed',
    predictive_confidence DOUBLE PRECISION NOT NULL DEFAULT 0,
    cluster TEXT NOT NULL,
    namespace TEXT NOT NULL,
    service TEXT NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL,
    severity TEXT NOT NULL,
    anomaly_score DOUBLE PRECISION NOT NULL,
    telemetry_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
    detector_signals JSONB NOT NULL DEFAULT '[]'::jsonb,
    root_cause_entity TEXT NOT NULL DEFAULT '',
    dependency_chain JSONB NOT NULL DEFAULT '[]'::jsonb,
    remediation_suggestions JSONB NOT NULL DEFAULT '[]'::jsonb,
    timeline_summary JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS incidents_service_timestamp_idx
    ON incidents(service, timestamp DESC);

CREATE INDEX IF NOT EXISTS incidents_problem_timestamp_idx
    ON incidents(problem_id, timestamp DESC);

CREATE TABLE IF NOT EXISTS reasoning (
    incident_id TEXT PRIMARY KEY REFERENCES incidents(incident_id) ON DELETE CASCADE,
    root_cause TEXT NOT NULL,
    root_cause_service TEXT NOT NULL DEFAULT '',
    root_cause_signal TEXT NOT NULL DEFAULT '',
    confidence_score DOUBLE PRECISION NOT NULL,
    confidence_explanation JSONB NOT NULL DEFAULT '{}'::jsonb,
    causal_chain JSONB NOT NULL DEFAULT '[]'::jsonb,
    correlated_signals JSONB NOT NULL DEFAULT '[]'::jsonb,
    propagation_path JSONB NOT NULL DEFAULT '[]'::jsonb,
    impact_assessment TEXT NOT NULL,
    customer_impact TEXT NOT NULL DEFAULT '',
    recommended_actions JSONB NOT NULL DEFAULT '[]'::jsonb,
    missing_telemetry_signals JSONB NOT NULL DEFAULT '[]'::jsonb,
    observability_score DOUBLE PRECISION NOT NULL DEFAULT 0,
    observability_summary JSONB NOT NULL DEFAULT '{}'::jsonb,
    deployment_correlation TEXT NOT NULL DEFAULT '',
    historical_matches JSONB NOT NULL DEFAULT '[]'::jsonb,
    severity TEXT NOT NULL DEFAULT 'unknown',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

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
);

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
);

CREATE TABLE IF NOT EXISTS incident_knowledge_base (
    incident_id TEXT PRIMARY KEY REFERENCES incidents(incident_id) ON DELETE CASCADE,
    fingerprint TEXT NOT NULL,
    root_cause_service TEXT NOT NULL DEFAULT '',
    root_cause_signal TEXT NOT NULL DEFAULT '',
    summary TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS dependency_graphs (
    cluster TEXT NOT NULL,
    namespace TEXT NOT NULL,
    graph JSONB NOT NULL DEFAULT '{"nodes":[],"edges":[]}'::jsonb,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (cluster, namespace)
);

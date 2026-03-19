package incidents

import (
	"context"
	"encoding/json"
	"regexp"
	"sort"
	"strings"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"

	"deep-observer/ai-core/internal/clickhouse"
	"deep-observer/ai-core/internal/config"
)

type Store struct {
	pool *pgxpool.Pool
}

var structuredIncidentEntityPattern = regexp.MustCompile(`^(?:[a-z0-9][a-z0-9-]{0,63}|db:[a-z0-9][a-z0-9._/-]{0,95}|messaging:[a-z0-9][a-z0-9._/-]{0,95})$`)

type QueryFilters struct {
	ProjectID string
	Cluster   string
	Namespace string
	Service   string
	ProblemID string
	Start     *time.Time
	End       *time.Time
	Limit     int
}

type Incident struct {
	ID                     string                     `json:"incident_id"`
	ProjectID              string                     `json:"project_id"`
	ProblemID              string                     `json:"problem_id"`
	IncidentType           string                     `json:"incident_type"`
	PredictiveConfidence   float64                    `json:"predictive_confidence"`
	Cluster                string                     `json:"cluster"`
	Namespace              string                     `json:"namespace"`
	Service                string                     `json:"service"`
	Timestamp              time.Time                  `json:"timestamp"`
	Severity               string                     `json:"severity"`
	AnomalyScore           float64                    `json:"anomaly_score"`
	TelemetrySnapshot      clickhouse.Snapshot        `json:"telemetry_snapshot"`
	Signals                []string                   `json:"signals"`
	RootCauseEntity        string                     `json:"root_cause_entity"`
	DependencyChain        []string                   `json:"dependency_chain"`
	RemediationSuggestions []string                   `json:"remediation_suggestions"`
	TimelineSummary        []clickhouse.TimelineEvent `json:"timeline_summary"`
	Impacts                []IncidentImpact           `json:"impacts"`
	Reasoning              *Reasoning                 `json:"reasoning,omitempty"`
	ReasoningStatus        string                     `json:"reasoning_status"`
	ReasoningError         string                     `json:"reasoning_error"`
	ReasoningRequestedAt   *time.Time                 `json:"reasoning_requested_at,omitempty"`
	ReasoningUpdatedAt     *time.Time                 `json:"reasoning_updated_at,omitempty"`
	WorkflowStatus         string                     `json:"workflow_status"`
	AssignedTo             string                     `json:"assigned_to"`
	AcknowledgedAt         *time.Time                 `json:"acknowledged_at,omitempty"`
	InvestigatingAt        *time.Time                 `json:"investigating_at,omitempty"`
	ResolvedAt             *time.Time                 `json:"resolved_at,omitempty"`
	WorkflowUpdatedAt      *time.Time                 `json:"workflow_updated_at,omitempty"`
}

type IncidentImpact struct {
	IncidentID string  `json:"incident_id"`
	Service    string  `json:"service"`
	ImpactType string  `json:"impact_type"`
	ImpactScore float64 `json:"impact_score"`
}

type Reasoning struct {
	IncidentID              string            `json:"incident_id"`
	RootCause               string            `json:"root_cause"`
	RootCauseService        string            `json:"root_cause_service"`
	RootCauseSignal         string            `json:"root_cause_signal"`
	ConfidenceScore         float64           `json:"confidence_score"`
	ConfidenceExplanation   map[string]any    `json:"confidence_explanation"`
	CausalChain             []string          `json:"causal_chain"`
	CorrelatedSignals       []string          `json:"correlated_signals"`
	PropagationPath         []string          `json:"propagation_path"`
	ImpactAssessment        string            `json:"impact_assessment"`
	CustomerImpact          string            `json:"customer_impact"`
	RecommendedActions      []string          `json:"recommended_actions"`
	MissingTelemetrySignals []string          `json:"missing_telemetry_signals"`
	ObservabilityScore      float64           `json:"observability_score"`
	ObservabilitySummary    map[string]string `json:"observability_summary"`
	DeploymentCorrelation   string            `json:"deployment_correlation"`
	HistoricalMatches       []map[string]any  `json:"historical_matches"`
	Severity                string            `json:"severity"`
	CreatedAt               time.Time         `json:"created_at"`
}

type ReasoningRequest struct {
	IncidentID  string     `json:"incident_id"`
	Status      string     `json:"status"`
	LastError   string     `json:"last_error"`
	Attempts    int        `json:"attempts"`
	TriggerType string     `json:"trigger_type"`
	RequestedAt time.Time  `json:"requested_at"`
	StartedAt   *time.Time `json:"started_at,omitempty"`
	CompletedAt *time.Time `json:"completed_at,omitempty"`
	UpdatedAt   time.Time  `json:"updated_at"`
}

type ReasoningRun struct {
	RunID                string         `json:"reasoning_run_id"`
	IncidentID           string         `json:"incident_id"`
	Status               string         `json:"status"`
	Provider             string         `json:"provider"`
	Model                string         `json:"model"`
	TriggerType          string         `json:"trigger_type"`
	ErrorMessage         string         `json:"error_message"`
	Summary              string         `json:"summary"`
	RootCauseService     string         `json:"root_cause_service"`
	RootCauseSignal      string         `json:"root_cause_signal"`
	RootCauseConfidence  float64        `json:"root_cause_confidence"`
	SuggestedActions     []string       `json:"suggested_actions"`
	PropagationPath      []string       `json:"propagation_path"`
	EvidenceSnapshot     map[string]any `json:"evidence_snapshot"`
	ConfidenceExplanation map[string]any `json:"confidence_explanation"`
	CorrelationSummary   string         `json:"correlation_summary"`
	StartedAt            time.Time      `json:"started_at"`
	CompletedAt          *time.Time     `json:"completed_at,omitempty"`
}

type CorrelatedIncident struct {
	IncidentID       string    `json:"incident_id"`
	Timestamp        time.Time `json:"timestamp"`
	RootCauseSummary string    `json:"root_cause_summary"`
	CorrelationReason string   `json:"correlation_reason"`
	CorrelationScore float64   `json:"correlation_score"`
}

func NewStore(ctx context.Context, cfg config.PostgresConfig) (*Store, error) {
	pool, err := pgxpool.New(ctx, cfg.DSN())
	if err != nil {
		return nil, err
	}
	if err := pool.Ping(ctx); err != nil {
		return nil, err
	}
	store := &Store{pool: pool}
	if err := store.EnsureSchema(ctx); err != nil {
		pool.Close()
		return nil, err
	}
	return store, nil
}

func (s *Store) Close() {
	s.pool.Close()
}

func (s *Store) EnsureSchema(ctx context.Context) error {
	statements := []string{
		`CREATE TABLE IF NOT EXISTS incidents (
			incident_id TEXT PRIMARY KEY,
			project_id TEXT NOT NULL DEFAULT 'default-project',
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
			workflow_status TEXT NOT NULL DEFAULT 'open',
			assigned_to TEXT NOT NULL DEFAULT '',
			acknowledged_at TIMESTAMPTZ,
			investigating_at TIMESTAMPTZ,
			resolved_at TIMESTAMPTZ,
			workflow_updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
			created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
		)`,
		`ALTER TABLE incidents ADD COLUMN IF NOT EXISTS problem_id TEXT NOT NULL DEFAULT ''`,
		`ALTER TABLE incidents ADD COLUMN IF NOT EXISTS project_id TEXT NOT NULL DEFAULT 'default-project'`,
		`ALTER TABLE incidents ADD COLUMN IF NOT EXISTS incident_type TEXT NOT NULL DEFAULT 'observed'`,
		`ALTER TABLE incidents ADD COLUMN IF NOT EXISTS predictive_confidence DOUBLE PRECISION NOT NULL DEFAULT 0`,
		`ALTER TABLE incidents ADD COLUMN IF NOT EXISTS root_cause_entity TEXT NOT NULL DEFAULT ''`,
		`ALTER TABLE incidents ADD COLUMN IF NOT EXISTS dependency_chain JSONB NOT NULL DEFAULT '[]'::jsonb`,
		`ALTER TABLE incidents ADD COLUMN IF NOT EXISTS remediation_suggestions JSONB NOT NULL DEFAULT '[]'::jsonb`,
		`ALTER TABLE incidents ADD COLUMN IF NOT EXISTS timeline_summary JSONB NOT NULL DEFAULT '[]'::jsonb`,
		`ALTER TABLE incidents ADD COLUMN IF NOT EXISTS workflow_status TEXT NOT NULL DEFAULT 'open'`,
		`ALTER TABLE incidents ADD COLUMN IF NOT EXISTS assigned_to TEXT NOT NULL DEFAULT ''`,
		`ALTER TABLE incidents ADD COLUMN IF NOT EXISTS acknowledged_at TIMESTAMPTZ`,
		`ALTER TABLE incidents ADD COLUMN IF NOT EXISTS investigating_at TIMESTAMPTZ`,
		`ALTER TABLE incidents ADD COLUMN IF NOT EXISTS resolved_at TIMESTAMPTZ`,
		`ALTER TABLE incidents ADD COLUMN IF NOT EXISTS workflow_updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()`,
		`CREATE INDEX IF NOT EXISTS incidents_service_timestamp_idx ON incidents(service, timestamp DESC)`,
		`CREATE INDEX IF NOT EXISTS incidents_project_timestamp_idx ON incidents(project_id, timestamp DESC)`,
		`CREATE INDEX IF NOT EXISTS incidents_problem_timestamp_idx ON incidents(problem_id, timestamp DESC)`,
		`CREATE TABLE IF NOT EXISTS reasoning (
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
		)`,
		`CREATE TABLE IF NOT EXISTS reasoning_requests (
			incident_id TEXT PRIMARY KEY REFERENCES incidents(incident_id) ON DELETE CASCADE,
			status TEXT NOT NULL DEFAULT 'pending',
			last_error TEXT NOT NULL DEFAULT '',
			attempts INTEGER NOT NULL DEFAULT 0,
			trigger_type TEXT NOT NULL DEFAULT 'manual',
			requested_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
			started_at TIMESTAMPTZ,
			completed_at TIMESTAMPTZ,
			updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
		)`,
		`CREATE INDEX IF NOT EXISTS reasoning_requests_status_idx ON reasoning_requests(status, requested_at DESC)`,
		`ALTER TABLE reasoning ADD COLUMN IF NOT EXISTS root_cause_service TEXT NOT NULL DEFAULT ''`,
		`ALTER TABLE reasoning ADD COLUMN IF NOT EXISTS root_cause_signal TEXT NOT NULL DEFAULT ''`,
		`ALTER TABLE reasoning ADD COLUMN IF NOT EXISTS confidence_explanation JSONB NOT NULL DEFAULT '{}'::jsonb`,
		`ALTER TABLE reasoning ADD COLUMN IF NOT EXISTS propagation_path JSONB NOT NULL DEFAULT '[]'::jsonb`,
		`ALTER TABLE reasoning ADD COLUMN IF NOT EXISTS customer_impact TEXT NOT NULL DEFAULT ''`,
		`ALTER TABLE reasoning ADD COLUMN IF NOT EXISTS missing_telemetry_signals JSONB NOT NULL DEFAULT '[]'::jsonb`,
		`ALTER TABLE reasoning ADD COLUMN IF NOT EXISTS observability_score DOUBLE PRECISION NOT NULL DEFAULT 0`,
		`ALTER TABLE reasoning ADD COLUMN IF NOT EXISTS observability_summary JSONB NOT NULL DEFAULT '{}'::jsonb`,
		`ALTER TABLE reasoning ADD COLUMN IF NOT EXISTS deployment_correlation TEXT NOT NULL DEFAULT ''`,
		`ALTER TABLE reasoning ADD COLUMN IF NOT EXISTS historical_matches JSONB NOT NULL DEFAULT '[]'::jsonb`,
		`ALTER TABLE reasoning_requests ADD COLUMN IF NOT EXISTS trigger_type TEXT NOT NULL DEFAULT 'manual'`,
		`CREATE TABLE IF NOT EXISTS reasoning_runs (
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
		)`,
		`CREATE INDEX IF NOT EXISTS reasoning_runs_incident_idx ON reasoning_runs(incident_id, started_at DESC)`,
		`CREATE TABLE IF NOT EXISTS incident_knowledge_base (
			incident_id TEXT PRIMARY KEY REFERENCES incidents(incident_id) ON DELETE CASCADE,
			fingerprint TEXT NOT NULL,
			root_cause_service TEXT NOT NULL DEFAULT '',
			root_cause_signal TEXT NOT NULL DEFAULT '',
			summary TEXT NOT NULL DEFAULT '',
			created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
		)`,
		`CREATE TABLE IF NOT EXISTS dependency_graphs (
			cluster TEXT NOT NULL,
			namespace TEXT NOT NULL,
			graph JSONB NOT NULL DEFAULT '{"nodes":[],"edges":[]}'::jsonb,
			updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
			PRIMARY KEY (cluster, namespace)
		)`,
		`CREATE TABLE IF NOT EXISTS service_dependencies (
			project_id TEXT NOT NULL,
			cluster TEXT NOT NULL,
			namespace TEXT NOT NULL,
			source_service TEXT NOT NULL,
			target_service TEXT NOT NULL,
			edge_type TEXT NOT NULL DEFAULT 'trace',
			dependency_type TEXT NOT NULL DEFAULT 'trace_parent_child',
			destination_name TEXT NOT NULL DEFAULT '',
			confidence DOUBLE PRECISION NOT NULL DEFAULT 0.5,
			call_count BIGINT NOT NULL DEFAULT 0,
			avg_latency_ms DOUBLE PRECISION NOT NULL DEFAULT 0,
			error_rate DOUBLE PRECISION NOT NULL DEFAULT 0,
			first_seen TIMESTAMPTZ NOT NULL DEFAULT NOW(),
			last_seen TIMESTAMPTZ NOT NULL DEFAULT NOW(),
			PRIMARY KEY (project_id, cluster, namespace, source_service, target_service, dependency_type, destination_name)
		)`,
		`ALTER TABLE service_dependencies ADD COLUMN IF NOT EXISTS edge_type TEXT NOT NULL DEFAULT 'trace'`,
		`ALTER TABLE service_dependencies ADD COLUMN IF NOT EXISTS confidence DOUBLE PRECISION NOT NULL DEFAULT 0.5`,
		`CREATE TABLE IF NOT EXISTS incident_impacts (
			incident_id TEXT NOT NULL REFERENCES incidents(incident_id) ON DELETE CASCADE,
			service TEXT NOT NULL,
			impact_type TEXT NOT NULL,
			impact_score DOUBLE PRECISION NOT NULL DEFAULT 0,
			created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
			PRIMARY KEY (incident_id, service, impact_type)
		)`,
		`CREATE INDEX IF NOT EXISTS incident_impacts_service_idx ON incident_impacts(service, created_at DESC)`,
		`CREATE TABLE IF NOT EXISTS services_registry (
			project_id TEXT NOT NULL,
			cluster TEXT NOT NULL,
			namespace TEXT NOT NULL,
			service_name TEXT NOT NULL,
			service_type TEXT NOT NULL DEFAULT '',
			deployment TEXT NOT NULL DEFAULT '',
			telemetry_status TEXT NOT NULL DEFAULT 'unknown',
			first_seen TIMESTAMPTZ NOT NULL DEFAULT NOW(),
			last_seen TIMESTAMPTZ NOT NULL DEFAULT NOW(),
			telemetry_sources JSONB NOT NULL DEFAULT '[]'::jsonb,
			PRIMARY KEY (project_id, cluster, namespace, service_name)
		)`,
		`ALTER TABLE services_registry ADD COLUMN IF NOT EXISTS service_type TEXT NOT NULL DEFAULT ''`,
		`ALTER TABLE services_registry ADD COLUMN IF NOT EXISTS deployment TEXT NOT NULL DEFAULT ''`,
		`ALTER TABLE services_registry ADD COLUMN IF NOT EXISTS telemetry_status TEXT NOT NULL DEFAULT 'unknown'`,
		`CREATE TABLE IF NOT EXISTS problems (
			problem_id TEXT PRIMARY KEY,
			project_id TEXT NOT NULL DEFAULT 'default-project',
			cluster TEXT NOT NULL DEFAULT '',
			namespace TEXT NOT NULL DEFAULT '',
			root_cause_service TEXT NOT NULL DEFAULT '',
			affected_services JSONB NOT NULL DEFAULT '[]'::jsonb,
			incident_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
			change_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
			confidence DOUBLE PRECISION NOT NULL DEFAULT 0,
			created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
			resolved_at TIMESTAMPTZ
		)`,
		`ALTER TABLE problems ADD COLUMN IF NOT EXISTS change_ids JSONB NOT NULL DEFAULT '[]'::jsonb`,
		`CREATE INDEX IF NOT EXISTS problems_project_created_idx ON problems(project_id, created_at DESC)`,
		`CREATE TABLE IF NOT EXISTS service_states (
			project_id TEXT NOT NULL,
			cluster TEXT NOT NULL,
			namespace TEXT NOT NULL,
			service_name TEXT NOT NULL,
			cpu_utilization DOUBLE PRECISION NOT NULL DEFAULT 0,
			memory_utilization DOUBLE PRECISION NOT NULL DEFAULT 0,
			latency_p95 DOUBLE PRECISION NOT NULL DEFAULT 0,
			error_rate DOUBLE PRECISION NOT NULL DEFAULT 0,
			dependency_impact DOUBLE PRECISION NOT NULL DEFAULT 0,
			health_score DOUBLE PRECISION NOT NULL DEFAULT 100,
			timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),
			PRIMARY KEY (project_id, cluster, namespace, service_name, timestamp)
		)`,
		`CREATE INDEX IF NOT EXISTS service_states_latest_idx ON service_states(project_id, cluster, namespace, service_name, timestamp DESC)`,
		`CREATE TABLE IF NOT EXISTS cluster_resources (
			cluster_id TEXT NOT NULL,
			namespace TEXT NOT NULL,
			resource_type TEXT NOT NULL,
			resource_name TEXT NOT NULL,
			replicas INTEGER NOT NULL DEFAULT 0,
			status TEXT NOT NULL DEFAULT '',
			node TEXT NOT NULL DEFAULT '',
			updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
			PRIMARY KEY (cluster_id, namespace, resource_type, resource_name)
		)`,
		`CREATE TABLE IF NOT EXISTS problem_alerts (
			problem_id TEXT NOT NULL,
			target_type TEXT NOT NULL,
			target TEXT NOT NULL,
			payload JSONB NOT NULL DEFAULT '{}'::jsonb,
			status TEXT NOT NULL DEFAULT 'pending',
			created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
			PRIMARY KEY (problem_id, target_type, target)
		)`,
		`CREATE TABLE IF NOT EXISTS system_changes (
			change_id TEXT PRIMARY KEY,
			cluster_id TEXT NOT NULL,
			namespace TEXT NOT NULL,
			resource_type TEXT NOT NULL,
			resource_name TEXT NOT NULL,
			change_type TEXT NOT NULL,
			timestamp TIMESTAMPTZ NOT NULL,
			metadata JSONB NOT NULL DEFAULT '{}'::jsonb
		)`,
		`CREATE INDEX IF NOT EXISTS system_changes_recent_idx ON system_changes(cluster_id, namespace, timestamp DESC)`,
		`CREATE TABLE IF NOT EXISTS service_slos (
			service_name TEXT NOT NULL,
			slo_type TEXT NOT NULL,
			target_value DOUBLE PRECISION NOT NULL,
			window_duration TEXT NOT NULL DEFAULT '24h',
			PRIMARY KEY (service_name, slo_type)
		)`,
		`CREATE TABLE IF NOT EXISTS runbooks (
			runbook_id TEXT PRIMARY KEY,
			incident_type TEXT NOT NULL,
			root_cause_signal TEXT NOT NULL,
			steps JSONB NOT NULL DEFAULT '[]'::jsonb,
			created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
		)`,
		`CREATE TABLE IF NOT EXISTS graph_nodes (
			project_id TEXT NOT NULL,
			cluster TEXT NOT NULL,
			namespace TEXT NOT NULL,
			node_id TEXT NOT NULL,
			node_type TEXT NOT NULL,
			metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
			first_seen TIMESTAMPTZ NOT NULL DEFAULT NOW(),
			last_seen TIMESTAMPTZ NOT NULL DEFAULT NOW(),
			PRIMARY KEY (project_id, cluster, namespace, node_id, node_type)
		)`,
		`CREATE TABLE IF NOT EXISTS graph_edges (
			project_id TEXT NOT NULL,
			cluster TEXT NOT NULL,
			namespace TEXT NOT NULL,
			source_node TEXT NOT NULL,
			target_node TEXT NOT NULL,
			edge_type TEXT NOT NULL,
			confidence DOUBLE PRECISION NOT NULL DEFAULT 0.5,
			metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
			first_seen TIMESTAMPTZ NOT NULL DEFAULT NOW(),
			last_seen TIMESTAMPTZ NOT NULL DEFAULT NOW(),
			PRIMARY KEY (project_id, cluster, namespace, source_node, target_node, edge_type)
		)`,
		`CREATE TABLE IF NOT EXISTS incident_graph_nodes (
			incident_id TEXT NOT NULL,
			node_id TEXT NOT NULL,
			node_type TEXT NOT NULL,
			metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
			created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
			PRIMARY KEY (incident_id, node_id, node_type)
		)`,
		`CREATE TABLE IF NOT EXISTS incident_graph_edges (
			incident_id TEXT NOT NULL,
			source_node TEXT NOT NULL,
			target_node TEXT NOT NULL,
			edge_type TEXT NOT NULL,
			metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
			created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
			PRIMARY KEY (incident_id, source_node, target_node, edge_type)
		)`,
		`CREATE TABLE IF NOT EXISTS service_baselines (
			project_id TEXT NOT NULL,
			cluster TEXT NOT NULL,
			namespace TEXT NOT NULL,
			service_name TEXT NOT NULL,
			window_type TEXT NOT NULL,
			metric_name TEXT NOT NULL,
			baseline_mean DOUBLE PRECISION NOT NULL DEFAULT 0,
			baseline_stddev DOUBLE PRECISION NOT NULL DEFAULT 0,
			sample_count BIGINT NOT NULL DEFAULT 0,
			updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
			PRIMARY KEY (project_id, cluster, namespace, service_name, window_type, metric_name)
		)`,
		`CREATE TABLE IF NOT EXISTS service_metric_baselines (
			project_id TEXT NOT NULL,
			cluster TEXT NOT NULL,
			namespace TEXT NOT NULL,
			service TEXT NOT NULL,
			metric TEXT NOT NULL,
			hour_of_day INTEGER NOT NULL,
			day_of_week INTEGER NOT NULL,
			baseline_value DOUBLE PRECISION NOT NULL DEFAULT 0,
			variance DOUBLE PRECISION NOT NULL DEFAULT 0,
			sample_count BIGINT NOT NULL DEFAULT 0,
			updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
			PRIMARY KEY (project_id, cluster, namespace, service, metric, hour_of_day, day_of_week)
		)`,
		`CREATE INDEX IF NOT EXISTS service_metric_baselines_lookup_idx ON service_metric_baselines(project_id, cluster, namespace, service, metric, updated_at DESC)`,
		`CREATE INDEX IF NOT EXISTS graph_edges_recent_idx ON graph_edges(project_id, cluster, namespace, last_seen DESC)`,
		`CREATE INDEX IF NOT EXISTS incident_graph_edges_incident_idx ON incident_graph_edges(incident_id, created_at DESC)`,
		`CREATE INDEX IF NOT EXISTS service_dependencies_recent_idx ON service_dependencies(project_id, cluster, namespace, last_seen DESC)`,
		`UPDATE incidents SET namespace = 'default' WHERE namespace = ''`,
		`UPDATE incidents SET cluster = 'default-cluster' WHERE cluster = ''`,
		`UPDATE service_states SET namespace = 'default' WHERE namespace = ''`,
		`UPDATE service_states SET cluster = 'default-cluster' WHERE cluster = ''`,
		`UPDATE problems SET namespace = 'default' WHERE namespace = ''`,
		`UPDATE problems SET cluster = 'default-cluster' WHERE cluster = ''`,
		`UPDATE services_registry SET namespace = 'default' WHERE namespace = ''`,
		`UPDATE services_registry SET cluster = 'default-cluster' WHERE cluster = ''`,
	}

	for _, statement := range statements {
		if _, err := s.pool.Exec(ctx, statement); err != nil {
			return err
		}
	}
	return nil
}

func (s *Store) UpsertDependencyGraph(ctx context.Context, cluster, namespace string, graph clickhouse.TopologyGraph) error {
	graphJSON, err := json.Marshal(graph)
	if err != nil {
		return err
	}
	_, err = s.pool.Exec(ctx, `
		INSERT INTO dependency_graphs (cluster, namespace, graph, updated_at)
		VALUES ($1, $2, $3, NOW())
		ON CONFLICT (cluster, namespace) DO UPDATE
		SET graph = EXCLUDED.graph, updated_at = NOW()
	`, cluster, namespace, graphJSON)
	return err
}

func (s *Store) GetDependencyGraph(ctx context.Context, cluster, namespace string) (*clickhouse.TopologyGraph, error) {
	var graphJSON []byte
	err := s.pool.QueryRow(ctx, `
		SELECT graph
		FROM dependency_graphs
		WHERE cluster = $1 AND namespace = $2
	`, cluster, namespace).Scan(&graphJSON)
	if err != nil {
		return nil, err
	}
	var graph clickhouse.TopologyGraph
	if unmarshalErr := json.Unmarshal(graphJSON, &graph); unmarshalErr != nil {
		return nil, unmarshalErr
	}
	return &graph, nil
}

func (s *Store) ReplaceServiceDependencies(ctx context.Context, projectID, cluster, namespace string, edges []clickhouse.TopologyEdge) error {
	tx, err := s.pool.Begin(ctx)
	if err != nil {
		return err
	}
	defer tx.Rollback(ctx)
	for _, edge := range edges {
		if edge.Source == "" || edge.Target == "" {
			continue
		}
		if _, err := tx.Exec(ctx, `
			INSERT INTO service_dependencies (
				project_id, cluster, namespace, source_service, target_service, edge_type, dependency_type, destination_name, confidence,
				call_count, avg_latency_ms, error_rate, first_seen, last_seen
			) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,NOW(),NOW())
			ON CONFLICT (project_id, cluster, namespace, source_service, target_service, dependency_type, destination_name) DO UPDATE
			SET
				edge_type = EXCLUDED.edge_type,
				confidence = GREATEST(service_dependencies.confidence, EXCLUDED.confidence),
				call_count = EXCLUDED.call_count,
				avg_latency_ms = EXCLUDED.avg_latency_ms,
				error_rate = EXCLUDED.error_rate,
				last_seen = NOW()
		`, projectID, cluster, namespace, edge.Source, edge.Target, edgeType(edge.DependencyType), defaultDependencyType(edge.DependencyType), edge.Destination, dependencyConfidence(edge.DependencyType), edge.CallCount, edge.AvgLatencyMs, edge.ErrorRate); err != nil {
			return err
		}
	}
	if _, err := tx.Exec(ctx, `
		DELETE FROM service_dependencies
		WHERE project_id = $1 AND cluster = $2 AND namespace = $3
		  AND last_seen < NOW() - INTERVAL '24 hours'
	`, projectID, cluster, namespace); err != nil {
		return err
	}
	return tx.Commit(ctx)
}

func (s *Store) InsertIncident(ctx context.Context, incident Incident) error {
	snapshotJSON, err := json.Marshal(incident.TelemetrySnapshot)
	if err != nil {
		return err
	}
	signalsJSON, err := json.Marshal(incident.Signals)
	if err != nil {
		return err
	}
	dependencyJSON, err := json.Marshal(incident.DependencyChain)
	if err != nil {
		return err
	}
	remediationJSON, err := json.Marshal(incident.RemediationSuggestions)
	if err != nil {
		return err
	}
	timelineJSON, err := json.Marshal(incident.TimelineSummary)
	if err != nil {
		return err
	}
	_, err = s.pool.Exec(ctx, `
		INSERT INTO incidents (
			incident_id, project_id, problem_id, incident_type, predictive_confidence, cluster, namespace, service, timestamp, severity,
			anomaly_score, telemetry_snapshot, detector_signals, root_cause_entity,
			dependency_chain, remediation_suggestions, timeline_summary
		) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17)
	`, incident.ID, defaultProjectID(incident.ProjectID), incident.ProblemID, defaultIncidentType(incident.IncidentType), incident.PredictiveConfidence, incident.Cluster, incident.Namespace, incident.Service, incident.Timestamp, incident.Severity,
		incident.AnomalyScore, snapshotJSON, signalsJSON, incident.RootCauseEntity, dependencyJSON, remediationJSON, timelineJSON)
	return err
}

func (s *Store) HasRecentIncident(ctx context.Context, cluster, namespace, service string, within time.Duration) (bool, error) {
	var count int
	err := s.pool.QueryRow(ctx, `
		SELECT count(*)
		FROM incidents
		WHERE cluster = $1 AND namespace = $2 AND service = $3 AND timestamp >= NOW() - $4::interval
	`, cluster, namespace, service, within.String()).Scan(&count)
	return count > 0, err
}

func (s *Store) ListIncidents(ctx context.Context, filters QueryFilters) ([]Incident, error) {
	limit := filters.Limit
	if limit <= 0 {
		limit = 100
	}

	rows, err := s.pool.Query(ctx, `
		SELECT
			i.incident_id, i.project_id, i.problem_id, i.incident_type, i.predictive_confidence, i.cluster, i.namespace, i.service, i.timestamp, i.severity, i.anomaly_score,
			i.telemetry_snapshot, i.detector_signals, i.root_cause_entity, i.dependency_chain,
			i.remediation_suggestions, i.timeline_summary,
			i.workflow_status, i.assigned_to, i.acknowledged_at, i.investigating_at, i.resolved_at, i.workflow_updated_at,
			r.incident_id, r.root_cause, r.root_cause_service, r.root_cause_signal, r.confidence_score, r.confidence_explanation,
			r.causal_chain, r.correlated_signals, r.propagation_path, r.impact_assessment,
			r.customer_impact, r.recommended_actions, r.missing_telemetry_signals,
			r.observability_score, r.observability_summary, r.deployment_correlation, r.historical_matches,
			r.severity, r.created_at,
			rr.status, rr.last_error, rr.requested_at, rr.updated_at
		FROM incidents i
		LEFT JOIN reasoning r ON r.incident_id = i.incident_id
		LEFT JOIN reasoning_requests rr ON rr.incident_id = i.incident_id
		WHERE ($1 = '' OR i.project_id = $1)
		  AND ($2 = '' OR i.cluster = $2)
		  AND ($3 = '' OR i.namespace = $3)
		  AND (
		    $4 = '' OR
		    i.service = $4 OR
		    i.root_cause_entity = $4
		  )
		  AND ($5 = '' OR i.problem_id = $5)
		  AND ($6::timestamptz IS NULL OR i.timestamp >= $6)
		  AND ($7::timestamptz IS NULL OR i.timestamp <= $7)
		ORDER BY i.timestamp DESC
		LIMIT $8
	`, filters.ProjectID, filters.Cluster, filters.Namespace, filters.Service, filters.ProblemID, filters.Start, filters.End, limit)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	items := make([]Incident, 0)
	for rows.Next() {
		item, err := scanIncident(rows)
		if err != nil {
			return nil, err
		}
		items = append(items, item)
	}
	if err := s.attachIncidentImpacts(ctx, items); err != nil {
		return nil, err
	}
	return items, rows.Err()
}

func (s *Store) GetIncident(ctx context.Context, incidentID string) (*Incident, error) {
	rows, err := s.pool.Query(ctx, `
		SELECT
			i.incident_id, i.project_id, i.problem_id, i.incident_type, i.predictive_confidence, i.cluster, i.namespace, i.service, i.timestamp, i.severity, i.anomaly_score,
			i.telemetry_snapshot, i.detector_signals, i.root_cause_entity, i.dependency_chain,
			i.remediation_suggestions, i.timeline_summary,
			i.workflow_status, i.assigned_to, i.acknowledged_at, i.investigating_at, i.resolved_at, i.workflow_updated_at,
			r.incident_id, r.root_cause, r.root_cause_service, r.root_cause_signal, r.confidence_score, r.confidence_explanation,
			r.causal_chain, r.correlated_signals, r.propagation_path, r.impact_assessment,
			r.customer_impact, r.recommended_actions, r.missing_telemetry_signals,
			r.observability_score, r.observability_summary, r.deployment_correlation, r.historical_matches,
			r.severity, r.created_at,
			rr.status, rr.last_error, rr.requested_at, rr.updated_at
		FROM incidents i
		LEFT JOIN reasoning r ON r.incident_id = i.incident_id
		LEFT JOIN reasoning_requests rr ON rr.incident_id = i.incident_id
		WHERE i.incident_id = $1
	`, incidentID)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	if !rows.Next() {
		return nil, nil
	}
	item, err := scanIncident(rows)
	if err != nil {
		return nil, err
	}
	impacts, err := s.loadIncidentImpacts(ctx, item.ID)
	if err != nil {
		return nil, err
	}
	item.Impacts = impacts
	return &item, rows.Err()
}

func (s *Store) DistinctFilters(ctx context.Context) (map[string][]string, error) {
	rows, err := s.pool.Query(ctx, `
		WITH combined AS (
			SELECT cluster, namespace, service AS service_name
			FROM incidents
			UNION ALL
			SELECT cluster, namespace, service_name
			FROM services_registry
			UNION ALL
			SELECT cluster_id AS cluster, namespace, resource_name AS service_name
			FROM cluster_resources
			WHERE resource_type = 'service'
		)
		SELECT DISTINCT cluster, namespace, service_name
		FROM combined
		ORDER BY cluster, namespace, service_name
	`)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	clusterSet := map[string]struct{}{}
	namespaceSet := map[string]struct{}{}
	serviceSet := map[string]struct{}{}
	for rows.Next() {
		var cluster, namespace, service string
		if err := rows.Scan(&cluster, &namespace, &service); err != nil {
			return nil, err
		}
		if cluster != "" {
			clusterSet[cluster] = struct{}{}
		}
		if namespace != "" {
			namespaceSet[namespace] = struct{}{}
		}
		if service != "" {
			serviceSet[service] = struct{}{}
		}
	}
	return map[string][]string{
		"clusters":   mapKeys(clusterSet),
		"namespaces": mapKeys(namespaceSet),
		"services":   mapKeys(serviceSet),
	}, nil
}

type rowScanner interface {
	Scan(dest ...any) error
}

func scanIncident(scanner rowScanner) (Incident, error) {
	var item Incident
	var snapshotJSON, signalsJSON, dependencyJSON, remediationJSON, timelineJSON []byte
	var reasoningID *string
	var rootCause, rootCauseService, rootCauseSignal, impact, customerImpact, severity, deploymentCorrelation *string
	var confidence, observabilityScore *float64
	var confidenceExplanationJSON, causalJSON, correlatedJSON, propagationJSON, actionsJSON, missingSignalsJSON, observabilitySummaryJSON, historicalMatchesJSON []byte
	var createdAt *time.Time
	var reasoningStatus, reasoningError *string
	var reasoningRequestedAt, reasoningUpdatedAt *time.Time
	var workflowStatus, assignedTo *string
	var acknowledgedAt, investigatingAt, resolvedAt, workflowUpdatedAt *time.Time

	err := scanner.Scan(
		&item.ID, &item.ProjectID, &item.ProblemID, &item.IncidentType, &item.PredictiveConfidence, &item.Cluster, &item.Namespace, &item.Service, &item.Timestamp, &item.Severity, &item.AnomalyScore,
		&snapshotJSON, &signalsJSON, &item.RootCauseEntity, &dependencyJSON, &remediationJSON, &timelineJSON,
		&workflowStatus, &assignedTo, &acknowledgedAt, &investigatingAt, &resolvedAt, &workflowUpdatedAt,
		&reasoningID, &rootCause, &rootCauseService, &rootCauseSignal, &confidence, &confidenceExplanationJSON,
		&causalJSON, &correlatedJSON, &propagationJSON, &impact,
		&customerImpact, &actionsJSON, &missingSignalsJSON,
		&observabilityScore, &observabilitySummaryJSON, &deploymentCorrelation, &historicalMatchesJSON,
		&severity, &createdAt,
		&reasoningStatus, &reasoningError, &reasoningRequestedAt, &reasoningUpdatedAt,
	)
	if err != nil {
		return Incident{}, err
	}

	_ = json.Unmarshal(snapshotJSON, &item.TelemetrySnapshot)
	_ = json.Unmarshal(signalsJSON, &item.Signals)
	_ = json.Unmarshal(dependencyJSON, &item.DependencyChain)
	_ = json.Unmarshal(remediationJSON, &item.RemediationSuggestions)
	_ = json.Unmarshal(timelineJSON, &item.TimelineSummary)
	item.RootCauseEntity = normalizeIncidentEntity(item.RootCauseEntity)
	item.DependencyChain = normalizeIncidentEntities(item.DependencyChain)

	if reasoningID != nil {
		reasoning := Reasoning{
			IncidentID:            *reasoningID,
			RootCause:             derefString(rootCause),
			RootCauseService:      derefString(rootCauseService),
			RootCauseSignal:       derefString(rootCauseSignal),
			ConfidenceScore:       derefFloat(confidence),
			ImpactAssessment:      derefString(impact),
			CustomerImpact:        derefString(customerImpact),
			ObservabilityScore:    derefFloat(observabilityScore),
			DeploymentCorrelation: derefString(deploymentCorrelation),
			Severity:              derefString(severity),
			CreatedAt:             derefTime(createdAt),
			ObservabilitySummary:  map[string]string{},
			ConfidenceExplanation: map[string]any{},
		}
		_ = json.Unmarshal(confidenceExplanationJSON, &reasoning.ConfidenceExplanation)
		_ = json.Unmarshal(causalJSON, &reasoning.CausalChain)
		_ = json.Unmarshal(correlatedJSON, &reasoning.CorrelatedSignals)
		_ = json.Unmarshal(propagationJSON, &reasoning.PropagationPath)
		_ = json.Unmarshal(actionsJSON, &reasoning.RecommendedActions)
		_ = json.Unmarshal(missingSignalsJSON, &reasoning.MissingTelemetrySignals)
		_ = json.Unmarshal(observabilitySummaryJSON, &reasoning.ObservabilitySummary)
		_ = json.Unmarshal(historicalMatchesJSON, &reasoning.HistoricalMatches)
		reasoning.RootCauseService = normalizeIncidentEntity(reasoning.RootCauseService)
		item.Reasoning = &reasoning
	}
	if reasoningStatus != nil {
		item.ReasoningStatus = *reasoningStatus
	}
	if reasoningError != nil {
		item.ReasoningError = *reasoningError
	}
	item.ReasoningRequestedAt = reasoningRequestedAt
	item.ReasoningUpdatedAt = reasoningUpdatedAt
	if workflowStatus != nil {
		item.WorkflowStatus = *workflowStatus
	}
	if assignedTo != nil {
		item.AssignedTo = *assignedTo
	}
	item.AcknowledgedAt = acknowledgedAt
	item.InvestigatingAt = investigatingAt
	item.ResolvedAt = resolvedAt
	item.WorkflowUpdatedAt = workflowUpdatedAt
	if item.WorkflowStatus == "" {
		item.WorkflowStatus = "open"
	}
	if item.ReasoningStatus == "" {
		if item.Reasoning != nil {
			item.ReasoningStatus = "completed"
		} else {
			item.ReasoningStatus = "not_generated"
		}
	}
	return item, nil
}

func (s *Store) CreateReasoningRequest(ctx context.Context, incidentID, triggerType string) (*ReasoningRequest, error) {
	var hasReasoning bool
	if err := s.pool.QueryRow(ctx, `SELECT EXISTS(SELECT 1 FROM reasoning WHERE incident_id = $1)`, incidentID).Scan(&hasReasoning); err != nil {
		return nil, err
	}
	if hasReasoning && triggerType != "retry" {
		return &ReasoningRequest{
			IncidentID: incidentID,
			Status:     "completed",
			TriggerType: triggerType,
		}, nil
	}

	row := s.pool.QueryRow(ctx, `
		INSERT INTO reasoning_requests (
			incident_id, status, last_error, attempts, trigger_type, requested_at, updated_at
		) VALUES ($1, 'pending', '', 0, $2, NOW(), NOW())
		ON CONFLICT (incident_id) DO UPDATE
		SET
			status = 'pending',
			last_error = '',
			trigger_type = EXCLUDED.trigger_type,
			requested_at = NOW(),
			updated_at = NOW()
		RETURNING incident_id, status, last_error, attempts, trigger_type, requested_at, started_at, completed_at, updated_at
	`, incidentID, triggerType)
	var req ReasoningRequest
	if err := row.Scan(&req.IncidentID, &req.Status, &req.LastError, &req.Attempts, &req.TriggerType, &req.RequestedAt, &req.StartedAt, &req.CompletedAt, &req.UpdatedAt); err != nil {
		return nil, err
	}
	return &req, nil
}

type WorkflowUpdate struct {
	Status         string     `json:"status"`
	AssignedTo     string     `json:"assigned_to"`
	AcknowledgedAt *time.Time `json:"acknowledged_at,omitempty"`
	InvestigatingAt *time.Time `json:"investigating_at,omitempty"`
	ResolvedAt     *time.Time `json:"resolved_at,omitempty"`
	WorkflowUpdatedAt *time.Time `json:"workflow_updated_at,omitempty"`
}

func (s *Store) UpdateWorkflow(ctx context.Context, incidentID string, update WorkflowUpdate) (*Incident, error) {
	_, err := s.pool.Exec(ctx, `
		UPDATE incidents
		SET
			workflow_status = COALESCE(NULLIF($2, ''), workflow_status),
			assigned_to = COALESCE($3, assigned_to),
			acknowledged_at = COALESCE($4, acknowledged_at),
			investigating_at = COALESCE($5, investigating_at),
			resolved_at = COALESCE($6, resolved_at),
			workflow_updated_at = COALESCE($7, workflow_updated_at)
		WHERE incident_id = $1
	`, incidentID, update.Status, update.AssignedTo, update.AcknowledgedAt, update.InvestigatingAt, update.ResolvedAt, update.WorkflowUpdatedAt)
	if err != nil {
		return nil, err
	}
	return s.GetIncident(ctx, incidentID)
}

func (s *Store) ListReasoningRuns(ctx context.Context, incidentID string, limit int) ([]ReasoningRun, error) {
	if limit <= 0 || limit > 50 {
		limit = 20
	}
	rows, err := s.pool.Query(ctx, `
		SELECT
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
		FROM reasoning_runs
		WHERE incident_id = $1
		ORDER BY started_at DESC
		LIMIT $2
	`, incidentID, limit)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	items := []ReasoningRun{}
	for rows.Next() {
		var item ReasoningRun
		var actionsJSON, propagationJSON, evidenceJSON, confidenceJSON []byte
		if err := rows.Scan(
			&item.RunID,
			&item.IncidentID,
			&item.Status,
			&item.Provider,
			&item.Model,
			&item.TriggerType,
			&item.ErrorMessage,
			&item.Summary,
			&item.RootCauseService,
			&item.RootCauseSignal,
			&item.RootCauseConfidence,
			&actionsJSON,
			&propagationJSON,
			&evidenceJSON,
			&confidenceJSON,
			&item.CorrelationSummary,
			&item.StartedAt,
			&item.CompletedAt,
		); err != nil {
			return nil, err
		}
		_ = json.Unmarshal(actionsJSON, &item.SuggestedActions)
		_ = json.Unmarshal(propagationJSON, &item.PropagationPath)
		_ = json.Unmarshal(evidenceJSON, &item.EvidenceSnapshot)
		_ = json.Unmarshal(confidenceJSON, &item.ConfidenceExplanation)
		items = append(items, item)
	}
	return items, rows.Err()
}

func (s *Store) GetReasoningRun(ctx context.Context, incidentID, runID string) (*ReasoningRun, error) {
	row := s.pool.QueryRow(ctx, `
		SELECT
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
		FROM reasoning_runs
		WHERE incident_id = $1 AND reasoning_run_id = $2
	`, incidentID, runID)
	var item ReasoningRun
	var actionsJSON, propagationJSON, evidenceJSON, confidenceJSON []byte
	if err := row.Scan(
		&item.RunID,
		&item.IncidentID,
		&item.Status,
		&item.Provider,
		&item.Model,
		&item.TriggerType,
		&item.ErrorMessage,
		&item.Summary,
		&item.RootCauseService,
		&item.RootCauseSignal,
		&item.RootCauseConfidence,
		&actionsJSON,
		&propagationJSON,
		&evidenceJSON,
		&confidenceJSON,
		&item.CorrelationSummary,
		&item.StartedAt,
		&item.CompletedAt,
	); err != nil {
		return nil, err
	}
	_ = json.Unmarshal(actionsJSON, &item.SuggestedActions)
	_ = json.Unmarshal(propagationJSON, &item.PropagationPath)
	_ = json.Unmarshal(evidenceJSON, &item.EvidenceSnapshot)
	_ = json.Unmarshal(confidenceJSON, &item.ConfidenceExplanation)
	return &item, nil
}

func (s *Store) ListCorrelatedIncidents(ctx context.Context, incidentID string, window time.Duration, limit int) ([]CorrelatedIncident, error) {
	if limit <= 0 || limit > 20 {
		limit = 8
	}
	current, err := s.GetIncident(ctx, incidentID)
	if err != nil || current == nil {
		return []CorrelatedIncident{}, err
	}
	rootService := ""
	rootSignal := ""
	if current.Reasoning != nil {
		rootService = current.Reasoning.RootCauseService
		rootSignal = current.Reasoning.RootCauseSignal
	}
	start := current.Timestamp.Add(-window)
	end := current.Timestamp.Add(window)

	rows, err := s.pool.Query(ctx, `
		SELECT
			i.incident_id,
			i.timestamp,
			COALESCE(r.root_cause, ''),
			COALESCE(r.root_cause_service, ''),
			COALESCE(r.root_cause_signal, ''),
			i.service
		FROM incidents i
		LEFT JOIN reasoning r ON r.incident_id = i.incident_id
		WHERE i.incident_id <> $1
		  AND i.timestamp BETWEEN $2 AND $3
		  AND (
			i.service = $4 OR
			r.root_cause_service = $5 OR
			r.root_cause_signal = $6 OR
			i.namespace = $7 AND i.cluster = $8
		  )
		ORDER BY i.timestamp DESC
		LIMIT $9
	`, incidentID, start, end, current.Service, rootService, rootSignal, current.Namespace, current.Cluster, limit)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	results := []CorrelatedIncident{}
	for rows.Next() {
		var id string
		var ts time.Time
		var summary, rcService, rcSignal, svc string
		if err := rows.Scan(&id, &ts, &summary, &rcService, &rcSignal, &svc); err != nil {
			return nil, err
		}
		score := 0.0
		reasons := []string{}
		if svc != "" && svc == current.Service {
			score += 0.35
			reasons = append(reasons, "same service")
		}
		if rootService != "" && rcService == rootService {
			score += 0.35
			reasons = append(reasons, "same root cause service")
		}
		if rootSignal != "" && rcSignal == rootSignal {
			score += 0.2
			reasons = append(reasons, "same root cause signal")
		}
		if len(reasons) == 0 {
			reasons = append(reasons, "similar time window and scope")
		}
		if score == 0 {
			score = 0.15
		}
		results = append(results, CorrelatedIncident{
			IncidentID:       id,
			Timestamp:        ts,
			RootCauseSummary: summary,
			CorrelationReason: strings.Join(reasons, ", "),
			CorrelationScore: score,
		})
	}
	return results, rows.Err()
}

func mapKeys(values map[string]struct{}) []string {
	items := make([]string, 0, len(values))
	for value := range values {
		items = append(items, value)
	}
	sort.Strings(items)
	return items
}

func derefString(value *string) string {
	if value == nil {
		return ""
	}
	return *value
}

func derefFloat(value *float64) float64 {
	if value == nil {
		return 0
	}
	return *value
}

func derefTime(value *time.Time) time.Time {
	if value == nil {
		return time.Time{}
	}
	return *value
}

func defaultIncidentType(value string) string {
	if value == "" {
		return "observed"
	}
	return value
}

func defaultProjectID(value string) string {
	if value == "" {
		return "default-project"
	}
	return value
}

func normalizeIncidentEntity(value string) string {
	normalized := clickhouse.CanonicalTopologyNodeID(value)
	if strings.TrimSpace(normalized) == "" {
		return strings.TrimSpace(value)
	}
	if strings.ContainsAny(normalized, " \t\r\n") || len(normalized) > 128 || !structuredIncidentEntityPattern.MatchString(normalized) {
		return ""
	}
	return normalized
}

func normalizeIncidentEntities(values []string) []string {
	if len(values) == 0 {
		return values
	}
	out := make([]string, 0, len(values))
	for _, value := range values {
		normalized := normalizeIncidentEntity(value)
		if normalized == "" {
			continue
		}
		out = append(out, normalized)
	}
	return out
}

func defaultDependencyType(value string) string {
	if value == "" {
		return "trace_http"
	}
	return value
}

func edgeType(dependencyType string) string {
	switch dependencyType {
	case "messaging":
		return "messaging"
	case "messaging_kafka":
		return "messaging_kafka"
	case "trace_http":
		return "trace_http"
	case "trace_rpc":
		return "trace_rpc"
	case "database":
		return "database"
	case "kubernetes_dns":
		return "kubernetes_dns"
	default:
		return dependencyType
	}
}

func dependencyConfidence(dependencyType string) float64 {
	switch dependencyType {
	case "trace_rpc":
		return 0.95
	case "trace_http":
		return 0.9
	case "messaging":
		return 0.9
	case "messaging_kafka":
		return 0.9
	case "database":
		return 0.85
	case "kubernetes_dns":
		return 0.7
	default:
		return 0.5
	}
}

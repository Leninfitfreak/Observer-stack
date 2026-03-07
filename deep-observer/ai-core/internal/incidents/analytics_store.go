package incidents

import (
	"context"
	"encoding/json"
	"time"
)

type ServiceState struct {
	ProjectID         string    `json:"project_id"`
	Cluster           string    `json:"cluster"`
	Namespace         string    `json:"namespace"`
	ServiceName       string    `json:"service_name"`
	CPUUtilization    float64   `json:"cpu_utilization"`
	MemoryUtilization float64   `json:"memory_utilization"`
	LatencyP95        float64   `json:"latency_p95"`
	ErrorRate         float64   `json:"error_rate"`
	DependencyImpact  float64   `json:"dependency_impact"`
	HealthScore       float64   `json:"health_score"`
	Timestamp         time.Time `json:"timestamp"`
}

type Problem struct {
	ProblemID        string     `json:"problem_id"`
	ProjectID        string     `json:"project_id"`
	Cluster          string     `json:"cluster"`
	Namespace        string     `json:"namespace"`
	RootCauseService string     `json:"root_cause_service"`
	AffectedServices []string   `json:"affected_services"`
	IncidentIDs      []string   `json:"incident_ids"`
	ChangeIDs        []string   `json:"change_ids"`
	Confidence       float64    `json:"confidence"`
	CreatedAt        time.Time  `json:"created_at"`
	ResolvedAt       *time.Time `json:"resolved_at,omitempty"`
}

type ClusterResource struct {
	ClusterID    string `json:"cluster_id"`
	Namespace    string `json:"namespace"`
	ResourceType string `json:"resource_type"`
	ResourceName string `json:"resource_name"`
	Replicas     int    `json:"replicas"`
	Status       string `json:"status"`
	Node         string `json:"node"`
}

type DependencyRecord struct {
	SourceService  string  `json:"source_service"`
	TargetService  string  `json:"target_service"`
	DependencyType string  `json:"dependency_type"`
	CallCount      int64   `json:"call_count"`
	AvgLatencyMs   float64 `json:"avg_latency_ms"`
	ErrorRate      float64 `json:"error_rate"`
}

type RegisteredService struct {
	ServiceName string `json:"service_name"`
	Namespace   string `json:"namespace"`
	Cluster     string `json:"cluster"`
}

func (s *Store) UpsertServiceRegistry(ctx context.Context, projectID, cluster, namespace, service string, sources []string) error {
	return s.UpsertServiceRegistryDetailed(ctx, projectID, cluster, namespace, service, "", "", telemetryStatusFromSources(sources), sources)
}

func (s *Store) UpsertServiceRegistryTyped(ctx context.Context, projectID, cluster, namespace, service, serviceType string, sources []string) error {
	return s.UpsertServiceRegistryDetailed(ctx, projectID, cluster, namespace, service, serviceType, "", telemetryStatusFromSources(sources), sources)
}

func (s *Store) UpsertServiceRegistryDetailed(ctx context.Context, projectID, cluster, namespace, service, serviceType, deployment, telemetryStatus string, sources []string) error {
	if service == "" {
		return nil
	}
	sourceJSON, err := json.Marshal(sources)
	if err != nil {
		return err
	}
	if telemetryStatus == "" {
		telemetryStatus = telemetryStatusFromSources(sources)
	}
	_, err = s.pool.Exec(ctx, `
		INSERT INTO services_registry (
			project_id, cluster, namespace, service_name, service_type, deployment, telemetry_status, first_seen, last_seen, telemetry_sources
		)
		VALUES ($1,$2,$3,$4,$5,$6,$7,NOW(),NOW(),$8)
		ON CONFLICT (project_id, cluster, namespace, service_name) DO UPDATE
		SET
			service_type = CASE
				WHEN EXCLUDED.service_type = '' THEN services_registry.service_type
				ELSE EXCLUDED.service_type
			END,
			deployment = CASE
				WHEN EXCLUDED.deployment = '' THEN services_registry.deployment
				ELSE EXCLUDED.deployment
			END,
			telemetry_status = CASE
				WHEN services_registry.telemetry_status = 'has_telemetry' THEN services_registry.telemetry_status
				WHEN EXCLUDED.telemetry_status = '' THEN services_registry.telemetry_status
				ELSE EXCLUDED.telemetry_status
			END,
			last_seen = NOW(),
			telemetry_sources = CASE
				WHEN EXCLUDED.telemetry_sources = '[]'::jsonb THEN services_registry.telemetry_sources
				ELSE EXCLUDED.telemetry_sources
			END
	`, defaultProjectID(projectID), cluster, namespace, service, serviceType, deployment, telemetryStatus, sourceJSON)
	return err
}

func telemetryStatusFromSources(sources []string) string {
	if len(sources) == 0 {
		return "missing_telemetry"
	}
	return "has_telemetry"
}

func (s *Store) InsertServiceState(ctx context.Context, state ServiceState) error {
	if state.Timestamp.IsZero() {
		state.Timestamp = time.Now().UTC()
	}
	_, err := s.pool.Exec(ctx, `
		INSERT INTO service_states (
			project_id, cluster, namespace, service_name, cpu_utilization, memory_utilization,
			latency_p95, error_rate, dependency_impact, health_score, timestamp
		) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)
	`, defaultProjectID(state.ProjectID), state.Cluster, state.Namespace, state.ServiceName, state.CPUUtilization, state.MemoryUtilization, state.LatencyP95, state.ErrorRate, state.DependencyImpact, state.HealthScore, state.Timestamp)
	return err
}

func (s *Store) UpsertProblem(ctx context.Context, problem Problem) error {
	affectedJSON, err := json.Marshal(problem.AffectedServices)
	if err != nil {
		return err
	}
	incidentJSON, err := json.Marshal(problem.IncidentIDs)
	if err != nil {
		return err
	}
	changeJSON, err := json.Marshal(problem.ChangeIDs)
	if err != nil {
		return err
	}
	if problem.CreatedAt.IsZero() {
		problem.CreatedAt = time.Now().UTC()
	}
	_, err = s.pool.Exec(ctx, `
		INSERT INTO problems (
			problem_id, project_id, cluster, namespace, root_cause_service,
			affected_services, incident_ids, change_ids, confidence, created_at, resolved_at
		) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)
		ON CONFLICT (problem_id) DO UPDATE SET
			root_cause_service = EXCLUDED.root_cause_service,
			affected_services = EXCLUDED.affected_services,
			incident_ids = EXCLUDED.incident_ids,
			change_ids = EXCLUDED.change_ids,
			confidence = GREATEST(problems.confidence, EXCLUDED.confidence)
	`, problem.ProblemID, defaultProjectID(problem.ProjectID), problem.Cluster, problem.Namespace, problem.RootCauseService, affectedJSON, incidentJSON, changeJSON, problem.Confidence, problem.CreatedAt, problem.ResolvedAt)
	return err
}

func (s *Store) ListServiceHealth(ctx context.Context, projectID, cluster, namespace, service string, limit int) ([]ServiceState, error) {
	if limit <= 0 {
		limit = 200
	}
	rows, err := s.pool.Query(ctx, `
		SELECT DISTINCT ON (project_id, cluster, namespace, service_name)
			project_id, cluster, namespace, service_name, cpu_utilization, memory_utilization,
			latency_p95, error_rate, dependency_impact, health_score, timestamp
		FROM service_states
		WHERE ($1 = '' OR project_id = $1)
		  AND ($2 = '' OR cluster = $2)
		  AND ($3 = '' OR namespace = $3)
		  AND ($4 = '' OR service_name = $4)
		ORDER BY project_id, cluster, namespace, service_name, timestamp DESC
		LIMIT $5
	`, projectID, cluster, namespace, service, limit)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	states := make([]ServiceState, 0)
	for rows.Next() {
		var state ServiceState
		if scanErr := rows.Scan(
			&state.ProjectID, &state.Cluster, &state.Namespace, &state.ServiceName, &state.CPUUtilization, &state.MemoryUtilization,
			&state.LatencyP95, &state.ErrorRate, &state.DependencyImpact, &state.HealthScore, &state.Timestamp,
		); scanErr != nil {
			return nil, scanErr
		}
		states = append(states, state)
	}
	return states, rows.Err()
}

func (s *Store) ReplaceClusterResources(ctx context.Context, clusterID string, resources []ClusterResource) error {
	tx, err := s.pool.Begin(ctx)
	if err != nil {
		return err
	}
	defer tx.Rollback(ctx)
	if _, err := tx.Exec(ctx, `DELETE FROM cluster_resources WHERE cluster_id = $1`, clusterID); err != nil {
		return err
	}
	for _, resource := range resources {
		if _, err := tx.Exec(ctx, `
			INSERT INTO cluster_resources (
				cluster_id, namespace, resource_type, resource_name, replicas, status, node, updated_at
			) VALUES ($1,$2,$3,$4,$5,$6,$7,NOW())
		`, resource.ClusterID, resource.Namespace, resource.ResourceType, resource.ResourceName, resource.Replicas, resource.Status, resource.Node); err != nil {
			return err
		}
	}
	return tx.Commit(ctx)
}

func (s *Store) BuildClusterReport(ctx context.Context, projectID, clusterID string) (map[string]any, error) {
	report := map[string]any{
		"project_id": projectID,
		"cluster_id": clusterID,
	}
	var unscoredCount int
	if err := s.pool.QueryRow(ctx, `
		SELECT count(*)
		FROM service_states
		WHERE project_id = $1 AND cluster = $2 AND health_score < 60
	`, projectID, clusterID).Scan(&unscoredCount); err != nil {
		return nil, err
	}
	var missingLimitsCount int
	if err := s.pool.QueryRow(ctx, `
		SELECT count(*)
		FROM cluster_resources
		WHERE cluster_id = $1
		  AND resource_type = 'deployment'
		  AND status ILIKE '%missing-limits%'
	`, clusterID).Scan(&missingLimitsCount); err != nil {
		return nil, err
	}
	report["at_risk_services"] = unscoredCount
	report["missing_resource_limits"] = missingLimitsCount
	report["generated_at"] = time.Now().UTC()
	return report, nil
}

func (s *Store) ListRecentDependencies(ctx context.Context, projectID, cluster, namespace string, limit int) ([]DependencyRecord, error) {
	if limit <= 0 {
		limit = 200
	}
	rows, err := s.pool.Query(ctx, `
		SELECT source_service, target_service, dependency_type, call_count, avg_latency_ms, error_rate
		FROM service_dependencies
		WHERE ($1 = '' OR project_id = $1)
		  AND ($2 = '' OR cluster = $2)
		  AND ($3 = '' OR namespace = $3)
		  AND last_seen >= NOW() - INTERVAL '24 hours'
		ORDER BY last_seen DESC
		LIMIT $4
	`, defaultProjectID(projectID), cluster, namespace, limit)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	items := []DependencyRecord{}
	for rows.Next() {
		var item DependencyRecord
		if scanErr := rows.Scan(&item.SourceService, &item.TargetService, &item.DependencyType, &item.CallCount, &item.AvgLatencyMs, &item.ErrorRate); scanErr != nil {
			return nil, scanErr
		}
		items = append(items, item)
	}
	return items, rows.Err()
}

func (s *Store) ListRegisteredServices(ctx context.Context, projectID, cluster, namespace string, limit int) ([]RegisteredService, error) {
	if limit <= 0 {
		limit = 500
	}
	rows, err := s.pool.Query(ctx, `
		SELECT service_name, namespace, cluster
		FROM services_registry
		WHERE ($1 = '' OR project_id = $1)
		  AND ($2 = '' OR cluster = $2)
		  AND ($3 = '' OR namespace = $3)
		ORDER BY service_name
		LIMIT $4
	`, defaultProjectID(projectID), cluster, namespace, limit)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	items := []RegisteredService{}
	for rows.Next() {
		var item RegisteredService
		if scanErr := rows.Scan(&item.ServiceName, &item.Namespace, &item.Cluster); scanErr != nil {
			return nil, scanErr
		}
		items = append(items, item)
	}
	return items, rows.Err()
}

func (s *Store) ListProblems(ctx context.Context, projectID, cluster, namespace, service string, limit int) ([]Problem, error) {
	if limit <= 0 {
		limit = 100
	}
	rows, err := s.pool.Query(ctx, `
		SELECT problem_id, project_id, cluster, namespace, root_cause_service, affected_services, incident_ids, change_ids, confidence, created_at, resolved_at
		FROM problems
		WHERE ($1 = '' OR project_id = $1)
		  AND ($2 = '' OR cluster = $2)
		  AND ($3 = '' OR namespace = $3)
		  AND ($4 = '' OR root_cause_service = $4 OR affected_services ? $4)
		ORDER BY created_at DESC
		LIMIT $5
	`, projectID, cluster, namespace, service, limit)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	items := []Problem{}
	for rows.Next() {
		var item Problem
		var affectedJSON, incidentJSON, changeJSON []byte
		if scanErr := rows.Scan(&item.ProblemID, &item.ProjectID, &item.Cluster, &item.Namespace, &item.RootCauseService, &affectedJSON, &incidentJSON, &changeJSON, &item.Confidence, &item.CreatedAt, &item.ResolvedAt); scanErr != nil {
			return nil, scanErr
		}
		_ = json.Unmarshal(affectedJSON, &item.AffectedServices)
		_ = json.Unmarshal(incidentJSON, &item.IncidentIDs)
		_ = json.Unmarshal(changeJSON, &item.ChangeIDs)
		items = append(items, item)
	}
	return items, rows.Err()
}

func (s *Store) QueueProblemAlert(ctx context.Context, problemID, targetType, target string, payload map[string]any) error {
	if problemID == "" || targetType == "" || target == "" {
		return nil
	}
	payloadJSON, err := json.Marshal(payload)
	if err != nil {
		return err
	}
	_, err = s.pool.Exec(ctx, `
		INSERT INTO problem_alerts (problem_id, target_type, target, payload, status, created_at)
		VALUES ($1,$2,$3,$4,'pending',NOW())
		ON CONFLICT (problem_id, target_type, target) DO NOTHING
	`, problemID, targetType, target, payloadJSON)
	return err
}

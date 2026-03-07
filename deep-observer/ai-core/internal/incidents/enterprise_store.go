package incidents

import (
	"context"
	"encoding/json"
	"time"
)

type SystemChange struct {
	ChangeID     string         `json:"change_id"`
	ClusterID    string         `json:"cluster_id"`
	Namespace    string         `json:"namespace"`
	ResourceType string         `json:"resource_type"`
	ResourceName string         `json:"resource_name"`
	ChangeType   string         `json:"change_type"`
	Timestamp    time.Time      `json:"timestamp"`
	Metadata     map[string]any `json:"metadata,omitempty"`
}

type SLOStatus struct {
	ServiceName          string  `json:"service_name"`
	SLOType              string  `json:"slo_type"`
	TargetValue          float64 `json:"target_value"`
	WindowDuration       string  `json:"window_duration"`
	SLOStatus            string  `json:"slo_status"`
	ErrorBudgetRemaining float64 `json:"error_budget_remaining"`
}

type Runbook struct {
	RunbookID       string    `json:"runbook_id"`
	IncidentType    string    `json:"incident_type"`
	RootCauseSignal string    `json:"root_cause_signal"`
	Steps           []string  `json:"steps"`
	CreatedAt       time.Time `json:"created_at"`
}

func (s *Store) UpsertSystemChange(ctx context.Context, change SystemChange) error {
	if change.ChangeID == "" {
		return nil
	}
	if change.Timestamp.IsZero() {
		change.Timestamp = time.Now().UTC()
	}
	metadataJSON, err := json.Marshal(change.Metadata)
	if err != nil {
		return err
	}
	_, err = s.pool.Exec(ctx, `
		INSERT INTO system_changes (change_id, cluster_id, namespace, resource_type, resource_name, change_type, timestamp, metadata)
		VALUES ($1,$2,$3,$4,$5,$6,$7,$8)
		ON CONFLICT (change_id) DO UPDATE
		SET
			change_type = EXCLUDED.change_type,
			timestamp = EXCLUDED.timestamp,
			metadata = EXCLUDED.metadata
	`, change.ChangeID, change.ClusterID, change.Namespace, change.ResourceType, change.ResourceName, change.ChangeType, change.Timestamp, metadataJSON)
	return err
}

func (s *Store) ListSystemChanges(ctx context.Context, clusterID, namespace string, limit int) ([]SystemChange, error) {
	if limit <= 0 {
		limit = 200
	}
	rows, err := s.pool.Query(ctx, `
		SELECT change_id, cluster_id, namespace, resource_type, resource_name, change_type, timestamp, metadata
		FROM system_changes
		WHERE ($1 = '' OR cluster_id = $1)
		  AND ($2 = '' OR namespace = $2)
		ORDER BY timestamp DESC
		LIMIT $3
	`, clusterID, namespace, limit)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	changes := []SystemChange{}
	for rows.Next() {
		var item SystemChange
		var metadataJSON []byte
		if scanErr := rows.Scan(&item.ChangeID, &item.ClusterID, &item.Namespace, &item.ResourceType, &item.ResourceName, &item.ChangeType, &item.Timestamp, &metadataJSON); scanErr != nil {
			return nil, scanErr
		}
		_ = json.Unmarshal(metadataJSON, &item.Metadata)
		changes = append(changes, item)
	}
	return changes, rows.Err()
}

func (s *Store) EnsureDefaultSLOs(ctx context.Context, service string) error {
	_, err := s.pool.Exec(ctx, `
		INSERT INTO service_slos (service_name, slo_type, target_value, window_duration)
		VALUES
			($1, 'availability', 99.9, '24h'),
			($1, 'latency_p95_ms', 300, '24h'),
			($1, 'error_rate_percent', 1, '24h')
		ON CONFLICT (service_name, slo_type) DO NOTHING
	`, service)
	return err
}

func (s *Store) ListSLOStatus(ctx context.Context, projectID, cluster, namespace string, limit int) ([]SLOStatus, error) {
	if limit <= 0 {
		limit = 300
	}
	rows, err := s.pool.Query(ctx, `
		WITH latest AS (
			SELECT DISTINCT ON (project_id, cluster, namespace, service_name)
				project_id, cluster, namespace, service_name, latency_p95, error_rate, health_score, timestamp
			FROM service_states
			WHERE ($1 = '' OR project_id = $1)
			  AND ($2 = '' OR cluster = $2)
			  AND ($3 = '' OR namespace = $3)
			ORDER BY project_id, cluster, namespace, service_name, timestamp DESC
		)
		SELECT
			s.service_name,
			s.slo_type,
			s.target_value,
			s.window_duration,
			CASE
				WHEN s.slo_type = 'latency_p95_ms' AND l.latency_p95 <= s.target_value THEN 'healthy'
				WHEN s.slo_type = 'error_rate_percent' AND (l.error_rate * 100) <= s.target_value THEN 'healthy'
				WHEN s.slo_type = 'availability' AND l.health_score >= s.target_value THEN 'healthy'
				ELSE 'violated'
			END AS slo_status,
			CASE
				WHEN s.slo_type = 'latency_p95_ms' THEN GREATEST(0, 100 - ((l.latency_p95 / NULLIF(s.target_value, 0)) * 100))
				WHEN s.slo_type = 'error_rate_percent' THEN GREATEST(0, 100 - (((l.error_rate * 100) / NULLIF(s.target_value, 0)) * 100))
				WHEN s.slo_type = 'availability' THEN GREATEST(0, (l.health_score / NULLIF(s.target_value, 0)) * 100)
				ELSE 0
			END AS error_budget_remaining
		FROM service_slos s
		INNER JOIN latest l ON l.service_name = s.service_name
		ORDER BY s.service_name, s.slo_type
		LIMIT $4
	`, projectID, cluster, namespace, limit)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	items := []SLOStatus{}
	for rows.Next() {
		var item SLOStatus
		if scanErr := rows.Scan(&item.ServiceName, &item.SLOType, &item.TargetValue, &item.WindowDuration, &item.SLOStatus, &item.ErrorBudgetRemaining); scanErr != nil {
			return nil, scanErr
		}
		items = append(items, item)
	}
	return items, rows.Err()
}

func (s *Store) ListRunbooks(ctx context.Context, incidentType, rootCauseSignal string, limit int) ([]Runbook, error) {
	if limit <= 0 {
		limit = 100
	}
	rows, err := s.pool.Query(ctx, `
		SELECT runbook_id, incident_type, root_cause_signal, steps, created_at
		FROM runbooks
		WHERE ($1 = '' OR incident_type = $1)
		  AND ($2 = '' OR root_cause_signal = $2)
		ORDER BY created_at DESC
		LIMIT $3
	`, incidentType, rootCauseSignal, limit)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	items := []Runbook{}
	for rows.Next() {
		var item Runbook
		var stepsJSON []byte
		if scanErr := rows.Scan(&item.RunbookID, &item.IncidentType, &item.RootCauseSignal, &stepsJSON, &item.CreatedAt); scanErr != nil {
			return nil, scanErr
		}
		_ = json.Unmarshal(stepsJSON, &item.Steps)
		items = append(items, item)
	}
	return items, rows.Err()
}

func (s *Store) BuildObservabilityReport(ctx context.Context, projectID, cluster string) (map[string]any, error) {
	report := map[string]any{
		"project_id": projectID,
		"cluster_id": cluster,
	}
	var discovered, withTraces, withMetrics, withLogs, missingTelemetry int
	if err := s.pool.QueryRow(ctx, `
		SELECT
			count(*) AS discovered,
			count(*) FILTER (WHERE telemetry_sources::text ILIKE '%traces%') AS with_traces,
			count(*) FILTER (WHERE telemetry_sources::text ILIKE '%metrics%') AS with_metrics,
			count(*) FILTER (WHERE telemetry_sources::text ILIKE '%logs%') AS with_logs,
			count(*) FILTER (WHERE telemetry_status = 'missing_telemetry') AS missing_telemetry
		FROM services_registry
		WHERE ($1 = '' OR project_id = $1)
		  AND ($2 = '' OR cluster = $2)
	`, projectID, cluster).Scan(&discovered, &withTraces, &withMetrics, &withLogs, &missingTelemetry); err != nil {
		return nil, err
	}
	coverageScore := 0.0
	if discovered > 0 {
		coverageScore = ((float64(withTraces) + float64(withMetrics) + float64(withLogs)) / float64(discovered*3)) * 100
	}
	recommendations := []string{}
	if withTraces < discovered {
		recommendations = append(recommendations, "Enable tracing for services without distributed traces.")
	}
	if withMetrics < discovered {
		recommendations = append(recommendations, "Enable metrics export for uncovered services.")
	}
	if withLogs < discovered {
		recommendations = append(recommendations, "Enable structured logs and log collection for uncovered services.")
	}
	if missingTelemetry > 0 {
		recommendations = append(recommendations, "Instrument Kubernetes workloads marked missing_telemetry with traces, metrics, and logs.")
	}
	var missingLimits int
	if err := s.pool.QueryRow(ctx, `
		SELECT count(*)
		FROM cluster_resources
		WHERE ($1 = '' OR cluster_id = $1)
		  AND resource_type IN ('deployment', 'statefulset')
		  AND status ILIKE '%missing-limits%'
	`, cluster).Scan(&missingLimits); err == nil && missingLimits > 0 {
		recommendations = append(recommendations, "Add CPU and memory limits to workloads missing resource constraints.")
	}
	report["services_discovered"] = discovered
	report["services_with_traces"] = withTraces
	report["services_with_metrics"] = withMetrics
	report["services_with_logs"] = withLogs
	report["services_missing_telemetry"] = missingTelemetry
	report["observability_coverage_score"] = coverageScore
	report["recommendations"] = recommendations
	missingItems := []map[string]any{}
	rows, err := s.pool.Query(ctx, `
		SELECT service_name, namespace, service_type, deployment
		FROM services_registry
		WHERE ($1 = '' OR project_id = $1)
		  AND ($2 = '' OR cluster = $2)
		  AND telemetry_status = 'missing_telemetry'
		ORDER BY namespace, service_name
		LIMIT 100
	`, projectID, cluster)
	if err == nil {
		defer rows.Close()
		for rows.Next() {
			var serviceName, namespace, serviceType, deployment string
			if scanErr := rows.Scan(&serviceName, &namespace, &serviceType, &deployment); scanErr == nil {
				missingItems = append(missingItems, map[string]any{
					"service_name": serviceName,
					"namespace":    namespace,
					"service_type": serviceType,
					"deployment":   deployment,
				})
			}
		}
	}
	report["missing_telemetry_services"] = missingItems
	report["generated_at"] = time.Now().UTC()
	return report, nil
}

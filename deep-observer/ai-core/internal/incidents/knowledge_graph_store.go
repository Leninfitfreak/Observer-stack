package incidents

import (
	"context"
	"encoding/json"
	"math"
	"strconv"
	"strings"

	"deep-observer/ai-core/internal/clickhouse"
)

func (s *Store) UpsertSystemGraph(ctx context.Context, projectID, cluster, namespace string, graph clickhouse.TopologyGraph) error {
	tx, err := s.pool.Begin(ctx)
	if err != nil {
		return err
	}
	defer tx.Rollback(ctx)

	for _, node := range graph.Nodes {
		nodeType := inferNodeType(node.ID)
		metadata, _ := json.Marshal(map[string]any{
			"label":         node.Label,
			"request_count": node.RequestCount,
			"error_rate":    node.ErrorRate,
		})
		if _, err := tx.Exec(ctx, `
			INSERT INTO graph_nodes (
				project_id, cluster, namespace, node_id, node_type, metadata, first_seen, last_seen
			) VALUES ($1,$2,$3,$4,$5,$6,NOW(),NOW())
			ON CONFLICT (project_id, cluster, namespace, node_id, node_type) DO UPDATE
			SET metadata = EXCLUDED.metadata, last_seen = NOW()
		`, defaultProjectID(projectID), cluster, namespace, node.ID, nodeType, metadata); err != nil {
			return err
		}
	}

	for _, edge := range graph.Edges {
		if edge.Source == "" || edge.Target == "" {
			continue
		}
		metadata, _ := json.Marshal(map[string]any{
			"dependency_type": edge.DependencyType,
			"call_count":      edge.CallCount,
			"avg_latency_ms":  edge.AvgLatencyMs,
			"error_rate":      edge.ErrorRate,
			"destination":     edge.Destination,
		})
		if _, err := tx.Exec(ctx, `
			INSERT INTO graph_edges (
				project_id, cluster, namespace, source_node, target_node, edge_type, confidence, metadata, first_seen, last_seen
			) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,NOW(),NOW())
			ON CONFLICT (project_id, cluster, namespace, source_node, target_node, edge_type) DO UPDATE
			SET
				confidence = GREATEST(graph_edges.confidence, EXCLUDED.confidence),
				metadata = EXCLUDED.metadata,
				last_seen = NOW()
		`, defaultProjectID(projectID), cluster, namespace, edge.Source, edge.Target, graphEdgeType(edge.DependencyType), dependencyConfidence(edge.DependencyType), metadata); err != nil {
			return err
		}
	}

	if _, err := tx.Exec(ctx, `
		DELETE FROM graph_nodes
		WHERE project_id = $1 AND cluster = $2 AND namespace = $3
		  AND last_seen < NOW() - INTERVAL '24 hours'
	`, defaultProjectID(projectID), cluster, namespace); err != nil {
		return err
	}
	if _, err := tx.Exec(ctx, `
		DELETE FROM graph_edges
		WHERE project_id = $1 AND cluster = $2 AND namespace = $3
		  AND last_seen < NOW() - INTERVAL '24 hours'
	`, defaultProjectID(projectID), cluster, namespace); err != nil {
		return err
	}

	return tx.Commit(ctx)
}

func (s *Store) UpsertIncidentKnowledgeGraph(ctx context.Context, incident Incident) error {
	tx, err := s.pool.Begin(ctx)
	if err != nil {
		return err
	}
	defer tx.Rollback(ctx)

	insertNode := func(nodeID, nodeType string, metadata map[string]any) error {
		raw, _ := json.Marshal(metadata)
		_, err := tx.Exec(ctx, `
			INSERT INTO incident_graph_nodes (incident_id, node_id, node_type, metadata, created_at)
			VALUES ($1,$2,$3,$4,NOW())
			ON CONFLICT (incident_id, node_id, node_type) DO UPDATE
			SET metadata = EXCLUDED.metadata
		`, incident.ID, nodeID, nodeType, raw)
		return err
	}
	insertEdge := func(source, target, edgeType string, metadata map[string]any) error {
		raw, _ := json.Marshal(metadata)
		_, err := tx.Exec(ctx, `
			INSERT INTO incident_graph_edges (incident_id, source_node, target_node, edge_type, metadata, created_at)
			VALUES ($1,$2,$3,$4,$5,NOW())
			ON CONFLICT (incident_id, source_node, target_node, edge_type) DO UPDATE
			SET metadata = EXCLUDED.metadata
		`, incident.ID, source, target, edgeType, raw)
		return err
	}

	if err := insertNode("incident:"+incident.ID, "incident", map[string]any{
		"severity": incident.Severity,
		"score":    incident.AnomalyScore,
		"service":  incident.Service,
	}); err != nil {
		return err
	}
	if err := insertNode("service:"+incident.Service, "service", map[string]any{
		"cluster":   incident.Cluster,
		"namespace": incident.Namespace,
	}); err != nil {
		return err
	}
	if err := insertEdge("incident:"+incident.ID, "service:"+incident.Service, "impacts", map[string]any{}); err != nil {
		return err
	}

	for _, signal := range incident.Signals {
		if signal == "" {
			continue
		}
		signalNode := "signal:" + signal
		if err := insertNode(signalNode, "signal", map[string]any{}); err != nil {
			return err
		}
		if err := insertEdge("incident:"+incident.ID, signalNode, "triggered_by", map[string]any{}); err != nil {
			return err
		}
	}
	for _, dep := range incident.DependencyChain {
		if dep == "" {
			continue
		}
		depNode := "service:" + dep
		if err := insertNode(depNode, "dependency", map[string]any{}); err != nil {
			return err
		}
		if err := insertEdge("service:"+incident.Service, depNode, "correlates_with", map[string]any{}); err != nil {
			return err
		}
	}
	return tx.Commit(ctx)
}

func (s *Store) DetectAdaptiveSignals(ctx context.Context, projectID, cluster, namespace, service string, snapshot clickhouse.Snapshot) ([]string, error) {
	signals := []string{}
	metrics := map[string]float64{
		"latency_p95_ms": snapshot.P95LatencyMs,
		"error_rate":     snapshot.ErrorRate,
	}
	if lag := queueLagValue(snapshot); lag > 0 {
		metrics["queue_lag"] = lag
	}

	for metricName, value := range metrics {
		rows, err := s.pool.Query(ctx, `
			SELECT hour_of_day, day_of_week, baseline_value, variance, sample_count
			FROM service_metric_baselines
			WHERE project_id = $1 AND cluster = $2 AND namespace = $3 AND service = $4 AND metric = $5
			  AND hour_of_day = $6 AND day_of_week = $7
		`, defaultProjectID(projectID), cluster, namespace, service, metricName, int(snapshot.ObservedAt.Hour()), int(snapshot.ObservedAt.Weekday()))
		if err != nil {
			return nil, err
		}
		for rows.Next() {
			var hourOfDay, dayOfWeek int
			var mean, variance float64
			var count int64
			if scanErr := rows.Scan(&hourOfDay, &dayOfWeek, &mean, &variance, &count); scanErr != nil {
				rows.Close()
				return nil, scanErr
			}
			if count < 20 {
				continue
			}
			std := math.Sqrt(math.Max(variance, minStd(metricName)*minStd(metricName)))
			threshold := mean + 3*math.Max(std, minStd(metricName))
			if value > threshold {
				switch metricName {
				case "latency_p95_ms":
					signals = append(signals, "adaptive_latency_deviation_h"+itoa(hourOfDay)+"_d"+itoa(dayOfWeek))
				case "error_rate":
					signals = append(signals, "adaptive_error_deviation_h"+itoa(hourOfDay)+"_d"+itoa(dayOfWeek))
				case "queue_lag":
					signals = append(signals, "queue_lag_spike_h"+itoa(hourOfDay)+"_d"+itoa(dayOfWeek))
				}
			}
		}
		if err := rows.Err(); err != nil {
			rows.Close()
			return nil, err
		}
		rows.Close()
	}
	return uniqueSignals(signals), nil
}

func (s *Store) UpdateAdaptiveBaselines(ctx context.Context, projectID, cluster, namespace, service string, snapshot clickhouse.Snapshot) error {
	values := map[string]float64{
		"latency_p95_ms": snapshot.P95LatencyMs,
		"error_rate":     snapshot.ErrorRate,
	}
	if lag := queueLagValue(snapshot); lag > 0 {
		values["queue_lag"] = lag
	}
	hourOfDay := int(snapshot.ObservedAt.Hour())
	dayOfWeek := int(snapshot.ObservedAt.Weekday())
	alpha := 0.15
	for metricName, value := range values {
		var mean, variance float64
		var count int64
		err := s.pool.QueryRow(ctx, `
			SELECT baseline_value, variance, sample_count
			FROM service_metric_baselines
			WHERE project_id = $1 AND cluster = $2 AND namespace = $3 AND service = $4
			  AND metric = $5 AND hour_of_day = $6 AND day_of_week = $7
		`, defaultProjectID(projectID), cluster, namespace, service, metricName, hourOfDay, dayOfWeek).Scan(&mean, &variance, &count)
		if err != nil {
			mean = value
			variance = minStd(metricName) * minStd(metricName)
			count = 0
		} else {
			delta := value - mean
			newMean := mean + alpha*delta
			newVariance := (1 - alpha) * (variance + alpha*delta*delta)
			mean = newMean
			variance = math.Max(newVariance, minStd(metricName)*minStd(metricName))
		}
		_, execErr := s.pool.Exec(ctx, `
			INSERT INTO service_metric_baselines (
				project_id, cluster, namespace, service, metric, hour_of_day, day_of_week,
				baseline_value, variance, sample_count, updated_at
			) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,NOW())
			ON CONFLICT (project_id, cluster, namespace, service, metric, hour_of_day, day_of_week) DO UPDATE
			SET
				baseline_value = EXCLUDED.baseline_value,
				variance = EXCLUDED.variance,
				sample_count = service_metric_baselines.sample_count + 1,
				updated_at = NOW()
		`, defaultProjectID(projectID), cluster, namespace, service, metricName, hourOfDay, dayOfWeek, mean, variance, count+1)
		if execErr != nil {
			return execErr
		}
	}
	return nil
}

func itoa(value int) string {
	return strconv.Itoa(value)
}

func inferNodeType(nodeID string) string {
	id := strings.ToLower(strings.TrimSpace(nodeID))
	switch {
	case strings.HasPrefix(id, "db:"):
		return "database"
	case strings.Contains(id, "kafka") || strings.Contains(id, "topic"):
		return "kafka_topic"
	case strings.Contains(id, "pod/"):
		return "pod"
	case strings.Contains(id, "node/"):
		return "node"
	case strings.Contains(id, "deploy/") || strings.Contains(id, "deployment"):
		return "deployment"
	default:
		return "service"
	}
}

func graphEdgeType(depType string) string {
	switch depType {
	case "messaging":
		return "publishes_to"
	case "database":
		return "connects_to"
	default:
		return "depends_on"
	}
}

func queueLagValue(snapshot clickhouse.Snapshot) float64 {
	maxLag := 0.0
	for name, value := range snapshot.MetricHighlights {
		lower := strings.ToLower(name)
		if strings.Contains(lower, "lag") || strings.Contains(lower, "backlog") || strings.Contains(lower, "queue") {
			if value > maxLag {
				maxLag = value
			}
		}
	}
	return maxLag
}

func minStd(metricName string) float64 {
	switch metricName {
	case "latency_p95_ms":
		return 10
	case "error_rate":
		return 0.01
	case "queue_lag":
		return 5
	default:
		return 1
	}
}

func uniqueSignals(items []string) []string {
	out := []string{}
	seen := map[string]struct{}{}
	for _, item := range items {
		if item == "" {
			continue
		}
		if _, ok := seen[item]; ok {
			continue
		}
		seen[item] = struct{}{}
		out = append(out, item)
	}
	return out
}

package clickhouse

import (
	"context"
	"fmt"
	"strings"
	"time"
)

type ChangeRecord struct {
	ClusterID    string            `json:"cluster_id"`
	Namespace    string            `json:"namespace"`
	ResourceType string            `json:"resource_type"`
	ResourceName string            `json:"resource_name"`
	ChangeType   string            `json:"change_type"`
	Timestamp    time.Time         `json:"timestamp"`
	Metadata     map[string]string `json:"metadata"`
}

func (c *Client) DetectSystemChanges(ctx context.Context, clusterID, namespace string, since time.Duration, limit int) ([]ChangeRecord, error) {
	if limit <= 0 {
		limit = 200
	}
	now := time.Now().UTC()
	start := now.Add(-since)
	query := fmt.Sprintf(`
		SELECT
			timestamp,
			ifNull(resources_string['k8s.cluster.name'], '') AS cluster,
			ifNull(resources_string['k8s.namespace.name'], '') AS namespace,
			substring(toString(body), 1, 500) AS body
		FROM %s
		WHERE timestamp >= %d
		  AND timestamp < %d
		  AND (
			positionCaseInsensitive(body, 'deployment') > 0 OR
			positionCaseInsensitive(body, 'rollout') > 0 OR
			positionCaseInsensitive(body, 'scaled') > 0 OR
			positionCaseInsensitive(body, 'restart') > 0 OR
			positionCaseInsensitive(body, 'image') > 0
		  )
		ORDER BY timestamp DESC
		LIMIT %d
	`, logsTable, start.UnixNano(), now.UnixNano(), limit)
	rows, err := c.conn.Query(ctx, query)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	records := []ChangeRecord{}
	for rows.Next() {
		var timestampNs uint64
		var cluster, ns, body string
		if scanErr := rows.Scan(&timestampNs, &cluster, &ns, &body); scanErr != nil {
			return nil, scanErr
		}
		if clusterID != "" && cluster != clusterID {
			continue
		}
		if namespace != "" && ns != namespace {
			continue
		}
		record := ChangeRecord{
			ClusterID:    cluster,
			Namespace:    ns,
			ResourceType: inferResourceType(body),
			ResourceName: inferResourceName(body),
			ChangeType:   inferChangeType(body),
			Timestamp:    time.Unix(0, int64(timestampNs)).UTC(),
			Metadata: map[string]string{
				"body": body,
			},
		}
		records = append(records, record)
	}
	return records, rows.Err()
}

func inferChangeType(body string) string {
	lower := strings.ToLower(body)
	switch {
	case strings.Contains(lower, "rollout"):
		return "rollout"
	case strings.Contains(lower, "scaled"):
		return "scale_change"
	case strings.Contains(lower, "restart"):
		return "pod_restart"
	case strings.Contains(lower, "image"):
		return "image_update"
	default:
		return "configuration_change"
	}
}

func inferResourceType(body string) string {
	lower := strings.ToLower(body)
	switch {
	case strings.Contains(lower, "\"kind\":\"deployment\"") || strings.Contains(lower, "deployment"):
		return "deployment"
	case strings.Contains(lower, "\"kind\":\"statefulset\"") || strings.Contains(lower, "statefulset"):
		return "statefulset"
	case strings.Contains(lower, "\"kind\":\"pod\"") || strings.Contains(lower, "pod"):
		return "pod"
	default:
		return "kubernetes_resource"
	}
}

func inferResourceName(body string) string {
	lower := strings.ToLower(body)
	for _, token := range []string{"\"name\":\"", "name=\"", "deployment/"} {
		index := strings.Index(lower, token)
		if index == -1 {
			continue
		}
		start := index + len(token)
		end := start
		for end < len(body) && body[end] != '"' && body[end] != '\'' && body[end] != ',' && body[end] != ' ' {
			end++
		}
		if end > start {
			return body[start:end]
		}
	}
	return ""
}

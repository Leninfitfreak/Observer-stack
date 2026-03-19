package enterprise

import (
	"context"
	"crypto/sha1"
	"encoding/hex"
	"encoding/json"
	"os/exec"
	"strings"
	"time"

	"deep-observer/ai-core/internal/incidents"
)

type ChangeIntelligenceEngine struct {
	store     *incidents.Store
	clusterID string
	interval  time.Duration
}

func NewChangeIntelligenceEngine(store *incidents.Store, clusterID string, interval time.Duration) *ChangeIntelligenceEngine {
	if interval <= 0 {
		interval = 3 * time.Minute
	}
	return &ChangeIntelligenceEngine{
		store:     store,
		clusterID: clusterID,
		interval:  interval,
	}
}

func (e *ChangeIntelligenceEngine) Run(ctx context.Context) {
	ticker := time.NewTicker(e.interval)
	defer ticker.Stop()
	e.refresh(ctx)
	for {
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
			e.refresh(ctx)
		}
	}
}

func (e *ChangeIntelligenceEngine) CorrelateRecentChanges(ctx context.Context, namespace string, incidentAt time.Time, limit int) ([]incidents.SystemChange, error) {
	changes, err := e.store.ListSystemChanges(ctx, e.resolveClusterID(ctx), namespace, limit)
	if err != nil {
		return nil, err
	}
	window := 20 * time.Minute
	filtered := make([]incidents.SystemChange, 0, len(changes))
	for _, change := range changes {
		if change.Timestamp.Before(incidentAt.Add(-window)) || change.Timestamp.After(incidentAt.Add(window)) {
			continue
		}
		filtered = append(filtered, change)
	}
	return filtered, nil
}

func (e *ChangeIntelligenceEngine) refresh(ctx context.Context) {
	clusterID := e.resolveClusterID(ctx)
	rawEvents, err := runKubectl(ctx, "get", "events", "-A", "-o", "json")
	if err != nil {
		return
	}
	var payload map[string]any
	if err := json.Unmarshal(rawEvents, &payload); err != nil {
		return
	}
	items, ok := payload["items"].([]any)
	if !ok {
		return
	}
	now := time.Now().UTC()
	for _, item := range items {
		event, ok := item.(map[string]any)
		if !ok {
			continue
		}
		meta := mapValue(event, "metadata")
		involved := mapValue(event, "involvedObject")
		namespace := strValue(meta, "namespace")
		resource := strings.ToLower(strValue(involved, "kind"))
		resourceName := strValue(involved, "name")
		reason := strings.ToLower(strValue(event, "reason"))
		message := strValue(event, "message")
		combined := reason + " " + strings.ToLower(message)
		if !strings.Contains(combined, "deploy") &&
			!strings.Contains(combined, "rollout") &&
			!strings.Contains(combined, "restart") &&
			!strings.Contains(combined, "pulling image") &&
			!strings.Contains(combined, "scaled") {
			continue
		}
		ts := strValue(event, "eventTime")
		if ts == "" {
			ts = strValue(event, "lastTimestamp")
		}
		if ts == "" {
			ts = strValue(meta, "creationTimestamp")
		}
		if ts == "" {
			continue
		}
		timestamp, err := parseTimestamp(ts)
		if err != nil {
			continue
		}
		if timestamp.Before(now.Add(-48 * time.Hour)) {
			continue
		}
		changeType := inferChangeType(combined)
		metadata := map[string]any{
			"reason":   reason,
			"message":  message,
			"resource": resource,
		}
		if resource == "deployment" && resourceName != "" {
			if history, err := runKubectl(ctx, "rollout", "history", "deployment/"+resourceName, "-n", namespace); err == nil {
				metadata["rollout_history"] = strings.TrimSpace(string(history))
			}
		}
		_ = e.store.UpsertSystemChange(ctx, incidents.SystemChange{
			ChangeID:     hashID(namespace + "|" + resource + "|" + resourceName + "|" + changeType + "|" + timestamp.Format(time.RFC3339Nano)),
			ClusterID:    clusterID,
			Namespace:    namespace,
			ResourceType: resource,
			ResourceName: resourceName,
			ChangeType:   changeType,
			Timestamp:    timestamp,
			Metadata:     metadata,
		})
	}
}

func (e *ChangeIntelligenceEngine) resolveClusterID(ctx context.Context) string {
	if trimmed := strings.TrimSpace(e.clusterID); trimmed != "" {
		return trimmed
	}
	output, err := runKubectl(ctx, "config", "current-context")
	if err != nil {
		return ""
	}
	current := strings.TrimSpace(string(output))
	return current
}

func runKubectl(ctx context.Context, args ...string) ([]byte, error) {
	cmd := exec.CommandContext(ctx, "kubectl", args...)
	return cmd.Output()
}

func parseTimestamp(raw string) (time.Time, error) {
	parsed, err := time.Parse(time.RFC3339, raw)
	if err == nil {
		return parsed.UTC(), nil
	}
	parsed, err = time.Parse("2006-01-02T15:04:05Z07:00", raw)
	if err != nil {
		return time.Time{}, err
	}
	return parsed.UTC(), nil
}

func inferChangeType(text string) string {
	switch {
	case strings.Contains(text, "rollout"):
		return "rollout"
	case strings.Contains(text, "restart"):
		return "pod_restart"
	case strings.Contains(text, "image"):
		return "image_update"
	case strings.Contains(text, "scaled"):
		return "scale_change"
	default:
		return "configuration_change"
	}
}

func hashID(value string) string {
	sum := sha1.Sum([]byte(value))
	return hex.EncodeToString(sum[:])
}

func mapValue(value map[string]any, key string) map[string]any {
	raw, ok := value[key].(map[string]any)
	if !ok {
		return map[string]any{}
	}
	return raw
}

func strValue(value map[string]any, key string) string {
	raw, ok := value[key]
	if !ok || raw == nil {
		return ""
	}
	text, ok := raw.(string)
	if ok {
		return text
	}
	return ""
}

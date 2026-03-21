package truth

import (
	"context"
	"strings"
	"time"

	"deep-observer/ai-core/internal/clickhouse"
	"deep-observer/ai-core/internal/config"
	"deep-observer/ai-core/internal/incidents"
)

type Service struct {
	store   *incidents.Store
	chConfig config.ClickHouseConfig
	project config.ProjectConfig
}

func NewService(store *incidents.Store, chConfig config.ClickHouseConfig, project config.ProjectConfig) *Service {
	return &Service{store: store, chConfig: chConfig, project: project}
}

func (s *Service) normalizeScope(req ScopeRequest) NormalizedScope {
	start := req.Start.UTC()
	end := req.End.UTC()
	if start.IsZero() && end.IsZero() {
		end = time.Now().UTC()
		start = end.Add(-24 * time.Hour)
	} else if start.IsZero() {
		start = end.Add(-24 * time.Hour)
	} else if end.IsZero() {
		end = start.Add(24 * time.Hour)
	}
	if end.Before(start) {
		end = start.Add(24 * time.Hour)
	}
	return NormalizedScope{
		Cluster:   normalizeScopeValue(firstNonEmpty(req.Cluster, s.project.ClusterID)),
		Namespace: normalizeScopeValue(firstNonEmpty(req.Namespace, s.project.NamespaceFilter)),
		Service:   normalizeServiceName(normalizeScopeValue(firstNonEmpty(req.Service, s.project.ServiceFilter))),
		Start:     start,
		End:       end,
	}
}

func (s *Service) newClickHouseClient(ctx context.Context) (*clickhouse.Client, error) {
	return clickhouse.NewClient(ctx, s.chConfig)
}

func firstNonEmpty(values ...string) string {
	for _, value := range values {
		value = strings.TrimSpace(value)
		if value != "" {
			return value
		}
	}
	return ""
}

func normalizeServiceName(value string) string {
	return strings.TrimSpace(strings.ToLower(value))
}

func normalizeScopeValue(value string) string {
	switch strings.ToLower(strings.TrimSpace(value)) {
	case "", "all", "all clusters", "all namespaces", "all services":
		return ""
	default:
		return strings.TrimSpace(value)
	}
}

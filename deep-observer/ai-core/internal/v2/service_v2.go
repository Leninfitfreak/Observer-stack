package v2

import (
	"context"
	"strings"
	"time"

	"deep-observer/ai-core/internal/config"
	"deep-observer/ai-core/internal/incidents"
)

type Service struct {
	store   *incidents.Store
	project config.ProjectConfig
	api     *apiClient
}

func NewService(store *incidents.Store, project config.ProjectConfig) *Service {
	return &Service{
		store:   store,
		project: project,
		api:     newAPIClient(),
	}
}

func (s *Service) normalizeScope(req ScopeRequest) Scope {
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
	return Scope{
		Cluster:   normalizeScopeValue(firstNonEmpty(req.Cluster, s.project.ClusterID)),
		Namespace: normalizeScopeValue(firstNonEmpty(req.Namespace, s.project.NamespaceFilter)),
		Service:   normalizeService(normalizeScopeValue(firstNonEmpty(req.Service, s.project.ServiceFilter))),
		Start:     start,
		End:       end,
	}
}

func normalizeScopeValue(value string) string {
	switch strings.ToLower(strings.TrimSpace(value)) {
	case "", "all", "all clusters", "all namespaces", "all services":
		return ""
	default:
		return strings.TrimSpace(value)
	}
}

func normalizeService(value string) string {
	return strings.ToLower(strings.TrimSpace(value))
}

func (s *Service) ListIncidents(ctx context.Context, scope Scope, limit int) ([]incidents.Incident, error) {
	start := scope.Start
	end := scope.End
	items, err := s.store.ListIncidents(ctx, incidents.QueryFilters{
		ProjectID: s.project.ProjectID,
		Cluster:   scope.Cluster,
		Namespace: scope.Namespace,
		Service:   scope.Service,
		Start:     &start,
		End:       &end,
		Limit:     limit,
	})
	if err != nil {
		return nil, err
	}
	return items, nil
}

func (s *Service) GetIncident(ctx context.Context, incidentID string) (*incidents.Incident, error) {
	return s.store.GetIncident(ctx, strings.TrimSpace(incidentID))
}


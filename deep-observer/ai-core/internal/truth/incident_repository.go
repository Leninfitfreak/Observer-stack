package truth

import (
	"context"

	"deep-observer/ai-core/internal/clickhouse"
	"deep-observer/ai-core/internal/incidents"
)

func (s *Service) ListIncidents(ctx context.Context, scope NormalizedScope, limit int) ([]incidents.Incident, error) {
	items, err := s.store.ListIncidents(ctx, incidents.QueryFilters{
		ProjectID: s.project.ProjectID,
		Cluster:   scope.Cluster,
		Namespace: scope.Namespace,
		Service:   scope.Service,
		Start:     &scope.Start,
		End:       &scope.End,
		Limit:     limit,
	})
	if err != nil {
		return nil, err
	}

	filtered := make([]incidents.Incident, 0, len(items))
	for _, item := range items {
		if clickhouse.IsIgnoredService(item.Service) {
			continue
		}
		filtered = append(filtered, item)
	}
	return filtered, nil
}

func (s *Service) GetIncident(ctx context.Context, incidentID string) (*incidents.Incident, error) {
	return s.store.GetIncident(ctx, incidentID)
}

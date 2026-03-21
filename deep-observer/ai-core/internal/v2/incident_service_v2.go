package v2

import (
	"context"
	"strings"
	"time"

	"deep-observer/ai-core/internal/incidents"
)

func (s *Service) ListRelatedIncidents(ctx context.Context, incidentID string) []incidents.Incident {
	correlated, err := s.store.ListCorrelatedIncidents(ctx, incidentID, 24*time.Hour, 6)
	if err != nil {
		return []incidents.Incident{}
	}
	out := make([]incidents.Incident, 0, len(correlated))
	for _, item := range correlated {
		incident, err := s.store.GetIncident(ctx, strings.TrimSpace(item.IncidentID))
		if err != nil || incident == nil {
			continue
		}
		out = append(out, *incident)
	}
	return out
}

func (s *Service) ListNearestObserved(ctx context.Context, scope Scope, currentID string) []incidents.Incident {
	items, err := s.ListIncidents(ctx, Scope{
		Cluster:   scope.Cluster,
		Namespace: scope.Namespace,
		Service:   scope.Service,
		Start:     scope.Start.Add(-48 * time.Hour),
		End:       scope.End,
	}, 20)
	if err != nil {
		return []incidents.Incident{}
	}
	out := make([]incidents.Incident, 0, 3)
	for _, item := range items {
		if item.ID == currentID || !strings.EqualFold(item.IncidentType, "observed") {
			continue
		}
		out = append(out, item)
		if len(out) >= 3 {
			break
		}
	}
	return out
}


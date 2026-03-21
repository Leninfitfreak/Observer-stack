package truth

import "context"

func (s *Service) BuildSelectedIncidentContract(ctx context.Context, incidentID string, req ScopeRequest) (SelectedIncidentContract, error) {
	item, err := s.GetIncident(ctx, incidentID)
	if err != nil {
		return nil, err
	}
	scope := s.normalizeScope(req)
	if item.Scope.IncidentWindowStart != nil {
		scope.Start = item.Scope.IncidentWindowStart.UTC()
	}
	if item.Scope.IncidentWindowEnd != nil {
		scope.End = item.Scope.IncidentWindowEnd.UTC()
	}
	scope.Cluster = firstNonEmpty(scope.Cluster, item.Cluster, item.Scope.Cluster)
	scope.Namespace = firstNonEmpty(scope.Namespace, item.Namespace, item.Scope.Namespace)
	scope.Service = normalizeServiceName(firstNonEmpty(scope.Service, item.Service, item.Scope.Service))
	return SelectedIncidentContract(s.collectTelemetry(ctx, item, scope)), nil
}

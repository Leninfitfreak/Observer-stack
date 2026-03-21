package truth

import (
	"context"
	"strings"
)

func (s *Service) BuildDashboardContract(ctx context.Context, req ScopeRequest) (DashboardContract, error) {
	scope := s.normalizeScope(req)
	incidents, err := s.ListIncidents(ctx, scope, 200)
	if err != nil {
		return DashboardContract{}, err
	}
	topology := s.ResolveTopology(ctx, scope)
	options := s.DiscoverFilterOptions(ctx, scope)

	summary := SummaryCounts{
		TotalIncidents: len(incidents),
		TopologyNodes:  len(topology.Nodes),
		TopologyEdges:  len(topology.Edges),
	}
	for _, item := range incidents {
		if strings.EqualFold(item.IncidentType, "predictive") {
			summary.PredictiveIncidents++
		} else {
			summary.ObservedIncidents++
		}
	}

	empty := len(incidents) == 0
	return DashboardContract{
		NormalizedScope: scope,
		FilterOptions:   options,
		IncidentList:    incidents,
		ScopedTopology:  topology,
		SummaryCounts:   summary,
		NoResultsState: NoResultsState{
			Empty:   empty,
			Message: ternaryString(empty, "No incidents match the current scope.", ""),
		},
	}, nil
}

func ternaryString(condition bool, yes, no string) string {
	if condition {
		return yes
	}
	return no
}

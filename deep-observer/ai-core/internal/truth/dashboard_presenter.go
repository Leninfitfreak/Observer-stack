package truth

import (
	"context"
	"strings"

	"deep-observer/ai-core/internal/clickhouse"
)

func (s *Service) BuildDashboardContract(ctx context.Context, req ScopeRequest) (DashboardContract, error) {
	scope := s.normalizeScope(req)
	incidents, err := s.ListIncidents(ctx, scope, 200)
	if err != nil {
		return DashboardContract{}, err
	}
	options := s.DiscoverFilterOptions(ctx, scope)

	empty := len(incidents) == 0
	if empty {
		return DashboardContract{
			NormalizedScope: scope,
			FilterOptions:   options,
			IncidentList:    incidents,
			ScopedTopology:  clickhouse.TopologyGraph{Nodes: []clickhouse.TopologyNode{}, Edges: []clickhouse.TopologyEdge{}},
			SummaryCounts: SummaryCounts{
				TotalIncidents:      0,
				ObservedIncidents:   0,
				PredictiveIncidents: 0,
				TopologyNodes:       0,
				TopologyEdges:       0,
			},
			NoResultsState: NoResultsState{
				Empty:   true,
				Message: "No incidents match the current scope.",
			},
		}, nil
	}

	topology := s.ResolveTopology(ctx, scope)
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

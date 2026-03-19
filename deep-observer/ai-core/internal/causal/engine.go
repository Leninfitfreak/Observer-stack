package causal

import (
	"math"
	"sort"

	"deep-observer/ai-core/internal/clickhouse"
	"deep-observer/ai-core/internal/incidents"
)

type Engine struct{}

func NewEngine() *Engine {
	return &Engine{}
}

func (e *Engine) BuildProblem(incident incidents.Incident, graph clickhouse.TopologyGraph) incidents.Problem {
	impact := map[string]float64{}
	impact[incident.Service] = incident.AnomalyScore
	for _, edge := range graph.Edges {
		if edge.Source == incident.Service {
			impact[edge.Target] += float64(edge.CallCount) * edgeWeight(edge.DependencyType)
		}
		if edge.Target == incident.Service {
			impact[edge.Source] += float64(edge.CallCount) * edgeWeight(edge.DependencyType) * 0.5
		}
	}
	affected := make([]string, 0, len(impact))
	for service := range impact {
		affected = append(affected, service)
	}
	sort.Slice(affected, func(i, j int) bool {
		return impact[affected[i]] > impact[affected[j]]
	})
	confidence := math.Min(0.99, 0.5+(incident.AnomalyScore/120))
	if len(graph.Edges) > 0 {
		confidence = math.Min(0.99, confidence+0.2)
	}
	return incidents.Problem{
		ProblemID:        incident.ProblemID,
		ProjectID:        incident.ProjectID,
		Cluster:          incident.Cluster,
		Namespace:        incident.Namespace,
		RootCauseService: incident.Service,
		AffectedServices: affected,
		IncidentIDs:      []string{incident.ID},
		Confidence:       math.Round(confidence*100) / 100,
		CreatedAt:        incident.Timestamp,
	}
}

func edgeWeight(edgeType string) float64 {
	switch edgeType {
	case "trace_rpc":
		return 1.0
	case "messaging":
		return 0.95
	case "trace_http":
		return 0.9
	case "database":
		return 0.82
	case "kubernetes_dns":
		return 0.5
	default:
		return 0.4
	}
}

package v2

import (
	"context"
	"strings"
)

func (s *Service) ResolveTopology(ctx context.Context, scope Scope) Topology {
	items, err := s.api.fetchDependencies(ctx, Scope{
		Cluster:   scope.Cluster,
		Namespace: scope.Namespace,
		Service:   "",
		Start:     scope.Start,
		End:       scope.End,
	})
	if err != nil {
		return Topology{Available: false, Nodes: []TopologyNode{}, Edges: []TopologyEdge{}}
	}
	nodeMap := map[string]TopologyNode{}
	edges := []TopologyEdge{}
	targetService := normalizeService(scope.Service)
	for _, item := range items {
		source := canonicalNodeID(item.Parent)
		target := canonicalNodeID(item.Child)
		if source == "" || target == "" || source == target {
			continue
		}
		if targetService != "" {
			if normalizeService(source) != targetService && normalizeService(target) != targetService {
				continue
			}
		}
		edge := TopologyEdge{
			Source:         source,
			Target:         target,
			DependencyType: inferDependencyType(target),
			CallCount:      int64(item.CallCount),
			ErrorRate:      item.ErrorRate,
			LatencyMs:      firstPositive(item.P95, item.P99),
		}
		edges = append(edges, edge)
		nodeMap[source] = TopologyNode{ID: source, Label: source, NodeType: inferNodeType(source)}
		nodeMap[target] = TopologyNode{ID: target, Label: target, NodeType: inferNodeType(target)}
	}
	nodes := make([]TopologyNode, 0, len(nodeMap))
	for _, node := range nodeMap {
		nodes = append(nodes, node)
	}
	return Topology{
		Available: len(nodes) > 0 || len(edges) > 0,
		Nodes:     nodes,
		Edges:     edges,
	}
}

func inferNodeType(id string) string {
	lower := strings.ToLower(strings.TrimSpace(id))
	switch {
	case strings.HasPrefix(lower, "db:"):
		return "database"
	case strings.HasPrefix(lower, "messaging:"):
		return "messaging"
	default:
		return "service"
	}
}

func inferDependencyType(target string) string {
	switch inferNodeType(target) {
	case "database":
		return "database"
	case "messaging":
		return "messaging"
	default:
		return "service"
	}
}

func canonicalNodeID(value string) string {
	value = normalizeService(value)
	if value == "" {
		return ""
	}
	// Preserve already-structured IDs returned by API.
	if strings.HasPrefix(value, "db:") || strings.HasPrefix(value, "messaging:") {
		return value
	}
	return value
}

func firstPositive(values ...float64) float64 {
	for _, value := range values {
		if value > 0 {
			return value
		}
	}
	return 0
}

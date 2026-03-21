package truth

import (
	"context"
	"sort"
	"strings"

	"deep-observer/ai-core/internal/clickhouse"
)

func (s *Service) ResolveTopology(ctx context.Context, scope NormalizedScope) clickhouse.TopologyGraph {
	graph := clickhouse.TopologyGraph{
		Nodes: []clickhouse.TopologyNode{},
		Edges: []clickhouse.TopologyEdge{},
	}
	fetched, err := s.signozFetchDependencyGraph(ctx, NormalizedScope{
		Cluster:   scope.Cluster,
		Namespace: scope.Namespace,
		Service:   "",
		Start:     scope.Start,
		End:       scope.End,
	})
	if err != nil {
		return graph
	}
	graph = sanitizeGraph(dedupeGraph(fetched))
	if scope.Service != "" {
		graph = filterGraphToService(graph, scope.Service)
	}
	return graph
}

func sanitizeGraph(graph clickhouse.TopologyGraph) clickhouse.TopologyGraph {
	structuredInfra := map[string]struct{}{}
	for _, node := range graph.Nodes {
		lower := strings.ToLower(strings.TrimSpace(node.ID))
		if strings.HasPrefix(lower, "db:") || strings.HasPrefix(lower, "messaging:") {
			parts := strings.SplitN(strings.TrimPrefix(lower, strings.SplitN(lower, ":", 2)[0]+":"), "/", 2)
			if len(parts) > 0 && parts[0] != "" {
				structuredInfra[parts[0]] = struct{}{}
			}
		}
	}

	nodes := make([]clickhouse.TopologyNode, 0, len(graph.Nodes))
	allowed := map[string]struct{}{}
	for _, node := range graph.Nodes {
		lower := strings.ToLower(strings.TrimSpace(node.ID))
		nodeType := strings.ToLower(strings.TrimSpace(node.NodeType))
		if nodeType == "service" {
			if _, ok := structuredInfra[lower]; ok {
				continue
			}
		}
		allowed[node.ID] = struct{}{}
		nodes = append(nodes, node)
	}

	edges := make([]clickhouse.TopologyEdge, 0, len(graph.Edges))
	for _, edge := range graph.Edges {
		if _, ok := allowed[edge.Source]; !ok {
			continue
		}
		if _, ok := allowed[edge.Target]; !ok {
			continue
		}
		edges = append(edges, edge)
	}

	graph.Nodes = nodes
	graph.Edges = edges
	return graph
}

func dedupeGraph(graph clickhouse.TopologyGraph) clickhouse.TopologyGraph {
	nodeSeen := map[string]struct{}{}
	edgeSeen := map[string]struct{}{}
	nodes := make([]clickhouse.TopologyNode, 0, len(graph.Nodes))
	edges := make([]clickhouse.TopologyEdge, 0, len(graph.Edges))

	for _, node := range graph.Nodes {
		key := strings.TrimSpace(node.ID)
		if key == "" {
			continue
		}
		if _, ok := nodeSeen[key]; ok {
			continue
		}
		nodeSeen[key] = struct{}{}
		nodes = append(nodes, node)
	}

	for _, edge := range graph.Edges {
		key := strings.Join([]string{
			strings.TrimSpace(edge.Source),
			strings.TrimSpace(edge.Target),
			strings.TrimSpace(edge.DependencyType),
			strings.TrimSpace(edge.Destination),
		}, "|")
		if key == "|||" {
			continue
		}
		if _, ok := edgeSeen[key]; ok {
			continue
		}
		edgeSeen[key] = struct{}{}
		edges = append(edges, edge)
	}

	sort.Slice(nodes, func(i, j int) bool { return nodes[i].ID < nodes[j].ID })
	sort.Slice(edges, func(i, j int) bool {
		left := edges[i].Source + "|" + edges[i].Target + "|" + edges[i].DependencyType
		right := edges[j].Source + "|" + edges[j].Target + "|" + edges[j].DependencyType
		return left < right
	})

	graph.Nodes = nodes
	graph.Edges = edges
	return graph
}

func scopeTopology(graph clickhouse.TopologyGraph, service string) map[string]any {
	target := normalizeServiceName(service)
	if target == "" {
		return map[string]any{
			"available": len(graph.Nodes) > 0 || len(graph.Edges) > 0,
			"nodes":     graph.Nodes,
			"edges":     graph.Edges,
		}
	}

	seen := map[string]struct{}{}
	edges := []clickhouse.TopologyEdge{}
	for _, edge := range graph.Edges {
		source := normalizeServiceName(edge.Source)
		targetName := normalizeServiceName(edge.Target)
		if source == target || targetName == target {
			edges = append(edges, edge)
			seen[edge.Source] = struct{}{}
			seen[edge.Target] = struct{}{}
		}
	}

	nodes := []clickhouse.TopologyNode{}
	for _, node := range graph.Nodes {
		if _, ok := seen[node.ID]; ok {
			nodes = append(nodes, node)
		}
	}

	return map[string]any{
		"available": len(nodes) > 0 || len(edges) > 0,
		"nodes":     nodes,
		"edges":     edges,
	}
}

func filterGraphToService(graph clickhouse.TopologyGraph, service string) clickhouse.TopologyGraph {
	target := normalizeServiceName(service)
	if target == "" {
		return graph
	}
	scoped := scopeTopology(graph, service)
	nodes, _ := scoped["nodes"].([]clickhouse.TopologyNode)
	edges, _ := scoped["edges"].([]clickhouse.TopologyEdge)
	return clickhouse.TopologyGraph{
		GeneratedAt: graph.GeneratedAt,
		Nodes:       nodes,
		Edges:       edges,
	}
}

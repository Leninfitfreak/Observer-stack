package enterprise

import (
	"math"
	"sort"
	"strings"

	"deep-observer/ai-core/internal/clickhouse"
	"deep-observer/ai-core/internal/incidents"
)

type CausalGraphEngine struct{}

type RankedNode struct {
	Service     string  `json:"service"`
	ImpactScore float64 `json:"impact_score"`
	Depth       int     `json:"propagation_depth"`
}

func NewCausalGraphEngine() *CausalGraphEngine {
	return &CausalGraphEngine{}
}

func (e *CausalGraphEngine) Rank(incident incidents.Incident, graph clickhouse.TopologyGraph) []RankedNode {
	nodeTypes := map[string]string{}
	for _, node := range graph.Nodes {
		kind := strings.ToLower(strings.TrimSpace(node.NodeType))
		if kind == "" {
			kind = "service"
		}
		nodeTypes[node.ID] = kind
	}
	upstream := map[string][]clickhouse.TopologyEdge{}
	for _, edge := range graph.Edges {
		upstream[edge.Target] = append(upstream[edge.Target], edge)
	}
	signalHint := signalHint(incident.Signals)
	queue := []RankedNode{{Service: incident.Service, ImpactScore: incident.AnomalyScore * 0.72, Depth: 1}}
	visited := map[string]float64{incident.Service: incident.AnomalyScore * 0.72}
	depths := map[string]int{incident.Service: 1}
	for len(queue) > 0 {
		current := queue[0]
		queue = queue[1:]
		for _, edge := range upstream[current.Service] {
			if strings.ToLower(nodeTypes[edge.Source]) != "service" {
				continue
			}
			depth := current.Depth + 1
			score := current.ImpactScore * edgeWeight(edge.DependencyType, signalHint) * 0.96
			score = score * (1 + math.Min(float64(depth-1), 4)*0.12)
			if prev, ok := visited[edge.Source]; ok && prev >= score {
				continue
			}
			visited[edge.Source] = score
			depths[edge.Source] = depth
			queue = append(queue, RankedNode{Service: edge.Source, ImpactScore: score, Depth: depth})
		}
	}
	items := make([]RankedNode, 0, len(visited))
	for service, score := range visited {
		depth := depths[service]
		if depth == 0 {
			depth = 1
		}
		items = append(items, RankedNode{
			Service:     service,
			ImpactScore: math.Round(score*100) / 100,
			Depth:       depth,
		})
	}
	sort.Slice(items, func(i, j int) bool {
		if items[i].ImpactScore == items[j].ImpactScore {
			return items[i].Depth > items[j].Depth
		}
		return items[i].ImpactScore > items[j].ImpactScore
	})
	return items
}

func edgeWeight(edgeType, signalHint string) float64 {
	switch edgeType {
	case "trace_rpc":
		return 1.0
	case "messaging_kafka":
		if signalHint == "kafka" {
			return 1.28
		}
		return 0.98
	case "trace_http":
		return 0.9
	case "database":
		if signalHint == "database" {
			return 1.2
		}
		return 0.82
	case "kubernetes_dns":
		return 0.6
	default:
		return 0.5
	}
}

func signalHint(signals []string) string {
	for _, signal := range signals {
		lowered := strings.ToLower(signal)
		if strings.Contains(lowered, "kafka") || strings.Contains(lowered, "queue") || strings.Contains(lowered, "consumer_lag") {
			return "kafka"
		}
		if strings.Contains(lowered, "db") || strings.Contains(lowered, "database") || strings.Contains(lowered, "postgres") {
			return "database"
		}
	}
	return "general"
}

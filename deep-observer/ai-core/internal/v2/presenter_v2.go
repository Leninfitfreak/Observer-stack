package v2

import (
	"context"
	"strings"
)

func (s *Service) BuildDashboard(ctx context.Context, req ScopeRequest) (DashboardResponse, error) {
	scope := s.normalizeScope(req)
	items, err := s.ListIncidents(ctx, scope, 200)
	if err != nil {
		return DashboardResponse{}, err
	}
	options := s.DiscoverFilters(ctx, scope)
	topology := s.ResolveTopology(ctx, scope)
	if len(items) == 0 {
		topology = Topology{Available: false, Nodes: []TopologyNode{}, Edges: []TopologyEdge{}}
	}

	summary := DashboardSummary{
		TotalIncidents: len(items),
		TopologyNodes:  len(topology.Nodes),
		TopologyEdges:  len(topology.Edges),
	}
	for _, item := range items {
		if strings.EqualFold(item.IncidentType, "predictive") {
			summary.PredictiveIncidents++
		} else {
			summary.ObservedIncidents++
		}
	}
	empty := len(items) == 0
	return DashboardResponse{
		NormalizedScope: scope,
		FilterOptions:   options,
		IncidentList:    items,
		ScopedTopology:  topology,
		Summary:         summary,
		Empty:           empty,
		Message:         ternary(empty, "No incidents match the selected scope.", ""),
	}, nil
}

func (s *Service) BuildIncidentView(ctx context.Context, incidentID string, req ScopeRequest) (IncidentViewResponse, error) {
	item, err := s.GetIncident(ctx, incidentID)
	if err != nil {
		return IncidentViewResponse{}, err
	}
	scope := s.normalizeScope(req)
	scope = s.incidentScopedRange(item, scope)
	direct, contextual, missing, sparse := s.ResolveEvidence(ctx, item, scope)
	topology := s.ResolveTopology(ctx, scope)

	reasoning := s.BuildReasoningView(item, sparse)
	state := "observed_full"
	if sparse {
		state = "predictive_sparse"
	}
	if reasoning.Status == "queued" || reasoning.Status == "pending" {
		state = "reasoning_queued"
	}
	if reasoning.Status == "running" {
		state = "reasoning_running"
	}
	if reasoning.Status == "failed" {
		state = "reasoning_failed"
	}
	if reasoning.Status == "completed" || reasoning.Status == "completed_with_fallback" {
		state = "reasoning_completed"
	}

	impacted := impactedFromTopology(topology, scope.Service)
	propagation := pathFromTopology(topology, scope.Service)
	if sparse {
		impacted = []string{}
		propagation = []string{}
	}
	observability := computeObservability(direct, contextual)
	related := s.ListRelatedIncidents(ctx, item.ID)
	response := IncidentViewResponse{
		Incident:           *item,
		NormalizedScope:    scope,
		State:              state,
		DirectEvidence:     direct,
		ContextualEvidence: contextual,
		MissingEvidence:    missing,
		Signals:            item.Signals,
		AnomalyScore:       item.AnomalyScore,
		IncidentTopology:   topology,
		ImpactedServices:   impacted,
		PropagationPath:    propagation,
		RelatedIncidents:   related,
		ObservabilityScore: observability,
		Sparse:             sparse,
		Reasoning:          reasoning,
	}
	if sparse {
		response.SparsePredictive = &SparsePredictiveView{
			Summary:            "Insufficient incident-scoped telemetry for RCA.",
			SignalSet:          item.Signals,
			AnomalyScore:       item.AnomalyScore,
			DirectEvidence:     direct,
			ContextualEvidence: contextual,
			NearestObserved:    s.ListNearestObserved(ctx, scope, item.ID),
			NextSteps: []string{
				"Collect traces, logs, and metrics for the selected incident scope.",
				"Re-run reasoning after direct telemetry is available.",
				"Review nearest observed incidents for concrete evidence.",
			},
		}
	}
	return response, nil
}

func impactedFromTopology(topology Topology, service string) []string {
	target := normalizeService(service)
	out := []string{}
	for _, edge := range topology.Edges {
		source := normalizeService(edge.Source)
		dst := normalizeService(edge.Target)
		if target != "" && source != target && dst != target {
			continue
		}
		if source == target {
			out = append(out, edge.Target)
		}
		if dst == target {
			out = append(out, edge.Source)
		}
	}
	return unique(out)
}

func pathFromTopology(topology Topology, service string) []string {
	target := normalizeService(service)
	out := []string{}
	for _, edge := range topology.Edges {
		if target != "" && normalizeService(edge.Source) != target && normalizeService(edge.Target) != target {
			continue
		}
		out = append(out, edge.Source+" -> "+edge.Target)
	}
	return unique(out)
}

func computeObservability(direct EvidenceDirect, contextual EvidenceContextual) float64 {
	score := 0.0
	if direct.RequestCount > 0 {
		score += 20
	}
	if direct.TraceSampleCount > 0 {
		score += 20
	}
	if direct.LogCount > 0 {
		score += 20
	}
	if len(direct.MetricHighlights) > 0 || direct.P95LatencyMs > 0 || direct.ErrorRate > 0 {
		score += 20
	}
	if contextual.Topology == "contextual" {
		score += 10
	}
	if contextual.Database == "contextual" || contextual.Messaging == "contextual" {
		score += 10
	}
	return score
}

func ternary(condition bool, whenTrue, whenFalse string) string {
	if condition {
		return whenTrue
	}
	return whenFalse
}

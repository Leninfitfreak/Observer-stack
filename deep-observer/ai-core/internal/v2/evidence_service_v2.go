package v2

import (
	"context"
	"strings"
	"time"

	"deep-observer/ai-core/internal/incidents"
)

func (s *Service) incidentScopedRange(item *incidents.Incident, scope Scope) Scope {
	scoped := scope
	if item.Scope.IncidentWindowStart != nil {
		scoped.Start = item.Scope.IncidentWindowStart.UTC()
	}
	if item.Scope.IncidentWindowEnd != nil {
		scoped.End = item.Scope.IncidentWindowEnd.UTC()
	}
	if scoped.End.Before(scoped.Start) || scoped.End.Equal(scoped.Start) {
		scoped.End = scoped.Start.Add(15 * time.Minute)
	}
	scoped.Cluster = firstNonEmpty(scoped.Cluster, item.Cluster, item.Scope.Cluster)
	scoped.Namespace = firstNonEmpty(scoped.Namespace, item.Namespace, item.Scope.Namespace)
	scoped.Service = normalizeService(firstNonEmpty(scoped.Service, item.Service, item.Scope.Service))
	return scoped
}

func (s *Service) ResolveEvidence(ctx context.Context, item *incidents.Incident, scope Scope) (EvidenceDirect, EvidenceContextual, []string, bool) {
	scoped := s.incidentScopedRange(item, scope)
	direct := EvidenceDirect{
		MetricHighlights: map[string]float64{},
		ErrorLogSamples:  []string{},
		TraceIDs:         []string{},
	}
	services, err := s.api.fetchServices(ctx, scoped)
	if err == nil {
		for _, svc := range services {
			if normalizeService(svc.ServiceName) != normalizeService(scoped.Service) {
				continue
			}
			direct.RequestCount = int64(svc.NumCalls)
			direct.ErrorRate = svc.ErrorRate
			direct.P95LatencyMs = svc.P99
			direct.MetricHighlights["service.p99_ms"] = svc.P99
			direct.MetricHighlights["service.error_rate"] = svc.ErrorRate
			direct.MetricHighlights["service.call_rate"] = svc.CallRate
			break
		}
	}
	if value, err := s.api.countSignal(ctx, scoped, "logs"); err == nil {
		direct.LogCount = value
	}
	if value, err := s.api.countSignal(ctx, scoped, "traces"); err == nil {
		direct.TraceSampleCount = value
	}
	if strings.EqualFold(firstNonEmpty(item.IncidentType, "observed"), "predictive") {
		snapshotSparse := item.TelemetrySnapshot.RequestCount == 0 &&
			item.TelemetrySnapshot.LogCount == 0 &&
			len(item.TelemetrySnapshot.TraceIDs) == 0 &&
			len(item.TelemetrySnapshot.MetricHighlights) == 0
		if snapshotSparse {
			direct.RequestCount = 0
			direct.LogCount = 0
			direct.TraceSampleCount = 0
			direct.ErrorRate = 0
			direct.P95LatencyMs = 0
			direct.MetricHighlights = map[string]float64{}
		}
	}
	topology := s.ResolveTopology(ctx, scoped)
	contextual := EvidenceContextual{
		Topology:  ternaryEvidence(topology.Available),
		Database:  "missing",
		Messaging: "missing",
	}
	for _, edge := range topology.Edges {
		targetType := inferNodeType(edge.Target)
		if targetType == "database" {
			contextual.Database = "contextual"
		}
		if targetType == "messaging" {
			contextual.Messaging = "contextual"
		}
	}
	missing := []string{}
	if direct.RequestCount == 0 && direct.TraceSampleCount == 0 {
		missing = append(missing, "No incident-scoped traces were found.")
	}
	if direct.LogCount == 0 {
		missing = append(missing, "No incident-scoped logs were found.")
	}
	if len(direct.MetricHighlights) == 0 && direct.ErrorRate == 0 && direct.P95LatencyMs == 0 {
		missing = append(missing, "No incident-scoped metrics were found.")
	}
	sparse := isSparsePredictive(item, direct)
	if sparse {
		contextual.Database = downgradeContextual(contextual.Database)
		contextual.Messaging = downgradeContextual(contextual.Messaging)
	}
	return direct, contextual, unique(missing), sparse
}

func isSparsePredictive(item *incidents.Incident, direct EvidenceDirect) bool {
	if !strings.EqualFold(firstNonEmpty(item.IncidentType, "observed"), "predictive") {
		return false
	}
	return direct.RequestCount == 0 &&
		direct.LogCount == 0 &&
		direct.TraceSampleCount == 0 &&
		len(direct.MetricHighlights) == 0
}

func downgradeContextual(value string) string {
	if value == "contextual" {
		return "contextual"
	}
	return "missing"
}

func ternaryEvidence(available bool) string {
	if available {
		return "contextual"
	}
	return "missing"
}

func unique(values []string) []string {
	seen := map[string]struct{}{}
	out := []string{}
	for _, value := range values {
		key := strings.TrimSpace(value)
		if key == "" {
			continue
		}
		if _, ok := seen[key]; ok {
			continue
		}
		seen[key] = struct{}{}
		out = append(out, key)
	}
	return out
}

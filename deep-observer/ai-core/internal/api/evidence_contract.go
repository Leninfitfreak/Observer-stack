package api

import (
	"context"
	"fmt"
	"strings"
	"time"

	"deep-observer/ai-core/internal/clickhouse"
	"deep-observer/ai-core/internal/config"
	"deep-observer/ai-core/internal/incidents"
)

func buildSelectedScopeEvidence(
	ctx context.Context,
	store *incidents.Store,
	chConfig config.ClickHouseConfig,
	project config.ProjectConfig,
	item *incidents.Incident,
	filters clickhouse.Filters,
) map[string]any {
	scope := normalizeEvidenceScope(item, filters)
	topology := loadEvidenceTopology(ctx, store, chConfig, project, scope)
	incidentTopology := scopeTopology(topology, scope.Service)
	directEvidence := map[string]any{
		"request_count":           item.TelemetrySnapshot.RequestCount,
		"log_count":               item.TelemetrySnapshot.LogCount,
		"trace_sample_count":      len(item.TelemetrySnapshot.TraceIDs),
		"error_rate":              item.TelemetrySnapshot.ErrorRate,
		"p95_latency_ms":          item.TelemetrySnapshot.P95LatencyMs,
		"cpu_utilization":         item.TelemetrySnapshot.CPUUtilization,
		"memory_utilization":      item.TelemetrySnapshot.MemoryUtilization,
		"metric_highlights":       item.TelemetrySnapshot.MetricHighlights,
		"timeline_event_count":    len(item.TimelineSummary),
		"direct_dependency_nodes": append([]string{}, item.DependencyChain...),
	}
	quality := buildEvidenceQuality(item, directEvidence, incidentTopology)
	contextual := map[string]any{
		"traces_present":    quality["traces"] != "missing",
		"logs_present":      quality["logs"] != "missing",
		"metrics_present":   quality["metrics"] != "missing",
		"database_present":  quality["database"] != "missing",
		"messaging_present": quality["messaging"] != "missing",
		"exception_present": quality["exceptions"] != "missing",
		"infra_present":     quality["infra"] != "missing",
		"topology_present":  quality["topology"] != "missing",
	}
	missingSignals := buildEvidenceMissing(scope, directEvidence, contextual, quality)
	observabilityScore := buildEvidenceObservabilityScore(scope, directEvidence, contextual, quality)
	reasoningReady := item.Reasoning != nil && strings.EqualFold(item.ReasoningStatus, "completed")
	supporting, weakening := buildEvidenceConfidenceFactors(directEvidence, contextual, quality, reasoningReady)

	return map[string]any{
		"scope": map[string]any{
			"incident_id":           item.ID,
			"cluster":               scope.Cluster,
			"namespace":             scope.Namespace,
			"service":               scope.Service,
			"incident_type":         item.IncidentType,
			"incident_window_start": scope.Start,
			"incident_window_end":   scope.End,
			"signal_set":            item.Signals,
			"anomaly_score":         item.AnomalyScore,
			"scope_complete":        item.Scope.ScopeComplete,
			"scope_warnings":        item.Scope.ScopeWarnings,
			"cluster_label":         firstNonEmpty(scope.Cluster, "Unknown cluster"),
			"namespace_label":       firstNonEmpty(scope.Namespace, "Unknown namespace"),
		},
		"direct_evidence":           directEvidence,
		"contextual_evidence":       contextual,
		"telemetry_audit":           map[string]any{"isSparse": directEvidence["request_count"].(int64) == 0 && directEvidence["log_count"].(int64) == 0 && directEvidence["trace_sample_count"].(int) == 0, "telemetryQuality": quality},
		"incident_topology":         incidentTopology,
		"telemetry_evidence":        buildEvidenceLines(scope, directEvidence, contextual, quality),
		"missing_telemetry_signals": missingSignals,
		"confidence_details": map[string]any{
			"score":              evidenceConfidence(item, reasoningReady),
			"level":              evidenceConfidenceLevel(evidenceConfidence(item, reasoningReady)),
			"explanation_text":   evidenceConfidenceText(reasoningReady),
			"supporting_factors": supporting,
			"weakening_factors":  weakening,
		},
		"trust_score": map[string]any{
			"score":   ternaryFloat(reasoningReady, evidenceConfidence(item, true), ternaryFloat(directEvidence["request_count"].(int64) > 0 || directEvidence["trace_sample_count"].(int) > 0, 0.65, 0.35)),
			"level":   evidenceConfidenceLevel(ternaryFloat(reasoningReady, evidenceConfidence(item, true), ternaryFloat(directEvidence["request_count"].(int64) > 0 || directEvidence["trace_sample_count"].(int) > 0, 0.65, 0.35))),
			"summary": ternaryString(reasoningReady, "Trust is based on the same selected-incident evidence contract as the rest of the page.", "Trust currently reflects evidence coverage only. RCA trust and confidence will be available after a manual reasoning run."),
		},
		"observability_score": observabilityScore,
		"impacted_services":   evidenceImpacts(item.Impacts),
		"propagation_path":    evidencePropagation(item, incidentTopology),
		"reasoning_ready":     reasoningReady,
		"reasoning_status":    firstNonEmpty(strings.ToLower(item.ReasoningStatus), "not_generated"),
		"reasoning_summary":   evidenceReasoningSummary(item, reasoningReady),
		"incident_summary":    evidenceIncidentSummary(item, directEvidence),
	}
}

type evidenceScope struct {
	Cluster   string
	Namespace string
	Service   string
	Start     time.Time
	End       time.Time
}

func normalizeEvidenceScope(item *incidents.Incident, filters clickhouse.Filters) evidenceScope {
	start := filters.Start
	if start.IsZero() {
		if item.Scope.IncidentWindowStart != nil {
			start = item.Scope.IncidentWindowStart.UTC()
		} else {
			start = item.Timestamp.Add(-15 * time.Minute)
		}
	}
	end := filters.End
	if end.IsZero() {
		if item.Scope.IncidentWindowEnd != nil {
			end = item.Scope.IncidentWindowEnd.UTC()
		} else {
			end = item.Timestamp.Add(5 * time.Minute)
		}
	}
	return evidenceScope{
		Cluster:   firstNonEmpty(filters.Cluster, item.Cluster, item.Scope.Cluster),
		Namespace: firstNonEmpty(filters.Namespace, item.Namespace, item.Scope.Namespace),
		Service:   firstNonEmpty(filters.Service, item.Service, item.Scope.Service),
		Start:     start,
		End:       end,
	}
}

func loadEvidenceTopology(ctx context.Context, store *incidents.Store, chConfig config.ClickHouseConfig, project config.ProjectConfig, scope evidenceScope) clickhouse.TopologyGraph {
	graph := emptyTopologyGraph()
	client, err := clickhouse.NewClient(ctx, chConfig)
	if err == nil {
		defer client.Close()
		graph, err = client.BuildTopology(ctx, clickhouse.Filters{
			Cluster:   scope.Cluster,
			Namespace: scope.Namespace,
			Service:   scope.Service,
			Start:     scope.Start,
			End:       scope.End,
		})
		if err == nil {
			graph = dedupeGraph(sanitizeApplicationGraph(graph))
		}
	}
	if len(graph.Edges) == 0 {
		if fallback, incErr := buildGraphFromIncidentChainsFallback(ctx, store, project.ProjectID, scope.Cluster, scope.Namespace, scope.Service); incErr == nil {
			graph = dedupeGraph(sanitizeApplicationGraph(fallback))
		}
	}
	if scope.Service != "" {
		graph = filterGraphByServiceChain(graph, scope.Service)
	}
	return dedupeGraph(graph)
}

func scopeTopology(graph clickhouse.TopologyGraph, service string) map[string]any {
	target := normalizeServiceName(service)
	seen := map[string]struct{}{}
	edges := []clickhouse.TopologyEdge{}
	for _, edge := range graph.Edges {
		if target == "" || normalizeServiceName(edge.Source) == target || normalizeServiceName(edge.Target) == target {
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
	return map[string]any{"available": len(nodes) > 0 || len(edges) > 0, "nodes": nodes, "edges": edges}
}

func buildEvidenceQuality(item *incidents.Incident, direct map[string]any, topology map[string]any) map[string]string {
	deps := strings.ToLower(strings.Join(item.DependencyChain, " "))
	metricNames := strings.ToLower(fmt.Sprintf("%v", item.TelemetrySnapshot.MetricHighlights))
	edges := strings.ToLower(fmt.Sprintf("%v", topology["edges"]))
	quality := map[string]string{"traces": "missing", "logs": "missing", "metrics": "missing", "database": "missing", "messaging": "missing", "exceptions": "missing", "infra": "missing", "topology": "missing"}
	if direct["request_count"].(int64) > 0 || direct["trace_sample_count"].(int) > 0 {
		quality["traces"] = "present"
	}
	if direct["log_count"].(int64) > 0 {
		quality["logs"] = "present"
	}
	if len(item.TelemetrySnapshot.MetricHighlights) > 0 {
		quality["metrics"] = "present"
	}
	if strings.Contains(deps, "db:") || strings.Contains(metricNames, "db") || strings.Contains(metricNames, "database") {
		quality["database"] = "present"
	} else if strings.Contains(edges, "db:") {
		quality["database"] = "contextual"
	}
	if strings.Contains(deps, "messaging:") || strings.Contains(metricNames, "messag") || strings.Contains(metricNames, "kafka") {
		quality["messaging"] = "present"
	} else if strings.Contains(edges, "messaging:") {
		quality["messaging"] = "contextual"
	}
	if len(item.TelemetrySnapshot.ErrorLogs) > 0 {
		quality["exceptions"] = "present"
	}
	if item.TelemetrySnapshot.CPUUtilization > 0 || item.TelemetrySnapshot.MemoryUtilization > 0 {
		quality["infra"] = "present"
	}
	if len(item.DependencyChain) > 0 {
		quality["topology"] = "present"
	} else if topology["available"].(bool) {
		quality["topology"] = "contextual"
	}
	return quality
}

func buildEvidenceMissing(scope evidenceScope, direct map[string]any, contextual map[string]any, quality map[string]string) []string {
	out := []string{}
	if direct["request_count"].(int64) == 0 && direct["trace_sample_count"].(int) == 0 {
		out = append(out, "No incident-scoped traces were found.")
	}
	if direct["log_count"].(int64) == 0 {
		out = append(out, "No incident-scoped logs were found.")
	}
	if quality["metrics"] == "missing" {
		out = append(out, "No incident-scoped service metrics were found.")
	}
	if quality["exceptions"] == "missing" {
		out = append(out, "No exception evidence was found for the selected incident scope.")
	}
	if quality["infra"] == "missing" {
		out = append(out, "No runtime host/container evidence was correlated for the selected incident scope.")
	}
	if scope.Namespace == "" {
		out = append(out, "Incident scope is incomplete: namespace missing from incident scope.")
	}
	return uniqueEvidenceStrings(out)
}

func buildEvidenceObservabilityScore(scope evidenceScope, direct map[string]any, contextual map[string]any, quality map[string]string) float64 {
	score := 0.0
	if direct["request_count"].(int64) > 0 || direct["trace_sample_count"].(int) > 0 {
		score += 24
	} else if quality["traces"] == "contextual" {
		score += 10
	} else {
		score += 6
	}
	if direct["log_count"].(int64) > 0 {
		score += 18
	} else {
		score += 4
	}
	if quality["metrics"] == "present" {
		score += 18
	} else {
		score += 4
	}
	score += ternaryFloat(contextual["database_present"].(bool), ternaryFloat(quality["database"] == "present", 10, 6), 4)
	score += ternaryFloat(contextual["messaging_present"].(bool), ternaryFloat(quality["messaging"] == "present", 10, 6), 4)
	score += ternaryFloat(contextual["exception_present"].(bool), 10, 4)
	score += ternaryFloat(contextual["infra_present"].(bool), 5, 2)
	score += ternaryFloat(contextual["topology_present"].(bool), ternaryFloat(quality["topology"] == "present", 5, 3), 2)
	if scope.Namespace == "" && score > 45 {
		score = 45
	}
	return score
}

func buildEvidenceLines(scope evidenceScope, direct map[string]any, contextual map[string]any, quality map[string]string) []string {
	out := []string{
		fmt.Sprintf("Selected incident scope: %s / %s / %s", firstNonEmpty(scope.Service, "Unknown service"), firstNonEmpty(scope.Namespace, "Unknown namespace"), firstNonEmpty(scope.Cluster, "Unknown cluster")),
		fmt.Sprintf("Incident-scoped requests: %d", direct["request_count"].(int64)),
		fmt.Sprintf("Incident-scoped logs: %d", direct["log_count"].(int64)),
		fmt.Sprintf("Incident-scoped trace samples: %d", direct["trace_sample_count"].(int)),
	}
	for _, key := range []string{"traces", "logs", "metrics", "database", "messaging", "exceptions", "infra", "topology"} {
		out = append(out, fmt.Sprintf("%s evidence quality: %s", key, quality[key]))
	}
	if contextual["database_present"].(bool) && quality["database"] == "contextual" {
		out = append(out, "Contextual database evidence is present in the scoped service window.")
	}
	if contextual["messaging_present"].(bool) && quality["messaging"] == "contextual" {
		out = append(out, "Contextual messaging evidence is present in the scoped service window.")
	}
	if contextual["topology_present"].(bool) {
		out = append(out, ternaryString(quality["topology"] == "present", "Dependency topology is available for this incident scope.", "Contextual dependency topology is available for this incident scope."))
	}
	return out
}

func buildEvidenceConfidenceFactors(direct map[string]any, contextual map[string]any, quality map[string]string, ready bool) ([]string, []string) {
	if !ready {
		return []string{
				fmt.Sprintf("Direct evidence currently shows %d requests, %d logs, and %d sampled traces.", direct["request_count"].(int64), direct["log_count"].(int64), direct["trace_sample_count"].(int)),
			},
			[]string{"RCA confidence is unavailable until reasoning is generated."}
	}
	supporting := []string{}
	weakening := []string{}
	if direct["request_count"].(int64) > 0 || direct["trace_sample_count"].(int) > 0 {
		supporting = append(supporting, fmt.Sprintf("Incident-scoped trace/request evidence is present (%d requests, %d sampled traces).", direct["request_count"].(int64), direct["trace_sample_count"].(int)))
	} else if contextual["traces_present"].(bool) {
		supporting = append(supporting, "Broader scoped trace evidence is present, but it is contextual rather than direct incident evidence.")
	} else {
		weakening = append(weakening, "No trace evidence was found for the selected incident scope.")
	}
	if direct["log_count"].(int64) > 0 {
		supporting = append(supporting, fmt.Sprintf("Incident-scoped logs are present (%d events).", direct["log_count"].(int64)))
	} else {
		weakening = append(weakening, "No logs were found for the selected incident scope.")
	}
	if quality["database"] == "present" {
		supporting = append(supporting, "Database evidence is directly attached to the selected incident.")
	} else if quality["database"] == "contextual" {
		supporting = append(supporting, "Database evidence is available as contextual service-window evidence.")
	}
	if quality["messaging"] == "present" {
		supporting = append(supporting, "Messaging evidence is directly attached to the selected incident.")
	} else if quality["messaging"] == "contextual" {
		supporting = append(supporting, "Messaging evidence is available as contextual service-window evidence.")
	}
	return uniqueEvidenceStrings(supporting), uniqueEvidenceStrings(weakening)
}

func evidenceImpacts(impacts []incidents.IncidentImpact) []string {
	out := []string{}
	for _, impact := range impacts {
		if strings.EqualFold(impact.ImpactType, "root") {
			continue
		}
		out = append(out, impact.Service)
	}
	return uniqueEvidenceStrings(out)
}

func evidencePropagation(item *incidents.Incident, topology map[string]any) []string {
	if item.Reasoning != nil && len(item.Reasoning.PropagationPath) > 0 {
		return uniqueEvidenceStrings(item.Reasoning.PropagationPath)
	}
	if len(item.DependencyChain) > 0 {
		return uniqueEvidenceStrings(item.DependencyChain)
	}
	edges, _ := topology["edges"].([]clickhouse.TopologyEdge)
	out := []string{}
	for _, edge := range edges {
		out = append(out, fmt.Sprintf("%s -> %s", edge.Source, edge.Target))
	}
	return uniqueEvidenceStrings(out)
}

func evidenceConfidence(item *incidents.Incident, ready bool) float64 {
	if ready && item.Reasoning != nil {
		return item.Reasoning.ConfidenceScore
	}
	return item.PredictiveConfidence
}

func evidenceConfidenceLevel(score float64) string {
	switch {
	case score >= 0.75:
		return "high"
	case score >= 0.45:
		return "medium"
	case score > 0:
		return "low"
	default:
		return "pending"
	}
}

func evidenceConfidenceText(ready bool) string {
	if ready {
		return "Confidence is based on the selected incident scope first, with broader scoped evidence labeled separately as contextual support."
	}
	return "Reasoning has not been generated for this incident yet. Confidence will be computed after a manual reasoning run from the same selected-incident evidence basis shown on this page."
}

func evidenceReasoningSummary(item *incidents.Incident, ready bool) string {
	if !ready {
		return "Reasoning has not been generated for this incident yet. The page is currently showing evidence only, not a completed RCA."
	}
	if item.Reasoning != nil && strings.TrimSpace(item.Reasoning.RootCause) != "" {
		return item.Reasoning.RootCause
	}
	return "Reasoning completed."
}

func evidenceIncidentSummary(item *incidents.Incident, direct map[string]any) string {
	base := fmt.Sprintf("%s incident on %s with anomaly score %.2f.", firstNonEmpty(item.IncidentType, "observed"), firstNonEmpty(item.Service, "unknown service"), item.AnomalyScore)
	if direct["request_count"].(int64) == 0 && direct["log_count"].(int64) == 0 && direct["trace_sample_count"].(int) == 0 {
		return base + " Direct incident telemetry is sparse and contextual evidence is labeled separately."
	}
	return base + " Panels below use the same selected-incident evidence model."
}

func uniqueEvidenceStrings(values []string) []string {
	seen := map[string]struct{}{}
	out := make([]string, 0, len(values))
	for _, value := range values {
		value = strings.TrimSpace(value)
		if value == "" {
			continue
		}
		if _, ok := seen[value]; ok {
			continue
		}
		seen[value] = struct{}{}
		out = append(out, value)
	}
	return out
}

func ternaryString(condition bool, yes, no string) string {
	if condition {
		return yes
	}
	return no
}

func ternaryFloat(condition bool, yes, no float64) float64 {
	if condition {
		return yes
	}
	return no
}

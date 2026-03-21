package truth

import (
	"context"
	"fmt"
	"strings"
	"time"

	"deep-observer/ai-core/internal/clickhouse"
	"deep-observer/ai-core/internal/incidents"
)

func (s *Service) collectTelemetry(ctx context.Context, item *incidents.Incident, scope NormalizedScope) map[string]any {
	incidentScope := incidentScopedScope(item, scope)
	direct := s.buildDirectEvidenceFromSynapse(ctx, item, incidentScope)
	graph := s.ResolveTopology(ctx, incidentScope)
	scopedGraph := scopeTopology(graph, scope.Service)
	missing := buildMissingEvidence(item, scope, direct, scopedGraph)
	quality := classifyEvidence(item, direct, scopedGraph)
	contextual := buildContextualEvidence(quality, scopedGraph)
	coverage := buildCoverage(scope, direct, quality, scopedGraph)
	validation, _ := s.store.GetReasoningValidation(ctx, item.ID)
	reasoning := reasoningView(item, quality)

	related, _ := s.store.ListCorrelatedIncidents(ctx, item.ID, 24*time.Hour, 8)
	history, _ := s.ListIncidents(ctx, NormalizedScope{
		Cluster:   scope.Cluster,
		Namespace: scope.Namespace,
		Service:   scope.Service,
		Start:     scope.Start.Add(-72 * time.Hour),
		End:       scope.End,
	}, 12)
	sparsePredictiveState := isSparsePredictiveIncident(item, direct, quality)
	sparsePredictiveContract := buildSparsePredictiveContract(item, scope, direct, quality, history)
	reasoningAllowed := !sparsePredictiveState && hasDirectEvidence(direct)
	impacted := impactedServicesFromTopology(scope, scopedGraph)
	propagation := propagationPath(item, scopedGraph)
	causal := toAnyStrings(item.Reasoning, item.DependencyChain)
	if sparsePredictiveState {
		impacted = []string{}
		propagation = []string{}
		causal = []string{}
	}

	return map[string]any{
		"incident":                   item,
		"scope":                      buildIncidentScope(item, scope),
		"normalized_scope":           buildIncidentScope(item, scope),
		"direct_evidence":            direct,
		"contextual_evidence":        contextual,
		"missing_evidence":           missing,
		"telemetry_audit":            map[string]any{"telemetryQuality": quality, "isSparse": direct["request_count"].(int64) == 0 && direct["log_count"].(int64) == 0 && direct["trace_sample_count"].(int) == 0},
		"incident_topology":          scopedGraph,
		"telemetry_evidence":         buildTelemetryEvidence(scope, direct, quality, scopedGraph),
		"observability_coverage":     coverage,
		"observability_score":        coverage["score"],
		"impacted_services":          impacted,
		"propagation_path":           propagation,
		"causal_chain":               causal,
		"confidence_details":         reasoning["confidence_details"],
		"trust_score":                reasoning["trust_score"],
		"reasoning_status":           reasoning["status"],
		"reasoning_ready":            item.Reasoning != nil && isCompletedReasoningStatus(item.ReasoningStatus),
		"reasoning_execution_mode":   reasoning["execution_mode"],
		"reasoning_failure_summary":  reasoning["failure_summary"],
		"reasoning_view":             reasoning,
		"reasoning_validation_status": validationStatus(validation),
		"reasoning_validation_summary": validationSummary(validation),
		"unsupported_claims_count":   unsupportedClaimsCount(validation),
		"unsupported_claims":         unsupportedClaims(validation),
		"reasoning_normalized":       validationNormalized(validation),
		"reasoning_binding_level":    validationBinding(validation),
		"reasoning_corrections":      validationCorrections(validation),
		"raw_model_output_summary":   rawModelOutputSummary(validation),
		"incident_summary":           incidentSummary(item, direct),
		"reasoning_summary":          reasoning["summary"],
		"signal_summary":             signalSummary(item, quality),
		"log_summary":                logSummaryFromDirect(item, direct),
		"impact_summary":             impactSummaryFromScopedEvidence(item, scope, scopedGraph),
		"decision_panel":             reasoning["decision_panel"],
		"prioritized_actions":        prioritizedActions(item, quality),
		"runbook":                    runbook(item, quality),
		"observability_gaps":         observabilityGaps(scope, quality, missing),
		"incident_timeline":          incidentTimeline(item),
		"telemetry_chart":            telemetryChart(item),
		"related_incidents":          related,
		"incident_history":           normalizeHistory(item.ID, history),
		"cluster_context":            clusterContext(history),
		"change_timeline":            changeTimeline(item),
		"slo_status":                 []string{},
		"service_health_score":       serviceHealthScore(item),
		"missing_telemetry_signals":  missing,
		"sparse_predictive_state":    sparsePredictiveState,
		"sparse_predictive_contract": sparsePredictiveContract,
		"reasoning_allowed":          reasoningAllowed,
	}
}

func buildSparsePredictiveContract(
	item *incidents.Incident,
	scope NormalizedScope,
	direct map[string]any,
	quality map[string]string,
	history []incidents.Incident,
) map[string]any {
	metricCount := 0
	switch values := direct["metric_highlights"].(type) {
	case map[string]any:
		metricCount = len(values)
	case map[string]float64:
		metricCount = len(values)
	}
	relatedObserved := []map[string]any{}
	for _, candidate := range history {
		if candidate.ID == item.ID || !strings.EqualFold(candidate.IncidentType, "observed") {
			continue
		}
		relatedObserved = append(relatedObserved, map[string]any{
			"incident_id": candidate.ID,
			"timestamp":   candidate.Timestamp,
			"service":     candidate.Service,
			"severity":    candidate.Severity,
		})
		if len(relatedObserved) >= 3 {
			break
		}
	}
	contextualFlags := map[string]bool{
		"database":  strings.EqualFold(quality["database"], "contextual") || strings.EqualFold(quality["database"], "direct"),
		"messaging": strings.EqualFold(quality["messaging"], "contextual") || strings.EqualFold(quality["messaging"], "direct"),
		"topology":  strings.EqualFold(quality["topology"], "contextual") || strings.EqualFold(quality["topology"], "direct"),
	}
	return map[string]any{
		"incident_id":            item.ID,
		"incident_type":          item.IncidentType,
		"scope":                  buildIncidentScope(item, scope),
		"anomaly_score":          item.AnomalyScore,
		"signals":                item.Signals,
		"direct_evidence_counts": map[string]any{"requests": direct["request_count"], "logs": direct["log_count"], "traces": direct["trace_sample_count"], "metrics": metricCount},
		"contextual_flags":       contextualFlags,
		"summary":                "Insufficient incident-scoped telemetry for RCA.",
		"guidance": []string{
			"Collect traces, logs, and service metrics for the selected incident scope.",
			"Re-run reasoning after incident-scoped telemetry becomes available.",
			"Review the nearest observed incident for concrete RCA evidence.",
		},
		"related_observed_incidents": relatedObserved,
	}
}

func validationStatus(validation *incidents.ReasoningValidation) string {
	if validation == nil {
		return ""
	}
	return strings.TrimSpace(validation.ValidationResult)
}

func unsupportedClaimsCount(validation *incidents.ReasoningValidation) int {
	if validation == nil {
		return 0
	}
	return validation.UnsupportedClaimsCount
}

func unsupportedClaims(validation *incidents.ReasoningValidation) []string {
	if validation == nil {
		return []string{}
	}
	return validation.UnsupportedStatements
}

func validationNormalized(validation *incidents.ReasoningValidation) bool {
	return validation != nil && validation.NormalizedOutput
}

func validationBinding(validation *incidents.ReasoningValidation) string {
	if validation == nil {
		return ""
	}
	return strings.TrimSpace(validation.EvidenceBinding)
}

func validationCorrections(validation *incidents.ReasoningValidation) []string {
	if validation == nil {
		return []string{}
	}
	return validation.Corrections
}

func rawModelOutputSummary(validation *incidents.ReasoningValidation) map[string]any {
	if validation == nil {
		return map[string]any{}
	}
	return validation.RawModelOutputSummary
}

func validationSummary(validation *incidents.ReasoningValidation) string {
	if validation == nil {
		return ""
	}
	if validation.NormalizedOutput {
		return "Model output contained unsupported claims; corrected using evidence validation."
	}
	if strings.EqualFold(validation.ValidationResult, "partial") {
		return "Model output was partially supported and constrained to selected-incident evidence."
	}
	return ""
}

func telemetryChart(item *incidents.Incident) []map[string]any {
	out := []map[string]any{}
	for _, event := range item.TimelineSummary {
		if event.Value == 0 {
			continue
		}
		out = append(out, map[string]any{
			"timestamp": event.Timestamp,
			"kind":      firstNonEmpty(event.Kind, "telemetry"),
			"value":     event.Value,
		})
	}
	return out
}

func (s *Service) buildDirectEvidenceFromSynapse(ctx context.Context, item *incidents.Incident, scope NormalizedScope) map[string]any {
	summary := s.fetchEvidenceFromSynapse(ctx, scope, item.Service)
	if strings.EqualFold(firstNonEmpty(item.IncidentType, "observed"), "predictive") {
		snapshotSparse := item.TelemetrySnapshot.RequestCount == 0 &&
			item.TelemetrySnapshot.LogCount == 0 &&
			len(item.TelemetrySnapshot.TraceIDs) == 0 &&
			len(item.TelemetrySnapshot.MetricHighlights) == 0
		if snapshotSparse {
			summary.RequestCount = 0
			summary.LogCount = 0
			summary.TraceCount = 0
			summary.ErrorLogSamples = []string{}
			summary.TraceIDs = []string{}
			summary.MetricHighlights = map[string]float64{}
			summary.ErrorRate = 0
			summary.P95LatencyMs = 0
		}
	}
	if summary.TraceCount == 0 && len(summary.TraceIDs) > 0 {
		summary.TraceCount = len(summary.TraceIDs)
	}
	dependencyNodes := topologyDependencyNodes(scope, s.ResolveTopology(ctx, scope))
	return map[string]any{
		"request_count":           summary.RequestCount,
		"log_count":               summary.LogCount,
		"trace_sample_count":      summary.TraceCount,
		"error_rate":              summary.ErrorRate,
		"p95_latency_ms":          summary.P95LatencyMs,
		"cpu_utilization":         0.0,
		"memory_utilization":      0.0,
		"metric_highlights":       summary.MetricHighlights,
		"timeline_event_count":    len(item.TimelineSummary),
		"direct_dependency_nodes": dependencyNodes,
		"error_log_samples":       summary.ErrorLogSamples,
		"trace_ids":               summary.TraceIDs,
	}
}

func incidentScopedScope(item *incidents.Incident, scope NormalizedScope) NormalizedScope {
	scoped := scope
	scoped.Start = incidentWindowStart(item, scope.Start)
	scoped.End = incidentWindowEnd(item, scope.End)
	if scoped.End.Before(scoped.Start) {
		scoped.End = scoped.Start.Add(15 * time.Minute)
	}
	if scoped.Start.Equal(scoped.End) {
		scoped.End = scoped.Start.Add(15 * time.Minute)
	}
	scoped.Cluster = firstNonEmpty(scoped.Cluster, item.Cluster, item.Scope.Cluster)
	scoped.Namespace = firstNonEmpty(scoped.Namespace, item.Namespace, item.Scope.Namespace)
	scoped.Service = normalizeServiceName(firstNonEmpty(scoped.Service, item.Service, item.Scope.Service))
	return scoped
}

func hasDirectEvidence(direct map[string]any) bool {
	if direct["request_count"].(int64) > 0 || direct["log_count"].(int64) > 0 || direct["trace_sample_count"].(int) > 0 {
		return true
	}
	switch values := direct["metric_highlights"].(type) {
	case map[string]any:
		return len(values) > 0
	case map[string]float64:
		return len(values) > 0
	default:
		return false
	}
}

func topologyDependencyNodes(scope NormalizedScope, graph clickhouse.TopologyGraph) []string {
	target := normalizeServiceName(scope.Service)
	out := []string{}
	for _, edge := range graph.Edges {
		source := normalizeServiceName(edge.Source)
		targetNode := normalizeServiceName(edge.Target)
		if target != "" && source != target && targetNode != target {
			continue
		}
		out = append(out, canonicalNarrativeValue(edge.Source))
		out = append(out, canonicalNarrativeValue(edge.Target))
	}
	return uniqueStrings(out)
}

func buildIncidentScope(item *incidents.Incident, scope NormalizedScope) map[string]any {
	return map[string]any{
		"incident_id":           item.ID,
		"cluster":               firstNonEmpty(scope.Cluster, item.Cluster, item.Scope.Cluster),
		"namespace":             firstNonEmpty(scope.Namespace, item.Namespace, item.Scope.Namespace),
		"service":               firstNonEmpty(scope.Service, item.Service, item.Scope.Service),
		"incident_type":         item.IncidentType,
		"incident_window_start": incidentWindowStart(item, scope.Start),
		"incident_window_end":   incidentWindowEnd(item, scope.End),
		"signal_set":            item.Signals,
		"anomaly_score":         item.AnomalyScore,
		"scope_complete":        item.Scope.ScopeComplete,
		"scope_warnings":        item.Scope.ScopeWarnings,
		"cluster_label":         firstNonEmpty(scope.Cluster, item.Cluster, item.Scope.Cluster, "Unknown cluster"),
		"namespace_label":       firstNonEmpty(scope.Namespace, item.Namespace, item.Scope.Namespace, "Unknown namespace"),
	}
}

func incidentWindowStart(item *incidents.Incident, fallback time.Time) time.Time {
	if item.Scope.IncidentWindowStart != nil {
		return item.Scope.IncidentWindowStart.UTC()
	}
	return fallback
}

func incidentWindowEnd(item *incidents.Incident, fallback time.Time) time.Time {
	if item.Scope.IncidentWindowEnd != nil {
		return item.Scope.IncidentWindowEnd.UTC()
	}
	return fallback
}

func classifyEvidence(item *incidents.Incident, direct map[string]any, scopedGraph map[string]any) map[string]string {
	quality := map[string]string{
		"traces":     "missing",
		"logs":       "missing",
		"metrics":    "missing",
		"database":   "missing",
		"messaging":  "missing",
		"exceptions": "missing",
		"infra":      "missing",
		"topology":   "missing",
	}
	if direct["trace_sample_count"].(int) > 0 {
		quality["traces"] = "direct"
	}
	hasDirectSignals := quality["traces"] == "direct" || direct["log_count"].(int64) > 0 || direct["request_count"].(int64) > 0
	if direct["log_count"].(int64) > 0 {
		quality["logs"] = "direct"
	}
	metricHighlightCount := 0
	switch values := direct["metric_highlights"].(type) {
	case map[string]any:
		metricHighlightCount = len(values)
	case map[string]float64:
		metricHighlightCount = len(values)
	}
	if metricHighlightCount > 0 || direct["p95_latency_ms"].(float64) > 0 || direct["error_rate"].(float64) > 0 {
		quality["metrics"] = "direct"
		hasDirectSignals = true
	}
	dependencyNodes := []string{}
	if values, ok := direct["direct_dependency_nodes"].([]string); ok {
		dependencyNodes = values
	}
	deps := strings.ToLower(strings.Join(dependencyNodes, " "))
	if strings.Contains(deps, "db:") {
		quality["database"] = "direct"
	}
	if strings.Contains(deps, "messaging:") {
		quality["messaging"] = "direct"
	}
	if values, ok := direct["error_log_samples"].([]string); ok && len(values) > 0 {
		quality["exceptions"] = "direct"
	}
	if direct["cpu_utilization"].(float64) > 0 || direct["memory_utilization"].(float64) > 0 {
		quality["infra"] = "direct"
	}
	edgesText := fmt.Sprintf("%v", scopedGraph["edges"])
	if quality["database"] == "missing" && strings.Contains(strings.ToLower(edgesText), "db:") {
		quality["database"] = "contextual"
	}
	if quality["messaging"] == "missing" && strings.Contains(strings.ToLower(edgesText), "messaging:") {
		quality["messaging"] = "contextual"
	}
	if len(dependencyNodes) > 0 && hasDirectSignals {
		quality["topology"] = "direct"
	} else if available, _ := scopedGraph["available"].(bool); available {
		quality["topology"] = "contextual"
	}
	if !hasDirectSignals {
		if quality["database"] == "direct" {
			quality["database"] = "contextual"
		}
		if quality["messaging"] == "direct" {
			quality["messaging"] = "contextual"
		}
	}
	return quality
}

func buildContextualEvidence(quality map[string]string, scopedGraph map[string]any) map[string]any {
	return map[string]any{
		"traces":     evidenceBucket(quality["traces"]),
		"logs":       evidenceBucket(quality["logs"]),
		"metrics":    evidenceBucket(quality["metrics"]),
		"database":   evidenceBucket(quality["database"]),
		"messaging":  evidenceBucket(quality["messaging"]),
		"exceptions": evidenceBucket(quality["exceptions"]),
		"infra":      evidenceBucket(quality["infra"]),
		"topology":   evidenceBucket(quality["topology"]),
		"topology_available": scopedGraph["available"],
	}
}

func evidenceBucket(value string) string {
	switch value {
	case "direct", "contextual":
		return value
	default:
		return "missing"
	}
}

func buildMissingEvidence(item *incidents.Incident, scope NormalizedScope, direct map[string]any, scopedGraph map[string]any) []string {
	missing := []string{}
	if direct["request_count"].(int64) == 0 && direct["trace_sample_count"].(int) == 0 {
		missing = append(missing, "No incident-scoped traces were found.")
	}
	if direct["log_count"].(int64) == 0 {
		missing = append(missing, "No incident-scoped logs were found.")
	}
	metricHighlightCount := 0
	switch values := direct["metric_highlights"].(type) {
	case map[string]any:
		metricHighlightCount = len(values)
	case map[string]float64:
		metricHighlightCount = len(values)
	}
	if metricHighlightCount == 0 && direct["p95_latency_ms"].(float64) == 0 && direct["error_rate"].(float64) == 0 {
		missing = append(missing, "No incident-scoped service metrics were found.")
	}
	errorSamples, _ := direct["error_log_samples"].([]string)
	if len(errorSamples) == 0 {
		missing = append(missing, "No exception evidence was found for the selected incident scope.")
	}
	if direct["cpu_utilization"].(float64) == 0 && direct["memory_utilization"].(float64) == 0 {
		missing = append(missing, "No runtime host/container evidence was correlated for the selected incident scope.")
	}
	if available, _ := scopedGraph["available"].(bool); !available && len(item.DependencyChain) == 0 {
		missing = append(missing, "No topology data is available for the selected scope.")
	}
	if firstNonEmpty(scope.Namespace, item.Namespace, item.Scope.Namespace) == "" {
		missing = append(missing, "Incident scope is incomplete: namespace missing from incident scope.")
	}
	return uniqueStrings(missing)
}

func buildTelemetryEvidence(scope NormalizedScope, direct map[string]any, quality map[string]string, scopedGraph map[string]any) []string {
	lines := []string{
		fmt.Sprintf("Selected incident scope: %s / %s / %s", firstNonEmpty(scope.Service, "Unknown service"), firstNonEmpty(scope.Namespace, "Unknown namespace"), firstNonEmpty(scope.Cluster, "Unknown cluster")),
		fmt.Sprintf("Incident-scoped requests: %d", direct["request_count"].(int64)),
		fmt.Sprintf("Incident-scoped logs: %d", direct["log_count"].(int64)),
		fmt.Sprintf("Incident-scoped trace samples: %d", direct["trace_sample_count"].(int)),
	}
	for _, key := range []string{"traces", "logs", "metrics", "database", "messaging", "exceptions", "infra", "topology"} {
		lines = append(lines, fmt.Sprintf("%s evidence: %s", key, quality[key]))
	}
	if available, _ := scopedGraph["available"].(bool); available {
		lines = append(lines, "Scoped topology is available for the selected incident.")
	}
	return lines
}

func buildCoverage(scope NormalizedScope, direct map[string]any, quality map[string]string, scopedGraph map[string]any) map[string]any {
	score := 0.0
	score += scoreForQuality(quality["traces"], 24, 8, 2)
	score += scoreForQuality(quality["logs"], 18, 6, 2)
	score += scoreForQuality(quality["metrics"], 18, 6, 2)
	score += scoreForQuality(quality["database"], 10, 4, 2)
	score += scoreForQuality(quality["messaging"], 10, 4, 2)
	score += scoreForQuality(quality["exceptions"], 10, 4, 2)
	score += scoreForQuality(quality["infra"], 5, 3, 1)
	score += scoreForQuality(quality["topology"], 5, 3, 1)
	if firstNonEmpty(scope.Namespace) == "" && score > 45 {
		score = 45
	}
	return map[string]any{
		"score": score,
		"traces":     quality["traces"],
		"logs":       quality["logs"],
		"metrics":    quality["metrics"],
		"database":   quality["database"],
		"messaging":  quality["messaging"],
		"exceptions": quality["exceptions"],
		"infra":      quality["infra"],
		"topology":   quality["topology"],
		"requests":   direct["request_count"],
		"log_count":  direct["log_count"],
		"trace_samples": direct["trace_sample_count"],
		"topology_available": scopedGraph["available"],
	}
}

func scoreForQuality(value string, direct, contextual, missing float64) float64 {
	switch value {
	case "direct":
		return direct
	case "contextual":
		return contextual
	default:
		return missing
	}
}

func impactedServices(item *incidents.Incident) []string {
	values := []string{}
	for _, impact := range item.Impacts {
		if strings.EqualFold(impact.ImpactType, "root") {
			continue
		}
		if strings.TrimSpace(impact.Service) != "" {
			values = append(values, canonicalNarrativeValue(impact.Service))
		}
	}
	return uniqueStrings(values)
}

func impactedServicesFromTopology(scope NormalizedScope, scopedGraph map[string]any) []string {
	target := normalizeServiceName(scope.Service)
	edges, _ := scopedGraph["edges"].([]clickhouse.TopologyEdge)
	values := []string{}
	for _, edge := range edges {
		source := normalizeServiceName(edge.Source)
		targetNode := normalizeServiceName(edge.Target)
		if target != "" && source != target && targetNode != target {
			continue
		}
		if source == target && edge.Target != "" {
			values = append(values, canonicalNarrativeValue(edge.Target))
		}
		if targetNode == target && edge.Source != "" {
			values = append(values, canonicalNarrativeValue(edge.Source))
		}
	}
	return uniqueStrings(values)
}

func logSummaryFromDirect(item *incidents.Incident, direct map[string]any) any {
	logCount, _ := direct["log_count"].(int64)
	samples, _ := direct["error_log_samples"].([]string)
	if logCount == 0 && len(samples) == 0 {
		return nil
	}
	sample := ""
	if len(samples) > 0 {
		sample = samples[0]
	}
	return map[string]any{
		"key_error":        firstNonEmpty(sample, "Log anomaly detected"),
		"occurrence_count": logCount,
		"affected_service": item.Service,
		"sample_log_line":  sample,
		"log_summary_text": fmt.Sprintf("Incident-scoped logs were retrieved from Synapse API for %s.", item.Service),
	}
}

func impactSummaryFromScopedEvidence(item *incidents.Incident, scope NormalizedScope, scopedGraph map[string]any) map[string]any {
	secondary := impactedServicesFromTopology(scope, scopedGraph)
	userImpact := "User impact depends on selected incident evidence."
	if item.Reasoning != nil && strings.TrimSpace(item.Reasoning.CustomerImpact) != "" {
		userImpact = item.Reasoning.CustomerImpact
	}
	return map[string]any{
		"primary_service":       firstNonEmpty(scope.Service, item.Service, item.RootCauseEntity),
		"secondary_services":    secondary,
		"summary_text":          "Impact summary is derived from API-scoped topology and incident evidence.",
		"estimated_user_impact": userImpact,
		"severity_label":        strings.ToUpper(firstNonEmpty(item.Severity, "unknown")),
	}
}

func propagationPath(item *incidents.Incident, scopedGraph map[string]any) []string {
	edges, _ := scopedGraph["edges"].([]clickhouse.TopologyEdge)
	graphValues := []string{}
	for _, edge := range edges {
		graphValues = append(graphValues, edge.Source+" -> "+edge.Target)
	}
	if item.Reasoning != nil && len(item.Reasoning.PropagationPath) > 0 {
		reasoningPath := normalizeNarrativeValues(item.Reasoning.PropagationPath)
		if len(reasoningPath) > 0 && hasRenderablePropagationPath(reasoningPath) {
			return reasoningPath
		}
		if len(graphValues) > 0 {
			return normalizeNarrativeValues(graphValues)
		}
	}
	if len(item.DependencyChain) > 0 {
		return normalizeNarrativeValues(item.DependencyChain)
	}
	return normalizeNarrativeValues(graphValues)
}

func toAnyStrings(reasoning *incidents.Reasoning, fallback []string) []string {
	if reasoning != nil && len(reasoning.CausalChain) > 0 {
		return normalizeNarrativeValues(reasoning.CausalChain)
	}
	return normalizeNarrativeValues(fallback)
}

func uniqueStrings(values []string) []string {
	seen := map[string]struct{}{}
	out := []string{}
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

func hasRenderablePropagationPath(values []string) bool {
	for _, value := range values {
		if strings.Contains(value, " -> ") {
			return true
		}
	}
	return false
}

func canonicalNarrativeValue(value string) string {
	trimmed := strings.TrimSpace(value)
	if trimmed == "" {
		return ""
	}
	if strings.Contains(trimmed, "->") {
		parts := strings.Split(trimmed, "->")
		normalized := make([]string, 0, len(parts))
		for _, part := range parts {
			canonical := canonicalNarrativeValue(part)
			if canonical == "" {
				continue
			}
			normalized = append(normalized, canonical)
		}
		if len(normalized) == 0 {
			return ""
		}
		return strings.Join(normalized, " -> ")
	}
	canonical := clickhouse.CanonicalTopologyNodeID(trimmed)
	if canonical != "" {
		return canonical
	}
	return trimmed
}

func normalizeNarrativeValues(values []string) []string {
	out := make([]string, 0, len(values))
	for _, value := range values {
		canonical := canonicalNarrativeValue(value)
		if canonical == "" {
			canonical = strings.TrimSpace(value)
		}
		if canonical == "" {
			continue
		}
		out = append(out, canonical)
	}
	return uniqueStrings(out)
}

func isCompletedReasoningStatus(status string) bool {
	switch strings.ToLower(strings.TrimSpace(status)) {
	case "completed", "completed_with_fallback":
		return true
	default:
		return false
	}
}

func reasoningExecutionMode(item *incidents.Incident) string {
	status := strings.ToLower(strings.TrimSpace(item.ReasoningStatus))
	if status == "completed_with_fallback" {
		return "fallback"
	}
	if item.Reasoning != nil {
		return "model"
	}
	return "pending"
}

func reasoningFailureSummary(item *incidents.Incident) string {
	if item == nil {
		return ""
	}
	return strings.TrimSpace(item.ReasoningError)
}

func normalizeHistory(currentID string, items []incidents.Incident) []map[string]any {
	out := []map[string]any{}
	for _, item := range items {
		if item.ID == currentID {
			continue
		}
		out = append(out, map[string]any{
			"incident_id":         item.ID,
			"timestamp":           item.Timestamp,
			"service":             item.Service,
			"severity":            item.Severity,
			"anomaly_score":       item.AnomalyScore,
			"root_cause_summary":  firstNonEmpty(item.RootCauseEntity, item.Service),
		})
		if len(out) >= 6 {
			break
		}
	}
	return out
}

func clusterContext(items []incidents.Incident) map[string]any {
	serviceSet := map[string]struct{}{}
	for _, item := range items {
		if item.Service != "" {
			serviceSet[item.Service] = struct{}{}
		}
	}
	return map[string]any{
		"at_risk_services":       len(serviceSet),
		"missing_resource_limits": "Unsupported from telemetry",
	}
}

func changeTimeline(item *incidents.Incident) []string {
	values := []string{}
	for _, event := range item.TimelineSummary {
		values = append(values, fmt.Sprintf("%s - %s", event.Timestamp.UTC().Format(time.RFC3339), firstNonEmpty(event.Title, event.Kind)))
	}
	return values
}

func serviceHealthScore(item *incidents.Incident) any {
	if item.TelemetrySnapshot.RequestCount == 0 && item.TelemetrySnapshot.ErrorRate == 0 && item.TelemetrySnapshot.P95LatencyMs == 0 {
		return "Unavailable"
	}
	score := 100.0
	score -= item.TelemetrySnapshot.ErrorRate * 100
	if item.TelemetrySnapshot.P95LatencyMs > item.TelemetrySnapshot.BaselineLatencyMs && item.TelemetrySnapshot.BaselineLatencyMs > 0 {
		score -= 15
	}
	if item.AnomalyScore > 1.5 {
		score -= 10
	}
	if score < 0 {
		score = 0
	}
	return score
}

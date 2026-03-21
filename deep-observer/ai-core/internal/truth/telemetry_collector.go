package truth

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"net/http"
	"os"
	"strings"
	"time"

	"deep-observer/ai-core/internal/clickhouse"
	"deep-observer/ai-core/internal/incidents"
)

func (s *Service) collectTelemetry(ctx context.Context, item *incidents.Incident, scope NormalizedScope) map[string]any {
	direct := buildDirectEvidence(item)
	graph := s.ResolveTopology(ctx, scope)
	scopedGraph := scopeTopology(graph, scope.Service)
	if shouldEnrichTopology(scopedGraph) {
		log.Printf("telemetry_collector: attempting signoz topology enrichment service=%s namespace=%s cluster=%s", firstNonEmpty(scope.Service, "all"), firstNonEmpty(scope.Namespace, "all"), firstNonEmpty(scope.Cluster, "all"))
		if enrichedGraph, err := fetchSigNozDependencies(ctx, scope); err == nil {
			scopedGraph = mergeScopedTopology(scopedGraph, enrichedGraph, scope)
		} else {
			log.Printf("telemetry_collector: signoz topology enrichment failed service=%s namespace=%s cluster=%s err=%v", firstNonEmpty(scope.Service, "all"), firstNonEmpty(scope.Namespace, "all"), firstNonEmpty(scope.Cluster, "all"), err)
		}
	}
	missing := buildMissingEvidence(item, scope, direct, scopedGraph)
	quality := classifyEvidence(item, direct, scopedGraph)
	contextual := buildContextualEvidence(quality, scopedGraph)
	coverage := buildCoverage(scope, direct, quality, scopedGraph)

	related, _ := s.store.ListCorrelatedIncidents(ctx, item.ID, 24*time.Hour, 8)
	history, _ := s.ListIncidents(ctx, NormalizedScope{
		Cluster:   scope.Cluster,
		Namespace: scope.Namespace,
		Service:   scope.Service,
		Start:     scope.Start.Add(-72 * time.Hour),
		End:       scope.End,
	}, 12)

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
		"impacted_services":          impactedServices(item),
		"propagation_path":           propagationPath(item, scopedGraph),
		"causal_chain":               toAnyStrings(item.Reasoning, item.DependencyChain),
		"confidence_details":         confidenceDetails(item, quality),
		"trust_score":                trustScore(item, quality),
		"reasoning_status":           firstNonEmpty(strings.ToLower(item.ReasoningStatus), "not_generated"),
		"reasoning_ready":            item.Reasoning != nil && isCompletedReasoningStatus(item.ReasoningStatus),
		"reasoning_execution_mode":   reasoningExecutionMode(item),
		"reasoning_failure_summary":  reasoningFailureSummary(item),
		"incident_summary":           incidentSummary(item, direct),
		"reasoning_summary":          reasoningSummary(item),
		"signal_summary":             signalSummary(item, quality),
		"log_summary":                logSummary(item),
		"impact_summary":             impactSummary(item),
		"decision_panel":             decisionPanel(item, quality),
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
	}
}

type sigNozDependencyItem struct {
	Parent    string  `json:"parent"`
	Child     string  `json:"child"`
	CallCount int64   `json:"callCount"`
	ErrorRate float64 `json:"errorRate"`
	P99       float64 `json:"p99"`
	P95       float64 `json:"p95"`
	P90       float64 `json:"p90"`
	P75       float64 `json:"p75"`
	P50       float64 `json:"p50"`
}

type sigNozTag struct {
	Key          string   `json:"key"`
	TagType      string   `json:"tagType"`
	StringValues []string `json:"stringValues"`
	NumberValues []int    `json:"numberValues"`
	BoolValues   []bool   `json:"boolValues"`
	Operator     string   `json:"operator"`
}

func shouldEnrichTopology(scopedGraph map[string]any) bool {
	available, _ := scopedGraph["available"].(bool)
	if !available {
		return true
	}
	nodes, _ := scopedGraph["nodes"].([]clickhouse.TopologyNode)
	edges, _ := scopedGraph["edges"].([]clickhouse.TopologyEdge)
	return len(edges) == 0 || (len(nodes) == 0 && len(edges) == 0)
}

func fetchSigNoZBaseURL() string {
	for _, key := range []string{"SIGNOZ_API_BASE_URL", "SIGNOZ_BASE_URL"} {
		if value := strings.TrimSpace(os.Getenv(key)); value != "" {
			return strings.TrimRight(value, "/")
		}
	}
	return "http://signoz:8080"
}

func fetchSigNoZAPIKey() string {
	for _, key := range []string{"SIGNOZ_API_KEY", "signoz_api_key"} {
		if value := strings.TrimSpace(os.Getenv(key)); value != "" {
			return value
		}
	}
	return ""
}

func fetchSigNozDependencies(ctx context.Context, scope NormalizedScope) (clickhouse.TopologyGraph, error) {
	graph := clickhouse.TopologyGraph{
		GeneratedAt: time.Now().UTC(),
		Nodes:       []clickhouse.TopologyNode{},
		Edges:       []clickhouse.TopologyEdge{},
	}

	payload := map[string]any{
		"start": scope.Start.UTC().Format(time.RFC3339),
		"end":   scope.End.UTC().Format(time.RFC3339),
		"tags":  buildSigNozTags(scope),
	}
	body, err := json.Marshal(payload)
	if err != nil {
		return graph, err
	}

	req, err := http.NewRequestWithContext(ctx, http.MethodPost, fetchSigNoZBaseURL()+"/api/v1/dependency_graph", bytes.NewReader(body))
	if err != nil {
		return graph, err
	}
	req.Header.Set("Content-Type", "application/json")
	if apiKey := fetchSigNoZAPIKey(); apiKey != "" {
		req.Header.Set("Authorization", "Bearer "+apiKey)
		req.Header.Set("SIGNOZ-API-KEY", apiKey)
	}

	client := &http.Client{Timeout: 8 * time.Second}
	resp, err := client.Do(req)
	if err != nil {
		return graph, err
	}
	defer resp.Body.Close()
	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		payload, _ := io.ReadAll(io.LimitReader(resp.Body, 2048))
		return graph, fmt.Errorf("signoz dependency_graph returned %d: %s", resp.StatusCode, strings.TrimSpace(string(payload)))
	}

	var items []sigNozDependencyItem
	if err := json.NewDecoder(resp.Body).Decode(&items); err != nil {
		return graph, err
	}

	nodeMap := map[string]clickhouse.TopologyNode{}
	for _, item := range items {
		source := normalizeServiceName(item.Parent)
		target := normalizeServiceName(item.Child)
		if source == "" || target == "" || source == target {
			continue
		}

		graph.Edges = append(graph.Edges, clickhouse.TopologyEdge{
			Source:         source,
			Target:         target,
			DependencyType: "trace_http",
			CallCount:      item.CallCount,
			AvgLatencyMs:   firstPositiveFloat(item.P95, item.P99, item.P90, item.P75, item.P50),
			ErrorRate:      item.ErrorRate,
		})

		if _, ok := nodeMap[source]; !ok {
			nodeMap[source] = clickhouse.TopologyNode{
				ID:        source,
				Label:     source,
				NodeType:  "service",
				Cluster:   scope.Cluster,
				Namespace: scope.Namespace,
			}
		}
		if _, ok := nodeMap[target]; !ok {
			nodeMap[target] = clickhouse.TopologyNode{
				ID:        target,
				Label:     target,
				NodeType:  "service",
				Cluster:   scope.Cluster,
				Namespace: scope.Namespace,
			}
		}
	}
	for _, node := range nodeMap {
		graph.Nodes = append(graph.Nodes, node)
	}
	return graph, nil
}

func buildSigNozTags(scope NormalizedScope) []sigNozTag {
	tags := []sigNozTag{}
	add := func(key, value string) {
		value = strings.TrimSpace(value)
		if value == "" {
			return
		}
		tags = append(tags, sigNozTag{
			Key:          key,
			TagType:      "ResourceAttribute",
			StringValues: []string{value},
			NumberValues: []int{},
			BoolValues:   []bool{},
			Operator:     "Equals",
		})
	}
	add("service.name", scope.Service)
	add("k8s.namespace.name", scope.Namespace)
	add("k8s.cluster.name", scope.Cluster)
	return tags
}

func mergeScopedTopology(existing map[string]any, enriched clickhouse.TopologyGraph, scope NormalizedScope) map[string]any {
	baseNodes, _ := existing["nodes"].([]clickhouse.TopologyNode)
	baseEdges, _ := existing["edges"].([]clickhouse.TopologyEdge)

	nodeMap := map[string]clickhouse.TopologyNode{}
	for _, node := range baseNodes {
		nodeMap[node.ID] = node
	}
	edgeMap := map[string]clickhouse.TopologyEdge{}
	for _, edge := range baseEdges {
		key := edge.Source + "|" + edge.Target + "|" + edge.DependencyType
		edgeMap[key] = edge
	}

	scopedEnriched := scopeTopology(enriched, scope.Service)
	enrichedNodes, _ := scopedEnriched["nodes"].([]clickhouse.TopologyNode)
	enrichedEdges, _ := scopedEnriched["edges"].([]clickhouse.TopologyEdge)
	for _, node := range enrichedNodes {
		if _, ok := nodeMap[node.ID]; !ok {
			nodeMap[node.ID] = node
		}
	}
	for _, edge := range enrichedEdges {
		key := edge.Source + "|" + edge.Target + "|" + edge.DependencyType
		if _, ok := edgeMap[key]; !ok {
			edgeMap[key] = edge
		}
	}

	nodes := make([]clickhouse.TopologyNode, 0, len(nodeMap))
	for _, node := range nodeMap {
		nodes = append(nodes, node)
	}
	edges := make([]clickhouse.TopologyEdge, 0, len(edgeMap))
	for _, edge := range edgeMap {
		edges = append(edges, edge)
	}

	return map[string]any{
		"available": len(nodes) > 0 || len(edges) > 0,
		"nodes":     nodes,
		"edges":     edges,
	}
}

func firstPositiveFloat(values ...float64) float64 {
	for _, value := range values {
		if value > 0 {
			return value
		}
	}
	return 0
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

func buildDirectEvidence(item *incidents.Incident) map[string]any {
	snapshot := item.TelemetrySnapshot
	return map[string]any{
		"request_count":           snapshot.RequestCount,
		"log_count":               snapshot.LogCount,
		"trace_sample_count":      len(snapshot.TraceIDs),
		"error_rate":              snapshot.ErrorRate,
		"p95_latency_ms":          snapshot.P95LatencyMs,
		"cpu_utilization":         snapshot.CPUUtilization,
		"memory_utilization":      snapshot.MemoryUtilization,
		"metric_highlights":       snapshot.MetricHighlights,
		"timeline_event_count":    len(item.TimelineSummary),
		"direct_dependency_nodes": append([]string{}, item.DependencyChain...),
	}
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
	if direct["request_count"].(int64) > 0 || direct["trace_sample_count"].(int) > 0 {
		quality["traces"] = "direct"
	}
	if direct["log_count"].(int64) > 0 {
		quality["logs"] = "direct"
	}
	if len(item.TelemetrySnapshot.MetricHighlights) > 0 || item.TelemetrySnapshot.P95LatencyMs > 0 || item.TelemetrySnapshot.ErrorRate > 0 {
		quality["metrics"] = "direct"
	}
	deps := strings.ToLower(strings.Join(item.DependencyChain, " "))
	if strings.Contains(deps, "db:") {
		quality["database"] = "direct"
	}
	if strings.Contains(deps, "messaging:") {
		quality["messaging"] = "direct"
	}
	if len(item.TelemetrySnapshot.ErrorLogs) > 0 {
		quality["exceptions"] = "direct"
	}
	if item.TelemetrySnapshot.CPUUtilization > 0 || item.TelemetrySnapshot.MemoryUtilization > 0 {
		quality["infra"] = "direct"
	}
	edgesText := fmt.Sprintf("%v", scopedGraph["edges"])
	if quality["database"] == "missing" && strings.Contains(strings.ToLower(edgesText), "db:") {
		quality["database"] = "contextual"
	}
	if quality["messaging"] == "missing" && strings.Contains(strings.ToLower(edgesText), "messaging:") {
		quality["messaging"] = "contextual"
	}
	if len(item.DependencyChain) > 0 {
		quality["topology"] = "direct"
	} else if available, _ := scopedGraph["available"].(bool); available {
		quality["topology"] = "contextual"
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
	if len(item.TelemetrySnapshot.MetricHighlights) == 0 && item.TelemetrySnapshot.P95LatencyMs == 0 && item.TelemetrySnapshot.ErrorRate == 0 {
		missing = append(missing, "No incident-scoped service metrics were found.")
	}
	if len(item.TelemetrySnapshot.ErrorLogs) == 0 {
		missing = append(missing, "No exception evidence was found for the selected incident scope.")
	}
	if item.TelemetrySnapshot.CPUUtilization == 0 && item.TelemetrySnapshot.MemoryUtilization == 0 {
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

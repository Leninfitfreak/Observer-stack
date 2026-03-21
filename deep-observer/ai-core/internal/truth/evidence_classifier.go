package truth

import (
	"fmt"
	"strings"

	"deep-observer/ai-core/internal/incidents"
)

func confidenceDetails(item *incidents.Incident, quality map[string]string) map[string]any {
	ready := item.Reasoning != nil && isCompletedReasoningStatus(item.ReasoningStatus)
	score := item.PredictiveConfidence
	if ready {
		score = item.Reasoning.ConfidenceScore
	}
	supporting := []string{}
	weakening := []string{}
	for _, signal := range []string{"traces", "logs", "metrics", "database", "messaging", "exceptions", "infra", "topology"} {
		switch quality[signal] {
		case "direct":
			supporting = append(supporting, fmt.Sprintf("Incident-scoped %s evidence is present.", signal))
		case "contextual":
			supporting = append(supporting, fmt.Sprintf("Contextual %s evidence is present in the selected scope.", signal))
		default:
			weakening = append(weakening, fmt.Sprintf("No %s evidence was found in the selected incident scope.", signal))
		}
	}

	text := "Reasoning has not been generated for this incident yet. Confidence will be computed after a manual reasoning run from the same selected-incident evidence basis shown on this page."
	if ready {
		text = "Confidence is based on direct selected-incident evidence first, with broader scope evidence labeled separately as contextual."
	}

	return map[string]any{
		"score":              score,
		"level":              confidenceLevel(score),
		"explanation_text":   text,
		"supporting_factors": uniqueStrings(supporting),
		"weakening_factors":  uniqueStrings(weakening),
	}
}

func evidenceTrustValue(quality map[string]string) float64 {
	total := 0.0
	max := 8.0
	for _, signal := range []string{"traces", "logs", "metrics", "database", "messaging", "exceptions", "infra", "topology"} {
		switch quality[signal] {
		case "direct":
			total += 1.0
		case "contextual":
			total += 0.25
		}
	}
	if max <= 0 {
		return 0
	}
	score := total / max
	if score < 0.05 {
		score = 0.05
	}
	if score > 0.95 {
		score = 0.95
	}
	return score
}

func trustScore(item *incidents.Incident, quality map[string]string) map[string]any {
	score := evidenceTrustValue(quality)
	return map[string]any{
		"score":   score,
		"level":   confidenceLevel(score),
		"summary": "Trust uses the same backend evidence contract as the rest of the selected-incident page.",
	}
}

func reasoningView(item *incidents.Incident, quality map[string]string) map[string]any {
	status := firstNonEmpty(strings.ToLower(item.ReasoningStatus), "not_generated")
	ready := item.Reasoning != nil && isCompletedReasoningStatus(item.ReasoningStatus)
	confidence := confidenceDetails(item, quality)
	trust := trustScore(item, quality)
	return map[string]any{
		"status":               status,
		"summary":              reasoningSummary(item),
		"confidence_score":     confidence["score"],
		"confidence_level":     confidence["level"],
		"confidence_details":   confidence,
		"execution_mode":       reasoningExecutionMode(item),
		"failure_summary":      reasoningFailureSummary(item),
		"placeholder_allowed":  !ready,
		"decision_panel":       decisionPanel(item, quality),
		"trust_score":          trust,
	}
}

func isSparsePredictiveIncident(item *incidents.Incident, direct map[string]any, quality map[string]string) bool {
	if !strings.EqualFold(firstNonEmpty(item.IncidentType, "observed"), "predictive") {
		return false
	}
	requestCount, _ := direct["request_count"].(int64)
	logCount, _ := direct["log_count"].(int64)
	traceCount, _ := direct["trace_sample_count"].(int)
	metricCount := 0
	switch values := direct["metric_highlights"].(type) {
	case map[string]any:
		metricCount = len(values)
	case map[string]float64:
		metricCount = len(values)
	}
	metricsDirect := strings.EqualFold(quality["metrics"], "direct")
	topologyDirect := strings.EqualFold(quality["topology"], "direct")
	return requestCount == 0 &&
		logCount == 0 &&
		traceCount == 0 &&
		(metricCount == 0 || !metricsDirect) &&
		!topologyDirect
}

func confidenceLevel(score float64) string {
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

func incidentSummary(item *incidents.Incident, direct map[string]any) string {
	if direct["request_count"].(int64) == 0 && direct["log_count"].(int64) == 0 && direct["trace_sample_count"].(int) == 0 {
		return fmt.Sprintf("%s incident on %s. Direct incident telemetry is sparse, so contextual evidence is labeled separately.", firstNonEmpty(item.IncidentType, "observed"), firstNonEmpty(item.Service, "unknown service"))
	}
	return fmt.Sprintf("%s incident on %s. Panels below use the same backend-selected evidence contract.", firstNonEmpty(item.IncidentType, "observed"), firstNonEmpty(item.Service, "unknown service"))
}

func reasoningSummary(item *incidents.Incident) string {
	if item.Reasoning == nil || !isCompletedReasoningStatus(item.ReasoningStatus) {
		return "Reasoning has not been generated for this incident yet. The page is currently showing evidence only, not a completed RCA."
	}
	if strings.TrimSpace(item.Reasoning.RootCause) != "" {
		if strings.EqualFold(item.ReasoningStatus, "completed_with_fallback") {
			return item.Reasoning.RootCause + " This result was produced by deterministic fallback because model generation failed."
		}
		return item.Reasoning.RootCause
	}
	return "Reasoning completed."
}

func signalSummary(item *incidents.Incident, quality map[string]string) map[string]any {
	critical := append([]string{}, item.Signals...)
	missing := []string{}
	for _, signal := range []string{"traces", "logs", "metrics", "database", "messaging", "exceptions", "infra", "topology"} {
		if quality[signal] == "missing" {
			missing = append(missing, signal)
		}
	}
	return map[string]any{
		"critical_signals":  uniqueStrings(critical),
		"secondary_signals": []string{},
		"missing_signals":   uniqueStrings(missing),
	}
}

func logSummary(item *incidents.Incident) any {
	if item.TelemetrySnapshot.LogCount == 0 && len(item.TelemetrySnapshot.ErrorLogs) == 0 {
		return nil
	}
	sample := ""
	if len(item.TelemetrySnapshot.ErrorLogs) > 0 {
		sample = item.TelemetrySnapshot.ErrorLogs[0]
	}
	return map[string]any{
		"key_error":         firstNonEmpty(sample, "Log anomaly detected"),
		"occurrence_count":  item.TelemetrySnapshot.LogCount,
		"affected_service":  item.Service,
		"sample_log_line":   sample,
		"log_summary_text":  fmt.Sprintf("Incident-scoped logs detected for %s.", item.Service),
	}
}

func impactSummary(item *incidents.Incident) map[string]any {
	secondary := impactedServices(item)
	userImpact := "User impact depends on the scoped telemetry shown on this page."
	if item.Reasoning != nil && strings.TrimSpace(item.Reasoning.CustomerImpact) != "" {
		userImpact = item.Reasoning.CustomerImpact
	}
	return map[string]any{
		"primary_service":        firstNonEmpty(item.Service, item.RootCauseEntity),
		"secondary_services":     secondary,
		"summary_text":           fmt.Sprintf("Impact assessment is grounded in the selected incident scope for %s.", firstNonEmpty(item.Service, "the selected service")),
		"estimated_user_impact":  userImpact,
		"severity_label":         strings.ToUpper(firstNonEmpty(item.Severity, "unknown")),
	}
}

func decisionPanel(item *incidents.Incident, quality map[string]string) map[string]any {
	if item.Reasoning == nil || !isCompletedReasoningStatus(item.ReasoningStatus) {
		return map[string]any{
			"root_cause":          "Reasoning not generated",
			"impact_summary":      "Selected-incident evidence is available, but a completed RCA has not been generated yet.",
			"immediate_action":    "Review the scoped telemetry evidence before taking remediation actions.",
			"next_actions":        []string{"Review incident-scoped telemetry evidence.", "Run reasoning when you need a grounded RCA."},
			"investigation_steps": []string{"Inspect direct traces, logs, and metrics for the selected incident scope."},
			"confidence_score":    0.0,
		}
	}
	return map[string]any{
		"root_cause":          firstNonEmpty(item.Reasoning.RootCauseService, item.Service),
		"impact_summary":      firstNonEmpty(item.Reasoning.ImpactAssessment, "Impact assessment unavailable."),
		"immediate_action":    firstNonEmpty(firstAction(item.Reasoning.RecommendedActions), "Review scoped evidence."),
		"next_actions":        uniqueStrings(item.Reasoning.RecommendedActions),
		"investigation_steps": []string{"Validate the direct evidence shown on this page against the RCA output."},
		"confidence_score":    item.Reasoning.ConfidenceScore,
	}
}

func prioritizedActions(item *incidents.Incident, quality map[string]string) []map[string]any {
	if item.Reasoning == nil || !isCompletedReasoningStatus(item.ReasoningStatus) {
		return []map[string]any{
			{
				"label":            "Review selected-incident telemetry evidence.",
				"priority":         "medium",
				"confidence":       0.25,
				"estimated_effort": "low",
				"risk_level":       "low",
			},
		}
	}
	out := []map[string]any{}
	for _, action := range uniqueStrings(item.Reasoning.RecommendedActions) {
		out = append(out, map[string]any{
			"label":            action,
			"priority":         "medium",
			"confidence":       item.Reasoning.ConfidenceScore,
			"estimated_effort": "medium",
			"risk_level":       "medium",
		})
	}
	if len(out) == 0 {
		out = append(out, map[string]any{
			"label":            "Review scoped telemetry evidence.",
			"priority":         "medium",
			"confidence":       0.4,
			"estimated_effort": "low",
			"risk_level":       "low",
		})
	}
	return out
}

func runbook(item *incidents.Incident, quality map[string]string) map[string]any {
	steps := []string{}
	if item.Reasoning != nil && isCompletedReasoningStatus(item.ReasoningStatus) {
		steps = uniqueStrings(item.Reasoning.RecommendedActions)
	}
	if len(steps) == 0 {
		steps = []string{"Review the selected-incident evidence before making operational changes."}
	}
	return map[string]any{
		"incident_steps":        steps,
		"related_context_steps": []string{},
	}
}

func observabilityGaps(scope NormalizedScope, quality map[string]string, missing []string) map[string]any {
	recommendations := []string{}
	if quality["traces"] == "missing" {
		recommendations = append(recommendations, "Add or verify distributed traces for the selected service scope.")
	}
	if quality["logs"] == "missing" {
		recommendations = append(recommendations, "Add or verify incident-scoped logs for the selected service scope.")
	}
	if quality["metrics"] == "missing" {
		recommendations = append(recommendations, "Add or verify service-level metrics for the selected service scope.")
	}
	return map[string]any{
		"missing_critical_signals":          missing,
		"impact_on_confidence":              "Confidence is limited by the exact missing signals listed above.",
		"recommended_instrumentation_steps": uniqueStrings(recommendations),
		"summary":                           "Observability gaps are computed from the same backend evidence contract as the rest of the page.",
	}
}

func incidentTimeline(item *incidents.Incident) []map[string]any {
	out := []map[string]any{}
	out = append(out, map[string]any{
		"timestamp":  item.Timestamp,
		"event_type": "incident_created",
		"label":      "Incident created",
		"service":    item.Service,
	})
	for _, event := range item.TimelineSummary {
		out = append(out, map[string]any{
			"timestamp":  event.Timestamp,
			"event_type": firstNonEmpty(event.Kind, "telemetry_event"),
			"label":      firstNonEmpty(event.Title, "Telemetry event"),
			"service":    firstNonEmpty(event.Entity, item.Service),
		})
	}
	return out
}

func firstAction(values []string) string {
	if len(values) == 0 {
		return ""
	}
	return strings.TrimSpace(values[0])
}

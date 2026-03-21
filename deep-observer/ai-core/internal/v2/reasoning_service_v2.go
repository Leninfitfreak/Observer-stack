package v2

import (
	"strings"

	"deep-observer/ai-core/internal/incidents"
)

func (s *Service) BuildReasoningView(item *incidents.Incident, sparse bool) ReasoningView {
	status := strings.ToLower(strings.TrimSpace(item.ReasoningStatus))
	if status == "" {
		status = "not_generated"
	}
	allowed := !sparse
	view := ReasoningView{
		Status:        status,
		Allowed:       allowed,
		ExecutionMode: "pending",
		Summary:       "Reasoning has not been generated yet.",
		RootCause:     "",
		RootCauseSignal: "",
		Confidence:    0,
		Actions:       []string{},
		Error:         strings.TrimSpace(item.ReasoningError),
	}
	if sparse {
		view.Summary = "Insufficient incident-scoped telemetry for root cause analysis."
		return view
	}
	if item.Reasoning == nil {
		if status == "failed" {
			view.Summary = "Reasoning failed. Review error and retry."
		}
		return view
	}
	view.Confidence = item.Reasoning.ConfidenceScore
	view.RootCause = firstNonEmpty(item.Reasoning.RootCauseService, item.Reasoning.RootCause, item.RootCauseEntity)
	view.RootCauseSignal = firstNonEmpty(item.Reasoning.RootCauseSignal)
	view.Actions = item.Reasoning.RecommendedActions
	view.Summary = firstNonEmpty(item.Reasoning.RootCause, "Reasoning completed.")
	switch status {
	case "completed_with_fallback":
		view.ExecutionMode = "fallback"
	case "completed":
		view.ExecutionMode = "model"
	case "running", "queued", "pending":
		view.ExecutionMode = "pending"
	case "failed":
		view.ExecutionMode = "failed"
	default:
		view.ExecutionMode = status
	}
	return view
}


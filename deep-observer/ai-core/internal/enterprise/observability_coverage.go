package enterprise

import (
	"context"

	"deep-observer/ai-core/internal/incidents"
)

type ObservabilityCoverageAnalyzer struct {
	store *incidents.Store
}

func NewObservabilityCoverageAnalyzer(store *incidents.Store) *ObservabilityCoverageAnalyzer {
	return &ObservabilityCoverageAnalyzer{store: store}
}

func (a *ObservabilityCoverageAnalyzer) Report(ctx context.Context, projectID, cluster string) (map[string]any, error) {
	return a.store.BuildObservabilityReport(ctx, projectID, cluster)
}

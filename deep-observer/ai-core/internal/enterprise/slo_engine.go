package enterprise

import (
	"context"

	"deep-observer/ai-core/internal/incidents"
)

type SLOEngine struct {
	store *incidents.Store
}

func NewSLOEngine(store *incidents.Store) *SLOEngine {
	return &SLOEngine{store: store}
}

func (e *SLOEngine) EnsureDefaults(ctx context.Context, service string) error {
	return e.store.EnsureDefaultSLOs(ctx, service)
}

func (e *SLOEngine) Status(ctx context.Context, projectID, cluster, namespace string, limit int) ([]incidents.SLOStatus, error) {
	return e.store.ListSLOStatus(ctx, projectID, cluster, namespace, limit)
}

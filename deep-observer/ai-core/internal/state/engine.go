package state

import (
	"context"
	"math"

	"deep-observer/ai-core/internal/clickhouse"
	"deep-observer/ai-core/internal/incidents"
)

type Engine struct {
	store *incidents.Store
}

func NewEngine(store *incidents.Store) *Engine {
	return &Engine{store: store}
}

func (e *Engine) Record(ctx context.Context, projectID string, snapshot clickhouse.Snapshot, service string, dependencyImpact float64) error {
	health := computeHealth(snapshot, dependencyImpact)
	return e.store.InsertServiceState(ctx, incidents.ServiceState{
		ProjectID:         projectID,
		Cluster:           snapshot.Filters.Cluster,
		Namespace:         snapshot.Filters.Namespace,
		ServiceName:       service,
		CPUUtilization:    normalizePercent(snapshot.CPUUtilization),
		MemoryUtilization: normalizePercent(snapshot.MemoryUtilization),
		LatencyP95:        snapshot.P95LatencyMs,
		ErrorRate:         snapshot.ErrorRate,
		DependencyImpact:  dependencyImpact,
		HealthScore:       health,
		Timestamp:         snapshot.ObservedAt,
	})
}

func computeHealth(snapshot clickhouse.Snapshot, dependencyImpact float64) float64 {
	cpuPenalty := normalizePercent(snapshot.CPUUtilization) * 0.2
	memoryPenalty := normalizePercent(snapshot.MemoryUtilization) * 0.2
	errorPenalty := math.Min(35, snapshot.ErrorRate*200)
	latencyPenalty := math.Min(25, snapshot.P95LatencyMs/40)
	impactPenalty := math.Min(20, dependencyImpact/10)
	score := 100 - cpuPenalty - memoryPenalty - errorPenalty - latencyPenalty - impactPenalty
	if score < 0 {
		score = 0
	}
	return math.Round(score*100) / 100
}

func normalizePercent(value float64) float64 {
	if value > 1 {
		return value
	}
	return value * 100
}

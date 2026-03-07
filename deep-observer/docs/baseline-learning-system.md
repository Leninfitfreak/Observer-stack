# Baseline Learning System

## Purpose
Deep Observer uses adaptive baselines to reduce static-threshold noise and detect context-aware anomalies.

## Current Implementation
- Engine: `ai-core/internal/incidents/knowledge_graph_store.go`
- Table: `service_metric_baselines`
  - `project_id`, `cluster`, `namespace`
  - `service`, `metric`
  - `hour_of_day`, `day_of_week`
  - `baseline_value`, `variance`, `sample_count`, `updated_at`

## Learned Metrics
- `latency_p95_ms`
- `error_rate`
- `queue_lag` (derived from metric highlights)

## Learning Method
- For each service/metric and current hour/day bucket:
  - Read existing mean/variance
  - Update via exponential smoothing
  - Persist updated baseline/variance/sample count

## Detection Method
- At detection time, compare current value to:
  - `threshold = baseline_value + 3 * stddev`
- If threshold exceeded, emit adaptive signals such as:
  - `adaptive_latency_deviation_hX_dY`
  - `adaptive_error_deviation_hX_dY`
  - `queue_lag_spike_hX_dY`

## Integration Point
- Detector calls:
  - `DetectAdaptiveSignals(...)`
  - `UpdateAdaptiveBaselines(...)`
- Adaptive signals are merged with rule-based anomaly signals before incident creation.


# Incident Analysis Pipeline

## Lifecycle
```text
Telemetry snapshot
  -> baseline comparison
  -> anomaly signal generation
  -> causal ranking on dependency graph
  -> root cause + impact propagation
  -> incident/problem persistence
  -> AI reasoning + validation
  -> dashboard presentation
```

## Detection Stage (ai-core)
`ai-core/internal/detector/engine.go`:
- Lists active services from telemetry.
- Reads snapshot (request count, latency, errors, CPU/memory, log anomalies).
- Evaluates rules:
  - latency spikes
  - error-rate increases
  - CPU/memory pressure
  - baseline deviation
  - latency z-score deviation
- Applies adaptive baseline signals from `service_metric_baselines`.

## Causal Ranking + Root Cause
- `enterprise/causal_graph_engine.go` ranks nodes by impact score and propagation depth.
- Detector sets root cause to top-ranked service.

## Impact Propagation
- Detector traverses topology upstream/downstream from root cause.
- Persists impacted services into `incident_impacts`:
  - `incident_id`
  - `service`
  - `impact_type` (`root`, `upstream`, `downstream`)
  - `impact_score`

## Incident and Problem Persistence
- Incident row written to `incidents`.
- Problem grouping updated in `problems`.
- Incident and system knowledge graph rows written in:
  - `incident_graph_nodes`
  - `incident_graph_edges`

## AI Reasoning Stage (ai-brain)
`ai-brain/app/main.py`:
- Polls pending incidents.
- Builds context: metrics/logs/traces/topology/timeline/coverage/deployment evidence.
- Calls LLM provider.
- Validates claims (`validation_engine.py`):
  - service existence
  - signal support from telemetry
  - topology support for causal claims
- Stores reasoning and runbook artifacts.

## Dashboard Representation
Frontend renders:
- Incident table and detailed panel
- Causal chain + propagation path + impacted services
- Timeline
- Suggested actions/runbooks
- Coverage/SLO/cluster report context


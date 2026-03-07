# Deep Observer AI Platform Architecture

## Repository Layout
- `ai-core` (Go)
- `ai-brain` (Python)
- `frontend` (React)
- `docker-compose.yml` for local runtime

## ai-core (Go) Responsibilities
- Load env-driven config (`internal/config/config.go`)
- Connect Postgres for metadata/state
- Query ClickHouse telemetry
- Build topology from traces/messaging/db spans
- Detect anomalies and predictive signals
- Rank causal root cause candidates
- Persist incidents, problems, dependencies, graphs, baselines
- Expose REST APIs for dashboard and integrations

Background engines started by `cmd/server/main.go`:
- Detector engine
- Cluster intelligence engine
- Change intelligence engine

## ai-brain (Python) Responsibilities
- Poll pending incidents
- Build compressed telemetry context (`app/telemetry.py`)
- Invoke LLM provider (Ollama/OpenAI compatible)
- Generate root-cause narrative and remediation
- Validate reasoning against telemetry evidence (`validation_engine.py`)
- Store reasoning validation reports + runbooks
- Create predictive incidents from trend analysis

## Frontend (React) Responsibilities
- Fetches:
  - incidents
  - topology
  - service health
  - cluster report
  - changes
  - SLO status
  - runbooks
  - observability report
- Provides cluster/namespace/service/time filtering
- Presents topology + incident table + details with reasoning/timeline

## Persistence Model (Postgres)
Major tables include:
- `incidents`, `reasoning`, `reasoning_validations`
- `problems`
- `incident_impacts`
- `service_dependencies`, `dependency_graphs`
- `services_registry`, `service_states`
- `service_baselines`, `service_metric_baselines`
- `graph_nodes`, `graph_edges`
- `incident_graph_nodes`, `incident_graph_edges`
- `system_changes`, `runbooks`, `service_slos`, `cluster_resources`

## API Surface (ai-core)
- `/health`
- `/api/incidents`
- `/api/incidents/{id}`
- `/api/incidents/{id}/timeline`
- `/api/topology`
- `/api/filters`
- `/api/problems`
- `/api/service-health`
- `/api/cluster-report`
- `/api/changes`
- `/api/slo-status`
- `/api/runbooks`
- `/api/observability-report`


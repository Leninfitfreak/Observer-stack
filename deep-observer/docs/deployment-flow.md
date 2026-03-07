# Deployment and Startup Flow

## Recommended Startup Sequence

1. **Start external Kafka platform**
   - Repo: `kafka-platform`
   - Command: `docker compose up -d`
   - Ensure broker healthy and topics exist.

2. **Ensure Kubernetes apps are deployed via GitOps**
   - Repo: `leninkart-infra`
   - ArgoCD root app syncs dev applications.
   - Verify pods/services/ingress in namespace `dev`.

3. **Start observability pipeline**
   - OTEL collector deployment and config must be healthy.
   - OTLP export endpoint must reach SigNoz.
   - Verify telemetry appears in ClickHouse tables.

4. **Start Deep Observer platform**
   - Repo: `Deep-observer`
   - Command: `docker compose up -d`
   - Services:
     - `postgres`
     - `ai-core`
     - `ai-brain`
     - `frontend`

5. **Validate Deep Observer APIs/UI**
   - `http://localhost:8081/health`
   - `http://localhost:8081/api/incidents`
   - `http://localhost:8081/api/topology`
   - `http://localhost:3000`

## Runtime Dependencies
- `ai-core` and `ai-brain` require:
  - Postgres connectivity
  - ClickHouse connectivity
  - `.env` configuration
- `ai-brain` additionally requires valid LLM provider credentials.

## Traffic and Telemetry Validation
- Run `traffic-generator` (K8s deployment) or real user traffic.
- Confirm topology includes expected application path and external nodes.
- Confirm incidents/reasoning appear after anomalies are detected.

## Restart Safety
- Kafka and Deep Observer are restart-safe with persistent volumes:
  - Kafka: `kafka_data`
  - Deep Observer Postgres: `postgres_data`


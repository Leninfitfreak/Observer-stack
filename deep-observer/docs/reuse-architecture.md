# Reusing This Architecture for Another Microservice System

## Reuse Principle
Deep Observer is designed to be environment-driven. Reuse should not require hardcoding service names in code.

## What to Change

### 1) Application onboarding
- Deploy your services in Kubernetes (or equivalent runtime).
- Ensure ingress/API routes represent real user flows.
- If Kafka is used, define external/internal broker pattern and topic model.

### 2) Instrumentation
- Add OpenTelemetry traces, metrics, and logs for each service.
- Emit canonical attributes:
  - `service.name`
  - `k8s.namespace.name`
  - HTTP attributes (`http.method`, `http.route`, status)
  - Messaging attrs (`messaging.system`, destination, operation)
  - DB attrs (`db.system`, `db.name` or address)

### 3) Environment variables
Update Deep Observer `.env` only:
- Project/tenant scope:
  - `PROJECT_ID`
  - `CLUSTER_ID`
  - `NAMESPACE_FILTER`
  - `SERVICE_FILTER`
- Data plane:
  - ClickHouse host/port/user/password/database
  - Postgres host/port/user/password/db
- Detector:
  - intervals/lookback/baseline/zscore
- LLM:
  - provider keys, model, timeout, retries

### 4) Kafka topic model
- Update topic names and producer/consumer mapping in app services.
- Ensure OTEL messaging instrumentation is enabled.

### 5) GitOps manifests
- Duplicate/adjust ArgoCD apps and Helm values per environment.
- Keep service, ingress, and secret names consistent with telemetry identity.

## Reuse Checklist
- Telemetry reaching SigNoz/ClickHouse
- `/api/filters` returns correct dynamic services/namespaces
- `/api/topology` reflects real dependencies
- Incidents generated from real anomalies
- Reasoning validation reports supported claims

## Common Pitfalls
- Missing telemetry attributes causing pod-name leakage
- Namespace filter too restrictive (`default` vs `dev`)
- Kafka topic mismatch between code and platform
- OTEL exporter endpoint unreachable from cluster


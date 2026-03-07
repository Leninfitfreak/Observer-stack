# Deep Observer Ecosystem Architecture Overview

## Scope
This document describes the full Deep Observer ecosystem across:
- `leninkart-infra` (GitOps Kubernetes infrastructure)
- `kafka-platform` (external Kafka in Docker Compose)
- `Deep-observer` (ai-core, ai-brain, frontend)
- OpenTelemetry + SigNoz + ClickHouse observability stack
- LeninKart microservices (`frontend`, `product-service`, `order-service`)

## High-Level System
```text
User Traffic
  -> LeninKart Frontend (K8s, dev namespace)
  -> Product API (/auth, /api/products)
  -> Order API (/api/orders)
  -> Kafka (external, host.minikube.internal:9092)
  -> Postgres (K8s service)

Microservices + K8s events
  -> OpenTelemetry Collector (K8s, dev namespace)
  -> SigNoz OTLP endpoint
  -> ClickHouse telemetry storage
     - signoz_metrics.distributed_time_series_v4
     - signoz_logs.distributed_logs_v2
     - signoz_traces.distributed_signoz_index_v3

Deep Observer
  -> ai-core (Go): topology, anomaly detection, incidents, APIs
  -> ai-brain (Python): reasoning, validation, runbooks
  -> frontend (React): dashboard
  -> Postgres metadata DB
```

## Primary Runtime Responsibilities
- LeninKart services generate real HTTP, DB, and Kafka traffic.
- OTEL collector enriches telemetry with K8s resource attributes.
- SigNoz stores telemetry in ClickHouse tables queried by Deep Observer.
- `ai-core` continuously detects anomalies and creates incidents/problems.
- `ai-brain` converts incidents into validated root-cause reasoning.
- Deep Observer UI renders topology, incidents, reasoning, and reports.

## End-to-End Operational Flow
1. User/load traffic enters ingress and reaches frontend/product/order services.
2. Product service publishes Kafka messages; order service consumes and writes to DB.
3. OTEL collector captures traces/metrics/logs + K8s events and exports to SigNoz.
4. `ai-core` reads ClickHouse telemetry, builds topology, computes anomalies, stores incidents in Postgres.
5. `ai-brain` polls pending incidents, builds context, generates reasoning, validates claims, stores reasoning/runbooks.
6. Dashboard calls `ai-core` APIs and presents incident + topology + AI analysis.


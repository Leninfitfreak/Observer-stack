# Observability Pipeline

## End-to-End Telemetry Path
```text
LeninKart services + Kubernetes events
  -> OpenTelemetry Collector (dev namespace)
  -> SigNoz OTLP ingest endpoint
  -> ClickHouse storage tables
  -> Deep Observer telemetry queries
```

## Data Sources Queried by Deep Observer
- Traces: `signoz_traces.distributed_signoz_index_v3`
- Logs: `signoz_logs.distributed_logs_v2`
- Metrics: `signoz_metrics.distributed_time_series_v4`

## OpenTelemetry Collection
`observability/otel/collector-configmap.yaml` configures:
- Receivers:
  - `otlp` (grpc/http)
  - `hostmetrics`
  - `kubeletstats`
  - `kafkametrics` (broker `host.minikube.internal:9092`)
  - `k8sobjects` (events)
- Processors:
  - `k8sattributes`
  - `resource`
  - `transform/logs`
  - `batch`, `memory_limiter`
- Exporter:
  - OTLP to SigNoz endpoint (`OTEL_EXPORTER_ENDPOINT`)

## Service Instrumentation Signals
Product/order services include:
- OTEL env values (`OTEL_SERVICE_NAME`, OTLP endpoint/protocol, exporters)
- Trace propagation (`tracecontext,baggage`)
- Kafka instrumentation enabled
- Actuator + Prometheus endpoints enabled (also useful for health and scrape sources)

## Deep Observer Ingestion
`ai-core` and `ai-brain` connect directly to ClickHouse:
- `ai-core`: service discovery, snapshots, topology, anomaly detection
- `ai-brain`: contextual telemetry fetch for reasoning/validation

## Telemetry Normalization
Service identity normalization favors:
- `service.name`
- `k8s.service.name`
- `k8s.deployment.name`
- `k8s.container.name`
- `k8s.pod.name`

Pod/deployment hash suffixes are stripped for canonical service IDs.


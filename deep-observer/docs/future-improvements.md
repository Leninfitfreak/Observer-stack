# Future Improvements

## 1) Stronger Adaptive Baseline Learning
- Extend from current hour/day baseline buckets to:
  - seasonality-aware models
  - percentile baselines by endpoint and status class
  - online drift detection with change-point alerts
- Add confidence intervals per metric/service/window.

## 2) Telemetry Coverage Intelligence
- Expand coverage scoring by workload type (API, worker, Kafka consumer, DB).
- Add automatic instrumentation gap tickets:
  - missing spans
  - missing Kafka metrics
  - missing resource attributes
  - low log correlation quality

## 3) Incident Knowledge Graph Expansion
- Extend graph node taxonomy:
  - deploy versions
  - feature flags
  - infra resources
- Introduce pattern mining:
  - recurring causal motifs
  - service-pair failure signatures
  - confidence boosting from history.

## 4) Predictive Detection Maturity
- Move beyond linear smoothing into:
  - multivariate trend models
  - workload-aware predictors
  - pre-incident anomaly classes (capacity, latency drift, error bloom)

## 5) Dependency Discovery Enhancements
- Add explicit DNS/service-mesh edge extraction when available.
- Include ingress-to-service edges as first-class topology elements.
- Increase confidence scoring based on repeated evidence across traces/logs/metrics.

## 6) Reasoning Guardrails
- Strengthen claim-evidence linkage in reasoning validation:
  - per-claim metric IDs and trace IDs
  - unsupported claim suppression in UI
  - traceable confidence decomposition.

## 7) Multi-Cluster Scale
- Partition metadata by `project_id` + `cluster_id`.
- Add cluster-scoped retention and archiving policies.
- Add cross-cluster comparison for SLO and anomaly posture.

## 8) Operational Productization
- Alert routing policies (service ownership, severity, on-call windows).
- SLA/SLO dashboards with error-budget burn alerts.
- Incident lifecycle management (acknowledge, assign, resolve, postmortem export).


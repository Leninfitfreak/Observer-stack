# Observability Discovery Guide

## Purpose

AI Observer can auto-discover and validate observability backends (Prometheus, Loki, Jaeger) from Kubernetes without hardcoded URLs.

This keeps enrichment portable across clusters and projects.

## Discovery Flow

1. Read discovery configuration from environment.
2. Query Kubernetes Service API in configured namespaces.
3. Match candidate services for:
   - Prometheus
   - Loki
   - Jaeger
4. Build in-cluster DNS URLs for matched services.
5. Validate connectivity:
   - Prometheus: `GET /api/v1/query?query=up`
   - Loki: `GET /loki/api/v1/status/buildinfo`
   - Jaeger: `GET /api/services`
6. Publish registry state into reasoning context as `context.observability_registry`.
7. Refresh periodically and update provider endpoints automatically.

## Required Environment Variables

- `KUBERNETES_ENABLED=true`
- `KUBERNETES_NAMESPACE=dev`
- `OBS_DISCOVERY_ENABLED=true`
- `DISCOVERY_NAMESPACES=dev`
- `K8S_API_URL=https://kubernetes.default.svc`
- `K8S_VERIFY_SSL=true`
- `K8S_SA_TOKEN_PATH=/var/run/secrets/kubernetes.io/serviceaccount/token`
- `K8S_SA_CA_PATH=/var/run/secrets/kubernetes.io/serviceaccount/ca.crt`
- `OBS_DISCOVERY_REFRESH_SECONDS=60`
- `OBS_DISCOVERY_VALIDATION_TIMEOUT_SECONDS=3`

Optional explicit overrides (take precedence over discovery):

- `PROMETHEUS_URL`
- `LOKI_URL`
- `JAEGER_URL`

Recommended for Docker backend outside Kubernetes with NGINX ingress:

- `PROMETHEUS_URL=http://minikube/prometheus`
- `LOKI_URL=http://minikube/loki`
- `JAEGER_URL=http://minikube/jaeger`

## Kubernetes RBAC Requirements

The backend service account must be allowed to read Services in discovery namespaces:

- `get`, `list` on `services`

If these permissions are missing, discovery degrades safely and backend continues operating.

## Runtime Behavior

- Discovery/enrichment never blocks telemetry ingestion.
- If a source is unreachable, status becomes `degraded` or `unavailable`.
- Reasoning continues with graceful degradation.
- Registry state is exposed in `context.observability_registry`.

## Validation Commands

Backend logs:

```bash
docker compose logs backend --tail=200
```

Expected log line:

`Observability discovery status prometheus=<state> loki=<state> jaeger=<state>`

Reasoning API:

```bash
curl "http://localhost:8080/api/reasoning/live?namespace=dev&service=all&cluster=minikube-dev&time_window=30m"
```

Check response path:

- `context.observability_registry.status`
- `context.observability_registry.sources`
- `context.observability_registry.checked_at`

## Troubleshooting

- `endpoint_not_configured_or_discovered`
  - No matching Kubernetes service found and no explicit URL configured.
- `degraded` with connection errors
  - Backend container cannot route to in-cluster service DNS.
  - Verify network model and service reachability from backend runtime.
- `unexpected_payload`
  - Endpoint exists but not a compatible Prometheus/Loki/Jaeger API response.

## Reuse Notes

For a new project, only update environment values (and RBAC if namespace differs). No code changes are required.

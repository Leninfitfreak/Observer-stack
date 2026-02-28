# Configuration Guide

## Configuration Model

All environment-specific values are externalized through environment variables.

No code edits are required to onboard new clusters/projects if configuration is updated correctly.

## Backend Configuration (`.env`)

Core:

- `DATABASE_URL` or (`DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`)
- `AGENT_TOKEN`
- `CLUSTER_ID`
- `DEFAULT_NAMESPACE`
- `DEFAULT_SERVICE`

Observability:

- `PROMETHEUS_URL`
- `LOKI_URL`
- `JAEGER_URL`
- For Docker backend + Minikube ingress, use path-based ingress URLs such as:
  - `PROMETHEUS_URL=http://minikube/prometheus`
  - `LOKI_URL=http://minikube/loki`
  - `JAEGER_URL=http://minikube/jaeger`

LLM:

- `LLM_PROVIDER`
- `LLM_MODEL`
- `LLAMA_API_URL`
- `LLAMA_API_KEY`
- `OLLAMA_URL`
- `OLLAMA_API_KEY`
- `OPENAI_BASE_URL`
- `OPENAI_API_KEY`

Runtime:

- `HTTP_TIMEOUT_SECONDS`
- `HTTP_ATTEMPTS`
- `KUBERNETES_ENABLED`
- `KUBERNETES_NAMESPACE`
- `OBS_DISCOVERY_ENABLED`
- `OBS_AUTO_DISCOVERY_ENABLED`
- `K8S_API_URL`
- `K8S_VERIFY_SSL`
- `K8S_SA_TOKEN_PATH`
- `K8S_SA_CA_PATH`
- `DISCOVERY_NAMESPACES`
- `OBS_DISCOVERY_REFRESH_SECONDS`
- `OBS_DISCOVERY_VALIDATION_TIMEOUT_SECONDS`

## Docker Compose

`docker-compose.yml` injects backend env vars and runs:

- `backend`
- `postgres`

Do not hardcode project values in source; place them in `.env`.

## Kubernetes Agent Configuration

Use ConfigMap for non-secret values and Secret for token.

ConfigMap keys:

- `CLUSTER_ID`
- `CENTRAL_URL`
- `PROM_URL`
- `PUSH_INTERVAL`
- `ENVIRONMENT`
- `K8S_DISCOVERY_ENABLED`
- `K8S_DISCOVERY_NAMESPACES`
- `K8S_DISCOVERY_TIMEOUT_SECONDS`
- `K8S_API_URL`
- `K8S_VERIFY_SSL`

Secret key:

- `AGENT_TOKEN`

## Istio Removal / NGINX Ingress Model

- Keep `ingress-nginx` as the only ingress path.
- Disable namespace Istio sidecar injection labels.
- Remove Istio CRDs/control-plane only after workloads run sidecar-free.
- Verify `Ingress` resources point directly to Kubernetes services.

Deployment must use:

- `envFrom.configMapRef`
- `envFrom.secretRef`

## New Cluster Onboarding (No Code Change)

Set only:

1. `CLUSTER_ID=<new-cluster>`
2. `CENTRAL_URL=http(s)://<central>/api/agent/push`
3. `AGENT_TOKEN=<shared-secret>`

Optionally adjust:

- `PROM_URL`
- `ENVIRONMENT`
- `PUSH_INTERVAL`

## Validation Commands

Backend health:

```bash
curl http://localhost:8080/healthz
```

Live reasoning:

```bash
curl "http://localhost:8080/api/reasoning/live?namespace=dev&service=all&cluster=minikube-dev&time_window=30m"
```

Incidents API:

```bash
curl "http://localhost:8080/api/incidents?start_date=2026-02-28&end_date=2026-02-28&cluster=minikube-dev&limit=20"
```

DB telemetry check:

```bash
docker compose exec -T postgres psql -U ai_observer -d ai_observer -c "SELECT cluster_id, raw_payload, created_at FROM incidents ORDER BY created_at DESC LIMIT 5;"
```

Observability discovery check:

```bash
curl "http://localhost:8080/api/reasoning/live?namespace=dev&service=all&cluster=minikube-dev&time_window=30m"
```

Validate `context.observability_registry` includes:

- `status.prometheus|loki|jaeger`
- `sources`
- `checked_at`
- `last_success_at`
- `last_error`

## Troubleshooting Matrix

- `401 invalid_agent_token`:
  - mismatch between agent secret and backend `AGENT_TOKEN`
- empty metrics in reasoning:
  - verify agent push logs and `raw_payload.metrics` in DB
- UI empty sections:
  - verify `/api/reasoning/live` JSON contains analysis fields
- wrong backend endpoint:
  - ensure `CENTRAL_URL` points to central Docker backend endpoint reachable from cluster
- topology not present in incidents:
  - verify agent logs include `Topology discovered ...`
  - verify `/api/agent/push` backend is rebuilt with topology payload support
- agent push timeouts:
  - verify backend is reachable via `CENTRAL_URL`
  - increase `PUSH_INTERVAL` and check backend CPU/load

## Topology + Discovery References

- See `TOPOLOGY_GUIDE.md` for topology schema, RBAC, and API validation.
- Backend observability auto-discovery is enabled through `OBS_DISCOVERY_ENABLED=true` (or legacy `OBS_AUTO_DISCOVERY_ENABLED=true`) and resolves Prometheus/Loki/Jaeger dynamically when explicit URLs are not set.
- See `OBSERVABILITY_DISCOVERY_GUIDE.md` for service matching, health probes, and troubleshooting.

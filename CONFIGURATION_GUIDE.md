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

Secret key:

- `AGENT_TOKEN`

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

## Troubleshooting Matrix

- `401 invalid_agent_token`:
  - mismatch between agent secret and backend `AGENT_TOKEN`
- empty metrics in reasoning:
  - verify agent push logs and `raw_payload.metrics` in DB
- UI empty sections:
  - verify `/api/reasoning/live` JSON contains analysis fields
- wrong backend endpoint:
  - ensure `CENTRAL_URL` points to central Docker backend endpoint reachable from cluster

# Reuse Guide

## Purpose

This project can be reused as a central AI observability intelligence backend for any Kubernetes cluster set.

Core flow:

`observer-agent (cluster) -> /api/agent/push -> PostgreSQL -> reasoning -> API/UI`

## Reusable Components

Reusable intelligence modules are in `src/ai_observer/intelligence`:

- `anomaly_engine.py`
- `correlation_engine.py`
- `dependency_graph_engine.py`
- `topology_engine.py`
- `temporal_engine.py`
- `causal_engine.py`
- `confidence_engine.py`
- `reasoning_engine.py`

All modules accept structured telemetry and produce structured output without hardcoded cluster/service names.

## Reuse for Another Project

1. Copy repo and set environment values in `.env`.
2. Start backend + database with Docker Compose.
3. Deploy observer-agent to target cluster with cluster-specific env (no code change).
4. Validate telemetry and reasoning with provided API checks.

## Required Project-Specific Configuration

- Prometheus endpoint (`PROMETHEUS_URL`)
- Cluster identifier (`CLUSTER_ID` / agent `CLUSTER_ID`)
- Namespace defaults (`DEFAULT_NAMESPACE`)
- DB connection (`DATABASE_URL` or DB vars)
- Agent auth token (`AGENT_TOKEN`)
- Central push URL (`CENTRAL_URL` on agent side)

## Deploy Backend (Central)

```bash
cp .env.example .env
docker compose up -d --build
```

## Deploy Agent (Cluster)

Set these in Kubernetes ConfigMap/Secret:

- `CLUSTER_ID`
- `CENTRAL_URL`
- `PROM_URL`
- `PUSH_INTERVAL`
- `ENVIRONMENT`
- `AGENT_TOKEN` (Secret)

Then apply manifests and let ArgoCD reconcile.

## Validation Checklist

1. Agent push succeeds:
   - backend logs contain `POST /api/agent/push ... 200`
2. DB stores telemetry:
   - `incidents.raw_payload.metrics` contains non-zero values
3. Reasoning endpoint returns structured intelligence:
   - `analysis.confidence_details`
   - `analysis.causal_analysis`
   - `analysis.correlated_signals`
   - `analysis.topology_insights`
4. Incidents API returns non-zero telemetry:
   - `cpu_usage`, `memory_usage`, `request_rate`
5. UI route works:
   - `GET /history` returns `200`

## Common Mistakes

- Using Kubernetes service DNS for backend when backend runs in Docker Compose.
- Token mismatch between agent and backend (`AGENT_TOKEN`).
- Port conflicts on `8080` with ArgoCD port-forward.
- Missing Prometheus connectivity from agent.
- Forgetting to rebuild backend after code updates.

## Troubleshooting

- Check backend logs:
  - `docker compose logs backend --tail=200`
- Check DB recent incidents:
  - query `incidents` and `incident_analysis`
- Check live reasoning payload:
  - `GET /api/reasoning/live?namespace=...&service=...`
- Check agent logs:
  - `kubectl logs -n <ns> deployment/observer-agent`

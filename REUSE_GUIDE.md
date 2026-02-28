# Reuse Guide

## Purpose

This project can be reused as a central AI observability intelligence backend for any Kubernetes cluster set.

Core flow:

`observer-agent (cluster) -> /api/agent/push -> PostgreSQL -> reasoning -> API/UI`

Incident-driven runtime contract:

- Reasoning is executed during incident creation/persistence paths (agent push / webhook), not dashboard refresh.
- Dashboard and history pages read stored incident + stored reasoning from `/api/incidents` and `/api/incidents/{id}`.
- `/api/reasoning/live` is for diagnostics and must not be used as the primary UI data source.

## Reusable Components

Reusable intelligence modules are in:

- `src/ai_observer/intelligence` (core reasoning engines)
- `src/ai_observer/backend/intelligence` (topology/discovery/dependency registry used by API/ingestion path)

- `anomaly_engine.py`
- `correlation_engine.py`
- `dependency_graph_engine.py`
- `topology_engine.py`
- `temporal_engine.py`
- `causal_engine.py`
- `confidence_engine.py`
- `reasoning_engine.py`
- `backend/intelligence/topology_engine.py`
- `backend/intelligence/dependency_engine.py`
- `backend/intelligence/discovery_engine.py`
- `backend/intelligence/observability_registry.py`
- `backend/intelligence/causal_engine.py`

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

## Istio-Free Cluster Mode (Recommended)

This platform does not require Istio.

- Keep NGINX Ingress Controller enabled.
- Ensure namespace sidecar injection is disabled.
- Route external traffic through Kubernetes Ingress resources (`ingressClassName: nginx`).
- Use observer-agent for telemetry forwarding and Kubernetes API topology discovery.

## Kubernetes Topology Discovery

`observer-agent` can enrich payloads with discovered topology metadata from Kubernetes API:

- namespaces
- pods
- services
- endpoints
- deployments
- ingresses

Required runtime permissions are provided through ServiceAccount + ClusterRole + ClusterRoleBinding in infra manifests.

Key env variables:

- `K8S_DISCOVERY_ENABLED` (`true|false`)
- `K8S_DISCOVERY_NAMESPACES` (comma-separated list; empty means all)
- `K8S_DISCOVERY_TIMEOUT_SECONDS`
- `K8S_API_URL` (default `https://kubernetes.default.svc`)
- `K8S_VERIFY_SSL` (`true|false`)

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
6. Dashboard is incident-view only:
   - open `/dashboard`
   - confirm backend logs show `/api/incidents` calls during refresh, not `/api/reasoning/live`

## Canonical Narrative Consistency

Narrative telemetry is enforced from one canonical object across live reasoning, persisted incidents, and API responses:

1. `incident_metrics_snapshot`
2. `incidents.raw_payload.metrics`
3. `incident_analysis.mitigation.telemetry`
4. fallback only when all sources are missing

Guarantees:

- Lower-priority zero values cannot override higher-priority real telemetry.
- `origin_service` is resolved from topology and normalized before narrative persistence/response.
- LLM is used for explanation only; telemetry/origin values are deterministic and sanitized post-LLM.
- Historical API responses are normalized so UI does not display stale `CPU 0%`, `Memory 0MB`, or unknown origin text when canonical telemetry exists.

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

# Topology Guide

## Purpose

AI Observer uses `observer-agent` to auto-discover Kubernetes topology and attach it to each telemetry push as `raw_payload.topology`.

The backend consumes this topology to build dependency graphs and improve origin-service and causal-chain inference.

## Discovery Data Model

`observer-agent` discovers:

- namespaces
- pods
- services
- endpoints
- deployments
- ingresses
- pod ownership chains (Pod -> ReplicaSet -> Deployment)
- service to pod mappings (selector based)
- service to service edges (ingress backend + pod env/args references)
- pod to container mapping
- observability services present in cluster (`prometheus`, `loki`, `jaeger`)

Top-level payload fields:

- `topology.cluster_id`
- `topology.discovered_at`
- `topology.counts`
- `topology.namespace_segmentation`
- `topology.observability_services`
- `topology.relations.*`

## Required Kubernetes RBAC

The agent service account needs `get/list/watch` on:

- core: `pods`, `services`, `endpoints`, `namespaces`
- apps: `deployments`
- networking.k8s.io: `ingresses`

## Required Agent Environment Variables

- `K8S_DISCOVERY_ENABLED=true`
- `K8S_DISCOVERY_NAMESPACES=dev` (or comma-separated namespaces; empty = all)
- `K8S_DISCOVERY_TIMEOUT_SECONDS=4`
- `K8S_API_URL=https://kubernetes.default.svc`
- `K8S_VERIFY_SSL=true`
- `K8S_SA_TOKEN_PATH=/var/run/secrets/kubernetes.io/serviceaccount/token`
- `K8S_SA_CA_PATH=/var/run/secrets/kubernetes.io/serviceaccount/ca.crt`

## Backend Topology Integration

Backend modules:

- `src/ai_observer/backend/intelligence/discovery_engine.py`
- `src/ai_observer/backend/intelligence/observability_registry.py`
- `src/ai_observer/backend/intelligence/dependency_engine.py`
- `src/ai_observer/backend/intelligence/topology_engine.py`
- `src/ai_observer/backend/intelligence/causal_engine.py`

Runtime behavior:

1. Agent push stores full topology in `incidents.raw_payload`.
2. Backend builds dependency graph from `topology.relations`.
3. Reasoning fallback path resolves `origin_service`, `impacted_services`, and `causal_chain` from topology.
4. API responses expose topology-aware fields:
   - `origin_service`
   - `topology_insights`
   - `causal_chain`

## Validation Steps

1. Agent logs:

```bash
kubectl logs -n dev deployment/observer-agent | grep "Topology discovered"
```

Expected format: `Topology discovered namespaces=X pods=Y services=Z ...`

2. Confirm topology in DB:

```bash
docker compose exec -T postgres psql -U ai_observer -d ai_observer -c "SELECT incident_id, raw_payload->'topology' IS NOT NULL AS has_topology, created_at FROM incidents ORDER BY created_at DESC LIMIT 5;"
```

3. Confirm live reasoning contains topology fields:

```bash
curl "http://localhost:8080/api/reasoning/live?namespace=dev&service=all&cluster=minikube-dev&time_window=30m"
```

Check:

- `analysis.origin_service != "unknown"` when topology exists
- `analysis.topology_insights` populated
- `analysis.causal_chain` includes topology lines

4. Confirm incidents API includes topology-aware fields:

```bash
curl "http://localhost:8080/api/incidents?start_date=2026-02-01&end_date=2026-12-31&cluster=minikube-dev&limit=20"
```

## Troubleshooting

- No topology in incidents:
  - verify RBAC and service account on agent deployment
  - verify discovery env vars in ConfigMap
  - check agent can access K8s API in pod logs
- `origin_service` still unknown:
  - verify `topology.relations.service_to_pod` or `service_to_service` has entries
  - verify backend is running latest image/code
- Missing observability service detection:
  - verify Prometheus/Loki/Jaeger services exist in discovered namespaces

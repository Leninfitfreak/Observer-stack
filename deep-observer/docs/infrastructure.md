# Infrastructure Architecture (GitOps / Kubernetes)

## Repository and Pattern
- Repo: `C:\Projects\infra\leninkart-infra`
- GitOps controller: ArgoCD
- Root app: `argocd/leninkart-root.yaml`
  - Recursively syncs `argocd/applications/dev`
  - `automated.prune=true`, `selfHeal=true`

## Environment Layout
- Main runtime namespace: `dev`
- Additional cluster namespaces are present (`argocd`, `kube-system`, etc.)
- App-of-apps model deploys:
  - `frontend`
  - `product-service`
  - `order-service`
  - `otel-collector`
  - ingress and platform apps

## Core K8s Objects in Flow
- Deployments:
  - `frontend`
  - `product-service`
  - `order-service`
  - `traffic-generator` (loadtest)
  - `otel-collector`
- Services:
  - `leninkart-frontend` (80)
  - `leninkart-product-service` (8081)
  - `leninkart-order-service` (8080)
  - infra/platform services (postgres, ingress, etc.)
- Ingress:
  - `platform/ingress/dev/ingress.yaml`
  - Routes:
    - `/` -> frontend
    - `/auth`, `/api/products` -> product-service
    - `/api/orders` -> order-service

## ConfigMaps and Secrets
- OTEL config via `observability/otel/collector-configmap.yaml`.
- Service environment values via Helm `values-dev.yaml`.
- Vault + External Secrets manifests exist under `platform/external-secrets` and `platform/vault`.
- Deployments can consume DB/app secrets via `envFrom` secret refs (templated in Helm).

## Service Discovery Model
Service discovery is achieved through:
- Kubernetes DNS (`*.svc.cluster.local`)
- Ingress path routing
- OTEL resource metadata enrichment (`k8s.namespace.name`, `k8s.pod.name`, `k8s.deployment.name`)
- Deep Observer dynamic filters (`/api/filters`) combining telemetry + K8s namespace discovery.

## Notes
- Infrastructure repo still includes legacy docs/references to Prometheus/Grafana/Jaeger; Deep Observer runtime for this project consumes SigNoz/ClickHouse telemetry.


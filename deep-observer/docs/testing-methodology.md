# Testing Methodology

## Objective
Validate Deep Observer end-to-end against real telemetry and real service interactions.

## Test Stages

1. **Platform Prerequisites**
- `docker compose -f kafka-platform/docker-compose.yml up -d`
- `minikube status`
- `kubectl get pods -A`

2. **Deep Observer Build/Runtime**
- `docker compose build` (inside `Deep-observer`)
- `docker compose up -d`
- `docker compose ps`

3. **API Health and Contract**
- `/health`
- `/api/filters`
- `/api/incidents`
- `/api/topology`
- `/api/service-health`
- `/api/cluster-report`
- `/api/changes`
- `/api/slo-status`
- `/api/runbooks`
- `/api/observability-report`

4. **Traffic Validation**
- Ensure load generator or manual user flow drives:
  - `/` frontend
  - `/api/products`
  - `/api/orders`
  - Kafka produce/consume path

5. **Telemetry Validation**
- Verify traces/metrics/logs exist in ClickHouse-backed APIs.
- Confirm topology contains service and external nodes where telemetry supports them.

6. **Incident and RCA Validation**
- Verify incidents are generated from anomalies.
- Verify root cause and impacted services are populated.
- Verify reasoning validation flags unsupported claims.
- Verify runbooks include signal-driven remediation actions.

## Stability Criteria
- No crashing Deep Observer containers.
- Dashboard loads and refreshes without API errors.
- Filters update all major panels consistently.
- Telemetry coverage report reflects real signal presence/absence.


# BOOTSTRAP_VALIDATION_REPORT

## Final Status
Passed.

The existing SigNoz bootstrap implementation in [bootstrap.py](D:/Projects/Services/observer-stack/bootstrap/bootstrap.py) now works end-to-end against the live Docker-based observer stack, with runtime evidence from Docker, the SigNoz API, the SigNoz UI, and post-run evaluator logs.

## What Was Executed
- Read the existing bootstrap implementation and config:
  - [bootstrap.py](D:/Projects/Services/observer-stack/bootstrap/bootstrap.py)
  - [variables.env](D:/Projects/Services/observer-stack/bootstrap/variables.env)
  - [dashboards.yaml](D:/Projects/Services/observer-stack/bootstrap/dashboards.yaml)
  - [alerts.yaml](D:/Projects/Services/observer-stack/bootstrap/alerts.yaml)
  - [channels.yaml](D:/Projects/Services/observer-stack/bootstrap/channels.yaml)
  - [README.md](D:/Projects/Services/observer-stack/bootstrap/README.md)
- Verified runtime health for SigNoz, ClickHouse, ZooKeeper, the SigNoz collector, and external Kafka.
- Validated API-key authentication live against SigNoz.
- Ran the bootstrap multiple times and validated idempotency.
- Captured UI screenshots for login, home, dashboards, alerts, and channels.

## Runtime Detected
- SigNoz runs only on Docker Compose and remained external to Kubernetes.
- `http://127.0.0.1:8080` was reachable.
- `GET /api/v1/health` returned `ok`.
- `GET /api/v1/version` returned `v0.113.0` and `setupCompleted=true`.
- The live SigNoz API key authenticated successfully through Vault.

## Dashboards Found
9 dashboards were confirmed via the live API:
- LeninKart Frontend HTTP Monitoring
- LeninKart Auth Service APM
- LeninKart Product Service APM
- LeninKart Order Service APM
- LeninKart Product Service JVM
- LeninKart Order Service JVM
- LeninKart Database Visibility
- LeninKart otel-collector Pod Metrics
- LeninKart Kafka Overview

## Alerts Found
13 alert rules were confirmed via the live API:
- leninkart-product-service-high-latency
- leninkart-order-service-high-latency
- leninkart-product-service-high-error-rate
- leninkart-order-service-high-error-rate
- leninkart-product-service-high-cpu
- leninkart-order-service-high-cpu
- leninkart-product-service-high-memory
- leninkart-order-service-high-memory
- leninkart-kafka-consumer-lag
- leninkart-product-service-no-traffic
- leninkart-order-service-no-traffic
- leninkart-log-error-spike
- leninkart-otel-export-failures

The alert set includes:
- metrics-based alerts
- traces-based alerts
- a logs-based alert
- service down style coverage through no-traffic absent checks

## Channels Found
- Created: `LeninKart Email Alerts`
- Slack support remains present in config and code, but was intentionally skipped because `ENABLE_SLACK_ALERTS=false` and no webhook was configured.

This confirms variable-driven behavior instead of silent hardcoding.

## Idempotency
Passed.

The rerun updated existing resources in place:
- channel was updated, not duplicated
- dashboards were updated, not duplicated
- alerts were updated, not duplicated

## Variable-Driven Validation
Passed.

Observed behavior matched config toggles in [variables.env](D:/Projects/Services/observer-stack/bootstrap/variables.env):
- email alerts enabled -> email channel created
- Slack alerts disabled -> Slack channel skipped
- metric alerts enabled -> metric alerts created
- log alerts enabled -> logs-based alert created

## What Failed Initially
1. Vault secret mismatch
   - Vault did not hold the currently working SigNoz API key, so the bootstrap would not have authenticated correctly without the plaintext fallback.
2. Email channel payload mismatch
   - SigNoz rejected the initial email payload because `email_configs[].to` was sent as an array.
3. Trace error-rate filter mismatch
   - `status.code` was not recognized by the running SigNoz trace schema.
4. Metric alert filter mismatches
   - The original no-traffic and OTel exporter filters did not match the live evaluator's accepted field shape for this stack.

## What Was Fixed
See [BOOTSTRAP_FIXES_APPLIED.md](D:/Projects/Services/observer-stack/bootstrap/BOOTSTRAP_FIXES_APPLIED.md).

## Evidence Files
- [last-run-summary.json](D:/Projects/Services/observer-stack/bootstrap/last-run-summary.json)
- [validation-summary.json](D:/Projects/Services/observer-stack/bootstrap/validation-summary.json)
- [BOOTSTRAP_RUNTIME_LOG.md](D:/Projects/Services/observer-stack/bootstrap/BOOTSTRAP_RUNTIME_LOG.md)
- [BOOTSTRAP_FIXES_APPLIED.md](D:/Projects/Services/observer-stack/bootstrap/BOOTSTRAP_FIXES_APPLIED.md)
- [screenshots/observer-stack](D:/Projects/Services/screenshots/observer-stack)

## Final Confirmation
- Bootstrap script runs successfully.
- SigNoz is reachable.
- Authentication works with the live API key sourced from Vault.
- Dashboards are created and updated successfully.
- Alert rules are created and updated successfully.
- Notification channels are created according to enabled config.
- Reruns are idempotent.
- UI screenshots were captured.
- No secrets were exposed in generated artifacts.

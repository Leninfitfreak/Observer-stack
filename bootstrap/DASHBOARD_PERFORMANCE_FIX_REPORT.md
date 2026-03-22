# DASHBOARD_PERFORMANCE_FIX_REPORT

## Scope
This pass optimized only the SigNoz dashboard layer used by the existing LeninKart bootstrap. Alerts, channels, and the Docker Compose observer stack were left intact.

## Dashboards That Were Too Heavy
- `LeninKart otel-collector Pod Metrics`
- `LeninKart Kafka Overview`

## Root Cause
- The original otel dashboard was an imported Kubernetes pod template with 3 variable queries against `signoz_metrics.distributed_time_series_v4_1day`.
- The original otel widgets grouped by `k8s.node.name`, `k8s.namespace.name`, `k8s.pod.name`, `interface`, and `direction`.
- The original Kafka dashboard grouped by `group + topic + partition`, which created a high-cardinality render path.
- Those combinations made the UI expensive to open and were consistent with the Chrome "page unresponsive" behavior seen during validation.

## What Changed
- Replaced the imported otel pod dashboard with a generated LeninKart-specific collector summary.
- Removed all otel dashboard variables.
- Reduced the otel dashboard from 4 widgets to 2 exporter-focused widgets:
  - `Exporter Sent Spans`
  - `Exporter Send Failed Spans`
- Reworked the Kafka dashboard from partition-heavy panels to lightweight summary panels:
  - `Total Consumer Lag`
  - `Messages Consumed by Group`
  - `Messages In Rate`
- Removed Kafka partition-level groupings.
- Reduced panel bucket counts to `12` for the optimized generated dashboards.
- Kept the dashboard titles stable so bootstrap updates replace the old dashboards in place.

## Before And After
- Dashboard list response:
  - Earlier validation sample: about `352061` bytes
  - After optimization: about `339909` bytes in `0.48s`
- Kafka dashboard payload:
  - Before: 4 widgets, partition-level grouping, about `6340` bytes
  - After: 3 widgets, no partition grouping, about `4624` bytes
- OTel dashboard payload:
  - Before: 4 widgets, 3 SQL-backed variables, about `6630` bytes
  - After: 2 widgets, 0 variables, about `3105` bytes

## What Was Removed
- OTel variable queries for:
  - `k8s.cluster.name`
  - `k8s.node.name`
  - `k8s.namespace.name`
- OTel pod network and broad pod breakdown widgets
- Kafka partition-level lag and current-offset widgets

## What Was Kept
- Dashboard bootstrap remains idempotent.
- Existing dashboard titles remain stable.
- Kafka visibility remains available at the service level.
- OTel visibility remains available for collector export health.
- Existing alerts and notification channels were not modified by this pass.

## Validation Evidence
- Bootstrap rerun updated dashboards successfully through [bootstrap.py](D:/Projects/Services/observer-stack/bootstrap/bootstrap.py).
- Direct dashboard API payloads now show the smaller generated definitions.
- Updated UI evidence exists in:
  - [dashboard-list.png](D:/Projects/Services/screenshots/observer-stack/dashboard-list.png)
  - [ui-capture-summary.json](D:/Projects/Services/screenshots/observer-stack/ui-capture-summary.json)

## Remaining Limitation
- Headless Playwright still times out when trying to screenshot the direct Kafka and otel dashboard routes, even after the dashboard payloads were reduced.
- The improved API payloads and the responsive dashboard list confirm the worst high-cardinality definitions were removed, but a final manual browser confirmation of direct dashboard rendering is still advisable for this local workstation.

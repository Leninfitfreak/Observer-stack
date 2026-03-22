# MINIMAL_DASHBOARD_SIMPLIFICATION_REPORT

## Summary

The LeninKart dashboard set now does two things:

1. keeps only a small showcase-oriented set of generated dashboards
2. validates every widget query live against SigNoz before the dashboard is written

This means dashboard creation no longer treats `created successfully` as enough. A widget is kept only if its underlying query stays within the live safety thresholds.

## Why The Old Set Was Replaced

The older dashboard set mixed imported SigNoz templates with local generated dashboards:

- imported APM templates for frontend, auth, product, and order
- imported JVM templates for product and order
- imported PostgreSQL visibility dashboard
- generated Kafka and otel dashboards

Those imported templates were larger, less predictable, and not needed for the GitHub/LinkedIn showcase requirement.

## What Was Removed Or Replaced

Removed from the active LeninKart dashboard set:

- `LeninKart Frontend HTTP Monitoring`
- `LeninKart Auth Service APM`
- `LeninKart Product Service APM`
- `LeninKart Order Service APM`
- `LeninKart Product Service JVM`
- `LeninKart Order Service JVM`
- `LeninKart Database Visibility`
- `LeninKart otel-collector Pod Metrics`
- `LeninKart Debug Minimal Dashboard`

## Final Dashboard List

- `LeninKart Platform Overview`
  Widgets kept: `4`
- `LeninKart Product Service Overview`
  Widgets kept: `2`
- `LeninKart Order Service Overview`
  Widgets kept: `2`
- `LeninKart Kafka Overview`
  Widgets kept: `1`
- `LeninKart Frontend Overview`
  Widgets kept: `2`

## Query Validation Gate

Bootstrap now validates every widget query through the live `/api/v5/query_range` API before saving the dashboard.

Safe widgets are kept.

Unsafe widgets are removed when they cross the configured thresholds for:

- backend query duration
- end-to-end wall-clock response time
- rows scanned
- bytes scanned
- group-by width
- series count

Implementation:

- [bootstrap.py](D:/Projects/Services/observer-stack/bootstrap/bootstrap.py)
- [DASHBOARD_QUERY_VALIDATION_REPORT.md](D:/Projects/Services/observer-stack/bootstrap/DASHBOARD_QUERY_VALIDATION_REPORT.md)

## Widgets Removed By Query Validation

- `LeninKart Product Service Overview`
  Removed: `External Call Rate`
- `LeninKart Order Service Overview`
  Removed: `Database Call Rate`
- `LeninKart Kafka Overview`
  Removed: `Total Consumer Lag`, `Messages Consumed by Group`
- `LeninKart Frontend Overview`
  Removed: `CPU Utilization`

These were removed because the live validation pass classified them as unsafe or too slow for the showcase dashboard budget.

## Why The New Set Is Stable

The final dashboards are stable because they now satisfy both constraints:

- small dashboard size
- individually validated widget queries

The remaining widgets avoid:

- template-driven query fanout
- expensive dashboard variables
- high-cardinality Kafka breakdowns
- widgets that repeatedly cross the wall-time/query-duration thresholds

## Validation Outcome

The final five dashboards:

- appear in the dashboard list
- open through UI click navigation
- remain responsive
- render visible content
- pass direct-route checks
- have screenshot evidence

See:

- [DASHBOARD_QUERY_VALIDATION_REPORT.md](D:/Projects/Services/observer-stack/bootstrap/DASHBOARD_QUERY_VALIDATION_REPORT.md)
- [DASHBOARD_E2E_VALIDATION_REPORT.md](D:/Projects/Services/observer-stack/bootstrap/DASHBOARD_E2E_VALIDATION_REPORT.md)
- [dashboard-e2e-summary.json](D:/Projects/Services/observer-stack/bootstrap/dashboard-e2e-summary.json)

## Screenshot Paths

- [dashboard-list-e2e.png](D:/Projects/Services/screenshots/observer-stack/dashboard-list-e2e.png)
- [dashboard-platform-overview-e2e.png](D:/Projects/Services/screenshots/observer-stack/dashboard-platform-overview-e2e.png)
- [dashboard-product-service-overview-e2e.png](D:/Projects/Services/screenshots/observer-stack/dashboard-product-service-overview-e2e.png)
- [dashboard-order-service-overview-e2e.png](D:/Projects/Services/screenshots/observer-stack/dashboard-order-service-overview-e2e.png)
- [dashboard-kafka-e2e.png](D:/Projects/Services/screenshots/observer-stack/dashboard-kafka-e2e.png)
- [dashboard-frontend-overview-e2e.png](D:/Projects/Services/screenshots/observer-stack/dashboard-frontend-overview-e2e.png)

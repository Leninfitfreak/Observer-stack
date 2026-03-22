# DASHBOARD_E2E_VALIDATION_REPORT

## Scope

This validation pass tested the query-validated showcase dashboards only. The goal was end-to-end browser usability from the SigNoz dashboard list after removing widgets that failed the live query-safety checks.

Validation script used:

- [validate_dashboards_e2e.mjs](D:/Projects/Services/observer-stack/bootstrap/validate_dashboards_e2e.mjs)

## Test Method

The validator:

- starts from a clean Playwright browser context
- fetches the live SigNoz user identity using the existing API key
- generates valid JWT session tokens for the local SigNoz UI
- opens the dashboard list
- locates each supported dashboard from the list
- clicks into the dashboard
- waits for visible content
- verifies the page remains responsive
- rechecks the direct route
- captures screenshots and request/console evidence

## Dashboards Tested

- `LeninKart Platform Overview`
- `LeninKart Product Service Overview`
- `LeninKart Order Service Overview`
- `LeninKart Kafka Overview`
- `LeninKart Frontend Overview`

## Results

All five dashboards passed after query validation trimmed the unsafe widgets.

Dashboard list:

- title: `SigNoz | All Dashboards`
- elapsed: `15.639s`

Per-dashboard click-flow timings:

- Platform Overview: `19.553s`
- Product Service Overview: `20.615s`
- Order Service Overview: `16.626s`
- Kafka Overview: `13.844s`
- Frontend Overview: `17.036s`

Pass criteria status:

- appears in dashboard list: yes
- opens through UI click navigation: yes
- direct route opens: yes
- page remains responsive: yes
- visible dashboard content renders: yes
- screenshot captured: yes
- browser automation completed without freeze: yes

## Query-Safe Final Widget Set

- `LeninKart Platform Overview`
  Widgets rendered: `4`
- `LeninKart Product Service Overview`
  Widgets rendered: `2`
- `LeninKart Order Service Overview`
  Widgets rendered: `2`
- `LeninKart Kafka Overview`
  Widgets rendered: `1`
- `LeninKart Frontend Overview`
  Widgets rendered: `2`

## Non-Blocking Noise

The UI still logs stock SigNoz noise during validation:

- `GET /api/v3/licenses/active` returns `404`
- the frontend logs `no active license found`
- some widgets log `aggregateData is null in baseAggregateOptionsConfig`
- a few `query_range` requests are aborted while navigating away from a page, which showed up as `net::ERR_ABORTED` but did not block rendering

These did not block dashboard rendering, navigation, responsiveness, or screenshot capture for the supported dashboards.

## Evidence

Detailed summary:

- [dashboard-e2e-summary.json](D:/Projects/Services/observer-stack/bootstrap/dashboard-e2e-summary.json)

Screenshots:

- [dashboard-list-e2e.png](D:/Projects/Services/screenshots/observer-stack/dashboard-list-e2e.png)
- [dashboard-platform-overview-e2e.png](D:/Projects/Services/screenshots/observer-stack/dashboard-platform-overview-e2e.png)
- [dashboard-product-service-overview-e2e.png](D:/Projects/Services/screenshots/observer-stack/dashboard-product-service-overview-e2e.png)
- [dashboard-order-service-overview-e2e.png](D:/Projects/Services/screenshots/observer-stack/dashboard-order-service-overview-e2e.png)
- [dashboard-kafka-e2e.png](D:/Projects/Services/screenshots/observer-stack/dashboard-kafka-e2e.png)
- [dashboard-frontend-overview-e2e.png](D:/Projects/Services/screenshots/observer-stack/dashboard-frontend-overview-e2e.png)

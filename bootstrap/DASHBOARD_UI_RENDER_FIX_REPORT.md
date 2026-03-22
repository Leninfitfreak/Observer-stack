# DASHBOARD_UI_RENDER_FIX_REPORT

## Final Status

The supported LeninKart dashboards are now rendering successfully in the browser on the stabilized runtime.

## What Was Actually Wrong

The earlier dashboard-failure conclusion was contaminated by two separate issues:

1. The old browser harness was not creating a real SigNoz UI session.
   - It set `IS_LOGGED_IN=true` with placeholder tokens.
   - SigNoz frontend API clients actually use `Authorization: Bearer <AUTH_TOKEN>` from local storage.
   - That caused route probes to mix real dashboard behavior with invalid-session behavior.

2. The running `signoz` container was serving a locally mounted frontend bundle instead of the stock `signoz/signoz:v0.113.0` web assets.
   - Local mounted bundle: `main.1a57560a62c536ce9c9d.js`
   - Official image bundle: `main.1b22b7bbc971cbdb8aa7.js`
   - This was a workspace-specific deviation from official SigNoz Docker behavior.

## Safe Fix Applied

### 1. Corrected the validation method

- Added [validate_dashboards_e2e.mjs](D:/Projects/Services/observer-stack/bootstrap/validate_dashboards_e2e.mjs)
- The validator now:
  - fetches the live user identity from `/api/v1/user/me` using the existing validated API key
  - generates a valid local JWT using the configured SigNoz tokenizer secret
  - stores real bearer tokens in `AUTH_TOKEN` and `REFRESH_AUTH_TOKEN`
  - validates dashboards through normal UI click navigation from the dashboard list

This fixed the invalid-session problem without changing SigNoz auth configuration.

### 2. Restored the official SigNoz frontend bundle

Changed file:

- [docker-compose.yaml](D:/Projects/Services/observer-stack/deploy/docker/docker-compose.yaml)

Change:

- Removed the local frontend override mount:
  - `../../frontend/build:/etc/signoz/web:ro`

Why this was safe:

- It restores the stock frontend assets shipped in the official `signoz/signoz:v0.113.0` image.
- It does not modify ClickHouse, SQLite data, alerts, channels, or dashboards.
- It removes a non-official local deviation from the running observer stack.

## Proof Of Official Alignment

After recreating only the `signoz` container:

- `http://127.0.0.1:8080` served:
  - `main.1b22b7bbc971cbdb8aa7.js`
- The running bundle now matches the stock `signoz/signoz:v0.113.0` image instead of the local mounted build.

## Browser Validation Outcome

Validated through actual UI navigation from the dashboard list:

- `LeninKart Frontend HTTP Monitoring`: pass
- `LeninKart Product Service APM`: pass
- `LeninKart Order Service APM`: pass
- `LeninKart Kafka Overview`: pass
- `LeninKart otel-collector Pod Metrics`: pass
- `LeninKart Database Visibility`: pass
- `LeninKart Debug Minimal Dashboard`: pass

Pass criteria achieved for each:

- dashboard appears in list
- dashboard opens via click navigation
- direct route also opens
- page remains responsive
- visible content renders
- screenshot captured

## Evidence

Summary:

- [dashboard-e2e-summary.json](D:/Projects/Services/observer-stack/bootstrap/dashboard-e2e-summary.json)
- [dashboard-list-e2e.png](D:/Projects/Services/screenshots/observer-stack/dashboard-list-e2e.png)

Per-dashboard screenshots:

- [dashboard-frontend-http-e2e.png](D:/Projects/Services/screenshots/observer-stack/dashboard-frontend-http-e2e.png)
- [dashboard-product-apm-e2e.png](D:/Projects/Services/screenshots/observer-stack/dashboard-product-apm-e2e.png)
- [dashboard-order-apm-e2e.png](D:/Projects/Services/screenshots/observer-stack/dashboard-order-apm-e2e.png)
- [dashboard-kafka-e2e.png](D:/Projects/Services/screenshots/observer-stack/dashboard-kafka-e2e.png)
- [dashboard-otel-e2e.png](D:/Projects/Services/screenshots/observer-stack/dashboard-otel-e2e.png)
- [dashboard-database-e2e.png](D:/Projects/Services/screenshots/observer-stack/dashboard-database-e2e.png)
- [dashboard-minimal-debug-e2e.png](D:/Projects/Services/screenshots/observer-stack/dashboard-minimal-debug-e2e.png)

## Remaining Noise

Non-blocking console/API noise still appears during validation:

- `GET /api/v3/licenses/active` returns `404`
- some dashboard loads show transient `400` or aborted requests for variable/query-range calls
- the frontend logs a noisy `APIError: no active license found...`

These did not block rendering or responsiveness in the validated dashboards.

## Root Cause Assessment

The remaining user-visible dashboard failure was not a dashboard-schema bug.

The effective root causes were:

- invalid browser-session simulation in the earlier validation harness
- a local frontend bundle override that deviated from official SigNoz Docker behavior

Once validation used a real bearer session and the stack served the official frontend bundle, the supported dashboards rendered successfully.

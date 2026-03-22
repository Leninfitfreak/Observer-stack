# BOOTSTRAP_RUNTIME_LOG

## Runtime Detected
Date validated: March 22, 2026

```text
signoz                 Up 4 hours (healthy)   0.0.0.0:8080->8080/tcp
signoz-otel-collector  Up 4 hours             0.0.0.0:4317-4318->4317-4318/tcp
signoz-clickhouse      Up 4 hours (healthy)
signoz-zookeeper-1     Up 4 hours (healthy)
kafka-platform         Up 3 days (healthy)    0.0.0.0:7071->7071/tcp, 0.0.0.0:9092->9092/tcp
```

## Reachability
```text
GET http://127.0.0.1:8080/api/v1/health -> {"status":"ok"}
GET http://127.0.0.1:8080/api/v1/version -> version v0.113.0, setupCompleted true
GET http://127.0.0.1:8080/api/v1/user/me with API key -> success
```

## Bootstrap Runs
1. Initial validation run
   - Failed on channel creation because the live SigNoz API expects `email_configs[].to` as a string.
2. Second run after payload fix
   - Created `LeninKart Email Alerts`
   - Updated all 9 dashboards
   - Created all 13 alerts
3. Idempotency rerun
   - Updated existing channel, dashboards, and alerts in place
   - Created no uncontrolled duplicates
4. Final rerun after evaluator fixes
   - Updated the three previously invalid alert rules
   - Confirmed they evaluated successfully in live SigNoz logs

## API Validation Summary
```text
Dashboards: 9
Channels: 1
Alerts: 13
Logs-based alert present: yes
Slack channel created: no, skipped intentionally by config
```

## UI Evidence
Generated in [screenshots/observer-stack](D:/Projects/Services/screenshots/observer-stack):
- [login-page.png](D:/Projects/Services/screenshots/observer-stack/login-page.png)
- [home.png](D:/Projects/Services/screenshots/observer-stack/home.png)
- [dashboard-list.png](D:/Projects/Services/screenshots/observer-stack/dashboard-list.png)
- [alerts-list.png](D:/Projects/Services/screenshots/observer-stack/alerts-list.png)
- [channels-list.png](D:/Projects/Services/screenshots/observer-stack/channels-list.png)
- [ui-capture-summary.json](D:/Projects/Services/screenshots/observer-stack/ui-capture-summary.json)

## Notes
- The UI screenshots were captured by injecting the already validated SigNoz API key as a browser header and setting the app's logged-in local state. This avoided changing SigNoz auth or storing any new credentials.
- The real SigNoz API key was not written to logs or reports.

# BOOTSTRAP_FIXES_APPLIED

## Scope
This validation pass kept the existing bootstrap design and only changed the parts proven broken by live execution.

## Fixes
1. Secret source correction
   - The working SigNoz API key was not usable from Vault at runtime.
   - The Vault secret at `secret/leninkart/observability` was refreshed with the live key.
   - `SIGNOZ_API_KEY` was then blanked in `observer-stack/bootstrap/variables.env` so the bootstrap now prefers Vault as intended.

2. Email channel API contract
   - The live SigNoz API rejected `email_configs[].to` as an array.
   - [bootstrap.py](D:/Projects/Services/observer-stack/bootstrap/bootstrap.py) was updated to send a comma-separated string, which matches the running SigNoz API schema.

3. Trace error-rate rules
   - The original filters used `status.code`, which the live SigNoz trace schema did not recognize.
   - [alerts.yaml](D:/Projects/Services/observer-stack/bootstrap/alerts.yaml) now uses `hasError = true` for the two trace error-rate alerts.

4. No-traffic rules
   - The original metric filters for `signoz.calls.total` failed against the live metric label shape.
   - The two no-traffic alerts were converted to traces-based absent checks using `serviceName = '<service>' AND spanKind = 'Server'`, which evaluates correctly in this stack.

5. OTel exporter failure rule
   - The original filter on `otelcol.exporter.send_failed_spans` failed because the queried metric series did not expose the expected service label.
   - The unsupported filter was removed so the rule evaluates against the metric globally in this local observer stack.

## Files Changed
- [bootstrap.py](D:/Projects/Services/observer-stack/bootstrap/bootstrap.py)
- [variables.env](D:/Projects/Services/observer-stack/bootstrap/variables.env)
- [alerts.yaml](D:/Projects/Services/observer-stack/bootstrap/alerts.yaml)
- [capture_ui.mjs](D:/Projects/Services/observer-stack/bootstrap/capture_ui.mjs)

## Result
The bootstrap now:
- authenticates from Vault
- creates or updates the email notification channel
- updates dashboards idempotently
- creates and updates all 13 alert rules
- reruns without duplicate creation
- evaluates the full active rule set without the earlier filter parse failures

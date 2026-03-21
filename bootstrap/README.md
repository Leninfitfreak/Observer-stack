# SigNoz Bootstrap

This module bootstraps LeninKart SigNoz dashboards, alert rules, and notification channels against the running Docker Compose observer stack.

## Files

- `bootstrap.py`: waits for SigNoz, resolves the API key, and applies channels, dashboards, and alerts idempotently
- `variables.env`: variable-driven configuration
- `dashboards.yaml`: dashboard definitions
- `alerts.yaml`: alert rule definitions
- `channels.yaml`: notification channel definitions
- `last-run-summary.json`: generated after each run

## How It Resolves Secrets

1. `SIGNOZ_API_KEY` from the current environment
2. `signoz_api_key` from the workspace root `.env`
3. Vault secret `secret/leninkart/observability` field `signoz_api_key`

The script does not print the API key.

## Run

```powershell
python .\observer-stack\bootstrap\bootstrap.py
```

## Notes

- SigNoz stays external in Docker Compose.
- The bootstrap is safe to re-run.
- Email and Slack channels are only created when their enable flags and values are provided.

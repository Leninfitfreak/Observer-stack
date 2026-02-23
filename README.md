# AI Observer Agent

FastAPI webhook service for incident analysis.

## Run locally

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8080
```

## Architecture

- New reusable architecture lives in `src/ai_observer`.
- Legacy entrypoint `app/main.py` is a compatibility wrapper.
- See `ARCHITECTURE.md` for folder layout, DI pattern, provider abstraction, and LLM provider switching examples.

## Environment variables

- `PROMETHEUS_URL` (default: `http://prometheus:9090`)
- `LOKI_URL` (default: `http://loki-gateway:80`)
- `JAEGER_URL` (default: `http://jaeger-query:16686`)
- `LLM_PROVIDER` (`openai` or `ollama`, default: `ollama`)
- `LLM_MODEL` (default: `gpt-oss:20b`)
- `HTTP_TIMEOUT_SECONDS` (default: `30`)
- `HTTP_ATTEMPTS` (default: `3`)
- `OPENAI_BASE_URL` (default: `https://api.openai.com/v1`)
- `OPENAI_API_KEY` (required when `LLM_PROVIDER=openai`)
- `OLLAMA_URL` (used when `LLM_PROVIDER=ollama`, default: `https://ollama.com`)
- `OLLAMA_API_KEY` (recommended when `LLM_PROVIDER=ollama`)
- `DEFAULT_NAMESPACE` (default: `dev`)
- `SLO_TARGET` (default: `0.995`)
- `OLLAMA_TIMEOUT_SECONDS` (default: `180`)
- `OLLAMA_ATTEMPTS` (default: `1`)
- `KNOWN_ERROR_SIGNATURES` (optional, comma-separated)
- `DATABASE_URL` (default: `postgresql+psycopg://postgres:postgres@postgres:5432/ai_observer`)
- `DB_ECHO_SQL` (default: `false`)

## Endpoints

- `GET /healthz`
- `POST /webhook/alertmanager`
- `GET /api/reasoning/live?namespace=dev&service=order-service&severity=warning`
- `GET /dashboard`
- `POST /incident-analysis`
- `GET /incident-analysis?start_date=2026-02-20&end_date=2026-02-23&service_name=order-service&limit=50&offset=0`
- `GET /incident-analysis/summary?start_date=2026-02-20&end_date=2026-02-23`
- `PATCH /incident-analysis/{incident_id}/mitigation-result`

## Response highlights

`POST /webhook/alertmanager` returns:
- `context`: metrics + traces + logs + kubernetes + deployment + slo + datasource_errors
- `analysis`:
  - `probable_root_cause`, `impact_level`, `recommended_remediation`, `confidence_score`
  - `causal_chain`, `corrective_actions`, `preventive_hardening`
  - `risk_forecast`, `deployment_correlation`, `error_log_prediction`
  - `missing_observability`, `policy_note`

## Incident Analysis Persistence

The service now stores structured incident snapshots in PostgreSQL table `incident_analysis`.

### Database initialization

1. Ensure PostgreSQL is reachable from `DATABASE_URL`.
2. Apply migration script:

```bash
psql "$DATABASE_URL" -f migrations/001_create_incident_analysis.sql
```

`create_app()` also runs `Base.metadata.create_all()` for safety at startup.

### Example JSON payload

```json
{
  "incident_id": "INC-803040",
  "service_name": "product-service",
  "anomaly_score": 0.18,
  "confidence_score": 0.62,
  "classification": "False Positive",
  "root_cause": "No correlated anomaly detected across metrics/logs/traces",
  "mitigation": {
    "actions": ["Restart Pod", "Inspect DB pool config"]
  },
  "risk_forecast": 0.04,
  "mitigation_success": null
}
```

### Example curl requests

```bash
curl -X POST "http://127.0.0.1:8080/incident-analysis" \
  -H "Content-Type: application/json" \
  -d '{
    "incident_id":"INC-803040",
    "service_name":"product-service",
    "anomaly_score":0.18,
    "confidence_score":0.62,
    "classification":"False Positive",
    "root_cause":"No correlated anomaly detected",
    "mitigation":{"actions":["Restart Pod"]},
    "risk_forecast":0.04,
    "mitigation_success":null
  }'

curl "http://127.0.0.1:8080/incident-analysis?start_date=2026-02-20&end_date=2026-02-23&service_name=product-service&limit=20&offset=0"

curl "http://127.0.0.1:8080/incident-analysis/summary?start_date=2026-02-20&end_date=2026-02-23"

curl -X PATCH "http://127.0.0.1:8080/incident-analysis/INC-803040/mitigation-result" \
  -H "Content-Type: application/json" \
  -d '{"mitigation_success":true}'
```

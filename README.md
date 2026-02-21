# AI Observer Agent

FastAPI webhook service for incident analysis.

## Run locally

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cd app
uvicorn main:app --host 0.0.0.0 --port 8080
```

## Environment variables

- `PROMETHEUS_URL` (default: `http://prometheus:9090`)
- `LOKI_URL` (default: `http://loki-gateway:80`)
- `JAEGER_URL` (default: `http://jaeger-query:16686`)
- `OLLAMA_URL` (default: `http://host.minikube.internal:11434`)
- `DEFAULT_NAMESPACE` (default: `dev`)
- `SLO_TARGET` (default: `0.995`)
- `OLLAMA_TIMEOUT_SECONDS` (default: `180`)
- `OLLAMA_ATTEMPTS` (default: `1`)
- `KNOWN_ERROR_SIGNATURES` (optional, comma-separated)

## Endpoints

- `GET /healthz`
- `POST /webhook/alertmanager`

## Response highlights

`POST /webhook/alertmanager` returns:
- `context`: metrics + traces + logs + kubernetes + deployment + slo + datasource_errors
- `analysis`:
  - `probable_root_cause`, `impact_level`, `recommended_remediation`, `confidence_score`
  - `causal_chain`, `corrective_actions`, `preventive_hardening`
  - `risk_forecast`, `deployment_correlation`, `error_log_prediction`
  - `missing_observability`, `policy_note`

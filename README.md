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

## Endpoints

- `GET /healthz`
- `POST /webhook/alertmanager`
- `GET /api/reasoning/live?namespace=dev&service=order-service&severity=warning`
- `GET /dashboard`

## Response highlights

`POST /webhook/alertmanager` returns:
- `context`: metrics + traces + logs + kubernetes + deployment + slo + datasource_errors
- `analysis`:
  - `probable_root_cause`, `impact_level`, `recommended_remediation`, `confidence_score`
  - `causal_chain`, `corrective_actions`, `preventive_hardening`
  - `risk_forecast`, `deployment_correlation`, `error_log_prediction`
  - `missing_observability`, `policy_note`

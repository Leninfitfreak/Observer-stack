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

## Endpoints

- `GET /healthz`
- `POST /webhook/alertmanager`
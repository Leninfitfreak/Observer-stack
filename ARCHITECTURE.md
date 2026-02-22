# Reusable AI Observer Architecture

## 1) Folder structure

```text
ai-observer-agent/
  app/
    main.py                       # compatibility entrypoint
    static/                       # dashboard assets
  src/
    ai_observer/
      api/
        app.py                    # FastAPI app factory
        routes/
          health.py
          reasoning.py
          schemas.py
      core/
        settings.py               # typed config loader
        di.py                     # dependency injection container
        logging.py
      domain/
        interfaces.py             # provider protocols
        models.py                 # request/response models
      infra/
        http_client.py            # shared retrying HTTP client
      providers/
        llm/
          factory.py              # provider switch by config
          ollama_cloud.py
          openai_provider.py
        metrics/
          prometheus_provider.py
        logs/
          loki_provider.py
        traces/
          jaeger_provider.py
      services/
        reasoning_service.py      # orchestration/use-case layer
```

## 2) Refactored sample modules
- `src/ai_observer/services/reasoning_service.py`
- `src/ai_observer/providers/metrics/prometheus_provider.py`
- `src/ai_observer/providers/logs/loki_provider.py`
- `src/ai_observer/providers/traces/jaeger_provider.py`

## 3) Dependency injection pattern example

```python
# src/ai_observer/core/di.py
http = HttpClient(timeout_seconds=settings.http.timeout_seconds, attempts=settings.http.attempts)
metrics = PrometheusMetricsProvider(settings.observability.prometheus_url, http)
logs = LokiLogsProvider(settings.observability.loki_url, http)
traces = JaegerTracesProvider(settings.observability.jaeger_url, http)
llm = create_llm_provider(settings.llm, http)
reasoning_service = ReasoningService(metrics, logs, traces, llm)
```

## 4) Config loader example

```python
# src/ai_observer/core/settings.py
settings = load_settings()
# Reads env vars only, no hardcoded credentials.
# LLM_PROVIDER determines implementation.
```

## 5) Provider abstraction example

```python
# src/ai_observer/domain/interfaces.py
class MetricsProvider(Protocol):
    def collect(self, namespace: str, service: str) -> dict[str, Any]: ...

class LlmProvider(Protocol):
    def analyze(self, payload: dict[str, Any]) -> dict[str, Any]: ...
```

## 6) Switch LLM provider via config

Set environment:

```bash
LLM_PROVIDER=ollama
OLLAMA_URL=https://ollama.com
OLLAMA_API_KEY=***
LLM_MODEL=gpt-oss:20b
```

or

```bash
LLM_PROVIDER=openai
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_API_KEY=***
LLM_MODEL=gpt-4o-mini
```

No code changes required: provider is selected in `src/ai_observer/providers/llm/factory.py`.

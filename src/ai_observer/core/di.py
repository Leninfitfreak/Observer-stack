from __future__ import annotations

from dataclasses import dataclass

from ai_observer.core.settings import AppSettings
from ai_observer.infra.http_client import HttpClient
from ai_observer.providers.llm.factory import create_llm_provider
from ai_observer.providers.cluster.kubernetes_provider import KubernetesWiringProvider
from ai_observer.providers.logs.loki_provider import LokiLogsProvider
from ai_observer.providers.metrics.prometheus_provider import PrometheusMetricsProvider
from ai_observer.providers.traces.jaeger_provider import JaegerTracesProvider
from ai_observer.services.reasoning_service import ReasoningService


@dataclass(frozen=True)
class Container:
    settings: AppSettings
    http: HttpClient
    reasoning_service: ReasoningService


def build_container(settings: AppSettings) -> Container:
    http = HttpClient(timeout_seconds=settings.http.timeout_seconds, attempts=settings.http.attempts)

    metrics = PrometheusMetricsProvider(base_url=settings.observability.prometheus_url, http=http)
    logs = LokiLogsProvider(base_url=settings.observability.loki_url, http=http)
    traces = JaegerTracesProvider(base_url=settings.observability.jaeger_url, http=http)
    llm = create_llm_provider(settings.llm, http=http)
    cluster_wiring = KubernetesWiringProvider()

    service = ReasoningService(
        metrics_provider=metrics,
        logs_provider=logs,
        traces_provider=traces,
        llm_provider=llm,
        cluster_wiring_provider=cluster_wiring,
    )
    return Container(settings=settings, http=http, reasoning_service=service)

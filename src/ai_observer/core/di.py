from __future__ import annotations

from dataclasses import dataclass

from ai_observer.backend.intelligence import DependencyEngine, DiscoveryEngine, ObservabilityRegistry
from ai_observer.backend.intelligence.discovery_engine import DiscoveryConfig
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
    observability_registry: ObservabilityRegistry
    dependency_engine: DependencyEngine


def build_container(settings: AppSettings) -> Container:
    http = HttpClient(timeout_seconds=settings.http.timeout_seconds, attempts=settings.http.attempts)

    discovery = DiscoveryEngine(
        DiscoveryConfig(
            enabled=settings.discovery.enabled,
            api_url=settings.discovery.k8s_api_url,
            verify_ssl=settings.discovery.verify_ssl,
            service_account_token_path=settings.discovery.service_account_token_path,
            service_account_ca_path=settings.discovery.service_account_ca_path,
            namespaces=settings.discovery.namespaces,
        )
    )
    registry = ObservabilityRegistry(discovery=discovery)
    resolved = registry.resolve(settings.observability)
    dependency_engine = DependencyEngine()

    metrics = PrometheusMetricsProvider(base_url=resolved.prometheus_url, http=http)
    logs = LokiLogsProvider(base_url=resolved.loki_url, http=http)
    traces = JaegerTracesProvider(base_url=resolved.jaeger_url, http=http)
    llm = create_llm_provider(settings.llm, http=http)
    cluster_wiring = KubernetesWiringProvider()

    service = ReasoningService(
        metrics_provider=metrics,
        logs_provider=logs,
        traces_provider=traces,
        llm_provider=llm,
        cluster_wiring_provider=cluster_wiring,
    )
    return Container(
        settings=settings,
        http=http,
        reasoning_service=service,
        observability_registry=registry,
        dependency_engine=dependency_engine,
    )

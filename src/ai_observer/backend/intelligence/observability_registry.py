from __future__ import annotations

from dataclasses import dataclass

from ai_observer.backend.intelligence.discovery_engine import DiscoveryEngine, DiscoveryResult
from ai_observer.core.settings import ObservabilitySettings


@dataclass(frozen=True)
class ObservabilityRegistryState:
    prometheus_url: str
    loki_url: str
    jaeger_url: str
    sources: dict[str, str]


class ObservabilityRegistry:
    def __init__(self, discovery: DiscoveryEngine):
        self.discovery = discovery
        self._state = ObservabilityRegistryState(
            prometheus_url="",
            loki_url="",
            jaeger_url="",
            sources={},
        )

    @property
    def state(self) -> ObservabilityRegistryState:
        return self._state

    def resolve(self, configured: ObservabilitySettings) -> ObservabilityRegistryState:
        discovered: DiscoveryResult = self.discovery.discover_observability_services()

        # Prefer explicit env configuration and only fill missing values from discovery.
        prometheus_url = (configured.prometheus_url or discovered.prometheus_url).strip()
        loki_url = (configured.loki_url or discovered.loki_url).strip()
        jaeger_url = (configured.jaeger_url or discovered.jaeger_url).strip()

        self._state = ObservabilityRegistryState(
            prometheus_url=prometheus_url,
            loki_url=loki_url,
            jaeger_url=jaeger_url,
            sources=discovered.sources or {},
        )
        return self._state

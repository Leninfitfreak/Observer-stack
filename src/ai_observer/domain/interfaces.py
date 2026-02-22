from __future__ import annotations

from typing import Any, Protocol


class MetricsProvider(Protocol):
    def collect(
        self,
        namespace: str,
        service: str,
        pod_names: list[str] | None = None,
        workloads: list[str] | None = None,
    ) -> dict[str, Any]: ...


class LogsProvider(Protocol):
    def collect(self, namespace: str, service: str, minutes: int, limit: int = 20) -> dict[str, Any]: ...


class TracesProvider(Protocol):
    def collect(self, service: str, lookback_minutes: int, limit: int = 5) -> dict[str, Any]: ...


class LlmProvider(Protocol):
    def analyze(self, payload: dict[str, Any]) -> dict[str, Any]: ...


class ClusterWiringProvider(Protocol):
    def collect(self, namespace: str) -> dict[str, Any]: ...

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import logging
import time
from typing import Any

import requests

from ai_observer.backend.intelligence.discovery_engine import DiscoveryEngine, DiscoveryResult
from ai_observer.core.settings import ObservabilitySettings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ObservabilityRegistryState:
    prometheus_url: str
    loki_url: str
    jaeger_url: str
    sources: dict[str, str]
    status: dict[str, str]
    checked_at: str
    last_success_at: dict[str, str]
    last_error: dict[str, str]


class ObservabilityRegistry:
    def __init__(
        self,
        discovery: DiscoveryEngine,
        refresh_interval_seconds: int = 60,
        validation_timeout_seconds: int = 3,
    ):
        self.discovery = discovery
        self.refresh_interval_seconds = max(10, int(refresh_interval_seconds))
        self.validation_timeout_seconds = max(1, int(validation_timeout_seconds))
        self._configured = ObservabilitySettings()
        self._last_refresh_ts = 0.0
        self._last_success_ts: dict[str, str] = {}
        self._state = ObservabilityRegistryState(
            prometheus_url="",
            loki_url="",
            jaeger_url="",
            sources={},
            status={"prometheus": "unknown", "loki": "unknown", "jaeger": "unknown"},
            checked_at="",
            last_success_at={},
            last_error={},
        )

    @property
    def state(self) -> ObservabilityRegistryState:
        return self._state

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()

    def _validate_prometheus(self, base_url: str) -> tuple[bool, str]:
        response = requests.get(
            f"{base_url.rstrip('/')}/api/v1/query",
            params={"query": "up"},
            timeout=self.validation_timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        if isinstance(payload, dict) and payload.get("status") == "success":
            return True, ""
        return False, "unexpected_payload"

    def _validate_loki(self, base_url: str) -> tuple[bool, str]:
        response = requests.get(
            f"{base_url.rstrip('/')}/loki/api/v1/status/buildinfo",
            timeout=self.validation_timeout_seconds,
        )
        response.raise_for_status()
        return True, ""

    def _validate_jaeger(self, base_url: str) -> tuple[bool, str]:
        response = requests.get(
            f"{base_url.rstrip('/')}/api/services",
            timeout=self.validation_timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        # Some deployments return {"data": [...]} and some return list directly.
        if isinstance(payload, dict):
            return (isinstance(payload.get("data"), list), "" if isinstance(payload.get("data"), list) else "unexpected_payload")
        if isinstance(payload, list):
            return True, ""
        return False, "unexpected_payload"

    def _validate_urls(self, prometheus_url: str, loki_url: str, jaeger_url: str) -> tuple[dict[str, str], dict[str, str]]:
        status: dict[str, str] = {}
        errors: dict[str, str] = {}
        validators = {
            "prometheus": (prometheus_url, self._validate_prometheus),
            "loki": (loki_url, self._validate_loki),
            "jaeger": (jaeger_url, self._validate_jaeger),
        }
        now = self._now_iso()
        for source, (url, validator) in validators.items():
            if not url:
                status[source] = "unavailable"
                errors[source] = "endpoint_not_configured_or_discovered"
                continue
            try:
                healthy, reason = validator(url)
                if healthy:
                    status[source] = "healthy"
                    self._last_success_ts[source] = now
                else:
                    status[source] = "degraded"
                    errors[source] = reason or "validation_failed"
            except requests.RequestException as exc:
                status[source] = "degraded"
                errors[source] = str(exc)
        return status, errors

    def _build_state(self, configured: ObservabilitySettings, discovered: DiscoveryResult) -> ObservabilityRegistryState:
        # Prefer explicit env configuration and only fill missing values from discovery.
        prometheus_url = (configured.prometheus_url or discovered.prometheus_url).strip()
        loki_url = (configured.loki_url or discovered.loki_url).strip()
        jaeger_url = (configured.jaeger_url or discovered.jaeger_url).strip()
        status, errors = self._validate_urls(prometheus_url, loki_url, jaeger_url)
        checked_at = self._now_iso()
        logger.info(
            "Observability discovery status prometheus=%s loki=%s jaeger=%s",
            status.get("prometheus", "unknown"),
            status.get("loki", "unknown"),
            status.get("jaeger", "unknown"),
        )
        return ObservabilityRegistryState(
            prometheus_url=prometheus_url,
            loki_url=loki_url,
            jaeger_url=jaeger_url,
            sources=discovered.sources or {},
            status=status,
            checked_at=checked_at,
            last_success_at=dict(self._last_success_ts),
            last_error=errors,
        )

    def resolve(self, configured: ObservabilitySettings) -> ObservabilityRegistryState:
        self._configured = configured
        discovered: DiscoveryResult = self.discovery.discover_observability_services()
        self._state = self._build_state(configured, discovered)
        self._last_refresh_ts = time.time()
        return self._state

    def refresh(self, force: bool = False) -> ObservabilityRegistryState:
        now_ts = time.time()
        if not force and (now_ts - self._last_refresh_ts) < self.refresh_interval_seconds:
            return self._state
        discovered: DiscoveryResult = self.discovery.discover_observability_services()
        self._state = self._build_state(self._configured, discovered)
        self._last_refresh_ts = now_ts
        return self._state

    def status_view(self) -> dict[str, Any]:
        return {
            "sources": self._state.sources,
            "status": self._state.status,
            "checked_at": self._state.checked_at,
            "last_success_at": self._state.last_success_at,
            "last_error": self._state.last_error,
            "endpoints": {
                "prometheus_url": self._state.prometheus_url,
                "loki_url": self._state.loki_url,
                "jaeger_url": self._state.jaeger_url,
            },
        }

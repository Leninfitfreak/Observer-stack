from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import requests


@dataclass(frozen=True)
class DiscoveryConfig:
    enabled: bool = True
    api_url: str = "https://kubernetes.default.svc"
    verify_ssl: bool = True
    service_account_token_path: str = "/var/run/secrets/kubernetes.io/serviceaccount/token"
    service_account_ca_path: str = "/var/run/secrets/kubernetes.io/serviceaccount/ca.crt"
    namespaces: tuple[str, ...] = ("dev",)


@dataclass(frozen=True)
class DiscoveryResult:
    prometheus_url: str = ""
    loki_url: str = ""
    jaeger_url: str = ""
    sources: dict[str, str] | None = None


class DiscoveryEngine:
    def __init__(self, config: DiscoveryConfig):
        self.config = config

    @staticmethod
    def _read_token(path: str) -> str:
        try:
            with open(path, "r", encoding="utf-8") as handle:
                return handle.read().strip()
        except OSError:
            return ""

    def _verify_setting(self) -> bool | str:
        if not self.config.verify_ssl:
            return False
        if os.path.exists(self.config.service_account_ca_path):
            return self.config.service_account_ca_path
        return True

    def _list_services(self, namespace: str) -> list[dict[str, Any]]:
        token = self._read_token(self.config.service_account_token_path)
        if not token:
            return []
        headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
        response = requests.get(
            f"{self.config.api_url.rstrip('/')}/api/v1/namespaces/{namespace}/services",
            headers=headers,
            verify=self._verify_setting(),
            timeout=5,
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            return []
        items = payload.get("items", [])
        return items if isinstance(items, list) else []

    @staticmethod
    def _service_port(service: dict[str, Any], default_port: int) -> int:
        ports = (((service.get("spec") or {}).get("ports")) or [])
        for port_item in ports:
            port_name = str(port_item.get("name", "")).lower()
            port_value = int(port_item.get("port", default_port) or default_port)
            if port_name in {"http", "http-metrics", "web", "query-frontend", "jaeger-ui"}:
                return port_value
        if ports:
            return int((ports[0].get("port", default_port) or default_port))
        return default_port

    @staticmethod
    def _service_url(name: str, namespace: str, port: int) -> str:
        return f"http://{name}.{namespace}.svc.cluster.local:{port}"

    def discover_observability_services(self) -> DiscoveryResult:
        if not self.config.enabled:
            return DiscoveryResult(sources={})

        discovered: dict[str, str] = {}
        for namespace in self.config.namespaces:
            try:
                services = self._list_services(namespace)
            except requests.RequestException:
                continue

            for service in services:
                metadata = service.get("metadata") or {}
                name = str(metadata.get("name", "")).strip()
                if not name:
                    continue
                lname = name.lower()
                if "prometheus" in lname and "prometheus_url" not in discovered:
                    discovered["prometheus_url"] = self._service_url(name, namespace, self._service_port(service, 9090))
                    discovered["prometheus_source"] = f"{namespace}/{name}"
                if "loki" in lname and "gateway" in lname and "loki_url" not in discovered:
                    discovered["loki_url"] = self._service_url(name, namespace, self._service_port(service, 3100))
                    discovered["loki_source"] = f"{namespace}/{name}"
                if "jaeger" in lname and "jaeger_url" not in discovered:
                    discovered["jaeger_url"] = self._service_url(name, namespace, self._service_port(service, 16686))
                    discovered["jaeger_source"] = f"{namespace}/{name}"

        return DiscoveryResult(
            prometheus_url=discovered.get("prometheus_url", ""),
            loki_url=discovered.get("loki_url", ""),
            jaeger_url=discovered.get("jaeger_url", ""),
            sources={
                "prometheus": discovered.get("prometheus_source", ""),
                "loki": discovered.get("loki_source", ""),
                "jaeger": discovered.get("jaeger_source", ""),
            },
        )

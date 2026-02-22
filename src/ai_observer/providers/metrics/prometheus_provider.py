from __future__ import annotations

from typing import Any
from urllib.parse import urlencode

from ai_observer.infra.http_client import HttpClient


class PrometheusMetricsProvider:
    def __init__(self, base_url: str, http: HttpClient):
        self.base_url = base_url.rstrip("/")
        self.http = http

    def _query_scalar(self, promql: str) -> float | None:
        query = urlencode({"query": promql})
        resp = self.http.request("GET", f"{self.base_url}/api/v1/query?{query}")
        rows = resp.json().get("data", {}).get("result", [])
        if not rows:
            return None
        try:
            return float(rows[0]["value"][1])
        except Exception:
            return None

    def _query_with_fallback(self, primary: str, fallback: str) -> float | None:
        value = self._query_scalar(primary)
        if value is not None:
            return value
        return self._query_scalar(fallback)

    def collect(self, namespace: str, service: str) -> dict[str, Any]:
        normalized_service = (service or "all").strip()
        use_service_scope = normalized_service not in {"all", "*"}
        pod_regex = f".*{normalized_service}.*"
        req_filter = f'namespace="{namespace}"'
        if use_service_scope:
            req_filter = f'namespace="{namespace}",pod=~"{pod_regex}"'
        pod_filter = f'namespace="{namespace}",pod=~"{pod_regex}"' if use_service_scope else f'namespace="{namespace}"'

        metrics = {
            "request_rate_rps_5m": self._query_with_fallback(
                f'sum(rate(http_server_requests_seconds_count{{{req_filter}}}[5m]))',
                f'sum(rate(http_server_requests_seconds_count{{namespace="{namespace}"}}[5m]))',
            ) or 0,
            "latency_p95_s_5m": self._query_with_fallback(
                f'histogram_quantile(0.95, sum(rate(http_server_requests_seconds_bucket{{{req_filter}}}[5m])) by (le))',
                f'histogram_quantile(0.95, sum(rate(http_server_requests_seconds_bucket{{namespace="{namespace}"}}[5m])) by (le))',
            ) or 0,
            "latency_p99_s_5m": self._query_with_fallback(
                f'histogram_quantile(0.99, sum(rate(http_server_requests_seconds_bucket{{{req_filter}}}[5m])) by (le))',
                f'histogram_quantile(0.99, sum(rate(http_server_requests_seconds_bucket{{namespace="{namespace}"}}[5m])) by (le))',
            ) or 0,
            "error_rate_5xx_5m": self._query_with_fallback(
                f'sum(rate(http_server_requests_seconds_count{{status=~"5..",{req_filter}}}[5m]))'
                f' / clamp_min(sum(rate(http_server_requests_seconds_count{{{req_filter}}}[5m])), 0.000001)',
                f'sum(rate(http_server_requests_seconds_count{{status=~"5..",namespace="{namespace}"}}[5m]))'
                f' / clamp_min(sum(rate(http_server_requests_seconds_count{{namespace="{namespace}"}}[5m])), 0.000001)',
            ) or 0,
            "cpu_usage_cores_5m": self._query_scalar(
                f'sum(rate(container_cpu_usage_seconds_total{{{pod_filter},container!="",container!="POD"}}[5m]))'
            ) or 0,
            "memory_usage_bytes": self._query_scalar(
                f'sum(container_memory_working_set_bytes{{{pod_filter},container!="",container!="POD"}})'
            ) or 0,
            "pod_restarts_10m": self._query_scalar(
                f'sum(increase(kube_pod_container_status_restarts_total{{{pod_filter}}}[10m]))'
            ) or 0,
        }

        anomalies: list[str] = []
        if metrics["error_rate_5xx_5m"] > 0.05:
            anomalies.append("sustained_5xx_rate_gt_5pct_over_5m")
        if metrics["latency_p95_s_5m"] > 0.75:
            anomalies.append("sustained_p95_latency_gt_750ms_over_5m")
        metrics["anomalies"] = anomalies
        return metrics

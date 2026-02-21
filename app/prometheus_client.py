from typing import Any
from urllib.parse import urlencode

from utils import request_with_retry


class PrometheusClient:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")

    def query(self, promql: str) -> list[dict[str, Any]]:
        query_string = urlencode({"query": promql})
        resp = request_with_retry("GET", f"{self.base_url}/api/v1/query?{query_string}")
        payload = resp.json()
        return payload.get("data", {}).get("result", [])

    def query_scalar(self, promql: str) -> float | None:
        result = self.query(promql)
        if not result:
            return None
        return float(result[0]["value"][1])

    def collect_metrics(self, namespace: str, service: str) -> dict[str, Any]:
        pod_regex = f".*{service}.*"
        metric_selector = f'namespace="{namespace}"'
        error_rate_q = (
            f'sum(rate(http_server_requests_seconds_count{{status=~"5..",{metric_selector}}}[5m]))'
            f' / clamp_min(sum(rate(http_server_requests_seconds_count{{{metric_selector}}}[5m])), 0.000001)'
        )
        p95_q = (
            f'histogram_quantile(0.95, sum(rate(http_server_requests_seconds_bucket'
            f'{{{metric_selector}}}[5m])) by (le))'
        )
        cpu_q = (
            "sum(rate(container_cpu_usage_seconds_total{"
            f'namespace="{namespace}",pod=~"{pod_regex}",container!="",container!="POD"'
            "}[5m]))"
        )
        mem_q = (
            "sum(container_memory_working_set_bytes{"
            f'namespace="{namespace}",pod=~"{pod_regex}",container!="",container!="POD"'
            "})"
        )

        return {
            "error_rate_5xx_5m": self.query_scalar(error_rate_q),
            "latency_p95_seconds_5m": self.query_scalar(p95_q),
            "cpu_usage_cores_5m": self.query_scalar(cpu_q),
            "memory_usage_bytes": self.query_scalar(mem_q),
        }

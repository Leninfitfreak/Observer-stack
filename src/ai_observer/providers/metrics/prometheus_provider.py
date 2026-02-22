from __future__ import annotations

from typing import Any
from urllib.parse import urlencode
import re

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

    @staticmethod
    def _regex_union(values: list[str]) -> str:
        escaped = [re.escape(v) for v in values if v]
        if not escaped:
            return ".*"
        return f"^({'|'.join(escaped)})$"

    @staticmethod
    def _derive_workload_from_pod(pod_name: str) -> str:
        parts = (pod_name or "").split("-")
        if len(parts) >= 3 and re.fullmatch(r"[a-f0-9]{8,}", parts[-2] or ""):
            return "-".join(parts[:-2])
        if len(parts) >= 2 and parts[-1].isdigit():
            return "-".join(parts[:-1])
        if len(parts) >= 2:
            return "-".join(parts[:-1])
        return pod_name or ""

    @staticmethod
    def _derive_job_candidates(service: str, pod_names: list[str]) -> list[str]:
        candidates: set[str] = set()
        svc = (service or "").strip()
        if svc:
            candidates.add(svc)
            if svc.startswith("leninkart-"):
                candidates.add(svc.replace("leninkart-", "", 1))
            if svc.startswith("dev-"):
                candidates.add(svc.replace("dev-", "", 1))
            if "order-service" in svc:
                candidates.add("order-service")
            if "product-service" in svc:
                candidates.add("product-service")
            if "frontend" in svc:
                candidates.add("frontend")
            if "ai-observer" in svc:
                candidates.add("ai-observer")

        for pod in pod_names:
            workload = PrometheusMetricsProvider._derive_workload_from_pod(pod)
            if workload:
                candidates.add(workload)
            if "order-service" in pod:
                candidates.add("order-service")
            if "product-service" in pod:
                candidates.add("product-service")
            if "frontend" in pod:
                candidates.add("frontend")
            if "ai-observer" in pod:
                candidates.add("ai-observer")
        return sorted(c for c in candidates if c and c not in {"all", "*"})

    def collect(
        self,
        namespace: str,
        service: str,
        pod_names: list[str] | None = None,
        workloads: list[str] | None = None,
    ) -> dict[str, Any]:
        normalized_service = (service or "all").strip()
        use_service_scope = normalized_service not in {"all", "*"}
        resolved_pods = [p for p in (pod_names or []) if p]
        pod_regex = self._regex_union(resolved_pods) if resolved_pods else f".*{normalized_service}.*"
        req_filter = f'namespace="{namespace}"'
        if use_service_scope:
            req_filter = f'namespace="{namespace}",pod=~"{pod_regex}"'
        pod_filter = f'namespace="{namespace}",pod=~"{pod_regex}"' if use_service_scope else f'namespace="{namespace}"'
        resolved_workloads = [w for w in (workloads or []) if w]
        if not resolved_workloads and resolved_pods:
            resolved_workloads = sorted({self._derive_workload_from_pod(p) for p in resolved_pods if self._derive_workload_from_pod(p)})
        workload_regex = self._regex_union(resolved_workloads) if resolved_workloads else f".*{normalized_service.replace('leninkart-', '')}.*"
        job_candidates = self._derive_job_candidates(normalized_service, resolved_pods)
        job_regex = self._regex_union(job_candidates)
        job_filter = f'namespace="{namespace}",job=~"{job_regex}"'
        job_filter_all = f'namespace="{namespace}"'

        metrics = {
            "request_rate_rps_5m": self._query_with_fallback(
                f'sum(rate(http_server_requests_seconds_count{{{job_filter}}}[5m]))',
                f'sum(rate(http_server_requests_seconds_count{{{req_filter}}}[5m]))',
            ) or 0,
            "latency_p95_s_5m": self._query_with_fallback(
                f'clamp_min(sum(rate(http_server_requests_seconds_sum{{{job_filter}}}[5m])) / clamp_min(sum(rate(http_server_requests_seconds_count{{{job_filter}}}[5m])), 0.000001), 0)',
                f'clamp_min(sum(rate(http_server_requests_seconds_sum{{{job_filter_all}}}[5m])) / clamp_min(sum(rate(http_server_requests_seconds_count{{{job_filter_all}}}[5m])), 0.000001), 0)',
            ) or 0,
            "latency_p99_s_5m": self._query_with_fallback(
                f'max(http_server_requests_seconds_max{{{job_filter}}})',
                f'max(http_server_requests_seconds_max{{{job_filter_all}}})',
            ) or 0,
            "error_rate_5xx_5m": self._query_with_fallback(
                f'sum(rate(http_server_requests_seconds_count{{status=~"5..",{job_filter}}}[5m]))'
                f' / clamp_min(sum(rate(http_server_requests_seconds_count{{{job_filter}}}[5m])), 0.000001)',
                f'sum(rate(http_server_requests_seconds_count{{status=~"5..",{req_filter}}}[5m]))'
                f' / clamp_min(sum(rate(http_server_requests_seconds_count{{{req_filter}}}[5m])), 0.000001)',
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

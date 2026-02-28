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

    def _query_first(self, *queries: str) -> float | None:
        for query in queries:
            if not query:
                continue
            value = self._query_scalar(query)
            if value is not None:
                return value
        return None

    def _query_baseline_stats(self, expressions: list[str], window: str) -> tuple[float | None, float | None]:
        for expr in expressions:
            if not expr:
                continue
            mean = self._query_scalar(f"avg_over_time(({expr})[{window}:1m])")
            if mean is None:
                continue
            stddev = self._query_scalar(f"stddev_over_time(({expr})[{window}:1m])")
            return mean, (stddev if stddev is not None else 0.0)
        return None, None

    @staticmethod
    def _safe_zscore(current: float, mean: float | None, stddev: float | None) -> float:
        if mean is None:
            return 0.0
        m = float(mean)
        s = abs(float(stddev or 0.0))
        # Guard against near-zero stddev for mostly-flat series.
        effective_std = max(s, abs(m) * 0.1, 1e-6)
        return (float(current) - m) / effective_std

    @staticmethod
    def _zscore_to_score(z: float) -> float:
        # |z|=3 maps to score=1.0
        return max(0.0, min(1.0, abs(float(z)) / 3.0))

    @staticmethod
    def _safe_ratio(num: float | None, den: float | None) -> float:
        n = float(num or 0)
        d = float(den or 0)
        if d <= 0:
            return 0.0
        return n / d

    @staticmethod
    def _regex_union(values: list[str]) -> str:
        # PromQL label regex uses RE2 string escaping; escaping '-' as '\-'
        # can produce parse errors. Keep literals simple and only escape
        # backslash and quote for safety.
        normalized = [
            str(v).replace("\\", "\\\\").replace('"', '\\"')
            for v in values
            if v
        ]
        if not normalized:
            return ".*"
        return f"^({'|'.join(normalized)})$"

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

        cpu_exprs = [
            f'sum(process_cpu_usage{{{job_filter}}})',
            f'sum(process_cpu_usage{{{req_filter}}})',
            f'sum(process_cpu_usage{{{job_filter_all}}})',
            f'sum(rate(container_cpu_usage_seconds_total{{{pod_filter},container!="",container!="POD"}}[5m]))',
            f'sum(rate(node_namespace_pod_container:container_cpu_usage_seconds_total:sum_irate{{{pod_filter}}}[5m]))',
        ]
        memory_exprs = [
            f'sum(jvm_memory_used_bytes{{{job_filter}}})',
            f'sum(jvm_memory_used_bytes{{{req_filter}}})',
            f'sum(jvm_memory_used_bytes{{{job_filter_all}}})',
            f'sum(container_memory_working_set_bytes{{{pod_filter},container!="",container!="POD"}})',
            f'sum(container_memory_usage_bytes{{{pod_filter},container!="",container!="POD"}})',
            f'sum(node_namespace_pod_container:container_memory_working_set_bytes{{{pod_filter}}})',
        ]
        request_rate_exprs = [
            f'sum(rate(http_server_requests_seconds_count{{{job_filter}}}[5m]))',
            f'sum(rate(http_server_requests_seconds_count{{{req_filter}}}[5m]))',
        ]
        error_rate_exprs = [
            f'sum(rate(http_server_requests_seconds_count{{status=~"5..",{job_filter}}}[5m]))'
            f' / clamp_min(sum(rate(http_server_requests_seconds_count{{{job_filter}}}[5m])), 0.000001)',
            f'sum(rate(http_server_requests_seconds_count{{status=~"5..",{req_filter}}}[5m]))'
            f' / clamp_min(sum(rate(http_server_requests_seconds_count{{{req_filter}}}[5m])), 0.000001)',
        ]
        restarts_exprs = [
            f'sum(increase(kube_pod_container_status_restarts_total{{{pod_filter}}}[10m]))',
            f'sum(increase(kube_pod_container_status_restarts_total{{namespace="{namespace}"}}[10m]))',
        ]

        cpu_usage = self._query_first(*cpu_exprs)
        memory_usage = self._query_first(*memory_exprs)
        db_pool_usage = self._query_first(
            f'sum(hikaricp_connections_active{{{job_filter}}}) / clamp_min(sum(hikaricp_connections_max{{{job_filter}}}), 1)',
            f'sum(hikaricp_connections_active{{{job_filter_all}}}) / clamp_min(sum(hikaricp_connections_max{{{job_filter_all}}}), 1)',
        )
        thread_pool_saturation = self._query_first(
            f'sum(jvm_threads_live_threads{{{job_filter}}}) / clamp_min(sum(jvm_threads_peak_threads{{{job_filter}}}), 1)',
            f'sum(jvm_threads_live_threads{{{job_filter_all}}}) / clamp_min(sum(jvm_threads_peak_threads{{{job_filter_all}}}), 1)',
        )
        kafka_lag = self._query_first(
            f'sum(kafka_consumergroup_lag{{{job_filter}}})',
            f'sum(kafka_consumergroup_lag{{{job_filter_all}}})',
        )
        baseline_p95_7d = self._query_first(
            f'avg_over_time((clamp_min(sum(rate(http_server_requests_seconds_sum{{{job_filter}}}[5m])) / clamp_min(sum(rate(http_server_requests_seconds_count{{{job_filter}}}[5m])), 0.000001), 0))[7d:5m])',
            f'avg_over_time((clamp_min(sum(rate(http_server_requests_seconds_sum{{{job_filter_all}}}[5m])) / clamp_min(sum(rate(http_server_requests_seconds_count{{{job_filter_all}}}[5m])), 0.000001), 0))[7d:5m])',
        )
        p95_yesterday = self._query_first(
            f'clamp_min(sum(rate(http_server_requests_seconds_sum{{{job_filter}}}[5m] offset 1d)) / clamp_min(sum(rate(http_server_requests_seconds_count{{{job_filter}}}[5m] offset 1d)), 0.000001), 0)',
            f'clamp_min(sum(rate(http_server_requests_seconds_sum{{{job_filter_all}}}[5m] offset 1d)) / clamp_min(sum(rate(http_server_requests_seconds_count{{{job_filter_all}}}[5m] offset 1d)), 0.000001), 0)',
        )
        error_rate_prev_5m = self._query_first(
            f'sum(rate(http_server_requests_seconds_count{{status=~"5..",{job_filter}}}[5m] offset 5m)) / clamp_min(sum(rate(http_server_requests_seconds_count{{{job_filter}}}[5m] offset 5m)), 0.000001)',
            f'sum(rate(http_server_requests_seconds_count{{status=~"5..",{req_filter}}}[5m] offset 5m)) / clamp_min(sum(rate(http_server_requests_seconds_count{{{req_filter}}}[5m] offset 5m)), 0.000001)',
        )

        request_rate = self._query_first(*request_rate_exprs) or 0
        error_rate = self._query_first(*error_rate_exprs) or 0
        pod_restarts = self._query_first(*restarts_exprs) or 0

        metrics = {
            "request_rate_rps_5m": request_rate,
            "latency_p95_s_5m": self._query_with_fallback(
                f'clamp_min(sum(rate(http_server_requests_seconds_sum{{{job_filter}}}[5m])) / clamp_min(sum(rate(http_server_requests_seconds_count{{{job_filter}}}[5m])), 0.000001), 0)',
                f'clamp_min(sum(rate(http_server_requests_seconds_sum{{{job_filter_all}}}[5m])) / clamp_min(sum(rate(http_server_requests_seconds_count{{{job_filter_all}}}[5m])), 0.000001), 0)',
            ) or 0,
            "latency_p99_s_5m": self._query_with_fallback(
                f'max(http_server_requests_seconds_max{{{job_filter}}})',
                f'max(http_server_requests_seconds_max{{{job_filter_all}}})',
            ) or 0,
            "error_rate_5xx_5m": error_rate,
            "cpu_usage_cores_5m": cpu_usage or 0,
            "memory_usage_bytes": memory_usage or 0,
            "db_connection_pool_usage_5m": db_pool_usage or 0,
            "thread_pool_saturation_5m": thread_pool_saturation or 0,
            "kafka_consumer_lag": kafka_lag or 0,
            "baseline_p95_s_7d": baseline_p95_7d or 0,
            "p95_yesterday_s_5m": p95_yesterday or 0,
            "error_rate_prev_5m": error_rate_prev_5m or 0,
            "pod_restarts_10m": pod_restarts,
        }

        baseline_windows = {"5m": "5m", "30m": "30m", "1h": "1h"}
        for suffix, window in baseline_windows.items():
            cpu_mean, cpu_std = self._query_baseline_stats(cpu_exprs, window)
            mem_mean, mem_std = self._query_baseline_stats(memory_exprs, window)
            rps_mean, rps_std = self._query_baseline_stats(request_rate_exprs, window)
            err_mean, err_std = self._query_baseline_stats(error_rate_exprs, window)
            restart_mean, restart_std = self._query_baseline_stats(restarts_exprs, window)

            metrics[f"cpu_baseline_mean_{suffix}"] = cpu_mean or 0.0
            metrics[f"cpu_baseline_stddev_{suffix}"] = cpu_std or 0.0
            metrics[f"memory_baseline_mean_{suffix}"] = mem_mean or 0.0
            metrics[f"memory_baseline_stddev_{suffix}"] = mem_std or 0.0
            metrics[f"request_rate_baseline_mean_{suffix}"] = rps_mean or 0.0
            metrics[f"request_rate_baseline_stddev_{suffix}"] = rps_std or 0.0
            metrics[f"error_rate_baseline_mean_{suffix}"] = err_mean or 0.0
            metrics[f"error_rate_baseline_stddev_{suffix}"] = err_std or 0.0
            metrics[f"pod_restarts_baseline_mean_{suffix}"] = restart_mean or 0.0
            metrics[f"pod_restarts_baseline_stddev_{suffix}"] = restart_std or 0.0

            cpu_z = self._safe_zscore(metrics["cpu_usage_cores_5m"], cpu_mean, cpu_std)
            mem_z = self._safe_zscore(metrics["memory_usage_bytes"], mem_mean, mem_std)
            rps_z = self._safe_zscore(metrics["request_rate_rps_5m"], rps_mean, rps_std)
            err_z = self._safe_zscore(metrics["error_rate_5xx_5m"], err_mean, err_std)
            restart_z = self._safe_zscore(metrics["pod_restarts_10m"], restart_mean, restart_std)

            metrics[f"cpu_baseline_zscore_{suffix}"] = cpu_z
            metrics[f"memory_baseline_zscore_{suffix}"] = mem_z
            metrics[f"request_rate_baseline_zscore_{suffix}"] = rps_z
            metrics[f"error_rate_baseline_zscore_{suffix}"] = err_z
            metrics[f"pod_restarts_baseline_zscore_{suffix}"] = restart_z

            metrics[f"cpu_baseline_anomaly_{suffix}"] = self._zscore_to_score(cpu_z)
            metrics[f"memory_baseline_anomaly_{suffix}"] = self._zscore_to_score(mem_z)
            metrics[f"request_rate_baseline_anomaly_{suffix}"] = self._zscore_to_score(rps_z)
            metrics[f"error_rate_baseline_anomaly_{suffix}"] = self._zscore_to_score(err_z)
            metrics[f"pod_restarts_baseline_anomaly_{suffix}"] = self._zscore_to_score(restart_z)

        # Primary baseline window for downstream reasoning.
        primary_suffix = "30m"
        metric_scores = [
            float(metrics.get(f"cpu_baseline_anomaly_{primary_suffix}", 0) or 0),
            float(metrics.get(f"memory_baseline_anomaly_{primary_suffix}", 0) or 0),
            float(metrics.get(f"request_rate_baseline_anomaly_{primary_suffix}", 0) or 0),
            float(metrics.get(f"error_rate_baseline_anomaly_{primary_suffix}", 0) or 0),
            float(metrics.get(f"pod_restarts_baseline_anomaly_{primary_suffix}", 0) or 0),
        ]
        weights = [0.25, 0.2, 0.2, 0.25, 0.1]
        weighted_sum = sum(score * weight for score, weight in zip(metric_scores, weights))
        metrics["baseline_window_used"] = primary_suffix
        metrics["baseline_anomaly_score"] = max(0.0, min(1.0, weighted_sum))

        base_p95 = metrics.get("baseline_p95_s_7d", 0) or 0
        cur_p95 = metrics.get("latency_p95_s_5m", 0) or 0
        prev_err = metrics.get("error_rate_prev_5m", 0) or 0
        cur_err = metrics.get("error_rate_5xx_5m", 0) or 0
        metrics["latency_deviation_7d_pct"] = (
            ((cur_p95 - base_p95) / base_p95) * 100 if base_p95 > 0 else 0
        )
        metrics["error_growth_rate"] = cur_err - prev_err

        anomalies: list[str] = []
        if metrics["error_rate_5xx_5m"] > 0.05:
            anomalies.append("sustained_5xx_rate_gt_5pct_over_5m")
        if metrics["latency_p95_s_5m"] > 0.75:
            anomalies.append("sustained_p95_latency_gt_750ms_over_5m")
        if float(metrics.get("baseline_anomaly_score", 0) or 0) >= 0.65:
            anomalies.append("baseline_deviation_zscore_high")
        metrics["anomalies"] = anomalies
        return metrics

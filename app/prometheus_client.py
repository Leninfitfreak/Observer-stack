from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlencode

from utils import clean_float, request_with_retry


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
        return clean_float(result[0]["value"][1])

    def discover_services(self, namespace: str) -> list[str]:
        queries = [
            f'sum(kube_deployment_status_replicas{{namespace="{namespace}"}}) by (deployment)',
            f'sum(kube_pod_container_status_ready{{namespace="{namespace}"}}) by (pod)',
        ]
        names: set[str] = set()
        for q in queries:
            try:
                rows = self.query(q)
            except Exception:
                continue
            for row in rows:
                metric = row.get("metric", {})
                dep = metric.get("deployment")
                if dep:
                    names.add(dep)
                    continue
                pod = metric.get("pod", "")
                if pod:
                    parts = pod.split("-")
                    if len(parts) >= 3:
                        names.add("-".join(parts[:-2]))

        filtered = []
        for name in sorted(names):
            if name.startswith(("ai-observer", "prometheus", "grafana", "loki", "jaeger", "alertmanager")):
                continue
            filtered.append(name)
        return filtered

    def _baseline_deviation(self, current_q: str, baseline_q: str) -> float | None:
        current = self.query_scalar(current_q)
        baseline = self.query_scalar(baseline_q)
        if current is None or baseline is None or baseline == 0:
            return None
        return (current - baseline) / baseline

    def collect_service_metrics(self, namespace: str, service: str) -> dict[str, Any]:
        pod_regex = f".*{service}.*"
        req_filter = f'namespace="{namespace}"'
        pod_filter = f'namespace="{namespace}",pod=~"{pod_regex}"'

        req_rate_q = f'sum(rate(http_server_requests_seconds_count{{{req_filter}}}[5m]))'
        p50_q = (
            f'histogram_quantile(0.50, sum(rate(http_server_requests_seconds_bucket'
            f'{{{req_filter}}}[5m])) by (le))'
        )
        p95_q = (
            f'histogram_quantile(0.95, sum(rate(http_server_requests_seconds_bucket'
            f'{{{req_filter}}}[5m])) by (le))'
        )
        p99_q = (
            f'histogram_quantile(0.99, sum(rate(http_server_requests_seconds_bucket'
            f'{{{req_filter}}}[5m])) by (le))'
        )
        error_4xx_q = (
            f'sum(rate(http_server_requests_seconds_count{{status=~"4..",{req_filter}}}[5m]))'
            f' / clamp_min(sum(rate(http_server_requests_seconds_count{{{req_filter}}}[5m])), 0.000001)'
        )
        error_5xx_q = (
            f'sum(rate(http_server_requests_seconds_count{{status=~"5..",{req_filter}}}[5m]))'
            f' / clamp_min(sum(rate(http_server_requests_seconds_count{{{req_filter}}}[5m])), 0.000001)'
        )
        cpu_q = (
            "sum(rate(container_cpu_usage_seconds_total{"
            f'{pod_filter},container!="",container!="POD"'
            "}[5m]))"
        )
        mem_q = (
            "sum(container_memory_working_set_bytes{"
            f'{pod_filter},container!="",container!="POD"'
            "})"
        )
        thread_pool_q = (
            f'sum(max_over_time(jvm_threads_live_threads{{{req_filter}}}[5m]))'
            f' / clamp_min(sum(max_over_time(jvm_threads_peak_threads{{{req_filter}}}[5m])), 1)'
            f' or aiobserver:thread_pool_saturation_5m'
        )
        db_pool_q = (
            f'sum(max_over_time(hikaricp_connections_active{{{req_filter}}}[5m]))'
            f' / clamp_min(sum(max_over_time(hikaricp_connections_max{{{req_filter}}}[5m])), 1)'
            f' or aiobserver:db_connection_pool_usage_5m'
        )
        kafka_lag_q = (
            f'sum(kafka_consumergroup_lag{{namespace="{namespace}"}})'
            f' or aiobserver:kafka_consumer_lag{{namespace="{namespace}"}}'
        )

        req_dev = self._baseline_deviation(
            req_rate_q,
            f'avg_over_time(sum(rate(http_server_requests_seconds_count{{{req_filter}}}[5m]))[7d:5m])',
        )
        p95_dev = self._baseline_deviation(
            p95_q,
            (
                f'avg_over_time(histogram_quantile(0.95, sum(rate(http_server_requests_seconds_bucket'
                f'{{{req_filter}}}[5m])) by (le))[7d:5m])'
            ),
        )
        err5_dev = self._baseline_deviation(
            error_5xx_q,
            (
                f'avg_over_time((sum(rate(http_server_requests_seconds_count{{status=~"5..",{req_filter}}}[5m]))'
                f' / clamp_min(sum(rate(http_server_requests_seconds_count{{{req_filter}}}[5m])), 0.000001))[7d:5m])'
            ),
        )

        metrics = {
            "request_rate_rps_5m": self.query_scalar(req_rate_q),
            "latency_p50_s_5m": self.query_scalar(p50_q),
            "latency_p95_s_5m": self.query_scalar(p95_q),
            "latency_p99_s_5m": self.query_scalar(p99_q),
            "error_rate_4xx_5m": self.query_scalar(error_4xx_q),
            "error_rate_5xx_5m": self.query_scalar(error_5xx_q),
            "cpu_usage_cores_5m": self.query_scalar(cpu_q),
            "memory_usage_bytes": self.query_scalar(mem_q),
            "thread_pool_saturation_5m": self.query_scalar(thread_pool_q),
            "db_connection_pool_usage_5m": self.query_scalar(db_pool_q),
            "kafka_consumer_lag": self.query_scalar(kafka_lag_q),
            "deviation_vs_7d_baseline": {
                "request_rate": req_dev,
                "latency_p95": p95_dev,
                "error_rate_5xx": err5_dev,
            },
        }

        anomalies: list[str] = []
        if (metrics.get("error_rate_5xx_5m") or 0) > 0.05:
            anomalies.append("sustained_5xx_rate_gt_5pct_over_5m")
        if (metrics.get("latency_p95_s_5m") or 0) > 0.75:
            anomalies.append("sustained_p95_latency_gt_750ms_over_5m")
        if (metrics.get("thread_pool_saturation_5m") or 0) > 0.8:
            anomalies.append("thread_pool_saturation_high")
        if (metrics.get("db_connection_pool_usage_5m") or 0) > 0.8:
            anomalies.append("db_connection_pool_high")
        if (metrics.get("kafka_consumer_lag") or 0) > 1000:
            anomalies.append("kafka_consumer_lag_high")
        metrics["anomalies"] = anomalies
        return metrics

    def collect_kubernetes_signals(self, namespace: str, service: str) -> dict[str, Any]:
        pod_regex = f".*{service}.*"
        restarts_q = (
            "sum(increase(kube_pod_container_status_restarts_total{"
            f'namespace="{namespace}",pod=~"{pod_regex}"'
            "}[10m]))"
        )
        crashloop_q = (
            "sum(kube_pod_container_status_waiting_reason{"
            f'namespace="{namespace}",pod=~"{pod_regex}",reason="CrashLoopBackOff"'
            "})"
        )
        oom_q = (
            "sum(increase(kube_pod_container_status_last_terminated_reason{"
            f'namespace="{namespace}",pod=~"{pod_regex}",reason="OOMKilled"'
            "}[10m]))"
        )
        throttle_q = (
            "sum(rate(container_cpu_cfs_throttled_seconds_total{"
            f'namespace="{namespace}",pod=~"{pod_regex}",container!="",container!="POD"'
            "}[5m]))"
        )
        hpa_changes_q = f'changes(kube_horizontalpodautoscaler_status_current_replicas{{namespace="{namespace}"}}[10m])'
        pvc_pressure_q = (
            f'min(100 * (1 - (kubelet_volume_stats_available_bytes{{namespace="{namespace}"}}'
            f' / clamp_min(kubelet_volume_stats_capacity_bytes{{namespace="{namespace}"}},1))))'
        )
        node_pressure_q = 'sum(kube_node_status_condition{condition=~"MemoryPressure|DiskPressure|PIDPressure",status="true"})'

        signals = {
            "pod_restarts_10m": self.query_scalar(restarts_q),
            "crashloop_pods": self.query_scalar(crashloop_q),
            "oom_killed_10m": self.query_scalar(oom_q),
            "cpu_throttled_rate_5m": self.query_scalar(throttle_q),
            "hpa_scaling_events_10m": self.query_scalar(hpa_changes_q),
            "pvc_usage_percent_max": self.query_scalar(pvc_pressure_q),
            "node_pressure_count": self.query_scalar(node_pressure_q),
        }
        return signals

    def collect_deployment_signals(self, namespace: str, service: str) -> dict[str, Any]:
        deploy_regex = f".*{service}.*"
        generation_changes_q = (
            f'sum(changes(kube_deployment_status_observed_generation{{namespace="{namespace}",deployment=~"{deploy_regex}"}}[10m]))'
        )
        updated_replicas_changes_q = (
            f'sum(changes(kube_deployment_status_replicas_updated{{namespace="{namespace}",deployment=~"{deploy_regex}"}}[10m]))'
        )
        created_ts_q = f'max(kube_deployment_created{{namespace="{namespace}",deployment=~"{deploy_regex}"}})'
        ai_observer_changes_q = (
            f'sum(changes(kube_deployment_status_observed_generation{{namespace="{namespace}",deployment="ai-observer"}}[15m]))'
        )
        ai_observer_updated_q = (
            f'sum(changes(kube_deployment_status_replicas_updated{{namespace="{namespace}",deployment="ai-observer"}}[15m]))'
        )

        created_ts = self.query_scalar(created_ts_q)
        created_iso = None
        if created_ts:
            created_iso = datetime.fromtimestamp(created_ts, tz=timezone.utc).isoformat()

        recent_deploy = ((self.query_scalar(generation_changes_q) or 0) > 0) or (
            (self.query_scalar(updated_replicas_changes_q) or 0) > 0
        )
        ai_observer_changed = ((self.query_scalar(ai_observer_changes_q) or 0) > 0) or (
            (self.query_scalar(ai_observer_updated_q) or 0) > 0
        )

        return {
            "deployment_changed_last_10m": recent_deploy,
            "deployment_generation_changes_10m": self.query_scalar(generation_changes_q),
            "updated_replicas_changes_10m": self.query_scalar(updated_replicas_changes_q),
            "ai_observer_frontend_changed_last_15m": ai_observer_changed,
            "deployment_created_at": created_iso,
            "argocd_deployment_history": "unavailable_via_current_datasources",
            "cicd_pipeline_signals": "unavailable_via_current_datasources",
        }

    def collect_slo_error_budget(
        self,
        namespace: str,
        error_rate_5xx: float | None,
        slo_target: float,
    ) -> dict[str, Any]:
        req_filter = f'namespace="{namespace}"'
        availability = None if error_rate_5xx is None else max(0.0, 1 - error_rate_5xx)
        burn_rate_1h_q = (
            f'(sum(rate(http_server_requests_seconds_count{{status=~"5..",{req_filter}}}[1h]))'
            f' / clamp_min(sum(rate(http_server_requests_seconds_count{{{req_filter}}}[1h])), 0.000001))'
            f' / {max(0.000001, 1 - slo_target)}'
        )
        burn_rate_24h_q = (
            f'(sum(rate(http_server_requests_seconds_count{{status=~"5..",{req_filter}}}[24h]))'
            f' / clamp_min(sum(rate(http_server_requests_seconds_count{{{req_filter}}}[24h])), 0.000001))'
            f' / {max(0.000001, 1 - slo_target)}'
        )
        burn_1h = self.query_scalar(burn_rate_1h_q)
        burn_24h = self.query_scalar(burn_rate_24h_q)

        predicted = "low_risk"
        if (burn_1h or 0) > 14:
            predicted = "likely_breach_within_1h"
        elif (burn_24h or 0) > 2:
            predicted = "likely_breach_within_24h"

        return {
            "availability_pct": None if availability is None else round(availability * 100, 4),
            "slo_target_pct": round(slo_target * 100, 4),
            "error_budget_burn_rate_1h": burn_1h,
            "error_budget_burn_rate_24h": burn_24h,
            "predicted_breach_window": predicted,
        }

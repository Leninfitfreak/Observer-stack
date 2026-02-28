from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any

import requests

log = logging.getLogger(__name__)

def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def _float(value: str, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _int(value: str, default: int) -> int:
    try:
        parsed = int(value)
        return parsed if parsed > 0 else default
    except (TypeError, ValueError):
        return default


def _clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def _query_prometheus_value(prom_url: str, query: str, metric_name: str) -> tuple[float, bool]:
    if not prom_url:
        log.warning("Prometheus URL missing; metric=%s defaults to 0", metric_name)
        return 0.0, False
    try:
        response = requests.get(
            f"{prom_url.rstrip('/')}/api/v1/query",
            params={"query": query},
            timeout=5,
        )
        response.raise_for_status()
        payload = response.json()
        data = payload.get("data", {})
        results = data.get("result", [])
        if not results:
            log.warning("Prometheus returned empty result for metric=%s query=%s", metric_name, query)
            return 0.0, False
        values: list[float] = []
        for row in results:
            sample = row.get("value")
            if not isinstance(sample, list) or len(sample) < 2:
                continue
            try:
                values.append(float(sample[1]))
            except (TypeError, ValueError):
                continue
        if not values:
            log.warning("Prometheus samples could not be parsed for metric=%s query=%s", metric_name, query)
            return 0.0, False
        return float(sum(values)), True
    except (requests.RequestException, ValueError, TypeError) as exc:
        log.warning("Prometheus query failed for metric=%s query=%s err=%s", metric_name, query, exc)
        return 0.0, False


def _query_metric_with_fallback(prom_url: str, metric_name: str, primary_query: str, fallback_queries: list[str]) -> float:
    value, has_data = _query_prometheus_value(prom_url, primary_query, metric_name)
    if has_data:
        return value
    for fallback in fallback_queries:
        fb_value, fb_has_data = _query_prometheus_value(prom_url, fallback, metric_name)
        if fb_has_data:
            log.info("Using fallback query for metric=%s query=%s", metric_name, fallback)
            return fb_value
    return 0.0


def _classification_from_metrics(cpu_usage: float, error_rate: float) -> tuple[str, str]:
    if error_rate > 0.05:
        return "Error Spike", "error_rate_threshold_breached"
    if cpu_usage > 0.8:
        return "CPU Saturation", "cpu_usage_threshold_breached"
    return "Healthy", "metrics_within_expected_range"


def build_payload(cluster_id: str, environment: str, prom_url: str) -> dict[str, Any]:
    now_dt = datetime.now(timezone.utc)
    now = now_dt.strftime("%Y%m%d%H%M%S")
    timestamp = now_dt.isoformat()
    service_name = _env("AGENT_SERVICE_NAME", "observer-agent")
    cpu_usage = _query_metric_with_fallback(
        prom_url,
        "cpu_usage",
        'sum(rate(container_cpu_usage_seconds_total{container!="",pod!=""}[2m]))',
        ["avg(process_cpu_usage)", "sum(rate(process_cpu_time_ns_total[2m])) / 1e9"],
    )
    memory_usage = _query_metric_with_fallback(
        prom_url,
        "memory_usage",
        'sum(container_memory_working_set_bytes{container!="",pod!=""})',
        ["sum(jvm_memory_used_bytes)"],
    )
    pod_restarts = _query_metric_with_fallback(
        prom_url,
        "pod_restarts",
        "sum(kube_pod_container_status_restarts_total)",
        ["sum(kube_pod_container_status_restarts)", "sum(resets(process_uptime_seconds[30m]))"],
    )
    request_rate = _query_metric_with_fallback(
        prom_url,
        "request_rate",
        "sum(rate(http_server_requests_seconds_count[2m]))",
        ["sum(rate(http_requests_total[2m]))"],
    )
    error_rate = 0.0
    log.info(
        "Collected metrics: cpu=%s memory=%s restarts=%s rps=%s",
        cpu_usage,
        memory_usage,
        pod_restarts,
        request_rate,
    )
    classification, root_cause = _classification_from_metrics(cpu_usage=cpu_usage, error_rate=error_rate)

    anomaly_score = _clamp((cpu_usage + (error_rate * 4.0)) / 2.0, 0.0, 1.0)
    risk_forecast = _clamp((cpu_usage * 0.6) + (error_rate * 0.4), 0.0, 1.0)
    confidence_score = 0.95 if prom_url else 0.6

    return {
        "cluster_id": cluster_id,
        "environment": environment,
        "timestamp": timestamp,
        "metrics": {
            "cpu_usage": cpu_usage,
            "memory_usage": memory_usage,
            "pod_restarts": pod_restarts,
            "request_rate": request_rate,
            "error_rate": error_rate,
        },
        "incidents": [
            {
                "incident_id": f"agent-{cluster_id}-{service_name}-{now}",
                "service_name": service_name,
                "anomaly_score": anomaly_score,
                "confidence_score": confidence_score,
                "classification": classification,
                "root_cause": root_cause,
                "mitigation": {"action": "verify_observability_path"},
                "risk_forecast": risk_forecast,
                "mitigation_success": None,
            }
        ],
    }


def run() -> int:
    logging.basicConfig(
        level=_env("LOG_LEVEL", "INFO").upper(),
        format="%(asctime)s %(levelname)s %(message)s",
    )

    cluster_id = _env("CLUSTER_ID")
    central_url = _env("CENTRAL_URL")
    agent_token = _env("AGENT_TOKEN")
    prom_url = _env("PROM_URL")
    environment = _env("ENVIRONMENT", "dev")
    push_interval = _int(_env("PUSH_INTERVAL", "30"), 30)
    run_once = _env("RUN_ONCE", "false").lower() in {"1", "true", "yes", "on"}

    if not cluster_id or not central_url or not agent_token:
        logging.error("Missing required env vars: CLUSTER_ID, CENTRAL_URL, AGENT_TOKEN")
        return 1

    headers = {
        "Content-Type": "application/json",
        "X-Agent-Token": agent_token,
    }

    while True:
        payload = build_payload(cluster_id, environment, prom_url)
        try:
            response = requests.post(
                central_url,
                headers=headers,
                data=json.dumps(payload),
                timeout=10,
            )
            if response.ok:
                logging.info(
                    "push_success cluster=%s status=%s metrics=%s",
                    cluster_id,
                    response.status_code,
                    payload.get("metrics"),
                )
            else:
                logging.warning(
                    "push_failed cluster=%s status=%s body=%s",
                    cluster_id,
                    response.status_code,
                    response.text[:500],
                )
        except requests.RequestException as exc:
            logging.exception("push_error cluster=%s err=%s", cluster_id, exc)

        if run_once:
            return 0
        time.sleep(push_interval)


if __name__ == "__main__":
    raise SystemExit(run())

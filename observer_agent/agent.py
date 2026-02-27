from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any

import requests


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


def build_payload(cluster_id: str, environment: str, prom_url: str) -> dict[str, Any]:
    now = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    service_name = _env("AGENT_SERVICE_NAME", "observer-agent")
    anomaly_score = _float(_env("AGENT_ANOMALY_SCORE", "0.1"), 0.1)
    confidence_score = _float(_env("AGENT_CONFIDENCE_SCORE", "0.9"), 0.9)
    risk_forecast = _float(_env("AGENT_RISK_FORECAST", "0.2"), 0.2)

    root_cause = "prometheus_unreachable"
    classification = "Observability Gap"
    if prom_url:
        try:
            query = "up"
            response = requests.get(
                f"{prom_url.rstrip('/')}/api/v1/query",
                params={"query": query},
                timeout=5,
            )
            if response.ok:
                root_cause = "telemetry_heartbeat"
                classification = "Healthy"
            else:
                root_cause = f"prometheus_http_{response.status_code}"
        except requests.RequestException:
            root_cause = "prometheus_request_error"

    return {
        "cluster_id": cluster_id,
        "environment": environment,
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
                logging.info("push_success cluster=%s status=%s", cluster_id, response.status_code)
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

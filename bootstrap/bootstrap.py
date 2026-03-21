#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any


BOOTSTRAP_DIR = Path(__file__).resolve().parent
OBSERVER_STACK_DIR = BOOTSTRAP_DIR.parent
WORKSPACE_ROOT = OBSERVER_STACK_DIR.parent
VARIABLES_PATH = BOOTSTRAP_DIR / "variables.env"
CHANNELS_PATH = BOOTSTRAP_DIR / "channels.yaml"
DASHBOARDS_PATH = BOOTSTRAP_DIR / "dashboards.yaml"
ALERTS_PATH = BOOTSTRAP_DIR / "alerts.yaml"
SUMMARY_PATH = BOOTSTRAP_DIR / "last-run-summary.json"
ROOT_ENV_PATH = WORKSPACE_ROOT / ".env"


def load_env_file(path: Path) -> dict[str, str]:
    data: dict[str, str] = {}
    if not path.exists():
        return data
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        data[key.strip()] = value.strip()
    return data


def load_json_document(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def parse_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def parse_csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def resolve_config() -> dict[str, str]:
    config = load_env_file(VARIABLES_PATH)
    root_env = load_env_file(ROOT_ENV_PATH)
    for key, value in root_env.items():
        config.setdefault(key, value)
    for key, value in os.environ.items():
        if value != "":
            config[key] = value
    return config


def run_command(args: list[str], *, suppress_stderr: bool = False) -> str:
    completed = subprocess.run(
        args,
        cwd=str(WORKSPACE_ROOT),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL if suppress_stderr else subprocess.PIPE,
        check=True,
    )
    return completed.stdout or ""


def fetch_vault_signoz_api_key(config: dict[str, str]) -> str | None:
    namespace = config.get("VAULT_NAMESPACE", "vault")
    pod = config.get("VAULT_POD_NAME", "vault-0")
    secret_path = config.get("VAULT_SIGNOZ_SECRET_PATH", "secret/leninkart/observability")
    secret_field = config.get("VAULT_SIGNOZ_SECRET_FIELD", "signoz_api_key")

    bootstrap_json = run_command(
        ["kubectl", "exec", "-n", namespace, pod, "--", "cat", "/vault/data/bootstrap-keys.json"]
    )
    match = re.search(r'"root_token":"([^"]+)"', "".join(bootstrap_json.split()))
    if not match:
        return None

    root_token = match.group(1)
    script = (
        "export VAULT_ADDR=http://127.0.0.1:8200\n"
        f"export VAULT_TOKEN='{root_token}'\n"
        f"vault kv get -field={secret_field} {secret_path} 2>/dev/null || true\n"
    )
    value = run_command(
        ["kubectl", "exec", "-n", namespace, pod, "--", "sh", "-lc", script],
        suppress_stderr=True,
    ).strip()
    return value or None


def resolve_signoz_api_key(config: dict[str, str]) -> str:
    for candidate_key in ("SIGNOZ_API_KEY", "signoz_api_key"):
        candidate = config.get(candidate_key, "").strip()
        if candidate:
            return candidate
    if parse_bool(config.get("VAULT_ENABLED", "true"), default=True):
        candidate = fetch_vault_signoz_api_key(config)
        if candidate:
            return candidate
    raise RuntimeError("Could not resolve a SigNoz API key from env or Vault.")


class SigNozClient:
    def __init__(self, base_url: str, api_key: str, timeout_seconds: int = 30) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.headers = {
            "Content-Type": "application/json",
            "SIGNOZ-API-KEY": api_key,
        }

    def _request(self, method: str, path: str, payload: Any | None = None) -> tuple[int, Any]:
        body = None if payload is None else json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            url=f"{self.base_url}{path}",
            data=body,
            method=method,
            headers=self.headers,
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                content = response.read().decode("utf-8")
                if not content:
                    return response.status, None
                return response.status, json.loads(content)
        except urllib.error.HTTPError as exc:
            body_text = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"{method} {path} failed with {exc.code}: {body_text}") from exc

    def wait_until_ready(self, attempts: int, interval_seconds: int) -> None:
        url = f"{self.base_url}/api/v1/health"
        for _ in range(attempts):
            try:
                with urllib.request.urlopen(url, timeout=10) as response:
                    if response.status == 200:
                        return
            except Exception:
                pass
            time.sleep(interval_seconds)
        raise RuntimeError(f"SigNoz did not become ready at {url}")

    def list_channels(self) -> list[dict[str, Any]]:
        _, payload = self._request("GET", "/api/v1/channels")
        return payload["data"]

    def create_channel(self, payload: dict[str, Any]) -> None:
        self._request("POST", "/api/v1/channels", payload)

    def update_channel(self, channel_id: str, payload: dict[str, Any]) -> None:
        self._request("PUT", f"/api/v1/channels/{channel_id}", payload)

    def list_dashboards(self) -> list[dict[str, Any]]:
        _, payload = self._request("GET", "/api/v1/dashboards")
        return payload["data"]

    def create_dashboard(self, payload: dict[str, Any]) -> None:
        self._request("POST", "/api/v1/dashboards", payload)

    def update_dashboard(self, dashboard_id: str, payload: dict[str, Any]) -> None:
        self._request("PUT", f"/api/v1/dashboards/{dashboard_id}", payload)

    def list_alert_rules(self) -> list[dict[str, Any]]:
        _, payload = self._request("GET", "/api/v1/rules")
        return payload["data"]["rules"]

    def create_alert_rule(self, payload: dict[str, Any]) -> None:
        self._request("POST", "/api/v1/rules", payload)

    def update_alert_rule(self, rule_id: str, payload: dict[str, Any]) -> None:
        self._request("PUT", f"/api/v1/rules/{rule_id}", payload)


def fetch_remote_json(url: str) -> dict[str, Any]:
    with urllib.request.urlopen(url, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def set_dashboard_variable_defaults(dashboard: dict[str, Any], defaults: dict[str, Any]) -> None:
    for variable in dashboard.get("variables", {}).values():
        name = variable.get("name")
        if name in defaults:
            variable["selectedValue"] = defaults[name]


def metric_widget(
    *,
    title: str,
    metric_key: str,
    metric_type: str,
    aggregation_operator: str,
    time_aggregation: str,
    space_aggregation: str,
    y_axis_unit: str,
    x: int,
    y: int,
    w: int,
    h: int,
    group_by: list[dict[str, str]] | None = None,
    filters: list[dict[str, Any]] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    widget_id = str(uuid.uuid4())
    query_id = str(uuid.uuid4())
    widget = {
        "bucketCount": 30,
        "bucketWidth": 0,
        "columnUnits": {},
        "description": "",
        "fillSpans": False,
        "id": widget_id,
        "isStacked": False,
        "mergeAllActiveQueries": False,
        "nullZeroValues": "zero",
        "opacity": "1",
        "panelTypes": "graph",
        "query": {
            "builder": {
                "queryData": [
                    {
                        "aggregateAttribute": {
                            "dataType": "float64",
                            "id": f"{metric_key}--float64--{metric_type}--true",
                            "isColumn": True,
                            "isJSON": False,
                            "key": metric_key,
                            "type": metric_type,
                        },
                        "aggregateOperator": aggregation_operator,
                        "dataSource": "metrics",
                        "disabled": False,
                        "expression": "A",
                        "filters": {"items": filters or [], "op": "AND"},
                        "functions": [],
                        "groupBy": group_by or [],
                        "having": [],
                        "legend": "",
                        "limit": None,
                        "orderBy": [],
                        "queryName": "A",
                        "reduceTo": "avg",
                        "spaceAggregation": space_aggregation,
                        "stepInterval": 60,
                        "timeAggregation": time_aggregation,
                    }
                ],
                "queryFormulas": [],
            },
            "clickhouse_sql": [{"disabled": False, "legend": "", "name": "A", "query": ""}],
            "id": query_id,
            "promql": [{"disabled": False, "legend": "", "name": "A", "query": ""}],
            "queryType": "builder",
        },
        "selectedLogFields": [],
        "selectedTracesFields": [],
        "softMax": 0,
        "softMin": 0,
        "stackedBarChart": False,
        "thresholds": [],
        "timePreferance": "GLOBAL_TIME",
        "title": title,
        "yAxisUnit": y_axis_unit,
    }
    layout = {"h": h, "i": widget_id, "moved": False, "static": False, "w": w, "x": x, "y": y}
    return layout, widget


def generate_kafka_dashboard(config: dict[str, str]) -> dict[str, Any]:
    layout: list[dict[str, Any]] = []
    widgets: list[dict[str, Any]] = []
    group_by_topic = [
        {"dataType": "string", "id": "topic--string--tag--false", "isColumn": False, "key": "topic", "type": "tag"}
    ]
    group_by_group_topic = [
        {"dataType": "string", "id": "group--string--tag--false", "isColumn": False, "key": "group", "type": "tag"},
        {"dataType": "string", "id": "topic--string--tag--false", "isColumn": False, "key": "topic", "type": "tag"},
    ]
    group_by_partition = group_by_group_topic + [
        {
            "dataType": "string",
            "id": "partition--string--tag--false",
            "isColumn": False,
            "key": "partition",
            "type": "tag",
        }
    ]
    for widget_args in (
        dict(
            title="Consumer Lag by Group",
            metric_key="kafka.consumer_group.lag",
            metric_type="Gauge",
            aggregation_operator="avg",
            time_aggregation="avg",
            space_aggregation="avg",
            y_axis_unit="short",
            x=0,
            y=0,
            w=6,
            h=6,
            group_by=group_by_partition,
        ),
        dict(
            title="Messages Consumed",
            metric_key="kafka.consumer.records_consumed_rate",
            metric_type="Gauge",
            aggregation_operator="avg",
            time_aggregation="avg",
            space_aggregation="avg",
            y_axis_unit="reqps",
            x=6,
            y=0,
            w=6,
            h=6,
            group_by=group_by_group_topic,
        ),
        dict(
            title="Topic Partitions",
            metric_key="kafka.topic.partitions",
            metric_type="Gauge",
            aggregation_operator="avg",
            time_aggregation="avg",
            space_aggregation="avg",
            y_axis_unit="short",
            x=0,
            y=6,
            w=6,
            h=6,
            group_by=group_by_topic,
        ),
        dict(
            title="Partition Current Offset",
            metric_key="kafka.partition.current_offset",
            metric_type="Gauge",
            aggregation_operator="avg",
            time_aggregation="avg",
            space_aggregation="avg",
            y_axis_unit="short",
            x=6,
            y=6,
            w=6,
            h=6,
            group_by=group_by_partition,
        ),
    ):
        widget_layout, widget = metric_widget(**widget_args)
        layout.append(widget_layout)
        widgets.append(widget)
    return {
        "description": "Kafka consumer lag, throughput, topic, and offset visibility for the external LeninKart broker.",
        "layout": layout,
        "panelMap": {},
        "tags": ["leninkart", "kafka", "messaging"],
        "title": f"{config.get('PROJECT_NAME', 'LeninKart')} Kafka Overview",
        "uploadedGrafana": False,
        "variables": {},
        "version": "v4",
        "widgets": widgets,
    }


def prepare_dashboard_from_spec(spec: dict[str, Any], config: dict[str, str]) -> dict[str, Any]:
    source = spec["source"]
    if source["type"] == "official-template":
        dashboard = fetch_remote_json(source["url"])
    elif source["type"] == "generated":
        if source["generator"] != "kafka_overview":
            raise RuntimeError(f"Unsupported dashboard generator: {source['generator']}")
        dashboard = generate_kafka_dashboard(config)
    else:
        raise RuntimeError(f"Unsupported dashboard source type: {source['type']}")

    dashboard["title"] = spec["title"]
    dashboard["description"] = spec.get("description", dashboard.get("description", ""))
    dashboard["tags"] = list(dict.fromkeys((dashboard.get("tags") or []) + spec.get("tags", [])))
    dashboard["uploadedGrafana"] = False
    set_dashboard_variable_defaults(dashboard, spec.get("variable_defaults", {}))
    return dashboard


def build_channel_payload(spec: dict[str, Any], config: dict[str, str]) -> dict[str, Any] | None:
    if spec.get("enabled_var") and not parse_bool(config.get(spec["enabled_var"]), default=False):
        return None
    if spec["type"] == "email":
        recipients = parse_csv(config.get(spec["to_var"], ""))
        if not recipients:
            return None
        return {
            "name": spec["name"],
            "email_configs": [
                {
                    "send_resolved": spec.get("send_resolved", True),
                    "to": recipients,
                    "html": spec.get("html", ""),
                    "headers": spec.get("headers", {}),
                }
            ],
        }
    if spec["type"] == "slack":
        webhook = config.get(spec["webhook_var"], "").strip()
        if not webhook:
            return None
        return {
            "name": spec["name"],
            "slack_configs": [
                {
                    "send_resolved": spec.get("send_resolved", True),
                    "api_url": webhook,
                    "channel": config.get(spec.get("channel_var", ""), "") if spec.get("channel_var") else "",
                    "title": spec.get("title", ""),
                    "text": spec.get("text", ""),
                }
            ],
        }
    raise RuntimeError(f"Unsupported channel type: {spec['type']}")


def build_alert_payload(
    spec: dict[str, Any], config: dict[str, str], created_channels: dict[str, str]
) -> dict[str, Any] | None:
    threshold_value = spec.get("threshold")
    if spec.get("threshold_var"):
        raw_value = config[spec["threshold_var"]]
        threshold_value = float(raw_value) if "." in raw_value else int(raw_value)

    resolved_channel_names = [
        created_channels[channel_ref]
        for channel_ref in spec.get("channels", [])
        if channel_ref in created_channels
    ]
    if not resolved_channel_names:
        return None

    if spec["signal"] == "metrics":
        aggregation = {
            "metricName": spec["metric_name"],
            "timeAggregation": spec.get("time_aggregation", "avg"),
            "spaceAggregation": spec.get("space_aggregation", "avg"),
        }
    else:
        aggregation = {"expression": spec["aggregation_expression"]}

    return {
        "alert": spec["name"],
        "ruleType": "threshold_rule",
        "alertType": spec["alert_type"],
        "condition": {
            "thresholds": {
                "kind": "basic",
                "spec": [
                    {
                        "name": "critical",
                        "target": threshold_value,
                        "matchType": spec.get("match_type", "3"),
                        "op": spec.get("op", "1"),
                        "channels": resolved_channel_names,
                        "targetUnit": spec.get("target_unit", ""),
                    }
                ],
            },
            "compositeQuery": {
                "queryType": "builder",
                "panelType": "graph",
                "unit": spec.get("unit"),
                "queries": [
                    {
                        "type": "builder_query",
                        "spec": {
                            "name": "A",
                            "signal": spec["signal"],
                            "filter": {"expression": spec.get("filter_expression", "")},
                            "aggregations": [aggregation],
                        },
                    }
                ],
            },
            "selectedQueryName": "A",
            "alertOnAbsent": spec.get("alert_on_absent", False),
            "absentFor": spec.get("absent_for", 1),
        },
        "evaluation": {
            "kind": "rolling",
            "spec": {
                "evalWindow": spec.get("eval_window", config.get("DEFAULT_EVAL_WINDOW", "5m0s")),
                "frequency": spec.get("frequency", config.get("DEFAULT_EVAL_FREQUENCY", "1m")),
            },
        },
        "labels": {"severity": spec.get("severity", "warning")},
        "annotations": {
            "description": spec.get(
                "description",
                "This alert is fired when the defined metric (current value: {{$value}}) crosses the threshold ({{$threshold}})",
            ),
            "summary": spec.get(
                "summary",
                "The rule threshold is set to {{$threshold}}, and the observed metric value is {{$value}}",
            ),
        },
        "notificationSettings": {
            "groupBy": [],
            "usePolicy": False,
            "renotify": {"enabled": False, "interval": "30m", "alertStates": []},
        },
        "version": "v5",
        "schemaVersion": "v2alpha1",
    }


def main() -> int:
    config = resolve_config()
    api_key = resolve_signoz_api_key(config)
    client = SigNozClient(config.get("SIGNOZ_BASE_URL", "http://127.0.0.1:8080"), api_key)
    client.wait_until_ready(
        int(config.get("READY_CHECK_ATTEMPTS", "30")),
        int(config.get("READY_CHECK_INTERVAL_SECONDS", "10")),
    )

    channels_spec = load_json_document(CHANNELS_PATH)["channels"]
    dashboards_spec = load_json_document(DASHBOARDS_PATH)["dashboards"]
    alerts_spec = load_json_document(ALERTS_PATH)["alerts"]

    summary: dict[str, Any] = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "signoz_base_url": config.get("SIGNOZ_BASE_URL", "http://127.0.0.1:8080"),
        "channels": {"created": [], "updated": [], "skipped": []},
        "dashboards": {"created": [], "updated": []},
        "alerts": {"created": [], "updated": [], "skipped": []},
    }

    existing_channels = {item["name"]: item for item in client.list_channels()}
    created_channels: dict[str, str] = {}
    for spec in channels_spec:
        payload = build_channel_payload(spec, config)
        if payload is None:
            summary["channels"]["skipped"].append({"name": spec["name"], "reason": "disabled-or-missing-config"})
            continue
        if payload["name"] in existing_channels:
            client.update_channel(existing_channels[payload["name"]]["id"], payload)
            summary["channels"]["updated"].append(payload["name"])
        else:
            client.create_channel(payload)
            summary["channels"]["created"].append(payload["name"])
        created_channels[spec["ref"]] = payload["name"]

    existing_dashboards = {item["data"]["title"]: item for item in client.list_dashboards()}
    for spec in dashboards_spec:
        payload = prepare_dashboard_from_spec(spec, config)
        if payload["title"] in existing_dashboards:
            client.update_dashboard(existing_dashboards[payload["title"]]["id"], payload)
            summary["dashboards"]["updated"].append(payload["title"])
        else:
            client.create_dashboard(payload)
            summary["dashboards"]["created"].append(payload["title"])

    existing_rules = {item["alert"]: item for item in client.list_alert_rules()}
    for spec in alerts_spec:
        if spec.get("requires_var") and not parse_bool(config.get(spec["requires_var"]), default=False):
            summary["alerts"]["skipped"].append({"name": spec["name"], "reason": "feature-flag-disabled"})
            continue
        payload = build_alert_payload(spec, config, created_channels)
        if payload is None:
            summary["alerts"]["skipped"].append({"name": spec["name"], "reason": "no-channels-configured"})
            continue
        if payload["alert"] in existing_rules:
            client.update_alert_rule(existing_rules[payload["alert"]]["id"], payload)
            summary["alerts"]["updated"].append(payload["alert"])
        else:
            client.create_alert_rule(payload)
            summary["alerts"]["created"].append(payload["alert"])

    SUMMARY_PATH.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"bootstrap failed: {exc}", file=sys.stderr)
        raise

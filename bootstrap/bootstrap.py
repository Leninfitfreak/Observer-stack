#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
import traceback
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
QUERY_VALIDATION_REPORT_PATH = BOOTSTRAP_DIR / "DASHBOARD_QUERY_VALIDATION_REPORT.md"
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

    def delete_dashboard(self, dashboard_id: str) -> None:
        self._request("DELETE", f"/api/v1/dashboards/{dashboard_id}")

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


def stable_dashboard_uuid(title: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"leninkart-signoz-dashboard:{title}"))


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


def tag_filter(key: str, value: str, *, op: str = "=") -> dict[str, Any]:
    return {
        "id": str(uuid.uuid4())[:8],
        "key": {
            "dataType": "string",
            "id": f"{key}--string--tag--false",
            "isColumn": False,
            "key": key,
            "type": "tag",
        },
        "op": op,
        "value": value,
    }


def filters_to_expression(filters: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for item in filters:
        key = item["key"]["key"]
        op = item.get("op", "=")
        value = str(item.get("value", "")).replace('"', '\\"')
        if op == "=":
            parts.append(f'{key} = "{value}"')
        else:
            parts.append(f'{key} {op} "{value}"')
    return " AND ".join(parts)


def widget_to_query_payload(widget: dict[str, Any], *, start_ms: int, end_ms: int) -> dict[str, Any]:
    query_data = widget["query"]["builder"]["queryData"][0]
    return {
        "schemaVersion": "v1",
        "start": start_ms,
        "end": end_ms,
        "requestType": "time_series",
        "compositeQuery": {
            "queries": [
                {
                    "type": "builder_query",
                    "spec": {
                        "name": query_data["queryName"],
                        "signal": "metrics",
                        "source": query_data.get("source", ""),
                        "disabled": query_data.get("disabled", False),
                        "stepInterval": query_data.get("stepInterval"),
                        "filter": {
                            "expression": filters_to_expression(query_data.get("filters", {}).get("items", []))
                        },
                        "groupBy": [
                            {
                                "name": group["key"],
                                "fieldDataType": group.get("dataType", ""),
                                "fieldContext": group.get("type", ""),
                            }
                            for group in query_data.get("groupBy", [])
                        ]
                        or None,
                        "legend": query_data.get("legend") or None,
                        "limit": query_data.get("limit"),
                        "aggregations": [
                            {
                                "metricName": query_data["aggregateAttribute"]["key"],
                                "timeAggregation": query_data["timeAggregation"],
                                "spaceAggregation": query_data["spaceAggregation"],
                            }
                        ],
                    },
                }
            ]
        },
        "formatOptions": {"formatTableResultForUI": False, "fillGaps": False},
        "variables": {},
    }


def classify_query_result(
    *,
    widget: dict[str, Any],
    response_payload: dict[str, Any],
    wall_time_ms: float,
    config: dict[str, str],
) -> dict[str, Any]:
    meta = response_payload.get("data", {}).get("meta", {}) or {}
    results = response_payload.get("data", {}).get("data", {}).get("results", []) or []
    result_set = results[0] if results else {}
    aggregations = result_set.get("aggregations")
    series_count = len(aggregations) if isinstance(aggregations, list) else 0
    group_by_count = len(widget["query"]["builder"]["queryData"][0].get("groupBy", []))
    status = "safe"
    reasons: list[str] = []

    max_meta_duration_ms = int(config.get("MAX_WIDGET_META_DURATION_MS", "2500"))
    max_wall_time_ms = int(config.get("MAX_WIDGET_WALL_TIME_MS", "8000"))
    max_rows_scanned = int(config.get("MAX_WIDGET_ROWS_SCANNED", "150000"))
    max_bytes_scanned = int(config.get("MAX_WIDGET_BYTES_SCANNED", str(20 * 1024 * 1024)))
    max_series_count = int(config.get("MAX_WIDGET_SERIES_COUNT", "20"))
    max_group_by = int(config.get("MAX_WIDGET_GROUP_BY_COUNT", "1"))

    meta_duration_ms = int(meta.get("durationMs", 0) or 0)
    rows_scanned = int(meta.get("rowsScanned", 0) or 0)
    bytes_scanned = int(meta.get("bytesScanned", 0) or 0)

    if group_by_count > max_group_by:
        status = "unsafe"
        reasons.append(f"group_by_count>{max_group_by}")
    if meta_duration_ms > max_meta_duration_ms:
        status = "unsafe"
        reasons.append(f"meta_duration_ms>{max_meta_duration_ms}")
    if wall_time_ms > max_wall_time_ms:
        status = "unsafe"
        reasons.append(f"wall_time_ms>{max_wall_time_ms}")
    if rows_scanned > max_rows_scanned:
        status = "unsafe"
        reasons.append(f"rows_scanned>{max_rows_scanned}")
    if bytes_scanned > max_bytes_scanned:
        status = "unsafe"
        reasons.append(f"bytes_scanned>{max_bytes_scanned}")
    if series_count > max_series_count:
        status = "unsafe"
        reasons.append(f"series_count>{max_series_count}")

    return {
        "status": status,
        "reasons": reasons,
        "meta_duration_ms": meta_duration_ms,
        "wall_time_ms": round(wall_time_ms, 2),
        "rows_scanned": rows_scanned,
        "bytes_scanned": bytes_scanned,
        "series_count": series_count,
        "group_by_count": group_by_count,
    }


def validate_dashboard_queries(
    client: SigNozClient,
    dashboard: dict[str, Any],
    config: dict[str, str],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    validation_window_minutes = int(config.get("QUERY_VALIDATION_WINDOW_MINUTES", "15"))
    end_ms = int(time.time() * 1000)
    start_ms = end_ms - validation_window_minutes * 60 * 1000
    kept_widgets: list[dict[str, Any]] = []
    kept_layout_ids: set[str] = set()
    widget_results: list[dict[str, Any]] = []

    for widget in dashboard.get("widgets", []):
        widget_result: dict[str, Any] = {
            "title": widget.get("title", ""),
            "metric": widget["query"]["builder"]["queryData"][0]["aggregateAttribute"]["key"],
            "group_by": [item["key"] for item in widget["query"]["builder"]["queryData"][0].get("groupBy", [])],
            "filters": [
                f'{item["key"]["key"]}{item.get("op", "=")}{item.get("value", "")}'
                for item in widget["query"]["builder"]["queryData"][0].get("filters", {}).get("items", [])
            ],
        }
        try:
            payload = widget_to_query_payload(widget, start_ms=start_ms, end_ms=end_ms)
            started = time.perf_counter()
            _, response_payload = client._request("POST", "/api/v5/query_range", payload)
            wall_time_ms = (time.perf_counter() - started) * 1000
            widget_result["payload"] = payload
            widget_result["response_meta"] = response_payload.get("data", {}).get("meta", {}) or {}
            widget_result.update(
                classify_query_result(
                    widget=widget,
                    response_payload=response_payload,
                    wall_time_ms=wall_time_ms,
                    config=config,
                )
            )
        except Exception as exc:
            widget_result["status"] = "unsafe"
            widget_result["reasons"] = [f"request_failed:{type(exc).__name__}"]
            widget_result["error"] = str(exc)
            widget_result["traceback"] = traceback.format_exc(limit=1)

        if widget_result["status"] == "safe":
            kept_widgets.append(widget)
            kept_layout_ids.add(widget["id"])
        widget_results.append(widget_result)

    filtered_dashboard = dict(dashboard)
    filtered_dashboard["widgets"] = kept_widgets
    filtered_dashboard["layout"] = [
        item for item in dashboard.get("layout", []) if item.get("i") in kept_layout_ids
    ]
    return filtered_dashboard, widget_results


def write_query_validation_report(results: list[dict[str, Any]]) -> None:
    lines = ["# DASHBOARD_QUERY_VALIDATION_REPORT", "", "## Scope", ""]
    lines.append("This report records per-widget live query validation against `/api/v5/query_range` before dashboards are written to SigNoz.")
    lines.extend(["", "## Dashboards Analyzed", ""])
    for dashboard in results:
        lines.append(f"- `{dashboard['title']}`")
    lines.extend(["", "## Per-Dashboard Results", ""])
    for dashboard in results:
        lines.append(f"### {dashboard['title']}")
        lines.append("")
        lines.append(f"- widgets kept: `{len(dashboard['kept_widgets'])}`")
        lines.append(f"- widgets removed: `{len(dashboard['removed_widgets'])}`")
        for widget in dashboard["widgets"]:
            status = widget["status"]
            reasons = ", ".join(widget.get("reasons", [])) or "none"
            lines.append(
                f"- `{widget['title']}`: status=`{status}`, metric=`{widget['metric']}`, "
                f"meta_duration_ms=`{widget.get('meta_duration_ms', 'n/a')}`, "
                f"wall_time_ms=`{widget.get('wall_time_ms', 'n/a')}`, "
                f"rows_scanned=`{widget.get('rows_scanned', 'n/a')}`, "
                f"bytes_scanned=`{widget.get('bytes_scanned', 'n/a')}`, "
                f"series_count=`{widget.get('series_count', 'n/a')}`, reasons=`{reasons}`"
            )
        lines.append("")
    QUERY_VALIDATION_REPORT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def base_dashboard(*, title: str, description: str, tags: list[str], widgets: list[dict[str, Any]], layout: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "description": description,
        "layout": layout,
        "panelMap": {},
        "tags": tags,
        "title": title,
        "uploadedGrafana": False,
        "variables": {},
        "version": "v4",
        "widgets": widgets,
    }


def build_dashboard(widget_args_list: list[dict[str, Any]], *, title: str, description: str, tags: list[str]) -> dict[str, Any]:
    layout: list[dict[str, Any]] = []
    widgets: list[dict[str, Any]] = []
    for widget_args in widget_args_list:
        widget_layout, widget = metric_widget(**widget_args)
        widget["bucketCount"] = 12
        layout.append(widget_layout)
        widgets.append(widget)
    return base_dashboard(title=title, description=description, tags=tags, widgets=widgets, layout=layout)


def service_filters(service_name: str) -> list[dict[str, Any]]:
    return [tag_filter("service.name", service_name)]


def frontend_filters(config: dict[str, str]) -> list[dict[str, Any]]:
    filters = [tag_filter("k8s.container.name", "frontend")]
    namespace = config.get("K8S_NAMESPACE", "dev").strip()
    if namespace:
        filters.append(tag_filter("k8s.namespace.name", namespace))
    return filters


def generate_platform_dashboard(config: dict[str, str]) -> dict[str, Any]:
    title = f"{config.get('PROJECT_NAME', 'LeninKart')} Platform Overview"
    return build_dashboard(
        [
            dict(
                title="Product Request Rate",
                metric_key="signoz_calls_total",
                metric_type="Sum",
                aggregation_operator="sum",
                time_aggregation="rate",
                space_aggregation="sum",
                y_axis_unit="reqps",
                x=0,
                y=0,
                w=3,
                h=6,
                filters=service_filters("product-service"),
            ),
            dict(
                title="Order Request Rate",
                metric_key="signoz_calls_total",
                metric_type="Sum",
                aggregation_operator="sum",
                time_aggregation="rate",
                space_aggregation="sum",
                y_axis_unit="reqps",
                x=3,
                y=0,
                w=3,
                h=6,
                filters=service_filters("order-service"),
            ),
            dict(
                title="Kafka Messages In Rate",
                metric_key="kafka.broker.topic.messages_in.rate",
                metric_type="Gauge",
                aggregation_operator="avg",
                time_aggregation="avg",
                space_aggregation="avg",
                y_axis_unit="reqps",
                x=6,
                y=0,
                w=3,
                h=6,
                filters=[],
            ),
            dict(
                title="Frontend CPU Utilization",
                metric_key="container.cpu.utilization",
                metric_type="Gauge",
                aggregation_operator="avg",
                time_aggregation="avg",
                space_aggregation="avg",
                y_axis_unit="percentunit",
                x=9,
                y=0,
                w=3,
                h=6,
                filters=frontend_filters(config),
            ),
        ],
        title=title,
        description="Showcase dashboard with four low-cost signals across the LeninKart platform.",
        tags=["leninkart", "platform", "showcase"],
    )


def generate_service_dashboard(config: dict[str, str], *, service_name: str, display_name: str) -> dict[str, Any]:
    title = f"{config.get('PROJECT_NAME', 'LeninKart')} {display_name} Overview"
    filters = service_filters(service_name)
    return build_dashboard(
        [
            dict(
                title="Request Rate",
                metric_key="signoz_calls_total",
                metric_type="Sum",
                aggregation_operator="sum",
                time_aggregation="rate",
                space_aggregation="sum",
                y_axis_unit="reqps",
                x=0,
                y=0,
                w=4,
                h=6,
                filters=filters,
            ),
            dict(
                title="Database Call Rate",
                metric_key="signoz_db_latency_count",
                metric_type="Sum",
                aggregation_operator="sum",
                time_aggregation="rate",
                space_aggregation="sum",
                y_axis_unit="reqps",
                x=4,
                y=0,
                w=4,
                h=6,
                filters=filters,
            ),
            dict(
                title="External Call Rate",
                metric_key="signoz_external_call_latency_count",
                metric_type="Sum",
                aggregation_operator="sum",
                time_aggregation="rate",
                space_aggregation="sum",
                y_axis_unit="reqps",
                x=8,
                y=0,
                w=4,
                h=6,
                filters=filters,
            ),
        ],
        title=title,
        description=f"Showcase dashboard with three low-cost service metrics for {service_name}.",
        tags=["leninkart", service_name, "showcase"],
    )


def generate_frontend_dashboard(config: dict[str, str]) -> dict[str, Any]:
    title = f"{config.get('PROJECT_NAME', 'LeninKart')} Frontend Overview"
    filters = frontend_filters(config)
    return build_dashboard(
        [
            dict(
                title="CPU Utilization",
                metric_key="container.cpu.utilization",
                metric_type="Gauge",
                aggregation_operator="avg",
                time_aggregation="avg",
                space_aggregation="avg",
                y_axis_unit="percentunit",
                x=0,
                y=0,
                w=4,
                h=6,
                filters=filters,
            ),
            dict(
                title="Memory Working Set",
                metric_key="container.memory.working_set",
                metric_type="Gauge",
                aggregation_operator="avg",
                time_aggregation="avg",
                space_aggregation="avg",
                y_axis_unit="bytes",
                x=4,
                y=0,
                w=4,
                h=6,
                filters=filters,
            ),
            dict(
                title="Memory RSS",
                metric_key="container.memory.rss",
                metric_type="Gauge",
                aggregation_operator="avg",
                time_aggregation="avg",
                space_aggregation="avg",
                y_axis_unit="bytes",
                x=8,
                y=0,
                w=4,
                h=6,
                filters=filters,
            ),
        ],
        title=title,
        description="Showcase dashboard with three lightweight frontend pod metrics.",
        tags=["leninkart", "frontend", "showcase"],
    )


def generate_kafka_dashboard(config: dict[str, str]) -> dict[str, Any]:
    title = f"{config.get('PROJECT_NAME', 'LeninKart')} Kafka Overview"
    group_by_group = [
        {"dataType": "string", "id": "group--string--tag--false", "isColumn": False, "key": "group", "type": "tag"}
    ]
    return build_dashboard(
        [
            dict(
                title="Total Consumer Lag",
                metric_key="kafka.consumer_group.lag",
                metric_type="Gauge",
                aggregation_operator="max",
                time_aggregation="max",
                space_aggregation="max",
                y_axis_unit="short",
                x=0,
                y=0,
                w=4,
                h=6,
                group_by=[],
                filters=[],
            ),
            dict(
                title="Messages Consumed by Group",
                metric_key="kafka.consumer.records_consumed_rate",
                metric_type="Gauge",
                aggregation_operator="avg",
                time_aggregation="avg",
                space_aggregation="avg",
                y_axis_unit="reqps",
                x=4,
                y=0,
                w=4,
                h=6,
                group_by=group_by_group,
                filters=[],
            ),
            dict(
                title="Messages In Rate",
                metric_key="kafka.broker.topic.messages_in.rate",
                metric_type="Gauge",
                aggregation_operator="avg",
                time_aggregation="avg",
                space_aggregation="avg",
                y_axis_unit="reqps",
                x=8,
                y=0,
                w=4,
                h=6,
                group_by=[],
                filters=[],
            ),
        ],
        title=title,
        description="Showcase dashboard with three low-cost Kafka metrics for the external LeninKart broker.",
        tags=["leninkart", "kafka", "showcase"],
    )


def prepare_dashboard_from_spec(spec: dict[str, Any], config: dict[str, str]) -> dict[str, Any]:
    source = spec["source"]
    if source["type"] == "official-template":
        dashboard = fetch_remote_json(source["url"])
    elif source["type"] == "generated":
        generator = source["generator"]
        if generator == "platform_overview":
            dashboard = generate_platform_dashboard(config)
        elif generator == "product_service_overview":
            dashboard = generate_service_dashboard(config, service_name="product-service", display_name="Product Service")
        elif generator == "order_service_overview":
            dashboard = generate_service_dashboard(config, service_name="order-service", display_name="Order Service")
        elif generator == "frontend_overview":
            dashboard = generate_frontend_dashboard(config)
        elif generator == "kafka_overview":
            dashboard = generate_kafka_dashboard(config)
        else:
            raise RuntimeError(f"Unsupported dashboard generator: {generator}")
    else:
        raise RuntimeError(f"Unsupported dashboard source type: {source['type']}")

    dashboard["title"] = spec["title"]
    dashboard["description"] = spec.get("description", dashboard.get("description", ""))
    dashboard["tags"] = list(dict.fromkeys((dashboard.get("tags") or []) + spec.get("tags", [])))
    dashboard["uploadedGrafana"] = False
    dashboard.setdefault("uuid", stable_dashboard_uuid(spec["title"]))
    dashboard.setdefault("image", "")
    dashboard.setdefault("dotMigrated", True)
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
                    "to": ",".join(recipients),
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
        "dashboards": {"created": [], "updated": [], "deleted": []},
        "alerts": {"created": [], "updated": [], "skipped": []},
        "query_validation": {"dashboards": []},
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
    desired_titles = {spec["title"] for spec in dashboards_spec}
    for spec in dashboards_spec:
        payload = prepare_dashboard_from_spec(spec, config)
        payload, widget_results = validate_dashboard_queries(client, payload, config)
        summary["query_validation"]["dashboards"].append(
            {
                "title": payload["title"],
                "widgets": widget_results,
                "kept_widgets": [item["title"] for item in widget_results if item["status"] == "safe"],
                "removed_widgets": [item["title"] for item in widget_results if item["status"] != "safe"],
            }
        )
        if not payload["widgets"]:
            raise RuntimeError(f"Dashboard {payload['title']} had no safe widgets after query validation.")
        if payload["title"] in existing_dashboards:
            client.update_dashboard(existing_dashboards[payload["title"]]["id"], payload)
            summary["dashboards"]["updated"].append(payload["title"])
        else:
            client.create_dashboard(payload)
            summary["dashboards"]["created"].append(payload["title"])
    project_prefix = f"{config.get('PROJECT_NAME', 'LeninKart')} "
    for title, existing in existing_dashboards.items():
        if title.startswith(project_prefix) and title not in desired_titles:
            client.delete_dashboard(existing["id"])
            summary["dashboards"]["deleted"].append(title)

    write_query_validation_report(summary["query_validation"]["dashboards"])

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

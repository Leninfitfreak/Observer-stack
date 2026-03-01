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


def _query_prometheus_series(prom_url: str, query: str, metric_name: str) -> list[dict[str, Any]]:
    if not prom_url:
        log.warning("Prometheus URL missing; metric=%s has no series", metric_name)
        return []
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
        if not isinstance(results, list) or not results:
            log.warning("Prometheus returned empty series for metric=%s query=%s", metric_name, query)
            return []
        out: list[dict[str, Any]] = []
        for row in results:
            if not isinstance(row, dict):
                continue
            metric = row.get("metric")
            sample = row.get("value")
            if not isinstance(metric, dict) or not isinstance(sample, list) or len(sample) < 2:
                continue
            try:
                out.append({"metric": metric, "value": float(sample[1])})
            except (TypeError, ValueError):
                continue
        return out
    except (requests.RequestException, ValueError, TypeError) as exc:
        log.warning("Prometheus series query failed for metric=%s query=%s err=%s", metric_name, query, exc)
        return []


def _query_pod_cpu_rates(prom_url: str) -> dict[tuple[str, str], float]:
    series = _query_prometheus_series(
        prom_url,
        'sum(rate(container_cpu_usage_seconds_total{namespace!="",pod!="",container!=""}[2m])) by (namespace,pod)',
        "cpu_usage_pod_series",
    )
    rates: dict[tuple[str, str], float] = {}
    for row in series:
        metric = row.get("metric") or {}
        namespace = str(metric.get("namespace", "")).strip()
        pod = str(metric.get("pod", "")).strip()
        if not namespace or not pod:
            continue
        key = (namespace, pod)
        rates[key] = rates.get(key, 0.0) + float(row.get("value", 0.0) or 0.0)
    return rates


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


def _read_file(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return handle.read().strip()
    except OSError:
        return ""


def _k8s_api_get(session: requests.Session, base_url: str, path: str, timeout_seconds: float) -> dict[str, Any]:
    response = session.get(
        f"{base_url.rstrip('/')}{path}",
        timeout=timeout_seconds,
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        return {}
    return payload


def _service_selected_pods(service: dict[str, Any], pods: list[dict[str, Any]]) -> list[dict[str, Any]]:
    selector = ((service.get("spec") or {}).get("selector") or {})
    if not selector:
        return []
    selected: list[dict[str, Any]] = []
    for pod in pods:
        labels = ((pod.get("metadata") or {}).get("labels") or {})
        if all(labels.get(k) == v for k, v in selector.items()):
            selected.append(pod)
    return selected


def _owner_chain(pod: dict[str, Any], rs_to_dep: dict[str, str]) -> list[dict[str, str]]:
    chain: list[dict[str, str]] = []
    owners = ((pod.get("metadata") or {}).get("ownerReferences") or [])
    if not isinstance(owners, list):
        return chain
    for owner in owners:
        if not isinstance(owner, dict):
            continue
        kind = str(owner.get("kind", "")).strip()
        name = str(owner.get("name", "")).strip()
        if not kind or not name:
            continue
        chain.append({"kind": kind, "name": name})
        if kind == "ReplicaSet":
            dep_name = rs_to_dep.get(name)
            if dep_name:
                chain.append({"kind": "Deployment", "name": dep_name})
    return chain


def _service_key(namespace: str, name: str) -> str:
    return f"{namespace}/{name}"


def _service_dns_variants(namespace: str, name: str) -> set[str]:
    base = f"{name}.{namespace}.svc.cluster.local"
    return {
        name.lower(),
        f"{name}.{namespace}".lower(),
        f"{name}.{namespace}.svc".lower(),
        base.lower(),
        f"http://{name}".lower(),
        f"http://{name}.{namespace}".lower(),
        f"http://{base}".lower(),
        f"https://{name}".lower(),
        f"https://{name}.{namespace}".lower(),
        f"https://{base}".lower(),
    }


def _discover_observability_services(services: list[dict[str, Any]]) -> dict[str, str]:
    out: dict[str, str] = {}
    for svc in services:
        meta = svc.get("metadata") or {}
        ns = str(meta.get("namespace", "")).strip()
        name = str(meta.get("name", "")).strip()
        if not ns or not name:
            continue
        lname = name.lower()
        key = _service_key(ns, name)
        if "prometheus" in lname and "prometheus" not in out:
            out["prometheus"] = key
        elif "loki" in lname and "loki" not in out:
            out["loki"] = key
        elif "jaeger" in lname and "jaeger" not in out:
            out["jaeger"] = key
    return out


def _init_k8s_client() -> tuple[requests.Session, str, float] | None:
    in_cluster_token_path = _env(
        "K8S_SA_TOKEN_PATH",
        "/var/run/secrets/kubernetes.io/serviceaccount/token",
    )
    in_cluster_ca_path = _env(
        "K8S_SA_CA_PATH",
        "/var/run/secrets/kubernetes.io/serviceaccount/ca.crt",
    )
    token = _env("K8S_BEARER_TOKEN") or _read_file(in_cluster_token_path)
    if not token:
        return None
    base_url = _env("K8S_API_URL", "https://kubernetes.default.svc")
    timeout_seconds = _float(_env("K8S_DISCOVERY_TIMEOUT_SECONDS", "4"), 4.0)
    verify_ssl_env = _env("K8S_VERIFY_SSL", "true").lower()
    verify_ssl: bool | str
    if verify_ssl_env in {"0", "false", "no", "off"}:
        verify_ssl = False
    elif os.path.exists(in_cluster_ca_path):
        verify_ssl = in_cluster_ca_path
    else:
        verify_ssl = True
    session = requests.Session()
    session.headers.update({"Authorization": f"Bearer {token}"})
    session.verify = verify_ssl
    return session, base_url, timeout_seconds


def _discover_topology() -> dict[str, Any]:
    discovery_enabled = _env("K8S_DISCOVERY_ENABLED", "true").lower() in {"1", "true", "yes", "on"}
    if not discovery_enabled:
        return {}

    k8s_client = _init_k8s_client()
    if not k8s_client:
        log.warning("Kubernetes discovery enabled but service account token is unavailable")
        return {}
    session, base_url, timeout_seconds = k8s_client

    namespace_filter = [part.strip() for part in _env("K8S_DISCOVERY_NAMESPACES", "").split(",") if part.strip()]
    namespace_set = set(namespace_filter)

    try:
        nodes_items = _k8s_api_get(session, base_url, "/api/v1/nodes", timeout_seconds).get("items", [])
        pods_items = _k8s_api_get(session, base_url, "/api/v1/pods", timeout_seconds).get("items", [])
        services_items = _k8s_api_get(session, base_url, "/api/v1/services", timeout_seconds).get("items", [])
        endpoints_items = _k8s_api_get(session, base_url, "/api/v1/endpoints", timeout_seconds).get("items", [])
        deployments_items = _k8s_api_get(session, base_url, "/apis/apps/v1/deployments", timeout_seconds).get("items", [])
        namespaces_items = _k8s_api_get(session, base_url, "/api/v1/namespaces", timeout_seconds).get("items", [])
        ingresses_items = _k8s_api_get(session, base_url, "/apis/networking.k8s.io/v1/ingresses", timeout_seconds).get("items", [])
    except (requests.RequestException, ValueError) as exc:
        log.warning("Kubernetes topology discovery failed err=%s", exc)
        return {}

    def _namespace_ok(item: dict[str, Any]) -> bool:
        if not namespace_set:
            return True
        namespace = ((item.get("metadata") or {}).get("namespace") or "")
        return namespace in namespace_set

    pods = [item for item in pods_items if _namespace_ok(item)]
    services = [item for item in services_items if _namespace_ok(item)]
    endpoints = [item for item in endpoints_items if _namespace_ok(item)]
    deployments = [item for item in deployments_items if _namespace_ok(item)]
    ingresses = [item for item in ingresses_items if _namespace_ok(item)]
    namespaces = namespaces_items
    nodes = nodes_items

    detected_cluster_id = _env("CLUSTER_ID")
    if nodes:
        first_node = nodes[0].get("metadata") or {}
        node_name = str(first_node.get("name", "")).strip()
        if node_name:
            detected_cluster_id = node_name

    namespace_inventory = sorted(
        {
            str((ns.get("metadata") or {}).get("name", "")).strip()
            for ns in namespaces
            if str((ns.get("metadata") or {}).get("name", "")).strip()
        }
    )
    service_inventory = sorted(
        [
            {
                "namespace": str((svc.get("metadata") or {}).get("namespace", "")).strip(),
                "name": str((svc.get("metadata") or {}).get("name", "")).strip(),
            }
            for svc in services
            if str((svc.get("metadata") or {}).get("namespace", "")).strip()
            and str((svc.get("metadata") or {}).get("name", "")).strip()
        ],
        key=lambda x: (x["namespace"], x["name"]),
    )
    pod_inventory = sorted(
        [
            {
                "namespace": str((pod.get("metadata") or {}).get("namespace", "")).strip(),
                "name": str((pod.get("metadata") or {}).get("name", "")).strip(),
            }
            for pod in pods
            if str((pod.get("metadata") or {}).get("namespace", "")).strip()
            and str((pod.get("metadata") or {}).get("name", "")).strip()
        ],
        key=lambda x: (x["namespace"], x["name"]),
    )

    service_to_pods: list[dict[str, Any]] = []
    pod_to_containers: list[dict[str, Any]] = []
    pod_ownership: list[dict[str, Any]] = []
    service_to_service: list[dict[str, Any]] = []
    namespace_segmentation: dict[str, dict[str, int]] = {}
    observability_services = _discover_observability_services(services)

    rs_to_dep: dict[str, str] = {}
    for dep in deployments:
        dep_meta = dep.get("metadata") or {}
        dep_name = str(dep_meta.get("name", "")).strip()
        dep_ns = str(dep_meta.get("namespace", "")).strip()
        selector = (((dep.get("spec") or {}).get("selector") or {}).get("matchLabels") or {})
        if not dep_name or not dep_ns or not selector:
            continue
        for pod in pods:
            pod_meta = pod.get("metadata") or {}
            pod_ns = str(pod_meta.get("namespace", "")).strip()
            if pod_ns != dep_ns:
                continue
            labels = (pod_meta.get("labels") or {})
            if not all(labels.get(k) == v for k, v in selector.items()):
                continue
            owners = pod_meta.get("ownerReferences") or []
            for owner in owners:
                if isinstance(owner, dict) and str(owner.get("kind", "")).strip() == "ReplicaSet":
                    rs_name = str(owner.get("name", "")).strip()
                    if rs_name:
                        rs_to_dep[rs_name] = dep_name

    for svc in services:
        svc_meta = svc.get("metadata") or {}
        svc_name = str(svc_meta.get("name", "")).strip()
        svc_ns = str(svc_meta.get("namespace", "")).strip()
        if not svc_name or not svc_ns:
            continue
        selected = _service_selected_pods(svc, pods)
        for pod in selected:
            pod_meta = pod.get("metadata") or {}
            pod_name = str(pod_meta.get("name", "")).strip()
            pod_ns = str(pod_meta.get("namespace", "")).strip()
            if not pod_name or not pod_ns:
                continue
            service_to_pods.append(
                {
                    "service": _service_key(svc_ns, svc_name),
                    "pod": f"{pod_ns}/{pod_name}",
                }
            )

    svc_dns_map: dict[str, set[str]] = {}
    for svc in services:
        meta = svc.get("metadata") or {}
        ns = str(meta.get("namespace", "")).strip()
        name = str(meta.get("name", "")).strip()
        if ns and name:
            svc_dns_map[_service_key(ns, name)] = _service_dns_variants(ns, name)

    pod_to_service: dict[str, str] = {}
    for rel in service_to_pods:
        svc = str(rel.get("service", "")).strip()
        pod = str(rel.get("pod", "")).strip()
        if svc and pod and pod not in pod_to_service:
            pod_to_service[pod] = svc

    for pod in pods:
        pod_meta = pod.get("metadata") or {}
        pod_name = str(pod_meta.get("name", "")).strip()
        pod_ns = str(pod_meta.get("namespace", "")).strip()
        if not pod_name or not pod_ns:
            continue
        pod_key = f"{pod_ns}/{pod_name}"
        namespace_segmentation.setdefault(pod_ns, {"pods": 0, "services": 0, "deployments": 0, "ingresses": 0})
        namespace_segmentation[pod_ns]["pods"] += 1

        owners = _owner_chain(pod, rs_to_dep)
        if owners:
            pod_ownership.append({"pod": pod_key, "owners": owners})

        containers = ((pod.get("spec") or {}).get("containers") or [])
        env_values: list[str] = []
        for container in containers:
            if not isinstance(container, dict):
                continue
            cname = str(container.get("name", "")).strip()
            image = str(container.get("image", "")).strip()
            if cname:
                pod_to_containers.append({"pod": pod_key, "container": cname, "image": image})

            for env in container.get("env") or []:
                if not isinstance(env, dict):
                    continue
                value = env.get("value")
                if isinstance(value, str) and value.strip():
                    env_values.append(value.lower())
            for arg in container.get("args") or []:
                if isinstance(arg, str) and arg.strip():
                    env_values.append(arg.lower())

        source_service = pod_to_service.get(pod_key, "")
        if not source_service or not env_values:
            continue
        joined = " ".join(env_values)
        for target_service, variants in svc_dns_map.items():
            if target_service == source_service:
                continue
            if any(variant in joined for variant in variants):
                service_to_service.append(
                    {
                        "from_service": source_service,
                        "to_service": target_service,
                        "evidence": "pod_env_or_args_reference",
                    }
                )

    deployment_to_pods: list[dict[str, Any]] = []
    for dep in deployments:
        dep_meta = dep.get("metadata") or {}
        dep_name = dep_meta.get("name", "")
        dep_ns = dep_meta.get("namespace", "")
        match_labels = (((dep.get("spec") or {}).get("selector") or {}).get("matchLabels") or {})
        if not match_labels:
            continue
        for pod in pods:
            pod_labels = ((pod.get("metadata") or {}).get("labels") or {})
            if all(pod_labels.get(k) == v for k, v in match_labels.items()):
                pod_meta = pod.get("metadata") or {}
                deployment_to_pods.append(
                    {
                        "deployment": f"{dep_ns}/{dep_name}",
                        "pod": f"{pod_meta.get('namespace', '')}/{pod_meta.get('name', '')}",
                    }
                )
        namespace_segmentation.setdefault(dep_ns, {"pods": 0, "services": 0, "deployments": 0, "ingresses": 0})
        namespace_segmentation[dep_ns]["deployments"] += 1

    ingress_backends: list[dict[str, Any]] = []
    for ing in ingresses:
        ing_meta = ing.get("metadata") or {}
        ing_ns = ing_meta.get("namespace", "")
        ing_name = ing_meta.get("name", "")
        rules = ((ing.get("spec") or {}).get("rules") or [])
        for rule in rules:
            host = rule.get("host", "")
            paths = (((rule.get("http") or {}).get("paths") or []))
            for path_rule in paths:
                backend = (path_rule.get("backend") or {}).get("service") or {}
                svc_name = backend.get("name", "")
                svc_port = (backend.get("port") or {}).get("number") or (backend.get("port") or {}).get("name")
                ingress_backends.append(
                    {
                        "ingress": f"{ing_ns}/{ing_name}",
                        "host": host,
                        "path": path_rule.get("path", "/"),
                        "service": f"{ing_ns}/{svc_name}" if svc_name else "",
                        "service_port": svc_port,
                    }
                )
                if svc_name:
                    service_to_service.append(
                        {
                            "from_service": f"{ing_ns}/{ing_name}",
                            "to_service": f"{ing_ns}/{svc_name}",
                            "evidence": "ingress_backend",
                        }
                    )
        namespace_segmentation.setdefault(ing_ns, {"pods": 0, "services": 0, "deployments": 0, "ingresses": 0})
        namespace_segmentation[ing_ns]["ingresses"] += 1

    for svc in services:
        svc_ns = str((svc.get("metadata") or {}).get("namespace", "")).strip()
        if svc_ns:
            namespace_segmentation.setdefault(svc_ns, {"pods": 0, "services": 0, "deployments": 0, "ingresses": 0})
            namespace_segmentation[svc_ns]["services"] += 1

    dedup_s2s: list[dict[str, Any]] = []
    seen_s2s: set[tuple[str, str, str]] = set()
    for rel in service_to_service:
        src = str(rel.get("from_service", "")).strip()
        dst = str(rel.get("to_service", "")).strip()
        ev = str(rel.get("evidence", "")).strip()
        key = (src, dst, ev)
        if not src or not dst or key in seen_s2s:
            continue
        seen_s2s.add(key)
        dedup_s2s.append({"from_service": src, "to_service": dst, "evidence": ev})

    topology = {
        "cluster_id": detected_cluster_id,
        "discovered_at": datetime.now(timezone.utc).isoformat(),
        "observability_services": observability_services,
        "inventory": {
            "namespaces": namespace_inventory,
            "services": service_inventory,
            "pods": pod_inventory,
        },
        "counts": {
            "nodes": len(nodes),
            "namespaces": len(namespaces),
            "pods": len(pods),
            "services": len(services),
            "endpoints": len(endpoints),
            "deployments": len(deployments),
            "ingresses": len(ingresses),
        },
        "namespace_segmentation": namespace_segmentation,
        "relations": {
            "service_to_pod": service_to_pods,
            "deployment_to_pod": deployment_to_pods,
            "ingress_backends": ingress_backends,
            "pod_to_container": pod_to_containers,
            "pod_ownership_chain": pod_ownership,
            "service_to_service": dedup_s2s,
        },
    }
    log.info(
        "Topology discovered namespaces=%s pods=%s services=%s deployments=%s ingresses=%s",
        topology["counts"]["namespaces"],
        topology["counts"]["pods"],
        topology["counts"]["services"],
        topology["counts"]["deployments"],
        topology["counts"]["ingresses"],
    )
    return topology


def _service_from_topology(topology: dict[str, Any], namespace: str, pod: str) -> str:
    relations = topology.get("relations") if isinstance(topology, dict) else {}
    service_to_pod = relations.get("service_to_pod") if isinstance(relations, dict) else []
    pod_key = f"{namespace}/{pod}"
    if not isinstance(service_to_pod, list):
        return ""
    for rel in service_to_pod:
        if not isinstance(rel, dict):
            continue
        if str(rel.get("pod", "")).strip() != pod_key:
            continue
        service = str(rel.get("service", "")).strip()
        if not service:
            continue
        parts = service.split("/", 1)
        return parts[1] if len(parts) == 2 and parts[1] else service
    return ""


def _resolve_service_for_pod(topology: dict[str, Any], namespace: str, pod: str, default_service: str) -> str:
    from_topology = _service_from_topology(topology, namespace, pod)
    if from_topology:
        return from_topology

    k8s_client = _init_k8s_client()
    if not k8s_client:
        return default_service
    session, base_url, timeout_seconds = k8s_client
    try:
        pod_obj = _k8s_api_get(session, base_url, f"/api/v1/namespaces/{namespace}/pods/{pod}", timeout_seconds)
    except (requests.RequestException, ValueError):
        return default_service

    labels = ((pod_obj.get("metadata") or {}).get("labels") or {})
    for key in ("app", "app.kubernetes.io/name", "k8s-app"):
        value = str(labels.get(key, "")).strip()
        if value:
            return value
    return default_service


def _select_namespace_and_service(topology: dict[str, Any], default_namespace: str, default_service: str) -> tuple[str, str]:
    inventory = topology.get("inventory") or {}
    namespaces = [str(x).strip() for x in (inventory.get("namespaces") or []) if str(x).strip()]
    services = inventory.get("services") or []

    selected_namespace = default_namespace
    preferred_namespaces = [part.strip() for part in _env("K8S_DISCOVERY_NAMESPACES", "").split(",") if part.strip()]
    if preferred_namespaces:
        for ns in preferred_namespaces:
            if ns in namespaces:
                selected_namespace = ns
                break
    elif namespaces:
        selected_namespace = namespaces[0]

    namespace_services = [
        str(item.get("name", "")).strip()
        for item in services
        if isinstance(item, dict) and str(item.get("namespace", "")).strip() == selected_namespace and str(item.get("name", "")).strip()
    ]
    namespace_services = sorted(set(namespace_services))

    configured_service = _env("AGENT_SERVICE_NAME", default_service)
    if configured_service in namespace_services:
        selected_service = configured_service
    elif "observer-agent" in namespace_services:
        selected_service = "observer-agent"
    elif namespace_services:
        selected_service = namespace_services[0]
    else:
        selected_service = default_service

    return selected_namespace, selected_service


def build_payload(configured_cluster_id: str, environment: str, prom_url: str) -> dict[str, Any]:
    now_dt = datetime.now(timezone.utc)
    now = now_dt.strftime("%Y%m%d%H%M%S")
    timestamp = now_dt.isoformat()
    default_service_name = _env("AGENT_SERVICE_NAME", "observer-agent")
    cpu_usage = _query_metric_with_fallback(
        prom_url,
        "cpu_usage",
        'sum(rate(container_cpu_usage_seconds_total{namespace!="",pod!="",container!=""}[2m])) by (namespace,pod)',
        ["avg(process_cpu_usage)", "sum(rate(process_cpu_time_ns_total[2m])) / 1e9"],
    )
    pod_cpu_rates = _query_pod_cpu_rates(prom_url)
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
    topology = _discover_topology()
    detected_cluster_id = str(topology.get("cluster_id", "")).strip() or configured_cluster_id
    selected_namespace, selected_service_name = _select_namespace_and_service(topology, environment, default_service_name)

    dominant_pod = ""
    if pod_cpu_rates:
        (selected_namespace, dominant_pod), dominant_cpu = max(pod_cpu_rates.items(), key=lambda item: item[1])
        selected_service_name = _resolve_service_for_pod(topology, selected_namespace, dominant_pod, selected_service_name)
        cpu_usage = float(dominant_cpu)

    pod_count = float(len(pod_cpu_rates)) if pod_cpu_rates else float((topology.get("counts") or {}).get("pods", 0) or 0)
    restart_count = float(pod_restarts)
    classification, root_cause = _classification_from_metrics(cpu_usage=cpu_usage, error_rate=error_rate)
    if not detected_cluster_id:
        detected_cluster_id = "unknown-cluster"

    log.info(
        "Kubernetes identity detected cluster_id=%s namespace_count=%s service_count=%s",
        detected_cluster_id,
        len((topology.get("inventory") or {}).get("namespaces") or []),
        len((topology.get("inventory") or {}).get("services") or []),
    )

    anomaly_score = _clamp((cpu_usage + (error_rate * 4.0)) / 2.0, 0.0, 1.0)
    risk_forecast = _clamp((cpu_usage * 0.6) + (error_rate * 0.4), 0.0, 1.0)
    confidence_score = 0.95 if prom_url else 0.6

    return {
        "cluster_id": detected_cluster_id,
        "environment": selected_namespace,
        "namespace": selected_namespace,
        "service": selected_service_name,
        "timestamp": timestamp,
        "metrics": {
            "cpu_usage": cpu_usage,
            "cluster_cpu_usage": float(sum(pod_cpu_rates.values())) if pod_cpu_rates else cpu_usage,
            "memory_usage": memory_usage,
            "pod_restarts": pod_restarts,
            "restart_count": restart_count,
            "pod_count": pod_count,
            "request_rate": request_rate,
            "error_rate": error_rate,
        },
        "topology": topology,
        "incidents": [
            {
                "incident_id": f"agent-{detected_cluster_id}-{selected_service_name}-{now}",
                "service_name": selected_service_name,
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
    push_timeout_seconds = _float(_env("PUSH_TIMEOUT_SECONDS", "25"), 25.0)
    run_once = _env("RUN_ONCE", "false").lower() in {"1", "true", "yes", "on"}

    if not central_url or not agent_token:
        logging.error("Missing required env vars: CENTRAL_URL, AGENT_TOKEN")
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
                timeout=push_timeout_seconds,
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

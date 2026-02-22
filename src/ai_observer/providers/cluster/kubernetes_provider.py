from __future__ import annotations

from typing import Any

import requests


class KubernetesWiringProvider:
    def __init__(self):
        self.api = "https://kubernetes.default.svc"
        self.token_path = "/var/run/secrets/kubernetes.io/serviceaccount/token"
        self.ca_path = "/var/run/secrets/kubernetes.io/serviceaccount/ca.crt"

    def _headers(self) -> dict[str, str]:
        token = ""
        try:
            with open(self.token_path, "r", encoding="utf-8") as f:
                token = f.read().strip()
        except Exception:
            token = ""
        headers = {"Accept": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return headers

    def _get(self, path: str) -> dict[str, Any]:
        resp = requests.get(
            f"{self.api}{path}",
            headers=self._headers(),
            verify=self.ca_path,
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json()

    @staticmethod
    def _labels_match(selector: dict[str, str], labels: dict[str, str]) -> bool:
        if not selector:
            return False
        for key, val in selector.items():
            if labels.get(key) != val:
                return False
        return True

    def collect(self, namespace: str) -> dict[str, Any]:
        services_obj = self._get(f"/api/v1/namespaces/{namespace}/services")
        pods_obj = self._get(f"/api/v1/namespaces/{namespace}/pods")
        endpoints_obj = self._get(f"/api/v1/namespaces/{namespace}/endpoints")

        services = services_obj.get("items", [])
        pods = pods_obj.get("items", [])
        endpoints = endpoints_obj.get("items", [])

        pod_labels: dict[str, dict[str, str]] = {}
        for pod in pods:
            name = pod.get("metadata", {}).get("name")
            if name:
                pod_labels[name] = pod.get("metadata", {}).get("labels", {}) or {}

        nodes: list[dict[str, Any]] = []
        edges: list[dict[str, Any]] = []

        for svc in services:
            svc_name = svc.get("metadata", {}).get("name")
            if not svc_name:
                continue
            nodes.append({"id": svc_name, "kind": "service", "status": "healthy"})

        for pod in pods:
            pod_name = pod.get("metadata", {}).get("name")
            if not pod_name:
                continue
            phase = (pod.get("status", {}).get("phase") or "Unknown").lower()
            status = "healthy" if phase == "running" else "warning"
            nodes.append({"id": pod_name, "kind": "pod", "status": status})

        for svc in services:
            svc_name = svc.get("metadata", {}).get("name")
            selector = svc.get("spec", {}).get("selector") or {}
            if not svc_name:
                continue

            for pod_name, labels in pod_labels.items():
                if self._labels_match(selector, labels):
                    edges.append({"from": svc_name, "to": pod_name, "type": "selector"})

        for ep in endpoints:
            ep_name = ep.get("metadata", {}).get("name")
            for subset in ep.get("subsets", []) or []:
                for addr in subset.get("addresses", []) or []:
                    target_ref = addr.get("targetRef", {})
                    if target_ref.get("kind") == "Pod" and target_ref.get("name"):
                        edges.append({"from": ep_name, "to": target_ref.get("name"), "type": "endpoint"})

        return {
            "namespace": namespace,
            "nodes": nodes,
            "edges": edges,
            "service_count": sum(1 for n in nodes if n.get("kind") == "service"),
            "pod_count": sum(1 for n in nodes if n.get("kind") == "pod"),
        }

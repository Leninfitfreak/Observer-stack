from __future__ import annotations

from collections import deque
from datetime import datetime, timezone
from typing import Any


class DependencyGraphEngine:
    def __init__(self):
        self._cache: dict[str, dict[str, Any]] = {}

    def build(self, namespace: str, cluster_wiring: dict[str, Any]) -> dict[str, Any]:
        key = f"{namespace}"
        nodes = cluster_wiring.get("nodes", []) or []
        edges = cluster_wiring.get("edges", []) or []
        services = sorted({str(n.get("id")) for n in nodes if n.get("kind") == "service"})
        adjacency: dict[str, list[str]] = {svc: [] for svc in services}
        reverse: dict[str, list[str]] = {svc: [] for svc in services}
        service_to_pods: dict[str, list[str]] = {svc: [] for svc in services}

        for edge in edges:
            src = str(edge.get("from", "")).strip()
            dst = str(edge.get("to", "")).strip()
            if not src or not dst:
                continue
            if src in adjacency and dst in adjacency and dst not in adjacency[src]:
                adjacency[src].append(dst)
                reverse[dst].append(src)
            if src in service_to_pods:
                service_to_pods[src].append(dst)

        for svc, pods in service_to_pods.items():
            service_to_pods[svc] = sorted(set(pods))

        graph = {
            "namespace": namespace,
            "services": services,
            "adjacency": adjacency,
            "reverse_adjacency": reverse,
            "service_to_pods": service_to_pods,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        self._cache[key] = graph
        return graph

    @staticmethod
    def propagation_path(graph: dict[str, Any], origin: str, targets: list[str]) -> list[str]:
        services = set(graph.get("services", []))
        if origin not in services:
            return []
        target_set = {t for t in targets if t in services}
        if not target_set:
            return [origin]
        adjacency = graph.get("adjacency", {}) or {}
        q: deque[tuple[str, list[str]]] = deque([(origin, [origin])])
        visited = {origin}
        while q:
            cur, path = q.popleft()
            if cur in target_set:
                return path
            for nxt in adjacency.get(cur, []):
                if nxt not in visited:
                    visited.add(nxt)
                    q.append((nxt, path + [nxt]))
        return [origin]

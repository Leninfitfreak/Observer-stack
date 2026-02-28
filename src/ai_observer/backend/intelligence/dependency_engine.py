from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


class DependencyEngine:
    def __init__(self):
        self._graphs: dict[str, dict[str, Any]] = {}

    def build_from_topology(self, cluster_id: str, namespace: str, topology: dict[str, Any]) -> dict[str, Any]:
        relations = topology.get("relations", {}) if isinstance(topology, dict) else {}
        service_to_pod = relations.get("service_to_pod", []) if isinstance(relations, dict) else []
        ingress_backends = relations.get("ingress_backends", []) if isinstance(relations, dict) else []
        service_to_service = relations.get("service_to_service", []) if isinstance(relations, dict) else []

        services: set[str] = set()
        upstream: dict[str, set[str]] = {}
        downstream: dict[str, set[str]] = {}
        service_to_pods: dict[str, set[str]] = {}

        for rel in service_to_pod:
            if not isinstance(rel, dict):
                continue
            svc = str(rel.get("service", "")).strip()
            pod = str(rel.get("pod", "")).strip()
            if not svc:
                continue
            services.add(svc)
            service_to_pods.setdefault(svc, set())
            if pod:
                service_to_pods[svc].add(pod)

        for rel in ingress_backends:
            if not isinstance(rel, dict):
                continue
            svc = str(rel.get("service", "")).strip()
            ingress = str(rel.get("ingress", "")).strip()
            if not svc:
                continue
            services.add(svc)
            upstream.setdefault(svc, set())
            if ingress:
                upstream[svc].add(ingress)

        for rel in service_to_service:
            if not isinstance(rel, dict):
                continue
            src = str(rel.get("from_service", "")).strip()
            dst = str(rel.get("to_service", "")).strip()
            if not src or not dst:
                continue
            services.add(src)
            services.add(dst)
            downstream.setdefault(src, set()).add(dst)
            upstream.setdefault(dst, set()).add(src)

        graph = {
            "cluster_id": cluster_id,
            "namespace": namespace,
            "services": sorted(services),
            "upstream": {k: sorted(v) for k, v in upstream.items()},
            "downstream": {k: sorted(v) for k, v in downstream.items()},
            "service_to_pods": {k: sorted(v) for k, v in service_to_pods.items()},
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }

        key = f"{cluster_id}:{namespace}"
        self._graphs[key] = graph
        return graph

    def get_graph(self, cluster_id: str, namespace: str) -> dict[str, Any]:
        return self._graphs.get(f"{cluster_id}:{namespace}", {})

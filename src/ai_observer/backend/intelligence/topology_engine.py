from __future__ import annotations

from typing import Any


class TopologyEngine:
    @staticmethod
    def infer_origin_service(topology: dict[str, Any], preferred_service: str = "") -> str:
        if not isinstance(topology, dict):
            return preferred_service or "unknown"

        relations = topology.get("relations", {}) if isinstance(topology.get("relations"), dict) else {}
        ranked = topology.get("ranked_services", [])
        if isinstance(ranked, list) and ranked:
            first = ranked[0]
            if isinstance(first, dict):
                candidate = str(first.get("service", "")).strip()
                if candidate:
                    return candidate

        service_rel = relations.get("service_to_pod", [])
        if isinstance(service_rel, list):
            for item in service_rel:
                if not isinstance(item, dict):
                    continue
                svc = str(item.get("service", "")).strip()
                if svc:
                    return svc

        ingress_rel = relations.get("ingress_backends", [])
        if isinstance(ingress_rel, list):
            for item in ingress_rel:
                if not isinstance(item, dict):
                    continue
                svc = str(item.get("service", "")).strip()
                if svc:
                    return svc

        return preferred_service or "unknown"

    @staticmethod
    def infer_impacted_services(topology: dict[str, Any]) -> list[str]:
        if not isinstance(topology, dict):
            return []
        relations = topology.get("relations", {}) if isinstance(topology.get("relations"), dict) else {}
        service_rel = relations.get("service_to_pod", [])
        service_edges = relations.get("service_to_service", [])
        impacted: set[str] = set()
        if isinstance(service_rel, list):
            for item in service_rel:
                if not isinstance(item, dict):
                    continue
                svc = str(item.get("service", "")).strip()
                if svc:
                    impacted.add(svc)
        if isinstance(service_edges, list):
            for item in service_edges:
                if not isinstance(item, dict):
                    continue
                src = str(item.get("from_service", "")).strip()
                dst = str(item.get("to_service", "")).strip()
                if src:
                    impacted.add(src)
                if dst:
                    impacted.add(dst)
        return sorted(impacted)

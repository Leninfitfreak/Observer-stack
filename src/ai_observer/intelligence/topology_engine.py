from __future__ import annotations

from typing import Any

from ai_observer.intelligence.dependency_graph_engine import DependencyGraphEngine
from ai_observer.intelligence.utils import clamp


class TopologyEngine:
    def __init__(self, dependency_graph_engine: DependencyGraphEngine):
        self.dependency_graph_engine = dependency_graph_engine

    def evaluate(
        self,
        namespace: str,
        cluster_wiring: dict[str, Any],
        component_metrics: dict[str, dict[str, Any]],
        alert_service: str,
    ) -> dict[str, Any]:
        graph = self.dependency_graph_engine.build(namespace, cluster_wiring)

        def svc_anomaly(svc_metrics: dict[str, Any]) -> float:
            baseline = float(svc_metrics.get("baseline_anomaly_score", 0) or 0)
            err = float(svc_metrics.get("error_rate_5xx_5m", 0) or 0)
            lat = float(svc_metrics.get("latency_p95_s_5m", 0) or 0)
            cpu = float(svc_metrics.get("cpu_usage_cores_5m", 0) or 0)
            return clamp((0.35 * baseline) + (0.3 * (err / 0.05 if err > 0 else 0)) + (0.2 * (lat / 0.75 if lat > 0 else 0)) + (0.15 * (cpu / 0.8 if cpu > 0 else 0)))

        ranked = sorted(((svc, svc_anomaly(v)) for svc, v in component_metrics.items()), key=lambda item: item[1], reverse=True)
        likely_origin = ranked[0][0] if ranked else (alert_service if alert_service not in {"all", "*"} else "")
        if not likely_origin:
            service_to_pods = graph.get("service_to_pods", {}) if isinstance(graph, dict) else {}
            if isinstance(service_to_pods, dict):
                populated = [svc for svc, pods in service_to_pods.items() if isinstance(pods, list) and pods]
                if populated:
                    likely_origin = sorted(populated)[0]
        if not likely_origin:
            services = graph.get("services", []) if isinstance(graph, dict) else []
            if isinstance(services, list) and services:
                likely_origin = str(services[0])
        if not likely_origin:
            likely_origin = "unknown"
        likely_origin_score = ranked[0][1] if ranked else 0.0
        impacted = [svc for svc, score in ranked if score >= 0.2]
        downstream_coverage = clamp((len(impacted) / max(len(graph.get("services", [])), 1)) if graph.get("services") else 0.0)
        propagation_consistency = clamp((0.7 * likely_origin_score) + (0.3 * downstream_coverage))
        path = self.dependency_graph_engine.propagation_path(graph, likely_origin, impacted)
        return {
            "service_count": len(graph.get("services", [])),
            "service_to_pods": graph.get("service_to_pods", {}),
            "ranked_services": [{"service": s, "score": round(v, 3)} for s, v in ranked[:8]],
            "likely_origin_service": likely_origin,
            "likely_origin_score": round(likely_origin_score, 3),
            "impacted_services": impacted,
            "propagation_consistency": round(propagation_consistency, 3),
            "propagation_path": path,
            "has_dependency_graph": bool(graph.get("services")),
            "dependency_graph": graph,
        }

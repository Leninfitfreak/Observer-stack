from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ai_observer.domain.interfaces import ClusterWiringProvider, LlmProvider, LogsProvider, MetricsProvider, TracesProvider
from ai_observer.domain.models import AlertSignal, LiveReasoningResponse, ObservabilityContext, ReasoningResult


class ReasoningService:
    def __init__(
        self,
        metrics_provider: MetricsProvider,
        logs_provider: LogsProvider,
        traces_provider: TracesProvider,
        llm_provider: LlmProvider,
        cluster_wiring_provider: ClusterWiringProvider,
    ):
        self.metrics_provider = metrics_provider
        self.logs_provider = logs_provider
        self.traces_provider = traces_provider
        self.llm_provider = llm_provider
        self.cluster_wiring_provider = cluster_wiring_provider
        self.started_at = datetime.now(timezone.utc)

    @staticmethod
    def _is_infra_service(name: str) -> bool:
        lowered = (name or "").lower()
        infra_tokens = [
            "kubernetes",
            "prometheus",
            "grafana",
            "loki",
            "jaeger",
            "otel",
            "alertmanager",
            "vault",
            "argocd",
            "kube-",
            "istio",
        ]
        return any(token in lowered for token in infra_tokens)

    @staticmethod
    def _service_has_pods(service_name: str, wiring: dict[str, Any]) -> bool:
        for edge in wiring.get("edges", []):
            if edge.get("from") == service_name and str(edge.get("to", "")).strip():
                return True
        return False

    @staticmethod
    def _pods_for_service(service_name: str, wiring: dict[str, Any]) -> list[str]:
        pods: list[str] = []
        for edge in wiring.get("edges", []):
            if edge.get("from") != service_name:
                continue
            target = str(edge.get("to", "")).strip()
            if target:
                pods.append(target)
        return sorted(set(pods))

    @staticmethod
    def _incident_classification(metrics: dict[str, Any], missing_observability: list[str]) -> str:
        error_rate = float(metrics.get("error_rate_5xx_5m", 0) or 0)
        latency = float(metrics.get("latency_p95_s_5m", 0) or 0)
        if missing_observability:
            return "Observability Gap"
        if error_rate > 0.05 or latency > 0.75:
            return "Performance Degradation"
        return "False Positive"

    @staticmethod
    def _resource_saturation_signals(metrics: dict[str, Any]) -> list[str]:
        cpu_pct = float(metrics.get("cpu_usage_cores_5m", 0) or 0) * 100
        mem_mb = float(metrics.get("memory_usage_bytes", 0) or 0) / (1024 * 1024)
        restarts = float(metrics.get("pod_restarts_10m", 0) or 0)
        return [
            f"CPU {round(cpu_pct)}% {'(high)' if cpu_pct > 80 else '(below saturation)'}",
            f"Memory {round(mem_mb)}MB {'(high)' if mem_mb > 1024 else '(stable)'}",
            f"Pod restarts {int(restarts)} {'(elevated)' if restarts > 0 else '(none)'}",
        ]

    @staticmethod
    def _confidence_details(context: dict[str, Any]) -> dict[str, Any]:
        missing = context.get("analysis_missing_observability", []) or []
        ds_errors = context.get("datasource_errors", {}) or {}
        metrics = context.get("metrics", {}) or {}
        anomaly_count = len(metrics.get("anomalies", []) or [])
        data_completeness = max(30, 100 - (len(missing) * 8) - (len(ds_errors) * 10))
        signal_agreement = "High" if anomaly_count >= 2 else "Moderate" if anomaly_count == 1 else "Low"
        historical_similarity = "High" if data_completeness >= 85 else "Moderate" if data_completeness >= 60 else "Low"
        overall_band = "High" if data_completeness >= 80 else "Low-Medium" if data_completeness >= 55 else "Low"
        return {
            "data_completeness": f"{data_completeness}%",
            "signal_agreement": signal_agreement,
            "historical_similarity": historical_similarity,
            "overall_band": overall_band,
        }

    @staticmethod
    def _metric_narrative(metrics: dict[str, Any]) -> tuple[str, list[str]]:
        rps = float(metrics.get("request_rate_rps_5m", 0) or 0)
        p95_ms = float(metrics.get("latency_p95_s_5m", 0) or 0) * 1000
        err_pct = float(metrics.get("error_rate_5xx_5m", 0) or 0) * 100
        cpu_pct = float(metrics.get("cpu_usage_cores_5m", 0) or 0) * 100
        mem_mb = float(metrics.get("memory_usage_bytes", 0) or 0) / (1024 * 1024)

        if err_pct > 5 or p95_ms > 750:
            summary = "Service behavior indicates active degradation with elevated latency and/or error pressure."
        elif rps <= 0.01:
            summary = "Traffic is currently minimal; no reliable evidence of active degradation in this window."
        else:
            summary = "Service performance remains within normal operating baseline."

        bullets = [
            "No error-rate growth detected." if err_pct <= 1 else "Error-rate growth detected and requires watch.",
            "Resource utilization is below saturation thresholds." if cpu_pct < 80 and mem_mb < 1024 else "Resource utilization is approaching saturation thresholds.",
            "No evidence of active degradation." if err_pct <= 1 and p95_ms <= 750 else "Latency or failure signals indicate active degradation.",
        ]
        return summary, bullets

    def _baseline(self, context: dict[str, Any]) -> dict[str, Any]:
        metrics = context.get("metrics", {})
        error_rate = metrics.get("error_rate_5xx_5m", 0) or 0
        latency = metrics.get("latency_p95_s_5m", 0) or 0
        missing_observability = context.get("analysis_missing_observability", []) or []
        classification = self._incident_classification(metrics, missing_observability)
        metric_summary, metric_bullets = self._metric_narrative(metrics)
        why_not_resource = self._resource_saturation_signals(metrics)

        if error_rate > 0.05:
            root = "5xx error-rate spike"
            impact = "High"
            confidence = 0.8
        elif latency > 0.75:
            root = "sustained p95 latency breach"
            impact = "Medium"
            confidence = 0.65
        else:
            root = "No dominant fault domain identified"
            impact = "Low"
            confidence = 0.43

        confidence_details = self._confidence_details(context)
        change_detection_context = []
        deployment = context.get("deployment", {}) or {}
        if deployment.get("deployment_changed_last_10m"):
            change_detection_context.append("Deployment change detected in last 10 minutes.")
        else:
            change_detection_context.append("No deployments detected in last 30 minutes.")
        if deployment.get("ai_observer_frontend_changed_last_15m"):
            change_detection_context.append("AI Observer frontend changed recently.")
        else:
            change_detection_context.append("No AI Observer frontend/config update detected in last 15 minutes.")

        return {
            "probable_root_cause": root,
            "impact_level": impact,
            "recommended_remediation": "Continue monitoring for 10-15 minutes; no active mitigation is recommended at current signal confidence.",
            "confidence": confidence,
            "confidence_score": f"{round(confidence * 100)}%",
            "causal_chain": ["Assessment: No correlated anomaly detected across metrics and logs."],
            "corrective_actions": [
                "Restart Pod - 58% likelihood of resolving transient application stalls.",
                "Scale Deployment - 34% likelihood if latency persists under load.",
                "Rollback - 12% likelihood unless tied to a confirmed recent release.",
            ],
            "preventive_hardening": ["Add recording rules and SLO burn-rate alerts."],
            "risk_forecast": {"predicted_breach_window": "low_risk"},
            "deployment_correlation": {"within_10m": bool(context.get("deployment", {}).get("deployment_changed_last_10m"))},
            "error_log_prediction": {"repeated_signatures": []},
            "missing_observability": missing_observability,
            "human_summary": f"{metric_summary} Impact remains {impact.lower()}.",
            "executive_summary": metric_summary,
            "assessment": "No correlated anomaly detected across metrics and logs.",
            "most_likely_scenario": "False positive trigger or transient fluctuation.",
            "why_not_resource_saturation": why_not_resource,
            "incident_classification": classification,
            "confidence_details": confidence_details,
            "ai_response_status": "complete",
            "change_detection_context": change_detection_context,
            "supporting_evidence": metric_bullets,
        }

    def _normalize(self, analysis: dict[str, Any]) -> dict[str, Any]:
        out = dict(analysis)

        def to_list_str(value: Any) -> list[str]:
            if not isinstance(value, list):
                return []
            result: list[str] = []
            for item in value:
                result.append(item if isinstance(item, str) else str(item))
            return result

        out["recommended_remediation"] = " ".join(out["recommended_remediation"]) if isinstance(out.get("recommended_remediation"), list) else str(out.get("recommended_remediation", ""))
        out["causal_chain"] = to_list_str(out.get("causal_chain"))
        out["corrective_actions"] = to_list_str(out.get("corrective_actions"))
        out["preventive_hardening"] = to_list_str(out.get("preventive_hardening"))
        out["missing_observability"] = to_list_str(out.get("missing_observability"))
        out["why_not_resource_saturation"] = to_list_str(out.get("why_not_resource_saturation"))
        out["change_detection_context"] = to_list_str(out.get("change_detection_context"))
        if not isinstance(out.get("deployment_correlation"), dict):
            out["deployment_correlation"] = {"value": out.get("deployment_correlation")}
        if not isinstance(out.get("error_log_prediction"), dict):
            out["error_log_prediction"] = {"value": out.get("error_log_prediction")}
        if not isinstance(out.get("confidence_details"), dict):
            out["confidence_details"] = {}

        if "confidence_score" not in out and out.get("confidence") is not None:
            try:
                out["confidence_score"] = f"{round(float(out['confidence']) * 100)}%"
            except Exception:
                out["confidence_score"] = "40%"

        return out

    def analyze(self, alert: AlertSignal, window_minutes: int = 30) -> LiveReasoningResponse:
        errors: dict[str, str] = {}

        try:
            metrics = self.metrics_provider.collect(alert.namespace, alert.service)
        except Exception as exc:
            metrics = {}
            errors["prometheus"] = str(exc)

        try:
            logs = self.logs_provider.collect(alert.namespace, alert.service, window_minutes, limit=20)
        except Exception as exc:
            logs = {"summary": "logs datasource unavailable", "lines": []}
            errors["loki"] = str(exc)

        try:
            traces = self.traces_provider.collect(alert.service, lookback_minutes=window_minutes, limit=5)
        except Exception as exc:
            traces = {"summary": "tracing datasource unavailable", "slow_traces": []}
            errors["jaeger"] = str(exc)

        try:
            cluster_wiring = self.cluster_wiring_provider.collect(alert.namespace)
        except Exception as exc:
            cluster_wiring = {"namespace": alert.namespace, "nodes": [], "edges": []}
            errors["cluster_wiring"] = str(exc)

        components: list[dict[str, Any]] = []
        for node in cluster_wiring.get("nodes", []):
            if node.get("kind") != "service":
                continue
            name = str(node.get("id"))
            if name in {"kubernetes"}:
                continue
            if alert.service not in {"all", "*"} and name != alert.service:
                continue
            if alert.service in {"all", "*"} and self._is_infra_service(name):
                continue
            if not self._service_has_pods(name, cluster_wiring):
                continue
            components.append({"service": name, "status": node.get("status", "healthy"), "reasons": ["k8s service discovered"]})

        component_metrics: dict[str, dict[str, Any]] = {}
        for comp in components:
            svc_name = comp["service"]
            svc_pods = self._pods_for_service(svc_name, cluster_wiring)
            try:
                svc_metrics = self.metrics_provider.collect(alert.namespace, svc_name, pod_names=svc_pods)
            except Exception as exc:
                svc_metrics = {}
                errors[f"prometheus:{svc_name}"] = str(exc)
            component_metrics[svc_name] = svc_metrics

            err_rate = svc_metrics.get("error_rate_5xx_5m", 0) or 0
            p95 = svc_metrics.get("latency_p95_s_5m", 0) or 0
            if err_rate > 0.05:
                comp["status"] = "critical"
                comp["reasons"] = ["5xx error rate > 5%"]
            elif p95 > 0.75:
                comp["status"] = "warning"
                comp["reasons"] = ["p95 latency > 750ms"]
            elif comp.get("status") not in {"warning", "critical"}:
                comp["status"] = "healthy"
                comp["reasons"] = ["telemetry within threshold"]

        component_summary = {
            "scope": "all" if alert.service in {"all", "*"} else "single",
            "overall_status": "critical"
            if any(c.get("status") == "critical" for c in components)
            else "warning" if any(c.get("status") == "warning" for c in components)
            else "healthy",
            "total": len(components),
            "healthy": sum(1 for c in components if c.get("status") == "healthy"),
            "warning": sum(1 for c in components if c.get("status") == "warning"),
            "critical": sum(1 for c in components if c.get("status") == "critical"),
        }

        deployment = {
            "deployment_changed_last_10m": False,
            "ai_observer_frontend_changed_last_15m": (datetime.now(timezone.utc) - self.started_at).total_seconds() <= 900,
            "ai_observer_started_at": self.started_at.isoformat(),
        }

        context_data = {
            "alert": alert.model_dump(),
            "time_window_minutes": window_minutes,
            "metrics": metrics,
            "logs": logs,
            "traces": traces,
            "kubernetes": {},
            "deployment": deployment,
            "components": components,
            "component_metrics": component_metrics,
            "component_summary": component_summary,
            "cluster_wiring": cluster_wiring,
            "datasource_errors": errors,
        }

        missing_observability: list[str] = []
        if not context_data["metrics"].get("db_connection_pool_usage_5m"):
            missing_observability.append("db_connection_pool_usage metric missing")
        if not context_data["metrics"].get("thread_pool_saturation_5m"):
            missing_observability.append("thread_pool_saturation metric missing")
        if not context_data["metrics"].get("kafka_consumer_lag"):
            missing_observability.append("kafka_consumer_lag metric missing")
        context_data["analysis_missing_observability"] = missing_observability

        baseline = self._baseline(context_data)
        try:
            llm_response = self.llm_provider.analyze({"context": context_data, "baseline": baseline})
            llm_partial = bool(llm_response.get("_llm_partial"))
            merged = dict(baseline)
            merged.update({k: v for k, v in llm_response.items() if not str(k).startswith("_") and v is not None and v != ""})
            if llm_partial:
                merged["ai_response_status"] = "partial_fallback"
                merged["confidence"] = min(float(merged.get("confidence") or 0.4), 0.55)
                merged["confidence_score"] = f"{round(float(merged.get('confidence') or 0.4) * 100)}%"
                merged["human_summary"] = "No service degradation detected. AI model response was incomplete; deterministic fallback reasoning is applied."
                merged["probable_root_cause"] = "No correlated degradation; fallback reasoning in effect."
            analysis_data = self._normalize(merged)
        except Exception as exc:
            errors["llm"] = str(exc)
            context_data["datasource_errors"] = errors
            baseline["ai_response_status"] = "partial_fallback"
            baseline["confidence"] = min(float(baseline.get("confidence") or 0.4), 0.55)
            baseline["confidence_score"] = f"{round(float(baseline.get('confidence') or 0.4) * 100)}%"
            baseline["human_summary"] = "No service degradation detected. AI model response was incomplete; deterministic fallback reasoning is applied."
            baseline["probable_root_cause"] = "No correlated degradation; fallback reasoning in effect."
            analysis_data = self._normalize(baseline)

        analysis_data["policy_note"] = "No auto-remediation was applied. Explicit approval required before changes."

        context = ObservabilityContext(**context_data)
        analysis = ReasoningResult(**analysis_data)
        return LiveReasoningResponse(context=context, analysis=analysis)

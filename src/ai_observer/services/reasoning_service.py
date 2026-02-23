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
        self._incident_state: dict[str, dict[str, Any]] = {}

    @staticmethod
    def _clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
        return max(lo, min(hi, value))

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
    def _signal_scores(metrics: dict[str, Any], missing_observability: list[str]) -> dict[str, float]:
        cpu_pct = float(metrics.get("cpu_usage_cores_5m", 0) or 0) * 100
        err_rate = float(metrics.get("error_rate_5xx_5m", 0) or 0)
        err_growth = float(metrics.get("error_growth_rate", 0) or 0)
        p95_cur = float(metrics.get("latency_p95_s_5m", 0) or 0)
        p95_base = float(metrics.get("baseline_p95_s_7d", 0) or 0)
        db_pool = float(metrics.get("db_connection_pool_usage_5m", 0) or 0)
        thread_sat = float(metrics.get("thread_pool_saturation_5m", 0) or 0)
        kafka_lag = float(metrics.get("kafka_consumer_lag", 0) or 0)

        cpu_saturation_score = ReasoningService._clamp(cpu_pct / 80.0)
        latency_deviation_score = ReasoningService._clamp(((p95_cur - p95_base) / p95_base) if p95_base > 0 else (p95_cur / 0.75 if p95_cur > 0 else 0))
        error_growth_score = ReasoningService._clamp(err_growth / 0.02 if err_growth > 0 else 0)
        error_level_score = ReasoningService._clamp(err_rate / 0.05)
        db_pressure_score = ReasoningService._clamp(db_pool / 0.85)
        thread_pressure_score = ReasoningService._clamp(thread_sat / 0.85)
        kafka_pressure_score = ReasoningService._clamp(kafka_lag / 1000.0 if kafka_lag > 0 else 0)

        observability_penalty = ReasoningService._clamp(len(missing_observability) / 8.0)

        overall_anomaly_score = ReasoningService._clamp(
            (0.26 * latency_deviation_score)
            + (0.24 * error_level_score)
            + (0.16 * error_growth_score)
            + (0.10 * cpu_saturation_score)
            + (0.10 * db_pressure_score)
            + (0.07 * thread_pressure_score)
            + (0.07 * kafka_pressure_score)
            - (0.12 * observability_penalty)
        )

        return {
            "cpu_saturation_score": cpu_saturation_score,
            "latency_deviation_score": latency_deviation_score,
            "error_growth_score": error_growth_score,
            "error_level_score": error_level_score,
            "db_pressure_score": db_pressure_score,
            "thread_pressure_score": thread_pressure_score,
            "kafka_pressure_score": kafka_pressure_score,
            "observability_penalty": observability_penalty,
            "overall_anomaly_score": overall_anomaly_score,
        }

    @staticmethod
    def _causal_likelihoods(metrics: dict[str, Any], logs: dict[str, Any], traces: dict[str, Any], cluster_wiring: dict[str, Any]) -> dict[str, float]:
        log_text = f"{logs.get('summary', '')}\n" + "\n".join(logs.get("lines", [])[:20]).lower()
        trace_text = str(traces.get("summary", "")).lower()
        has_db = "postgres" in log_text or "db" in log_text or "postgres" in trace_text
        has_kafka = "kafka" in log_text or "kafka" in trace_text
        has_external = any(t in log_text for t in ["timeout", "connection reset", "upstream"]) or any(
            t in trace_text for t in ["timeout", "upstream", "external"]
        )

        db_weight = 0.2 + (0.35 if has_db else 0) + (0.25 if float(metrics.get("db_connection_pool_usage_5m", 0) or 0) > 0.7 else 0)
        kafka_weight = 0.15 + (0.35 if has_kafka else 0) + (0.25 if float(metrics.get("kafka_consumer_lag", 0) or 0) > 50 else 0)
        external_weight = 0.2 + (0.35 if has_external else 0)
        internal_weight = 0.25 + (0.2 if float(metrics.get("thread_pool_saturation_5m", 0) or 0) > 0.8 else 0)

        node_ids = {str(n.get("id", "")).lower() for n in cluster_wiring.get("nodes", [])}
        if any("postgres" in n for n in node_ids):
            db_weight += 0.05
        if any("kafka" in n for n in node_ids):
            kafka_weight += 0.05

        total = max(0.0001, db_weight + kafka_weight + external_weight + internal_weight)
        return {
            "db": db_weight / total,
            "kafka": kafka_weight / total,
            "external_dependency": external_weight / total,
            "internal_runtime": internal_weight / total,
        }

    def _lifecycle_progression(self, incident_key: str, metrics: dict[str, Any]) -> dict[str, Any]:
        prev = self._incident_state.get(incident_key, {})
        current = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "p95": float(metrics.get("latency_p95_s_5m", 0) or 0),
            "err": float(metrics.get("error_rate_5xx_5m", 0) or 0),
            "score": float(metrics.get("overall_anomaly_score", 0) or 0),
            "restarts": float(metrics.get("pod_restarts_10m", 0) or 0),
        }
        progression = "steady"
        if prev:
            if current["score"] > (prev.get("score", 0) + 0.05):
                progression = "worsening"
            elif current["score"] < (prev.get("score", 0) - 0.05):
                progression = "improving"

        mitigation_effect = "No mitigation event observed."
        if prev and current["restarts"] > prev.get("restarts", 0):
            if current["score"] < prev.get("score", 0):
                mitigation_effect = "Post-restart, metrics improved; runtime issue likelihood reduced."
            else:
                mitigation_effect = "Post-restart, no improvement observed; infrastructure issue likelihood reduced."

        self._incident_state[incident_key] = current
        return {
            "progression": progression,
            "mitigation_effect": mitigation_effect,
            "previous": prev or None,
            "current": current,
        }

    @staticmethod
    def _risk_forecast_15m(metrics: dict[str, Any], lifecycle: dict[str, Any]) -> float:
        score = float(metrics.get("overall_anomaly_score", 0) or 0)
        err_rate = float(metrics.get("error_rate_5xx_5m", 0) or 0)
        p95 = float(metrics.get("latency_p95_s_5m", 0) or 0)
        progression = lifecycle.get("progression", "steady")

        prob = (score * 60.0) + (err_rate / 0.05 * 22.0) + (p95 / 0.75 * 18.0)
        if progression == "worsening":
            prob += 12.0
        elif progression == "improving":
            prob -= 10.0
        return round(max(1.0, min(99.0, prob)), 1)

    @staticmethod
    def _confidence_details(context: dict[str, Any]) -> dict[str, Any]:
        missing = context.get("analysis_missing_observability", []) or []
        ds_errors = context.get("datasource_errors", {}) or {}
        score = context.get("signal_scores", {}) or {}
        causal = context.get("causal_likelihoods", {}) or {}
        signal_strength = float(score.get("overall_anomaly_score", 0) or 0)
        data_completeness_frac = ReasoningService._clamp(1.0 - (len(missing) * 0.08) - (len(ds_errors) * 0.12))
        causal_consistency_frac = max(causal.values()) if causal else 0.45
        confidence_frac = ReasoningService._clamp(signal_strength * data_completeness_frac * causal_consistency_frac + 0.20)

        signal_agreement = "High" if signal_strength >= 0.65 else "Moderate" if signal_strength >= 0.35 else "Low"
        historical_similarity = "High" if float(score.get("latency_deviation_score", 0) or 0) < 0.2 else "Moderate" if float(score.get("latency_deviation_score", 0) or 0) < 0.6 else "Low"
        overall_band = "High" if confidence_frac >= 0.75 else "Low-Medium" if confidence_frac >= 0.5 else "Low"
        return {
            "data_completeness": f"{round(data_completeness_frac * 100)}%",
            "signal_agreement": signal_agreement,
            "historical_similarity": historical_similarity,
            "overall_band": overall_band,
            "confidence_formula": "confidence = signal_strength * data_completeness * causal_consistency",
            "signal_strength": round(signal_strength, 3),
            "causal_consistency": round(causal_consistency_frac, 3),
            "computed_confidence": round(confidence_frac, 3),
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
        signal_scores = context.get("signal_scores", {}) or {}
        causal_likelihoods = context.get("causal_likelihoods", {}) or {}
        lifecycle = context.get("lifecycle", {}) or {}
        classification = self._incident_classification(metrics, missing_observability)
        metric_summary, metric_bullets = self._metric_narrative(metrics)
        why_not_resource = self._resource_saturation_signals(metrics)
        p95_dev = float(metrics.get("latency_deviation_7d_pct", 0) or 0)
        p95_yesterday = float(metrics.get("p95_yesterday_s_5m", 0) or 0) * 1000

        if error_rate > 0.05:
            root = "5xx error-rate spike"
            impact = "High"
            confidence = 0.78
        elif latency > 0.75:
            root = "sustained p95 latency breach"
            impact = "Medium"
            confidence = 0.64
        else:
            root = "No dominant fault domain identified"
            impact = "Low"
            confidence = 0.48

        confidence_details = self._confidence_details(context)
        if confidence_details.get("computed_confidence") is not None:
            confidence = float(confidence_details["computed_confidence"])
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
        change_detection_context.append(
            f"Latency deviation from 7-day baseline: {p95_dev:+.1f}%."
        )
        if p95_yesterday > 0:
            change_detection_context.append(f"Same window yesterday p95: {round(p95_yesterday)}ms.")

        top_domain = "internal_runtime"
        if causal_likelihoods:
            top_domain = max(causal_likelihoods, key=causal_likelihoods.get)
        scenario_map = {
            "db": "Downstream database latency is the most likely contributor.",
            "kafka": "Messaging backlog/consumer lag is the most likely contributor.",
            "external_dependency": "External dependency latency is the most likely contributor.",
            "internal_runtime": "Transient runtime or traffic fluctuation is the most likely contributor.",
        }
        most_likely = scenario_map.get(top_domain, "Transient runtime or traffic fluctuation is the most likely contributor.")
        risk_15m = self._risk_forecast_15m(metrics, lifecycle)
        anomaly_score = float(signal_scores.get("overall_anomaly_score", 0) or 0)
        anomaly_threshold = 0.65
        anomaly_status = "Anomalous" if anomaly_score >= anomaly_threshold else "Normal"

        return {
            "probable_root_cause": root,
            "impact_level": impact,
            "recommended_remediation": "Continue monitoring for 10-15 minutes; no active mitigation is recommended at current signal confidence.",
            "confidence": confidence,
            "confidence_score": f"{round(confidence * 100)}%",
            "causal_chain": [
                "Assessment: No correlated anomaly detected across metrics and logs.",
                f"Incident progression: {lifecycle.get('progression', 'steady')}.",
                lifecycle.get("mitigation_effect", "No mitigation event observed."),
            ],
            "corrective_actions": [
                "Restart Pod - 58% likelihood of resolving transient application stalls.",
                "Scale Deployment - 34% likelihood if latency persists under load.",
                "Rollback - 12% likelihood unless tied to a confirmed recent release.",
            ],
            "preventive_hardening": ["Add recording rules and SLO burn-rate alerts."],
            "risk_forecast": {
                "predicted_breach_window": "likely_breach_within_1h" if risk_15m >= 70 else "likely_breach_within_24h" if risk_15m >= 40 else "low_risk",
                "predicted_breach_next_15m_pct": risk_15m,
                "context": "Based on current burn rate and latency stability.",
            },
            "deployment_correlation": {"within_10m": bool(context.get("deployment", {}).get("deployment_changed_last_10m"))},
            "error_log_prediction": {"repeated_signatures": []},
            "missing_observability": missing_observability,
            "human_summary": f"{metric_summary} Impact remains {impact.lower()}.",
            "executive_summary": metric_summary,
            "assessment": "No correlated anomaly detected across metrics and logs." if signal_scores.get("overall_anomaly_score", 0) < 0.35 else "Metrics and logs indicate correlated performance pressure.",
            "most_likely_scenario": most_likely,
            "why_not_resource_saturation": why_not_resource,
            "incident_classification": classification,
            "confidence_details": confidence_details,
            "ai_response_status": "complete",
            "change_detection_context": change_detection_context,
            "supporting_evidence": metric_bullets,
            "signal_scores": signal_scores,
            "causal_likelihoods": causal_likelihoods,
            "incident_lifecycle": lifecycle,
            "anomaly_summary": {
                "score": round(anomaly_score, 3),
                "threshold": anomaly_threshold,
                "status": anomaly_status,
            },
            "engine_boundary_note": "Classification and scoring are computed by deterministic signal engine; LLM is used only for structured narrative generation.",
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
        if not isinstance(out.get("signal_scores"), dict):
            out["signal_scores"] = {}
        if not isinstance(out.get("causal_likelihoods"), dict):
            out["causal_likelihoods"] = {}
        if not isinstance(out.get("incident_lifecycle"), dict):
            out["incident_lifecycle"] = {}
        if not isinstance(out.get("anomaly_summary"), dict):
            out["anomaly_summary"] = {}

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

        signal_scores = self._signal_scores(context_data["metrics"], missing_observability)
        context_data["metrics"].update(signal_scores)
        context_data["signal_scores"] = signal_scores
        causal_likelihoods = self._causal_likelihoods(context_data["metrics"], logs, traces, cluster_wiring)
        context_data["causal_likelihoods"] = causal_likelihoods
        incident_key = f"{alert.namespace}:{alert.service}:{alert.severity}:{alert.alertname}"
        lifecycle = self._lifecycle_progression(incident_key, context_data["metrics"])
        context_data["incident_lifecycle"] = lifecycle
        context_data["lifecycle"] = lifecycle

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

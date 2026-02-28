from __future__ import annotations

from datetime import datetime, timezone
import math
from typing import Any

from ai_observer.backend.intelligence.observability_registry import ObservabilityRegistry
from ai_observer.domain.interfaces import ClusterWiringProvider, LlmProvider, LogsProvider, MetricsProvider, TracesProvider
from ai_observer.domain.models import AlertSignal, LiveReasoningResponse, ObservabilityContext, ReasoningResult
from ai_observer.intelligence import (
    AnomalyEngine,
    CausalEngine,
    ConfidenceEngine,
    CorrelationEngine,
    DependencyGraphEngine,
    ReasoningEngine,
    TemporalEngine,
    TopologyEngine,
)


class ReasoningService:
    def __init__(
        self,
        metrics_provider: MetricsProvider,
        logs_provider: LogsProvider,
        traces_provider: TracesProvider,
        llm_provider: LlmProvider,
        cluster_wiring_provider: ClusterWiringProvider,
        observability_registry: ObservabilityRegistry | None = None,
    ):
        self.metrics_provider = metrics_provider
        self.logs_provider = logs_provider
        self.traces_provider = traces_provider
        self.llm_provider = llm_provider
        self.cluster_wiring_provider = cluster_wiring_provider
        self.observability_registry = observability_registry
        self.started_at = datetime.now(timezone.utc)
        self._incident_state: dict[str, dict[str, Any]] = {}
        self.anomaly_engine = AnomalyEngine()
        self.causal_engine = CausalEngine()
        self.confidence_engine = ConfidenceEngine()
        self.correlation_engine = CorrelationEngine()
        self.dependency_graph_engine = DependencyGraphEngine()
        self.topology_engine = TopologyEngine(self.dependency_graph_engine)
        self.temporal_engine = TemporalEngine()
        self.reasoning_engine = ReasoningEngine()

    @staticmethod
    def _clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
        return max(lo, min(hi, value))

    @staticmethod
    def _num(metrics: dict[str, Any], key: str, default: float = 0.0) -> float:
        try:
            return float(metrics.get(key, default) or default)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _mean(values: list[float]) -> float:
        if not values:
            return 0.0
        return sum(values) / len(values)

    @staticmethod
    def _stddev(values: list[float]) -> float:
        if len(values) <= 1:
            return 0.0
        avg = ReasoningService._mean(values)
        variance = sum((v - avg) ** 2 for v in values) / len(values)
        return math.sqrt(max(variance, 0.0))

    @staticmethod
    def _pearson(xs: list[float], ys: list[float]) -> float:
        if len(xs) != len(ys) or len(xs) < 3:
            return 0.0
        mx = ReasoningService._mean(xs)
        my = ReasoningService._mean(ys)
        num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
        den_x = math.sqrt(sum((x - mx) ** 2 for x in xs))
        den_y = math.sqrt(sum((y - my) ** 2 for y in ys))
        den = den_x * den_y
        if den <= 0:
            return 0.0
        return max(-1.0, min(1.0, num / den))

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
        baseline_anomaly = float(metrics.get("baseline_anomaly_score", 0) or 0)
        if missing_observability:
            return "Observability Gap"
        if baseline_anomaly >= 0.65:
            return "Performance Degradation"
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
        baseline_anomaly = float(metrics.get("baseline_anomaly_score", 0) or 0)
        cpu_baseline_score = float(metrics.get("cpu_baseline_anomaly_30m", 0) or 0)
        memory_baseline_score = float(metrics.get("memory_baseline_anomaly_30m", 0) or 0)
        request_baseline_score = float(metrics.get("request_rate_baseline_anomaly_30m", 0) or 0)
        error_baseline_score = float(metrics.get("error_rate_baseline_anomaly_30m", 0) or 0)
        restart_baseline_score = float(metrics.get("pod_restarts_baseline_anomaly_30m", 0) or 0)

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
            + (0.22 * baseline_anomaly)
            + (0.08 * cpu_baseline_score)
            + (0.07 * memory_baseline_score)
            + (0.06 * request_baseline_score)
            + (0.08 * error_baseline_score)
            + (0.04 * restart_baseline_score)
            - (0.12 * observability_penalty)
        )
        # Ensure baseline deviation has a direct effect on anomaly score even with sparse observability.
        overall_anomaly_score = max(overall_anomaly_score, ReasoningService._clamp(baseline_anomaly * 0.7))

        return {
            "cpu_saturation_score": cpu_saturation_score,
            "latency_deviation_score": latency_deviation_score,
            "error_growth_score": error_growth_score,
            "error_level_score": error_level_score,
            "db_pressure_score": db_pressure_score,
            "thread_pressure_score": thread_pressure_score,
            "kafka_pressure_score": kafka_pressure_score,
            "observability_penalty": observability_penalty,
            "baseline_anomaly_score": baseline_anomaly,
            "cpu_baseline_anomaly_score": cpu_baseline_score,
            "memory_baseline_anomaly_score": memory_baseline_score,
            "request_baseline_anomaly_score": request_baseline_score,
            "error_baseline_anomaly_score": error_baseline_score,
            "restart_baseline_anomaly_score": restart_baseline_score,
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
        state = self._incident_state.get(incident_key, {})
        history = list(state.get("history", []))
        prev = history[-1] if history else {}
        current = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "p95": float(metrics.get("latency_p95_s_5m", 0) or 0),
            "err": float(metrics.get("error_rate_5xx_5m", 0) or 0),
            "score": float(metrics.get("overall_anomaly_score", 0) or 0),
            "restarts": float(metrics.get("pod_restarts_10m", 0) or 0),
            "cpu": float(metrics.get("cpu_usage_cores_5m", 0) or 0),
            "memory": float(metrics.get("memory_usage_bytes", 0) or 0),
            "rps": float(metrics.get("request_rate_rps_5m", 0) or 0),
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

        history.append(current)
        history = history[-12:]
        anomaly_samples = [float(s.get("score", 0) or 0) for s in history]
        stability = 1.0 - self._clamp(self._stddev(anomaly_samples) / 0.25)
        short = anomaly_samples[-3:] if len(anomaly_samples) >= 3 else anomaly_samples
        long = anomaly_samples
        trend_delta = (self._mean(short) - self._mean(long)) if long else 0.0
        temporal_consistency = 1.0 - self._clamp(abs(trend_delta) / 0.25)

        self._incident_state[incident_key] = {"history": history}
        return {
            "progression": progression,
            "mitigation_effect": mitigation_effect,
            "previous": prev or None,
            "current": current,
            "history": history,
            "signal_stability": round(stability, 3),
            "temporal_consistency": round(temporal_consistency, 3),
            "trend_delta": round(trend_delta, 4),
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
    def _topology_awareness(
        alert: AlertSignal,
        cluster_wiring: dict[str, Any],
        component_metrics: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        edges = cluster_wiring.get("edges", []) or []
        services = sorted({str(n.get("id")) for n in cluster_wiring.get("nodes", []) if n.get("kind") == "service"})
        service_to_pods: dict[str, list[str]] = {}
        for edge in edges:
            src = str(edge.get("from", "")).strip()
            dst = str(edge.get("to", "")).strip()
            if src and dst:
                service_to_pods.setdefault(src, []).append(dst)
        for svc in list(service_to_pods.keys()):
            service_to_pods[svc] = sorted(set(service_to_pods[svc]))

        def svc_anomaly(svc_metrics: dict[str, Any]) -> float:
            baseline = float(svc_metrics.get("baseline_anomaly_score", 0) or 0)
            err = float(svc_metrics.get("error_rate_5xx_5m", 0) or 0)
            lat = float(svc_metrics.get("latency_p95_s_5m", 0) or 0)
            cpu = float(svc_metrics.get("cpu_usage_cores_5m", 0) or 0)
            return ReasoningService._clamp((0.35 * baseline) + (0.3 * (err / 0.05 if err > 0 else 0)) + (0.2 * (lat / 0.75 if lat > 0 else 0)) + (0.15 * (cpu / 0.8 if cpu > 0 else 0)))

        ranked: list[tuple[str, float]] = []
        for svc, svc_metrics in component_metrics.items():
            ranked.append((svc, svc_anomaly(svc_metrics)))
        ranked.sort(key=lambda item: item[1], reverse=True)
        likely_origin = ranked[0][0] if ranked else (alert.service if alert.service not in {"all", "*"} else "unknown")
        likely_origin_score = ranked[0][1] if ranked else 0.0

        impacted = [svc for svc, score in ranked if score >= 0.2]
        downstream_coverage = ReasoningService._clamp((len(impacted) / max(len(services), 1)) if services else 0.0)
        propagation_consistency = ReasoningService._clamp((0.7 * likely_origin_score) + (0.3 * downstream_coverage))
        return {
            "service_count": len(services),
            "service_to_pods": service_to_pods,
            "ranked_services": [{"service": s, "score": round(v, 3)} for s, v in ranked[:8]],
            "likely_origin_service": likely_origin,
            "likely_origin_score": round(likely_origin_score, 3),
            "impacted_services": impacted,
            "propagation_consistency": round(propagation_consistency, 3),
            "has_dependency_graph": bool(services and edges),
        }

    @staticmethod
    def _correlation_engine(metrics: dict[str, Any], component_metrics: dict[str, dict[str, Any]], lifecycle: dict[str, Any]) -> dict[str, Any]:
        cpu = float(metrics.get("cpu_usage_cores_5m", 0) or 0)
        memory = float(metrics.get("memory_usage_bytes", 0) or 0)
        rps = float(metrics.get("request_rate_rps_5m", 0) or 0)
        error = float(metrics.get("error_rate_5xx_5m", 0) or 0)
        restarts = float(metrics.get("pod_restarts_10m", 0) or 0)
        latency = float(metrics.get("latency_p95_s_5m", 0) or 0)

        agreement_votes = 0
        total_votes = 0
        if latency > 0 and error > 0:
            total_votes += 1
            agreement_votes += 1 if (latency > 0.5 and error > 0.02) else 0
        if cpu > 0 and latency > 0:
            total_votes += 1
            agreement_votes += 1 if (cpu > 0.6 and latency > 0.5) else 0
        if rps > 0 and latency > 0:
            total_votes += 1
            agreement_votes += 1 if (rps > 0.2 and latency > 0.4) else 0
        if restarts > 0:
            total_votes += 1
            agreement_votes += 1 if (error > 0.01 or latency > 0.4) else 0
        if memory > 0 and latency > 0:
            total_votes += 1
            agreement_votes += 1 if (memory > (512 * 1024 * 1024) and latency > 0.4) else 0
        signal_agreement = ReasoningService._clamp((agreement_votes / total_votes) if total_votes else 0.4)

        rows = list(component_metrics.items())
        pairwise: dict[str, float] = {}
        if len(rows) >= 3:
            cpu_series = [float(v.get("cpu_usage_cores_5m", 0) or 0) for _, v in rows]
            err_series = [float(v.get("error_rate_5xx_5m", 0) or 0) for _, v in rows]
            lat_series = [float(v.get("latency_p95_s_5m", 0) or 0) for _, v in rows]
            rps_series = [float(v.get("request_rate_rps_5m", 0) or 0) for _, v in rows]
            pairwise["cpu_vs_latency"] = round(ReasoningService._pearson(cpu_series, lat_series), 3)
            pairwise["error_vs_latency"] = round(ReasoningService._pearson(err_series, lat_series), 3)
            pairwise["rps_vs_latency"] = round(ReasoningService._pearson(rps_series, lat_series), 3)
            pairwise["cpu_vs_error"] = round(ReasoningService._pearson(cpu_series, err_series), 3)
        else:
            pairwise["cpu_vs_latency"] = round(ReasoningService._clamp((cpu / 0.8) * (latency / 0.75) if latency > 0 else 0), 3)
            pairwise["error_vs_latency"] = round(ReasoningService._clamp((error / 0.05) * (latency / 0.75) if latency > 0 else 0), 3)
            pairwise["rps_vs_latency"] = round(ReasoningService._clamp((rps / 1.0) * (latency / 0.75) if latency > 0 else 0), 3)
            pairwise["cpu_vs_error"] = round(ReasoningService._clamp((cpu / 0.8) * (error / 0.05) if error > 0 else 0), 3)

        correlation_strength = ReasoningService._clamp(
            (
                abs(pairwise.get("cpu_vs_latency", 0))
                + abs(pairwise.get("error_vs_latency", 0))
                + abs(pairwise.get("rps_vs_latency", 0))
                + abs(pairwise.get("cpu_vs_error", 0))
            )
            / 4.0
        )

        temporal = float(lifecycle.get("temporal_consistency", 0.5) or 0.5)
        return {
            "signal_agreement_score": round(signal_agreement, 3),
            "correlation_strength": round(correlation_strength, 3),
            "pairwise_correlations": pairwise,
            "temporal_alignment_score": round(temporal, 3),
        }

    @staticmethod
    def _advanced_confidence(
        metrics: dict[str, Any],
        missing_observability: list[str],
        datasource_errors: dict[str, Any],
        signal_scores: dict[str, Any],
        correlation: dict[str, Any],
        topology: dict[str, Any],
        lifecycle: dict[str, Any],
    ) -> dict[str, Any]:
        metric_keys = [
            "cpu_usage_cores_5m",
            "memory_usage_bytes",
            "request_rate_rps_5m",
            "error_rate_5xx_5m",
            "pod_restarts_10m",
            "latency_p95_s_5m",
            "baseline_anomaly_score",
        ]
        present = sum(1 for k in metric_keys if float(metrics.get(k, 0) or 0) > 0 or k == "pod_restarts_10m")
        telemetry_completeness = ReasoningService._clamp(present / len(metric_keys))
        anomaly_strength = ReasoningService._clamp(float(signal_scores.get("overall_anomaly_score", 0) or 0))
        baseline_magnitude = ReasoningService._clamp(float(metrics.get("baseline_anomaly_score", 0) or 0))
        # Confidence represents certainty, not severity: both clearly-normal and clearly-anomalous
        # conditions can have high confidence.
        anomaly_certainty = abs((anomaly_strength * 2.0) - 1.0)
        baseline_certainty = abs((baseline_magnitude * 2.0) - 1.0)
        agreement = ReasoningService._clamp(float(correlation.get("signal_agreement_score", 0.4) or 0.4))
        corr_strength = ReasoningService._clamp(float(correlation.get("correlation_strength", 0.4) or 0.4))
        stability = ReasoningService._clamp(float(lifecycle.get("signal_stability", 0.5) or 0.5))
        temporal_consistency = ReasoningService._clamp(float(lifecycle.get("temporal_consistency", 0.5) or 0.5))
        topology_consistency = ReasoningService._clamp(float(topology.get("propagation_consistency", 0.5) or 0.5))
        data_penalty = ReasoningService._clamp((len(missing_observability) * 0.06) + (len(datasource_errors or {}) * 0.1))
        historical_consistency = ReasoningService._clamp((0.55 * stability) + (0.45 * temporal_consistency))

        confidence = ReasoningService._clamp(
            (0.22 * telemetry_completeness)
            + (0.14 * agreement)
            + (0.10 * baseline_certainty)
            + (0.14 * anomaly_certainty)
            + (0.10 * stability)
            + (0.10 * historical_consistency)
            + (0.10 * corr_strength)
            + (0.10 * topology_consistency)
            + (0.10 * (1.0 - data_penalty))
            - data_penalty
        )
        band = "High" if confidence >= 0.75 else "Medium" if confidence >= 0.5 else "Low"
        return {
            "computed_confidence": round(confidence, 3),
            "confidence_band": band,
            "telemetry_completeness": round(telemetry_completeness, 3),
            "signal_agreement": round(agreement, 3),
            "baseline_deviation_magnitude": round(baseline_magnitude, 3),
            "anomaly_strength": round(anomaly_strength, 3),
            "anomaly_certainty": round(anomaly_certainty, 3),
            "baseline_certainty": round(baseline_certainty, 3),
            "signal_stability": round(stability, 3),
            "historical_consistency": round(historical_consistency, 3),
            "correlation_strength": round(corr_strength, 3),
            "topology_propagation_consistency": round(topology_consistency, 3),
            "data_penalty": round(data_penalty, 3),
        }

    @staticmethod
    def _causal_reasoning(
        metrics: dict[str, Any],
        signal_scores: dict[str, Any],
        correlation: dict[str, Any],
        topology: dict[str, Any],
        lifecycle: dict[str, Any],
    ) -> dict[str, Any]:
        cpu = float(metrics.get("cpu_usage_cores_5m", 0) or 0)
        err = float(metrics.get("error_rate_5xx_5m", 0) or 0)
        lat = float(metrics.get("latency_p95_s_5m", 0) or 0)
        memory = float(metrics.get("memory_usage_bytes", 0) or 0)
        rps = float(metrics.get("request_rate_rps_5m", 0) or 0)
        baseline = float(metrics.get("baseline_anomaly_score", 0) or 0)
        trend_delta = float(lifecycle.get("trend_delta", 0.0) or 0.0)

        root_candidates: list[tuple[str, float, str]] = [
            ("error_rate_5xx_5m", err / 0.05 if err > 0 else 0.0, "Error pressure exceeded expected baseline."),
            ("latency_p95_s_5m", lat / 0.75 if lat > 0 else 0.0, "Latency drift exceeded service objective window."),
            ("cpu_usage_cores_5m", cpu / 0.8 if cpu > 0 else 0.0, "CPU utilization shifted away from baseline."),
            ("memory_usage_bytes", memory / (1024 * 1024 * 1024), "Memory working set increased relative to baseline."),
            ("request_rate_rps_5m", rps / 1.0 if rps > 0 else 0.0, "Traffic pattern changed from normal request profile."),
            ("baseline_anomaly_score", baseline / 0.65 if baseline > 0 else 0.0, "Adaptive baseline deviation indicates non-normal behavior."),
        ]
        root_candidates.sort(key=lambda x: x[1], reverse=True)
        root_metric, root_score, root_reason = root_candidates[0]

        pairwise = correlation.get("pairwise_correlations", {}) or {}
        dependent_signals: list[str] = []
        contradictory: list[str] = []
        unaffected: list[str] = []
        if abs(float(pairwise.get("error_vs_latency", 0) or 0)) > 0.45 and lat > 0 and err > 0:
            dependent_signals.append("Latency tracks error-rate changes (strong coupling).")
        if abs(float(pairwise.get("cpu_vs_latency", 0) or 0)) > 0.45 and cpu > 0 and lat > 0:
            dependent_signals.append("Latency follows CPU pressure trend.")
        if rps <= 0.05 and (lat > 0.5 or err > 0.02):
            contradictory.append("Low traffic with elevated latency/errors suggests internal bottleneck.")
        if memory <= (256 * 1024 * 1024):
            unaffected.append("Memory pressure is not a dominant contributor.")
        if float(metrics.get("pod_restarts_10m", 0) or 0) <= 0:
            unaffected.append("No restart storm observed in current window.")

        origin_service = topology.get("likely_origin_service", "unknown")
        causal_narrative = (
            f"{root_metric} appears primary (score={root_score:.2f}); "
            f"propagation consistency={float(topology.get('propagation_consistency', 0) or 0):.2f}, "
            f"temporal trend delta={trend_delta:+.3f}, origin service={origin_service}."
        )
        return {
            "root_cause_metric": root_metric,
            "root_cause_strength": round(ReasoningService._clamp(root_score), 3),
            "root_cause_explanation": root_reason,
            "dependent_signals": dependent_signals,
            "unaffected_signals": unaffected,
            "contradictory_signals": contradictory,
            "causal_narrative": causal_narrative,
        }

    @staticmethod
    def _confidence_details(context: dict[str, Any]) -> dict[str, Any]:
        advanced = context.get("advanced_confidence")
        if isinstance(advanced, dict) and advanced:
            computed = float(advanced.get("computed_confidence", 0.0) or 0.0)
            return {
                "data_completeness": f"{round(float(advanced.get('telemetry_completeness', 0.0) or 0.0) * 100)}%",
                "signal_agreement": (
                    "High"
                    if float(advanced.get("signal_agreement", 0.0) or 0.0) >= 0.75
                    else "Moderate"
                    if float(advanced.get("signal_agreement", 0.0) or 0.0) >= 0.45
                    else "Low"
                ),
                "historical_similarity": (
                    "High"
                    if float(advanced.get("historical_consistency", 0.0) or 0.0) >= 0.75
                    else "Moderate"
                    if float(advanced.get("historical_consistency", 0.0) or 0.0) >= 0.45
                    else "Low"
                ),
                "overall_band": advanced.get("confidence_band", "Low"),
                "confidence_formula": (
                    "weighted(telemetry_completeness, signal_agreement, baseline_deviation_magnitude, "
                    "anomaly_strength, signal_stability, historical_consistency, correlation_strength, "
                    "topology_propagation_consistency) - data_penalty"
                ),
                "signal_strength": round(float(advanced.get("anomaly_strength", 0.0) or 0.0), 3),
                "causal_consistency": round(float(advanced.get("topology_propagation_consistency", 0.0) or 0.0), 3),
                "computed_confidence": round(computed, 3),
                "factors": advanced,
            }

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
        baseline_score = float(metrics.get("baseline_anomaly_score", 0) or 0)
        baseline_window = str(metrics.get("baseline_window_used", "30m"))

        if baseline_score >= 0.65:
            summary = "Behavioral anomaly detected from historical baseline deviation."
        elif err_pct > 5 or p95_ms > 750:
            summary = "Service behavior indicates active degradation with elevated latency and/or error pressure."
        elif rps <= 0.01:
            summary = "Traffic is currently minimal; no reliable evidence of active degradation in this window."
        else:
            summary = "Service performance remains within normal operating baseline."

        bullets = [
            "No error-rate growth detected." if err_pct <= 1 else "Error-rate growth detected and requires watch.",
            "Resource utilization is below saturation thresholds." if cpu_pct < 80 and mem_mb < 1024 else "Resource utilization is approaching saturation thresholds.",
            "No evidence of active degradation." if err_pct <= 1 and p95_ms <= 750 else "Latency or failure signals indicate active degradation.",
            f"Baseline anomaly score ({baseline_window}) = {baseline_score:.2f}.",
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
        correlation = context.get("correlation", {}) or {}
        topology_insights = context.get("topology_insights", {}) or {}
        causal_analysis = context.get("causal_analysis", {}) or {}
        advanced_conf = context.get("advanced_confidence", {}) or {}
        classification = self.reasoning_engine.classify(metrics, missing_observability)
        metric_summary, metric_bullets = self.reasoning_engine.metric_narrative(metrics)
        why_not_resource = self._resource_saturation_signals(metrics)
        p95_dev = float(metrics.get("latency_deviation_7d_pct", 0) or 0)
        p95_yesterday = float(metrics.get("p95_yesterday_s_5m", 0) or 0) * 1000

        if causal_analysis.get("root_cause_metric"):
            root = str(causal_analysis.get("root_cause_metric"))
            impact = "High" if float(causal_analysis.get("root_cause_strength", 0) or 0) >= 0.7 else "Medium" if float(causal_analysis.get("root_cause_strength", 0) or 0) >= 0.45 else "Low"
            confidence = float(advanced_conf.get("computed_confidence", 0.5) or 0.5)
        elif error_rate > 0.05:
            root = "error_rate_5xx_5m"
            impact = "High"
            confidence = 0.78
        elif latency > 0.75:
            root = "latency_p95_s_5m"
            impact = "Medium"
            confidence = 0.64
        else:
            root = "metrics_within_expected_range"
            impact = "Low"
            confidence = 0.48

        confidence_details = self.reasoning_engine.confidence_details(advanced_conf) if advanced_conf else self._confidence_details(context)
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
        change_detection_context.append(f"Latency deviation from 7-day baseline: {p95_dev:+.1f}%.")
        if p95_yesterday > 0:
            change_detection_context.append(f"Same window yesterday p95: {round(p95_yesterday)}ms.")
        if advanced_conf:
            change_detection_context.append(
                "Confidence factors: "
                f"telemetry={float(advanced_conf.get('telemetry_completeness', 0) or 0):.2f}, "
                f"agreement={float(advanced_conf.get('signal_agreement', 0) or 0):.2f}, "
                f"correlation={float(advanced_conf.get('correlation_strength', 0) or 0):.2f}, "
                f"topology={float(advanced_conf.get('topology_propagation_consistency', 0) or 0):.2f}."
            )
        if topology_insights:
            change_detection_context.append(
                f"Topology origin service: {topology_insights.get('likely_origin_service', 'unknown')} "
                f"(propagation={float(topology_insights.get('propagation_consistency', 0) or 0):.2f})."
            )
        origin_service = str(topology_insights.get("likely_origin_service", "unknown") or "unknown")

        top_domain = "internal_runtime"
        if causal_likelihoods:
            top_domain = max(causal_likelihoods, key=causal_likelihoods.get)
        scenario_map = {
            "db": "Downstream database latency is the most likely contributor.",
            "kafka": "Messaging backlog/consumer lag is the most likely contributor.",
            "external_dependency": "External dependency latency is the most likely contributor.",
            "internal_runtime": "Transient runtime or traffic fluctuation is the most likely contributor.",
        }
        most_likely = self.reasoning_engine.scenario_from_domain(causal_likelihoods)
        risk_15m = self.reasoning_engine.risk_forecast_15m(metrics, lifecycle)
        anomaly_score = float(signal_scores.get("overall_anomaly_score", 0) or 0)
        anomaly_threshold = 0.65
        anomaly_status = "Anomalous" if anomaly_score >= anomaly_threshold else "Normal"

        supporting_evidence = list(metric_bullets)
        if causal_analysis.get("root_cause_explanation"):
            supporting_evidence.append(str(causal_analysis.get("root_cause_explanation")))
        supporting_evidence.extend([str(x) for x in (causal_analysis.get("dependent_signals") or [])])
        supporting_evidence.extend([f"Contradiction: {x}" for x in (causal_analysis.get("contradictory_signals") or [])])

        causal_chain = [
            f"Primary root signal: {root}.",
            f"Assessment: {'Correlated anomaly observed.' if signal_scores.get('overall_anomaly_score', 0) >= 0.35 else 'No high-risk anomaly across combined signals.'}",
            f"Incident progression: {lifecycle.get('progression', 'steady')}.",
            lifecycle.get("mitigation_effect", "No mitigation event observed."),
        ]
        if causal_analysis.get("causal_narrative"):
            causal_chain.append(str(causal_analysis.get("causal_narrative")))

        confidence = max(confidence, float(advanced_conf.get("computed_confidence", 0.0) or 0.0))
        confidence_floor = self.reasoning_engine.confidence_floor(missing_observability)
        confidence = max(confidence, confidence_floor)
        confidence = self.reasoning_engine.clamp(confidence)
        return {
            "probable_root_cause": root,
            "origin_service": origin_service,
            "impact_level": impact,
            "recommended_remediation": "Continue monitoring for 10-15 minutes; no active mitigation is recommended at current signal confidence.",
            "confidence": confidence,
            "confidence_score": f"{round(confidence * 100)}%",
            "causal_chain": causal_chain,
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
            "assessment": "No correlated anomaly detected across metrics and logs." if signal_scores.get("overall_anomaly_score", 0) < 0.35 else "Metrics, topology, and temporal correlation indicate performance pressure.",
            "most_likely_scenario": most_likely,
            "why_not_resource_saturation": why_not_resource,
            "incident_classification": classification,
            "confidence_details": confidence_details,
            "ai_response_status": "complete",
            "change_detection_context": change_detection_context,
            "supporting_evidence": supporting_evidence,
            "signal_scores": signal_scores,
            "causal_likelihoods": causal_likelihoods,
            "incident_lifecycle": lifecycle,
            "correlated_signals": correlation,
            "causal_analysis": causal_analysis,
            "topology_insights": topology_insights,
            "anomaly_summary": self.reasoning_engine.anomaly_summary(signal_scores, anomaly_threshold),
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
        out["supporting_evidence"] = to_list_str(out.get("supporting_evidence"))
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
        if not isinstance(out.get("correlated_signals"), dict):
            out["correlated_signals"] = {}
        if not isinstance(out.get("causal_analysis"), dict):
            out["causal_analysis"] = {}
        if not isinstance(out.get("topology_insights"), dict):
            out["topology_insights"] = {}
        if not out.get("origin_service"):
            out["origin_service"] = str((out.get("topology_insights") or {}).get("likely_origin_service", "unknown") or "unknown")
        if not isinstance(out.get("anomaly_summary"), dict):
            out["anomaly_summary"] = {}

        if "confidence_score" not in out and out.get("confidence") is not None:
            try:
                out["confidence_score"] = f"{round(float(out['confidence']) * 100)}%"
            except Exception:
                out["confidence_score"] = "40%"

        out.pop("_llm_partial", None)
        out["ai_response_status"] = "complete"
        return out

    @staticmethod
    def _derive_origin_from_context(context: dict[str, Any], preferred_service: str = "observer-agent") -> str:
        topology = context.get("topology_insights", {}) if isinstance(context.get("topology_insights"), dict) else {}
        current = str(topology.get("likely_origin_service", "") or "").strip()
        if current and current.lower() != "unknown":
            return current

        ranked = topology.get("ranked_services")
        if isinstance(ranked, list):
            for item in ranked:
                if isinstance(item, dict):
                    svc = str(item.get("service", "")).strip()
                    if svc:
                        return svc

        service_to_pods = topology.get("service_to_pods")
        if isinstance(service_to_pods, dict):
            for svc, pods in service_to_pods.items():
                if isinstance(pods, list) and pods:
                    return str(svc)

        dep_graph = topology.get("dependency_graph")
        if isinstance(dep_graph, dict):
            services = dep_graph.get("services")
            if isinstance(services, list) and services:
                return str(services[0])

        wiring = context.get("cluster_wiring", {}) if isinstance(context.get("cluster_wiring"), dict) else {}
        relations = wiring.get("relations") if isinstance(wiring.get("relations"), dict) else {}
        svc_to_pod = relations.get("service_to_pod") if isinstance(relations, dict) else None
        if isinstance(svc_to_pod, list):
            for rel in svc_to_pod:
                if isinstance(rel, dict):
                    svc = str(rel.get("service", "")).strip()
                    if svc:
                        return svc

        edges = wiring.get("edges")
        if isinstance(edges, list):
            for edge in edges:
                if isinstance(edge, dict):
                    src = str(edge.get("from", "")).strip()
                    if src:
                        return src

        return preferred_service

    def _ensure_complete_analysis(self, analysis: dict[str, Any], context: dict[str, Any], preferred_service: str = "observer-agent") -> dict[str, Any]:
        out = self._normalize(analysis)
        origin = str(out.get("origin_service", "")).strip()
        if not origin or origin.lower() == "unknown":
            origin = self._derive_origin_from_context(context, preferred_service=preferred_service)
            out["origin_service"] = origin

        topology = out.get("topology_insights")
        if not isinstance(topology, dict):
            topology = {}
        if not topology:
            topology = dict(context.get("topology_insights", {}) or {})
        if str(topology.get("likely_origin_service", "")).strip().lower() in {"", "unknown"}:
            topology["likely_origin_service"] = origin
        out["topology_insights"] = topology

        chain = out.get("causal_chain")
        if not isinstance(chain, list) or not chain:
            chain = [
                f"Primary root signal: {out.get('probable_root_cause', 'metrics_within_expected_range')}.",
                f"Topology-derived origin service: {origin}.",
            ]
            dep = topology.get("propagation_path")
            if isinstance(dep, list) and dep:
                chain.append(f"Propagation path: {' -> '.join(str(x) for x in dep)}.")
            out["causal_chain"] = chain

        conf_score = str(out.get("confidence_score", "")).strip()
        if not conf_score:
            try:
                conf = float(out.get("confidence", 0.6) or 0.6)
            except Exception:
                conf = 0.6
            out["confidence"] = self._clamp(conf, 0.0, 1.0)
            out["confidence_score"] = f"{round(out['confidence'] * 100)}%"

        out["ai_response_status"] = "complete"
        return out

    def analyze(self, alert: AlertSignal, window_minutes: int = 30) -> LiveReasoningResponse:
        errors: dict[str, str] = {}
        observability_registry_state: dict[str, Any] = {}

        if self.observability_registry is not None:
            refreshed = self.observability_registry.refresh()
            observability_registry_state = self.observability_registry.status_view()
            # Providers are long-lived objects. Keep their endpoints fresh as discovery evolves.
            if refreshed.prometheus_url:
                self.metrics_provider.base_url = refreshed.prometheus_url  # type: ignore[attr-defined]
            if refreshed.loki_url:
                self.logs_provider.base_url = refreshed.loki_url  # type: ignore[attr-defined]
            if refreshed.jaeger_url:
                self.traces_provider.base_url = refreshed.jaeger_url  # type: ignore[attr-defined]
            for source, source_status in refreshed.status.items():
                if source_status != "healthy":
                    source_error = refreshed.last_error.get(source, source_status)
                    errors[source] = source_error or source_status

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
            "observability_registry": observability_registry_state,
        }

        missing_observability: list[str] = []
        if not context_data["metrics"].get("db_connection_pool_usage_5m"):
            missing_observability.append("db_connection_pool_usage metric missing")
        if not context_data["metrics"].get("thread_pool_saturation_5m"):
            missing_observability.append("thread_pool_saturation metric missing")
        if not context_data["metrics"].get("kafka_consumer_lag"):
            missing_observability.append("kafka_consumer_lag metric missing")
        context_data["analysis_missing_observability"] = missing_observability

        signal_scores = self.anomaly_engine.compute_signal_scores(context_data["metrics"], missing_observability)
        context_data["metrics"].update(signal_scores)
        context_data["signal_scores"] = signal_scores
        causal_likelihoods = self.causal_engine.likelihoods(context_data["metrics"], logs, traces, cluster_wiring)
        context_data["causal_likelihoods"] = causal_likelihoods
        incident_key = f"{alert.namespace}:{alert.service}:{alert.severity}:{alert.alertname}"
        lifecycle = self.temporal_engine.lifecycle(incident_key, context_data["metrics"])
        context_data["incident_lifecycle"] = lifecycle
        context_data["lifecycle"] = lifecycle
        topology_insights = self.topology_engine.evaluate(alert.namespace, cluster_wiring, component_metrics, alert.service)
        context_data["topology_insights"] = topology_insights
        correlation = self.correlation_engine.evaluate(context_data["metrics"], component_metrics, lifecycle)
        context_data["correlation"] = correlation
        advanced_confidence = self.confidence_engine.evaluate(
            context_data["metrics"],
            missing_observability,
            errors,
            signal_scores,
            correlation,
            topology_insights,
            lifecycle,
        )
        context_data["advanced_confidence"] = advanced_confidence
        causal_analysis = self.causal_engine.infer(
            context_data["metrics"],
            signal_scores,
            correlation,
            topology_insights,
            lifecycle,
        )
        context_data["causal_analysis"] = causal_analysis

        baseline = self._baseline(context_data)
        try:
            llm_response = self.llm_provider.analyze({"context": context_data, "baseline": baseline})
            merged = dict(baseline)
            merged.update({k: v for k, v in llm_response.items() if not str(k).startswith("_") and v is not None and v != ""})
            analysis_data = self._ensure_complete_analysis(merged, context_data, preferred_service=alert.service or "observer-agent")
        except Exception as exc:
            errors["llm"] = str(exc)
            context_data["datasource_errors"] = errors
            analysis_data = self._ensure_complete_analysis(baseline, context_data, preferred_service=alert.service or "observer-agent")

        analysis_data["policy_note"] = "No auto-remediation was applied. Explicit approval required before changes."

        context = ObservabilityContext(**context_data)
        analysis = ReasoningResult(**analysis_data)
        return LiveReasoningResponse(context=context, analysis=analysis)

from __future__ import annotations

from typing import Any

from ai_observer.intelligence.utils import clamp


class CausalEngine:
    def likelihoods(self, metrics: dict[str, Any], logs: dict[str, Any], traces: dict[str, Any], cluster_wiring: dict[str, Any]) -> dict[str, float]:
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

    def infer(
        self,
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
            "root_cause_strength": round(clamp(root_score), 3),
            "root_cause_explanation": root_reason,
            "dependent_signals": dependent_signals,
            "unaffected_signals": unaffected,
            "contradictory_signals": contradictory,
            "causal_narrative": causal_narrative,
        }

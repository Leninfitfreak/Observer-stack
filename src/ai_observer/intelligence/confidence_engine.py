from __future__ import annotations

from typing import Any

from ai_observer.intelligence.utils import clamp


class ConfidenceEngine:
    def evaluate(
        self,
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
        telemetry_completeness = clamp(present / len(metric_keys))
        anomaly_strength = clamp(float(signal_scores.get("overall_anomaly_score", 0) or 0))
        baseline_magnitude = clamp(float(metrics.get("baseline_anomaly_score", 0) or 0))
        anomaly_certainty = abs((anomaly_strength * 2.0) - 1.0)
        baseline_certainty = abs((baseline_magnitude * 2.0) - 1.0)
        agreement = clamp(float(correlation.get("signal_agreement_score", 0.4) or 0.4))
        corr_strength = clamp(float(correlation.get("correlation_strength", 0.4) or 0.4))
        stability = clamp(float(lifecycle.get("signal_stability", 0.5) or 0.5))
        temporal_consistency = clamp(float(lifecycle.get("temporal_consistency", 0.5) or 0.5))
        topology_consistency = clamp(float(topology.get("propagation_consistency", 0.5) or 0.5))
        data_penalty = clamp((len(missing_observability) * 0.06) + (len(datasource_errors or {}) * 0.1))
        historical_consistency = clamp((0.55 * stability) + (0.45 * temporal_consistency))
        confidence = clamp(
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

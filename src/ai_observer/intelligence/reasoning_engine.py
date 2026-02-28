from __future__ import annotations

from typing import Any

from ai_observer.intelligence.utils import clamp


class ReasoningEngine:
    @staticmethod
    def classify(metrics: dict[str, Any], missing_observability: list[str]) -> str:
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
    def confidence_details(advanced_confidence: dict[str, Any]) -> dict[str, Any]:
        computed = float(advanced_confidence.get("computed_confidence", 0.0) or 0.0)
        return {
            "data_completeness": f"{round(float(advanced_confidence.get('telemetry_completeness', 0.0) or 0.0) * 100)}%",
            "signal_agreement": (
                "High"
                if float(advanced_confidence.get("signal_agreement", 0.0) or 0.0) >= 0.75
                else "Moderate"
                if float(advanced_confidence.get("signal_agreement", 0.0) or 0.0) >= 0.45
                else "Low"
            ),
            "historical_similarity": (
                "High"
                if float(advanced_confidence.get("historical_consistency", 0.0) or 0.0) >= 0.75
                else "Moderate"
                if float(advanced_confidence.get("historical_consistency", 0.0) or 0.0) >= 0.45
                else "Low"
            ),
            "overall_band": advanced_confidence.get("confidence_band", "Low"),
            "confidence_formula": (
                "weighted(telemetry_completeness, signal_agreement, baseline_deviation_magnitude, "
                "anomaly_strength, signal_stability, historical_consistency, correlation_strength, "
                "topology_propagation_consistency) - data_penalty"
            ),
            "signal_strength": round(float(advanced_confidence.get("anomaly_strength", 0.0) or 0.0), 3),
            "causal_consistency": round(float(advanced_confidence.get("topology_propagation_consistency", 0.0) or 0.0), 3),
            "computed_confidence": round(computed, 3),
            "factors": advanced_confidence,
        }

    @staticmethod
    def risk_forecast_15m(metrics: dict[str, Any], lifecycle: dict[str, Any]) -> float:
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
    def confidence_floor(missing_observability: list[str]) -> float:
        return 0.35 if len(missing_observability) <= 2 else 0.2

    @staticmethod
    def anomaly_summary(signal_scores: dict[str, Any], threshold: float = 0.65) -> dict[str, Any]:
        score = float(signal_scores.get("overall_anomaly_score", 0) or 0)
        return {
            "score": round(score, 3),
            "threshold": threshold,
            "status": "Anomalous" if score >= threshold else "Normal",
        }

    @staticmethod
    def scenario_from_domain(causal_likelihoods: dict[str, float]) -> str:
        top_domain = "internal_runtime"
        if causal_likelihoods:
            top_domain = max(causal_likelihoods, key=causal_likelihoods.get)
        scenario_map = {
            "db": "Downstream database latency is the most likely contributor.",
            "kafka": "Messaging backlog/consumer lag is the most likely contributor.",
            "external_dependency": "External dependency latency is the most likely contributor.",
            "internal_runtime": "Transient runtime or traffic fluctuation is the most likely contributor.",
        }
        return scenario_map.get(top_domain, "Transient runtime or traffic fluctuation is the most likely contributor.")

    @staticmethod
    def metric_narrative(metrics: dict[str, Any]) -> tuple[str, list[str]]:
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

    @staticmethod
    def clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
        return clamp(value, lo, hi)

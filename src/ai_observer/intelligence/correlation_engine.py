from __future__ import annotations

from typing import Any

from ai_observer.intelligence.utils import clamp, pearson


class CorrelationEngine:
    def evaluate(self, metrics: dict[str, Any], component_metrics: dict[str, dict[str, Any]], lifecycle: dict[str, Any]) -> dict[str, Any]:
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
        signal_agreement = clamp((agreement_votes / total_votes) if total_votes else 0.4)

        rows = list(component_metrics.items())
        pairwise: dict[str, float] = {}
        if len(rows) >= 3:
            cpu_series = [float(v.get("cpu_usage_cores_5m", 0) or 0) for _, v in rows]
            err_series = [float(v.get("error_rate_5xx_5m", 0) or 0) for _, v in rows]
            lat_series = [float(v.get("latency_p95_s_5m", 0) or 0) for _, v in rows]
            rps_series = [float(v.get("request_rate_rps_5m", 0) or 0) for _, v in rows]
            pairwise["cpu_vs_latency"] = round(pearson(cpu_series, lat_series), 3)
            pairwise["error_vs_latency"] = round(pearson(err_series, lat_series), 3)
            pairwise["rps_vs_latency"] = round(pearson(rps_series, lat_series), 3)
            pairwise["cpu_vs_error"] = round(pearson(cpu_series, err_series), 3)
        else:
            pairwise["cpu_vs_latency"] = round(clamp((cpu / 0.8) * (latency / 0.75) if latency > 0 else 0), 3)
            pairwise["error_vs_latency"] = round(clamp((error / 0.05) * (latency / 0.75) if latency > 0 else 0), 3)
            pairwise["rps_vs_latency"] = round(clamp((rps / 1.0) * (latency / 0.75) if latency > 0 else 0), 3)
            pairwise["cpu_vs_error"] = round(clamp((cpu / 0.8) * (error / 0.05) if error > 0 else 0), 3)

        correlation_strength = clamp(
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

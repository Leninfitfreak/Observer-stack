from __future__ import annotations

from typing import Any

from ai_observer.intelligence.utils import clamp


class AnomalyEngine:
    def compute_signal_scores(self, metrics: dict[str, Any], missing_observability: list[str]) -> dict[str, float]:
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

        cpu_saturation_score = clamp(cpu_pct / 80.0)
        latency_deviation_score = clamp(((p95_cur - p95_base) / p95_base) if p95_base > 0 else (p95_cur / 0.75 if p95_cur > 0 else 0))
        error_growth_score = clamp(err_growth / 0.02 if err_growth > 0 else 0)
        error_level_score = clamp(err_rate / 0.05)
        db_pressure_score = clamp(db_pool / 0.85)
        thread_pressure_score = clamp(thread_sat / 0.85)
        kafka_pressure_score = clamp(kafka_lag / 1000.0 if kafka_lag > 0 else 0)
        observability_penalty = clamp(len(missing_observability) / 8.0)

        overall_anomaly_score = clamp(
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
        overall_anomaly_score = max(overall_anomaly_score, clamp(baseline_anomaly * 0.7))
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

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ai_observer.intelligence.utils import clamp, mean, stddev


class TemporalEngine:
    def __init__(self):
        self._state: dict[str, dict[str, Any]] = {}

    def lifecycle(self, incident_key: str, metrics: dict[str, Any]) -> dict[str, Any]:
        state = self._state.get(incident_key, {})
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
        stability = 1.0 - clamp(stddev(anomaly_samples) / 0.25)
        short = anomaly_samples[-3:] if len(anomaly_samples) >= 3 else anomaly_samples
        trend_delta = (mean(short) - mean(anomaly_samples)) if anomaly_samples else 0.0
        temporal_consistency = 1.0 - clamp(abs(trend_delta) / 0.25)

        self._state[incident_key] = {"history": history}
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

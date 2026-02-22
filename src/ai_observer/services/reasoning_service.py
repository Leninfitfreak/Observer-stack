from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ai_observer.domain.interfaces import LlmProvider, LogsProvider, MetricsProvider, TracesProvider
from ai_observer.domain.models import AlertSignal, LiveReasoningResponse, ObservabilityContext, ReasoningResult


class ReasoningService:
    def __init__(
        self,
        metrics_provider: MetricsProvider,
        logs_provider: LogsProvider,
        traces_provider: TracesProvider,
        llm_provider: LlmProvider,
    ):
        self.metrics_provider = metrics_provider
        self.logs_provider = logs_provider
        self.traces_provider = traces_provider
        self.llm_provider = llm_provider
        self.started_at = datetime.now(timezone.utc)

    def _baseline(self, context: dict[str, Any]) -> dict[str, Any]:
        metrics = context.get("metrics", {})
        error_rate = metrics.get("error_rate_5xx_5m", 0) or 0
        latency = metrics.get("latency_p95_s_5m", 0) or 0

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

        return {
            "probable_root_cause": root,
            "impact_level": impact,
            "recommended_remediation": "Continue monitoring and validate telemetry coverage.",
            "confidence": confidence,
            "confidence_score": f"{round(confidence * 100)}%",
            "causal_chain": ["No strong multi-signal causal chain detected from current telemetry."],
            "corrective_actions": ["No immediate mitigation required."],
            "preventive_hardening": ["Add recording rules and SLO burn-rate alerts."],
            "risk_forecast": {"predicted_breach_window": "low_risk"},
            "deployment_correlation": {"within_10m": bool(context.get("deployment", {}).get("deployment_changed_last_10m"))},
            "error_log_prediction": {"repeated_signatures": []},
            "missing_observability": [],
            "human_summary": f"Probable root cause: {root}. Impact: {impact}.",
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
        if not isinstance(out.get("deployment_correlation"), dict):
            out["deployment_correlation"] = {"value": out.get("deployment_correlation")}
        if not isinstance(out.get("error_log_prediction"), dict):
            out["error_log_prediction"] = {"value": out.get("error_log_prediction")}

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
            "datasource_errors": errors,
        }

        baseline = self._baseline(context_data)
        try:
            llm_response = self.llm_provider.analyze({"context": context_data, "baseline": baseline})
            merged = dict(baseline)
            merged.update({k: v for k, v in llm_response.items() if v is not None and v != ""})
            analysis_data = self._normalize(merged)
        except Exception as exc:
            errors["llm"] = str(exc)
            context_data["datasource_errors"] = errors
            analysis_data = self._normalize(baseline)

        analysis_data["policy_note"] = "No auto-remediation was applied. Explicit approval required before changes."

        context = ObservabilityContext(**context_data)
        analysis = ReasoningResult(**analysis_data)
        return LiveReasoningResponse(context=context, analysis=analysis)

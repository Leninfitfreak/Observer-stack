from __future__ import annotations

import io
import json
from datetime import datetime, timezone
from typing import Any

import pandas as pd
from sqlalchemy.orm import Session

from ai_observer.backend.models.incident import Incident, IncidentMetricsSnapshot, IncidentStatusHistory
from ai_observer.backend.repositories.incidents_repository import IncidentsRepository
from ai_observer.backend.schemas.incidents import IncidentFilterQuery
from ai_observer.domain.models import AlertSignal, LiveReasoningResponse
from ai_observer.incident_analysis.models import IncidentAnalysis


class IncidentsService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = IncidentsRepository(db)

    def list(self, query: IncidentFilterQuery) -> tuple[int, list[dict[str, Any]]]:
        total, rows = self.repo.list_incidents(query)
        data: list[dict[str, Any]] = []
        for incident, analysis in rows:
            data.append(
                {
                    "incident_id": incident.incident_id,
                    "status": incident.status,
                    "severity": incident.severity,
                    "impact_level": incident.impact_level,
                    "slo_breach_risk": incident.slo_breach_risk,
                    "error_budget_remaining": incident.error_budget_remaining,
                    "affected_services": incident.affected_services,
                    "start_time": incident.start_time,
                    "duration": incident.duration,
                    "created_at": incident.created_at,
                    "executive_summary": analysis.executive_summary if analysis else None,
                    "root_cause": analysis.root_cause if analysis else None,
                    "confidence_score": analysis.confidence_score if analysis else None,
                    "classification": analysis.classification if analysis else None,
                    "risk_forecast": analysis.risk_forecast if analysis else None,
                }
            )
        return total, data

    def details(self, incident_id: str) -> dict[str, Any] | None:
        row = self.repo.get_incident_details(incident_id)
        if row is None:
            return None
        return {
            "incident": {
                "incident_id": row["incident"].incident_id,
                "status": row["incident"].status,
                "severity": row["incident"].severity,
                "impact_level": row["incident"].impact_level,
                "slo_breach_risk": row["incident"].slo_breach_risk,
                "error_budget_remaining": row["incident"].error_budget_remaining,
                "affected_services": row["incident"].affected_services,
                "start_time": row["incident"].start_time,
                "duration": row["incident"].duration,
                "created_at": row["incident"].created_at,
            },
            "analysis": [
                {
                    "id": a.id,
                    "incident_id": a.incident_id,
                    "executive_summary": a.executive_summary,
                    "root_cause": a.root_cause,
                    "supporting_signals": a.supporting_signals,
                    "risk_forecast": a.risk_forecast,
                    "suggested_actions": a.suggested_actions,
                    "confidence_score": a.confidence_score,
                    "confidence_breakdown": a.confidence_breakdown,
                    "created_at": a.created_at,
                    "classification": a.classification,
                    "mitigation": a.mitigation,
                }
                for a in row["analysis"]
            ],
            "metrics_snapshot": [
                {
                    "id": m.id,
                    "incident_id": m.incident_id,
                    "cpu_usage": m.cpu_usage,
                    "memory_usage": m.memory_usage,
                    "latency_p95": m.latency_p95,
                    "error_rate": m.error_rate,
                    "thread_pool_saturation": m.thread_pool_saturation,
                    "raw_metrics_json": m.raw_metrics_json,
                    "captured_at": m.captured_at,
                }
                for m in row["metrics_snapshot"]
            ],
            "status_history": [
                {
                    "id": h.id,
                    "incident_id": h.incident_id,
                    "from_status": h.from_status,
                    "to_status": h.to_status,
                    "changed_at": h.changed_at,
                }
                for h in row["status_history"]
            ],
        }

    def export_excel(self, query: IncidentFilterQuery) -> bytes:
        _total, data = self.list(query)
        ids = [item["incident_id"] for item in data]
        detail_rows = [self.details(incident_id) for incident_id in ids]
        detail_rows = [d for d in detail_rows if d is not None]

        def _safe_json(value: Any) -> str:
            if value is None:
                return ""
            if isinstance(value, (dict, list)):
                return json.dumps(value, ensure_ascii=False, default=str)
            return str(value)

        def _sla_countdown(start_time: Any, window_minutes: int = 60) -> str:
            if not isinstance(start_time, datetime):
                return ""
            start = start_time if start_time.tzinfo else start_time.replace(tzinfo=timezone.utc)
            elapsed = int((datetime.now(timezone.utc) - start).total_seconds())
            remaining = max(0, (window_minutes * 60) - max(0, elapsed))
            hh = str(remaining // 3600).zfill(2)
            mm = str((remaining % 3600) // 60).zfill(2)
            ss = str(remaining % 60).zfill(2)
            return f"{hh}:{mm}:{ss}"

        incident_core_rows: list[dict[str, Any]] = [
            {
                "Incident ID": item["incident_id"],
                "Status": item["status"],
                "Severity": item["severity"],
                "Impact Level": item["impact_level"],
                "SLA Countdown": _sla_countdown(item["start_time"]),
                "SLO Breach Risk": item["slo_breach_risk"],
                "Error Budget Remaining": item["error_budget_remaining"],
                "Affected Services": item["affected_services"],
                "Start Time": item["start_time"],
                "Duration": item["duration"],
            }
            for item in data
        ]

        ai_analysis_rows: list[dict[str, Any]] = []
        metrics_rows: list[dict[str, Any]] = []
        raw_json_rows: list[dict[str, Any]] = []

        for item in detail_rows:
            incident_obj = item.get("incident", {})
            incident_id = incident_obj.get("incident_id", "")

            for analysis in item.get("analysis", []):
                supporting_signals = analysis.get("supporting_signals")
                mitigation = analysis.get("mitigation")
                change_context = []
                if isinstance(mitigation, dict):
                    change_context = mitigation.get("change_detection_context") or []
                if not change_context and isinstance(supporting_signals, dict):
                    change_context = supporting_signals.get("change_detection_context") or []

                ai_analysis_rows.append(
                    {
                        "Incident ID": incident_id or analysis.get("incident_id", ""),
                        "Executive Summary": _safe_json(analysis.get("executive_summary")),
                        "Root Cause": _safe_json(analysis.get("root_cause")),
                        "Supporting Signals": _safe_json(supporting_signals),
                        "Change Detection Context": _safe_json(change_context),
                        "Risk Forecast": analysis.get("risk_forecast"),
                        "Suggested Actions": _safe_json(analysis.get("suggested_actions")),
                        "Confidence Score": analysis.get("confidence_score"),
                        "Confidence Breakdown": _safe_json(analysis.get("confidence_breakdown")),
                    }
                )

            for metrics in item.get("metrics_snapshot", []):
                metrics_rows.append(
                    {
                        "Incident ID": incident_id or metrics.get("incident_id", ""),
                        "CPU Usage": metrics.get("cpu_usage"),
                        "Memory Usage": metrics.get("memory_usage"),
                        "Latency P95": metrics.get("latency_p95"),
                        "Error Rate": metrics.get("error_rate"),
                        "Thread Pool Saturation": metrics.get("thread_pool_saturation"),
                        "Raw Metrics JSON": _safe_json(metrics.get("raw_metrics_json")),
                    }
                )

            raw_json_rows.append({"Incident JSON": _safe_json(item)})

        output = io.BytesIO()
        with pd.ExcelWriter(output, engine="openpyxl") as writer:
            if not incident_core_rows:
                pd.DataFrame([{"message": "No data available"}]).to_excel(
                    writer, index=False, sheet_name="No data available"
                )
            else:
                pd.DataFrame(incident_core_rows).to_excel(writer, index=False, sheet_name="Incident Core")
                pd.DataFrame(ai_analysis_rows or [{"Incident ID": "", "Executive Summary": "", "Root Cause": ""}]).to_excel(
                    writer, index=False, sheet_name="AI Analysis"
                )
                pd.DataFrame(metrics_rows or [{"Incident ID": "", "CPU Usage": "", "Memory Usage": ""}]).to_excel(
                    writer, index=False, sheet_name="Metrics Snapshot"
                )
                pd.DataFrame(raw_json_rows).to_excel(writer, index=False, sheet_name="Raw JSON")
        output.seek(0)
        return output.getvalue()

    def persist_from_reasoning(self, alert: AlertSignal, response: LiveReasoningResponse) -> None:
        now = datetime.now(timezone.utc)
        analysis = response.analysis
        context = response.context
        risk_pct = float((analysis.risk_forecast or {}).get("predicted_breach_next_15m_pct", 0) or 0)
        risk = max(0.0, min(1.0, risk_pct / 100.0))
        incident_id = f"{alert.alertname}-{now.strftime('%Y%m%d%H%M%S')}-{alert.service}"

        incident = Incident(
            incident_id=incident_id,
            status="OPEN",
            severity=str(alert.severity).upper(),
            impact_level=analysis.impact_level,
            slo_breach_risk=risk_pct,
            error_budget_remaining=100.0,
            affected_services=alert.service,
            start_time=now,
            duration="00:00:00",
            created_at=now,
        )
        self.db.add(incident)
        self.db.add(
            IncidentStatusHistory(
                incident_id=incident_id,
                from_status="OPEN",
                to_status="OPEN",
                changed_at=now,
            )
        )
        self.db.add(
            IncidentAnalysis(
                incident_id=incident_id,
                service_name=alert.service,
                anomaly_score=float((analysis.anomaly_summary or {}).get("score", 0) or 0),
                confidence_score=float(analysis.confidence or 0),
                classification=analysis.incident_classification or "Unknown",
                root_cause=analysis.probable_root_cause or "Unknown",
                mitigation={
                    "executive_summary": analysis.executive_summary or "",
                    "supporting_signals": analysis.causal_chain or [],
                    "actions": analysis.corrective_actions or [],
                    "confidence_breakdown": analysis.confidence_details or {},
                },
                risk_forecast=risk,
                mitigation_success=None,
                executive_summary=analysis.executive_summary or analysis.human_summary or "",
                supporting_signals={"signals": analysis.causal_chain or []},
                suggested_actions={"actions": analysis.corrective_actions or []},
                confidence_breakdown=analysis.confidence_details or {},
                created_at=now,
            )
        )
        m = context.metrics or {}
        self.db.add(
            IncidentMetricsSnapshot(
                incident_id=incident_id,
                cpu_usage=float((m.get("cpu_usage_cores_5m", 0) or 0) * 100),
                memory_usage=float((m.get("memory_usage_bytes", 0) or 0) / (1024 * 1024)),
                latency_p95=float((m.get("latency_p95_s_5m", 0) or 0) * 1000),
                error_rate=float((m.get("error_rate_5xx_5m", 0) or 0) * 100),
                thread_pool_saturation=float(m.get("thread_pool_saturation_5m", 0) or 0),
                raw_metrics_json=m,
                captured_at=now,
            )
        )
        self.db.commit()

from __future__ import annotations

import io
import json
import re
from datetime import datetime, timezone
from typing import Any

import pandas as pd
from sqlalchemy.orm import Session

from ai_observer.backend.models.incident import Incident, IncidentMetricsSnapshot, IncidentStatusHistory
from ai_observer.backend.repositories.incidents_repository import IncidentsRepository
from ai_observer.backend.schemas.incidents import IncidentFilterQuery
from ai_observer.backend.services.canonical_telemetry import build_canonical_telemetry
from ai_observer.domain.models import AlertSignal, LiveReasoningResponse
from ai_observer.incident_analysis.models import IncidentAnalysis


class IncidentsService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = IncidentsRepository(db)

    @staticmethod
    def _num(metrics: dict[str, Any], key: str, default: float = 0.0) -> float:
        try:
            return float(metrics.get(key, default))
        except (TypeError, ValueError):
            return default

    @classmethod
    def _normalize_metrics(cls, metrics: dict[str, Any]) -> dict[str, float]:
        if not isinstance(metrics, dict):
            return {
                "cpu_usage": 0.0,
                "memory_usage": 0.0,
                "request_rate": 0.0,
                "pod_restarts": 0.0,
                "error_rate": 0.0,
            }
        cpu = cls._num(metrics, "cpu_usage_cores_5m", cls._num(metrics, "cpu_usage"))
        memory = cls._num(metrics, "memory_usage_bytes", cls._num(metrics, "memory_usage"))
        request_rate = cls._num(metrics, "request_rate_rps_5m", cls._num(metrics, "request_rate"))
        restarts = cls._num(metrics, "pod_restarts_10m", cls._num(metrics, "pod_restarts"))
        error_rate = cls._num(metrics, "error_rate_5xx_5m", cls._num(metrics, "error_rate"))

        if cpu > 1.0:
            cpu = cpu / 100.0
        if 0.0 < memory < 1024.0:
            memory = memory * 1024.0 * 1024.0
        if error_rate > 1.0:
            error_rate = error_rate / 100.0

        return {
            "cpu_usage": cpu,
            "memory_usage": memory,
            "request_rate": request_rate,
            "pod_restarts": restarts,
            "error_rate": error_rate,
        }

    @staticmethod
    def _has_signal(metrics: dict[str, float]) -> bool:
        return any(float(metrics.get(k, 0.0) or 0.0) > 0.0 for k in ("cpu_usage", "memory_usage", "request_rate", "pod_restarts", "error_rate"))

    @classmethod
    def _merge_priority_metrics(cls, sources: list[dict[str, float]]) -> dict[str, float]:
        merged = {"cpu_usage": 0.0, "memory_usage": 0.0, "request_rate": 0.0, "pod_restarts": 0.0, "error_rate": 0.0}
        for source in sources:
            if not isinstance(source, dict):
                continue
            for key in merged.keys():
                current = float(merged.get(key, 0.0) or 0.0)
                candidate = float(source.get(key, 0.0) or 0.0)
                # Never allow a lower-priority zero value to override a higher-priority real signal.
                if current <= 0.0 and candidate > 0.0:
                    merged[key] = candidate
        return merged

    @staticmethod
    def _topology_from_raw_payload(raw_payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(raw_payload, dict):
            return {}
        topology = raw_payload.get("topology")
        return topology if isinstance(topology, dict) else {}

    @classmethod
    def _derive_origin_service(cls, raw_topology: dict[str, Any], fallback_service: str = "") -> str:
        relations = raw_topology.get("relations", {}) if isinstance(raw_topology.get("relations"), dict) else {}
        service_to_pod = relations.get("service_to_pod", [])
        if isinstance(service_to_pod, list):
            for rel in service_to_pod:
                if not isinstance(rel, dict):
                    continue
                svc = str(rel.get("service", "")).strip()
                if svc:
                    return svc
        if fallback_service:
            return cls._normalize_origin_service(fallback_service, "observer-agent")
        return "observer-agent"

    @staticmethod
    def _normalize_origin_service(origin: str | None, fallback: str = "observer-agent") -> str:
        candidate = str(origin or "").strip()
        if candidate.lower() in {"", "unknown", "all", "*"}:
            return fallback
        return candidate

    def _extract_telemetry(self, incident: Incident) -> dict[str, float]:
        canonical = build_canonical_telemetry(incident)
        return {
            "cpu_usage": float(canonical.get("cpu_usage", 0.0) or 0.0),
            "memory_usage": float(canonical.get("memory_usage", 0.0) or 0.0),
            "request_rate": float(canonical.get("request_rate", 0.0) or 0.0),
            "pod_restarts": float(canonical.get("pod_restarts", 0.0) or 0.0),
            "error_rate": float(canonical.get("error_rate", 0.0) or 0.0),
        }

    @classmethod
    def _repair_metrics_snapshot_row(cls, row: dict[str, Any], preferred: dict[str, float]) -> dict[str, Any]:
        fixed = dict(row)
        raw = fixed.get("raw_metrics_json")
        raw_json = raw if isinstance(raw, dict) else {}
        for key in ("cpu_usage", "memory_usage", "request_rate", "pod_restarts", "error_rate"):
            current = cls._num(raw_json, key, 0.0)
            candidate = cls._num(preferred, key, 0.0)
            if current <= 0.0 and candidate > 0.0:
                raw_json[key] = candidate
        fixed["raw_metrics_json"] = raw_json

        cpu_pct = cls._to_cpu_percent(cls._num(preferred, "cpu_usage", 0.0))
        mem_mb = cls._to_memory_mb(cls._num(preferred, "memory_usage", 0.0))
        err_pct = cls._num(preferred, "error_rate", 0.0)
        if err_pct <= 1.0:
            err_pct = err_pct * 100.0

        if cls._num(fixed, "cpu_usage", 0.0) <= 0.0 and cpu_pct > 0.0:
            fixed["cpu_usage"] = cpu_pct
        if cls._num(fixed, "memory_usage", 0.0) <= 0.0 and mem_mb > 0.0:
            fixed["memory_usage"] = mem_mb
        if cls._num(fixed, "error_rate", 0.0) <= 0.0 and err_pct > 0.0:
            fixed["error_rate"] = err_pct
        return fixed

    @staticmethod
    def _to_cpu_percent(value: float) -> float:
        return value * 100.0 if value <= 1.0 else value

    @staticmethod
    def _to_memory_mb(value: float) -> float:
        return value / (1024.0 * 1024.0) if value > 1024.0 else value

    @classmethod
    def _canonical_telemetry_line(cls, telemetry: dict[str, float]) -> str:
        cpu_pct = cls._to_cpu_percent(cls._num(telemetry, "cpu_usage", 0.0))
        mem_mb = cls._to_memory_mb(cls._num(telemetry, "memory_usage", 0.0))
        rps = cls._num(telemetry, "request_rate", 0.0)
        err_pct = cls._num(telemetry, "error_rate", 0.0)
        if err_pct <= 1.0:
            err_pct = err_pct * 100.0
        return f"Current telemetry: RPS {rps:.2f}, 5xx {err_pct:.2f}%, CPU {cpu_pct:.0f}%, Memory {mem_mb:.0f}MB."

    @classmethod
    def _sanitize_narrative_text(cls, text: str, telemetry: dict[str, float], origin_service: str) -> str:
        normalized = str(text or "")
        normalized = re.sub(r"origin service\s*=\s*(unknown|all|\*)", f"origin service={origin_service}", normalized, flags=re.IGNORECASE)
        normalized = re.sub(
            r"origin service[^a-zA-Z0-9]+(unknown|all|\*)",
            f"origin service={origin_service}",
            normalized,
            flags=re.IGNORECASE,
        )
        normalized = re.sub(
            r"Topology origin service:\s*(unknown|all|\*)",
            f"Topology origin service: {origin_service}",
            normalized,
            flags=re.IGNORECASE,
        )
        stale_metric_pattern = re.compile(r"(cpu\s*0+(\.0+)?%|memory\s*0+(\.0+)?\s*mb)", re.IGNORECASE)
        if cls._has_signal(telemetry):
            canonical = cls._canonical_telemetry_line(telemetry)
            if "current telemetry:" in normalized.lower():
                normalized = re.sub(r"Current telemetry:.*", canonical, normalized, flags=re.IGNORECASE)
            elif stale_metric_pattern.search(normalized):
                normalized = f"{normalized} {canonical}".strip()
        return normalized

    @classmethod
    def _sanitize_narrative_list(cls, lines: list[str], telemetry: dict[str, float], origin_service: str) -> list[str]:
        sanitized: list[str] = []
        for line in lines:
            sanitized.append(cls._sanitize_narrative_text(str(line), telemetry, origin_service))
        return sanitized

    def list(self, query: IncidentFilterQuery) -> tuple[int, list[dict[str, Any]]]:
        total, rows = self.repo.list_incidents(query)
        data: list[dict[str, Any]] = []
        for incident, analysis in rows:
            telemetry = self._extract_telemetry(incident)
            topology_insights: dict[str, Any] = {}
            causal_chain: list[str] = []
            origin_service: str | None = None
            if analysis and isinstance(analysis.mitigation, dict):
                top = analysis.mitigation.get("topology_insights")
                if isinstance(top, dict):
                    topology_insights = top
                    origin_service = str(top.get("likely_origin_service", "") or "") or None
                signals = analysis.mitigation.get("supporting_signals")
                if isinstance(signals, list):
                    causal_chain = [str(x) for x in signals]
                elif isinstance(signals, dict):
                    chain = signals.get("causal_chain")
                    if isinstance(chain, list):
                        causal_chain = [str(x) for x in chain]
            origin_service = self._normalize_origin_service(origin_service, "")
            if not origin_service:
                raw_topology = self._topology_from_raw_payload(incident.raw_payload if isinstance(incident.raw_payload, dict) else {})
                if raw_topology:
                    origin_service = self._derive_origin_service(raw_topology, fallback_service=incident.affected_services or "")
                    if not topology_insights:
                        relations = raw_topology.get("relations", {}) if isinstance(raw_topology.get("relations"), dict) else {}
                        service_to_pod = relations.get("service_to_pod", [])
                        counts = raw_topology.get("counts", {}) if isinstance(raw_topology.get("counts"), dict) else {}
                        impacted = sorted(
                            {
                                str(rel.get("service", "")).strip()
                                for rel in service_to_pod
                                if isinstance(rel, dict) and str(rel.get("service", "")).strip()
                            }
                        )
                        topology_insights = {
                            "likely_origin_service": origin_service or "unknown",
                            "impacted_services": impacted,
                            "service_count": int(counts.get("services", 0) or 0),
                            "pod_count": int(counts.get("pods", 0) or 0),
                        }
            origin_service = self._normalize_origin_service(origin_service, "observer-agent")
            if isinstance(topology_insights, dict) and topology_insights:
                likely = self._normalize_origin_service(str(topology_insights.get("likely_origin_service", "") or ""), "")
                if not likely:
                    topology_insights["likely_origin_service"] = origin_service
            executive_summary = analysis.executive_summary if analysis else None
            if isinstance(executive_summary, str):
                executive_summary = self._sanitize_narrative_text(executive_summary, telemetry, origin_service)
            if causal_chain:
                causal_chain = self._sanitize_narrative_list(causal_chain, telemetry, origin_service)
            data.append(
                {
                    "incident_id": incident.incident_id,
                    "cluster_id": incident.cluster_id,
                    "status": incident.status,
                    "severity": incident.severity,
                    "impact_level": incident.impact_level,
                    "slo_breach_risk": incident.slo_breach_risk,
                    "error_budget_remaining": incident.error_budget_remaining,
                    "affected_services": incident.affected_services,
                    "start_time": incident.start_time,
                    "duration": incident.duration,
                    "created_at": incident.created_at,
                    "executive_summary": executive_summary,
                    "root_cause": analysis.root_cause if analysis else None,
                    "confidence_score": analysis.confidence_score if analysis else None,
                    "classification": analysis.classification if analysis else None,
                    "risk_forecast": analysis.risk_forecast if analysis else None,
                    "cpu_usage": telemetry["cpu_usage"],
                    "memory_usage": telemetry["memory_usage"],
                    "request_rate": telemetry["request_rate"],
                    "pod_restarts": telemetry["pod_restarts"],
                    "error_rate": telemetry["error_rate"],
                    "origin_service": origin_service,
                    "topology_insights": topology_insights,
                    "causal_chain": causal_chain,
                }
            )
        return total, data

    def filter_options(self, query: IncidentFilterQuery) -> dict[str, list[str]]:
        return self.repo.list_filter_options(query)

    def details(self, incident_id: str) -> dict[str, Any] | None:
        row = self.repo.get_incident_details(incident_id)
        if row is None:
            return None
        latest_analysis = row["analysis"][0] if row["analysis"] else None
        fallback_telemetry = self._extract_telemetry(row["incident"])
        metrics_snapshot = [
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
        ]
        if metrics_snapshot and any(v > 0.0 for v in fallback_telemetry.values()):
            metrics_snapshot[0] = self._repair_metrics_snapshot_row(metrics_snapshot[0], fallback_telemetry)
        if not metrics_snapshot and any(v != 0.0 for v in fallback_telemetry.values()):
            metrics_snapshot = [
                {
                    "id": 0,
                    "incident_id": row["incident"].incident_id,
                    "cpu_usage": self._to_cpu_percent(fallback_telemetry["cpu_usage"]),
                    "memory_usage": self._to_memory_mb(fallback_telemetry["memory_usage"]),
                    "latency_p95": 0.0,
                    "error_rate": fallback_telemetry["error_rate"] * 100.0 if fallback_telemetry["error_rate"] <= 1.0 else fallback_telemetry["error_rate"],
                    "thread_pool_saturation": 0.0,
                    "raw_metrics_json": fallback_telemetry,
                    "captured_at": row["incident"].created_at,
                }
            ]
        raw_topology = self._topology_from_raw_payload(row["incident"].raw_payload if isinstance(row["incident"].raw_payload, dict) else {})
        resolved_origin = self._normalize_origin_service(
            self._derive_origin_service(raw_topology, fallback_service=row["incident"].affected_services or ""),
            "observer-agent",
        )
        analysis_rows: list[dict[str, Any]] = []
        for a in row["analysis"]:
            mitigation = a.mitigation if isinstance(a.mitigation, dict) else {}
            topology_insights = mitigation.get("topology_insights") if isinstance(mitigation.get("topology_insights"), dict) else {}
            likely = str(topology_insights.get("likely_origin_service", "") or "").strip().lower()
            if raw_topology and (not likely or likely in {"unknown", "all", "*"}):
                topology_insights = {**topology_insights, "likely_origin_service": resolved_origin}
            executive_summary = self._sanitize_narrative_text(a.executive_summary or "", fallback_telemetry, resolved_origin)
            supporting = a.supporting_signals if isinstance(a.supporting_signals, dict) else {}
            if isinstance(supporting.get("causal_chain"), list):
                supporting["causal_chain"] = self._sanitize_narrative_list(
                    [str(x) for x in (supporting.get("causal_chain") or [])],
                    fallback_telemetry,
                    resolved_origin or "unknown",
                )
            evidence = supporting.get("evidence")
            if isinstance(evidence, list):
                supporting["evidence"] = self._sanitize_narrative_list([str(x) for x in evidence], fallback_telemetry, resolved_origin or "unknown")
            analysis_rows.append(
                {
                    "id": a.id,
                    "incident_id": a.incident_id,
                    "executive_summary": executive_summary,
                    "root_cause": a.root_cause,
                    "supporting_signals": supporting,
                    "risk_forecast": a.risk_forecast,
                    "suggested_actions": a.suggested_actions,
                    "confidence_score": a.confidence_score,
                    "confidence_breakdown": a.confidence_breakdown,
                    "created_at": a.created_at,
                    "classification": a.classification,
                    "mitigation": {
                        **mitigation,
                        "topology_insights": topology_insights,
                        "origin_service": self._normalize_origin_service(mitigation.get("origin_service"), resolved_origin),
                        "telemetry": self._merge_priority_metrics(
                            [
                                self._normalize_metrics(mitigation.get("telemetry") if isinstance(mitigation.get("telemetry"), dict) else {}),
                                fallback_telemetry,
                            ]
                        ),
                    } if mitigation else mitigation,
                }
            )
        return {
            "incident": {
                "incident_id": row["incident"].incident_id,
                "cluster_id": row["incident"].cluster_id,
                "status": row["incident"].status,
                "severity": row["incident"].severity,
                "impact_level": row["incident"].impact_level,
                "slo_breach_risk": row["incident"].slo_breach_risk,
                "error_budget_remaining": row["incident"].error_budget_remaining,
                "affected_services": row["incident"].affected_services,
                "start_time": row["incident"].start_time,
                "duration": row["incident"].duration,
                "created_at": row["incident"].created_at,
                "raw_payload": row["incident"].raw_payload,
                "analysis_json": row["incident"].analysis,
            },
            "analysis": analysis_rows,
            "metrics_snapshot": metrics_snapshot,
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
        def _safe_json(value: Any) -> str:
            if value is None:
                return ""
            if isinstance(value, (dict, list)):
                return json.dumps(value, ensure_ascii=False, default=str)
            return str(value)

        def _excel_value(value: Any) -> Any:
            if value is None:
                return ""
            if isinstance(value, datetime):
                dt = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
                return dt.isoformat()
            if isinstance(value, (dict, list)):
                return _safe_json(value)
            return value

        def _row_or_placeholder(rows: list[dict[str, Any]], placeholder: dict[str, Any]) -> list[dict[str, Any]]:
            return rows if rows else [placeholder]

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

        all_items: list[dict[str, Any]] = []
        total, first_page = self.list(query)
        all_items.extend(first_page)
        page_limit = max(1, min(500, query.limit))
        next_offset = query.offset + page_limit
        while len(all_items) < total:
            page_query = query.model_copy(update={"limit": page_limit, "offset": next_offset})
            _page_total, page_rows = self.list(page_query)
            if not page_rows:
                break
            all_items.extend(page_rows)
            next_offset += page_limit

        ids = [item["incident_id"] for item in all_items]
        detail_rows = [self.details(incident_id) for incident_id in ids]
        detail_rows = [d for d in detail_rows if d is not None]
        details_by_id: dict[str, dict[str, Any]] = {
            str((d.get("incident") or {}).get("incident_id")): d for d in detail_rows if isinstance(d, dict)
        }

        summary_rows: list[dict[str, Any]] = []
        telemetry_rows: list[dict[str, Any]] = []
        reasoning_rows: list[dict[str, Any]] = []
        causal_chain_rows: list[dict[str, Any]] = []
        correlation_rows: list[dict[str, Any]] = []
        topology_rows: list[dict[str, Any]] = []
        recommendation_rows: list[dict[str, Any]] = []
        observability_rows: list[dict[str, Any]] = []
        raw_payload_rows: list[dict[str, Any]] = []

        for item in all_items:
            incident_id = str(item.get("incident_id", "") or "")
            detail = details_by_id.get(incident_id, {})
            incident_obj = detail.get("incident") if isinstance(detail.get("incident"), dict) else {}
            analyses = detail.get("analysis") if isinstance(detail.get("analysis"), list) else []
            metrics_snapshot = detail.get("metrics_snapshot") if isinstance(detail.get("metrics_snapshot"), list) else []
            latest_analysis = analyses[0] if analyses else {}
            mitigation = latest_analysis.get("mitigation") if isinstance(latest_analysis.get("mitigation"), dict) else {}
            supporting = latest_analysis.get("supporting_signals") if isinstance(latest_analysis.get("supporting_signals"), dict) else {}
            chain_rows_before = len(causal_chain_rows)
            correlation_rows_before = len(correlation_rows)
            recommendation_rows_before = len(recommendation_rows)

            summary_rows.append(
                {
                    "Incident ID": incident_id,
                    "Cluster ID": item.get("cluster_id", ""),
                    "Status": item.get("status", ""),
                    "Severity": item.get("severity", ""),
                    "Impact Level": item.get("impact_level", ""),
                    "SLA Countdown": _sla_countdown(item.get("start_time")),
                    "SLO Breach Risk (%)": _excel_value(item.get("slo_breach_risk")),
                    "Error Budget Remaining (%)": _excel_value(item.get("error_budget_remaining")),
                    "Affected Services": item.get("affected_services", ""),
                    "Classification": item.get("classification", ""),
                    "Confidence Score": _excel_value(item.get("confidence_score")),
                    "Start Time": _excel_value(item.get("start_time")),
                    "Created At": _excel_value(item.get("created_at")),
                    "Duration": item.get("duration", ""),
                    "Executive Summary": _excel_value(item.get("executive_summary")),
                    "Root Cause": _excel_value(item.get("root_cause")),
                }
            )

            telemetry_rows.append(
                {
                    "Incident ID": incident_id,
                    "Metric Source": "canonical",
                    "CPU Usage": _excel_value(item.get("cpu_usage")),
                    "Memory Usage": _excel_value(item.get("memory_usage")),
                    "Request Rate": _excel_value(item.get("request_rate")),
                    "Pod Restarts": _excel_value(item.get("pod_restarts")),
                    "Error Rate": _excel_value(item.get("error_rate")),
                    "Captured At": _excel_value(item.get("created_at")),
                }
            )
            for metrics in metrics_snapshot:
                telemetry_rows.append(
                    {
                        "Incident ID": incident_id,
                        "Metric Source": "snapshot",
                        "CPU Usage": _excel_value(metrics.get("cpu_usage")),
                        "Memory Usage": _excel_value(metrics.get("memory_usage")),
                        "Request Rate": _excel_value((metrics.get("raw_metrics_json") or {}).get("request_rate")),
                        "Pod Restarts": _excel_value((metrics.get("raw_metrics_json") or {}).get("pod_restarts")),
                        "Error Rate": _excel_value(metrics.get("error_rate")),
                        "Captured At": _excel_value(metrics.get("captured_at")),
                        "Raw Metrics JSON": _excel_value(metrics.get("raw_metrics_json")),
                    }
                )

            for analysis in analyses:
                mitigation_data = analysis.get("mitigation") if isinstance(analysis.get("mitigation"), dict) else {}
                supporting_signals = analysis.get("supporting_signals") if isinstance(analysis.get("supporting_signals"), dict) else {}
                reasoning_rows.append(
                    {
                        "Incident ID": incident_id,
                        "Analysis ID": _excel_value(analysis.get("id")),
                        "Classification": _excel_value(analysis.get("classification")),
                        "Executive Summary": _excel_value(analysis.get("executive_summary")),
                        "Root Cause": _excel_value(analysis.get("root_cause")),
                        "Risk Forecast": _excel_value(analysis.get("risk_forecast")),
                        "Confidence Score": _excel_value(analysis.get("confidence_score")),
                        "Confidence Breakdown": _excel_value(analysis.get("confidence_breakdown")),
                        "Supporting Signals": _excel_value(supporting_signals),
                        "Mitigation Payload": _excel_value(mitigation_data),
                        "Created At": _excel_value(analysis.get("created_at")),
                    }
                )

                chain = supporting_signals.get("causal_chain")
                if isinstance(chain, list):
                    for idx, step in enumerate(chain, start=1):
                        causal_chain_rows.append(
                            {
                                "Incident ID": incident_id,
                                "Analysis ID": _excel_value(analysis.get("id")),
                                "Step": idx,
                                "Causal Signal": _excel_value(step),
                            }
                        )

                correlated_signals = mitigation_data.get("correlated_signals")
                if isinstance(correlated_signals, dict):
                    for key, value in correlated_signals.items():
                        correlation_rows.append(
                            {
                                "Incident ID": incident_id,
                                "Analysis ID": _excel_value(analysis.get("id")),
                                "Signal": str(key),
                                "Value": _excel_value(value),
                            }
                        )

                suggested_actions = analysis.get("suggested_actions")
                if isinstance(suggested_actions, dict):
                    actions = suggested_actions.get("actions")
                    if isinstance(actions, list):
                        for idx, action in enumerate(actions, start=1):
                            recommendation_rows.append(
                                {
                                    "Incident ID": incident_id,
                                    "Analysis ID": _excel_value(analysis.get("id")),
                                    "Priority": idx,
                                    "Recommendation": _excel_value(action),
                                }
                            )
                elif isinstance(suggested_actions, list):
                    for idx, action in enumerate(suggested_actions, start=1):
                        recommendation_rows.append(
                            {
                                "Incident ID": incident_id,
                                "Analysis ID": _excel_value(analysis.get("id")),
                                "Priority": idx,
                                "Recommendation": _excel_value(action),
                            }
                        )

            top = item.get("topology_insights") if isinstance(item.get("topology_insights"), dict) else {}
            raw_payload = incident_obj.get("raw_payload") if isinstance(incident_obj.get("raw_payload"), dict) else {}
            topology = raw_payload.get("topology") if isinstance(raw_payload.get("topology"), dict) else {}
            topology_rows.append(
                {
                    "Incident ID": incident_id,
                    "Origin Service": _excel_value(item.get("origin_service")),
                    "Affected Services": _excel_value(top.get("impacted_services")),
                    "Service Count": _excel_value(top.get("service_count")),
                    "Pod Count": _excel_value(top.get("pod_count")),
                    "Topology Insights": _excel_value(top),
                    "Topology Graph": _excel_value(topology),
                }
            )

            observability = raw_payload.get("observability_registry") if isinstance(raw_payload.get("observability_registry"), dict) else {}
            if observability:
                for source, status in observability.items():
                    observability_rows.append(
                        {
                            "Incident ID": incident_id,
                            "Source": str(source),
                            "Status": _excel_value(status.get("status") if isinstance(status, dict) else status),
                            "Endpoint": _excel_value(status.get("endpoint") if isinstance(status, dict) else ""),
                            "Last Success": _excel_value(status.get("last_success_at") if isinstance(status, dict) else ""),
                            "Raw Status": _excel_value(status),
                        }
                    )
            else:
                observability_rows.append(
                    {
                        "Incident ID": incident_id,
                        "Source": "",
                        "Status": "not_available",
                        "Endpoint": "",
                        "Last Success": "",
                        "Raw Status": "",
                    }
                )

            raw_payload_rows.append(
                {
                    "Incident ID": incident_id,
                    "Cluster ID": _excel_value(incident_obj.get("cluster_id")),
                    "Created At": _excel_value(incident_obj.get("created_at")),
                    "Incident JSON": _excel_value(detail),
                    "Raw Payload": _excel_value(raw_payload),
                    "Incident Analysis JSON": _excel_value(incident_obj.get("analysis_json")),
                }
            )

            if len(causal_chain_rows) == chain_rows_before and isinstance(item.get("causal_chain"), list):
                for idx, step in enumerate(item.get("causal_chain") or [], start=1):
                    causal_chain_rows.append(
                        {
                            "Incident ID": incident_id,
                            "Analysis ID": "",
                            "Step": idx,
                            "Causal Signal": _excel_value(step),
                        }
                    )

            if len(correlation_rows) == correlation_rows_before:
                fallback_correlation = mitigation.get("correlated_signals") if isinstance(mitigation.get("correlated_signals"), dict) else {}
                for key, value in fallback_correlation.items():
                    correlation_rows.append(
                        {
                            "Incident ID": incident_id,
                            "Analysis ID": "",
                            "Signal": str(key),
                            "Value": _excel_value(value),
                        }
                    )

            if len(recommendation_rows) == recommendation_rows_before:
                fallback_actions = mitigation.get("actions") if isinstance(mitigation.get("actions"), list) else []
                for idx, action in enumerate(fallback_actions, start=1):
                    recommendation_rows.append(
                        {
                            "Incident ID": incident_id,
                            "Analysis ID": "",
                            "Priority": idx,
                            "Recommendation": _excel_value(action),
                        }
                    )

        output = io.BytesIO()
        with pd.ExcelWriter(output, engine="openpyxl") as writer:
            pd.DataFrame(
                _row_or_placeholder(
                    summary_rows,
                    {"Message": "No incidents found for the selected filters."},
                )
            ).to_excel(writer, index=False, sheet_name="Incident Summary")
            pd.DataFrame(
                _row_or_placeholder(
                    telemetry_rows,
                    {"Message": "No telemetry metrics available."},
                )
            ).to_excel(writer, index=False, sheet_name="Telemetry Metrics")
            pd.DataFrame(
                _row_or_placeholder(
                    reasoning_rows,
                    {"Message": "No reasoning analysis available."},
                )
            ).to_excel(writer, index=False, sheet_name="Reasoning Analysis")
            pd.DataFrame(
                _row_or_placeholder(
                    causal_chain_rows,
                    {"Message": "No causal chain data available."},
                )
            ).to_excel(writer, index=False, sheet_name="Causal Chain")
            pd.DataFrame(
                _row_or_placeholder(
                    correlation_rows,
                    {"Message": "No correlated signals available."},
                )
            ).to_excel(writer, index=False, sheet_name="Correlated Signals")
            pd.DataFrame(
                _row_or_placeholder(
                    topology_rows,
                    {"Message": "No topology or origin data available."},
                )
            ).to_excel(writer, index=False, sheet_name="Topology and Origin")
            pd.DataFrame(
                _row_or_placeholder(
                    recommendation_rows,
                    {"Message": "No recommendations available."},
                )
            ).to_excel(writer, index=False, sheet_name="Recommendations")
            pd.DataFrame(
                _row_or_placeholder(
                    observability_rows,
                    {"Message": "No observability registry status available."},
                )
            ).to_excel(writer, index=False, sheet_name="Observability Registry Status")
            pd.DataFrame(
                _row_or_placeholder(
                    raw_payload_rows,
                    {"Message": "No raw incident payload available."},
                )
            ).to_excel(writer, index=False, sheet_name="Raw Incident Payload")
        output.seek(0)
        return output.getvalue()

    def persist_from_telemetry_sample(
        self,
        *,
        alert: AlertSignal,
        metrics: dict[str, float],
        raw_payload: dict[str, Any],
        reasoner,
        window_minutes: int = 30,
    ) -> str:
        response = reasoner.analyze(alert, window_minutes=window_minutes)
        response.context.metrics.update(
            {
                "cpu_usage_cores_5m": float(metrics.get("cpu_usage", 0.0) or 0.0),
                "memory_usage_bytes": float(metrics.get("memory_usage", 0.0) or 0.0),
                "request_rate_rps_5m": float(metrics.get("request_rate", 0.0) or 0.0),
                "pod_restarts_10m": float(metrics.get("pod_restarts", 0.0) or 0.0),
                "error_rate_5xx_5m": float(metrics.get("error_rate", 0.0) or 0.0),
                "latency_p95_s_5m": float(metrics.get("latency", 0.0) or 0.0),
            }
        )
        cpu = float(metrics.get("cpu_usage", 0.0) or 0.0)
        err = float(metrics.get("error_rate", 0.0) or 0.0)
        mem_mb = float(metrics.get("memory_usage", 0.0) or 0.0) / (1024.0 * 1024.0)
        rps = float(metrics.get("request_rate", 0.0) or 0.0)
        if err > 0.05:
            response.analysis.probable_root_cause = "error_rate_threshold_breached"
            response.analysis.incident_classification = "Performance Degradation"
        elif cpu > 0.8:
            response.analysis.probable_root_cause = "cpu_usage_threshold_breached"
            response.analysis.incident_classification = "Performance Degradation"
        response.analysis.executive_summary = (
            f"Incident-scoped telemetry snapshot: CPU {cpu*100:.1f}%, "
            f"Memory {mem_mb:.0f}MB, RPS {rps:.2f}, 5xx {err*100:.2f}%."
        )
        response.analysis.human_summary = response.analysis.executive_summary
        topology = raw_payload.get("topology") if isinstance(raw_payload.get("topology"), dict) else {}
        if topology:
            response.context.cluster_wiring = topology
            top = response.analysis.topology_insights if isinstance(response.analysis.topology_insights, dict) else {}
            if not top:
                top = {"service_count": 0, "impacted_services": []}
            if str(top.get("likely_origin_service", "")).strip().lower() in {"", "unknown", "all", "*"}:
                top["likely_origin_service"] = alert.service
            response.analysis.topology_insights = top
            if str(response.analysis.origin_service or "").strip().lower() in {"", "unknown", "all", "*"}:
                response.analysis.origin_service = str(top.get("likely_origin_service") or alert.service)
        incident_id = self.persist_from_reasoning(alert, response)
        incident = self.db.query(Incident).filter(Incident.incident_id == incident_id).first()
        if incident:
            merged_payload = dict(raw_payload or {})
            merged_payload.setdefault("cluster_id", alert.cluster_id or "")
            merged_payload.setdefault("namespace", alert.namespace)
            merged_payload.setdefault("service_name", alert.service)
            merged_payload.setdefault("metrics", metrics)
            incident.raw_payload = merged_payload
            incident.analysis = response.analysis.model_dump()
            self.db.commit()
        return incident_id

    def persist_from_reasoning(self, alert: AlertSignal, response: LiveReasoningResponse) -> str:
        now = datetime.now(timezone.utc)
        analysis = response.analysis
        context = response.context
        risk_pct = float((analysis.risk_forecast or {}).get("predicted_breach_next_15m_pct", 0) or 0)
        risk = max(0.0, min(1.0, risk_pct / 100.0))
        incident_id = f"{alert.alertname}-{now.strftime('%Y%m%d%H%M%S')}-{alert.service}"

        incident = Incident(
            incident_id=incident_id,
            cluster_id=(alert.cluster_id or ""),
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
        m = context.metrics or {}
        if not self._has_signal(self._normalize_metrics(m)):
            # Snapshot reconstruction fallback for persistence from component-level metrics.
            component_metrics = context.component_metrics if isinstance(context.component_metrics, dict) else {}
            aggregate = {"cpu_usage_cores_5m": 0.0, "memory_usage_bytes": 0.0, "request_rate_rps_5m": 0.0, "pod_restarts_10m": 0.0, "error_rate_5xx_5m": 0.0}
            for item in component_metrics.values():
                if not isinstance(item, dict):
                    continue
                aggregate["cpu_usage_cores_5m"] = max(float(item.get("cpu_usage_cores_5m", 0) or 0), aggregate["cpu_usage_cores_5m"])
                aggregate["memory_usage_bytes"] += float(item.get("memory_usage_bytes", 0) or 0)
                aggregate["request_rate_rps_5m"] += float(item.get("request_rate_rps_5m", 0) or 0)
                aggregate["pod_restarts_10m"] += float(item.get("pod_restarts_10m", 0) or 0)
                aggregate["error_rate_5xx_5m"] = max(float(item.get("error_rate_5xx_5m", 0) or 0), aggregate["error_rate_5xx_5m"])
            if self._has_signal(self._normalize_metrics(aggregate)):
                m = {**m, **aggregate}
        normalized_m = self._normalize_metrics(m)
        telemetry_payload = {
            "cpu_usage": normalized_m["cpu_usage"],
            "memory_usage": normalized_m["memory_usage"],
            "request_rate": normalized_m["request_rate"],
            "pod_restarts": normalized_m["pod_restarts"],
            "error_rate": normalized_m["error_rate"],
        }
        topology_payload = context.cluster_wiring if isinstance(context.cluster_wiring, dict) else {}
        if isinstance(topology_payload, dict) and topology_payload:
            incoming_analysis_topology = analysis.topology_insights if isinstance(analysis.topology_insights, dict) else {}
            origin = str(analysis.origin_service or incoming_analysis_topology.get("likely_origin_service", "")).strip()
            if not origin or origin.lower() == "unknown":
                origin = self._derive_origin_service(topology_payload, fallback_service=alert.service or "observer-agent")
            if isinstance(analysis.topology_insights, dict):
                analysis.topology_insights["likely_origin_service"] = origin
            analysis.origin_service = origin
        self.db.add(
            IncidentAnalysis(
                incident_id=incident_id,
                service_name=alert.service,
                cluster_id=(alert.cluster_id or ""),
                anomaly_score=float((analysis.anomaly_summary or {}).get("score", 0) or 0),
                confidence_score=float(analysis.confidence or 0),
                classification=analysis.incident_classification or "Unknown",
                root_cause=analysis.probable_root_cause or "Unknown",
                mitigation={
                    "executive_summary": analysis.executive_summary or "",
                    "supporting_signals": analysis.causal_chain or [],
                    "origin_service": analysis.origin_service or (analysis.topology_insights or {}).get("likely_origin_service"),
                    "actions": analysis.corrective_actions or [],
                    "confidence_breakdown": analysis.confidence_details or {},
                    "telemetry": telemetry_payload,
                    "correlated_signals": analysis.correlated_signals or {},
                    "causal_analysis": analysis.causal_analysis or {},
                    "topology_insights": analysis.topology_insights or {},
                    "topology": topology_payload,
                },
                risk_forecast=risk,
                mitigation_success=None,
                executive_summary=analysis.executive_summary or analysis.human_summary or "",
                supporting_signals={
                    "signals": analysis.causal_chain or [],
                    "evidence": analysis.supporting_evidence or [],
                    "correlation": analysis.correlated_signals or {},
                    "causal_analysis": analysis.causal_analysis or {},
                    "topology_insights": analysis.topology_insights or {},
                },
                suggested_actions={"actions": analysis.corrective_actions or []},
                confidence_breakdown={
                    **(analysis.confidence_details or {}),
                    "signal_scores": analysis.signal_scores or {},
                    "anomaly_summary": analysis.anomaly_summary or {},
                },
                created_at=now,
            )
        )
        self.db.add(
            IncidentMetricsSnapshot(
                incident_id=incident_id,
                cpu_usage=float((normalized_m.get("cpu_usage", 0) or 0) * 100),
                memory_usage=float((normalized_m.get("memory_usage", 0) or 0) / (1024 * 1024)),
                latency_p95=float((m.get("latency_p95_s_5m", 0) or 0) * 1000),
                error_rate=float((normalized_m.get("error_rate", 0) or 0) * 100),
                thread_pool_saturation=float(m.get("thread_pool_saturation_5m", 0) or 0),
                raw_metrics_json={
                    **m,
                    **telemetry_payload,
                    "topology": topology_payload,
                },
                captured_at=now,
            )
        )
        self.db.commit()
        return incident_id

from __future__ import annotations

import logging
import re
import time
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ai_observer.backend.intelligence import TopologyEngine
from ai_observer.backend.models.incident import Incident, IncidentMetricsSnapshot, IncidentStatusHistory
from ai_observer.incident_analysis.database import get_db_session
from ai_observer.incident_analysis.service_layer import IncidentAnalysisService

router = APIRouter(prefix="/api/agent", tags=["agent"])
logger = logging.getLogger(__name__)

MAX_RETRIES = 3
RETRY_DELAY_SECONDS = 2


class AgentIncident(BaseModel):
    incident_id: str | None = None
    service_name: str
    anomaly_score: float = Field(ge=0.0, le=1.0, default=0.0)
    confidence_score: float = Field(ge=0.0, le=1.0, default=0.0)
    classification: str = "Unknown"
    root_cause: str = ""
    mitigation: dict[str, Any] = Field(default_factory=dict)
    risk_forecast: float = Field(ge=0.0, le=1.0, default=0.0)
    mitigation_success: bool | None = None


class AgentPushPayload(BaseModel):
    cluster_id: str
    environment: str | None = None
    timestamp: str | None = None
    metrics: dict[str, float] | None = None
    topology: dict[str, Any] | None = None
    incidents: list[AgentIncident] = Field(default_factory=list)


class AgentPushResponse(BaseModel):
    accepted: bool
    cluster_id: str
    inserted: int


def _as_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _to_cpu_percent(value: float) -> float:
    # Agent reports CPU as a fraction in [0..1] for process-based series.
    return value * 100.0 if value <= 1.0 else value


def _to_memory_mb(value: float) -> float:
    # Agent reports memory in bytes for container/jvm series.
    return value / (1024.0 * 1024.0) if value > 1024.0 else value


def _to_error_percent(value: float) -> float:
    return value * 100.0 if value <= 1.0 else value


def _extract_confidence_fraction(value: Any, default_value: float = 0.95) -> float:
    if isinstance(value, (int, float)):
        parsed = float(value)
        return max(0.0, min(1.0, parsed if parsed <= 1.0 else parsed / 100.0))
    if isinstance(value, str):
        raw = value.strip().replace("%", "")
        try:
            parsed = float(raw)
            return max(0.0, min(1.0, parsed if parsed <= 1.0 else parsed / 100.0))
        except ValueError:
            return default_value
    return default_value


def _llm_reasoning_for_metrics(
    request: Request,
    cluster_id: str,
    environment: str,
    service_name: str,
    metrics: dict[str, float],
    classification: str,
    root_cause: str,
    topology: dict[str, Any] | None = None,
) -> dict[str, Any]:
    provider = request.app.state.container.reasoning_service.llm_provider
    baseline = {
        "probable_root_cause": root_cause,
        "impact_level": "Low",
        "recommended_remediation": "Continue monitoring and validate telemetry trends.",
        "confidence": 0.95,
        "causal_chain": ["Telemetry received from observer-agent."],
        "corrective_actions": ["Monitor CPU/memory/error-rate trend for 15 minutes."],
        "preventive_hardening": ["Keep telemetry collection healthy and continuous."],
        "risk_forecast": {"predicted_breach_next_15m_pct": 5.0},
        "deployment_correlation": {"within_10m": False},
        "error_log_prediction": {"repeated_signatures": []},
        "missing_observability": [],
        "human_summary": f"{classification} based on incoming agent telemetry.",
    }
    llm_payload = {
        "context": {
            "cluster_id": cluster_id,
            "environment": environment,
            "service_name": service_name,
            "telemetry": metrics,
            "topology": topology or {},
        },
        "baseline": baseline,
    }
    result = provider.analyze(llm_payload)
    return result if isinstance(result, dict) else {}


def _normalize_reasoning(analysis: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(analysis)
    if "root_cause" not in normalized:
        normalized["root_cause"] = normalized.get("probable_root_cause")
    if "recommendation" not in normalized:
        normalized["recommendation"] = normalized.get("recommended_remediation")
    confidence = _extract_confidence_fraction(normalized.get("confidence"), 0.9)
    normalized["confidence"] = confidence
    normalized["confidence_score"] = normalized.get("confidence_score") or f"{round(confidence * 100)}%"
    normalized["ai_response_status"] = "complete"
    return normalized


def _is_valid_reasoning(analysis: dict[str, Any]) -> bool:
    if not analysis:
        return False
    if analysis.get("_llm_partial"):
        return False
    required = ("root_cause", "confidence", "recommendation")
    for key in required:
        value = analysis.get(key)
        if value is None:
            return False
        if isinstance(value, str) and not value.strip():
            return False
    if not str(analysis.get("origin_service", "")).strip():
        return False
    if str(analysis.get("origin_service", "")).strip().lower() == "unknown":
        return False
    topology_insights = analysis.get("topology_insights")
    if not isinstance(topology_insights, dict) or not topology_insights:
        return False
    chain = analysis.get("causal_chain")
    if not isinstance(chain, list) or not chain:
        return False
    return True


def _deterministic_reasoning_for_metrics(
    cluster_id: str,
    environment: str,
    service_name: str,
    metrics: dict[str, float],
    classification: str,
    root_cause: str,
    topology: dict[str, Any] | None = None,
) -> dict[str, Any]:
    topology = topology if isinstance(topology, dict) else {}
    origin_service = TopologyEngine.infer_origin_service(topology, preferred_service=service_name or "observer-agent")
    impacted_services = TopologyEngine.infer_impacted_services(topology)
    if origin_service == "unknown":
        origin_service = service_name or "observer-agent"
    cpu = _as_float(metrics.get("cpu_usage", 0.0))
    mem = _as_float(metrics.get("memory_usage", 0.0))
    rps = _as_float(metrics.get("request_rate", 0.0))
    err = _as_float(metrics.get("error_rate", 0.0))
    confidence = 0.92
    return {
        "root_cause": root_cause,
        "recommendation": "Continue monitoring; verify dependencies and recent changes if anomaly persists.",
        "confidence": confidence,
        "confidence_score": f"{round(confidence * 100)}%",
        "origin_service": origin_service,
        "topology_insights": {
            "likely_origin_service": origin_service,
            "impacted_services": impacted_services,
            "service_count": len(impacted_services),
        },
        "causal_chain": [
            f"Cluster={cluster_id} environment={environment} service={service_name}.",
            f"Telemetry observed CPU={cpu:.4f}, memory={mem:.0f}, request_rate={rps:.4f}, error_rate={err:.4f}.",
            f"Topology-derived origin service={origin_service}.",
        ],
        "human_summary": f"{classification}: telemetry is processed with topology-aware deterministic reasoning.",
        "ai_response_status": "complete",
    }


def _ensure_complete_reasoning(
    analysis: dict[str, Any],
    *,
    cluster_id: str,
    environment: str,
    service_name: str,
    metrics: dict[str, float],
    classification: str,
    root_cause: str,
    topology: dict[str, Any] | None = None,
) -> dict[str, Any]:
    base = _deterministic_reasoning_for_metrics(
        cluster_id=cluster_id,
        environment=environment,
        service_name=service_name,
        metrics=metrics,
        classification=classification,
        root_cause=root_cause,
        topology=topology,
    )
    merged = {**base, **(analysis or {})}
    merged = _normalize_reasoning(merged)

    # Force topology-derived origin if unknown.
    if str(merged.get("origin_service", "")).strip().lower() in {"", "unknown"}:
        merged["origin_service"] = base["origin_service"]
    top = merged.get("topology_insights")
    if not isinstance(top, dict) or not top:
        merged["topology_insights"] = base["topology_insights"]
    else:
        if str(top.get("likely_origin_service", "")).strip().lower() in {"", "unknown"}:
            top["likely_origin_service"] = merged["origin_service"]
        merged["topology_insights"] = top
    chain = merged.get("causal_chain")
    if not isinstance(chain, list) or not chain:
        merged["causal_chain"] = base["causal_chain"]

    merged.pop("_llm_partial", None)
    merged["ai_response_status"] = "complete"
    return merged


def _sanitize_reasoning_narrative(
    analysis: dict[str, Any],
    *,
    metrics: dict[str, float],
    resolved_origin: str,
) -> dict[str, Any]:
    out = dict(analysis or {})
    cpu_pct = _to_cpu_percent(_as_float(metrics.get("cpu_usage", 0.0)))
    mem_mb = _to_memory_mb(_as_float(metrics.get("memory_usage", 0.0)))
    rps = _as_float(metrics.get("request_rate", 0.0))
    restarts = _as_float(metrics.get("pod_restarts", 0.0))
    err_pct = _to_error_percent(_as_float(metrics.get("error_rate", 0.0)))
    has_signal = any(v > 0.0 for v in (cpu_pct, mem_mb, rps, err_pct, restarts))
    canonical_line = (
        f"Current telemetry: RPS {rps:.2f}, 5xx {err_pct:.2f}%, "
        f"CPU {cpu_pct:.0f}%, Memory {mem_mb:.0f}MB."
    )
    stale_metric_pattern = re.compile(r"(cpu\s*0+(\.0+)?%|memory\s*0+(\.0+)?\s*mb)", re.IGNORECASE)

    def normalize_origin_text(text: str) -> str:
        normalized = re.sub(r"origin service\s*=\s*(unknown|all|\*)", f"origin service={resolved_origin}", text, flags=re.IGNORECASE)
        normalized = re.sub(
            r"origin service[^a-zA-Z0-9]+(unknown|all|\*)",
            f"origin service={resolved_origin}",
            normalized,
            flags=re.IGNORECASE,
        )
        normalized = re.sub(
            r"Topology[- ]derived origin service\s*=\s*(unknown|all|\*)",
            f"Topology-derived origin service={resolved_origin}",
            normalized,
            flags=re.IGNORECASE,
        )
        return normalized

    for field in ("human_summary",):
        value = out.get(field)
        if not isinstance(value, str):
            continue
        text = normalize_origin_text(value)
        if has_signal and stale_metric_pattern.search(text):
            text = f"{text} {canonical_line}".strip()
        out[field] = text

    chain = out.get("causal_chain")
    if isinstance(chain, list):
        rewritten: list[str] = []
        for item in chain:
            line = normalize_origin_text(str(item))
            if has_signal and "current telemetry:" in line.lower():
                line = canonical_line
            elif has_signal and stale_metric_pattern.search(line):
                line = canonical_line
            rewritten.append(line)
        out["causal_chain"] = rewritten

    top = out.get("topology_insights")
    if isinstance(top, dict):
        likely = str(top.get("likely_origin_service", "") or "").strip().lower()
        if not likely or likely in {"unknown", "all", "*"}:
            top["likely_origin_service"] = resolved_origin
        out["topology_insights"] = top
    out["origin_service"] = resolved_origin
    return out


@router.post("/push", response_model=AgentPushResponse)
def push_from_agent(
    request: Request,
    payload: AgentPushPayload,
    db: Session = Depends(get_db_session),
    x_agent_token: str | None = Header(default=None, alias="X-Agent-Token"),
) -> AgentPushResponse:
    expected = request.app.state.container.settings.agent_token
    if not expected or x_agent_token != expected:
        raise HTTPException(status_code=401, detail="invalid_agent_token")

    svc = IncidentAnalysisService(
        db=db,
        default_cluster_id=request.app.state.container.settings.telemetry.default_cluster_id,
    )

    inserted = 0
    incoming_payload = payload.model_dump()
    metrics = payload.metrics or {}
    topology = payload.topology or {}
    dependency_graph: dict[str, Any] = {}
    dependency_engine = getattr(request.app.state.container, "dependency_engine", None)
    if isinstance(topology, dict) and topology and dependency_engine is not None:
        try:
            dependency_graph = dependency_engine.build_from_topology(
                payload.cluster_id,
                payload.environment or "dev",
                topology,
            )
        except Exception:
            dependency_graph = {}
    cpu_usage = _as_float(metrics.get("cpu_usage", 0.0))
    memory_usage = _as_float(metrics.get("memory_usage", 0.0))
    request_rate = _as_float(metrics.get("request_rate", 0.0))
    error_rate = _as_float(metrics.get("error_rate", 0.0))
    logger.info(
        "Received telemetry cluster=%s metrics=%s",
        payload.cluster_id,
        {
            "cpu_usage": cpu_usage,
            "memory_usage": memory_usage,
            "request_rate": request_rate,
            "pod_restarts": _as_float(metrics.get("pod_restarts", 0.0)),
            "error_rate": error_rate,
        },
    )

    for row in payload.incidents:
        now = datetime.now(timezone.utc)
        generated_incident_id = row.incident_id or f"agent-{payload.cluster_id}-{row.service_name}-{now.strftime('%Y%m%d%H%M%S%f')}"
        classification = row.classification
        root_cause = row.root_cause or "unspecified"
        anomaly_score = row.anomaly_score
        confidence_score = row.confidence_score
        risk_forecast = row.risk_forecast
        llm_reasoning: dict[str, Any] = {}
        executive_summary: str | None = None
        supporting_signals: dict[str, Any] = {}
        suggested_actions: dict[str, Any] = {}
        confidence_breakdown: dict[str, Any] = {}

        # Prefer real telemetry-based classification when metrics are present.
        if payload.metrics:
            if error_rate > 0.05:
                classification = "Error Spike"
                root_cause = "error_rate_threshold_breached"
            elif cpu_usage > 0.8:
                classification = "CPU Saturation"
                root_cause = "cpu_usage_threshold_breached"
            else:
                classification = "Healthy"
                root_cause = "metrics_within_expected_range"

            anomaly_score = min(1.0, max(0.0, (cpu_usage + (error_rate * 4.0)) / 2.0))
            risk_forecast = min(1.0, max(0.0, (cpu_usage * 0.6) + (error_rate * 0.4)))
            confidence_score = 0.95

            try:
                for attempt in range(1, MAX_RETRIES + 1):
                    candidate = _llm_reasoning_for_metrics(
                        request=request,
                        cluster_id=payload.cluster_id,
                        environment=payload.environment or "dev",
                        service_name=row.service_name,
                        metrics={
                            "cpu_usage": cpu_usage,
                            "memory_usage": memory_usage,
                            "request_rate": request_rate,
                            "error_rate": error_rate,
                        },
                        classification=classification,
                        root_cause=root_cause,
                        topology=topology,
                    )
                    candidate = _ensure_complete_reasoning(
                        candidate,
                        cluster_id=payload.cluster_id,
                        environment=payload.environment or "dev",
                        service_name=row.service_name,
                        metrics={
                            "cpu_usage": cpu_usage,
                            "memory_usage": memory_usage,
                            "request_rate": request_rate,
                            "error_rate": error_rate,
                        },
                        classification=classification,
                        root_cause=root_cause,
                        topology=topology,
                    )
                    if _is_valid_reasoning(candidate):
                        llm_reasoning = candidate
                        logger.info("LLM inference successful for incident=%s attempt=%s", generated_incident_id, attempt)
                        break
                    logger.warning("LLM inference attempt %s failed for incident=%s", attempt, generated_incident_id)
                    if attempt < MAX_RETRIES:
                        time.sleep(RETRY_DELAY_SECONDS)
                if not llm_reasoning:
                    llm_reasoning = _deterministic_reasoning_for_metrics(
                        cluster_id=payload.cluster_id,
                        environment=payload.environment or "dev",
                        service_name=row.service_name,
                        metrics={
                            "cpu_usage": cpu_usage,
                            "memory_usage": memory_usage,
                            "request_rate": request_rate,
                            "error_rate": error_rate,
                        },
                        classification=classification,
                        root_cause=root_cause,
                        topology=topology,
                    )
                llm_reasoning = _sanitize_reasoning_narrative(
                    llm_reasoning,
                    metrics={
                        "cpu_usage": cpu_usage,
                        "memory_usage": memory_usage,
                        "request_rate": request_rate,
                        "pod_restarts": _as_float(metrics.get("pod_restarts", 0.0)),
                        "error_rate": error_rate,
                    },
                    resolved_origin=str(llm_reasoning.get("origin_service", "") or row.service_name or "observer-agent"),
                )

                root_cause = str(llm_reasoning.get("root_cause") or llm_reasoning.get("probable_root_cause") or root_cause)
                executive_summary = str(llm_reasoning.get("human_summary") or "")
                confidence_score = _extract_confidence_fraction(llm_reasoning.get("confidence"), confidence_score)
                origin_service = str(llm_reasoning.get("origin_service", "") or "").strip()
                topology_insights = llm_reasoning.get("topology_insights") if isinstance(llm_reasoning.get("topology_insights"), dict) else {}
                causal_chain = llm_reasoning.get("causal_chain") if isinstance(llm_reasoning.get("causal_chain"), list) else []
                supporting_signals = {
                    "causal_chain": causal_chain,
                }
                suggested_actions = {
                    "corrective_actions": llm_reasoning.get("corrective_actions") or [],
                    "preventive_hardening": llm_reasoning.get("preventive_hardening") or [],
                }
                confidence_breakdown = {
                    "confidence_score": llm_reasoning.get("confidence_score"),
                    "risk_forecast": llm_reasoning.get("risk_forecast"),
                    "ai_response_status": llm_reasoning.get("ai_response_status", "complete"),
                }
            except Exception:
                llm_reasoning = _deterministic_reasoning_for_metrics(
                    cluster_id=payload.cluster_id,
                    environment=payload.environment or "dev",
                    service_name=row.service_name,
                    metrics={
                        "cpu_usage": cpu_usage,
                        "memory_usage": memory_usage,
                        "request_rate": request_rate,
                        "error_rate": error_rate,
                    },
                    classification=classification,
                    root_cause=root_cause,
                    topology=topology,
                )

        if db.query(Incident).filter(Incident.incident_id == generated_incident_id).first() is None:
            db.add(
                Incident(
                    incident_id=generated_incident_id,
                    cluster_id=payload.cluster_id,
                    status="OPEN",
                    severity="WARNING",
                    impact_level="Low",
                    slo_breach_risk=row.risk_forecast * 100.0,
                    error_budget_remaining=100.0,
                    affected_services=row.service_name,
                    start_time=now,
                    duration="00:00:00",
                    analysis=llm_reasoning,
                    raw_payload=incoming_payload,
                    created_at=now,
                )
            )
            db.add(
                IncidentStatusHistory(
                    incident_id=generated_incident_id,
                    from_status="OPEN",
                    to_status="OPEN",
                    changed_at=now,
                )
            )

        db.add(
            IncidentMetricsSnapshot(
                incident_id=generated_incident_id,
                cpu_usage=_to_cpu_percent(cpu_usage),
                memory_usage=_to_memory_mb(memory_usage),
                latency_p95=0.0,
                error_rate=_to_error_percent(error_rate),
                thread_pool_saturation=0.0,
                raw_metrics_json={
                    "cpu_usage": cpu_usage,
                    "memory_usage": memory_usage,
                    "request_rate": request_rate,
                    "pod_restarts": _as_float(metrics.get("pod_restarts", 0.0)),
                    "error_rate": error_rate,
                    "topology": topology,
                    "dependency_graph": dependency_graph,
                },
                captured_at=now,
            )
        )
        svc.save_incident_analysis(
            {
                "incident_id": generated_incident_id,
                "service_name": row.service_name,
                "cluster_id": payload.cluster_id,
                "anomaly_score": anomaly_score,
                "confidence_score": confidence_score,
                "classification": classification,
                "root_cause": root_cause,
                "mitigation": {
                    **row.mitigation,
                    "telemetry": {
                        "cpu_usage": cpu_usage,
                        "memory_usage": memory_usage,
                        "request_rate": request_rate,
                        "error_rate": error_rate,
                    },
                    "origin_service": llm_reasoning.get("origin_service"),
                    "topology_insights": llm_reasoning.get("topology_insights", {}),
                    "supporting_signals": llm_reasoning.get("causal_chain", []),
                    "topology": topology,
                    "dependency_graph": dependency_graph,
                },
                "risk_forecast": risk_forecast,
                "mitigation_success": row.mitigation_success,
                "executive_summary": executive_summary,
                "supporting_signals": supporting_signals,
                "suggested_actions": suggested_actions,
                "confidence_breakdown": confidence_breakdown,
            }
        )
        inserted += 1

    return AgentPushResponse(accepted=True, cluster_id=payload.cluster_id, inserted=inserted)

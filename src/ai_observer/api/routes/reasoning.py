from __future__ import annotations

import logging
import math
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import and_
from sqlalchemy.orm import Session

from ai_observer.api.routes.schemas import AlertmanagerWebhook
from ai_observer.backend.intelligence import CausalEngine, TopologyEngine
from ai_observer.backend.models.incident import Incident, IncidentMetricsSnapshot
from ai_observer.backend.services.canonical_telemetry import build_canonical_telemetry
from ai_observer.backend.services import IncidentsService
from ai_observer.domain.models import AlertSignal, LiveReasoningResponse, ObservabilityContext, ReasoningResult
from ai_observer.incident_analysis.database import get_db_session
from ai_observer.incident_analysis.models import IncidentAnalysis
from ai_observer.services.reasoning_service import ReasoningService

router = APIRouter()
logger = logging.getLogger(__name__)


def get_reasoning_service(request: Request) -> ReasoningService:
    return request.app.state.container.reasoning_service


def _persist_analysis_snapshot(db: Session, alert: AlertSignal, response: LiveReasoningResponse) -> None:
    IncidentsService(db).persist_from_reasoning(alert, response)


def _has_metric_signal(metrics: dict[str, Any] | None) -> bool:
    if not isinstance(metrics, dict):
        return False
    keys = (
        "request_rate_rps_5m",
        "cpu_usage_cores_5m",
        "memory_usage_bytes",
        "pod_restarts_10m",
        "error_rate_5xx_5m",
    )
    return any(float(metrics.get(k, 0) or 0) > 0 for k in keys)


def _as_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _normalize_telemetry_metrics(metrics: dict[str, Any] | None) -> dict[str, float]:
    source = metrics if isinstance(metrics, dict) else {}
    cpu = _as_float(source.get("cpu_usage_cores_5m", source.get("cpu_usage", 0.0)))
    memory = _as_float(source.get("memory_usage_bytes", source.get("memory_usage", 0.0)))
    request_rate = _as_float(source.get("request_rate_rps_5m", source.get("request_rate", 0.0)))
    restarts = _as_float(source.get("pod_restarts_10m", source.get("pod_restarts", 0.0)))
    error_rate = _as_float(source.get("error_rate_5xx_5m", source.get("error_rate", 0.0)))

    if cpu > 1.0:
        cpu = cpu / 100.0
    if 0.0 < memory < 1024.0:
        memory = memory * 1024.0 * 1024.0
    if error_rate > 1.0:
        error_rate = error_rate / 100.0

    return {
        "cpu_usage_cores_5m": cpu,
        "memory_usage_bytes": memory,
        "request_rate_rps_5m": request_rate,
        "pod_restarts_10m": restarts,
        "error_rate_5xx_5m": error_rate,
    }


def _has_nonzero(metrics: dict[str, float]) -> bool:
    return any(_as_float(metrics.get(k, 0.0)) > 0.0 for k in metrics.keys())


def _merge_priority_metrics(sources: list[dict[str, float]]) -> dict[str, float]:
    merged = {
        "cpu_usage_cores_5m": 0.0,
        "memory_usage_bytes": 0.0,
        "request_rate_rps_5m": 0.0,
        "pod_restarts_10m": 0.0,
        "error_rate_5xx_5m": 0.0,
    }
    for source in sources:
        if not isinstance(source, dict):
            continue
        for key in merged.keys():
            current = _as_float(merged.get(key, 0.0))
            candidate = _as_float(source.get(key, 0.0))
            # Keep highest-priority non-zero values; never overwrite with lower-priority zeros.
            if current <= 0.0 and candidate > 0.0:
                merged[key] = candidate
    return merged


def _has_zero_telemetry_narrative(response: LiveReasoningResponse) -> bool:
    lines: list[str] = []
    lines.extend([str(x) for x in (response.analysis.supporting_evidence or [])])
    lines.extend([str(x) for x in (response.analysis.causal_chain or [])])
    text = " ".join(lines).lower()
    return ("current telemetry" in text) and ("cpu 0%" in text or "memory 0mb" in text)


def _needs_canonical_metric_repair(response: LiveReasoningResponse) -> bool:
    metrics = response.context.metrics or {}
    cpu = _as_float(metrics.get("cpu_usage_cores_5m", 0.0))
    mem = _as_float(metrics.get("memory_usage_bytes", 0.0))
    rps = _as_float(metrics.get("request_rate_rps_5m", 0.0))
    origin = str(response.analysis.origin_service or "").strip().lower()
    topo = response.analysis.topology_insights if isinstance(response.analysis.topology_insights, dict) else {}
    topo_origin = str(topo.get("likely_origin_service", "") or "").strip().lower()

    # Core fields used by UI narrative must be repaired if zero/unknown while telemetry signal exists elsewhere.
    has_any_signal = _has_metric_signal(metrics)
    zero_core = cpu <= 0.0 or mem <= 0.0 or rps <= 0.0
    unknown_origin = origin in {"", "unknown", "all", "*"} or topo_origin in {"", "unknown", "all", "*"}
    return _has_zero_telemetry_narrative(response) or (has_any_signal and zero_core) or unknown_origin


def _telemetry_for_incident(db: Session, incident: Incident) -> dict[str, float]:
    canonical = build_canonical_telemetry(incident)
    reasoning_metrics = canonical.get("reasoning_metrics", {}) if isinstance(canonical.get("reasoning_metrics"), dict) else {}
    return {
        "cpu_usage_cores_5m": _as_float(reasoning_metrics.get("cpu_usage_cores_5m", canonical.get("cpu_usage", 0.0))),
        "memory_usage_bytes": _as_float(reasoning_metrics.get("memory_usage_bytes", canonical.get("memory_usage", 0.0))),
        "request_rate_rps_5m": _as_float(reasoning_metrics.get("request_rate_rps_5m", canonical.get("request_rate", 0.0))),
        "pod_restarts_10m": _as_float(reasoning_metrics.get("pod_restarts_10m", canonical.get("pod_restarts", 0.0))),
        "error_rate_5xx_5m": _as_float(reasoning_metrics.get("error_rate_5xx_5m", canonical.get("error_rate", 0.0))),
    }


def _topology_for_incident(db: Session, incident: Incident) -> dict[str, Any]:
    raw_payload = incident.raw_payload if isinstance(incident.raw_payload, dict) else {}
    topology = raw_payload.get("topology") if isinstance(raw_payload, dict) else {}
    if isinstance(topology, dict) and topology:
        return topology

    latest_analysis = (
        db.query(IncidentAnalysis)
        .filter(IncidentAnalysis.incident_id == incident.incident_id)
        .order_by(IncidentAnalysis.created_at.desc())
        .first()
    )
    mitigation = latest_analysis.mitigation if latest_analysis and isinstance(latest_analysis.mitigation, dict) else {}
    topology = mitigation.get("topology") if isinstance(mitigation, dict) else {}
    if isinstance(topology, dict) and topology:
        return topology
    topology_insights = mitigation.get("topology_insights") if isinstance(mitigation, dict) else {}
    if isinstance(topology_insights, dict) and topology_insights:
        return {"topology_insights": topology_insights}
    return {}


def _hydrate_metrics_from_recent_incidents(db: Session, cluster_id: str) -> tuple[dict[str, Any], dict[str, dict[str, float]], dict[str, Any]]:
    query = db.query(Incident).filter(Incident.incident_id.ilike("agent-%")).order_by(Incident.created_at.desc())
    if cluster_id:
        rows = query.filter(Incident.cluster_id == cluster_id).limit(100).all()
        if not rows:
            rows = query.limit(100).all()
    else:
        rows = query.limit(100).all()
    component_metrics: dict[str, dict[str, float]] = {}
    topology_candidate: dict[str, Any] = {}
    metric_samples: dict[str, list[tuple[float, Any]]] = {
        "cpu_usage_cores_5m": [],
        "memory_usage_bytes": [],
        "request_rate_rps_5m": [],
        "error_rate_5xx_5m": [],
        "pod_restarts_10m": [],
    }

    for row in rows:
        resolved = _telemetry_for_incident(db, row)
        if not _has_nonzero(resolved):
            continue
        if not topology_candidate:
            topo = _topology_for_incident(db, row)
            if topo:
                topology_candidate = topo

        service = (row.affected_services or "observer-agent").split(",")[0].strip() or "observer-agent"
        if service not in component_metrics:
            component_metrics[service] = resolved

        ts = row.created_at
        for key in metric_samples.keys():
            metric_samples[key].append((float(resolved.get(key, 0.0) or 0.0), ts))

    if not component_metrics:
        return {}, {}, {}

    aggregated: dict[str, float | str] = {
        "cpu_usage_cores_5m": max(v.get("cpu_usage_cores_5m", 0.0) for v in component_metrics.values()),
        "memory_usage_bytes": sum(v.get("memory_usage_bytes", 0.0) for v in component_metrics.values()),
        "request_rate_rps_5m": sum(v.get("request_rate_rps_5m", 0.0) for v in component_metrics.values()),
        "pod_restarts_10m": sum(v.get("pod_restarts_10m", 0.0) for v in component_metrics.values()),
        "error_rate_5xx_5m": sum(v.get("error_rate_5xx_5m", 0.0) for v in component_metrics.values()),
    }

    def _mean_std(values: list[float]) -> tuple[float, float]:
        if not values:
            return 0.0, 0.0
        mean = sum(values) / len(values)
        if len(values) == 1:
            return mean, 0.0
        var = sum((v - mean) ** 2 for v in values) / len(values)
        return mean, math.sqrt(max(var, 0.0))

    def _zscore(current: float, mean: float, stddev: float) -> float:
        effective_std = max(abs(stddev), abs(mean) * 0.1, 1e-6)
        return (current - mean) / effective_std

    def _zscore_to_score(z: float) -> float:
        return max(0.0, min(1.0, abs(z) / 3.0))

    # Build historical baselines using recent incident telemetry as fallback.
    now_ts = rows[0].created_at if rows else None
    windows = {"5m": 5 * 60, "30m": 30 * 60, "1h": 60 * 60}
    for suffix, seconds in windows.items():
        for metric_key, samples in metric_samples.items():
            if now_ts is None:
                window_values = [v for v, _ in samples]
            else:
                window_values = [
                    v
                    for v, ts in samples
                    if ts is not None and abs((now_ts - ts).total_seconds()) <= seconds
                ]
                if not window_values:
                    window_values = [v for v, _ in samples]
            mean, stddev = _mean_std(window_values)
            aggregated[f"{metric_key.replace('_5m', '').replace('_10m', '')}_baseline_mean_{suffix}"] = mean
            aggregated[f"{metric_key.replace('_5m', '').replace('_10m', '')}_baseline_stddev_{suffix}"] = stddev
            current = float(aggregated.get(metric_key, 0.0) or 0.0)
            z = _zscore(current, mean, stddev)
            aggregated[f"{metric_key.replace('_5m', '').replace('_10m', '')}_baseline_zscore_{suffix}"] = z
            aggregated[f"{metric_key.replace('_5m', '').replace('_10m', '')}_baseline_anomaly_{suffix}"] = _zscore_to_score(z)

    # Normalize names to match Prometheus provider contract exactly.
    rename_pairs = {
        "cpu_usage_cores_baseline_mean_5m": "cpu_baseline_mean_5m",
        "cpu_usage_cores_baseline_mean_30m": "cpu_baseline_mean_30m",
        "cpu_usage_cores_baseline_mean_1h": "cpu_baseline_mean_1h",
        "cpu_usage_cores_baseline_stddev_5m": "cpu_baseline_stddev_5m",
        "cpu_usage_cores_baseline_stddev_30m": "cpu_baseline_stddev_30m",
        "cpu_usage_cores_baseline_stddev_1h": "cpu_baseline_stddev_1h",
        "cpu_usage_cores_baseline_zscore_5m": "cpu_baseline_zscore_5m",
        "cpu_usage_cores_baseline_zscore_30m": "cpu_baseline_zscore_30m",
        "cpu_usage_cores_baseline_zscore_1h": "cpu_baseline_zscore_1h",
        "cpu_usage_cores_baseline_anomaly_5m": "cpu_baseline_anomaly_5m",
        "cpu_usage_cores_baseline_anomaly_30m": "cpu_baseline_anomaly_30m",
        "cpu_usage_cores_baseline_anomaly_1h": "cpu_baseline_anomaly_1h",
        "memory_usage_bytes_baseline_mean_5m": "memory_baseline_mean_5m",
        "memory_usage_bytes_baseline_mean_30m": "memory_baseline_mean_30m",
        "memory_usage_bytes_baseline_mean_1h": "memory_baseline_mean_1h",
        "memory_usage_bytes_baseline_stddev_5m": "memory_baseline_stddev_5m",
        "memory_usage_bytes_baseline_stddev_30m": "memory_baseline_stddev_30m",
        "memory_usage_bytes_baseline_stddev_1h": "memory_baseline_stddev_1h",
        "memory_usage_bytes_baseline_zscore_5m": "memory_baseline_zscore_5m",
        "memory_usage_bytes_baseline_zscore_30m": "memory_baseline_zscore_30m",
        "memory_usage_bytes_baseline_zscore_1h": "memory_baseline_zscore_1h",
        "memory_usage_bytes_baseline_anomaly_5m": "memory_baseline_anomaly_5m",
        "memory_usage_bytes_baseline_anomaly_30m": "memory_baseline_anomaly_30m",
        "memory_usage_bytes_baseline_anomaly_1h": "memory_baseline_anomaly_1h",
        "request_rate_rps_baseline_mean_5m": "request_rate_baseline_mean_5m",
        "request_rate_rps_baseline_mean_30m": "request_rate_baseline_mean_30m",
        "request_rate_rps_baseline_mean_1h": "request_rate_baseline_mean_1h",
        "request_rate_rps_baseline_stddev_5m": "request_rate_baseline_stddev_5m",
        "request_rate_rps_baseline_stddev_30m": "request_rate_baseline_stddev_30m",
        "request_rate_rps_baseline_stddev_1h": "request_rate_baseline_stddev_1h",
        "request_rate_rps_baseline_zscore_5m": "request_rate_baseline_zscore_5m",
        "request_rate_rps_baseline_zscore_30m": "request_rate_baseline_zscore_30m",
        "request_rate_rps_baseline_zscore_1h": "request_rate_baseline_zscore_1h",
        "request_rate_rps_baseline_anomaly_5m": "request_rate_baseline_anomaly_5m",
        "request_rate_rps_baseline_anomaly_30m": "request_rate_baseline_anomaly_30m",
        "request_rate_rps_baseline_anomaly_1h": "request_rate_baseline_anomaly_1h",
        "error_rate_5xx_baseline_mean_5m": "error_rate_baseline_mean_5m",
        "error_rate_5xx_baseline_mean_30m": "error_rate_baseline_mean_30m",
        "error_rate_5xx_baseline_mean_1h": "error_rate_baseline_mean_1h",
        "error_rate_5xx_baseline_stddev_5m": "error_rate_baseline_stddev_5m",
        "error_rate_5xx_baseline_stddev_30m": "error_rate_baseline_stddev_30m",
        "error_rate_5xx_baseline_stddev_1h": "error_rate_baseline_stddev_1h",
        "error_rate_5xx_baseline_zscore_5m": "error_rate_baseline_zscore_5m",
        "error_rate_5xx_baseline_zscore_30m": "error_rate_baseline_zscore_30m",
        "error_rate_5xx_baseline_zscore_1h": "error_rate_baseline_zscore_1h",
        "error_rate_5xx_baseline_anomaly_5m": "error_rate_baseline_anomaly_5m",
        "error_rate_5xx_baseline_anomaly_30m": "error_rate_baseline_anomaly_30m",
        "error_rate_5xx_baseline_anomaly_1h": "error_rate_baseline_anomaly_1h",
        "pod_restarts_baseline_mean_5m": "pod_restarts_baseline_mean_5m",
        "pod_restarts_baseline_mean_30m": "pod_restarts_baseline_mean_30m",
        "pod_restarts_baseline_mean_1h": "pod_restarts_baseline_mean_1h",
        "pod_restarts_baseline_stddev_5m": "pod_restarts_baseline_stddev_5m",
        "pod_restarts_baseline_stddev_30m": "pod_restarts_baseline_stddev_30m",
        "pod_restarts_baseline_stddev_1h": "pod_restarts_baseline_stddev_1h",
        "pod_restarts_baseline_zscore_5m": "pod_restarts_baseline_zscore_5m",
        "pod_restarts_baseline_zscore_30m": "pod_restarts_baseline_zscore_30m",
        "pod_restarts_baseline_zscore_1h": "pod_restarts_baseline_zscore_1h",
        "pod_restarts_baseline_anomaly_5m": "pod_restarts_baseline_anomaly_5m",
        "pod_restarts_baseline_anomaly_30m": "pod_restarts_baseline_anomaly_30m",
        "pod_restarts_baseline_anomaly_1h": "pod_restarts_baseline_anomaly_1h",
    }
    for src, dst in rename_pairs.items():
        if src in aggregated:
            aggregated[dst] = float(aggregated[src] or 0.0)

    aggregated["baseline_window_used"] = "30m"
    weighted = (
        0.25 * float(aggregated.get("cpu_baseline_anomaly_30m", 0.0) or 0.0)
        + 0.2 * float(aggregated.get("memory_baseline_anomaly_30m", 0.0) or 0.0)
        + 0.2 * float(aggregated.get("request_rate_baseline_anomaly_30m", 0.0) or 0.0)
        + 0.25 * float(aggregated.get("error_rate_baseline_anomaly_30m", 0.0) or 0.0)
        + 0.1 * float(aggregated.get("pod_restarts_baseline_anomaly_30m", 0.0) or 0.0)
    )
    aggregated["baseline_anomaly_score"] = max(0.0, min(1.0, weighted))

    return {k: float(v) if isinstance(v, (int, float)) else v for k, v in aggregated.items()}, component_metrics, topology_candidate


def _refresh_analysis_from_metrics(response: LiveReasoningResponse, topology: dict[str, Any], service_hint: str) -> None:
    metrics = response.context.metrics or {}
    cpu = _as_float(metrics.get("cpu_usage_cores_5m", 0.0))
    mem_mb = _as_float(metrics.get("memory_usage_bytes", 0.0)) / (1024 * 1024)
    rps = _as_float(metrics.get("request_rate_rps_5m", 0.0))
    restarts = _as_float(metrics.get("pod_restarts_10m", 0.0))
    err = _as_float(metrics.get("error_rate_5xx_5m", 0.0))
    baseline_score = _as_float(metrics.get("baseline_anomaly_score", 0.0))

    if err > 0.05:
        response.analysis.probable_root_cause = "error_rate_threshold_breached"
        response.analysis.incident_classification = "Performance Degradation"
    elif baseline_score >= 0.65:
        response.analysis.probable_root_cause = "baseline_deviation_zscore_high"
        response.analysis.incident_classification = "Performance Degradation"
    elif cpu > 0.8:
        response.analysis.probable_root_cause = "cpu_usage_threshold_breached"
        response.analysis.incident_classification = "Performance Degradation"
    else:
        response.analysis.probable_root_cause = "metrics_within_expected_range"
        response.analysis.incident_classification = "Healthy"

    response.analysis.executive_summary = (
        f"Telemetry from observer-agent indicates CPU {cpu*100:.2f}%, "
        f"Memory {mem_mb:.0f}MB, Request rate {rps:.3f} rps, Restarts {restarts:.0f}, Error rate {err*100:.2f}%."
    )
    response.analysis.human_summary = response.analysis.executive_summary
    response.analysis.assessment = "Analysis refreshed from recent persisted agent telemetry."
    response.analysis.why_not_resource_saturation = [
        f"CPU {round(cpu * 100)}% {'(high)' if (cpu * 100) > 80 else '(below saturation)'}",
        f"Memory {round(mem_mb)}MB {'(high)' if mem_mb > 1024 else '(stable)'}",
        f"Pod restarts {int(restarts)} {'(elevated)' if restarts > 0 else '(none)'}",
    ]
    response.analysis.causal_chain = [
        f"Telemetry source resolved via prioritized incident pipeline (snapshot/raw_payload/mitigation).",
        f"Current metrics: CPU {cpu*100:.2f}%, Memory {mem_mb:.0f}MB, RPS {rps:.3f}, 5xx {err*100:.2f}%.",
    ]
    evidence_lines = [
        f"Baseline anomaly score (30m): {baseline_score:.3f}.",
        f"CPU deviation z-score (30m): {_as_float(metrics.get('cpu_baseline_zscore_30m', 0.0)):.3f}.",
        f"Memory deviation z-score (30m): {_as_float(metrics.get('memory_baseline_zscore_30m', 0.0)):.3f}.",
        f"Request rate deviation z-score (30m): {_as_float(metrics.get('request_rate_baseline_zscore_30m', 0.0)):.3f}.",
    ]
    response.analysis.supporting_evidence = evidence_lines
    existing_ctx = [str(x) for x in (response.analysis.change_detection_context or [])]
    existing_ctx = [x for x in existing_ctx if "Topology origin service:" not in x]
    response.analysis.change_detection_context = existing_ctx + evidence_lines
    response.analysis.anomaly_summary = {
        "score": round(baseline_score, 3),
        "threshold": 0.65,
        "status": "Anomalous" if baseline_score >= 0.65 else "Normal",
    }
    confidence = max(0.35, min(0.95, 0.55 + (baseline_score * 0.3)))
    response.analysis.confidence = round(confidence, 3)
    response.analysis.confidence_score = f"{round(confidence * 100)}%"
    response.analysis.confidence_details = {
        "data_completeness": "100%",
        "signal_agreement": "Moderate" if baseline_score >= 0.15 else "Low",
        "historical_similarity": "Moderate",
        "overall_band": "Medium" if confidence >= 0.5 else "Low",
        "confidence_formula": "historical_confidence = clamp(0.55 + baseline_anomaly_score*0.3, 0.35, 0.95)",
        "computed_confidence": round(confidence, 3),
    }
    response.context.signal_scores = response.context.signal_scores or {}
    response.context.signal_scores["baseline_anomaly_score"] = baseline_score
    response.context.signal_scores["overall_anomaly_score"] = max(
        _as_float(response.context.signal_scores.get("overall_anomaly_score", 0.0)),
        baseline_score * 0.7,
    )
    response.analysis.correlated_signals = {
        "signal_agreement_score": round(min(1.0, baseline_score + 0.25), 3),
        "correlation_strength": round(min(1.0, baseline_score + 0.2), 3),
    }
    response.analysis.causal_analysis = {
        "root_cause_metric": response.analysis.probable_root_cause,
        "root_cause_explanation": "Deterministic topology-aware reasoning used persisted telemetry with baseline deviation checks.",
        "dependent_signals": response.analysis.why_not_resource_saturation,
        "contradictory_signals": [],
        "unaffected_signals": [],
    }
    origin_service = TopologyEngine.infer_origin_service(topology, preferred_service=service_hint or "observer-agent")
    impacted_services = TopologyEngine.infer_impacted_services(topology)
    propagation_path = []
    if isinstance(topology.get("topology_insights"), dict):
        propagation_path = list(topology.get("topology_insights", {}).get("propagation_path", []) or [])
    if not propagation_path and impacted_services and origin_service in impacted_services:
        propagation_path = [origin_service]
    response.analysis.topology_insights = {
        "likely_origin_service": origin_service,
        "impacted_services": impacted_services,
        "propagation_path": propagation_path,
        "propagation_consistency": round(min(1.0, baseline_score + 0.3), 3),
    }
    response.analysis.origin_service = origin_service
    response.analysis.ai_response_status = "complete"
    chain_addons = CausalEngine.build_causal_chain(origin_service, impacted_services, propagation_path)
    response.analysis.causal_chain = [*response.analysis.causal_chain, *chain_addons]
    response.analysis.causal_analysis = {
        **(response.analysis.causal_analysis or {}),
        "origin_service": origin_service,
        "propagation_path": propagation_path,
        "impacted_services": impacted_services,
    }
    logger.info("Refreshed analysis why_not_resource_saturation=%s", response.analysis.why_not_resource_saturation)


def _parse_time_window(value: str) -> int:
    raw = (value or "30m").strip().lower()
    if raw.endswith("m"):
        raw = raw[:-1]
    elif raw.endswith("h"):
        raw = str(int(raw[:-1]) * 60) if raw[:-1].isdigit() else "60"
    elif raw.endswith("d"):
        raw = str(int(raw[:-1]) * 24 * 60) if raw[:-1].isdigit() else "360"
    try:
        minutes = int(raw)
    except ValueError:
        minutes = 30
    return max(5, min(360, minutes))


def _extract_alert(payload: AlertmanagerWebhook, default_namespace: str, default_service: str, default_cluster: str) -> AlertSignal:
    if not payload.alerts:
        raise HTTPException(status_code=400, detail="alert payload has no alerts")

    first = payload.alerts[0]
    labels = dict(payload.commonLabels)
    labels.update(first.labels)

    return AlertSignal(
        alertname=labels.get("alertname", "UnknownAlert"),
        namespace=labels.get("namespace", default_namespace),
        service=labels.get("service") or labels.get("app") or default_service,
        cluster_id=labels.get("cluster_id") or labels.get("cluster") or default_cluster,
        severity=labels.get("severity", "warning"),
        status=first.status,
    )


@router.get("/api/reasoning/live", response_model=LiveReasoningResponse)
def live_reasoning(
    request: Request,
    namespace: str = Query(default="dev"),
    service: str = Query(default="all"),
    cluster: str | None = Query(default=None),
    severity: str = Query(default="warning"),
    time_window: str = Query(default="30m"),
    reasoner: ReasoningService = Depends(get_reasoning_service),
    db: Session = Depends(get_db_session),
) -> LiveReasoningResponse:
    logger.warning("Endpoint /api/reasoning/live is disabled in incident-driven mode.")
    raise HTTPException(status_code=410, detail="live_reasoning_disabled_use_api_incidents")


@router.post("/webhook/alertmanager", response_model=LiveReasoningResponse)
def alertmanager_webhook(
    request: Request,
    payload: AlertmanagerWebhook,
    reasoner: ReasoningService = Depends(get_reasoning_service),
    db: Session = Depends(get_db_session),
) -> LiveReasoningResponse:
    settings = request.app.state.container.settings
    alert = _extract_alert(
        payload,
        settings.telemetry.default_namespace,
        settings.telemetry.default_service,
        settings.telemetry.default_cluster_id,
    )
    result = reasoner.analyze(alert, window_minutes=settings.telemetry.default_window_minutes)
    try:
        _persist_analysis_snapshot(db, alert, result)
    except Exception:
        # Persistence is best-effort and must not break webhook response path.
        pass
    return result

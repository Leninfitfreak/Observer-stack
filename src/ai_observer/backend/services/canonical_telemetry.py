from __future__ import annotations

from typing import Any

from sqlalchemy.orm import object_session

from ai_observer.backend.models.incident import Incident, IncidentMetricsSnapshot
from ai_observer.incident_analysis.models import IncidentAnalysis


def _as_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _normalize_source_metrics(metrics: dict[str, Any] | None) -> dict[str, float]:
    source = metrics if isinstance(metrics, dict) else {}
    cpu = _as_float(source.get("cpu_usage", source.get("cpu_usage_cores_5m", 0.0)))
    memory = _as_float(source.get("memory_usage", source.get("memory_usage_bytes", 0.0)))
    request_rate = _as_float(source.get("request_rate", source.get("request_rate_rps_5m", 0.0)))
    restarts = _as_float(source.get("pod_restarts", source.get("pod_restarts_10m", 0.0)))
    error_rate = _as_float(source.get("error_rate", source.get("error_rate_5xx_5m", 0.0)))

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


def _merge_priority_metrics(sources: list[tuple[str, dict[str, float]]]) -> tuple[dict[str, float], dict[str, str]]:
    merged = {"cpu_usage": 0.0, "memory_usage": 0.0, "request_rate": 0.0, "pod_restarts": 0.0, "error_rate": 0.0}
    source_used = {k: "fallback" for k in merged.keys()}
    for source_name, source in sources:
        if not isinstance(source, dict):
            continue
        for key in merged.keys():
            current = _as_float(merged.get(key, 0.0))
            candidate = _as_float(source.get(key, 0.0))
            # Strict precedence: keep the first non-zero from highest-priority source.
            if current <= 0.0 and candidate > 0.0:
                merged[key] = candidate
                source_used[key] = source_name
    return merged, source_used


def _snapshot_typed_reconstruction(snapshot: IncidentMetricsSnapshot) -> dict[str, float]:
    return {
        "cpu_usage": _as_float(snapshot.cpu_usage) / 100.0,
        "memory_usage": _as_float(snapshot.memory_usage) * 1024.0 * 1024.0,
        "request_rate": 0.0,
        "pod_restarts": 0.0,
        "error_rate": _as_float(snapshot.error_rate) / 100.0,
    }


def _extract_mitigation_telemetry(analysis: IncidentAnalysis | None) -> dict[str, float]:
    mitigation = analysis.mitigation if analysis and isinstance(analysis.mitigation, dict) else {}
    telemetry = mitigation.get("telemetry") if isinstance(mitigation, dict) else {}
    return _normalize_source_metrics(telemetry if isinstance(telemetry, dict) else {})


def build_canonical_telemetry(incident: Incident) -> dict[str, Any]:
    """
    Build one canonical telemetry object for an incident using strict priority:
    1) incident_metrics_snapshot
    2) incidents.raw_payload.metrics
    3) incident_analysis.mitigation.telemetry
    4) fallback zeros only when all above are missing
    """
    session = object_session(incident)
    if session is None:
        raw_payload = incident.raw_payload if isinstance(incident.raw_payload, dict) else {}
        payload_metrics = _normalize_source_metrics(raw_payload.get("metrics") if isinstance(raw_payload.get("metrics"), dict) else {})
        merged, source_used = _merge_priority_metrics([("raw_payload", payload_metrics)])
        return {
            **merged,
            "source_used": source_used,
            "has_signal": any(v > 0.0 for v in merged.values()),
        }

    snapshot = (
        session.query(IncidentMetricsSnapshot)
        .filter(IncidentMetricsSnapshot.incident_id == incident.incident_id)
        .order_by(IncidentMetricsSnapshot.captured_at.desc())
        .first()
    )
    snapshot_raw = _normalize_source_metrics(
        snapshot.raw_metrics_json if snapshot and isinstance(snapshot.raw_metrics_json, dict) else {}
    )
    snapshot_typed = _snapshot_typed_reconstruction(snapshot) if snapshot else _normalize_source_metrics({})
    snapshot_merged, _ = _merge_priority_metrics(
        [
            ("incident_metrics_snapshot.raw_metrics_json", snapshot_raw),
            ("incident_metrics_snapshot.columns", snapshot_typed),
        ]
    )

    raw_payload = incident.raw_payload if isinstance(incident.raw_payload, dict) else {}
    payload_metrics = _normalize_source_metrics(raw_payload.get("metrics") if isinstance(raw_payload.get("metrics"), dict) else {})

    latest_analysis = (
        session.query(IncidentAnalysis)
        .filter(IncidentAnalysis.incident_id == incident.incident_id)
        .order_by(IncidentAnalysis.created_at.desc())
        .first()
    )
    mitigation_metrics = _extract_mitigation_telemetry(latest_analysis)

    merged, source_used = _merge_priority_metrics(
        [
            ("incident_metrics_snapshot", snapshot_merged),
            ("raw_payload.metrics", payload_metrics),
            ("incident_analysis.mitigation.telemetry", mitigation_metrics),
        ]
    )
    return {
        **merged,
        "source_used": source_used,
        "has_signal": any(v > 0.0 for v in merged.values()),
        "reasoning_metrics": {
            "cpu_usage_cores_5m": merged["cpu_usage"],
            "memory_usage_bytes": merged["memory_usage"],
            "request_rate_rps_5m": merged["request_rate"],
            "pod_restarts_10m": merged["pod_restarts"],
            "error_rate_5xx_5m": merged["error_rate"],
        },
    }

from __future__ import annotations

import json
import re

from .llm.provider import LLMProvider
from .remediation_engine import build_remediation_steps
from .telemetry import TelemetryContext


OUTPUT_SCHEMA = {
    "root_cause": "",
    "root_cause_service": "",
    "root_cause_signal": "",
    "confidence_score": 0.0,
    "confidence_explanation": {},
    "causal_chain": [],
    "correlated_signals": [],
    "propagation_path": [],
    "impact_assessment": "",
    "customer_impact": "",
    "recommended_actions": [],
    "missing_telemetry_signals": [],
    "observability_score": 0.0,
    "observability_summary": {},
    "deployment_correlation": "",
    "historical_matches": [],
    "severity": "",
}


def _trim_text(value: str, limit: int = 220) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def _compact_incident(incident: dict) -> dict:
    snapshot = incident.get("telemetry_snapshot", {})
    return {
        "incident_id": incident["incident_id"],
        "problem_id": incident.get("problem_id", ""),
        "incident_type": incident.get("incident_type", "observed"),
        "predictive_confidence": incident.get("predictive_confidence", 0.0),
        "cluster": incident["cluster"],
        "namespace": incident["namespace"],
        "service": incident["service"],
        "timestamp": incident["timestamp"].isoformat() if hasattr(incident["timestamp"], "isoformat") else str(incident["timestamp"]),
        "severity": incident["severity"],
        "anomaly_score": incident["anomaly_score"],
        "anomaly_signals": incident["detector_signals"][:5],
        "snapshot": {
            "request_count": snapshot.get("request_count", 0),
            "error_rate": snapshot.get("error_rate", 0),
            "avg_latency_ms": snapshot.get("avg_latency_ms", 0),
            "p95_latency_ms": snapshot.get("p95_latency_ms", 0),
            "cpu_utilization": snapshot.get("cpu_utilization", 0),
            "memory_utilization": snapshot.get("memory_utilization", 0),
            "log_count": snapshot.get("log_count", 0),
            "error_logs": [_trim_text(item, 180) for item in snapshot.get("error_logs", [])[:3]],
        },
    }


def _compact_context(context: TelemetryContext) -> dict:
    edges = context.topology.get("edges", [])[:8]
    timeline = context.timeline[:8]
    detector_snapshot = context.metrics_summary.get("detector_snapshot", {})
    db_dependencies = context.db_summary.get("dependencies", [])[:6]
    messaging_flows = context.messaging_summary.get("flows", [])[:8]
    return {
        "scope": {
            "service": context.service_context.get("service", ""),
            "namespace": context.namespace_context.get("namespace", ""),
            "cluster": context.cluster_context.get("cluster", ""),
        },
        "metrics_summary": {
            "highlights": context.metrics_summary.get("highlights", {}),
            "detector_snapshot": {
                "request_count": detector_snapshot.get("request_count", 0),
                "error_rate": detector_snapshot.get("error_rate", 0),
                "avg_latency_ms": detector_snapshot.get("avg_latency_ms", 0),
                "p95_latency_ms": detector_snapshot.get("p95_latency_ms", 0),
                "cpu_utilization": detector_snapshot.get("cpu_utilization", 0),
                "memory_utilization": detector_snapshot.get("memory_utilization", 0),
                "log_count": detector_snapshot.get("log_count", 0),
            },
        },
        "logs_summary": {
            "log_count": context.logs_summary.get("log_count", 0),
            "context_log_count": context.logs_summary.get("context_log_count", 0),
            "examples": context.logs_summary.get("examples", [])[:5],
        },
        "trace_summary": context.trace_summary,
        "database_evidence": {
            "systems": context.db_summary.get("systems", []),
            "total_calls": context.db_summary.get("total_calls", 0),
            "dependencies": db_dependencies,
            "query_examples": context.db_summary.get("query_examples", [])[:3],
        },
        "messaging_evidence": {
            "systems": context.messaging_summary.get("systems", []),
            "destinations": context.messaging_summary.get("destinations", []),
            "total_calls": context.messaging_summary.get("total_calls", 0),
            "flows": messaging_flows,
        },
        "exception_evidence": {
            "exception_count": context.exception_summary.get("exception_count", 0),
            "error_span_count": context.exception_summary.get("error_span_count", 0),
            "types": context.exception_summary.get("types", []),
            "examples": context.exception_summary.get("examples", [])[:5],
        },
        "infra_evidence": {
            "pods": context.infra_summary.get("pods", []),
            "containers": context.infra_summary.get("containers", []),
            "nodes": context.infra_summary.get("nodes", []),
            "hosts": context.infra_summary.get("hosts", []),
            "environments": context.infra_summary.get("environments", []),
        },
        "service_context": context.service_context,
        "namespace_context": context.namespace_context,
        "cluster_context": context.cluster_context,
        "topology": {
            "nodes": [node.get("id") for node in context.topology.get("nodes", [])[:10]],
            "edges": [
                {
                    "source": edge.get("source"),
                    "target": edge.get("target"),
                    "call_count": edge.get("call_count"),
                }
                for edge in edges
            ],
        },
        "incident_timeline": [
            {
                "timestamp": event.get("timestamp"),
                "kind": event.get("kind"),
                "entity": event.get("entity"),
                "severity": event.get("severity"),
                "value": event.get("value"),
            }
            for event in timeline
        ],
        "telemetry_coverage": context.telemetry_coverage,
        "uncertainty": {
            "missing_signals": _as_string_list(context.telemetry_coverage.get("missing_signals", [])),
            "quality_by_signal": _quality_by_signal(context),
        },
        "deployment_correlation": {
            "events": [
                {
                    "timestamp": event.get("timestamp"),
                    "service": event.get("service"),
                    "details": _trim_text(event.get("details", ""), 180),
                }
                for event in context.deployment_correlation.get("events", [])[:3]
            ]
        },
    }


def _compact_history(historical_matches: list[dict]) -> list[dict]:
    return [
        {
            "incident_id": match.get("incident_id"),
            "service": match.get("service"),
            "severity": match.get("severity"),
            "anomaly_score": match.get("anomaly_score"),
            "timestamp": str(match.get("timestamp", "")),
            "root_cause_service": match.get("root_cause_service", ""),
            "root_cause_signal": match.get("root_cause_signal", ""),
            "root_cause": _trim_text(match.get("root_cause", ""), 180),
        }
        for match in historical_matches[:3]
    ]


def _reasoning_layers(incident: dict, context: TelemetryContext) -> dict:
    service = incident.get("service", "")
    namespace = incident.get("namespace", "")
    cluster = incident.get("cluster", "")
    detector_signals = _as_string_list(incident.get("detector_signals", []))
    service_worker = {
        "service": service,
        "namespace": namespace,
        "signals": detector_signals,
        "snapshot": _compact_incident(incident).get("snapshot", {}),
    }
    domain_nodes = sorted(
        {
            edge.get("source")
            for edge in context.topology.get("edges", [])
            if isinstance(edge, dict) and edge.get("source")
        }
        | {
            edge.get("target")
            for edge in context.topology.get("edges", [])
            if isinstance(edge, dict) and edge.get("target")
        }
    )
    domain_worker = {
        "domain": f"{cluster}/{namespace}",
        "services": domain_nodes[:20],
        "edges": context.topology.get("edges", [])[:20],
    }
    system_worker = {
        "cluster": cluster,
        "telemetry_coverage": context.telemetry_coverage,
        "recent_deployments": context.deployment_correlation.get("events", [])[:5],
        "database_evidence": context.db_summary,
        "messaging_evidence": context.messaging_summary,
        "exception_evidence": context.exception_summary,
        "infra_evidence": context.infra_summary,
    }
    return {
        "service_reasoning_worker": service_worker,
        "domain_reasoning_worker": domain_worker,
        "system_reasoning_worker": system_worker,
    }


def build_prompt(incident: dict, context: TelemetryContext, historical_matches: list[dict]) -> str:
    payload = {
        "incident": _compact_incident(incident),
        **_compact_context(context),
        "reasoning_layers": _reasoning_layers(incident, context),
        "historical_matches": _compact_history(historical_matches),
        "required_json_schema": OUTPUT_SCHEMA,
    }
    return (
        "You are Deep Observer, an AIOps root cause analysis engine. "
        "Use the provided structured scope, metrics, logs, traces, database evidence, messaging evidence, exception evidence, infra evidence, topology, telemetry coverage, deployment evidence, and historical incidents "
        "to determine the most probable root cause service and signal. "
        "Set root_cause_service to an actual service name from incident.service or topology.nodes, never to a span/operation name. "
        "Treat database, messaging, exception, and topology relationships as direct evidence only when they are explicitly present in the payload. "
        "Do not claim a specific infrastructure bottleneck or root cause unless the provided telemetry explicitly supports it. "
        "If telemetry is sparse or missing, say that root cause is insufficiently supported and keep confidence low. "
        "Clearly separate proven evidence from suspected correlation, and lower confidence when important evidence is absent. "
        "Apply causal scoring using dependency weight, temporal ordering, and signal strength. "
        "Correlate related anomalies into a single problem narrative with blast radius. "
        "Correlate anomalies into a single problem, describe the propagation path, customer impact, missing telemetry, "
        "observability maturity, and specific remediation actions. "
        "Respond with valid JSON matching required_json_schema exactly.\n"
        f"{json.dumps(payload, default=str)}"
    )


def _as_string(value, default: str = "") -> str:
    if value is None:
        return default
    if isinstance(value, (dict, list)):
        return json.dumps(value, default=str)
    return str(value)


def _as_float(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_string_list(value, default: list[str] | None = None) -> list[str]:
    if default is None:
        default = []
    if isinstance(value, list):
        return [_as_string(item) for item in value if _as_string(item)]
    if value in (None, ""):
        return list(default)
    return [_as_string(value)]


def _as_summary(value, fallback: dict) -> dict[str, str]:
    if not isinstance(value, dict):
        return normalize_summary(fallback)
    return normalize_summary(value)


def _as_history(value, fallback: list[dict]) -> list[dict]:
    def normalize_items(items) -> list[dict]:
        normalized: list[dict] = []
        for entry in items:
            if isinstance(entry, dict):
                normalized.append({str(k): _as_string(v) for k, v in entry.items()})
            else:
                normalized.append({"summary": _as_string(entry)})
        return normalized

    if not isinstance(value, list):
        return normalize_items(fallback)
    return normalize_items(value)

def _known_services(incident: dict, context: TelemetryContext) -> set[str]:
    known = {str(incident.get("service", "")).strip()}
    for node in context.topology.get("nodes", []):
        if isinstance(node, dict):
            value = str(node.get("id", "")).strip()
        else:
            value = str(node).strip()
        if value:
            known.add(value)
    return {item for item in known if item}


def _normalize_root_cause_service(candidate: str, incident: dict, context: TelemetryContext) -> str:
    value = str(candidate or "").strip()
    fallback = str(incident.get("service", "")).strip()
    if not value:
        return fallback
    canonical = value.strip()
    lowered = canonical.lower()
    if lowered in {"unknown", "n/a", "none"}:
        return fallback
    services = {item.lower(): item for item in _known_services(incident, context)}
    if lowered in services:
        return services[lowered]
    for service_lower, service_name in services.items():
        if service_lower in lowered or lowered in service_lower:
            return service_name
    return fallback


def _infer_root_from_topology(incident: dict, context: TelemetryContext) -> str:
    service = str(incident.get("service", "")).strip()
    if not service:
        return service
    edges = [edge for edge in context.topology.get("edges", []) if isinstance(edge, dict)]
    if not edges:
        return service
    upstream: dict[str, list[dict]] = {}
    for edge in edges:
        source = str(edge.get("source", "")).strip()
        target = str(edge.get("target", "")).strip()
        if not source or not target:
            continue
        upstream.setdefault(target, []).append(edge)
    queue: list[tuple[str, int, float]] = [(service, 0, 1.0)]
    visited: dict[str, float] = {service: 1.0}
    best = (service, 0.0, 0)  # service, score, depth
    while queue:
        current, depth, score = queue.pop(0)
        for edge in upstream.get(current, []):
            source = str(edge.get("source", "")).strip()
            dep = str(edge.get("dependency_type", "")).strip().lower()
            if not source:
                continue
            if not _is_service_candidate(source, incident, context):
                continue
            weight = 1.0 if dep == "trace_http" else 0.98
            next_score = score * weight * (1 + min(depth + 1, 4) * 0.08)
            if source in visited and visited[source] >= next_score:
                continue
            visited[source] = next_score
            queue.append((source, depth + 1, next_score))
            if depth + 1 > best[2] or (depth + 1 == best[2] and next_score > best[1]):
                best = (source, next_score, depth + 1)
    return best[0] if best[0] else service


def _topology_has_prefix(context: TelemetryContext, prefix: str) -> bool:
    pref = prefix.lower()
    for node in context.topology.get("nodes", []):
        node_id = str(node.get("id", "") if isinstance(node, dict) else node).lower()
        if node_id.startswith(pref):
            return True
    for edge in context.topology.get("edges", []):
        if not isinstance(edge, dict):
            continue
        source = str(edge.get("source", "")).lower()
        target = str(edge.get("target", "")).lower()
        if source.startswith(pref) or target.startswith(pref):
            return True
    return False


def _align_service_with_signal(root_service: str, root_signal: str, context: TelemetryContext) -> str:
    _ = context
    _ = root_signal
    return str(root_service or "").strip()


def _observed_metric_names(context: TelemetryContext) -> list[str]:
    highlights = context.metrics_summary.get("highlights", {}) or {}
    return [str(name).lower() for name in highlights.keys()]


def _quality_by_signal(context: TelemetryContext) -> dict:
    raw = context.telemetry_coverage.get("quality_by_signal", {})
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _telemetry_presence(incident: dict, context: TelemetryContext) -> dict:
    snapshot = incident.get("telemetry_snapshot", {}) or {}
    request_count = float(snapshot.get("request_count", 0) or 0)
    error_rate = float(snapshot.get("error_rate", 0) or 0)
    p95_latency = float(snapshot.get("p95_latency_ms", 0) or 0)
    avg_latency = float(snapshot.get("avg_latency_ms", 0) or 0)
    cpu = float(snapshot.get("cpu_utilization", 0) or 0)
    memory = float(snapshot.get("memory_utilization", 0) or 0)
    log_count = int(context.logs_summary.get("log_count", 0) or snapshot.get("log_count", 0) or 0)
    context_log_count = int(context.logs_summary.get("context_log_count", 0) or 0)
    trace_count = int(context.trace_summary.get("request_count", 0) or 0)
    metric_names = _observed_metric_names(context)
    topology_edges = len(context.topology.get("edges", []) or [])
    timeline_events = len(context.timeline or [])
    detector_signals = len(_as_string_list(incident.get("detector_signals", [])))
    db_dependency_count = len(context.db_summary.get("dependencies", []) or [])
    messaging_flow_count = len(context.messaging_summary.get("flows", []) or [])
    exception_count = int(context.exception_summary.get("exception_count", 0) or 0) + int(context.exception_summary.get("error_span_count", 0) or 0)
    infra_entity_count = sum(len(context.infra_summary.get(key, []) or []) for key in ("pods", "containers", "nodes", "hosts"))
    strong_signals = 0
    if error_rate > 0:
        strong_signals += 1
    if p95_latency > 0 or avg_latency > 0:
        strong_signals += 1
    if cpu > 0:
        strong_signals += 1
    if memory > 0:
        strong_signals += 1
    if log_count > 0:
        strong_signals += 1
    if trace_count > 0:
        strong_signals += 1
    if metric_names:
        strong_signals += 1
    if topology_edges > 0:
        strong_signals += 1
    if timeline_events > 0:
        strong_signals += 1
    if db_dependency_count > 0:
        strong_signals += 1
    if messaging_flow_count > 0:
        strong_signals += 1
    if exception_count > 0:
        strong_signals += 1
    if infra_entity_count > 0:
        strong_signals += 1
    return {
        "request_count": request_count,
        "error_rate": error_rate,
        "p95_latency_ms": p95_latency,
        "avg_latency_ms": avg_latency,
        "cpu_utilization": cpu,
        "memory_utilization": memory,
        "log_count": log_count,
        "context_log_count": context_log_count,
        "trace_count": trace_count,
        "metric_names": metric_names,
        "topology_edges": topology_edges,
        "timeline_events": timeline_events,
        "detector_signals": detector_signals,
        "db_dependency_count": db_dependency_count,
        "messaging_flow_count": messaging_flow_count,
        "exception_count": exception_count,
        "infra_entity_count": infra_entity_count,
        "strong_signals": strong_signals,
    }


def _is_service_candidate(candidate: str, incident: dict, context: TelemetryContext) -> bool:
    known = _known_services(incident, context)
    return str(candidate or "").strip() in known


def _insufficient_telemetry(incident: dict, context: TelemetryContext) -> bool:
    presence = _telemetry_presence(incident, context)
    snapshot = incident.get("telemetry_snapshot", {}) or {}
    snapshot_empty = (
        float(snapshot.get("request_count", 0) or 0) == 0
        and float(snapshot.get("error_rate", 0) or 0) == 0
        and float(snapshot.get("p95_latency_ms", 0) or 0) == 0
        and float(snapshot.get("cpu_utilization", 0) or 0) == 0
        and float(snapshot.get("memory_utilization", 0) or 0) == 0
        and int(snapshot.get("log_count", 0) or 0) == 0
        and not (snapshot.get("trace_ids") or [])
        and not (snapshot.get("metric_highlights") or {})
    )
    predictive = str(incident.get("incident_type", "")).lower() == "predictive"
    if snapshot_empty and predictive:
        return True
    return presence["strong_signals"] <= 1 and presence["detector_signals"] <= 1


def _missing_telemetry(context: TelemetryContext, incident: dict) -> list[str]:
    missing = _as_string_list(context.telemetry_coverage.get("missing_signals", []))
    presence = _telemetry_presence(incident, context)
    quality = _quality_by_signal(context)
    if presence["trace_count"] == 0:
        missing.append("No distributed tracing captured for this incident window")
    if presence["log_count"] == 0:
        missing.append("No incident-scoped logs captured for this incident window")
    if quality.get("metrics") == "zero":
        missing.append("Metrics are present, but their values are zero across the incident window")
    elif not presence["metric_names"] and presence["cpu_utilization"] == 0 and presence["memory_utilization"] == 0:
        missing.append("No service-level metrics captured for this incident window")
    if presence["db_dependency_count"] == 0:
        missing.append("No database dependency evidence captured for this incident window")
    if presence["messaging_flow_count"] == 0:
        missing.append("No messaging dependency evidence captured for this incident window")
    if presence["exception_count"] == 0:
        missing.append("No exception evidence captured for this incident window")
    if presence["infra_entity_count"] == 0:
        missing.append("No runtime host/container evidence captured for this incident window")
    if presence["request_count"] == 0 and presence["trace_count"] == 0:
        missing.append("No request activity was observed for this incident scope")
    return dedupe_list([item for item in missing if item])


def _evidence_score(incident: dict, context: TelemetryContext) -> float:
    presence = _telemetry_presence(incident, context)
    if _insufficient_telemetry(incident, context):
        return 0.18
    score = 0.0
    if presence["trace_count"] > 0:
        score += 0.2
    if presence["log_count"] > 0:
        score += 0.15
    if presence["metric_names"] or presence["cpu_utilization"] > 0 or presence["memory_utilization"] > 0:
        score += 0.15
    if presence["request_count"] > 0:
        score += 0.15
    if presence["topology_edges"] > 0:
        score += 0.1
    if presence["timeline_events"] > 0:
        score += 0.1
    if presence["db_dependency_count"] > 0:
        score += 0.08
    if presence["messaging_flow_count"] > 0:
        score += 0.08
    if presence["exception_count"] > 0:
        score += 0.06
    if presence["infra_entity_count"] > 0:
        score += 0.05
    if presence["detector_signals"] > 0:
        score += min(0.15, presence["detector_signals"] * 0.05)
    if presence["context_log_count"] > 0:
        score += 0.05
    quality = _quality_by_signal(context)
    degraded_signals = sum(1 for value in quality.values() if value in {"missing", "sparse", "stale", "zero", "contradictory"})
    if degraded_signals > 0:
        score -= min(0.2, degraded_signals * 0.08)
    return max(0.0, min(1.0, score))


def _generic_signal_label(incident: dict, context: TelemetryContext) -> str:
    detector_signals = _as_string_list(incident.get("detector_signals", []))
    if detector_signals:
        return detector_signals[0]
    presence = _telemetry_presence(incident, context)
    if presence["p95_latency_ms"] > 0:
        return "latency_anomaly"
    if presence["error_rate"] > 0:
        return "error_rate_anomaly"
    if presence["cpu_utilization"] > 0:
        return "cpu_pressure"
    if presence["memory_utilization"] > 0:
        return "memory_pressure"
    if presence["log_count"] > 0:
        return "log_anomaly"
    return "insufficient_telemetry"


def fallback_reasoning(incident: dict, context: TelemetryContext, historical_matches: list[dict]) -> dict:
    service = incident["service"]
    incident_type = incident.get("incident_type", "observed")
    insufficient = _insufficient_telemetry(incident, context)
    signal = _generic_signal_label(incident, context)
    inferred_service = service if insufficient else _infer_root_from_topology(incident, context)
    missing = _missing_telemetry(context, incident)
    confidence = 0.18 if insufficient else max(0.22, min(0.72, _evidence_score(incident, context)))
    topology_edges = context.topology.get("edges", []) or []
    propagation_path = []
    if not insufficient:
        propagation_path = [
            " -> ".join(
                [str(edge.get("source", "")).strip(), str(edge.get("target", "")).strip()]
            ).strip(" ->")
            for edge in topology_edges[:3]
            if edge.get("source") and edge.get("target")
        ]
    remediation = [] if insufficient else build_remediation_steps(
        service,
        incident.get("namespace", ""),
        _as_string_list(incident.get("detector_signals", [])),
        incident_type,
    )
    root_cause = (
        "Insufficient telemetry to determine root cause. "
        "Available incident evidence does not contain enough logs, traces, metrics, or dependency data to support a specific RCA."
        if insufficient
        else f"Observed evidence points to {inferred_service} as the most likely source of the incident."
    )
    impact_assessment = (
        "Root cause could not be determined confidently because incident-scoped telemetry is sparse."
        if insufficient
        else f"Incident is currently centered on {service} within namespace {incident['namespace']} based on observed telemetry."
    )
    customer_impact = (
        "Customer impact cannot be estimated confidently until more telemetry is available."
        if insufficient
        else f"Customer-facing impact is possible if {service} participates in active request paths."
    )
    return {
        "root_cause": root_cause,
        "root_cause_service": inferred_service,
        "root_cause_signal": signal,
        "confidence_score": confidence,
        "causal_chain": [] if insufficient else [root_cause],
        "correlated_signals": _as_string_list(incident.get("detector_signals", [])) if not insufficient else [],
        "propagation_path": propagation_path,
        "impact_assessment": impact_assessment,
        "customer_impact": customer_impact,
        "recommended_actions": (
            [f"Collect additional telemetry for {service}.", "Re-run reasoning after traces, metrics, or logs are available."]
            if insufficient
            else remediation
        ),
        "missing_telemetry_signals": missing,
        "observability_score": _as_float(context.telemetry_coverage.get("observability_score", 0)),
        "observability_summary": normalize_summary(context.telemetry_coverage),
        "deployment_correlation": summarize_deployments(context.deployment_correlation.get("events", [])),
        "historical_matches": historical_matches,
        "severity": incident["severity"],
        "confidence_explanation": build_confidence_explanation(
            incident,
            context,
            {
                "confidence_score": confidence,
                "root_cause_service": inferred_service,
                "root_cause_signal": signal,
                "missing_telemetry_signals": missing,
                "observability_score": _as_float(context.telemetry_coverage.get("observability_score", 0)),
            },
        ),
    }


def generate_reasoning(llm: LLMProvider, incident: dict, context: TelemetryContext, historical_matches: list[dict]) -> dict:
    fallback = fallback_reasoning(incident, context, historical_matches)
    if _insufficient_telemetry(incident, context):
        return fallback

    raw = llm.generate_reasoning(build_prompt(incident, context, historical_matches))
    try:
        parsed = json.loads(extract_json(raw))
        if not isinstance(parsed, dict):
            parsed = {}
    except json.JSONDecodeError:
        parsed = {}
    fallback_service = _normalize_root_cause_service(
        _as_string(parsed.get("root_cause_service"), fallback["root_cause_service"]),
        incident,
        context,
    )
    remediation = build_remediation_steps(
        incident.get("service", ""),
        incident.get("namespace", ""),
        _as_string_list(incident.get("detector_signals", [])),
        incident.get("incident_type", "observed"),
    )
    result = {
        "root_cause": _as_string(parsed.get("root_cause"), fallback["root_cause"]),
        "root_cause_service": fallback_service,
        "root_cause_signal": _as_string(parsed.get("root_cause_signal"), fallback["root_cause_signal"]),
        "confidence_score": _as_float(parsed.get("confidence_score"), fallback["confidence_score"]),
        "causal_chain": _as_string_list(parsed.get("causal_chain"), fallback["causal_chain"]),
        "correlated_signals": _as_string_list(parsed.get("correlated_signals"), fallback["correlated_signals"]),
        "propagation_path": _as_string_list(parsed.get("propagation_path"), fallback["propagation_path"]),
        "impact_assessment": _as_string(parsed.get("impact_assessment"), fallback["impact_assessment"]),
        "customer_impact": _as_string(parsed.get("customer_impact"), fallback["customer_impact"]),
        "recommended_actions": dedupe_list(_as_string_list(parsed.get("recommended_actions"), fallback["recommended_actions"]) + remediation),
        "missing_telemetry_signals": _as_string_list(parsed.get("missing_telemetry_signals"), fallback["missing_telemetry_signals"]),
        "observability_score": _as_float(parsed.get("observability_score"), fallback["observability_score"]),
        "observability_summary": _as_summary(parsed.get("observability_summary"), fallback["observability_summary"]),
        "deployment_correlation": _as_string(
            parsed.get("deployment_correlation"),
            fallback["deployment_correlation"],
        ),
        "historical_matches": _as_history(parsed.get("historical_matches"), fallback["historical_matches"]),
        "severity": _as_string(parsed.get("severity"), incident["severity"]),
    }
    result["root_cause_service"] = _align_service_with_signal(
        result["root_cause_service"],
        result["root_cause_signal"],
        context,
    )
    result["confidence_score"] = max(0.1, min(result["confidence_score"], max(fallback["confidence_score"], _evidence_score(incident, context))))
    result["missing_telemetry_signals"] = dedupe_list(
        _as_string_list(result.get("missing_telemetry_signals"), []) + _missing_telemetry(context, incident)
    )
    result["confidence_explanation"] = build_confidence_explanation(incident, context, result)
    return result


def build_confidence_explanation(incident: dict, context: TelemetryContext, reasoning: dict) -> dict:
    score = _as_float(reasoning.get("confidence_score"), 0.0)
    level = "low"
    if score >= 0.75:
        level = "high"
    elif score >= 0.5:
        level = "medium"

    supporting_factors = []
    detector_signals = _as_string_list(incident.get("detector_signals", []))
    if detector_signals:
        supporting_factors.append(f"Signals detected: {', '.join(detector_signals[:4])}")
    if incident.get("dependency_chain"):
        supporting_factors.append("Dependency chain confirms propagation context")
    if context.timeline:
        supporting_factors.append("Timeline evidence contains recent anomaly events")
    presence = _telemetry_presence(incident, context)
    snapshot = incident.get("telemetry_snapshot", {}) or {}
    direct_trace_count = int(len(snapshot.get("trace_ids", []) or []))
    direct_log_count = int(snapshot.get("log_count", 0) or 0)
    if presence["trace_count"] > 0:
        if direct_trace_count > 0:
            supporting_factors.append(f"Incident-scoped trace evidence present ({presence['trace_count']} requests)")
        else:
            supporting_factors.append(f"Broader scoped trace evidence present ({presence['trace_count']} requests)")
    if presence["log_count"] > 0:
        if direct_log_count > 0:
            supporting_factors.append(f"Incident-scoped logs present ({presence['log_count']} events)")
        else:
            supporting_factors.append(f"Broader scoped logs present ({presence['log_count']} events)")
    if presence["db_dependency_count"] > 0:
        supporting_factors.append(f"Contextual database evidence present ({presence['db_dependency_count']} dependencies)")
    if presence["messaging_flow_count"] > 0:
        supporting_factors.append(f"Contextual messaging evidence present ({presence['messaging_flow_count']} flows)")
    if presence["exception_count"] > 0:
        supporting_factors.append(f"Exception evidence present ({presence['exception_count']} signals)")

    weakening_factors = []
    missing = _as_string_list(reasoning.get("missing_telemetry_signals", []))
    if missing:
        weakening_factors.append(f"Missing telemetry: {', '.join(missing[:3])}")
    observability_score = _as_float(reasoning.get("observability_score"), 0.0)
    if observability_score < 50:
        weakening_factors.append("Observability coverage is below 50%")
    if presence["trace_count"] == 0:
        weakening_factors.append("Trace coverage is limited for this incident")
    if _quality_by_signal(context).get("metrics") == "zero":
        weakening_factors.append("Metrics exist but remain at zero values for this incident window")
    if _insufficient_telemetry(incident, context):
        weakening_factors.append("Telemetry volume is too sparse to support a specific root cause")

    evidence_count = len(detector_signals) + len(context.timeline or []) + int(presence["trace_count"] > 0) + int(presence["log_count"] > 0)
    missing_signal_count = len(missing)
    if _insufficient_telemetry(incident, context):
        explanation_text = (
            "Confidence is low because the available incident telemetry is too sparse to support a specific root cause."
        )
    else:
        explanation_text = (
            f"Confidence is {level} because incident evidence points to "
            f"{reasoning.get('root_cause_service', incident.get('service', 'the service'))}, "
            "but missing telemetry still reduces certainty."
        )

    return {
        "score": score,
        "level": level,
        "supporting_factors": supporting_factors,
        "weakening_factors": weakening_factors,
        "evidence_count": evidence_count,
        "missing_signal_count": missing_signal_count,
        "explanation_text": explanation_text,
    }


def normalize_summary(summary: dict) -> dict:
    normalized: dict[str, str] = {}
    for key, value in summary.items():
        normalized[str(key)] = str(value)
    return normalized


def summarize_deployments(events: list[dict]) -> str:
    if not events:
        return "No deployment evidence detected near the incident timestamp."
    latest = events[0]
    return f"Deployment-related event near incident: {latest.get('details', '')}"


def extract_json(raw: str) -> str:
    cleaned = raw.strip()
    cleaned = re.sub(r"^```json\s*", "", cleaned)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    start = cleaned.find("{")
    if start != -1:
        depth = 0
        in_string = False
        escape = False
        for index in range(start, len(cleaned)):
            char = cleaned[index]
            if in_string:
                if escape:
                    escape = False
                elif char == "\\":
                    escape = True
                elif char == "\"":
                    in_string = False
                continue
            if char == "\"":
                in_string = True
            elif char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
                if depth == 0:
                    return cleaned[start : index + 1]
    return cleaned


def dedupe_list(items: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        ordered.append(item)
    return ordered

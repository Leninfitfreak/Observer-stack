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
    return {
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
        },
        "trace_summary": context.trace_summary,
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
        "Use the provided metrics, logs, traces, topology, telemetry coverage, deployment evidence, and historical incidents "
        "to determine the most probable root cause service and signal. "
        "Set root_cause_service to an actual service name from incident.service or topology.nodes, never to a span/operation name. "
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
    lowered = value.lower()
    if lowered.startswith("kafka:"):
        lowered = "kafka"
        value = "kafka"
    if lowered.startswith("db:"):
        if "postgres" in lowered:
            lowered = "postgres"
            value = "postgres"
        else:
            lowered = "database"
            value = "database"
    if lowered in {"leninkart", "unknown", "n/a", "none"}:
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
    # Prefer the earliest upstream service; messaging/database origins get higher priority.
    queue: list[tuple[str, int, float]] = [(service, 0, 1.0)]
    visited: dict[str, float] = {service: 1.0}
    best = (service, 0.0, 0)  # service, score, depth
    while queue:
        current, depth, score = queue.pop(0)
        for edge in upstream.get(current, []):
            source = str(edge.get("source", "")).strip()
            dep = str(edge.get("dependency_type", "")).strip().lower()
            weight = 1.0
            if dep == "messaging_kafka":
                weight = 1.2
            elif dep == "database":
                weight = 1.1
            elif dep == "trace_http":
                weight = 0.95
            next_score = score * weight * (1 + min(depth + 1, 4) * 0.08)
            if source in visited and visited[source] >= next_score:
                continue
            visited[source] = next_score
            queue.append((source, depth + 1, next_score))
            if depth + 1 > best[2] or (depth + 1 == best[2] and next_score > best[1]):
                best = (source, next_score, depth + 1)
    selected = best[0] if best[0] else service
    selected_lower = selected.lower()
    if selected_lower.startswith("kafka:"):
        return "kafka"
    if selected_lower.startswith("db:"):
        if "postgres" in selected_lower:
            return "postgres"
        return "database"
    return selected


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
    service = str(root_service or "").strip()
    signal = str(root_signal or "").lower()
    if "kafka" in signal and (_topology_has_prefix(context, "kafka:") or _topology_has_prefix(context, "kafka")):
        return "kafka"
    if ("db." in signal or "postgres" in signal or "database" in signal) and _topology_has_prefix(context, "db:"):
        if _topology_has_prefix(context, "db:postgres"):
            return "postgres"
        return "database"
    return service


def fallback_reasoning(incident: dict, context: TelemetryContext, historical_matches: list[dict]) -> dict:
    service = incident["service"]
    inferred_service = _infer_root_from_topology(incident, context)
    signal = incident["detector_signals"][0] if incident["detector_signals"] else "unknown"
    incident_type = incident.get("incident_type", "observed")
    root_cause = f"Primary anomaly source is {inferred_service} driven by {signal.replace('_', ' ')}."
    if incident_type == "predictive":
        root_cause = f"Predicted near-term anomaly source is {inferred_service} based on rising telemetry trend ({signal.replace('_', ' ')})."
    if signal == "log_anomaly":
        root_cause = f"Primary anomaly source is {inferred_service} driven by elevated warning or error log activity."
    propagation_path = [edge.get("source") for edge in context.topology.get("edges", [])[:1] if edge.get("source")]
    if context.topology.get("edges"):
        propagation_path.append(service)
    remediation = build_remediation_steps(
        service,
        incident.get("namespace", ""),
        _as_string_list(incident.get("detector_signals", [])),
        incident_type,
    )
    return {
        "root_cause": root_cause,
        "root_cause_service": inferred_service,
        "root_cause_signal": signal,
        "confidence_score": _as_float(incident.get("predictive_confidence"), 0.62),
        "causal_chain": [root_cause],
        "correlated_signals": _as_string_list(incident.get("detector_signals", [])),
        "propagation_path": propagation_path,
        "impact_assessment": f"Incident is currently centered on {service} in namespace {incident['namespace']}.",
        "customer_impact": f"Customer-facing impact is possible if {service} participates in active request paths.",
        "recommended_actions": remediation
        + [
            f"Inspect recent logs and runtime events for {service}.",
            f"Validate deployments and configuration changes affecting {service}.",
        ],
        "missing_telemetry_signals": _as_string_list(context.telemetry_coverage.get("missing_signals", [])),
        "observability_score": _as_float(context.telemetry_coverage.get("observability_score", 0)),
        "observability_summary": normalize_summary(context.telemetry_coverage),
        "deployment_correlation": summarize_deployments(context.deployment_correlation.get("events", [])),
        "historical_matches": historical_matches,
        "severity": incident["severity"],
        "confidence_explanation": build_confidence_explanation(
            incident,
            context,
            {
                "confidence_score": _as_float(incident.get("predictive_confidence"), 0.62),
                "root_cause_service": inferred_service,
                "root_cause_signal": signal,
                "missing_telemetry_signals": _as_string_list(context.telemetry_coverage.get("missing_signals", [])),
            },
        ),
    }


def generate_reasoning(llm: LLMProvider, incident: dict, context: TelemetryContext, historical_matches: list[dict]) -> dict:
    raw = llm.generate_reasoning(build_prompt(incident, context, historical_matches))
    fallback = fallback_reasoning(incident, context, historical_matches)
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

    weakening_factors = []
    missing = _as_string_list(reasoning.get("missing_telemetry_signals", []))
    if missing:
        weakening_factors.append(f"Missing telemetry: {', '.join(missing[:3])}")
    observability_score = _as_float(reasoning.get("observability_score"), 0.0)
    if observability_score < 50:
        weakening_factors.append("Observability coverage is below 50%")
    if not context.trace_summary:
        weakening_factors.append("Trace coverage is limited for this incident")

    evidence_count = len(detector_signals) + len(context.timeline or [])
    missing_signal_count = len(missing)
    explanation_text = (
        f"Confidence is {level} because root cause evidence points to "
        f"{reasoning.get('root_cause_service', incident.get('service', 'the service'))}, "
        "but gaps in telemetry reduce certainty."
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

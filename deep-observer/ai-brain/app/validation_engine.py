from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ValidationReport:
    incident_id: str
    reasoning_statements: list[str]
    supporting_signals: list[str]
    unsupported_statements: list[str]
    validation_result: str
    confidence_score: float


def validate_reasoning(incident: dict, context, reasoning: dict, known_services: set[str]) -> ValidationReport:
    statements: list[str] = []
    supports: list[str] = []
    unsupported: list[str] = []

    root_cause_service = str(reasoning.get("root_cause_service", "")).strip()
    if root_cause_service:
        statements.append(f"root_cause_service={root_cause_service}")
        if root_cause_service in known_services:
            supports.append(f"service_exists:{root_cause_service}")
        elif not root_cause_service.startswith(("db:", "messaging:")):
            unsupported.append(f"service_not_found:{root_cause_service}")

    root_signal = str(reasoning.get("root_cause_signal", "")).lower()
    snapshot = incident.get("telemetry_snapshot", {}) or {}
    detector_signals = [str(item).lower() for item in incident.get("detector_signals", [])]
    metric_names = [str(name).lower() for name in (context.metrics_summary.get("highlights", {}) or {}).keys()]
    topology_edges = context.topology.get("edges", []) or []

    if root_signal:
        statements.append(f"root_cause_signal={root_signal}")
        if "cpu" in root_signal:
            cpu = float(snapshot.get("cpu_utilization", 0) or 0)
            if cpu >= 0.8 or cpu >= 80:
                supports.append("cpu_saturation_evidence")
            else:
                unsupported.append("cpu_claim_without_threshold_breach")
        if "memory" in root_signal:
            memory = float(snapshot.get("memory_utilization", 0) or 0)
            if memory >= 0.8 or memory >= 80:
                supports.append("memory_pressure_evidence")
            else:
                unsupported.append("memory_claim_without_threshold_breach")
        if "latency" in root_signal:
            p95 = float(snapshot.get("p95_latency_ms", 0) or 0)
            baseline = float(snapshot.get("baseline_latency_ms", 0) or 0)
            if p95 > 0 and (baseline <= 0 or p95 >= baseline * 1.2):
                supports.append("latency_spike_evidence")
            else:
                unsupported.append("latency_claim_without_spike")
        if "db" in root_signal or "database" in root_signal:
            if any(str(edge.get("target", "")).startswith("db:") for edge in topology_edges):
                supports.append("database_dependency_evidence")
            else:
                unsupported.append("database_claim_without_dependency")
        if "messag" in root_signal or "queue" in root_signal or "topic" in root_signal or "consumer" in root_signal:
            if any(str(edge.get("target", "")).startswith("messaging:") for edge in topology_edges) or any(
                any(token in name for token in ("messag", "queue", "topic", "consumer"))
                for name in metric_names
            ):
                supports.append("messaging_dependency_evidence")
            else:
                unsupported.append("messaging_claim_without_evidence")

    if reasoning.get("causal_chain"):
        statements.append("causal_chain_present")
        if topology_edges:
            supports.append("topology_edges_present")
        else:
            unsupported.append("causal_chain_without_topology")

    ratio = 0.0
    total = len(supports) + len(unsupported)
    if total > 0:
        ratio = len(supports) / total

    if unsupported and ratio < 0.5:
        result = "unsupported"
    elif unsupported:
        result = "partial"
    else:
        result = "supported"

    if not detector_signals and not metric_names and not topology_edges:
        confidence = 0.15
    else:
        confidence = max(0.1, min(0.99, ratio if total > 0 else 0.4))
    return ValidationReport(
        incident_id=incident.get("incident_id", ""),
        reasoning_statements=statements,
        supporting_signals=supports,
        unsupported_statements=unsupported,
        validation_result=result,
        confidence_score=round(confidence, 2),
    )


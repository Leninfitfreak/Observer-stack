from __future__ import annotations

import re
from dataclasses import dataclass, field

from .reasoner import (
    _evidence_score,
    _generic_signal_label,
    _missing_telemetry,
    _normalize_entity_reference,
    _normalize_reasoning_path,
    _quality_by_signal,
    _telemetry_presence,
    build_confidence_explanation,
    fallback_reasoning,
)


@dataclass
class ValidationReport:
    incident_id: str
    reasoning_statements: list[str]
    supporting_signals: list[str]
    unsupported_statements: list[str]
    validation_result: str
    confidence_score: float
    unsupported_claims_count: int = 0
    normalized_output: bool = False
    evidence_binding: str = "direct"
    corrections: list[str] = field(default_factory=list)
    raw_model_output_summary: dict = field(default_factory=dict)


def _direct_signals(incident: dict) -> list[str]:
    return [str(item).strip().lower() for item in incident.get("detector_signals", []) if str(item).strip()]


def _supported_contextual_signals(incident: dict, context) -> list[str]:
    snapshot = incident.get("telemetry_snapshot", {}) or {}
    presence = _telemetry_presence(incident, context)
    supported: list[str] = []
    p95 = float(snapshot.get("p95_latency_ms", 0) or presence.get("p95_latency_ms", 0) or 0)
    baseline = float(snapshot.get("baseline_latency_ms", 0) or 0)
    error_rate = float(snapshot.get("error_rate", 0) or presence.get("error_rate", 0) or 0)
    cpu = float(snapshot.get("cpu_utilization", 0) or 0)
    memory = float(snapshot.get("memory_utilization", 0) or 0)
    if p95 > 0 and (baseline <= 0 or p95 >= baseline * 1.2):
        supported.append("latency_spike")
    if error_rate > 0:
        supported.append("error_rate_increase")
    if cpu >= 0.8 or cpu >= 80:
        supported.append("cpu_saturation")
    if memory >= 0.8 or memory >= 80:
        supported.append("memory_pressure")
    if presence.get("log_count", 0) > 0:
        supported.append("log_anomaly")
    if presence.get("db_dependency_count", 0) > 0:
        supported.append("database_dependency")
    if presence.get("messaging_flow_count", 0) > 0:
        supported.append("messaging_dependency")
    if presence.get("exception_count", 0) > 0:
        supported.append("exception_anomaly")
    return list(dict.fromkeys(supported))


def _allowed_services(incident: dict, context, known_services: set[str]) -> set[str]:
    allowed = {str(incident.get("service", "")).strip()}
    for impact in incident.get("impacts", []) or []:
        if isinstance(impact, dict):
            candidate = str(impact.get("service", "")).strip()
        else:
            candidate = str(getattr(impact, "service", "")).strip()
        normalized = _normalize_entity_reference(candidate)
        if normalized and normalized in known_services:
            allowed.add(normalized)
    for node in context.topology.get("nodes", []) or []:
        node_id = str(node.get("id", "") if isinstance(node, dict) else node).strip()
        normalized = _normalize_entity_reference(node_id)
        if normalized and normalized in known_services:
            allowed.add(normalized)
    return {item for item in allowed if item}


def _allowed_entities(context) -> set[str]:
    entities: set[str] = set()
    for node in context.topology.get("nodes", []) or []:
        node_id = str(node.get("id", "") if isinstance(node, dict) else node).strip()
        normalized = _normalize_entity_reference(node_id)
        if normalized:
            entities.add(normalized)
    for edge in context.topology.get("edges", []) or []:
        if not isinstance(edge, dict):
            continue
        for key in ("source", "target"):
            normalized = _normalize_entity_reference(edge.get(key, ""))
            if normalized:
                entities.add(normalized)
    return entities


def _signal_binding(root_signal: str, incident: dict, context) -> tuple[str, str, list[str], list[str], list[str]]:
    direct = _direct_signals(incident)
    contextual = _supported_contextual_signals(incident, context)
    supports: list[str] = []
    unsupported: list[str] = []
    corrections: list[str] = []
    candidate = str(root_signal or "").strip().lower()
    if direct:
        if candidate in direct:
            supports.append(f"direct_signal:{candidate}")
            return candidate, "direct", supports, unsupported, corrections
        unsupported.append(f"unsupported_root_cause_signal:{candidate or 'missing'}")
        corrected = direct[0]
        corrections.append(f"root_cause_signal:{candidate or 'missing'}->{corrected}")
        supports.append(f"direct_signal:{corrected}")
        return corrected, "direct", supports, unsupported, corrections
    if candidate and candidate in contextual:
        supports.append(f"contextual_signal:{candidate}")
        return candidate, "contextual", supports, unsupported, corrections
    if contextual:
        unsupported.append(f"unsupported_root_cause_signal:{candidate or 'missing'}")
        corrected = contextual[0]
        corrections.append(f"root_cause_signal:{candidate or 'missing'}->{corrected}")
        supports.append(f"contextual_signal:{corrected}")
        return corrected, "contextual", supports, unsupported, corrections
    corrected = _generic_signal_label(incident, context)
    if candidate and candidate != corrected:
        unsupported.append(f"unsupported_root_cause_signal:{candidate}")
        corrections.append(f"root_cause_signal:{candidate}->{corrected}")
    supports.append(f"fallback_signal:{corrected}")
    return corrected, "corrected", supports, unsupported, corrections


def _bind_service(root_service: str, incident: dict, context, known_services: set[str]) -> tuple[str, list[str], list[str], list[str]]:
    allowed = _allowed_services(incident, context, known_services)
    candidate = _normalize_entity_reference(root_service)
    supports: list[str] = []
    unsupported: list[str] = []
    corrections: list[str] = []
    fallback = str(incident.get("service", "")).strip()
    if candidate and candidate in allowed:
        supports.append(f"allowed_service:{candidate}")
        return candidate, supports, unsupported, corrections
    if candidate:
        unsupported.append(f"unsupported_root_cause_service:{candidate}")
    corrected = fallback if fallback in allowed or fallback else next(iter(allowed), fallback)
    if corrected and corrected != candidate:
        corrections.append(f"root_cause_service:{candidate or 'missing'}->{corrected}")
        supports.append(f"allowed_service:{corrected}")
    return corrected, supports, unsupported, corrections


def _sanitize_actions(actions: list[str], incident: dict, context, bound_signal: str) -> tuple[list[str], list[str], list[str]]:
    presence = _telemetry_presence(incident, context)
    allowed_memory = presence.get("infra_entity_count", 0) > 0 and (
        float((incident.get("telemetry_snapshot", {}) or {}).get("memory_utilization", 0) or 0) >= 0.8
        or float((incident.get("telemetry_snapshot", {}) or {}).get("memory_utilization", 0) or 0) >= 80
        or bound_signal == "memory_pressure"
    )
    allowed_cpu = float((incident.get("telemetry_snapshot", {}) or {}).get("cpu_utilization", 0) or 0) >= 0.8 or bound_signal == "cpu_saturation"
    allowed_db = presence.get("db_dependency_count", 0) > 0
    allowed_messaging = presence.get("messaging_flow_count", 0) > 0
    allowed_exceptions = presence.get("exception_count", 0) > 0
    filtered: list[str] = []
    blocked: list[str] = []
    corrections: list[str] = []
    for action in actions:
        text = str(action or "").strip()
        if not text:
            continue
        lowered = text.lower()
        if re.search(r"\bmemory\b", lowered) and not allowed_memory:
            blocked.append(f"unsupported_action:{text}")
            corrections.append("removed_memory_action")
            continue
        if re.search(r"\bcpu\b", lowered) and not allowed_cpu:
            blocked.append(f"unsupported_action:{text}")
            corrections.append("removed_cpu_action")
            continue
        if re.search(r"\b(db|database|postgres|sql)\b", lowered) and not allowed_db:
            blocked.append(f"unsupported_action:{text}")
            corrections.append("removed_database_action")
            continue
        if re.search(r"\b(kafka|messag|queue|topic|consumer|producer)\b", lowered) and not allowed_messaging:
            blocked.append(f"unsupported_action:{text}")
            corrections.append("removed_messaging_action")
            continue
        if re.search(r"\b(exception|stack trace|stacktrace)\b", lowered) and not allowed_exceptions:
            blocked.append(f"unsupported_action:{text}")
            corrections.append("removed_exception_action")
            continue
        filtered.append(text)
    return list(dict.fromkeys(filtered)), blocked, corrections


def _bind_paths(values: list[str], context) -> tuple[list[str], list[str], list[str]]:
    allowed_entities = _allowed_entities(context)
    normalized = _normalize_reasoning_path(values)
    kept: list[str] = []
    unsupported: list[str] = []
    corrections: list[str] = []
    for item in normalized:
        if " -> " in item:
            parts = [part.strip() for part in item.split(" -> ") if part.strip()]
            if all(_normalize_entity_reference(part) in allowed_entities for part in parts):
                kept.append(item)
            else:
                unsupported.append(f"unsupported_path:{item}")
                corrections.append(f"removed_path:{item}")
            continue
        if _normalize_entity_reference(item) in allowed_entities:
            kept.append(item)
        else:
            unsupported.append(f"unsupported_chain:{item}")
            corrections.append(f"removed_chain:{item}")
    return kept, unsupported, corrections


def _validation_summary(report: ValidationReport) -> str:
    if not report.normalized_output and report.validation_result == "supported":
        return ""
    if report.normalized_output:
        return "Model output contained unsupported claims; corrected using evidence validation."
    if report.validation_result in {"partial", "fallback_validation"}:
        return "Model output was partially supported and was constrained to selected-incident evidence."
    return ""


def validate_and_bind_reasoning(incident: dict, context, reasoning: dict, known_services: set[str]) -> tuple[dict, ValidationReport]:
    raw_summary = {
        "root_cause": str(reasoning.get("root_cause", "")).strip(),
        "root_cause_service": str(reasoning.get("root_cause_service", "")).strip(),
        "root_cause_signal": str(reasoning.get("root_cause_signal", "")).strip(),
        "recommended_actions": [str(item).strip() for item in reasoning.get("recommended_actions", [])[:5]],
    }
    corrected = dict(reasoning)
    statements: list[str] = []
    supports: list[str] = []
    unsupported: list[str] = []
    corrections: list[str] = []

    bound_service, svc_supports, svc_unsupported, svc_corrections = _bind_service(
        corrected.get("root_cause_service", ""),
        incident,
        context,
        known_services,
    )
    corrected["root_cause_service"] = bound_service
    supports.extend(svc_supports)
    unsupported.extend(svc_unsupported)
    corrections.extend(svc_corrections)
    statements.append(f"root_cause_service={bound_service}")

    bound_signal, binding_level, sig_supports, sig_unsupported, sig_corrections = _signal_binding(
        corrected.get("root_cause_signal", ""),
        incident,
        context,
    )
    corrected["root_cause_signal"] = bound_signal
    supports.extend(sig_supports)
    unsupported.extend(sig_unsupported)
    corrections.extend(sig_corrections)
    statements.append(f"root_cause_signal={bound_signal}")

    bound_actions, action_unsupported, action_corrections = _sanitize_actions(
        corrected.get("recommended_actions", []),
        incident,
        context,
        bound_signal,
    )
    if not bound_actions:
        fallback = fallback_reasoning(incident, context, [])
        bound_actions = fallback.get("recommended_actions", [])
        if not bound_actions:
            bound_actions = [f"Review direct telemetry evidence for `{incident.get('service', '')}`."]
        corrections.append("replaced_actions_with_evidence_backed_actions")
    corrected["recommended_actions"] = bound_actions
    unsupported.extend(action_unsupported)
    corrections.extend(action_corrections)

    bound_chain, chain_unsupported, chain_corrections = _bind_paths(corrected.get("causal_chain", []), context)
    bound_path, path_unsupported, path_corrections = _bind_paths(corrected.get("propagation_path", []), context)
    corrected["causal_chain"] = bound_chain
    corrected["propagation_path"] = bound_path
    unsupported.extend(chain_unsupported + path_unsupported)
    corrections.extend(chain_corrections + path_corrections)

    normalized_output = bool(corrections or unsupported)
    fallback = fallback_reasoning(incident, context, [])
    evidence_score = _evidence_score(incident, context)
    if binding_level != "direct":
        corrected["confidence_score"] = min(float(corrected.get("confidence_score", 0) or 0), max(0.35, min(0.65, evidence_score)))
    if normalized_output:
        corrected["confidence_score"] = min(float(corrected.get("confidence_score", 0) or 0), max(0.35, fallback.get("confidence_score", 0.18)))
    corrected["confidence_score"] = round(max(0.1, min(0.99, float(corrected.get("confidence_score", 0) or 0))), 2)

    if normalized_output:
        if binding_level == "direct":
            corrected["root_cause"] = (
                f"Observed evidence points to {bound_service} as the most likely source of the incident, "
                f"with strongest direct signal {bound_signal}."
            )
            corrected["impact_assessment"] = (
                f"Incident is currently centered on {incident.get('service', '')} within namespace {incident.get('namespace', '')} "
                "based on selected-incident telemetry."
            )
        else:
            corrected["root_cause"] = (
                f"Available evidence suggests {bound_service} as the most likely source of the incident, "
                f"but the strongest supporting signal ({bound_signal}) is contextual rather than direct."
            )
            corrected["impact_assessment"] = (
                "Root cause is evidence-bounded and partially contextual because direct selected-incident evidence is limited."
            )

    corrected["missing_telemetry_signals"] = list(dict.fromkeys(
        [str(item) for item in corrected.get("missing_telemetry_signals", []) if str(item).strip()] +
        _missing_telemetry(context, incident)
    ))
    corrected["confidence_explanation"] = build_confidence_explanation(incident, context, corrected)

    validation_result = "supported"
    if normalized_output and binding_level == "corrected":
        validation_result = "corrected"
    elif normalized_output:
        validation_result = "corrected"
    elif unsupported:
        validation_result = "partial"

    report = ValidationReport(
        incident_id=incident.get("incident_id", ""),
        reasoning_statements=statements,
        supporting_signals=list(dict.fromkeys(supports)),
        unsupported_statements=list(dict.fromkeys(unsupported)),
        validation_result=validation_result,
        confidence_score=corrected["confidence_score"],
        unsupported_claims_count=len(list(dict.fromkeys(unsupported))),
        normalized_output=normalized_output,
        evidence_binding=binding_level,
        corrections=list(dict.fromkeys(corrections)),
        raw_model_output_summary=raw_summary,
    )
    corrected["validation_summary"] = _validation_summary(report)
    corrected["validation_status"] = report.validation_result
    corrected["unsupported_claims"] = report.unsupported_statements
    corrected["unsupported_claims_count"] = report.unsupported_claims_count
    corrected["normalized_after_generation"] = report.normalized_output
    corrected["evidence_binding"] = report.evidence_binding
    corrected["raw_model_output_summary"] = report.raw_model_output_summary
    return corrected, report


def validate_reasoning(incident: dict, context, reasoning: dict, known_services: set[str]) -> ValidationReport:
    _, report = validate_and_bind_reasoning(incident, context, reasoning, known_services)
    return report

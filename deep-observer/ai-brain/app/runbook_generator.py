from __future__ import annotations

import hashlib


def generate_runbook(incident: dict, reasoning: dict, historical_matches: list[dict]) -> dict:
    incident_type = str(incident.get("incident_type", "observed"))
    root_signal = str(reasoning.get("root_cause_signal", "unknown"))
    service = str(incident.get("service", "unknown-service"))
    namespace = str(incident.get("namespace", "default")) or "default"

    steps = [
        f"Validate incident scope in service `{service}` namespace `{namespace}`.",
        f"Review telemetry for signal `{root_signal}`.",
    ]
    steps.extend(signal_driven_steps(incident, reasoning))
    for action in reasoning.get("recommended_actions", [])[:4]:
        text = str(action).strip()
        if text:
            steps.append(text)
    if any("latency" in str(signal).lower() for signal in reasoning.get("correlated_signals", [])):
        steps.append(f"kubectl -n {namespace} top pod -l app={service}")
    if historical_matches:
        steps.append("Review historical incidents with similar signature for proven fixes.")

    runbook_id = hashlib.sha1(f"{incident_type}|{root_signal}".encode("utf-8")).hexdigest()
    return {
        "runbook_id": runbook_id,
        "incident_type": incident_type,
        "root_cause_signal": root_signal,
        "steps": dedupe(steps),
    }


def dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def signal_driven_steps(incident: dict, reasoning: dict) -> list[str]:
    snapshot = incident.get("telemetry_snapshot") or {}
    highlights = snapshot.get("metric_highlights") or {}
    signals = [str(item).lower() for item in (incident.get("detector_signals") or incident.get("signals") or [])]
    signals.extend(str(item).lower() for item in (reasoning.get("correlated_signals") or []))
    root_signal = str(reasoning.get("root_cause_signal", "")).lower()
    all_signals = " ".join(signals + [root_signal])
    namespace = str(incident.get("namespace", "default")) or "default"
    service = str(incident.get("service", "unknown-service"))

    steps: list[str] = []

    def has_metric(keyword: str) -> bool:
        return any(keyword in str(name).lower() for name in highlights.keys())

    if any(token in all_signals for token in ("db", "database", "slow_query", "connection_pool", "jdbc", "sql")):
        steps.extend(
            [
                "Inspect dependency/database latency and slow query metrics for spikes.",
                "Inspect dependency connection pool saturation and max-connection limits.",
                f"kubectl -n {namespace} logs deployment/{service} --tail=200 | grep -Ei \"timeout|connection|sql\"",
            ]
        )
    if any(token in all_signals for token in ("consumer_lag", "lag", "queue", "topic", "messag")) or has_metric("messag") or has_metric("queue"):
        steps.extend(
            [
                "Check broker or queue backlog and processing latency on the impacted flow.",
                "Verify consumer/worker concurrency and processing backlog.",
                "Validate producer or publisher throughput against downstream consumption.",
            ]
        )
    if any(token in all_signals for token in ("cpu", "saturation")) or float(snapshot.get("cpu_utilization", 0) or 0) >= 80:
        steps.extend(
            [
                f"kubectl -n {namespace} top pod -l app={service}",
                f"kubectl -n {namespace} describe deployment/{service}",
            ]
        )
    if any(token in all_signals for token in ("memory", "oom", "pressure")) or float(snapshot.get("memory_utilization", 0) or 0) >= 80:
        steps.extend(
            [
                "Check memory working-set trend and OOMKilled events.",
                f"kubectl -n {namespace} get events --sort-by=.lastTimestamp | grep -Ei \"oom|killed|evict\"",
            ]
        )
    if any(token in all_signals for token in ("latency", "timeout", "zscore")):
        steps.extend(
            [
                "Compare current p95 latency vs adaptive baseline for this hour/day window.",
                "Validate upstream/downstream propagation path in topology before remediation.",
            ]
        )
    return dedupe(steps)

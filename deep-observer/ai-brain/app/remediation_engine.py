from __future__ import annotations


def build_remediation_steps(service: str, namespace: str, signals: list[str], incident_type: str) -> list[str]:
    steps: list[str] = []
    if any(signal in {"cpu_saturation", "memory_pressure", "predictive_latency_risk"} for signal in signals):
        steps.append(f"kubectl -n {namespace or 'default'} top pod -l app={service}")
        steps.append(f"kubectl -n {namespace or 'default'} scale deployment/{service} --replicas=3")
    if any(signal in {"error_rate_increase", "log_anomaly"} for signal in signals):
        steps.append(f"kubectl -n {namespace or 'default'} logs deployment/{service} --tail=200")
    if any(signal.startswith("predictive_") for signal in signals) or incident_type == "predictive":
        steps.append(f"kubectl -n {namespace or 'default'} rollout history deployment/{service}")
    steps.append(f"kubectl -n {namespace or 'default'} describe deployment/{service}")
    return dedupe(steps)


def dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        ordered.append(item)
    return ordered

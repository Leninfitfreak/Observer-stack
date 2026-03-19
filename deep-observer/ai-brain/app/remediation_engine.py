from __future__ import annotations


def build_remediation_steps(service: str, namespace: str, signals: list[str], incident_type: str) -> list[str]:
    steps: list[str] = []
    scope = f" in namespace `{namespace}`" if namespace else ""
    if any(signal in {"cpu_saturation", "memory_pressure", "predictive_latency_risk"} for signal in signals):
        steps.append(f"Inspect runtime resource saturation for workloads serving `{service}`{scope}.")
        steps.append(f"Review current replica count and autoscaling state for workloads serving `{service}`{scope}.")
    if any(signal in {"error_rate_increase", "log_anomaly"} for signal in signals):
        steps.append(f"Inspect recent application logs for workloads serving `{service}`{scope}.")
    if any(signal.startswith("predictive_") for signal in signals) or incident_type == "predictive":
        steps.append(f"Review recent rollout or configuration changes affecting `{service}`{scope}.")
    steps.append(f"Inspect workload state and recent events for resources serving `{service}`{scope}.")
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

from typing import Any


def build_causal_chain(context: dict[str, Any]) -> list[str]:
    metrics = context.get("metrics", {})
    k8s = context.get("kubernetes", {})
    traces = context.get("traces", {})
    chain: list[str] = []

    cpu = metrics.get("cpu_usage_cores_5m") or 0
    p95 = metrics.get("latency_p95_s_5m") or 0
    err5 = metrics.get("error_rate_5xx_5m") or 0
    thread_sat = metrics.get("thread_pool_saturation_5m") or 0
    db_sat = metrics.get("db_connection_pool_usage_5m") or 0
    lag = metrics.get("kafka_consumer_lag") or 0
    restarts = k8s.get("pod_restarts_10m") or 0
    throttled = k8s.get("cpu_throttled_rate_5m") or 0

    if cpu > 0.8 or throttled > 0.05:
        chain.append("CPU pressure / throttling increased.")
    if thread_sat > 0.8:
        chain.append("Thread pool saturation detected.")
    if db_sat > 0.8:
        chain.append("DB connection pool saturation detected.")
    if lag > 1000:
        chain.append("Kafka lag buildup detected.")
    if p95 > 0.75:
        chain.append("Request queueing increased p95 latency.")
    if err5 > 0.05:
        chain.append("Error rate rose after latency degradation.")
    if restarts > 0:
        chain.append("Pod restarts amplified instability.")
    if traces.get("longest_critical_path"):
        chain.append(f"Trace critical path hotspot: {traces.get('longest_critical_path')}.")

    if not chain:
        chain.append("No strong multi-signal causal chain detected from current telemetry.")
    return chain


def _confidence(context: dict[str, Any], chain: list[str]) -> float:
    metrics = context.get("metrics", {})
    logs = context.get("logs", {})
    traces = context.get("traces", {})
    missing = 0
    total = 0

    for section in (metrics, logs, traces):
        for _, v in section.items():
            total += 1
            if v is None:
                missing += 1

    coverage = 1.0 if total == 0 else max(0.0, 1 - (missing / total))
    chain_score = min(1.0, len(chain) / 6)
    return round((0.55 * coverage) + (0.45 * chain_score), 3)


def build_rule_based_analysis(context: dict[str, Any]) -> dict[str, Any]:
    metrics = context.get("metrics", {})
    k8s = context.get("kubernetes", {})
    deployment = context.get("deployment", {})
    slo = context.get("slo", {})
    logs = context.get("logs", {})

    chain = build_causal_chain(context)
    confidence = _confidence(context, chain)
    confidence_pct = f"{round(confidence * 100)}%"

    root = "No dominant fault domain identified"
    impact = "Low"
    corrective = []
    preventive = []

    if (metrics.get("error_rate_5xx_5m") or 0) > 0.05:
        root = "Service instability with elevated 5xx error rate"
        impact = "High"
        corrective.append("Scale affected workload and inspect top failing endpoints with trace IDs.")
    if (metrics.get("latency_p95_s_5m") or 0) > 0.75:
        root = "Latency degradation likely from saturation/backpressure"
        impact = "High" if impact != "High" else impact
        corrective.append("Reduce queue pressure: increase replicas or tune concurrency/thread pools.")
    if (k8s.get("oom_killed_10m") or 0) > 0:
        root = "OOM-induced instability in workload pods"
        impact = "High"
        corrective.append("Increase memory limits/requests and inspect heap/off-heap growth.")
    if deployment.get("deployment_changed_last_10m") and impact in ("High", "Medium"):
        corrective.append("Correlate with recent deployment/config diff before rollback.")

    if not corrective:
        corrective.append("Continue monitoring; no immediate mitigation required.")

    preventive.extend(
        [
            "Define recording rules for thread pool/DB pool/Kafka lag and alert on 5m sustained breaches.",
            "Add canary analysis and progressive rollout guardrails before broad deployment.",
            "Continuously track SLO burn-rate and gate high-frequency deploy windows.",
        ]
    )

    missing_observability = []
    if metrics.get("thread_pool_saturation_5m") is None:
        missing_observability.append("thread_pool_saturation metric missing")
    if metrics.get("db_connection_pool_usage_5m") is None:
        missing_observability.append("db_connection_pool_usage metric missing")
    if metrics.get("kafka_consumer_lag") is None:
        missing_observability.append("kafka_consumer_lag metric missing")
    if deployment.get("argocd_deployment_history") == "unavailable_via_current_datasources":
        missing_observability.append("argocd deployment history unavailable in current datasource path")
    if deployment.get("cicd_pipeline_signals") == "unavailable_via_current_datasources":
        missing_observability.append("cicd pipeline signals unavailable in current datasource path")

    risk = {
        "level": "Low",
        "predicted_breach_window": slo.get("predicted_breach_window", "unknown"),
        "error_budget_burn_rate_1h": slo.get("error_budget_burn_rate_1h"),
        "error_budget_burn_rate_24h": slo.get("error_budget_burn_rate_24h"),
    }
    if risk["predicted_breach_window"] == "likely_breach_within_1h":
        risk["level"] = "High"
    elif risk["predicted_breach_window"] == "likely_breach_within_24h":
        risk["level"] = "Medium"

    return {
        "probable_root_cause": root,
        "impact_level": impact,
        "recommended_remediation": " ".join(corrective),
        "confidence_score": confidence_pct,
        "confidence": confidence,
        "causal_chain": chain,
        "corrective_actions": corrective,
        "preventive_hardening": preventive,
        "risk_forecast": risk,
        "deployment_correlation": {
            "within_10m": bool(deployment.get("deployment_changed_last_10m")),
            "flagged": bool(deployment.get("deployment_changed_last_10m")) and impact in ("High", "Medium"),
        },
        "error_log_prediction": {
            "repeated_signatures": logs.get("top_signatures", []),
            "new_signatures_detected": logs.get("new_signatures", []),
        },
        "missing_observability": missing_observability,
        "policy_note": "No auto-remediation applied. Explicit approval required before any change.",
    }

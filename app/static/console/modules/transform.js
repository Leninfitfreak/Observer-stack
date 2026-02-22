export function normalizeSeverity(value) {
  const raw = String(value || '').toLowerCase();
  if (raw.includes('critical')) return 'critical';
  if (raw.includes('degraded') || raw.includes('orange')) return 'degraded';
  if (raw.includes('warning') || raw.includes('medium')) return 'warning';
  if (raw.includes('healthy') || raw.includes('ok') || raw.includes('running')) return 'healthy';
  return 'unknown';
}

export function summarizeNodeStatus(node, serviceMetrics) {
  const svc = serviceMetrics[node.id] || {};
  return {
    p95: Math.round((svc.p95Ms || 0)),
    err: Number(svc.errorPct || 0).toFixed(2),
    cpu: Math.round(svc.cpuPct || 0),
  };
}

export function buildMetricsPoint(snapshot) {
  const m = snapshot?.context?.metrics || {};
  return {
    ts: Date.now(),
    p95Ms: (m.latency_p95_s_5m || 0) * 1000,
    p99Ms: (m.latency_p99_s_5m || 0) * 1000,
    errorPct: (m.error_rate_5xx_5m || 0) * 100,
    rps: m.request_rate_rps_5m || 0,
    cpuPct: (m.cpu_usage_cores_5m || 0) * 100,
    memMb: (m.memory_usage_bytes || 0) / (1024 * 1024),
  };
}

export async function fetchReasoningSnapshot({ namespace, service, severity, timeWindow }) {
  const qs = new URLSearchParams({
    namespace,
    service,
    severity,
    time_window: timeWindow,
  });
  const resp = await fetch(`/api/reasoning/live?${qs.toString()}`);
  if (!resp.ok) {
    const text = await resp.text();
    throw new Error(`HTTP ${resp.status}: ${text.slice(0, 200)}`);
  }
  return resp.json();
}

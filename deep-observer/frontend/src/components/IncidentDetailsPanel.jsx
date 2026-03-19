import { useEffect, useMemo, useState } from "react";
import {
  fetchIncident,
  fetchTimeline,
  runReasoning,
  retryReasoning,
  fetchReasoningHistory,
  fetchReasoningRun,
  fetchCorrelations,
} from "../api";

export default function IncidentDetailsPanel({ incident, serviceHealth, clusterReport, changes, sloStatus, runbooks, observabilityReport }) {
  const [timeline, setTimeline] = useState([]);
  const [activeIncident, setActiveIncident] = useState(null);
  const [reasoningStatus, setReasoningStatus] = useState("");
  const [reasoningError, setReasoningError] = useState("");
  const [reasoningBusy, setReasoningBusy] = useState(false);
  const [reasoningHistory, setReasoningHistory] = useState([]);
  const [selectedRun, setSelectedRun] = useState(null);
  const [correlations, setCorrelations] = useState([]);

  useEffect(() => {
    if (!incident) return;
    fetchTimeline(incident.incident_id)
      .then((payload) => setTimeline(payload.events || []))
      .catch(console.error);
  }, [incident]);

  useEffect(() => {
    if (!incident) {
      setActiveIncident(null);
      setReasoningStatus("");
      setReasoningError("");
      setReasoningBusy(false);
      setReasoningHistory([]);
      setSelectedRun(null);
      setCorrelations([]);
      return;
    }
    setActiveIncident(incident);
    setReasoningStatus(incident.reasoning_status || "");
    setReasoningError(incident.reasoning_error || "");
    setReasoningBusy(false);
  }, [incident]);

  useEffect(() => {
    if (!incident) return;
    fetchReasoningHistory(incident.incident_id)
      .then((payload) => {
        const items = Array.isArray(payload) ? payload : [];
        setReasoningHistory(items);
        setSelectedRun(items[0] || null);
      })
      .catch(console.error);
    fetchCorrelations(incident.incident_id)
      .then((payload) => setCorrelations(Array.isArray(payload) ? payload : []))
      .catch(console.error);
  }, [incident]);

  const chartPoints = useMemo(
    () =>
      timeline
        .filter((event) => Number.isFinite(Number(event?.value)))
        .slice(-8)
        .map((event) => ({
          ...event,
          ts: new Date(event.timestamp).toLocaleTimeString(),
          value: Number(event.value),
        })),
    [timeline],
  );

  const currentIncident = activeIncident || incident;
  if (!currentIncident) {
    return (
      <section className="rounded-3xl border border-white/10 bg-slate-900/60 p-6 text-sm text-slate-400">
        Select an incident to inspect the reasoning summary, charts, timeline, and propagation path.
      </section>
    );
  }

  const reasoning = currentIncident.reasoning;
  const coverage = reasoning?.observability_summary || {};
  const anomalyScore = formatScore(currentIncident.anomaly_score);
  const telemetryEvidence = buildTelemetryEvidence(currentIncident);
  const impactedServices = formatImpactedServices(currentIncident.impacts);
  const derivedStatus = reasoningStatus || currentIncident.reasoning_status || (reasoning ? "completed" : "not_generated");
  const canRunReasoning = ["not_generated", "failed", "completed"].includes(derivedStatus) && !reasoningBusy;
  const confidenceDetails = reasoning?.confidence_explanation || {};
  const runDetail = selectedRun && selectedRun.reasoning_run_id ? selectedRun : null;

  const refreshIncident = async () => {
    const updated = await fetchIncident(currentIncident.incident_id);
    if (updated) {
      setActiveIncident(updated);
      setReasoningStatus(updated.reasoning_status || derivedStatus);
      setReasoningError(updated.reasoning_error || "");
      fetchReasoningHistory(updated.incident_id)
        .then((payload) => {
          const items = Array.isArray(payload) ? payload : [];
          setReasoningHistory(items);
          setSelectedRun(items[0] || null);
        })
        .catch(console.error);
      fetchCorrelations(updated.incident_id)
        .then((payload) => setCorrelations(Array.isArray(payload) ? payload : []))
        .catch(console.error);
    }
    return updated;
  };

  const pollForReasoning = async (attempt = 0) => {
    if (attempt > 10) return;
    const updated = await refreshIncident();
    const status = updated?.reasoning_status || derivedStatus;
    if (status === "completed" || status === "failed") return;
    setTimeout(() => {
      pollForReasoning(attempt + 1).catch(() => {});
    }, 3000);
  };

  const handleRunReasoning = async () => {
    if (!currentIncident) return;
    setReasoningBusy(true);
    setReasoningStatus("running");
    setReasoningError("");
    try {
      const response =
        derivedStatus === "not_generated"
          ? await runReasoning(currentIncident.incident_id)
          : await retryReasoning(currentIncident.incident_id);
      setReasoningStatus(response?.status || "pending");
      await pollForReasoning(0);
    } catch (err) {
      setReasoningStatus("failed");
      setReasoningError(err?.message || "Reasoning request failed");
    } finally {
      setReasoningBusy(false);
    }
  };

  const handleSelectRun = async (run) => {
    if (!run || !currentIncident) {
      setSelectedRun(null);
      return;
    }
    try {
      const detail = await fetchReasoningRun(currentIncident.incident_id, run.reasoning_run_id);
      setSelectedRun(detail || run);
    } catch {
      setSelectedRun(run);
    }
  };

  return (
    <section className="space-y-4">
      <div className="rounded-3xl border border-white/10 bg-slate-900/60 p-6">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.3em] text-cyan-300">Incident Details Panel</p>
            <h2 className="mt-2 text-2xl font-semibold text-white">{currentIncident.service}</h2>
            <p className="mt-1 text-sm text-slate-400">
              {currentIncident.cluster} / {currentIncident.namespace} / {new Date(currentIncident.timestamp).toLocaleString()}
            </p>
          </div>
          <div className="rounded-3xl border border-white/10 bg-slate-950/80 px-4 py-3 text-right">
            <div className="text-xs uppercase tracking-[0.3em] text-slate-400">Anomaly Score</div>
            <div className="mt-1 text-2xl font-semibold text-white">{anomalyScore}</div>
          </div>
        </div>

        <div className="mt-6 grid gap-4 lg:grid-cols-2">
          <InfoCard title="Root Cause Service" value={reasoning?.root_cause_service || currentIncident.root_cause_entity || "Pending"} />
          <InfoCard title="Root Cause Signal" value={reasoning?.root_cause_signal || toList(currentIncident.signals).join(", ")} />
          <InfoCard title="Customer Impact" value={reasoning?.customer_impact || reasoning?.impact_assessment || "Pending"} />
          <InfoCard title="Observability Score" value={`${reasoning?.observability_score ?? coverage.observability_score ?? 0}%`} />
          <InfoCard title="Service Health Score" value={`${formatScore(serviceHealth?.health_score ?? 0)} / 100`} />
          <InfoCard title="Root Cause Confidence" value={formatScore(reasoning?.confidence_score ?? currentIncident.predictive_confidence ?? 0)} />
          <InfoCard title="Incident Type" value={currentIncident.incident_type || "observed"} />
        </div>

        <div className="mt-6 rounded-3xl border border-white/10 bg-slate-950/80 p-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <h3 className="text-sm font-semibold uppercase tracking-[0.3em] text-slate-400">AI Reasoning</h3>
              <p className="mt-1 text-xs text-slate-500">
                AI reasoning runs on demand and may consume LLM tokens.
              </p>
            </div>
            <button
              type="button"
              onClick={handleRunReasoning}
              disabled={!canRunReasoning}
              className={`rounded-full px-4 py-2 text-xs font-semibold uppercase tracking-[0.3em] ${
                canRunReasoning ? "bg-cyan-500 text-slate-950 hover:bg-cyan-400" : "bg-slate-700 text-slate-300"
              }`}
            >
              {derivedStatus === "failed" ? "Retry Reasoning" : derivedStatus === "completed" ? "Re-run Reasoning" : "Run Reasoning"}
            </button>
          </div>
          <div className="mt-3 text-sm text-slate-300">
            Status: <span className="font-semibold text-white">{formatReasoningStatus(derivedStatus, reasoningBusy)}</span>
          </div>
          {reasoningError ? (
            <p className="mt-2 text-xs text-rose-300">Last error: {reasoningError}</p>
          ) : null}
        </div>

        <div className="mt-6 grid gap-6 xl:grid-cols-2">
          <div className="rounded-3xl border border-white/10 bg-slate-950/70 p-4">
            <h3 className="text-sm font-semibold uppercase tracking-[0.3em] text-slate-400">Confidence Explanation</h3>
            <div className="mt-3 text-sm text-slate-200">
              <p>Score: {formatScore(confidenceDetails.score ?? reasoning?.confidence_score ?? 0)}</p>
              <p>Level: {toText(confidenceDetails.level || "unknown")}</p>
              <p className="mt-2 text-slate-400">{toText(confidenceDetails.explanation_text || "No explanation yet.")}</p>
            </div>
            <div className="mt-4 grid gap-3 lg:grid-cols-2">
              <div>
                <p className="text-xs font-semibold uppercase tracking-[0.3em] text-slate-500">Supporting Factors</p>
                <ul className="mt-2 space-y-1 text-sm text-slate-200">
                  {Array.isArray(confidenceDetails.supporting_factors) && confidenceDetails.supporting_factors.length
                    ? confidenceDetails.supporting_factors.map((item) => <li key={item}>- {toText(item)}</li>)
                    : <li className="text-slate-500">No data</li>}
                </ul>
              </div>
              <div>
                <p className="text-xs font-semibold uppercase tracking-[0.3em] text-slate-500">Weakening Factors</p>
                <ul className="mt-2 space-y-1 text-sm text-slate-200">
                  {Array.isArray(confidenceDetails.weakening_factors) && confidenceDetails.weakening_factors.length
                    ? confidenceDetails.weakening_factors.map((item) => <li key={item}>- {toText(item)}</li>)
                    : <li className="text-slate-500">No data</li>}
                </ul>
              </div>
            </div>
          </div>

          <div className="rounded-3xl border border-white/10 bg-slate-950/70 p-4">
            <h3 className="text-sm font-semibold uppercase tracking-[0.3em] text-slate-400">Reasoning History</h3>
            <div className="mt-3 space-y-2 text-sm text-slate-200">
              {reasoningHistory.length ? reasoningHistory.map((run) => (
                <button
                  key={run.reasoning_run_id}
                  type="button"
                  onClick={() => handleSelectRun(run)}
                  className={`w-full rounded-2xl border border-white/10 px-3 py-2 text-left ${
                    runDetail?.reasoning_run_id === run.reasoning_run_id ? "bg-slate-800/70" : "bg-slate-900/50"
                  }`}
                >
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <span className="text-xs text-slate-400">{new Date(run.started_at).toLocaleString()}</span>
                    <span className="text-xs uppercase tracking-[0.2em] text-cyan-300">{toText(run.status)}</span>
                  </div>
                  <div className="mt-1 text-sm text-white">{toText(run.summary || "No summary")}</div>
                  <div className="mt-1 text-xs text-slate-400">
                    {toText(run.provider)} / {toText(run.model)} / {toText(run.trigger_type)}
                  </div>
                </button>
              )) : (
                <p className="text-slate-500">No reasoning history yet.</p>
              )}
            </div>
            {runDetail ? (
              <div className="mt-4 rounded-2xl border border-white/10 bg-slate-900/60 p-3 text-sm text-slate-200">
                <p className="text-xs uppercase tracking-[0.3em] text-slate-500">Selected Run</p>
                <p className="mt-2">{toText(runDetail.summary || "No summary")}</p>
                <p className="mt-2 text-xs text-slate-400">Confidence: {formatScore(runDetail.root_cause_confidence ?? 0)}</p>
              </div>
            ) : null}
          </div>
        </div>

        <div className="mt-6 rounded-3xl border border-white/10 bg-slate-950/70 p-4">
          <h3 className="text-sm font-semibold uppercase tracking-[0.3em] text-slate-400">Related Incidents</h3>
          <div className="mt-3 space-y-2 text-sm text-slate-200">
            {correlations.length ? correlations.map((item) => (
              <div key={item.incident_id} className="rounded-2xl border border-white/10 bg-slate-900/60 p-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span className="text-xs text-slate-400">{new Date(item.timestamp).toLocaleString()}</span>
                  <span className="text-xs uppercase tracking-[0.2em] text-cyan-300">{formatScore(item.correlation_score)}</span>
                </div>
                <div className="mt-1 text-sm text-white">{toText(item.root_cause_summary || item.incident_id)}</div>
                <div className="mt-1 text-xs text-slate-400">{toText(item.correlation_reason || "related signal pattern")}</div>
              </div>
            )) : (
              <p className="text-slate-500">No related incidents found yet.</p>
            )}
          </div>
        </div>

        <div className="mt-6 grid gap-6 xl:grid-cols-[1.1fr_0.9fr]">
          <RichSection
            title="Incident Summary"
            content={`${currentIncident.incident_type || "observed"} incident on ${currentIncident.service} with anomaly score ${anomalyScore}.`}
          />
          <RichSection title="Reasoning Summary" content={reasoning?.root_cause || "Reasoning pending"} />
          <RichList title="Signals Detected" items={currentIncident.signals || []} />
          <RichList title="Causal Propagation Chain" items={reasoning?.causal_chain || []} />
          <RichList title="Suggested Actions" items={reasoning?.recommended_actions || currentIncident.remediation_suggestions || []} />
          <RichList title="Propagation Path" items={reasoning?.propagation_path || currentIncident.dependency_chain || []} />
          <RichList title="Impacted Services" items={impactedServices} />
          <RichList title="Missing Telemetry Signals" items={reasoning?.missing_telemetry_signals || []} />
          <RichList title="Telemetry Evidence" items={telemetryEvidence} />
        </div>

        <div className="mt-6 grid gap-4 lg:grid-cols-2">
          <InfoCard title="Cluster At-Risk Services" value={clusterReport?.at_risk_services ?? 0} />
          <InfoCard title="Missing Resource Limits" value={clusterReport?.missing_resource_limits ?? 0} />
        </div>

        <div className="mt-6 grid gap-6 xl:grid-cols-2">
          <RichList
            title="Change Timeline"
            items={(Array.isArray(changes) ? changes : [])
              .slice(0, 5)
              .map((item) => `${new Date(item.timestamp).toLocaleString()} - ${item.change_type} ${item.resource_type}/${item.resource_name}`)}
          />
          <RichList
            title="SLO Status"
            items={(Array.isArray(sloStatus) ? sloStatus : [])
              .map((item) => `${item.slo_type}: ${item.slo_status} (${Number(item.error_budget_remaining || 0).toFixed(1)}% budget)`)
            }
          />
          <RichList
            title="Runbook Suggestions"
            items={(Array.isArray(runbooks) ? runbooks : [])
              .slice(0, 3)
              .flatMap((runbook) => (Array.isArray(runbook.steps) ? runbook.steps.slice(0, 4) : []))
            }
          />
          <RichSection
            title="Observability Coverage Score"
            content={`Score: ${Number(observabilityReport?.observability_coverage_score ?? 0).toFixed(2)} | Traces: ${observabilityReport?.services_with_traces ?? 0}/${observabilityReport?.services_discovered ?? 0} | Metrics: ${observabilityReport?.services_with_metrics ?? 0}/${observabilityReport?.services_discovered ?? 0} | Logs: ${observabilityReport?.services_with_logs ?? 0}/${observabilityReport?.services_discovered ?? 0}`}
          />
        </div>

        <div className="mt-6 rounded-3xl border border-white/10 bg-slate-950/70 p-4">
          <div className="mb-3 flex items-center justify-between">
            <h3 className="text-sm font-semibold uppercase tracking-[0.3em] text-slate-400">Telemetry Charts</h3>
            <span className="text-xs text-slate-500">Timeline-derived values</span>
          </div>
          <div className="grid grid-cols-8 items-end gap-3">
            {chartPoints.map((point, index) => (
              <div key={`${point.kind}-${index}`} className="flex flex-col items-center gap-2">
                <div
                  className="w-full rounded-t-2xl bg-gradient-to-t from-cyan-500 to-orange-400"
                  style={{ height: `${Math.max(16, Math.min(160, point.value * 2))}px` }}
                />
                <span className="text-[10px] text-slate-500">{point.ts}</span>
              </div>
            ))}
          </div>
        </div>
      </div>

      <div className="rounded-3xl border border-white/10 bg-slate-900/60 p-6">
        <h3 className="text-lg font-semibold text-white">Incident Timeline</h3>
        <div className="mt-4 space-y-3">
          {timeline.map((event, index) => (
            <div key={`${event.kind}-${event.timestamp}-${index}`} className="rounded-2xl border border-white/10 bg-slate-950/70 p-4">
              <div className="flex items-center justify-between gap-4">
                <span className="text-sm font-medium text-white">{toText(event.title)}</span>
                <span className="text-xs uppercase tracking-[0.3em] text-slate-500">{toText(event.kind)}</span>
              </div>
              <p className="mt-2 text-sm text-slate-300">{toText(event.details)}</p>
              <p className="mt-2 text-xs text-slate-500">
                {new Date(event.timestamp).toLocaleString()} - {toText(event.entity)}
              </p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

function InfoCard({ title, value }) {
  return (
    <div className="rounded-3xl border border-white/10 bg-slate-950/70 p-4">
      <p className="text-xs font-semibold uppercase tracking-[0.3em] text-slate-500">{title}</p>
      <p className="mt-2 text-base text-white">{toText(value)}</p>
    </div>
  );
}

function RichSection({ title, content }) {
  return (
    <div className="rounded-3xl border border-white/10 bg-slate-950/70 p-4">
      <h3 className="text-sm font-semibold uppercase tracking-[0.3em] text-slate-400">{title}</h3>
      <p className="mt-3 text-sm leading-6 text-slate-200">{toText(content)}</p>
    </div>
  );
}

function RichList({ title, items }) {
  const normalizedItems = toList(items);
  return (
    <div className="rounded-3xl border border-white/10 bg-slate-950/70 p-4">
      <h3 className="text-sm font-semibold uppercase tracking-[0.3em] text-slate-400">{title}</h3>
      <ul className="mt-3 space-y-2 text-sm text-slate-200">
        {normalizedItems.length
          ? normalizedItems.map((item) => <li key={item}>- {toText(item)}</li>)
          : <li className="text-slate-500">No data</li>}
      </ul>
    </div>
  );
}

function formatScore(value) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return "0.00";
  return numeric.toFixed(2);
}

function formatReasoningStatus(status, busy) {
  if (busy) return "Running...";
  switch (status) {
    case "pending":
      return "Pending";
    case "running":
      return "Running...";
    case "completed":
      return "Completed";
    case "failed":
      return "Failed";
    case "not_generated":
    default:
      return "Not generated";
  }
}

function toList(value) {
  if (Array.isArray(value)) return value.map((item) => toText(item));
  if (value === null || value === undefined || value === "") return [];
  return [toText(value)];
}

function toText(value) {
  if (value === null || value === undefined) return "";
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}

function formatImpactedServices(value) {
  if (!Array.isArray(value)) return [];
  return value
    .map((impact) => {
      if (typeof impact === "string") return impact;
      if (!impact || typeof impact !== "object") return "";
      const service = toText(impact.service);
      const impactType = toText(impact.impact_type || "impact");
      const score = Number(impact.impact_score);
      if (!service) return "";
      if (Number.isFinite(score)) {
        return `${service} (${impactType}, score ${score.toFixed(2)})`;
      }
      return `${service} (${impactType})`;
    })
    .filter(Boolean);
}

function buildTelemetryEvidence(incident) {
  const snapshot = incident?.telemetry_snapshot || {};
  const lines = [];
  const requestCount = Number(snapshot.request_count || 0);
  const errorRate = Number(snapshot.error_rate || 0);
  const p95 = Number(snapshot.p95_latency_ms || 0);
  const cpu = Number(snapshot.cpu_utilization || 0);
  const memory = Number(snapshot.memory_utilization || 0);
  const logCount = Number(snapshot.log_count || 0);
  const traceCount = Array.isArray(snapshot.trace_ids) ? snapshot.trace_ids.length : 0;
  if (Number.isFinite(requestCount)) lines.push(`Requests observed: ${requestCount}`);
  if (Number.isFinite(errorRate)) lines.push(`Error rate: ${errorRate.toFixed(4)}`);
  if (Number.isFinite(p95)) lines.push(`P95 latency: ${p95.toFixed(2)} ms`);
  if (Number.isFinite(cpu)) lines.push(`CPU utilization: ${cpu.toFixed(2)}`);
  if (Number.isFinite(memory)) lines.push(`Memory utilization: ${memory.toFixed(2)}`);
  if (Number.isFinite(logCount)) lines.push(`Log events: ${logCount}`);
  lines.push(`Trace IDs sampled: ${traceCount}`);
  const highlights = snapshot.metric_highlights && typeof snapshot.metric_highlights === "object" ? snapshot.metric_highlights : {};
  const metricHighlights = Object.entries(highlights)
    .slice(0, 5)
    .map(([name, value]) => `${name}: ${Number(value).toFixed(4)}`);
  return lines.concat(metricHighlights);
}
